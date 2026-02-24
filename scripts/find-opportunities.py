"""
Opportunity Finder — identify development sites near qualifying substations.

A qualifying substation has:
  - MAX_VOLT >= 345 kV (proxy for 100 MW+ throughput capacity)
  - Nearest LMP pricing node classified as "low" (< $35/MWh)
  - Located within a utility territory classified as "surplus" (gen > load)

For each qualifying substation, sites within 3 miles are identified:
  1. Retired Plant — retired/retiring power plants from EIA-860 data
  2. Adaptive Reuse — industrial/commercial structures from OpenStreetMap + EPA brownfields
  3. Greenfield — vacant land >= 50 acres from OpenStreetMap

All sites scored using the 4-dimension model:
  Time to Power (50%) | Site Readiness (20%) | Connectivity (15%) | Risk Factors (15%)

Output: public/data/opportunities.geojson
"""

import json
import math
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "public", "data")

SUBSTATIONS_FILE = os.path.join(DATA_DIR, "substations.geojson")
LMP_FILE = os.path.join(DATA_DIR, "lmp-nodes.geojson")
TERRITORIES_FILE = os.path.join(DATA_DIR, "utility-territories.geojson")
PLANTS_FILE = os.path.join(DATA_DIR, "power-plants.geojson")
BROWNFIELDS_FILE = os.path.join(DATA_DIR, "epa-brownfields.geojson")
QUEUE_FILE = os.path.join(DATA_DIR, "queue-withdrawals.geojson")
LMP_NODES_FILE = os.path.join(DATA_DIR, "lmp-nodes.geojson")
OUTPUT_FILE = os.path.join(DATA_DIR, "opportunities.geojson")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RADIUS_MILES = 3.0
RADIUS_METERS = int(RADIUS_MILES * 1609.34)  # ~4828 m
MIN_GREENFIELD_ACRES = 50
MIN_GREENFIELD_SQM = MIN_GREENFIELD_ACRES * 4046.86  # ~202,343 m^2
MIN_SUBSTATION_KV = 345
OVERPASS_DELAY_SEC = 10.0  # generous delay for public API
OVERPASS_MAX_RETRIES = 2
OVERPASS_BACKOFF_SEC = 30.0
CLUSTER_RADIUS_MILES = 25.0  # aggressive clustering = fewer queries
MAX_OSM_CLUSTERS = 20  # limit API queries to top clusters by voltage
MAX_OUTPUT = 200
SKIP_OSM = "--skip-osm" in sys.argv

# ── Scoring constants (same as score-sites.py) ──────────────────────────

FLOOD_RISK_STATES = {"LA", "FL", "TX", "MS", "AL", "SC", "NC"}
MODERATE_FLOOD_STATES = {"NJ", "DE", "MD", "VA", "GA", "CT", "RI", "MA", "HI"}

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
    "Nuclear": 50, "Petroleum Liquids": 70, "Petroleum Coke": 70,
    "Coal Integrated Gasification Combined Cycle": 80,
    "Other Gases": 65, "Other Waste Biomass": 55,
    "Wood/Wood Waste Biomass": 55, "Municipal Solid Waste": 45,
    "Landfill Gas": 40, "Conventional Hydroelectric": 30,
    "Onshore Wind Turbine": 20, "Solar Photovoltaic": 25,
    "Geothermal": 35, "All Other": 50,
}

CONTAMINATION_SCORES = {
    "Conventional Steam Coal": 45,
    "Coal Integrated Gasification Combined Cycle": 50,
    "Nuclear": 20, "Petroleum Liquids": 55, "Petroleum Coke": 50,
    "Municipal Solid Waste": 40, "Other Waste Biomass": 50,
    "Landfill Gas": 45,
    "Natural Gas Fired Combined Cycle": 85,
    "Natural Gas Fired Combustion Turbine": 85,
    "Natural Gas Steam Turbine": 80,
    "Wood/Wood Waste Biomass": 70, "Other Gases": 65,
    "Conventional Hydroelectric": 90,
    "Onshore Wind Turbine": 95, "Solar Photovoltaic": 95,
    "Geothermal": 60, "All Other": 60,
}


# ── Math utilities ───────────────────────────────────────────────────────


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def polygon_area_sqm(geometry_nodes):
    """Approximate area from Overpass geometry nodes [{"lat":..,"lon":..}]."""
    if len(geometry_nodes) < 3:
        return 0
    coords = [(n["lon"], n["lat"]) for n in geometry_nodes]
    avg_lat = sum(c[1] for c in coords) / len(coords)
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(avg_lat))
    pts = [(c[0] * m_per_deg_lon, c[1] * m_per_deg_lat) for c in coords]
    n = len(pts)
    area = 0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2


# ── Point-in-polygon (ray casting) ──────────────────────────────────────


def point_in_ring(lat, lon, ring):
    """Ray-casting. ring is [[lon,lat], ...] GeoJSON order."""
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]   # lon, lat
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_geometry(lat, lon, geometry):
    """Check if (lat, lon) is inside GeoJSON Polygon or MultiPolygon."""
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        if not point_in_ring(lat, lon, coords[0]):
            return False
        for hole in coords[1:]:
            if point_in_ring(lat, lon, hole):
                return False
        return True
    elif gtype == "MultiPolygon":
        for poly in coords:
            if point_in_ring(lat, lon, poly[0]):
                in_hole = False
                for hole in poly[1:]:
                    if point_in_ring(lat, lon, hole):
                        in_hole = True
                        break
                if not in_hole:
                    return True
    return False


# ── Scoring functions (mirrored from score-sites.py) ────────────────────


def compute_sub_distance(dist):
    return clamp(100 - dist * 2)


def compute_sub_voltage(max_volt):
    if max_volt >= 765:
        return 100
    elif max_volt >= 500:
        return 85
    elif max_volt >= 345:
        return 70
    return 60


def compute_gen_capacity(capacity):
    return clamp((capacity - 50) / 1950 * 100)


def compute_tx_lines(lines):
    return clamp(lines / 8 * 100)


def compute_queue_withdrawal(qw_count, qw_mw):
    if qw_count == 0:
        return 30
    count_score = clamp(30 + qw_count * 5, 30, 100)
    mw_bonus = clamp(qw_mw / 5000 * 20, 0, 20)
    return clamp(count_score + mw_bonus)


def compute_lmp_score(avg_lmp):
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


def compute_longitude(lon):
    if lon < -70:
        return clamp(100 - (lon + 70) * -1.2)
    return 100


def compute_latitude(lat):
    if 33 <= lat <= 43:
        return 90
    elif 28 <= lat <= 48:
        return 70
    return 40


def compute_broadband(state):
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


def is_coastal_location(lat, lon, state):
    if state in FLOOD_RISK_STATES:
        if state == "FL":
            return True
        if state == "LA":
            return lat < 31.0 or lon < -91.0
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


def compute_flood_zone(lat, lon, state):
    if is_coastal_location(lat, lon, state):
        return 35
    elif state in MODERATE_FLOOD_STATES:
        return 65
    return 90


def find_nearest_lmp(lat, lon, lmp_nodes):
    best_dist = float("inf")
    best = None
    for n in lmp_nodes:
        d = haversine_miles(lat, lon, n["lat"], n["lon"])
        if d < best_dist:
            best_dist = d
            best = n
    if not best:
        return "", 0, 50
    return best["name"], best["avg_lmp"], compute_lmp_score(best["avg_lmp"])


def score_site(site, sub_coords, qw_points, lmp_nodes):
    """Score an opportunity site using the 4-dimension model.

    Returns dict with all scoring fields matching ScoredSite interface.
    """
    lat = site["latitude"]
    lon = site["longitude"]
    state = site["state"]
    opp_type = site["opportunity_type"]

    # ── Nearest 345kV+ substation ──
    best_dist = float("inf")
    best_sub = None
    for sc in sub_coords:
        d = haversine_miles(lat, lon, sc["lat"], sc["lon"])
        if d < best_dist:
            best_dist = d
            best_sub = sc

    if not best_sub:
        return None

    # ── Queue withdrawals within 20 mi ──
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

    # ── LMP ──
    lmp_name, lmp_avg, lmp_s = find_nearest_lmp(lat, lon, lmp_nodes)

    # ── Time to Power (50%) ──
    dist_s = compute_sub_distance(best_dist)
    volt_s = compute_sub_voltage(best_sub["max_volt"])
    lines_s = compute_tx_lines(best_sub.get("lines") or 0)
    qw_s = compute_queue_withdrawal(qw_count, qw_total_mw)

    if opp_type == "retired_plant":
        cap = site.get("total_capacity_mw", 0)
        gen_s = compute_gen_capacity(cap)
        ttp = (dist_s * 0.21 + gen_s * 0.17 + volt_s * 0.13 +
               lines_s * 0.13 + qw_s * 0.21 + lmp_s * 0.15)
    else:
        gen_s = 0
        ttp = (dist_s * 0.30 + volt_s * 0.17 + lines_s * 0.17 +
               qw_s * 0.21 + lmp_s * 0.15)

    # ── Site Readiness (20%) ──
    if opp_type == "retired_plant":
        fuel_s = FUEL_TYPE_SCORES.get(site.get("fuel_type", ""), 50)
        cap = site.get("total_capacity_mw", 0)
        scale_s = clamp((cap - 50) / 1450 * 100)
        sr = fuel_s * 0.60 + scale_s * 0.40
    elif opp_type == "adaptive_reuse":
        fuel_s = 0
        scale_s = 0
        sr = 70   # existing industrial structure
    else:  # greenfield
        fuel_s = 0
        scale_s = 0
        sr = 55   # undeveloped land

    # ── Connectivity (15%) ──
    lon_s = compute_longitude(lon)
    lat_s = compute_latitude(lat)
    bb_s = compute_broadband(state)
    co = lon_s * 0.40 + lat_s * 0.30 + bb_s * 0.30

    # ── Risk Factors (15%) ──
    flood_s = compute_flood_zone(lat, lon, state)
    if opp_type == "retired_plant":
        contam_s = CONTAMINATION_SCORES.get(site.get("fuel_type", ""), 60)
        status_s = 80 if site.get("status") == "retiring" else 65
        rf = contam_s * 0.50 + status_s * 0.20 + flood_s * 0.30
    elif opp_type == "adaptive_reuse":
        contam_s = 55
        status_s = 0
        rf = contam_s * 0.65 + flood_s * 0.35
    else:  # greenfield
        contam_s = 85   # undeveloped, lower contamination risk
        status_s = 0
        rf = contam_s * 0.65 + flood_s * 0.35

    composite = ttp * 0.50 + sr * 0.20 + co * 0.15 + rf * 0.15
    composite = round(clamp(composite), 1)

    r = lambda v: round(v, 1)
    return {
        "plant_name": site["plant_name"],
        "state": state,
        "latitude": lat,
        "longitude": lon,
        "total_capacity_mw": site.get("total_capacity_mw", 0),
        "fuel_type": site.get("fuel_type", ""),
        "status": site.get("status", "opportunity"),
        "opportunity_type": opp_type,
        "qualifying_substation": site.get("qualifying_substation", ""),
        "qualifying_sub_kv": site.get("qualifying_sub_kv", 0),
        "composite_score": composite,
        "time_to_power": r(ttp),
        "site_readiness": r(sr),
        "connectivity": r(co),
        "risk_factors": r(rf),
        "sub_distance_score": r(dist_s),
        "sub_voltage_score": r(volt_s),
        "gen_capacity_score": r(gen_s),
        "tx_lines_score": r(lines_s),
        "queue_withdrawal_score": r(qw_s),
        "fuel_type_score": r(fuel_s),
        "capacity_scale_score": r(scale_s),
        "longitude_score": r(lon_s),
        "latitude_score": r(lat_s),
        "broadband_score": r(bb_s),
        "contamination_score": r(contam_s),
        "operational_status_score": r(status_s),
        "flood_zone_score": r(flood_s),
        "lmp_score": r(lmp_s),
        "nearest_lmp_avg": r(lmp_avg),
        "nearest_lmp_node": lmp_name,
        "nearest_sub_name": best_sub["name"],
        "nearest_sub_distance_miles": r(best_dist),
        "nearest_sub_voltage_kv": best_sub["max_volt"],
        "nearest_sub_lines": best_sub.get("lines", 0),
        "queue_count_20mi": qw_count,
        "queue_mw_20mi": r(qw_total_mw),
    }


# ── Overpass API ─────────────────────────────────────────────────────────


def query_overpass(lat, lon, attempt=0):
    """Query OSM for industrial buildings and land parcels within 3 mi.
    Retries with exponential backoff on 429/504 errors."""
    query = (
        "[out:json][timeout:60];\n"
        "(\n"
        "  way[\"building\"~\"^(industrial|warehouse|commercial|factory|manufacture)$\"]"
        "(around:{r},{lat},{lon});\n"
        "  way[\"man_made\"~\"^(works|wastewater_plant)$\"]"
        "(around:{r},{lat},{lon});\n"
        "  way[\"landuse\"=\"industrial\"][\"building\"!~\".\"]"
        "(around:{r},{lat},{lon});\n"
        "  way[\"landuse\"~\"^(farmland|meadow|grass)$\"]"
        "(around:{r},{lat},{lon});\n"
        ");\n"
        "out center geom tags;\n"
    ).format(r=RADIUS_METERS, lat=lat, lon=lon)

    try:
        data = urllib.parse.urlencode({"data": query}).encode("utf-8")
        req = urllib.request.Request(OVERPASS_URL, data=data)
        req.add_header("User-Agent", "GridSite-OpportunityFinder/1.0")
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("elements", [])
    except urllib.error.HTTPError as e:
        if e.code in (429, 504) and attempt < OVERPASS_MAX_RETRIES:
            wait = OVERPASS_BACKOFF_SEC * (attempt + 1)
            print("      {} — retrying in {:.0f}s (attempt {})...".format(
                e.code, wait, attempt + 2))
            time.sleep(wait)
            return query_overpass(lat, lon, attempt + 1)
        print("    Overpass HTTP error {}: {}".format(e.code, e.reason))
        return []
    except urllib.error.URLError as e:
        if attempt < OVERPASS_MAX_RETRIES:
            wait = OVERPASS_BACKOFF_SEC * (attempt + 1)
            print("      URL error — retrying in {:.0f}s...".format(wait))
            time.sleep(wait)
            return query_overpass(lat, lon, attempt + 1)
        print("    Overpass URL error: {}".format(e.reason))
        return []
    except Exception as e:
        print("    Overpass error: {}".format(e))
        return []


def classify_osm_element(elem):
    """Classify an OSM element. Returns (type, name, area_acres) or None."""
    tags = elem.get("tags", {})
    building = tags.get("building", "")
    landuse = tags.get("landuse", "")
    man_made = tags.get("man_made", "")

    name = tags.get("name", "")

    # Adaptive Reuse: existing structures
    if building in ("industrial", "warehouse", "commercial", "factory", "manufacture"):
        label = name or ("Industrial " + building.title())
        return "adaptive_reuse", label, 0
    if man_made in ("works", "wastewater_plant"):
        label = name or man_made.replace("_", " ").title()
        return "adaptive_reuse", label, 0
    if landuse == "industrial":
        label = name or "Industrial Zone"
        return "adaptive_reuse", label, 0

    # Greenfield: large vacant land
    if landuse in ("farmland", "meadow", "grass"):
        geom = elem.get("geometry", [])
        area_sqm = polygon_area_sqm(geom)
        area_acres = area_sqm / 4046.86
        if area_acres >= MIN_GREENFIELD_ACRES:
            label = name or "{:.0f}-Acre {} Parcel".format(area_acres, landuse.title())
            return "greenfield", label, area_acres

    return None


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    print("=" * 80)
    print("OPPORTUNITY FINDER")
    print("=" * 80)
    print()

    # ── 1. Load data ──────────────────────────────────────────────────────

    print("Loading data...")

    with open(SUBSTATIONS_FILE) as f:
        subs_geojson = json.load(f)
    with open(LMP_FILE) as f:
        lmp_geojson = json.load(f)
    with open(TERRITORIES_FILE) as f:
        terr_geojson = json.load(f)
    with open(PLANTS_FILE) as f:
        plants_geojson = json.load(f)
    with open(QUEUE_FILE) as f:
        queue_geojson = json.load(f)

    brownfield_sites = []
    if os.path.exists(BROWNFIELDS_FILE):
        with open(BROWNFIELDS_FILE) as f:
            bf_geojson = json.load(f)
        for feat in bf_geojson["features"]:
            p = feat["properties"]
            coords = feat["geometry"]["coordinates"]
            brownfield_sites.append({
                "lat": coords[1], "lon": coords[0],
                "name": p.get("name", "Unknown"),
                "state": p.get("state", ""),
                "city": p.get("city", ""),
            })
    print("  Brownfield sites: {:,}".format(len(brownfield_sites)))

    # Pre-extract data structures
    lmp_nodes = []
    for feat in lmp_geojson["features"]:
        c = feat["geometry"]["coordinates"]
        p = feat["properties"]
        lmp_nodes.append({
            "lat": c[1], "lon": c[0],
            "name": p.get("name", ""),
            "avg_lmp": float(p.get("avg_lmp", 40)),
            "lmp_class": p.get("lmp_class", "moderate"),
        })

    surplus_territories = []
    for feat in terr_geojson["features"]:
        p = feat["properties"]
        if p.get("ratio_class") == "surplus":
            surplus_territories.append({
                "name": p.get("name", ""),
                "state": p.get("state", ""),
                "geometry": feat["geometry"],
                "ratio": p.get("ratio"),
                # Pre-compute bounding box for fast rejection
                "bbox": compute_bbox(feat["geometry"]),
            })
    print("  Surplus utility territories: {}".format(len(surplus_territories)))

    # All 345kV+ substations for scoring
    all_hv_subs = []
    for feat in subs_geojson["features"]:
        p = feat["properties"]
        v = p.get("MAX_VOLT")
        if v is not None and float(v) >= 345:
            all_hv_subs.append({
                "lat": float(p["LATITUDE"]),
                "lon": float(p["LONGITUDE"]),
                "max_volt": float(p["MAX_VOLT"]),
                "lines": float(p.get("LINES") or 0),
                "name": p.get("NAME", ""),
                "state": p.get("STATE", ""),
            })
    print("  Substations >= 345kV: {:,}".format(len(all_hv_subs)))

    # Queue withdrawals for scoring
    qw_points = []
    for feat in queue_geojson["features"]:
        c = feat["geometry"]["coordinates"]
        p = feat["properties"]
        qw_points.append({
            "lat": c[1], "lon": c[0],
            "total_mw": float(p.get("total_mw") or 0),
        })
    print("  Queue withdrawals: {:,}".format(len(qw_points)))

    # Power plants (retired/retiring)
    retired_plants = []
    for feat in plants_geojson["features"]:
        p = feat["properties"]
        if p.get("status") in ("retired", "retiring"):
            retired_plants.append({
                "lat": p["latitude"], "lon": p["longitude"],
                "plant_name": p["plant_name"],
                "state": p["state"],
                "total_capacity_mw": p.get("total_capacity_mw", 0),
                "fuel_type": p.get("fuel_type", ""),
                "status": p["status"],
                "planned_retirement_date": p.get("planned_retirement_date"),
            })
    print("  Retired/retiring plants: {:,}".format(len(retired_plants)))

    # ── 2. Find qualifying substations ────────────────────────────────────

    print()
    print("Finding qualifying substations (345kV+ / low LMP / surplus territory)...")

    qualifying = []
    for sub in all_hv_subs:
        # Check nearest LMP node is "low"
        best_dist = float("inf")
        best_lmp = None
        for lmp in lmp_nodes:
            d = haversine_miles(sub["lat"], sub["lon"], lmp["lat"], lmp["lon"])
            if d < best_dist:
                best_dist = d
                best_lmp = lmp
        if not best_lmp or best_lmp["lmp_class"] != "low":
            continue

        # Check if within surplus territory (with bbox pre-filter)
        in_surplus = False
        terr_name = ""
        for terr in surplus_territories:
            bbox = terr["bbox"]
            if (sub["lat"] < bbox["minlat"] or sub["lat"] > bbox["maxlat"] or
                    sub["lon"] < bbox["minlon"] or sub["lon"] > bbox["maxlon"]):
                continue
            if point_in_geometry(sub["lat"], sub["lon"], terr["geometry"]):
                in_surplus = True
                terr_name = terr["name"]
                break

        if not in_surplus:
            continue

        sub["territory_name"] = terr_name
        sub["lmp_node"] = best_lmp["name"]
        sub["lmp_avg"] = best_lmp["avg_lmp"]
        qualifying.append(sub)

    print("  Qualifying substations: {}".format(len(qualifying)))

    if not qualifying:
        print("  No qualifying substations found. Check data overlap.")
        # Write empty output
        with open(OUTPUT_FILE, "w") as f:
            json.dump({"type": "FeatureCollection", "features": []}, f, indent=2)
        return

    # Print summary by state
    state_counts = {}
    for q in qualifying:
        st = q.get("state", "?")
        state_counts[st] = state_counts.get(st, 0) + 1
    for st, c in sorted(state_counts.items(), key=lambda x: -x[1]):
        print("    {}: {}".format(st, c))

    # ── 3. Cluster nearby qualifying subs to reduce Overpass queries ──────

    print()
    print("Clustering substations for Overpass queries...")
    clusters = cluster_substations(qualifying, CLUSTER_RADIUS_MILES)
    print("  Clusters (Overpass queries): {}".format(len(clusters)))

    # ── 4. Find opportunity sites ─────────────────────────────────────────

    print()
    print("Identifying opportunity sites...")

    # Key: (round(lat,3), round(lon,3)) for dedup (~100m precision)
    seen = set()
    raw_sites = []

    # 4a. Retired plants near qualifying substations
    print("  Scanning retired plants...")
    for sub in qualifying:
        for plant in retired_plants:
            d = haversine_miles(sub["lat"], sub["lon"], plant["lat"], plant["lon"])
            if d <= RADIUS_MILES:
                key = (round(plant["lat"], 3), round(plant["lon"], 3))
                if key in seen:
                    continue
                seen.add(key)
                raw_sites.append({
                    "plant_name": plant["plant_name"],
                    "state": plant["state"],
                    "latitude": plant["lat"],
                    "longitude": plant["lon"],
                    "total_capacity_mw": plant["total_capacity_mw"],
                    "fuel_type": plant["fuel_type"],
                    "status": plant["status"],
                    "planned_retirement_date": plant.get("planned_retirement_date"),
                    "opportunity_type": "retired_plant",
                    "qualifying_substation": sub["name"],
                    "qualifying_sub_kv": sub["max_volt"],
                })
    print("    Retired plants found: {}".format(
        sum(1 for s in raw_sites if s["opportunity_type"] == "retired_plant")))

    # 4b. Brownfields near qualifying substations
    print("  Scanning brownfield sites...")
    bf_count_before = len(raw_sites)
    for sub in qualifying:
        # Fast bounding-box pre-filter
        deg_delta = RADIUS_MILES / 69.0
        lon_delta = deg_delta / max(math.cos(math.radians(sub["lat"])), 0.01)
        for bf in brownfield_sites:
            if abs(bf["lat"] - sub["lat"]) > deg_delta:
                continue
            if abs(bf["lon"] - sub["lon"]) > lon_delta:
                continue
            d = haversine_miles(sub["lat"], sub["lon"], bf["lat"], bf["lon"])
            if d <= RADIUS_MILES:
                key = (round(bf["lat"], 3), round(bf["lon"], 3))
                if key in seen:
                    continue
                seen.add(key)
                raw_sites.append({
                    "plant_name": bf["name"],
                    "state": bf["state"],
                    "latitude": bf["lat"],
                    "longitude": bf["lon"],
                    "total_capacity_mw": 0,
                    "fuel_type": "Brownfield",
                    "status": "brownfield",
                    "opportunity_type": "adaptive_reuse",
                    "qualifying_substation": sub["name"],
                    "qualifying_sub_kv": sub["max_volt"],
                })
    print("    Brownfield sites found: {}".format(len(raw_sites) - bf_count_before))

    # 4c. OpenStreetMap query for each cluster
    osm_adaptive = 0
    osm_greenfield = 0
    if SKIP_OSM:
        print("  Skipping Overpass API (--skip-osm flag)")
    else:
        # Sort clusters by max voltage (highest first) and limit
        clusters.sort(key=lambda c: -max(s["max_volt"] for s in c["subs"]))
        osm_clusters = clusters[:MAX_OSM_CLUSTERS]
        print("  Querying OpenStreetMap Overpass API ({} of {} clusters)...".format(
            len(osm_clusters), len(clusters)))
        clusters = osm_clusters
    for ci, cluster in enumerate(clusters):
        if SKIP_OSM:
            break
        center_lat = cluster["lat"]
        center_lon = cluster["lon"]
        sub_names = [s["name"] for s in cluster["subs"]]
        sub_state = cluster["subs"][0].get("state", "")
        sub_name = cluster["subs"][0]["name"]
        sub_kv = max(s["max_volt"] for s in cluster["subs"])

        print("    Cluster {}/{}: [{:.2f}, {:.2f}] ({} subs, state={})".format(
            ci + 1, len(clusters), center_lat, center_lon,
            len(cluster["subs"]), sub_state))

        elements = query_overpass(center_lat, center_lon)
        print("      OSM elements returned: {}".format(len(elements)))

        debug_no_center = 0
        debug_no_classify = 0
        debug_tag_samples = []
        for elem in elements:
            center = elem.get("center", {})
            lat = center.get("lat")
            lon = center.get("lon")
            if lat is None or lon is None:
                debug_no_center += 1
                # Try getting coords from first geometry node
                geom = elem.get("geometry", [])
                if geom and isinstance(geom, list) and len(geom) > 0:
                    if isinstance(geom[0], dict):
                        lat = geom[0].get("lat")
                        lon = geom[0].get("lon")
                    elif isinstance(geom[0], (list, tuple)):
                        lat = geom[0][1] if len(geom[0]) > 1 else None
                        lon = geom[0][0] if len(geom[0]) > 0 else None
                if lat is None or lon is None:
                    continue

            result = classify_osm_element(elem)
            if result is None:
                debug_no_classify += 1
                if len(debug_tag_samples) < 3:
                    debug_tag_samples.append(elem.get("tags", {}))
                continue

            opp_type, label, area_acres = result

            key = (round(lat, 3), round(lon, 3))
            if key in seen:
                continue
            seen.add(key)

            site = {
                "plant_name": label,
                "state": sub_state,
                "latitude": lat,
                "longitude": lon,
                "total_capacity_mw": 0,
                "fuel_type": "Industrial" if opp_type == "adaptive_reuse" else "Greenfield",
                "status": "opportunity",
                "opportunity_type": opp_type,
                "qualifying_substation": sub_name,
                "qualifying_sub_kv": sub_kv,
            }
            if area_acres > 0:
                site["area_acres"] = round(area_acres, 1)
            raw_sites.append(site)

            if opp_type == "adaptive_reuse":
                osm_adaptive += 1
            else:
                osm_greenfield += 1

        if debug_no_center > 0 or debug_no_classify > 0:
            print("      (no center: {}, not classified: {})".format(
                debug_no_center, debug_no_classify))
        if debug_tag_samples:
            for tags in debug_tag_samples[:2]:
                print("        sample unclassified: {}".format(
                    {k: v for k, v in tags.items() if k in ("building", "landuse", "man_made", "name")}))

        if ci < len(clusters) - 1:
            time.sleep(OVERPASS_DELAY_SEC)

    print("    OSM adaptive reuse: {}".format(osm_adaptive))
    print("    OSM greenfield (50+ acres): {}".format(osm_greenfield))
    print("  Total raw opportunity sites: {}".format(len(raw_sites)))

    # ── 5. Score all sites ────────────────────────────────────────────────

    print()
    print("Scoring {} opportunity sites...".format(len(raw_sites)))

    scored = []
    for site in raw_sites:
        result = score_site(site, all_hv_subs, qw_points, lmp_nodes)
        if result:
            scored.append(result)

    # Sort by composite score, but reserve slots per type for diversity
    scored.sort(key=lambda x: -x["composite_score"])

    # Reserve at least MIN_PER_TYPE slots for each opportunity type
    MIN_PER_TYPE = 10
    by_type = {"retired_plant": [], "adaptive_reuse": [], "greenfield": []}
    for s in scored:
        by_type[s["opportunity_type"]].append(s)

    top = []
    used = set()
    # First pass: guarantee MIN_PER_TYPE from each type (best of each)
    for t in ("retired_plant", "greenfield", "adaptive_reuse"):
        for s in by_type[t][:MIN_PER_TYPE]:
            key = (s["latitude"], s["longitude"])
            if key not in used:
                top.append(s)
                used.add(key)
    # Second pass: fill remaining slots with highest-scoring sites overall
    for s in scored:
        if len(top) >= MAX_OUTPUT:
            break
        key = (s["latitude"], s["longitude"])
        if key not in used:
            top.append(s)
            used.add(key)
    top.sort(key=lambda x: -x["composite_score"])

    # ── 6. Output GeoJSON ─────────────────────────────────────────────────

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

    # ── 7. Print results ──────────────────────────────────────────────────

    type_counts = {"retired_plant": 0, "adaptive_reuse": 0, "greenfield": 0}
    for s in top:
        type_counts[s["opportunity_type"]] = type_counts.get(s["opportunity_type"], 0) + 1

    print()
    print("=" * 120)
    print("TOP 20 OPPORTUNITY SITES")
    print("=" * 120)
    header = "{:>3}  {:<32} {:>2}  {:>6}  {:>15}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:<20}".format(
        "#", "Site Name", "ST", "Score", "Type", "TTP", "SiteR", "Conn", "Risk", "SubMi", "Qualifying Sub"
    )
    print(header)
    print("-" * 120)
    for i, s in enumerate(top[:20]):
        name = s["plant_name"][:32]
        type_label = {"retired_plant": "Retired Plant", "adaptive_reuse": "Adaptive Reuse",
                       "greenfield": "Greenfield"}[s["opportunity_type"]]
        print("{:>3}  {:<32} {:>2}  {:>6}  {:>15}  {:>5}  {:>5}  {:>5}  {:>5}  {:>6}  {:<20}".format(
            i + 1, name, s["state"], s["composite_score"],
            type_label, s["time_to_power"], s["site_readiness"],
            s["connectivity"], s["risk_factors"],
            s["nearest_sub_distance_miles"],
            (s.get("qualifying_substation") or "")[:20],
        ))

    print()
    print("Output: {} ({} KB)".format(OUTPUT_FILE, file_size))
    print("Total opportunities: {} (of {} raw sites scored)".format(len(top), len(scored)))
    print("  Retired Plant:   {}".format(type_counts["retired_plant"]))
    print("  Adaptive Reuse:  {}".format(type_counts["adaptive_reuse"]))
    print("  Greenfield:      {}".format(type_counts["greenfield"]))


def compute_bbox(geometry):
    """Compute bounding box of a GeoJSON geometry."""
    min_lat = 90
    max_lat = -90
    min_lon = 180
    max_lon = -180

    def process_coords(coords):
        nonlocal min_lat, max_lat, min_lon, max_lon
        for c in coords:
            if isinstance(c[0], (list, tuple)):
                process_coords(c)
            else:
                lon, lat = c[0], c[1]
                if lat < min_lat:
                    min_lat = lat
                if lat > max_lat:
                    max_lat = lat
                if lon < min_lon:
                    min_lon = lon
                if lon > max_lon:
                    max_lon = lon

    process_coords(geometry.get("coordinates", []))
    return {"minlat": min_lat, "maxlat": max_lat, "minlon": min_lon, "maxlon": max_lon}


def cluster_substations(qualifying, radius_miles):
    """Cluster nearby qualifying substations to reduce Overpass queries."""
    used = [False] * len(qualifying)
    clusters = []

    for i, sub in enumerate(qualifying):
        if used[i]:
            continue
        cluster = {"subs": [sub], "lat": sub["lat"], "lon": sub["lon"]}
        used[i] = True

        for j in range(i + 1, len(qualifying)):
            if used[j]:
                continue
            d = haversine_miles(sub["lat"], sub["lon"],
                                qualifying[j]["lat"], qualifying[j]["lon"])
            if d <= radius_miles * 2:
                cluster["subs"].append(qualifying[j])
                used[j] = True

        # Recompute center as average
        lats = [s["lat"] for s in cluster["subs"]]
        lons = [s["lon"] for s in cluster["subs"]]
        cluster["lat"] = sum(lats) / len(lats)
        cluster["lon"] = sum(lons) / len(lons)
        clusters.append(cluster)

    return clusters


if __name__ == "__main__":
    main()
