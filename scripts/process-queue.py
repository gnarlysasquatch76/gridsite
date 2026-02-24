"""
Process LBNL Interconnection Queue data into GeoJSON for GridSite map.

Reads the "03. Complete Queue Data" sheet from the LBNL Excel file,
filters to withdrawn projects with total MW >= 50, geocodes via
Census county centroids using FIPS codes, and outputs GeoJSON.

Source: LBNL Interconnection Queue Data (thru 2024)
Geocoding: Census Bureau 2020 county population centroids
"""

import json
import math
import os
import urllib.request
import openpyxl

SCRIPT_DIR = os.path.dirname(__file__)
INPUT_FILE = os.path.join(SCRIPT_DIR, "..", "data", "LBNL_Ix_Queue_Data_File_thru2024_v2.xlsx")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "queue-withdrawals.geojson")

CENSUS_URL = "https://www2.census.gov/geo/docs/reference/cenpop2020/county/CenPop2020_Mean_CO.txt"

SHEET_NAME = "03. Complete Queue Data"
HEADER_ROW = 1  # row index of column names (0-based)
MIN_MW = 50

# Column indices (0-based)
COL_QID = 0
COL_STATUS = 1
COL_QDATE = 2
COL_WDDATE = 5
COL_COUNTY = 9
COL_STATE = 10
COL_FIPS = 12
COL_POI = 13
COL_REGION = 14
COL_PROJECT = 15
COL_ENTITY = 17
COL_MW1 = 25
COL_MW2 = 26
COL_MW3 = 27
COL_TYPE_CLEAN = 28


def safe_float(val):
    if val is None or str(val).strip() in ("", "NA"):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def safe_str(val):
    if val is None or str(val).strip() == "NA":
        return ""
    return str(val).strip()


def excel_date_to_str(val):
    """Convert Excel serial date number to YYYY-MM-DD string."""
    if val is None or str(val).strip() in ("", "NA"):
        return None
    try:
        serial = int(float(val))
    except (ValueError, TypeError):
        return None
    if serial < 1:
        return None
    # Excel epoch: 1900-01-01 = 1 (with the 1900 leap year bug)
    import datetime
    try:
        dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=serial)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def fetch_county_centroids():
    """Download Census 2020 county centroids, return dict of FIPS -> (lat, lon)."""
    print("  Downloading Census county centroids...")
    req = urllib.request.Request(CENSUS_URL, headers={"User-Agent": "GridSite/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    text = raw.decode("utf-8-sig")
    lines = text.strip().split("\n")

    centroids = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        state_fp = parts[0].strip()
        county_fp = parts[1].strip()
        lat = parts[5].strip()
        lon = parts[6].strip()
        try:
            fips = int(state_fp + county_fp)
            centroids[fips] = (float(lat), float(lon))
        except ValueError:
            continue

    print("    Loaded " + str(len(centroids)) + " county centroids")
    return centroids


def main():
    print("Loading data...")
    centroids = fetch_county_centroids()

    print("  Reading " + INPUT_FILE)
    wb = openpyxl.load_workbook(INPUT_FILE, read_only=True)
    ws = wb[SHEET_NAME]

    features = []
    skipped_no_fips = 0
    skipped_no_centroid = 0
    total_withdrawn = 0
    region_counts = {}

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i <= HEADER_ROW:
            continue

        status = safe_str(row[COL_STATUS])
        if status != "withdrawn":
            continue
        total_withdrawn += 1

        mw1 = safe_float(row[COL_MW1])
        mw2 = safe_float(row[COL_MW2])
        mw3 = safe_float(row[COL_MW3])
        total_mw = round(mw1 + mw2 + mw3, 1)

        if total_mw < MIN_MW:
            continue

        fips_raw = row[COL_FIPS]
        if fips_raw is None or str(fips_raw).strip() in ("", "NA"):
            skipped_no_fips += 1
            continue

        try:
            fips = int(float(str(fips_raw).strip()))
        except (ValueError, TypeError):
            skipped_no_fips += 1
            continue

        if fips not in centroids:
            skipped_no_centroid += 1
            continue

        lat, lon = centroids[fips]

        q_id = safe_str(row[COL_QID])
        project_name = safe_str(row[COL_PROJECT])
        state = safe_str(row[COL_STATE])
        county = safe_str(row[COL_COUNTY])
        poi_name = safe_str(row[COL_POI])
        entity = safe_str(row[COL_ENTITY])
        fuel_type = safe_str(row[COL_TYPE_CLEAN])
        region = safe_str(row[COL_REGION])
        q_date = excel_date_to_str(row[COL_QDATE])
        wd_date = excel_date_to_str(row[COL_WDDATE])

        props = {
            "q_id": q_id,
            "project_name": project_name if project_name else None,
            "state": state,
            "county": county,
            "poi_name": poi_name,
            "entity": entity,
            "total_mw": total_mw,
            "fuel_type": fuel_type,
            "region": region,
            "q_date": q_date,
            "wd_date": wd_date,
        }

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": props,
        })

        region_counts[region] = region_counts.get(region, 0) + 1

    wb.close()

    geojson = {"type": "FeatureCollection", "features": features}

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f, indent=2)

    file_size = round(os.path.getsize(OUTPUT_FILE) / 1024 / 1024, 1)

    print()
    print("Done!")
    print("  Total withdrawn projects: " + str(total_withdrawn))
    print("  Withdrawn >= " + str(MIN_MW) + " MW: " + str(len(features) + skipped_no_fips + skipped_no_centroid))
    print("  Skipped (no FIPS): " + str(skipped_no_fips))
    print("  Skipped (no centroid): " + str(skipped_no_centroid))
    print("  Output features: " + str(len(features)))
    print("  Output: " + OUTPUT_FILE + " (" + str(file_size) + " MB)")
    print()
    print("By ISO region:")
    for r, c in sorted(region_counts.items(), key=lambda x: -x[1]):
        print("  " + (r if r else "(unknown)") + ": " + str(c))


if __name__ == "__main__":
    main()
