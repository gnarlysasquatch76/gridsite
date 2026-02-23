"""
Fetch HIFLD substations from ArcGIS FeatureServer with pagination.
Filters to transmission-level substations (MAX_VOLT >= 138 kV)
and saves as GeoJSON.

Source: ArcGIS Online HIFLD Electric Substations (75,328 total records)
"""

import json
import os
import urllib.request
import urllib.parse
import time

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "public", "data", "substations.geojson")

BASE_URL = "https://services1.arcgis.com/PMShNXB1carltgVf/arcgis/rest/services/Electric_Substations/FeatureServer/0/query"
PAGE_SIZE = 1000  # server maxRecordCount
MIN_VOLTAGE_KV = 138

OUT_FIELDS = "NAME,CITY,STATE,COUNTY,TYPE,STATUS,LATITUDE,LONGITUDE,LINES,MAX_VOLT,MIN_VOLT"


def fetch_page(offset):
    """Fetch a single page of filtered results via POST."""
    params = urllib.parse.urlencode({
        "where": "CAST(MAX_VOLT AS FLOAT) >= " + str(MIN_VOLTAGE_KV),
        "outFields": OUT_FIELDS,
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": str(PAGE_SIZE),
        "resultOffset": str(offset),
    }).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE_URL, data=params, headers={"User-Agent": "GridSite/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                raise Exception("API error: " + str(data["error"]))
            return data
        except Exception as e:
            print("  Attempt " + str(attempt + 1) + " failed: " + str(e))
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                raise


def safe_float(val):
    """Convert a value to float, returning None if not possible."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def main():
    all_features = []
    offset = 0

    print("Fetching HIFLD substations (MAX_VOLT >= " + str(MIN_VOLTAGE_KV) + " kV)...")
    print("Source: " + BASE_URL.split("/query")[0])
    print()

    while True:
        print("  Fetching offset " + str(offset) + "...")
        data = fetch_page(offset)

        features = data.get("features", [])
        if len(features) == 0:
            break

        # Normalize MAX_VOLT/MIN_VOLT from strings to numbers
        for f in features:
            props = f.get("properties", {})
            props["MAX_VOLT"] = safe_float(props.get("MAX_VOLT"))
            props["MIN_VOLT"] = safe_float(props.get("MIN_VOLT"))

        all_features.extend(features)
        print("    Got " + str(len(features)) + " records, total " + str(len(all_features)))

        if len(features) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        time.sleep(0.5)

    geojson = {
        "type": "FeatureCollection",
        "features": all_features,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f)

    file_size = round(os.path.getsize(OUTPUT_FILE) / 1024 / 1024, 1)

    # Stats
    states = {}
    for feat in all_features:
        props = feat.get("properties", {})
        st = props.get("STATE", "??")
        states[st] = states.get(st, 0) + 1

    print()
    print("Done!")
    print("  Substations (>= " + str(MIN_VOLTAGE_KV) + " kV): " + str(len(all_features)))
    print("  States covered: " + str(len(states)))
    print("  Top 10 states: " + ", ".join(
        s + "=" + str(c) for s, c in sorted(states.items(), key=lambda x: -x[1])[:10]
    ))
    print("  Output: " + OUTPUT_FILE + " (" + str(file_size) + " MB)")


if __name__ == "__main__":
    main()
