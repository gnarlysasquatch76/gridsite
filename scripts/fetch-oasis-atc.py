"""
Fetch Available Transfer Capability (ATC) data from US ISO OASIS portals.

Curated ATC interface data for 6 ISOs:
  PJM, NYISO, ISO-NE, MISO, SPP, CAISO

Geocodes each interface to its source substation location using HIFLD data.
For NYISO, attempts to fetch real data from public CSV archive.
For all others, uses representative ATC values from ISO annual reports.

Output: public/data/oasis-atc.geojson
"""

import csv
import io
import json
import math
import os
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(__file__)
SUBSTATIONS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "substations.geojson")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "oasis-atc.geojson")

# ATC thresholds for classification (MW)
ATC_HIGH = 200     # >= 200 MW = high (green)
ATC_LOW = 50       # < 50 MW = low (red)

# ── Interface definitions with source/sink substations and fallback ATC ──
# source_sub/sink_sub are HIFLD substation NAME values (uppercase) for geocoding.
# fallback_atc_mw are representative values from ISO annual reports and OASIS postings.

INTERFACES = [
    # ── PJM Interfaces ───────────────────────────────────────────────────
    {"name": "AP South", "iso": "PJM", "source_sub": "BEDINGTON", "sink_sub": "BLACK OAK", "fallback_atc_mw": 1850},
    {"name": "Bedington-Black Oak", "iso": "PJM", "source_sub": "BEDINGTON", "sink_sub": "BLACK OAK", "fallback_atc_mw": 1200},
    {"name": "West Interface", "iso": "PJM", "source_sub": "SAMMIS", "sink_sub": "STAR", "fallback_atc_mw": 3500},
    {"name": "5004/5005 Interface", "iso": "PJM", "source_sub": "CONASTONE", "sink_sub": "PEACH BOTTOM", "fallback_atc_mw": 2800},
    {"name": "Central East Interface", "iso": "PJM", "source_sub": "BRANCHBURG", "sink_sub": "ELROY", "fallback_atc_mw": 2200},
    {"name": "CETO East", "iso": "PJM", "source_sub": "DEANS", "sink_sub": "SAYREVILLE", "fallback_atc_mw": 1600},
    {"name": "PJM-MISO Interface", "iso": "PJM", "source_sub": "BREED", "sink_sub": "SULLIVAN", "fallback_atc_mw": 3200},
    {"name": "PJM-NYISO Interface", "iso": "PJM", "source_sub": "BRANCHBURG", "sink_sub": "RAMAPO", "fallback_atc_mw": 1900},
    {"name": "PJM South", "iso": "PJM", "source_sub": "CARSON", "sink_sub": "POSSUM POINT", "fallback_atc_mw": 4100},
    {"name": "PEPCO Import", "iso": "PJM", "source_sub": "CHALK POINT", "sink_sub": "BRIGHTSEAT", "fallback_atc_mw": 1400},

    # ── NYISO Interfaces ─────────────────────────────────────────────────
    {"name": "Central East", "iso": "NYISO", "source_sub": "MARCY", "sink_sub": "NEW SCOTLAND", "fallback_atc_mw": 2750},
    {"name": "Total East", "iso": "NYISO", "source_sub": "NEW SCOTLAND", "sink_sub": "PLEASANT VALLEY", "fallback_atc_mw": 3950},
    {"name": "UPNY-SENY", "iso": "NYISO", "source_sub": "LEEDS", "sink_sub": "PLEASANT VALLEY", "fallback_atc_mw": 5150},
    {"name": "Dysinger East", "iso": "NYISO", "source_sub": "DYSINGER", "sink_sub": "ROCHESTER", "fallback_atc_mw": 1700},
    {"name": "Moses-South", "iso": "NYISO", "source_sub": "MOSES", "sink_sub": "WILLIS", "fallback_atc_mw": 1100},
    {"name": "West Central", "iso": "NYISO", "source_sub": "ROCHESTER", "sink_sub": "CLAY", "fallback_atc_mw": 1950},
    {"name": "Dunwoodie-Shore Rd", "iso": "NYISO", "source_sub": "DUNWOODIE", "sink_sub": "SHORE ROAD", "fallback_atc_mw": 3150},
    {"name": "Cross Sound Cable", "iso": "NYISO", "source_sub": "SHORE ROAD", "sink_sub": "EAST HAVEN", "fallback_atc_mw": 330},
    {"name": "NY-NE Interface", "iso": "NYISO", "source_sub": "MARCY", "sink_sub": "NEW SCOTLAND", "fallback_atc_mw": 1400},

    # ── ISO-NE Interfaces ────────────────────────────────────────────────
    {"name": "NE-NY AC Ties", "iso": "ISO-NE", "source_sub": "SANDY POND", "sink_sub": "ALPS", "fallback_atc_mw": 1200},
    {"name": "Orrington South", "iso": "ISO-NE", "source_sub": "ORRINGTON", "sink_sub": "SUROWIEC", "fallback_atc_mw": 1150},
    {"name": "Boston Import", "iso": "ISO-NE", "source_sub": "SANDY POND", "sink_sub": "MILLBURY", "fallback_atc_mw": 4600},
    {"name": "CT Import", "iso": "ISO-NE", "source_sub": "MILLSTONE", "sink_sub": "NORWALK", "fallback_atc_mw": 3400},
    {"name": "SEMA/RI Export", "iso": "ISO-NE", "source_sub": "BRAYTON POINT", "sink_sub": "WEST MEDWAY", "fallback_atc_mw": 2800},
    {"name": "Maine Import", "iso": "ISO-NE", "source_sub": "ORRINGTON", "sink_sub": "CHESTER", "fallback_atc_mw": 1050},
    {"name": "North-South", "iso": "ISO-NE", "source_sub": "GRANITE", "sink_sub": "SANDY POND", "fallback_atc_mw": 2600},
    {"name": "NE-NB Interface", "iso": "ISO-NE", "source_sub": "ORRINGTON", "sink_sub": "KEENE ROAD", "fallback_atc_mw": 1000},
    {"name": "Cross Sound Cable (NE)", "iso": "ISO-NE", "source_sub": "EAST HAVEN", "sink_sub": "SHORE ROAD", "fallback_atc_mw": 330},

    # ── MISO Interfaces ──────────────────────────────────────────────────
    {"name": "MISO-PJM Interface", "iso": "MISO", "source_sub": "SULLIVAN", "sink_sub": "BREED", "fallback_atc_mw": 3200},
    {"name": "Michigan-Ontario", "iso": "MISO", "source_sub": "LAMBTON", "sink_sub": "ST CLAIR", "fallback_atc_mw": 1500},
    {"name": "MISO North-South", "iso": "MISO", "source_sub": "PRAIRIE ISLAND", "sink_sub": "LANSING", "fallback_atc_mw": 2000},
    {"name": "MISO South Import", "iso": "MISO", "source_sub": "DELTA", "sink_sub": "WEST POINT", "fallback_atc_mw": 2800},
    {"name": "MISO-SPP North", "iso": "MISO", "source_sub": "SIBLEY", "sink_sub": "OVERTON", "fallback_atc_mw": 1600},
    {"name": "MISO-SPP South", "iso": "MISO", "source_sub": "ACADIANA", "sink_sub": "HARTBURG", "fallback_atc_mw": 800},
    {"name": "MISO-TVA Interface", "iso": "MISO", "source_sub": "WILSON", "sink_sub": "DRESDEN", "fallback_atc_mw": 1200},
    {"name": "MISO Central Corridor", "iso": "MISO", "source_sub": "QUAD CITIES", "sink_sub": "NELSON DEWEY", "fallback_atc_mw": 2100},

    # ── SPP Interfaces ───────────────────────────────────────────────────
    {"name": "SPP-MISO North", "iso": "SPP", "source_sub": "OVERTON", "sink_sub": "SIBLEY", "fallback_atc_mw": 1600},
    {"name": "SPP-MISO South", "iso": "SPP", "source_sub": "HARTBURG", "sink_sub": "ACADIANA", "fallback_atc_mw": 800},
    {"name": "SPP-AECI Interface", "iso": "SPP", "source_sub": "NEOSHO", "sink_sub": "RIVERTON", "fallback_atc_mw": 650},
    {"name": "SPP North-South", "iso": "SPP", "source_sub": "WOODWARD", "sink_sub": "COMANCHE", "fallback_atc_mw": 2300},
    {"name": "SPP-ERCOT DC Tie", "iso": "SPP", "source_sub": "OKLAUNION", "sink_sub": "VERNON", "fallback_atc_mw": 220},
    {"name": "SPP West Corridor", "iso": "SPP", "source_sub": "TUCO", "sink_sub": "HITCHLAND", "fallback_atc_mw": 1400},
    {"name": "SPP-WAPA Interface", "iso": "SPP", "source_sub": "FORT THOMPSON", "sink_sub": "BIG BEND", "fallback_atc_mw": 400},
    {"name": "SPP Kansas Corridor", "iso": "SPP", "source_sub": "WICHITA", "sink_sub": "WOLF CREEK", "fallback_atc_mw": 1800},

    # ── CAISO Interfaces ─────────────────────────────────────────────────
    {"name": "Path 15 (N-S)", "iso": "CAISO", "source_sub": "LOS BANOS", "sink_sub": "GATES", "fallback_atc_mw": 2700},
    {"name": "Path 26 (N-S)", "iso": "CAISO", "source_sub": "MIDWAY", "sink_sub": "VINCENT", "fallback_atc_mw": 3700},
    {"name": "COI (Pacific AC)", "iso": "CAISO", "source_sub": "MALIN", "sink_sub": "ROUND MOUNTAIN", "fallback_atc_mw": 4800},
    {"name": "PDCI (Pacific DC)", "iso": "CAISO", "source_sub": "SYLMAR", "sink_sub": "CELILO", "fallback_atc_mw": 3100},
    {"name": "SCE Import", "iso": "CAISO", "source_sub": "LUGO", "sink_sub": "MIRA LOMA", "fallback_atc_mw": 5800},
    {"name": "SDG&E Import", "iso": "CAISO", "source_sub": "MIGUEL", "sink_sub": "IMPERIAL VALLEY", "fallback_atc_mw": 3900},
    {"name": "Eldorado-Ivanpah", "iso": "CAISO", "source_sub": "ELDORADO", "sink_sub": "IVANPAH", "fallback_atc_mw": 2200},
    {"name": "Palo Verde Interface", "iso": "CAISO", "source_sub": "PALO VERDE", "sink_sub": "DEVERS", "fallback_atc_mw": 5200},
]


# ── NYISO public ATC fetcher ────────────────────────────────────────────


def fetch_nyiso_atc():
    """
    Attempt to fetch ATC data from NYISO public OASIS CSV archive.
    Returns dict mapping interface name to average ATC MW, or empty dict on failure.
    """
    sample_dates = [
        "20240115", "20240415", "20240715", "20241015",
    ]

    interface_atcs = {}  # interface_name -> list of ATC values
    fetched_count = 0

    for date_str in sample_dates:
        url = "http://mis.nyiso.com/public/csv/atc_ttc/{}atc_ttc.csv".format(date_str)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GridSite-ETL/1.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read()

            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")

            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                iface = row.get("Interface Name", "").strip()
                atc_str = row.get("ATC (MW)", "").strip()
                if not iface or not atc_str:
                    continue
                try:
                    atc = float(atc_str)
                except ValueError:
                    continue
                if iface not in interface_atcs:
                    interface_atcs[iface] = []
                interface_atcs[iface].append(atc)

            fetched_count += 1
            print("    Fetched NYISO ATC {}".format(date_str))

        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
            print("    Failed NYISO ATC {}: {}".format(date_str, e))
            continue

    if fetched_count == 0:
        return {}

    averages = {}
    for iface, vals in interface_atcs.items():
        averages[iface] = round(sum(vals) / len(vals), 1)

    print("    NYISO ATC: {} days fetched, {} interfaces averaged".format(fetched_count, len(averages)))
    return averages


# ── Geocoding ────────────────────────────────────────────────────────────


def build_substation_lookup(subs_geojson):
    """Build name -> (lon, lat) lookup from substations GeoJSON."""
    lookup = {}
    for feat in subs_geojson["features"]:
        p = feat["properties"]
        name = (p.get("NAME") or "").upper().strip()
        if not name:
            continue
        coords = feat["geometry"]["coordinates"]
        if name not in lookup:
            v = float(p.get("MAX_VOLT") or 0)
            lookup[name] = {"lon": coords[0], "lat": coords[1], "max_volt": v}
        else:
            # Keep higher voltage sub if duplicate name
            v = float(p.get("MAX_VOLT") or 0)
            if v > lookup[name]["max_volt"]:
                lookup[name] = {"lon": coords[0], "lat": coords[1], "max_volt": v}
    return lookup


def geocode_interface(iface, sub_lookup):
    """
    Match source_sub to substation coords.
    Returns (lon, lat) or None.
    """
    source = iface["source_sub"]
    if source in sub_lookup:
        return sub_lookup[source]["lon"], sub_lookup[source]["lat"]

    # Try partial match
    for name, data in sub_lookup.items():
        if source in name or name in source:
            return data["lon"], data["lat"]

    return None


# ── Main ─────────────────────────────────────────────────────────────────


def classify_atc(avg_atc_mw):
    """Classify ATC level: high (green), moderate (yellow), low (red)."""
    if avg_atc_mw >= ATC_HIGH:
        return "high"
    elif avg_atc_mw >= ATC_LOW:
        return "moderate"
    else:
        return "low"


def main():
    print("Fetching OASIS ATC data from ISOs...")
    print("")

    # Load substations for geocoding
    print("  Loading substations for geocoding...")
    if not os.path.exists(SUBSTATIONS_FILE):
        print("  ERROR: substations.geojson not found")
        return
    with open(SUBSTATIONS_FILE) as f:
        subs_geojson = json.load(f)
    sub_lookup = build_substation_lookup(subs_geojson)
    print("  Substation name lookup: {} entries".format(len(sub_lookup)))

    # Attempt to fetch real data from NYISO
    print("")
    print("  NYISO (public CSV archive):")
    nyiso_data = fetch_nyiso_atc()

    # Map NYISO interface names to our curated entries
    nyiso_name_map = {
        "Central East": "Central East",
        "Total East": "Total East",
        "UPNY-SENY": "UPNY-SENY",
        "Dysinger East": "Dysinger East",
        "Moses South": "Moses-South",
    }

    # Build output features
    features = []
    iso_counts = {}
    real_count = 0
    fallback_count = 0
    geocode_failures = []

    for iface in INTERFACES:
        avg_atc = iface["fallback_atc_mw"]
        source = "curated_fallback"

        # Check if we have real NYISO data
        if iface["iso"] == "NYISO":
            for nyiso_key, our_name in nyiso_name_map.items():
                if iface["name"] == our_name and nyiso_key in nyiso_data:
                    avg_atc = nyiso_data[nyiso_key]
                    source = "nyiso_api"
                    real_count += 1
                    break
            else:
                fallback_count += 1
        else:
            fallback_count += 1

        # Geocode
        coords = geocode_interface(iface, sub_lookup)
        if coords is None:
            geocode_failures.append(iface["name"] + " (" + iface["source_sub"] + ")")
            continue

        atc_class = classify_atc(avg_atc)

        iso = iface["iso"]
        if iso not in iso_counts:
            iso_counts[iso] = {"total": 0, "high": 0, "moderate": 0, "low": 0}
        iso_counts[iso]["total"] += 1
        iso_counts[iso][atc_class] += 1

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [coords[0], coords[1]],
            },
            "properties": {
                "name": iface["name"],
                "iso": iface["iso"],
                "avg_atc_mw": avg_atc,
                "atc_class": atc_class,
                "source_sub": iface["source_sub"],
                "sink_sub": iface["sink_sub"],
                "source": source,
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f, indent=2)

    file_size = round(os.path.getsize(OUTPUT_FILE) / 1024, 1)

    # Print summary
    print("")
    print("=" * 90)
    print("OASIS ATC INTERFACE SUMMARY")
    print("=" * 90)
    print("{:>10}  {:>6}  {:>6}  {:>6}  {:>6}".format("ISO", "Ifaces", "High", "Mod", "Low"))
    print("-" * 90)
    for iso in ["PJM", "NYISO", "ISO-NE", "MISO", "SPP", "CAISO"]:
        c = iso_counts.get(iso, {"total": 0, "high": 0, "moderate": 0, "low": 0})
        print("{:>10}  {:>6}  {:>6}  {:>6}  {:>6}".format(
            iso, c["total"], c["high"], c["moderate"], c["low"]
        ))

    total = len(features)
    print("-" * 90)
    print("{:>10}  {:>6}  {:>6}  {:>6}  {:>6}".format(
        "TOTAL", total,
        sum(c["high"] for c in iso_counts.values()),
        sum(c["moderate"] for c in iso_counts.values()),
        sum(c["low"] for c in iso_counts.values()),
    ))

    if geocode_failures:
        print("")
        print("Geocode failures ({} interfaces):".format(len(geocode_failures)))
        for name in geocode_failures:
            print("  - " + name)

    print("")
    print("Data sources: {} interfaces from API, {} from curated fallback".format(real_count, fallback_count))
    print("Thresholds: Green >= {} MW, Yellow {}-{} MW, Red < {} MW".format(
        ATC_HIGH, ATC_LOW, ATC_HIGH, ATC_LOW
    ))
    print("Output: {} ({} KB, {} features)".format(OUTPUT_FILE, file_size, total))

    # Print all interfaces sorted by ATC
    print("")
    print("{:>3}  {:<30} {:>7}  {:>8}  {:>10}  {:>10}".format(
        "#", "Interface", "ISO", "ATC MW", "Class", "Source"))
    print("-" * 80)
    sorted_features = sorted(features, key=lambda f: -f["properties"]["avg_atc_mw"])
    for i, f in enumerate(sorted_features):
        p = f["properties"]
        marker = "*" if p["source"] != "curated_fallback" else ""
        print("{:>3}  {:<30} {:>7}  {:>8}  {:>10}  {:>10}{}".format(
            i + 1, p["name"][:30], p["iso"], p["avg_atc_mw"],
            p["atc_class"], p["source"][:10], marker
        ))
    if real_count > 0:
        print("")
        print("  * = data from ISO API (not curated fallback)")


if __name__ == "__main__":
    main()
