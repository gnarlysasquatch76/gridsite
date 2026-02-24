"""
Score sites for data center adaptive reuse potential.

Scores two site types using the same 5-dimension model:
  1. Retired/retiring power plants (>= 50 MW) from power-plants.geojson
  2. EPA brownfield sites from epa-brownfields.geojson

All sites are scored on a 0-100 composite scale and ranked together.
The top 100 are output to scored-sites.geojson.

Scoring model (5 dimensions, weighted):
  Power Access        (30%) - substation proximity, capacity/site potential, voltage
  Grid Capacity       (20%) - capacity/grid infrastructure, substation lines, queue withdrawals
  Site Characteristics (20%) - reuse suitability, scale
  Connectivity        (15%) - proximity to population centers, broadband coverage
  Risk Factors        (15%) - contamination/environmental risk, flood zone exposure
"""

import json
import math
import os

SCRIPT_DIR = os.path.dirname(__file__)
PLANTS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "power-plants.geojson")
SUBSTATIONS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "substations.geojson")
QUEUE_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "queue-withdrawals.geojson")
BROWNFIELDS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "epa-brownfields.geojson")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "scored-sites.geojson")

TOP_N = 100

# FEMA high-risk flood zone states/regions
FLOOD_RISK_STATES = {
    "LA", "FL", "TX", "MS", "AL",  # Gulf Coast
    "SC", "NC",                      # Atlantic hurricane coast
}

MODERATE_FLOOD_STATES = {
    "NJ", "DE", "MD", "VA",  # Mid-Atlantic
    "GA", "CT", "RI", "MA",  # Coastal states
    "HI",                      # Island
}

# FCC BDC broadband coverage by state (% of locations with 100/20+ Mbps)
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
    R = 3958.8
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
        if state == "FL":
            return True
        if state == "LA":
            if lat < 31.0:
                return True
            return lon < -91.0
        if state == "TX":
            return lon > -97.0 and lat < 30.5
        if state == "MS":
            return lat < 31.5
        if state == "AL":
            return lat < 31.5
        if state in ("NC", "SC"):
            return lon > -80.0
        return True
    return False


# ── Dimension scorers ──────────────────────────────────────────────────────


def score_power_access(site, nearest_sub):
    """
    30% weight.
    Power plants: distance + capacity + voltage
    Brownfields: distance + voltage (no existing capacity)
    """
    dist = nearest_sub["distance_miles"]
    max_volt = nearest_sub["max_volt"]
    capacity = site.get("total_capacity_mw", 0)

    # Distance score: 100 at 0 mi, 0 at 50+ mi
    dist_score = clamp(100 - (dist * 2))

    # Voltage bonus
    volt_score = 60
    if max_volt >= 765:
        volt_score = 100
    elif max_volt >= 500:
        volt_score = 85
    elif max_volt >= 345:
        volt_score = 70

    if site["site_type"] == "power_plant":
        cap_score = clamp((capacity - 50) / 1950 * 100)
        return dist_score * 0.50 + cap_score * 0.30 + volt_score * 0.20
    else:
        # Brownfields: no existing capacity, weight distance + voltage more
        return dist_score * 0.65 + volt_score * 0.35


def score_grid_capacity(site, nearest_sub, nearby_withdrawals):
    """
    20% weight.
    Power plants: capacity + lines + queue withdrawals
    Brownfields: lines + queue withdrawals (no existing capacity)
    """
    lines = nearest_sub.get("lines") or 0
    lines_score = clamp(lines / 8 * 100)

    qw_count = nearby_withdrawals["count"]
    qw_mw = nearby_withdrawals["total_mw"]
    if qw_count == 0:
        qw_score = 30
    else:
        count_score = clamp(30 + qw_count * 5, 30, 100)
        mw_bonus = clamp(qw_mw / 5000 * 20, 0, 20)
        qw_score = clamp(count_score + mw_bonus)

    if site["site_type"] == "power_plant":
        capacity = site.get("total_capacity_mw", 0)
        cap_score = clamp((capacity - 50) / 2950 * 100)
        return cap_score * 0.40 + lines_score * 0.30 + qw_score * 0.30
    else:
        # Brownfields: no capacity, weight lines + withdrawals
        return lines_score * 0.45 + qw_score * 0.55


def score_site_characteristics(site):
    """
    20% weight.
    Power plants: fuel type suitability + capacity scale
    Brownfields: base reuse score (already cleared/assessed for redevelopment)
    """
    if site["site_type"] == "power_plant":
        fuel = site["fuel_type"]
        capacity = site.get("total_capacity_mw", 0)

        fuel_scores = {
            "Conventional Steam Coal": 90,
            "Natural Gas Fired Combined Cycle": 95,
            "Natural Gas Fired Combustion Turbine": 80,
            "Natural Gas Steam Turbine": 85,
            "Nuclear": 50,
            "Petroleum Liquids": 70,
            "Petroleum Coke": 70,
            "Coal Integrated Gasification Combined Cycle": 80,
            "Other Gases": 65,
            "Other Waste Biomass": 55,
            "Wood/Wood Waste Biomass": 55,
            "Municipal Solid Waste": 45,
            "Landfill Gas": 40,
            "Conventional Hydroelectric": 30,
            "Onshore Wind Turbine": 20,
            "Solar Photovoltaic": 25,
            "Geothermal": 35,
            "All Other": 50,
        }
        fuel_score = fuel_scores.get(fuel, 50)
        scale_score = clamp((capacity - 50) / 1450 * 100)
        return fuel_score * 0.60 + scale_score * 0.40
    else:
        # Brownfields are assessed/cleared for redevelopment — good reuse potential
        # but unknown structural footprint, so moderate-high base score
        return 65


def score_connectivity(site):
    """
    15% weight. Same for both site types:
    longitude proxy + latitude band + broadband coverage
    """
    lat = site["latitude"]
    lon = site["longitude"]
    state = site["state"]

    lon_score = clamp(100 - (lon + 70) * -1.2) if lon < -70 else 100
    lon_score = clamp(lon_score)

    if 33 <= lat <= 43:
        lat_score = 90
    elif 28 <= lat <= 48:
        lat_score = 70
    else:
        lat_score = 40

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


def score_risk_factors(site):
    """
    15% weight.
    Power plants: contamination + status + flood
    Brownfields: brownfield contamination risk + flood
    """
    state = site["state"]
    lat = site["latitude"]
    lon = site["longitude"]

    # Flood zone risk
    if is_coastal_location(lat, lon, state):
        flood_score = 35
    elif state in MODERATE_FLOOD_STATES:
        flood_score = 65
    else:
        flood_score = 90

    if site["site_type"] == "power_plant":
        fuel = site["fuel_type"]
        status = site.get("status", "retired")

        contamination_scores = {
            "Conventional Steam Coal": 45,
            "Coal Integrated Gasification Combined Cycle": 50,
            "Nuclear": 20,
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
        status_score = 80 if status == "retiring" else 65
        return contam_score * 0.50 + status_score * 0.20 + flood_score * 0.30
    else:
        # Brownfields have known contamination (they're on the EPA list),
        # but they've been assessed and are in the remediation pipeline.
        # Moderate risk — better than coal/nuclear, worse than clean gas.
        contam_score = 55
        return contam_score * 0.65 + flood_score * 0.35


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

    # Load brownfields if available
    brownfield_sites = []
    if os.path.exists(BROWNFIELDS_FILE):
        with open(BROWNFIELDS_FILE) as f:
            bf_geojson = json.load(f)
        for feat in bf_geojson["features"]:
            p = feat["properties"]
            coords = feat["geometry"]["coordinates"]
            brownfield_sites.append({
                "plant_name": p.get("name", "Unknown"),
                "state": p.get("state", ""),
                "latitude": coords[1],
                "longitude": coords[0],
                "total_capacity_mw": 0,
                "fuel_type": "Brownfield",
                "status": "brownfield",
                "site_type": "brownfield",
                "city": p.get("city", ""),
                "county": p.get("county", ""),
            })
        print("  Brownfield sites loaded: " + str(len(brownfield_sites)))
    else:
        print("  Brownfields file not found, skipping")

    # Filter to retired/retiring plants
    plant_candidates = []
    for feat in plants_geojson["features"]:
        p = feat["properties"]
        if p["status"] in ("retired", "retiring"):
            p["site_type"] = "power_plant"
            plant_candidates.append(p)
    print("  Retired/retiring plants (>= 50 MW): " + str(len(plant_candidates)))

    # Combine all candidates
    candidates = plant_candidates + brownfield_sites
    print("  Total candidates: " + str(len(candidates)))

    # Filter substations to 345kV+
    hv_subs = []
    for feat in subs_geojson["features"]:
        p = feat["properties"]
        v = p.get("MAX_VOLT")
        if v is not None and float(v) >= 345:
            hv_subs.append(p)
    print("  Substations >= 345 kV: " + str(len(hv_subs)))

    sub_coords = []
    for s in hv_subs:
        sub_coords.append({
            "lat": float(s["LATITUDE"]),
            "lon": float(s["LONGITUDE"]),
            "max_volt": float(s["MAX_VOLT"]),
            "lines": float(s.get("LINES") or 0),
            "name": s.get("NAME", ""),
        })

    # Pre-extract queue withdrawal coords
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
    for idx, site in enumerate(candidates):
        if (idx + 1) % 10000 == 0:
            print("  Scored {:,} / {:,}...".format(idx + 1, len(candidates)))

        lat = site["latitude"]
        lon = site["longitude"]

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
        deg_delta = 20 / 69.0
        lon_delta = deg_delta / max(math.cos(math.radians(lat)), 0.01)
        qw_count = 0
        qw_total_mw = 0.0
        for qw in qw_points:
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
        pa = score_power_access(site, nearest)
        gc = score_grid_capacity(site, nearest, nearby_qw)
        sc_val = score_site_characteristics(site)
        co = score_connectivity(site)
        rf = score_risk_factors(site)

        composite = (pa * 0.30) + (gc * 0.20) + (sc_val * 0.20) + (co * 0.15) + (rf * 0.15)
        composite = round(clamp(composite), 1)

        scored.append({
            "plant_name": site["plant_name"],
            "state": site["state"],
            "latitude": lat,
            "longitude": lon,
            "total_capacity_mw": site.get("total_capacity_mw", 0),
            "fuel_type": site.get("fuel_type", "Brownfield"),
            "status": site.get("status", "brownfield"),
            "planned_retirement_date": site.get("planned_retirement_date"),
            "composite_score": composite,
            "power_access": round(pa, 1),
            "grid_capacity": round(gc, 1),
            "site_characteristics": round(sc_val, 1),
            "connectivity": round(co, 1),
            "risk_factors": round(rf, 1),
            "nearest_sub_name": nearest["name"],
            "nearest_sub_distance_miles": round(best_dist, 1),
            "nearest_sub_voltage_kv": nearest["max_volt"],
            "site_type": site["site_type"],
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
    print("=" * 140)
    print("TOP 20 ADAPTIVE REUSE SITES (ALL SITE TYPES)")
    print("=" * 140)
    header = "{:>3}  {:<30} {:>2}  {:>7}  {:>12}  {:>10}  {:>5}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6}".format(
        "#", "Site Name", "ST", "Score", "Capacity MW", "Type", "PwrAc", "Grid", "Site", "Conn", "Risk", "SubMi", "SubkV"
    )
    print(header)
    print("-" * 140)
    for i, s in enumerate(top[:20]):
        name = s["plant_name"][:30]
        site_type = "Plant" if s["site_type"] == "power_plant" else "Brown"
        cap_str = "{:>10,.0f}".format(s["total_capacity_mw"]) if s["total_capacity_mw"] > 0 else "       N/A"
        print("{:>3}  {:<30} {:>2}  {:>7}  {}  {:>10}  {:>5}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6,.0f}".format(
            i + 1,
            name,
            s["state"],
            s["composite_score"],
            cap_str,
            site_type,
            s["power_access"],
            s["grid_capacity"],
            s["site_characteristics"],
            s["connectivity"],
            s["risk_factors"],
            s["nearest_sub_distance_miles"],
            s["nearest_sub_voltage_kv"],
        ))

    # Count by type
    plant_count = sum(1 for s in top if s["site_type"] == "power_plant")
    bf_count = sum(1 for s in top if s["site_type"] == "brownfield")
    print("")
    print("Output: " + OUTPUT_FILE + " (" + str(file_size) + " KB)")
    print("Top " + str(TOP_N) + " sites: " + str(plant_count) + " power plants, " + str(bf_count) + " brownfields")
    print("Total scored: " + str(len(scored)))

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
