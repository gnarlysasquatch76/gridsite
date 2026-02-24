"""
Score sites for data center adaptive reuse potential.

Scores two site types using the same 4-dimension model:
  1. Retired/retiring power plants (>= 50 MW) from power-plants.geojson
  2. EPA brownfield sites from epa-brownfields.geojson

All sites are scored on a 0-100 composite scale and ranked together.
The top 100 are output to scored-sites.geojson.

Scoring model (4 dimensions, weighted):
  Time to Power    (50%) - substation proximity, voltage, gen capacity, tx lines, queue withdrawals
  Site Readiness   (20%) - fuel type suitability, capacity scale (plants) or base reuse score (brownfields)
  Connectivity     (15%) - proximity to population centers, broadband coverage
  Risk Factors     (15%) - contamination/environmental risk, operational status, flood zone exposure
"""

import json
import math
import os

SCRIPT_DIR = os.path.dirname(__file__)
PLANTS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "power-plants.geojson")
SUBSTATIONS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "substations.geojson")
QUEUE_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "queue-withdrawals.geojson")
BROWNFIELDS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "epa-brownfields.geojson")
LMP_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "lmp-nodes.geojson")
ATC_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "oasis-atc.geojson")
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

FUEL_TYPE_SCORES = {
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

CONTAMINATION_SCORES = {
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


# ── Sub-score functions ───────────────────────────────────────────────────


def compute_sub_distance(dist):
    """Distance to nearest 345kV+ sub: 100 at 0 mi, 0 at 50+ mi."""
    return clamp(100 - dist * 2)


def compute_sub_voltage(max_volt):
    """Voltage tier score."""
    if max_volt >= 765:
        return 100
    elif max_volt >= 500:
        return 85
    elif max_volt >= 345:
        return 70
    return 60


def compute_gen_capacity(capacity):
    """Existing generation capacity score (power plants only)."""
    return clamp((capacity - 50) / 1950 * 100)


def compute_tx_lines(lines):
    """Connected transmission lines score."""
    return clamp(lines / 8 * 100)


def compute_queue_withdrawal(qw_count, qw_mw):
    """Queue withdrawal activity score."""
    if qw_count == 0:
        return 30
    count_score = clamp(30 + qw_count * 5, 30, 100)
    mw_bonus = clamp(qw_mw / 5000 * 20, 0, 20)
    return clamp(count_score + mw_bonus)


def compute_fuel_type(fuel):
    """Fuel type suitability score (power plants only)."""
    return FUEL_TYPE_SCORES.get(fuel, 50)


def compute_capacity_scale(capacity):
    """Capacity scale score (power plants only)."""
    return clamp((capacity - 50) / 1450 * 100)


def compute_longitude(lon):
    """Longitude proximity proxy."""
    if lon < -70:
        return clamp(100 - (lon + 70) * -1.2)
    return 100


def compute_latitude(lat):
    """Latitude band score."""
    if 33 <= lat <= 43:
        return 90
    elif 28 <= lat <= 48:
        return 70
    return 40


def compute_broadband(state):
    """Broadband coverage score from state-level FCC data."""
    bb_pct = BROADBAND_COVERAGE.get(state, 80)
    if bb_pct >= 95:
        return 95
    elif bb_pct >= 90:
        return 85
    elif bb_pct >= 85:
        return 75
    elif bb_pct >= 80:
        return 65
    elif bb_pct >= 75:
        return 50
    return 35


def compute_contamination(site):
    """Contamination risk score."""
    if site["site_type"] == "power_plant":
        return CONTAMINATION_SCORES.get(site["fuel_type"], 60)
    return 55  # brownfield


def compute_operational_status(site):
    """Operational status score (power plants only)."""
    if site["site_type"] == "power_plant":
        return 80 if site.get("status") == "retiring" else 65
    return 0  # N/A for brownfields


def compute_flood_zone(lat, lon, state):
    """Flood zone exposure score."""
    if is_coastal_location(lat, lon, state):
        return 35
    elif state in MODERATE_FLOOD_STATES:
        return 65
    return 90


def compute_lmp_score(avg_lmp):
    """LMP pricing score. Low LMP = grid headroom = high score."""
    if avg_lmp <= 20:
        return 95
    elif avg_lmp <= 25:
        return 90
    elif avg_lmp <= 30:
        return 80
    elif avg_lmp <= 35:
        return 70
    elif avg_lmp <= 40:
        return 60
    elif avg_lmp <= 45:
        return 50
    elif avg_lmp <= 50:
        return 40
    elif avg_lmp <= 55:
        return 30
    return 20


def find_nearest_lmp(lat, lon, lmp_nodes):
    """Find nearest LMP pricing node and return (name, avg_lmp, lmp_score)."""
    best_dist = float("inf")
    best_node = None
    for node in lmp_nodes:
        d = haversine_miles(lat, lon, node["lat"], node["lon"])
        if d < best_dist:
            best_dist = d
            best_node = node
    if best_node is None:
        return "", 0, 50
    return best_node["name"], best_node["avg_lmp"], compute_lmp_score(best_node["avg_lmp"])


def compute_atc_score(avg_atc_mw):
    """ATC scoring. High ATC = more transfer capability = high score."""
    if avg_atc_mw >= 3000:
        return 95
    elif avg_atc_mw >= 2000:
        return 85
    elif avg_atc_mw >= 1500:
        return 75
    elif avg_atc_mw >= 1000:
        return 60
    elif avg_atc_mw >= 500:
        return 45
    elif avg_atc_mw >= 200:
        return 30
    return 20


def find_nearest_atc(lat, lon, atc_nodes):
    """Find nearest ATC interface and return (name, avg_atc_mw, atc_score)."""
    best_dist = float("inf")
    best_node = None
    for node in atc_nodes:
        d = haversine_miles(lat, lon, node["lat"], node["lon"])
        if d < best_dist:
            best_dist = d
            best_node = node
    if best_node is None:
        return "", 0, 50
    return best_node["name"], best_node["avg_atc_mw"], compute_atc_score(best_node["avg_atc_mw"])


# ── Dimension scorers ─────────────────────────────────────────────────────


def score_time_to_power(site, nearest, nearby_withdrawals, lmp_score, atc_score=50):
    """
    50% weight. Combines old Power Access + Grid Capacity + LMP pricing + ATC.
    Power plants: distance + gen capacity + voltage + tx lines + queue withdrawals + lmp + atc
    Brownfields: distance + voltage + tx lines + queue withdrawals + lmp + atc (no gen capacity)
    """
    dist_score = compute_sub_distance(nearest["distance_miles"])
    volt_score = compute_sub_voltage(nearest["max_volt"])
    lines_score = compute_tx_lines(nearest.get("lines") or 0)
    qw_score = compute_queue_withdrawal(
        nearby_withdrawals["count"], nearby_withdrawals["total_mw"]
    )

    if site["site_type"] == "power_plant":
        capacity = site.get("total_capacity_mw", 0)
        gen_cap_score = compute_gen_capacity(capacity)
        dim = (dist_score * 0.18 + gen_cap_score * 0.15 + volt_score * 0.11 +
               lines_score * 0.11 + qw_score * 0.18 + lmp_score * 0.14 + atc_score * 0.13)
    else:
        gen_cap_score = 0
        dim = (dist_score * 0.25 + volt_score * 0.15 + lines_score * 0.15 +
               qw_score * 0.18 + lmp_score * 0.14 + atc_score * 0.13)

    return dim, dist_score, volt_score, gen_cap_score, lines_score, qw_score


def score_site_readiness(site):
    """
    20% weight. Renamed from Site Characteristics.
    Power plants: fuel type suitability + capacity scale
    Brownfields: base reuse score (flat 65)
    """
    if site["site_type"] == "power_plant":
        fuel_score = compute_fuel_type(site["fuel_type"])
        capacity = site.get("total_capacity_mw", 0)
        scale_score = compute_capacity_scale(capacity)
        dim = fuel_score * 0.60 + scale_score * 0.40
        return dim, fuel_score, scale_score
    return 65, 0, 0


def score_connectivity(site):
    """
    15% weight. Same for both site types.
    """
    lon_score = compute_longitude(site["longitude"])
    lat_score = compute_latitude(site["latitude"])
    bb_score = compute_broadband(site["state"])
    dim = lon_score * 0.40 + lat_score * 0.30 + bb_score * 0.30
    return dim, lon_score, lat_score, bb_score


def score_risk_factors(site):
    """
    15% weight.
    Power plants: contamination + status + flood
    Brownfields: contamination + flood (no status)
    """
    contam_score = compute_contamination(site)
    status_score = compute_operational_status(site)
    flood_score = compute_flood_zone(site["latitude"], site["longitude"], site["state"])

    if site["site_type"] == "power_plant":
        dim = contam_score * 0.50 + status_score * 0.20 + flood_score * 0.30
    else:
        dim = contam_score * 0.65 + flood_score * 0.35

    return dim, contam_score, status_score, flood_score


# ── Main ──────────────────────────────────────────────────────────────────


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

    # Load LMP nodes
    lmp_nodes = []
    if os.path.exists(LMP_FILE):
        with open(LMP_FILE) as f:
            lmp_geojson = json.load(f)
        for feat in lmp_geojson["features"]:
            coords = feat["geometry"]["coordinates"]
            p = feat["properties"]
            lmp_nodes.append({
                "lat": coords[1],
                "lon": coords[0],
                "name": p.get("name", ""),
                "avg_lmp": float(p.get("avg_lmp", 40)),
            })
        print("  LMP nodes loaded: " + str(len(lmp_nodes)))
    else:
        print("  LMP nodes file not found, skipping")

    # Load ATC interfaces
    atc_nodes = []
    if os.path.exists(ATC_FILE):
        with open(ATC_FILE) as f:
            atc_geojson = json.load(f)
        for feat in atc_geojson["features"]:
            coords = feat["geometry"]["coordinates"]
            p = feat["properties"]
            atc_nodes.append({
                "lat": coords[1],
                "lon": coords[0],
                "name": p.get("name", ""),
                "avg_atc_mw": float(p.get("avg_atc_mw", 0)),
            })
        print("  ATC interfaces loaded: " + str(len(atc_nodes)))
    else:
        print("  ATC file not found, skipping")

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

    # Filter to retired/retiring plants (exclude retooled — still have active generators)
    plant_candidates = []
    retooled_skipped = 0
    for feat in plants_geojson["features"]:
        p = feat["properties"]
        if p["status"] == "retooled":
            retooled_skipped += 1
            continue
        if p["status"] in ("retired", "retiring"):
            p["site_type"] = "power_plant"
            plant_candidates.append(p)
    print("  Retired/retiring plants (>= 50 MW): " + str(len(plant_candidates)))
    if retooled_skipped > 0:
        print("  Retooled plants excluded: " + str(retooled_skipped))

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

        # Find nearest LMP node
        lmp_name, lmp_avg, lmp_s = find_nearest_lmp(lat, lon, lmp_nodes) if lmp_nodes else ("", 0, 50)

        # Find nearest ATC interface
        atc_name, atc_mw, atc_s = find_nearest_atc(lat, lon, atc_nodes) if atc_nodes else ("", 0, 50)

        # Score each dimension
        ttp, dist_s, volt_s, gen_s, lines_s, qw_s = score_time_to_power(site, nearest, nearby_qw, lmp_s, atc_s)
        sr, fuel_s, scale_s = score_site_readiness(site)
        co, lon_s, lat_s, bb_s = score_connectivity(site)
        rf, contam_s, status_s, flood_s = score_risk_factors(site)

        composite = (ttp * 0.50) + (sr * 0.20) + (co * 0.15) + (rf * 0.15)
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
            "time_to_power": round(ttp, 1),
            "site_readiness": round(sr, 1),
            "connectivity": round(co, 1),
            "risk_factors": round(rf, 1),
            "sub_distance_score": round(dist_s, 1),
            "sub_voltage_score": round(volt_s, 1),
            "gen_capacity_score": round(gen_s, 1),
            "tx_lines_score": round(lines_s, 1),
            "queue_withdrawal_score": round(qw_s, 1),
            "fuel_type_score": round(fuel_s, 1),
            "capacity_scale_score": round(scale_s, 1),
            "longitude_score": round(lon_s, 1),
            "latitude_score": round(lat_s, 1),
            "broadband_score": round(bb_s, 1),
            "contamination_score": round(contam_s, 1),
            "operational_status_score": round(status_s, 1),
            "flood_zone_score": round(flood_s, 1),
            "lmp_score": round(lmp_s, 1),
            "nearest_lmp_avg": round(lmp_avg, 1),
            "nearest_lmp_node": lmp_name,
            "atc_score": round(atc_s, 1),
            "nearest_atc_mw": round(atc_mw, 1),
            "nearest_atc_interface": atc_name,
            "nearest_sub_name": nearest["name"],
            "nearest_sub_distance_miles": round(best_dist, 1),
            "nearest_sub_voltage_kv": nearest["max_volt"],
            "nearest_sub_lines": nearest["lines"],
            "queue_count_20mi": qw_count,
            "queue_mw_20mi": round(qw_total_mw, 1),
            "site_type": site["site_type"],
            "owner_name": site.get("owner_name", ""),
            "utility_id": site.get("utility_id"),
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
    header = "{:>3}  {:<30} {:>2}  {:>7}  {:>12}  {:>10}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6}".format(
        "#", "Site Name", "ST", "Score", "Capacity MW", "Type", "TTP", "SiteR", "Conn", "Risk", "SubMi", "SubkV"
    )
    print(header)
    print("-" * 140)
    for i, s in enumerate(top[:20]):
        name = s["plant_name"][:30]
        site_type = "Plant" if s["site_type"] == "power_plant" else "Brown"
        cap_str = "{:>10,.0f}".format(s["total_capacity_mw"]) if s["total_capacity_mw"] > 0 else "       N/A"
        print("{:>3}  {:<30} {:>2}  {:>7}  {}  {:>10}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:>6,.0f}".format(
            i + 1,
            name,
            s["state"],
            s["composite_score"],
            cap_str,
            site_type,
            s["time_to_power"],
            s["site_readiness"],
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
