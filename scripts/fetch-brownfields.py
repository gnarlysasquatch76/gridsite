"""
Fetch EPA brownfield sites from FRS national CSV download and convert to GeoJSON.

Downloads the FRS national single-file CSV (zipped), filters for ACRES
(brownfield assessment) program facilities with valid lat/lng, deduplicates
by registry_id, and outputs to public/data/epa-brownfields.geojson.
"""

import csv
import io
import json
import os
import urllib.request
import zipfile

SCRIPT_DIR = os.path.dirname(__file__)
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "epa-brownfields.geojson")
FRS_URL = "https://ordsext.epa.gov/FLA/www3/state_files/national_single.zip"

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}


def main():
    print("Downloading FRS national CSV (~170 MB zip)...")
    print("  URL: " + FRS_URL)

    req = urllib.request.Request(FRS_URL, headers={"User-Agent": "GridSite/1.0"})
    response = urllib.request.urlopen(req, timeout=300)
    zip_data = response.read()
    print("  Downloaded: {:.1f} MB".format(len(zip_data) / 1024 / 1024))

    print("Extracting and filtering brownfield sites...")
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not csv_names:
        print("ERROR: No CSV file found in zip")
        return
    print("  CSV file: " + csv_names[0])

    csv_data = zf.read(csv_names[0]).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(csv_data))

    # Find column names (they vary by file version)
    fieldnames = reader.fieldnames
    print("  Columns: " + str(len(fieldnames)))

    # Identify key columns
    lat_col = None
    lon_col = None
    name_col = None
    state_col = None
    city_col = None
    county_col = None
    registry_col = None
    interest_col = None
    addr_col = None

    for col in fieldnames:
        cl = col.upper().strip()
        if "LATITUDE83" in cl or cl == "LATITUDE83":
            lat_col = col
        elif "LONGITUDE83" in cl or cl == "LONGITUDE83":
            lon_col = col
        elif cl in ("PRIMARY_NAME", "SITE_NAME"):
            name_col = col
        elif cl == "STATE_CODE":
            state_col = col
        elif cl == "CITY_NAME":
            city_col = col
        elif cl == "COUNTY_NAME":
            county_col = col
        elif cl == "REGISTRY_ID":
            registry_col = col
        elif cl == "INTEREST_TYPES" or cl == "INTEREST_TYPE":
            interest_col = col
        elif cl == "LOCATION_ADDRESS":
            addr_col = col

    # Fallback: try other lat/lon patterns
    if not lat_col:
        for col in fieldnames:
            cl = col.upper().strip()
            if "LAT" in cl and "LATITUDE" in cl:
                lat_col = col
                break
    if not lon_col:
        for col in fieldnames:
            cl = col.upper().strip()
            if "LON" in cl and "LONGITUDE" in cl:
                lon_col = col
                break

    print("  Lat column: " + str(lat_col))
    print("  Lon column: " + str(lon_col))
    print("  Name column: " + str(name_col))
    print("  State column: " + str(state_col))
    print("  Interest column: " + str(interest_col))

    if not lat_col or not lon_col:
        print("ERROR: Could not find lat/lon columns")
        print("  Available columns: " + ", ".join(fieldnames[:20]))
        return

    # Filter for brownfield sites with valid coordinates
    sites = {}  # keyed by registry_id to deduplicate
    total_rows = 0
    brownfield_rows = 0

    for row in reader:
        total_rows += 1
        if total_rows % 500000 == 0:
            print("  Processed {:,} rows...".format(total_rows))

        # Check if this is a brownfield/ACRES site
        interest = row.get(interest_col, "") if interest_col else ""
        is_brownfield = False
        if interest:
            interest_upper = interest.upper()
            if "BROWNFIELD" in interest_upper or "ACRES" in interest_upper:
                is_brownfield = True

        if not is_brownfield:
            continue

        brownfield_rows += 1

        # Get coordinates
        lat_str = row.get(lat_col, "").strip()
        lon_str = row.get(lon_col, "").strip()
        if not lat_str or not lon_str:
            continue

        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            continue

        # Skip invalid coordinates
        if lat == 0 or lon == 0:
            continue
        if lat < 17 or lat > 72:  # US bounds
            continue
        if lon > -60 or lon < -180:  # Outside US longitude range
            continue

        state = row.get(state_col, "").strip() if state_col else ""
        # Only US states
        if state and state not in US_STATES:
            continue

        reg_id = row.get(registry_col, "").strip() if registry_col else str(brownfield_rows)

        # Deduplicate by registry_id (keep first occurrence)
        if reg_id in sites:
            continue

        sites[reg_id] = {
            "name": row.get(name_col, "Unknown").strip() if name_col else "Unknown",
            "state": state,
            "city": row.get(city_col, "").strip() if city_col else "",
            "county": row.get(county_col, "").strip() if county_col else "",
            "address": row.get(addr_col, "").strip() if addr_col else "",
            "latitude": lat,
            "longitude": lon,
            "registry_id": reg_id,
        }

    print("  Total rows: {:,}".format(total_rows))
    print("  Brownfield rows: {:,}".format(brownfield_rows))
    print("  Unique sites with coords: {:,}".format(len(sites)))

    # Build GeoJSON
    features = []
    for site in sites.values():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [site["longitude"], site["latitude"]],
            },
            "properties": {
                "name": site["name"],
                "state": site["state"],
                "city": site["city"],
                "county": site["county"],
                "address": site["address"],
                "registry_id": site["registry_id"],
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f)

    file_size = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print("")
    print("Output: " + OUTPUT_FILE)
    print("  Sites: {:,}".format(len(features)))
    print("  File size: {:.1f} MB".format(file_size))

    # State distribution
    state_counts = {}
    for site in sites.values():
        st = site["state"] or "??"
        state_counts[st] = state_counts.get(st, 0) + 1
    top_states = sorted(state_counts.items(), key=lambda x: -x[1])[:10]
    print("  Top states: " + ", ".join("{} ({})".format(s, c) for s, c in top_states))


if __name__ == "__main__":
    main()
