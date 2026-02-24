"""
Fetch US data center locations from OpenStreetMap via the Overpass API.

Queries for telecom=data_center and building=data_center within the US,
deduplicates, and outputs to public/data/data-centers.geojson.
"""

import json
import os
import urllib.request

SCRIPT_DIR = os.path.dirname(__file__)
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "data-centers.geojson")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OVERPASS_QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="US"]->.usa;
(
  nwr["telecom"="data_center"](area.usa);
  nwr["building"="data_center"](area.usa);
);
out center;
"""

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


def main():
    print("Fetching US data centers from OpenStreetMap Overpass API...")
    print("  Query: telecom=data_center OR building=data_center in US")

    data = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode("utf-8")
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={
        "User-Agent": "GridSite/1.0",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    response = urllib.request.urlopen(req, timeout=300)
    result = json.loads(response.read().decode("utf-8"))

    elements = result.get("elements", [])
    print("  Raw elements: {:,}".format(len(elements)))

    # Extract and deduplicate
    seen = set()
    sites = []

    for el in elements:
        # Get coordinates — nodes have lat/lon directly, ways/relations have center
        lat = None
        lon = None
        if el["type"] == "node":
            lat = el.get("lat")
            lon = el.get("lon")
        elif "center" in el:
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")

        if lat is None or lon is None:
            continue

        # Filter to continental US + Hawaii + Alaska bounds
        if lat < 17 or lat > 72:
            continue
        if lon > -60 or lon < -180:
            continue

        tags = el.get("tags", {})
        name = tags.get("name", "")
        operator = tags.get("operator", "")
        # Some have brand or company instead
        if not operator:
            operator = tags.get("brand", "") or tags.get("company", "")

        # Deduplicate by rounding coords to ~10m precision
        dedup_key = "{:.4f},{:.4f}".format(lat, lon)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Extract additional useful tags
        addr_city = tags.get("addr:city", "")
        addr_state = tags.get("addr:state", "")
        addr_street = tags.get("addr:street", "")
        addr_housenumber = tags.get("addr:housenumber", "")
        address = ""
        if addr_housenumber and addr_street:
            address = addr_housenumber + " " + addr_street
        elif addr_street:
            address = addr_street

        power = tags.get("power", "")
        capacity = tags.get("capacity", "")
        building_levels = tags.get("building:levels", "")
        website = tags.get("website", "") or tags.get("contact:website", "")

        sites.append({
            "name": name,
            "operator": operator,
            "latitude": lat,
            "longitude": lon,
            "city": addr_city,
            "state": addr_state,
            "address": address,
            "capacity": capacity,
            "building_levels": building_levels,
            "website": website,
            "osm_type": el["type"],
            "osm_id": el["id"],
        })

    print("  Unique sites with coords: {:,}".format(len(sites)))

    # Build GeoJSON
    features = []
    for site in sites:
        props = {
            "name": site["name"] or "Data Center",
            "operator": site["operator"],
            "city": site["city"],
            "state": site["state"],
            "address": site["address"],
            "capacity": site["capacity"],
            "building_levels": site["building_levels"],
            "website": site["website"],
        }
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [site["longitude"], site["latitude"]],
            },
            "properties": props,
        })

    geojson = {"type": "FeatureCollection", "features": features}

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f)

    file_size = os.path.getsize(OUTPUT_FILE) / 1024
    print("")
    print("Output: " + OUTPUT_FILE)
    print("  Data Centers: {:,}".format(len(features)))
    print("  File size: {:.1f} KB".format(file_size))

    # Stats
    named = sum(1 for s in sites if s["name"])
    with_operator = sum(1 for s in sites if s["operator"])
    with_state = sum(1 for s in sites if s["state"])
    print("  Named: {:,}".format(named))
    print("  With operator: {:,}".format(with_operator))
    print("  With state: {:,}".format(with_state))

    # Top operators
    op_counts = {}
    for s in sites:
        op = s["operator"] or "(unknown)"
        op_counts[op] = op_counts.get(op, 0) + 1
    top_ops = sorted(op_counts.items(), key=lambda x: -x[1])[:15]
    print("  Top operators:")
    for op, count in top_ops:
        print("    {} ({})".format(op, count))


if __name__ == "__main__":
    main()
