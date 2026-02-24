"""
Process EIA-860 generator data into GeoJSON for GridSite map.

Reads Operating and Retired sheets from the EIA Excel file,
aggregates generators by plant, filters to >= 50 MW nameplate capacity,
and writes a GeoJSON FeatureCollection.
"""

import json
import os
import openpyxl

INPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "december_generator2025.xlsx")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "public", "data", "power-plants.geojson")

# Column indices (0-based) per sheet — these differ between sheets
COLUMNS = {
    "Operating": {
        "entity_id": 0,
        "entity_name": 1,
        "plant_id": 2,
        "plant_name": 3,
        "state": 6,
        "nameplate_mw": 12,
        "technology": 15,
        "energy_source": 16,
        "planned_retirement_month": 20,
        "planned_retirement_year": 21,
        "status": 22,
        "latitude": 35,
        "longitude": 36,
    },
    "Retired": {
        "entity_id": 0,
        "entity_name": 1,
        "plant_id": 2,
        "plant_name": 3,
        "state": 6,
        "nameplate_mw": 12,
        "technology": 15,
        "energy_source": 16,
        "retirement_month": 20,
        "retirement_year": 21,
        "latitude": 24,
        "longitude": 25,
    },
}

HEADER_ROWS = 3  # title row, blank row, column names


def safe_float(val):
    """Convert a value to float, returning None if not possible."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    """Convert a value to int, returning None if not possible."""
    f = safe_float(val)
    if f is None:
        return None
    return int(f)


def format_retirement_date(month, year):
    """Format month/year into YYYY-MM string, or None."""
    y = safe_int(year)
    m = safe_int(month)
    if y is None:
        return None
    if m is not None:
        return "{:04d}-{:02d}".format(y, m)
    return "{:04d}".format(y)


def read_sheet(wb, sheet_name, sheet_type):
    """
    Read a sheet and return a dict of plants keyed by plant_id.
    Each plant accumulates: total_mw, generators list (for fuel tracking),
    and metadata from the first generator encountered.
    """
    ws = wb[sheet_name]
    cols = COLUMNS[sheet_type]
    plants = {}

    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
        if row_idx < HEADER_ROWS:
            continue

        plant_id = row[cols["plant_id"]]
        if plant_id is None:
            continue

        lat = safe_float(row[cols["latitude"]])
        lng = safe_float(row[cols["longitude"]])
        mw = safe_float(row[cols["nameplate_mw"]])

        # Skip rows with missing coordinates or capacity
        if lat is None or lng is None:
            continue
        if mw is None:
            mw = 0.0

        plant_name = str(row[cols["plant_name"]] or "").strip()
        state = str(row[cols["state"]] or "").strip()
        technology = str(row[cols["technology"]] or "").strip()
        energy_source = str(row[cols["energy_source"]] or "").strip()
        entity_id = safe_int(row[cols["entity_id"]])
        entity_name = str(row[cols["entity_name"]] or "").strip()

        # Determine status and planned retirement
        planned_retirement = None
        if sheet_type == "Operating":
            ret_month = row[cols["planned_retirement_month"]]
            ret_year = row[cols["planned_retirement_year"]]
            planned_retirement = format_retirement_date(ret_month, ret_year)
            status = "retiring" if planned_retirement else "operating"
        else:
            ret_month = row[cols["retirement_month"]]
            ret_year = row[cols["retirement_year"]]
            planned_retirement = format_retirement_date(ret_month, ret_year)
            status = "retired"

        # Use a composite key: plant_id + sheet_type to keep operating and
        # retired entries for the same plant separate
        key = (plant_id, sheet_type)

        if key not in plants:
            plants[key] = {
                "plant_id": plant_id,
                "plant_name": plant_name,
                "state": state,
                "latitude": lat,
                "longitude": lng,
                "total_mw": 0.0,
                "status": status,
                "planned_retirement_date": planned_retirement,
                "generators": [],
                "entities": {},  # entity_id -> {name, mw}
            }

        plant = plants[key]
        plant["total_mw"] += mw
        plant["generators"].append({
            "mw": mw,
            "technology": technology,
            "energy_source": energy_source,
        })

        # Track entity MW to find dominant owner/operator
        if entity_id is not None:
            if entity_id not in plant["entities"]:
                plant["entities"][entity_id] = {"name": entity_name, "mw": 0.0}
            plant["entities"][entity_id]["mw"] += mw

        # If any generator on an operating plant has a retirement date,
        # flag the whole plant as retiring
        if status == "retiring" and plant["status"] == "operating":
            plant["status"] = "retiring"
            plant["planned_retirement_date"] = planned_retirement


    return plants


def dominant_fuel(generators):
    """Return the technology of the generator(s) contributing the most MW."""
    fuel_mw = {}
    for g in generators:
        tech = g["technology"] or g["energy_source"]
        fuel_mw[tech] = fuel_mw.get(tech, 0.0) + g["mw"]
    if not fuel_mw:
        return "Unknown"
    return max(fuel_mw, key=fuel_mw.get)


def dominant_entity(entities):
    """Return (entity_id, entity_name) of the entity contributing the most MW."""
    if not entities:
        return None, ""
    best_id = max(entities, key=lambda eid: entities[eid]["mw"])
    return best_id, entities[best_id]["name"]


def main():
    print("Reading " + INPUT_FILE)
    wb = openpyxl.load_workbook(INPUT_FILE, read_only=True)

    all_plants = {}

    # Process Operating sheet
    print("Processing Operating sheet...")
    operating = read_sheet(wb, "Operating", "Operating")
    all_plants.update(operating)
    print("  Plants from Operating: " + str(len(operating)))

    # Process Retired sheet
    print("Processing Retired sheet...")
    retired = read_sheet(wb, "Retired", "Retired")
    all_plants.update(retired)
    print("  Plants from Retired: " + str(len(retired)))

    wb.close()

    # Filter to >= 50 MW and build GeoJSON features
    features = []
    skipped = 0
    for plant in all_plants.values():
        total = round(plant["total_mw"], 1)
        if total < 50:
            skipped += 1
            continue

        eid, ename = dominant_entity(plant["entities"])

        props = {
            "plant_name": plant["plant_name"],
            "state": plant["state"],
            "latitude": plant["latitude"],
            "longitude": plant["longitude"],
            "total_capacity_mw": total,
            "fuel_type": dominant_fuel(plant["generators"]),
            "status": plant["status"],
            "owner_name": ename,
            "utility_id": eid,
        }
        if plant["planned_retirement_date"]:
            props["planned_retirement_date"] = plant["planned_retirement_date"]

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [plant["longitude"], plant["latitude"]],
            },
            "properties": props,
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f, indent=2)

    print("")
    print("Done!")
    print("  Total plants (all sizes): " + str(len(all_plants)))
    print("  Plants < 50 MW (skipped): " + str(skipped))
    print("  Plants >= 50 MW (output):  " + str(len(features)))

    # Breakdown by status
    status_counts = {}
    for feat in features:
        s = feat["properties"]["status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    for s in sorted(status_counts):
        print("    " + s + ": " + str(status_counts[s]))

    print("  Output: " + OUTPUT_FILE)


if __name__ == "__main__":
    main()
