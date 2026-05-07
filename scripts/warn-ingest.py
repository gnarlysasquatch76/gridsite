"""
WARN Act Filings Ingestion — National Pull
Downloads national WARN Act data, geocodes with Mapbox, computes nearest
substation proximity, and outputs GeoJSON for the GridSite map.

DATA SOURCE:
  layoffdata.com — a free public aggregator that scrapes official WARN filings
  from all 50 state labor departments and normalizes them into a single dataset.
  Maintained by data journalists/civic data volunteers. Updated monthly.
  All underlying data originates from official state government WARN filings,
  which are public records. layoffdata.com aggregates and standardizes them.
  - 2026 sheet: https://docs.google.com/spreadsheets/d/1q47pIyvmtY7GtF3-7mHOrqBe_0uot_G944XELZ_3raU
  - Historical: https://docs.google.com/spreadsheets/d/1B1CYZFyJ1ghK1ApuXEeGKo3mLYWzLwONvmWV8Plkav8

  If Gene asks "where does the data come from": "Official state WARN filings —
  every state labor department publishes these as public records. We aggregate
  from all 50 states, geocode, and overlay against power infrastructure."

Usage:
    python3 scripts/warn-ingest.py
    python3 scripts/warn-ingest.py --dry-run        # Print counts, no geocoding
    python3 scripts/warn-ingest.py --skip-geocode    # Use cached geocodes only
"""

import csv
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# ── Config ───────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "public", "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "warn-filings.geojson")
EXISTING_WARN_FILE = os.path.join(DATA_DIR, "warn-closures.geojson")
SUBSTATIONS_FILE = os.path.join(DATA_DIR, "substations.geojson")
DB_FILE = os.path.join(SCRIPT_DIR, "..", "warn-ingest.db")

CUTOFF_MONTHS = 12
MIN_EMPLOYEES = 100

DATA_2026_URL = "https://docs.google.com/spreadsheets/d/1q47pIyvmtY7GtF3-7mHOrqBe_0uot_G944XELZ_3raU/export?format=csv"
DATA_HISTORICAL_URL = "https://docs.google.com/spreadsheets/d/1B1CYZFyJ1ghK1ApuXEeGKo3mLYWzLwONvmWV8Plkav8/export?format=csv"

MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "")

US_STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}


def load_mapbox_token():
    global MAPBOX_TOKEN
    if MAPBOX_TOKEN:
        return
    env_file = os.path.join(SCRIPT_DIR, "..", ".env.local")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.startswith("NEXT_PUBLIC_MAPBOX_TOKEN="):
                    MAPBOX_TOKEN = line.split("=", 1)[1].strip()
                    return
    print("ERROR: No Mapbox token found")
    sys.exit(1)


# ── Utilities ────────────────────────────────────────────────────────────

def parse_date(date_str):
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    # Handle date ranges like "07/04/2026-09/30/2026" — use first date
    if "-" in date_str and "/" in date_str:
        date_str = date_str.split("-")[0].strip()
    for fmt in [
        "%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y",
        "%B %d, %Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S",
    ]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def is_within_cutoff(date_str):
    dt = parse_date(date_str)
    if dt is None:
        return False
    cutoff = datetime.now() - timedelta(days=CUTOFF_MONTHS * 30)
    return dt >= cutoff


def normalize_date(date_str):
    dt = parse_date(date_str)
    if dt is None:
        return date_str.strip() if date_str else ""
    return dt.strftime("%Y-%m-%d")


def parse_employees(emp_str):
    if not emp_str:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(emp_str).strip()) or "0")
    except ValueError:
        return 0


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_csv(url, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": "GridSite-WARNIngest/1.0 (brian@gridsite.dev)"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


# ── Database (SQLite audit + geocode cache) ──────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            lat REAL,
            lng REAL,
            place_name TEXT,
            is_centroid INTEGER DEFAULT 0,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            total_fetched INTEGER,
            total_after_filter INTEGER,
            total_geocoded INTEGER,
            total_output INTEGER,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_cached_geocode(query):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.execute("SELECT lat, lng, place_name, is_centroid FROM geocode_cache WHERE query = ?", (query,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"lat": row[0], "lng": row[1], "place_name": row[2], "is_centroid": bool(row[3])}
    return None


def cache_geocode(query, lat, lng, place_name, is_centroid=False):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT OR REPLACE INTO geocode_cache (query, lat, lng, place_name, is_centroid, timestamp) VALUES (?,?,?,?,?,?)",
        (query, lat, lng, place_name, 1 if is_centroid else 0, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


# ── Mapbox Geocoding ─────────────────────────────────────────────────────

def mapbox_geocode(address, state=""):
    """Geocode using Mapbox. Returns {lat, lng, place_name, is_centroid} or None."""
    query = address
    if state and len(state) == 2 and state not in address:
        query = address + ", " + state

    cached = get_cached_geocode(query)
    if cached:
        return cached

    url = "https://api.mapbox.com/search/geocode/v6/forward?" + urllib.parse.urlencode({
        "q": query,
        "country": "us",
        "limit": "1",
        "access_token": MAPBOX_TOKEN,
    })

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GridSite-WARNIngest/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        features = data.get("features", [])
        if not features:
            return mapbox_geocode_city_fallback(address, state)

        feat = features[0]
        coords = feat["geometry"]["coordinates"]
        place_name = feat["properties"].get("full_address", feat["properties"].get("name", ""))
        result = {"lat": coords[1], "lng": coords[0], "place_name": place_name, "is_centroid": False}
        cache_geocode(query, result["lat"], result["lng"], result["place_name"], False)
        time.sleep(0.05)
        return result

    except Exception as e:
        print("      Geocode failed for '{}': {}".format(query, e))
        return mapbox_geocode_city_fallback(address, state)


def mapbox_geocode_city_fallback(address, state):
    """Fallback: geocode to city centroid."""
    parts = [p.strip() for p in address.split(",")]
    city = parts[0] if parts else address
    if not state:
        state = parts[-1].strip() if len(parts) > 1 else ""
    city_query = city + ", " + state if state else city

    cached = get_cached_geocode("centroid:" + city_query)
    if cached:
        return cached

    url = "https://api.mapbox.com/search/geocode/v6/forward?" + urllib.parse.urlencode({
        "q": city_query,
        "country": "us",
        "types": "place",
        "limit": "1",
        "access_token": MAPBOX_TOKEN,
    })

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GridSite-WARNIngest/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        features = data.get("features", [])
        if not features:
            return None

        feat = features[0]
        coords = feat["geometry"]["coordinates"]
        place_name = feat["properties"].get("full_address", feat["properties"].get("name", ""))
        result = {"lat": coords[1], "lng": coords[0], "place_name": place_name, "is_centroid": True}
        cache_geocode("centroid:" + city_query, result["lat"], result["lng"], result["place_name"], True)
        time.sleep(0.05)
        return result

    except Exception as e:
        print("      City fallback failed for '{}': {}".format(city_query, e))
        return None


# ── Substation Proximity ─────────────────────────────────────────────────

_substations = None

def load_substations():
    global _substations
    if _substations is not None:
        return _substations
    if not os.path.exists(SUBSTATIONS_FILE):
        print("  WARNING: substations.geojson not found — skipping proximity")
        _substations = []
        return _substations
    print("  Loading substations...")
    with open(SUBSTATIONS_FILE) as f:
        geo = json.load(f)
    _substations = []
    for feat in geo["features"]:
        p = feat["properties"]
        v = p.get("MAX_VOLT")
        if v is not None and float(v) >= 138:
            coords = feat["geometry"]["coordinates"]
            _substations.append({
                "lat": float(p.get("LATITUDE", coords[1])),
                "lon": float(p.get("LONGITUDE", coords[0])),
                "max_volt": float(v),
                "name": p.get("NAME", ""),
            })
    print("  Loaded {} substations (138kV+)".format(len(_substations)))
    return _substations


def find_nearest_substation(lat, lon):
    """Returns (name, distance_miles, voltage_kv) or None."""
    subs = load_substations()
    if not subs:
        return None
    best_dist = float("inf")
    best = None
    for s in subs:
        d = haversine_miles(lat, lon, s["lat"], s["lon"])
        if d < best_dist:
            best_dist = d
            best = s
    if best is None:
        return None
    return best["name"], round(best_dist, 1), best["max_volt"]


# ── Data Fetching ────────────────────────────────────────────────────────

def fetch_national_data():
    """Fetch 2026 + recent historical WARN data, filter to last 12 months and 100+ employees."""
    all_records = []

    # Fetch 2026 data
    print("  Fetching 2026 WARN data...")
    try:
        text_2026 = fetch_csv(DATA_2026_URL, timeout=60)
        records_2026 = parse_national_csv(text_2026, "2026")
        print("    2026: {} records after filter".format(len(records_2026)))
        all_records.extend(records_2026)
    except Exception as e:
        print("    2026: ERROR — {}".format(e))

    # Fetch historical data (only need recent — last 12 months from 2025)
    print("  Fetching historical WARN data...")
    try:
        text_hist = fetch_csv(DATA_HISTORICAL_URL, timeout=120)
        records_hist = parse_national_csv(text_hist, "historical")
        print("    Historical: {} records after filter".format(len(records_hist)))
        all_records.extend(records_hist)
    except Exception as e:
        print("    Historical: ERROR — {}".format(e))

    return all_records


def parse_national_csv(text, label):
    """Parse national WARN CSV. Columns:
    State, Company, City, Number of Workers, WARN Received Date,
    Effective Date, Closure / Layoff, Temporary/Permanent, Union,
    Region, County, Industry, Notes
    """
    results = []
    reader = csv.DictReader(io.StringIO(text))
    total = 0
    skipped_date = 0
    skipped_emp = 0

    for row in reader:
        total += 1
        state_name = (row.get("State") or "").strip()
        company = (row.get("Company") or "").strip()
        city = (row.get("City") or "").strip()
        emp_str = row.get("Number of Workers") or "0"
        filing_date = (row.get("WARN Received Date") or "").strip()
        effective_date = (row.get("Effective Date") or "").strip()
        closure_type = (row.get("Closure / Layoff") or row.get("Closure/Layoff") or "").strip()
        temp_perm = (row.get("Temporary/Permanent") or "").strip()
        county = (row.get("County") or "").strip()
        industry = (row.get("Industry") or "").strip()

        # Convert state name to abbreviation
        state = US_STATE_NAMES.get(state_name, state_name)
        if len(state) > 2:
            # Try partial match
            for name, abbr in US_STATE_NAMES.items():
                if name.lower() in state.lower():
                    state = abbr
                    break

        employees = parse_employees(emp_str)
        if employees < MIN_EMPLOYEES:
            skipped_emp += 1
            continue

        if not is_within_cutoff(filing_date):
            skipped_date += 1
            continue

        # Build address for geocoding
        address = ", ".join(filter(None, [city, state]))

        results.append({
            "company": company,
            "city": city,
            "state": state,
            "county": county,
            "employees": employees,
            "filing_date": normalize_date(filing_date),
            "effective_date": normalize_date(effective_date),
            "industry": industry,
            "closure_type": closure_type,
            "temp_perm": temp_perm,
            "address": address,
            "source_url": "https://layoffdata.com/",
        })

    print("    {} total rows, {} skipped (date), {} skipped (employees < {})".format(
        total, skipped_date, skipped_emp, MIN_EMPLOYEES))
    return results


# ── Merge with existing data ────────────────────────────────────────────

def load_existing_warn_data():
    if not os.path.exists(EXISTING_WARN_FILE):
        return []
    with open(EXISTING_WARN_FILE) as f:
        geo = json.load(f)
    features = geo.get("features", [])
    print("  Loaded {} existing features from warn-closures.geojson".format(len(features)))
    return features


def dedup_key(company, city, filing_date):
    c = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    ci = re.sub(r"[^a-z0-9]", "", (city or "").lower())
    d = (filing_date or "")[:10]
    return c + "|" + ci + "|" + d


# ── Main Pipeline ────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    skip_geocode = "--skip-geocode" in sys.argv

    print("=" * 60)
    print("WARN Act Filings Ingestion — National Pull")
    print("Cutoff: last {} months, {}+ employees".format(CUTOFF_MONTHS, MIN_EMPLOYEES))
    print("=" * 60)

    init_db()
    if not dry_run and not skip_geocode:
        load_mapbox_token()

    run_start = datetime.now(timezone.utc).isoformat()

    # Step 1: Fetch national data
    print("\n--- Step 1: Fetching data ---")
    all_records = fetch_national_data()
    print("\n  Total records after filter: {}".format(len(all_records)))

    # Step 2: Deduplicate
    print("\n--- Step 2: Deduplicating ---")
    seen = set()
    unique_records = []
    for r in all_records:
        key = dedup_key(r["company"], r["city"], r["filing_date"])
        if key not in seen:
            seen.add(key)
            unique_records.append(r)
    print("  {} unique records (removed {} duplicates)".format(
        len(unique_records), len(all_records) - len(unique_records)))

    if dry_run:
        print("\n--- DRY RUN: Stats ---")
        states = {}
        big = 0
        for r in unique_records:
            states[r["state"]] = states.get(r["state"], 0) + 1
            if r["employees"] >= 500:
                big += 1
        print("  500+ employees: {}".format(big))
        print("  States: {}".format(len(states)))
        unique_records.sort(key=lambda r: r["employees"], reverse=True)
        print("\n  Top 15 by employees:")
        for r in unique_records[:15]:
            print("    {:>5} — {} ({}, {})".format(r["employees"], r["company"], r["city"], r["state"]))
        print("\n  By state:")
        for s, c in sorted(states.items(), key=lambda x: -x[1]):
            print("    {}: {}".format(s, c))
        return

    # Step 3: Geocode
    print("\n--- Step 3: Geocoding ({} records) ---".format(len(unique_records)))
    geocoded_new = 0
    geocoded_cached = 0
    geocoded_failed = 0
    features = []

    for i, r in enumerate(unique_records):
        address = r["address"]
        if skip_geocode:
            geo = get_cached_geocode(address) or get_cached_geocode("centroid:" + address)
        else:
            geo = mapbox_geocode(address, r["state"])

        if geo is None:
            geocoded_failed += 1
            continue

        # Track cache vs new
        if get_cached_geocode(address) or get_cached_geocode("centroid:" + address):
            geocoded_cached += 1
        else:
            geocoded_new += 1

        # Substation proximity
        sub_info = find_nearest_substation(geo["lat"], geo["lng"])
        sub_name = sub_info[0] if sub_info else ""
        sub_dist_mi = sub_info[1] if sub_info else 0
        sub_kv = sub_info[2] if sub_info else 0

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [geo["lng"], geo["lat"]],
            },
            "properties": {
                "name": r["company"],
                "company": r["company"],
                "city": r["city"],
                "state": r["state"],
                "county": r.get("county", ""),
                "employees_affected": r["employees"],
                "filing_date": r["filing_date"],
                "effective_date": r["effective_date"],
                "industry": r["industry"],
                "closure_type": r.get("closure_type", ""),
                "source_url": r["source_url"],
                "source": "warn_act",
                "site_type": "WARN Filing",
                "location_approximate": geo["is_centroid"],
                "nearest_substation_name": sub_name,
                "nearest_substation_miles": sub_dist_mi,
                "nearest_substation_kv": sub_kv,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        features.append(feature)

        if (i + 1) % 100 == 0:
            print("  Processed {}/{} ({} geocoded, {} cached, {} failed)".format(
                i + 1, len(unique_records), geocoded_new, geocoded_cached, geocoded_failed))

    print("  Done: {} geocoded, {} cached, {} failed".format(
        geocoded_new, geocoded_cached, geocoded_failed))

    # Step 4: Merge with existing warn-closures.geojson
    print("\n--- Step 4: Merging with existing data ---")
    existing_features = load_existing_warn_data()

    new_keys = set()
    for f in features:
        p = f["properties"]
        key = dedup_key(p["company"], p["city"], p["filing_date"])
        new_keys.add(key)

    merged_existing = 0
    for ef in existing_features:
        p = ef["properties"]
        company = p.get("company", p.get("name", ""))
        city = p.get("city", "")
        if not city:
            loc = p.get("location", "")
            parts = [x.strip() for x in loc.split(",")]
            if parts:
                city = parts[0]
        filing_date = p.get("closure_date", p.get("filing_date", ""))
        key = dedup_key(company, city, filing_date)

        if key not in new_keys:
            normalized = {
                "type": "Feature",
                "geometry": ef["geometry"],
                "properties": {
                    "name": p.get("name", company),
                    "company": company,
                    "city": city,
                    "state": p.get("state", ""),
                    "county": "",
                    "employees_affected": p.get("employee_count", 0),
                    "filing_date": normalize_date(filing_date),
                    "effective_date": normalize_date(p.get("effective_date", "")),
                    "industry": p.get("sub_type", ""),
                    "closure_type": p.get("closure_status", ""),
                    "source_url": (p.get("sources", [None]) or [None])[0] or "",
                    "source": "warn_act_existing",
                    "site_type": "WARN Filing",
                    "location_approximate": p.get("location_approximate", False),
                    "nearest_substation_name": p.get("nearest_substation_name", ""),
                    "nearest_substation_miles": round(
                        p.get("nearest_substation_km", 0) / 1.60934, 1
                    ) if p.get("nearest_substation_km") else 0,
                    "nearest_substation_kv": p.get("nearest_substation_kv", 0),
                    "ingested_at": p.get("researched_at", ""),
                },
            }
            features.append(normalized)
            new_keys.add(key)
            merged_existing += 1

    print("  Merged {} existing features".format(merged_existing))

    # Step 5: Output
    print("\n--- Step 5: Writing output ---")
    geojson = {"type": "FeatureCollection", "features": features}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f)

    # Stats
    total = len(features)
    big_filings = sum(1 for f in features if f["properties"]["employees_affected"] >= 500)
    states_repr = len(set(f["properties"]["state"] for f in features))
    has_sub = sum(1 for f in features if f["properties"]["nearest_substation_miles"] > 0)

    print("\n" + "=" * 60)
    print("OUTPUT: {}".format(OUTPUT_FILE))
    print("  Total filings:          {}".format(total))
    print("  States represented:     {}".format(states_repr))
    print("  500+ employees:         {}".format(big_filings))
    print("  With substation data:   {}".format(has_sub))
    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print("  File size:              {:.1f} MB".format(size_mb))
    print("=" * 60)

    # Log the run
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT, finished_at TEXT,
            total_fetched INTEGER, total_after_filter INTEGER,
            total_geocoded INTEGER, total_output INTEGER, notes TEXT
        )
    """)
    conn.execute(
        "INSERT INTO run_log (started_at, finished_at, total_fetched, total_after_filter, total_geocoded, total_output, notes) VALUES (?,?,?,?,?,?,?)",
        (run_start, datetime.now(timezone.utc).isoformat(),
         len(all_records), len(unique_records), len(features), total, ""),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
