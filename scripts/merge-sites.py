"""
Merge all site sources into a single unified GeoJSON file.

Combines:
  - scored-sites.geojson (power plants + brownfields from score-sites.py)
  - opportunities.geojson (opportunity sites from find-opportunities.py)
  - warn-closures.geojson (WARN Act closures from stranded_capacity.py)
  - industrial-closures.geojson (news scan closures from stranded_capacity.py)

Deduplicates by proximity (0.5 mile radius) — keeps the feature with more data.
Outputs: public/data/all-sites.geojson
"""

import json
import math
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "public", "data")

INPUT_FILES = [
    ("scored-sites.geojson", "scored"),
    ("opportunities.geojson", "opportunities"),
    ("warn-closures.geojson", "warn"),
    ("industrial-closures.geojson", "news"),
]

OUTPUT_FILE = os.path.join(DATA_DIR, "all-sites.geojson")
DEDUP_RADIUS_MILES = 0.5


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def feature_richness(feat):
    """Score how much data a feature has (for dedup preference)."""
    p = feat.get("properties", {})
    score = 0
    for key, val in p.items():
        if val is not None and val != "" and val != 0:
            score += 1
    # Prefer scored sites and sites with composite scores
    if p.get("composite_score"):
        score += 20
    if p.get("estimated_mw"):
        score += 5
    if p.get("employee_count"):
        score += 5
    return score


def main():
    print("=" * 70)
    print("MERGE SITES")
    print("=" * 70)

    all_features = []
    source_counts = {}

    for filename, label in INPUT_FILES:
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            print("  SKIP {} — not found".format(filename))
            source_counts[label] = 0
            continue
        with open(filepath) as f:
            geo = json.load(f)
        features = geo.get("features", [])
        source_counts[label] = len(features)
        all_features.extend(features)
        print("  {} — {} features".format(filename, len(features)))

    print()
    print("  Total before dedup: {}".format(len(all_features)))

    # Deduplicate by proximity
    # Sort by richness descending so we keep the best feature
    all_features.sort(key=lambda f: -feature_richness(f))

    kept = []
    kept_coords = []  # (lat, lon) for fast proximity check

    for feat in all_features:
        coords = feat.get("geometry", {}).get("coordinates", [0, 0])
        lat = coords[1]
        lon = coords[0]

        # Check proximity to already-kept features
        is_dup = False
        for klat, klon in kept_coords:
            if abs(klat - lat) > 0.01 and abs(klon - lon) > 0.01:
                continue
            if haversine_miles(lat, lon, klat, klon) < DEDUP_RADIUS_MILES:
                is_dup = True
                break

        if not is_dup:
            kept.append(feat)
            kept_coords.append((lat, lon))

    dupes_removed = len(all_features) - len(kept)
    print("  Duplicates removed: {}".format(dupes_removed))
    print("  Total after dedup:  {}".format(len(kept)))

    # Write output
    output = {"type": "FeatureCollection", "features": kept}
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    file_size = round(os.path.getsize(OUTPUT_FILE) / 1024, 1)
    print()
    print("  Output: {} ({} KB)".format(OUTPUT_FILE, file_size))

    # Breakdown
    type_counts = {}
    for feat in kept:
        p = feat.get("properties", {})
        st = p.get("site_type", p.get("opportunity_type", "unknown"))
        type_counts[st] = type_counts.get(st, 0) + 1
    print("  By type:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print("    {:30s} {}".format(t, c))


if __name__ == "__main__":
    main()
