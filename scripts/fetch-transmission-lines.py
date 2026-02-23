"""
Fetch HIFLD transmission lines from ArcGIS FeatureServer with pagination.
Filters to transmission-level lines (VOLTAGE >= 138 kV) and saves as GeoJSON.

Source: ArcGIS Online HIFLD Electric Power Transmission Lines (94,619 total records)
"""

import json
import os
import urllib.request
import urllib.parse
import time

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "public", "data", "transmission-lines.geojson")

BASE_URL = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/US_Electric_Power_Transmission_Lines/FeatureServer/0/query"
PAGE_SIZE = 2000  # server maxRecordCount
MIN_VOLTAGE_KV = 138

OUT_FIELDS = "ID,VOLTAGE,VOLT_CLASS,OWNER,STATUS,TYPE,SUB_1,SUB_2"


def fetch_page(offset):
    """Fetch a single page of filtered results via POST."""
    params = urllib.parse.urlencode({
        "where": "VOLTAGE >= " + str(MIN_VOLTAGE_KV),
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


def main():
    all_features = []
    offset = 0

    print("Fetching HIFLD transmission lines (VOLTAGE >= " + str(MIN_VOLTAGE_KV) + " kV)...")
    print("Source: " + BASE_URL.split("/query")[0])
    print()

    while True:
        print("  Fetching offset " + str(offset) + "...")
        data = fetch_page(offset)

        features = data.get("features", [])
        if len(features) == 0:
            break

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
    volt_classes = {}
    for feat in all_features:
        props = feat.get("properties", {})
        vc = props.get("VOLT_CLASS", "??")
        volt_classes[vc] = volt_classes.get(vc, 0) + 1

    print()
    print("Done!")
    print("  Transmission lines (>= " + str(MIN_VOLTAGE_KV) + " kV): " + str(len(all_features)))
    print("  Voltage classes: " + ", ".join(
        vc + "=" + str(c) for vc, c in sorted(volt_classes.items(), key=lambda x: -x[1])
    ))
    print("  Output: " + OUTPUT_FILE + " (" + str(file_size) + " MB)")


if __name__ == "__main__":
    main()
