"""
Score retired/retiring power plants for data center adaptive reuse potential.

Reads power-plants.geojson and substations.geojson, scores each retired/retiring
plant (>= 50 MW) on a 0-100 composite scale per ARCHITECTURE.md, and outputs
the top 100 sites to scored-sites.geojson.

Scoring model (5 dimensions, weighted):
  Power Access      (30%) - substation proximity, plant capacity, interconnection voltage
  Grid Capacity     (20%) - plant MW as proxy for grid headroom, substation line count
  Site Characteristics (20%) - fuel type reuse suitability, capacity scale
  Connectivity      (15%) - proximity to population centers (lat-based heuristic)
  Risk Factors      (15%) - fuel type contamination risk, retirement recency
"""

import json
import math
import os

SCRIPT_DIR = os.path.dirname(__file__)
PLANTS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "power-plants.geojson")
SUBSTATIONS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "substations.geojson")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "scored-sites.geojson")

TOP_N = 100


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in miles."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def clamp(val, lo=0.0, hi=100.0):
    return max(lo, min(hi, val))


# ── Dimension scorers ──────────────────────────────────────────────────────


def score_power_access(plant, nearest_sub):
    """
    30% weight. Based on:
    - Distance to nearest 345kV+ substation (closer = better)
    - Plant's own nameplate capacity (higher = better existing interconnection)
    - Nearest substation voltage (higher = better)
    """
    dist = nearest_sub["distance_miles"]
    max_volt = nearest_sub["max_volt"]
    capacity = plant["total_capacity_mw"]

    # Distance score: 100 at 0 mi, 0 at 50+ mi (linear decay)
    dist_score = clamp(100 - (dist * 2))

    # Capacity score: existing interconnection capacity is valuable
    # 100 at >= 2000 MW, scales linearly from 50 MW
    cap_score = clamp((capacity - 50) / 1950 * 100)

    # Voltage bonus: 345=base, 500=good, 765=great
    volt_score = 60
    if max_volt >= 765:
        volt_score = 100
    elif max_volt >= 500:
        volt_score = 85
    elif max_volt >= 345:
        volt_score = 70

    return dist_score * 0.50 + cap_score * 0.30 + volt_score * 0.20


def score_grid_capacity(plant, nearest_sub):
    """
    20% weight. Based on:
    - Plant capacity as proxy for existing grid headroom
    - Number of transmission lines at nearest substation
    """
    capacity = plant["total_capacity_mw"]
    lines = nearest_sub.get("lines") or 0

    # Capacity proxy: larger plant = more grid infrastructure already present
    cap_score = clamp((capacity - 50) / 2950 * 100)  # 0 at 50MW, 100 at 3000MW

    # Lines score: more connections = more grid flexibility
    # Typically 2-12 lines; score 100 at 8+
    lines_score = clamp(lines / 8 * 100)

    return cap_score * 0.60 + lines_score * 0.40


def score_site_characteristics(plant):
    """
    20% weight. Based on:
    - Fuel type suitability for structural reuse
    - Capacity scale (larger sites = more developable land)
    """
    fuel = plant["fuel_type"]
    capacity = plant["total_capacity_mw"]

    # Fuel type reuse suitability scores
    # Coal/gas plants have large flat footprints, heavy-duty foundations, water access
    fuel_scores = {
        "Conventional Steam Coal": 90,
        "Natural Gas Fired Combined Cycle": 95,
        "Natural Gas Fired Combustion Turbine": 80,
        "Natural Gas Steam Turbine": 85,
        "Nuclear": 50,  # Decommissioning complexity
        "Petroleum Liquids": 70,
        "Petroleum Coke": 70,
        "Coal Integrated Gasification Combined Cycle": 80,
        "Other Gases": 65,
        "Other Waste Biomass": 55,
        "Wood/Wood Waste Biomass": 55,
        "Municipal Solid Waste": 45,
        "Landfill Gas": 40,
        "Conventional Hydroelectric": 30,  # Not easily repurposed
        "Onshore Wind Turbine": 20,  # Distributed, no central structure
        "Solar Photovoltaic": 25,
        "Geothermal": 35,
        "All Other": 50,
    }
    fuel_score = fuel_scores.get(fuel, 50)

    # Scale score: larger sites have more room for data center campus
    scale_score = clamp((capacity - 50) / 1450 * 100)  # 100 at 1500 MW

    return fuel_score * 0.60 + scale_score * 0.40


def score_connectivity(plant):
    """
    15% weight. Heuristic based on:
    - Proximity to population centers (using latitude/longitude as a rough proxy)
    - Lower 48 population density tends to be higher east of -100 longitude
      and between 30-45 latitude
    """
    lat = plant["latitude"]
    lon = plant["longitude"]

    # Longitude score: eastern US (more fiber, more POPs)
    # -70 (East Coast) = 100, -120 (West Coast) = 40, further west = lower
    lon_score = clamp(100 - (lon + 70) * -1.2) if lon < -70 else 100
    lon_score = clamp(lon_score)

    # Latitude score: mid-latitudes (30-43) are population-dense corridor
    if 33 <= lat <= 43:
        lat_score = 90
    elif 28 <= lat <= 48:
        lat_score = 70
    else:
        lat_score = 40

    return lon_score * 0.60 + lat_score * 0.40


def score_risk_factors(plant):
    """
    15% weight. Based on:
    - Fuel type contamination risk (coal ash, nuclear waste, etc.)
    - Status: retiring (still operating) is lower risk than already retired
    """
    fuel = plant["fuel_type"]
    status = plant["status"]

    # Contamination risk (lower risk = higher score)
    contamination_scores = {
        "Conventional Steam Coal": 45,  # Coal ash ponds
        "Coal Integrated Gasification Combined Cycle": 50,
        "Nuclear": 20,  # Long decommissioning, NRC oversight
        "Petroleum Liquids": 55,
        "Petroleum Coke": 50,
        "Municipal Solid Waste": 40,
        "Other Waste Biomass": 50,
        "Landfill Gas": 45,
        "Natural Gas Fired Combined Cycle": 85,
        "Natural Gas Fired Combustion Turbine": 85,
        "Natural Gas Steam Turbine": 80,
        "Wood/Wood Waste Biomass": 70,
        "Other Gases": 65,
        "Conventional Hydroelectric": 90,
        "Onshore Wind Turbine": 95,
        "Solar Photovoltaic": 95,
        "Geothermal": 60,
        "All Other": 60,
    }
    contam_score = contamination_scores.get(fuel, 60)

    # Status: retiring plants still have active infrastructure and staff
    status_score = 80 if status == "retiring" else 65

    return contam_score * 0.70 + status_score * 0.30


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    print("Loading data...")
    with open(PLANTS_FILE) as f:
        plants_geojson = json.load(f)
    with open(SUBSTATIONS_FILE) as f:
        subs_geojson = json.load(f)

    # Filter to retired/retiring plants
    candidates = []
    for feat in plants_geojson["features"]:
        p = feat["properties"]
        if p["status"] in ("retired", "retiring"):
            candidates.append(p)
    print("  Retired/retiring plants (>= 50 MW): " + str(len(candidates)))

    # Filter substations to 345kV+
    hv_subs = []
    for feat in subs_geojson["features"]:
        p = feat["properties"]
        v = p.get("MAX_VOLT")
        if v is not None and float(v) >= 345:
            hv_subs.append(p)
    print("  Substations >= 345 kV: " + str(len(hv_subs)))

    # Pre-extract substation coords for distance calc
    sub_coords = []
    for s in hv_subs:
        sub_coords.append({
            "lat": float(s["LATITUDE"]),
            "lon": float(s["LONGITUDE"]),
            "max_volt": float(s["MAX_VOLT"]),
            "lines": float(s.get("LINES") or 0),
            "name": s.get("NAME", ""),
        })

    print("Scoring " + str(len(candidates)) + " sites...")

    scored = []
    for plant in candidates:
        lat = plant["latitude"]
        lon = plant["longitude"]

        # Find nearest 345kV+ substation
        best_dist = float("inf")
        best_sub = None
        for sc in sub_coords:
            d = haversine_miles(lat, lon, sc["lat"], sc["lon"])
            if d < best_dist:
                best_dist = d
                best_sub = sc

        nearest = {
            "distance_miles": best_dist,
            "max_volt": best_sub["max_volt"] if best_sub else 345,
            "lines": best_sub["lines"] if best_sub else 0,
            "name": best_sub["name"] if best_sub else "",
        }

        # Score each dimension
        pa = score_power_access(plant, nearest)
        gc = score_grid_capacity(plant, nearest)
        sc = score_site_characteristics(plant)
        co = score_connectivity(plant)
        rf = score_risk_factors(plant)

        composite = (pa * 0.30) + (gc * 0.20) + (sc * 0.20) + (co * 0.15) + (rf * 0.15)
        composite = round(clamp(composite), 1)

        scored.append({
            "plant_name": plant["plant_name"],
            "state": plant["state"],
            "latitude": lat,
            "longitude": lon,
            "total_capacity_mw": plant["total_capacity_mw"],
            "fuel_type": plant["fuel_type"],
            "status": plant["status"],
            "planned_retirement_date": plant.get("planned_retirement_date"),
            "composite_score": composite,
            "power_access": round(pa, 1),
            "grid_capacity": round(gc, 1),
            "site_characteristics": round(sc, 1),
            "connectivity": round(co, 1),
            "risk_factors": round(rf, 1),
            "nearest_sub_name": nearest["name"],
            "nearest_sub_distance_miles": round(best_dist, 1),
            "nearest_sub_voltage_kv": nearest["max_volt"],
        })

    # Sort by composite score descending, take top N
    scored.sort(key=lambda x: -x["composite_score"])
    top = scored[:TOP_N]

    # Build GeoJSON
    features = []
    for s in top:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s["longitude"], s["latitude"]],
            },
            "properties": s,
        })

    geojson = {"type": "FeatureCollection", "features": features}

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f, indent=2)

    file_size = round(os.path.getsize(OUTPUT_FILE) / 1024, 1)

    # Print summary table
    print("")
    print("=" * 120)
    print("TOP 20 ADAPTIVE REUSE SITES")
    print("=" * 120)
    header = "{:>3}  {:<30} {:>2}  {:>7}  {:>12}  {:>5}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6}".format(
        "#", "Plant Name", "ST", "Score", "Capacity MW", "PwrAc", "Grid", "Site", "Conn", "Risk", "SubMi", "SubkV"
    )
    print(header)
    print("-" * 120)
    for i, s in enumerate(top[:20]):
        name = s["plant_name"][:30]
        print("{:>3}  {:<30} {:>2}  {:>7}  {:>10,.0f}  {:>5}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6,.0f}".format(
            i + 1,
            name,
            s["state"],
            s["composite_score"],
            s["total_capacity_mw"],
            s["power_access"],
            s["grid_capacity"],
            s["site_characteristics"],
            s["connectivity"],
            s["risk_factors"],
            s["nearest_sub_distance_miles"],
            s["nearest_sub_voltage_kv"],
        ))

    print("")
    print("Output: " + OUTPUT_FILE + " (" + str(file_size) + " KB)")
    print("Top " + str(TOP_N) + " sites saved, " + str(len(scored)) + " total scored")

    # Score distribution
    brackets = {"90+": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
    for s in scored:
        cs = s["composite_score"]
        if cs >= 90:
            brackets["90+"] += 1
        elif cs >= 80:
            brackets["80-89"] += 1
        elif cs >= 70:
            brackets["70-79"] += 1
        elif cs >= 60:
            brackets["60-69"] += 1
        else:
            brackets["<60"] += 1
    print("Score distribution (all " + str(len(scored)) + " sites):")
    for k, v in brackets.items():
        print("  " + k + ": " + str(v))


if __name__ == "__main__":
    main()
