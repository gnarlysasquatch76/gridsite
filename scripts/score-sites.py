"""
Score retired/retiring power plants for data center adaptive reuse potential.

Reads power-plants.geojson, substations.geojson, and queue-withdrawals.geojson,
scores each retired/retiring plant (>= 50 MW) on a 0-100 composite scale,
and outputs the top 100 sites to scored-sites.geojson.

Scoring model (5 dimensions, weighted):
  Power Access        (30%) - substation proximity, plant capacity, interconnection voltage
  Grid Capacity       (20%) - plant MW, substation lines, nearby queue withdrawals
  Site Characteristics (20%) - fuel type reuse suitability, capacity scale
  Connectivity        (15%) - proximity to population centers, broadband coverage proxy
  Risk Factors        (15%) - contamination risk, retirement status, flood zone exposure
"""

import json
import math
import os

SCRIPT_DIR = os.path.dirname(__file__)
PLANTS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "power-plants.geojson")
SUBSTATIONS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "substations.geojson")
QUEUE_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "queue-withdrawals.geojson")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "scored-sites.geojson")

TOP_N = 100

# FEMA high-risk flood zone states/regions. Plants in these coastal/riverine
# counties face higher flood risk. We use state + longitude/latitude heuristics
# to identify sites in FEMA Special Flood Hazard Areas (SFHA).
# Coastal counties within 50 miles of coast and below 30ft elevation proxy.
FLOOD_RISK_STATES = {
    "LA", "FL", "TX", "MS", "AL",  # Gulf Coast
    "SC", "NC",                      # Atlantic hurricane coast
}

# States with moderate flood risk (riverine/coastal but less extreme)
MODERATE_FLOOD_STATES = {
    "NJ", "DE", "MD", "VA",  # Mid-Atlantic
    "GA", "CT", "RI", "MA",  # Coastal states
    "HI",                      # Island
}

# Broadband coverage tiers by state (FCC BDC data summary).
# Percentage of locations with 100/20 Mbps+ service ("served").
# Sourced from FCC Broadband Data Collection June 2024 state-level stats.
# Higher = better broadband coverage = better connectivity score.
BROADBAND_COVERAGE = {
    "NJ": 97, "CT": 96, "MA": 96, "RI": 95, "MD": 95, "DE": 94,
    "NY": 93, "VA": 93, "NH": 92, "PA": 91, "FL": 91, "IL": 90,
    "OH": 90, "CA": 90, "WA": 90, "CO": 89, "GA": 89, "TX": 89,
    "MI": 88, "NC": 88, "MN": 88, "OR": 87, "WI": 87, "IN": 86,
    "AZ": 86, "SC": 86, "TN": 85, "UT": 85, "NV": 85, "MO": 84,
    "KY": 83, "IA": 83, "AL": 82, "KS": 82, "NE": 81, "LA": 81,
    "OK": 80, "ID": 79, "SD": 78, "ND": 77, "WV": 76, "AR": 76,
    "NM": 75, "ME": 75, "VT": 74, "MT": 73, "WY": 72, "MS": 72,
    "AK": 70, "HI": 80,
}


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


def is_coastal_location(lat, lon, state):
    """Heuristic: is this site likely in a FEMA Special Flood Hazard Area?"""
    if state in FLOOD_RISK_STATES:
        # Gulf/Atlantic coast: most of these states have widespread flood zones
        # Sites closer to coast (lower elevation proxy) score worse
        if state == "FL":
            return True  # Nearly all of FL is flood-prone
        if state == "LA":
            if lat < 31.0:
                return True  # Southern LA is extremely flood-prone
            return lon < -91.0  # Mississippi River corridor
        if state == "TX":
            return lon > -97.0 and lat < 30.5  # Houston/Gulf Coast corridor
        if state == "MS":
            return lat < 31.5
        if state == "AL":
            return lat < 31.5
        if state in ("NC", "SC"):
            return lon > -80.0  # Coastal plain
        return True
    return False


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


def score_grid_capacity(plant, nearest_sub, nearby_withdrawals):
    """
    20% weight. Based on:
    - Plant capacity as proxy for existing grid headroom
    - Number of transmission lines at nearest substation
    - Nearby queue withdrawals (within 20 mi): more = more studied grid capacity,
      indicates interconnection infrastructure has been evaluated
    """
    capacity = plant["total_capacity_mw"]
    lines = nearest_sub.get("lines") or 0

    # Capacity proxy: larger plant = more grid infrastructure already present
    cap_score = clamp((capacity - 50) / 2950 * 100)  # 0 at 50MW, 100 at 3000MW

    # Lines score: more connections = more grid flexibility
    # Typically 2-12 lines; score 100 at 8+
    lines_score = clamp(lines / 8 * 100)

    # Queue withdrawals score: nearby withdrawn projects indicate
    # the grid has been studied for generation interconnection.
    # More withdrawn projects = more evaluated capacity = better understood grid.
    # 0 withdrawals = 30 (baseline), 5+ = 90, 15+ = 100
    qw_count = nearby_withdrawals["count"]
    qw_mw = nearby_withdrawals["total_mw"]
    if qw_count == 0:
        qw_score = 30
    else:
        count_score = clamp(30 + qw_count * 5, 30, 100)
        # MW bonus: large withdrawn capacity means major grid studies were done
        mw_bonus = clamp(qw_mw / 5000 * 20, 0, 20)
        qw_score = clamp(count_score + mw_bonus)

    return cap_score * 0.40 + lines_score * 0.30 + qw_score * 0.30


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
    15% weight. Based on:
    - Proximity to population centers (longitude proxy: eastern US has more fiber/POPs)
    - Latitude band (mid-latitudes 30-43 are population-dense corridor)
    - State broadband coverage (FCC BDC data: % of locations with 100/20+ Mbps)
    """
    lat = plant["latitude"]
    lon = plant["longitude"]
    state = plant["state"]

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

    # Broadband coverage score from FCC data
    # Scale: 70% coverage = 40 score, 90%+ = 90 score
    bb_pct = BROADBAND_COVERAGE.get(state, 80)
    if bb_pct >= 95:
        bb_score = 95
    elif bb_pct >= 90:
        bb_score = 85
    elif bb_pct >= 85:
        bb_score = 75
    elif bb_pct >= 80:
        bb_score = 65
    elif bb_pct >= 75:
        bb_score = 50
    else:
        bb_score = 35

    return lon_score * 0.40 + lat_score * 0.30 + bb_score * 0.30


def score_risk_factors(plant):
    """
    15% weight. Based on:
    - Fuel type contamination risk (coal ash, nuclear waste, etc.)
    - Status: retiring (still operating) is lower risk than already retired
    - FEMA flood zone exposure: sites in high-risk flood areas score lower
    """
    fuel = plant["fuel_type"]
    status = plant["status"]
    state = plant["state"]
    lat = plant["latitude"]
    lon = plant["longitude"]

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

    # Flood zone risk: sites NOT in flood zones score higher
    if is_coastal_location(lat, lon, state):
        flood_score = 35  # High flood risk
    elif state in MODERATE_FLOOD_STATES:
        flood_score = 65  # Moderate flood risk
    else:
        flood_score = 90  # Low flood risk

    return contam_score * 0.50 + status_score * 0.20 + flood_score * 0.30


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    # Load old scored sites for comparison
    old_top10 = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            old_geojson = json.load(f)
        for feat in old_geojson["features"][:10]:
            p = feat["properties"]
            old_top10.append({
                "plant_name": p["plant_name"],
                "state": p["state"],
                "composite_score": p["composite_score"],
            })

    print("Loading data...")
    with open(PLANTS_FILE) as f:
        plants_geojson = json.load(f)
    with open(SUBSTATIONS_FILE) as f:
        subs_geojson = json.load(f)
    with open(QUEUE_FILE) as f:
        queue_geojson = json.load(f)

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

    # Pre-extract queue withdrawal coords for proximity analysis
    qw_points = []
    for feat in queue_geojson["features"]:
        coords = feat["geometry"]["coordinates"]
        p = feat["properties"]
        mw = float(p.get("total_mw") or 0)
        qw_points.append({
            "lat": coords[1],
            "lon": coords[0],
            "total_mw": mw,
        })
    print("  Queue withdrawals loaded: " + str(len(qw_points)))

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

        # Count queue withdrawals within 20 miles
        # Use bbox pre-filter for performance (20 mi ~ 0.29 deg lat)
        deg_delta = 20 / 69.0
        lon_delta = deg_delta / max(math.cos(math.radians(lat)), 0.01)
        qw_count = 0
        qw_total_mw = 0.0
        for qw in qw_points:
            # Bbox pre-filter
            if abs(qw["lat"] - lat) > deg_delta:
                continue
            if abs(qw["lon"] - lon) > lon_delta:
                continue
            d = haversine_miles(lat, lon, qw["lat"], qw["lon"])
            if d <= 20:
                qw_count += 1
                qw_total_mw += qw["total_mw"]

        nearby_qw = {"count": qw_count, "total_mw": qw_total_mw}

        # Score each dimension
        pa = score_power_access(plant, nearest)
        gc = score_grid_capacity(plant, nearest, nearby_qw)
        sc_val = score_site_characteristics(plant)
        co = score_connectivity(plant)
        rf = score_risk_factors(plant)

        composite = (pa * 0.30) + (gc * 0.20) + (sc_val * 0.20) + (co * 0.15) + (rf * 0.15)
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
            "site_characteristics": round(sc_val, 1),
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

    # ── Comparison: Old Top 10 vs New Top 10 ──────────────────────────────
    if old_top10:
        print("")
        print("=" * 100)
        print("OLD TOP 10 vs NEW TOP 10")
        print("=" * 100)
        print("{:>3}  {:<32} {:>2} {:>6}   |  {:>3}  {:<32} {:>2} {:>6}".format(
            "#", "OLD", "ST", "Score", "#", "NEW", "ST", "Score"
        ))
        print("-" * 100)
        for i in range(10):
            old_name = ""
            old_st = ""
            old_sc = ""
            if i < len(old_top10):
                old_name = old_top10[i]["plant_name"][:32]
                old_st = old_top10[i]["state"]
                old_sc = str(old_top10[i]["composite_score"])

            new_name = top[i]["plant_name"][:32] if i < len(top) else ""
            new_st = top[i]["state"] if i < len(top) else ""
            new_sc = str(top[i]["composite_score"]) if i < len(top) else ""

            # Mark changes
            marker = ""
            if i < len(old_top10) and i < len(top):
                if old_top10[i]["plant_name"] != top[i]["plant_name"]:
                    marker = " *"

            print("{:>3}  {:<32} {:>2} {:>6}   |  {:>3}  {:<32} {:>2} {:>6}{}".format(
                i + 1, old_name, old_st, old_sc,
                i + 1, new_name, new_st, new_sc, marker
            ))
        print("")
        print("  * = position changed from old ranking")

    # ── Print summary table ───────────────────────────────────────────────
    print("")
    print("=" * 130)
    print("TOP 20 ADAPTIVE REUSE SITES (UPDATED SCORING)")
    print("=" * 130)
    header = "{:>3}  {:<30} {:>2}  {:>7}  {:>12}  {:>5}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6}".format(
        "#", "Plant Name", "ST", "Score", "Capacity MW", "PwrAc", "Grid", "Site", "Conn", "Risk", "SubMi", "SubkV"
    )
    print(header)
    print("-" * 130)
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
