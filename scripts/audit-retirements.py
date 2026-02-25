"""
Audit scored sites against EIA Form 860 generator-level data.

For every power plant in scored-sites.geojson and opportunities.geojson:
1. Look up all generators at that plant code in both Operating and Retired sheets
2. Flag plants where ANY generator is still active as "retooled/operating"
3. Flag plants where retirement date is after 2026
4. Produce a before/after summary showing reclassifications
"""

import json
import os
import openpyxl
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(__file__)
EIA_FILE = os.path.join(SCRIPT_DIR, "..", "data", "december_generator2025.xlsx")
SCORED_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "scored-sites.geojson")
OPPORTUNITIES_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "opportunities.geojson")
PLANTS_FILE = os.path.join(SCRIPT_DIR, "..", "public", "data", "power-plants.geojson")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "research", "retirement-audit.md")

HEADER_ROWS = 3


def safe_float(val):
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    f = safe_float(val)
    return int(f) if f is not None else None


def load_eia_generators(filepath):
    """Load ALL generators from EIA 860 into a dict keyed by plant_id."""
    print("Loading EIA Form 860 generator data...")
    wb = openpyxl.load_workbook(filepath, read_only=True)

    # Column mappings
    cols = {
        "Operating": {
            "plant_id": 2, "plant_name": 3, "generator_id": 4,
            "state": 6, "nameplate_mw": 12, "technology": 15,
            "energy_source": 16, "status_code": 22,
            "planned_ret_month": 20, "planned_ret_year": 21,
            "latitude": 35, "longitude": 36,
        },
        "Retired": {
            "plant_id": 2, "plant_name": 3, "generator_id": 4,
            "state": 6, "nameplate_mw": 12, "technology": 15,
            "energy_source": 16,
            "ret_month": 20, "ret_year": 21,
            "latitude": 24, "longitude": 25,
        },
    }

    # plant_id -> list of generator dicts
    generators = defaultdict(list)

    for sheet_name, col_map in cols.items():
        ws = wb[sheet_name]
        count = 0
        for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
            if row_idx < HEADER_ROWS:
                continue
            plant_id = row[col_map["plant_id"]]
            if plant_id is None:
                continue

            mw = safe_float(row[col_map["nameplate_mw"]]) or 0.0
            tech = str(row[col_map["technology"]] or "").strip()
            fuel = str(row[col_map["energy_source"]] or "").strip()
            gen_id = str(row[col_map.get("generator_id", 4)] or "").strip()
            plant_name = str(row[col_map["plant_name"]] or "").strip()
            state = str(row[col_map["state"]] or "").strip()
            lat = safe_float(row[col_map["latitude"]])
            lng = safe_float(row[col_map["longitude"]])

            if sheet_name == "Operating":
                status_code = str(row[col_map["status_code"]] or "").strip()
                ret_year = safe_int(row[col_map["planned_ret_year"]])
                ret_month = safe_int(row[col_map["planned_ret_month"]])
                sheet_status = "operating"
                # EIA status codes: OP=operating, SB=standby, OA/OS=out of service
                if status_code in ("RE", "CN"):
                    sheet_status = "retired"
                elif ret_year and ret_year > 0:
                    sheet_status = "retiring"
            else:
                ret_year = safe_int(row[col_map["ret_year"]])
                ret_month = safe_int(row[col_map["ret_month"]])
                sheet_status = "retired"
                status_code = "RE"

            generators[plant_id].append({
                "gen_id": gen_id,
                "plant_name": plant_name,
                "state": state,
                "mw": mw,
                "technology": tech,
                "fuel": fuel,
                "sheet": sheet_name,
                "sheet_status": sheet_status,
                "status_code": status_code,
                "ret_year": ret_year,
                "ret_month": ret_month,
                "lat": lat,
                "lng": lng,
            })
            count += 1
        print("  {} sheet: {:,} generators".format(sheet_name, count))

    wb.close()
    print("  Unique plant IDs: {:,}".format(len(generators)))
    return generators


def match_site_to_plant_id(site_props, generators):
    """Match a scored site to an EIA plant_id by name+state+coords."""
    name = site_props.get("plant_name", "").strip().lower()
    state = site_props.get("state", "").strip().upper()
    lat = site_props.get("latitude", 0)
    lng = site_props.get("longitude", 0)

    best_match = None
    best_score = -1

    for pid, gens in generators.items():
        first = gens[0]
        p_name = first["plant_name"].strip().lower()
        p_state = first["state"].strip().upper()
        p_lat = first.get("lat")
        p_lng = first.get("lng")

        # Name must be close match
        if p_state != state:
            continue

        # Exact name match
        if p_name == name:
            return pid

        # Check coordinate proximity (within ~0.01 degrees ~ 1km)
        if p_lat and p_lng and lat and lng:
            dlat = abs(p_lat - lat)
            dlng = abs(p_lng - lng)
            if dlat < 0.01 and dlng < 0.01:
                # Very close coords — likely same plant
                score = 100 - (dlat + dlng) * 1000
                if score > best_score:
                    best_score = score
                    best_match = pid

        # Partial name match
        if name in p_name or p_name in name:
            score = 50
            if best_score < score:
                best_score = score
                best_match = pid

    return best_match


def analyze_plant(plant_id, gens):
    """Analyze all generators at a plant. Returns analysis dict."""
    operating_gens = []
    retired_gens = []
    retiring_gens = []
    total_mw = 0
    operating_mw = 0
    retired_mw = 0

    fuels_operating = set()
    fuels_retired = set()
    latest_ret_year = None

    for g in gens:
        mw = g["mw"]
        total_mw += mw
        fuel = g["technology"] or g["fuel"]

        if g["sheet"] == "Operating" and g["sheet_status"] != "retired":
            if g["sheet_status"] == "retiring":
                retiring_gens.append(g)
                operating_mw += mw
                fuels_operating.add(fuel)
                if g["ret_year"]:
                    if latest_ret_year is None or g["ret_year"] > latest_ret_year:
                        latest_ret_year = g["ret_year"]
            else:
                operating_gens.append(g)
                operating_mw += mw
                fuels_operating.add(fuel)
        else:
            retired_gens.append(g)
            retired_mw += mw
            fuels_retired.add(fuel)
            if g["ret_year"]:
                if latest_ret_year is None or g["ret_year"] > latest_ret_year:
                    latest_ret_year = g["ret_year"]

    has_active = len(operating_gens) > 0 or len(retiring_gens) > 0
    has_retired = len(retired_gens) > 0
    fuel_change = bool(fuels_operating and fuels_retired and fuels_operating != fuels_retired)

    # Determine reclassification
    issues = []
    new_status = None

    if has_active and has_retired:
        issues.append("Has {} active + {} retired generators (retooled)".format(
            len(operating_gens) + len(retiring_gens), len(retired_gens)))
        new_status = "retooled"

    if has_active and not has_retired:
        issues.append("ALL {} generators still active (not retired at all)".format(
            len(operating_gens) + len(retiring_gens)))
        new_status = "still_operating"

    if fuel_change:
        issues.append("Fuel type changed: retired={}, active={}".format(
            ", ".join(sorted(fuels_retired)), ", ".join(sorted(fuels_operating))))

    if latest_ret_year and latest_ret_year > 2026:
        if not has_active:
            pass  # If truly retired, ret_year is historical
        else:
            issues.append("Retirement date {} is after 2026".format(latest_ret_year))
            if new_status is None:
                new_status = "retirement_too_far"

    # For retiring-only plants (no active non-retiring gens), check if retirement is far out
    if len(operating_gens) == 0 and len(retiring_gens) > 0 and len(retired_gens) == 0:
        if latest_ret_year and latest_ret_year > 2026:
            issues.append("All generators retiring but not until {}".format(latest_ret_year))
            new_status = "retirement_too_far"

    return {
        "total_gens": len(gens),
        "operating_gens": len(operating_gens),
        "retiring_gens": len(retiring_gens),
        "retired_gens": len(retired_gens),
        "total_mw": round(total_mw, 1),
        "operating_mw": round(operating_mw, 1),
        "retired_mw": round(retired_mw, 1),
        "fuels_operating": sorted(fuels_operating),
        "fuels_retired": sorted(fuels_retired),
        "fuel_change": fuel_change,
        "latest_ret_year": latest_ret_year,
        "issues": issues,
        "new_status": new_status,
    }


def main():
    generators = load_eia_generators(EIA_FILE)

    # Load scored sites and opportunities
    print("\nLoading scored sites and opportunities...")
    with open(SCORED_FILE) as f:
        scored = json.load(f)
    with open(OPPORTUNITIES_FILE) as f:
        opps = json.load(f)

    scored_plants = [f for f in scored["features"]
                     if f["properties"].get("site_type") == "power_plant"]
    opp_plants = [f for f in opps["features"]
                  if f["properties"].get("opportunity_type") == "retired_plant"]

    print("  Scored power plants: {}".format(len(scored_plants)))
    print("  Opportunity retired plants: {}".format(len(opp_plants)))

    # Combine and deduplicate
    all_plants = {}
    for f in scored_plants:
        p = f["properties"]
        key = (p["plant_name"], p["state"])
        all_plants[key] = {"props": p, "source": "scored", "feature": f}
    for f in opp_plants:
        p = f["properties"]
        name = p.get("plant_name") or p.get("name", "")
        state = p.get("state", "")
        key = (name, state)
        if key not in all_plants:
            all_plants[key] = {"props": p, "source": "opportunities", "feature": f}
        else:
            all_plants[key]["source"] = "both"

    print("  Unique plants to audit: {}".format(len(all_plants)))

    # Audit each plant
    print("\nAuditing against EIA generator data...")
    results = []
    matched = 0
    unmatched = 0

    for (name, state), info in sorted(all_plants.items()):
        props = info["props"]
        # Normalize props for matching
        match_props = {
            "plant_name": props.get("plant_name") or props.get("name", ""),
            "state": props.get("state", ""),
            "latitude": props.get("latitude", 0),
            "longitude": props.get("longitude", 0),
        }

        pid = match_site_to_plant_id(match_props, generators)

        if pid is None:
            unmatched += 1
            results.append({
                "name": name,
                "state": state,
                "source": info["source"],
                "current_status": props.get("status", "?"),
                "score": props.get("composite_score") or props.get("overall_score", 0),
                "mw": props.get("total_capacity_mw", 0),
                "plant_id": None,
                "matched": False,
                "analysis": None,
                "action": "NO_MATCH",
            })
            continue

        matched += 1
        analysis = analyze_plant(pid, generators[pid])

        action = "KEEP"
        if analysis["new_status"] == "retooled":
            action = "REMOVE_RETOOLED"
        elif analysis["new_status"] == "still_operating":
            action = "REMOVE_STILL_OPERATING"
        elif analysis["new_status"] == "retirement_too_far":
            action = "REMOVE_RETIREMENT_AFTER_2026"

        results.append({
            "name": name,
            "state": state,
            "source": info["source"],
            "current_status": props.get("status", "?"),
            "score": props.get("composite_score") or props.get("overall_score", 0),
            "mw": props.get("total_capacity_mw", 0),
            "plant_id": pid,
            "matched": True,
            "analysis": analysis,
            "action": action,
        })

    print("  Matched: {}".format(matched))
    print("  Unmatched: {}".format(unmatched))

    # Generate report
    keep = [r for r in results if r["action"] == "KEEP"]
    remove_retooled = [r for r in results if r["action"] == "REMOVE_RETOOLED"]
    remove_operating = [r for r in results if r["action"] == "REMOVE_STILL_OPERATING"]
    remove_future = [r for r in results if r["action"] == "REMOVE_RETIREMENT_AFTER_2026"]
    no_match = [r for r in results if r["action"] == "NO_MATCH"]

    print("\n" + "=" * 80)
    print("AUDIT RESULTS")
    print("=" * 80)
    print("  Total plants audited: {}".format(len(results)))
    print("  KEEP (truly retired, all gens retired, by 2026): {}".format(len(keep)))
    print("  REMOVE — retooled (active + retired gens): {}".format(len(remove_retooled)))
    print("  REMOVE — still operating (no retired gens): {}".format(len(remove_operating)))
    print("  REMOVE — retirement after 2026: {}".format(len(remove_future)))
    print("  UNMATCHED (brownfield/non-EIA): {}".format(len(no_match)))

    # Write markdown report
    lines = []
    lines.append("# Retirement Audit: Scored Sites vs EIA Form 860 Generator Data\n")
    lines.append("*Generated: 2026-02-24*\n")
    lines.append("## Summary\n")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    lines.append("| Total power plants audited | {} |".format(matched))
    lines.append("| **KEEP** — truly retired, all generators offline by 2026 | {} |".format(len(keep)))
    lines.append("| **REMOVE** — retooled (has active + retired generators) | {} |".format(len(remove_retooled)))
    lines.append("| **REMOVE** — still fully operating | {} |".format(len(remove_operating)))
    lines.append("| **REMOVE** — retirement date after 2026 | {} |".format(len(remove_future)))
    lines.append("| Unmatched (brownfield sites, no EIA plant code) | {} |".format(len(no_match)))
    lines.append("")

    # Reclassified sites detail
    if remove_retooled or remove_operating or remove_future:
        lines.append("---\n")
        lines.append("## Sites to Remove\n")

    if remove_retooled:
        lines.append("### Retooled Plants (Active + Retired Generators)\n")
        lines.append("These plants have some generators retired but others still operating — the plant was retooled, not abandoned.\n")
        lines.append("| Plant | State | MW | Source | Current Status | Active Gens | Retired Gens | Active Fuel | Retired Fuel |")
        lines.append("|-------|-------|----|--------|---------------|-------------|--------------|-------------|--------------|")
        for r in sorted(remove_retooled, key=lambda x: x["mw"], reverse=True):
            a = r["analysis"]
            lines.append("| {} | {} | {:,.0f} | {} | {} | {} ({:,.0f} MW) | {} ({:,.0f} MW) | {} | {} |".format(
                r["name"], r["state"], r["mw"], r["source"], r["current_status"],
                a["operating_gens"] + a["retiring_gens"], a["operating_mw"],
                a["retired_gens"], a["retired_mw"],
                ", ".join(a["fuels_operating"]), ", ".join(a["fuels_retired"]),
            ))
        lines.append("")

    if remove_operating:
        lines.append("### Still Fully Operating\n")
        lines.append("All generators at these plants are still in the EIA Operating sheet with no retirement.\n")
        lines.append("| Plant | State | MW | Source | Current Status | Generators | Fuel Types |")
        lines.append("|-------|-------|----|--------|---------------|------------|------------|")
        for r in sorted(remove_operating, key=lambda x: x["mw"], reverse=True):
            a = r["analysis"]
            lines.append("| {} | {} | {:,.0f} | {} | {} | {} ({:,.0f} MW) | {} |".format(
                r["name"], r["state"], r["mw"], r["source"], r["current_status"],
                a["operating_gens"] + a["retiring_gens"], a["operating_mw"],
                ", ".join(a["fuels_operating"]),
            ))
        lines.append("")

    if remove_future:
        lines.append("### Retirement After 2026\n")
        lines.append("These plants have announced retirement dates beyond 2026 — too early to score as opportunities.\n")
        lines.append("| Plant | State | MW | Source | Current Status | Retirement Year | Generators |")
        lines.append("|-------|-------|----|--------|---------------|-----------------|------------|")
        for r in sorted(remove_future, key=lambda x: x["analysis"]["latest_ret_year"] if x["analysis"] else 9999):
            a = r["analysis"]
            lines.append("| {} | {} | {:,.0f} | {} | {} | {} | {} active, {} retired |".format(
                r["name"], r["state"], r["mw"], r["source"], r["current_status"],
                a["latest_ret_year"],
                a["operating_gens"] + a["retiring_gens"], a["retired_gens"],
            ))
        lines.append("")

    # Kept sites
    lines.append("---\n")
    lines.append("## Sites Confirmed as Truly Retired (KEEP)\n")
    lines.append("All generators at these plants are in the EIA Retired sheet.\n")
    lines.append("| Plant | State | MW | Source | Retired Gens | Total Retired MW | Latest Retirement |")
    lines.append("|-------|-------|----|--------|-------------|-----------------|-------------------|")
    for r in sorted(keep, key=lambda x: x["mw"], reverse=True):
        a = r["analysis"]
        lines.append("| {} | {} | {:,.0f} | {} | {} | {:,.0f} | {} |".format(
            r["name"], r["state"], r["mw"], r["source"],
            a["retired_gens"], a["retired_mw"],
            a["latest_ret_year"] or "N/A",
        ))
    lines.append("")

    # Detailed issues for removed sites
    all_removed = remove_retooled + remove_operating + remove_future
    if all_removed:
        lines.append("---\n")
        lines.append("## Detailed Generator Breakdown (Removed Sites)\n")
        for r in sorted(all_removed, key=lambda x: x["name"]):
            a = r["analysis"]
            lines.append("### {} ({}) — {}\n".format(r["name"], r["state"], r["action"]))
            lines.append("- **Plant ID**: {}".format(r["plant_id"]))
            lines.append("- **Current scored status**: {}".format(r["current_status"]))
            lines.append("- **Total generators**: {} ({:,.1f} MW)".format(a["total_gens"], a["total_mw"]))
            lines.append("- **Operating**: {} gens ({:,.1f} MW)".format(a["operating_gens"], a["operating_mw"] if a["retiring_gens"] == 0 else 0))
            lines.append("- **Retiring**: {} gens".format(a["retiring_gens"]))
            lines.append("- **Retired**: {} gens ({:,.1f} MW)".format(a["retired_gens"], a["retired_mw"]))
            if a["fuels_operating"]:
                lines.append("- **Active fuel types**: {}".format(", ".join(a["fuels_operating"])))
            if a["fuels_retired"]:
                lines.append("- **Retired fuel types**: {}".format(", ".join(a["fuels_retired"])))
            if a["latest_ret_year"]:
                lines.append("- **Latest retirement year**: {}".format(a["latest_ret_year"]))
            for issue in a["issues"]:
                lines.append("- **Issue**: {}".format(issue))
            lines.append("")

    report = "\n".join(lines)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        f.write(report)
    print("\nReport saved to: {}".format(OUTPUT_FILE))

    # Now update the actual data files if there are removals
    if all_removed:
        removed_names = set()
        for r in all_removed:
            removed_names.add((r["name"], r["state"]))

        # Update power-plants.geojson: reclassify retooled/operating plants
        print("\nUpdating power-plants.geojson...")
        with open(PLANTS_FILE) as f:
            plants_data = json.load(f)

        reclassified = 0
        for feat in plants_data["features"]:
            p = feat["properties"]
            key = (p["plant_name"], p["state"])
            # Find matching audit result
            for r in all_removed:
                if r["name"] == p["plant_name"] and r["state"] == p["state"]:
                    if r["action"] in ("REMOVE_RETOOLED", "REMOVE_STILL_OPERATING"):
                        if p["status"] in ("retired", "retiring"):
                            p["status"] = "retooled"
                            reclassified += 1
                    elif r["action"] == "REMOVE_RETIREMENT_AFTER_2026":
                        if p["status"] == "retiring":
                            # Keep as retiring but these won't be scored
                            pass
                    break

        with open(PLANTS_FILE, "w") as f:
            json.dump(plants_data, f, indent=2)
        print("  Reclassified {} plants to 'retooled'".format(reclassified))

        # Update scored-sites.geojson: remove flagged plants
        print("Updating scored-sites.geojson...")
        before_scored = len(scored["features"])
        scored["features"] = [f for f in scored["features"]
                              if (f["properties"].get("plant_name", ""),
                                  f["properties"].get("state", "")) not in removed_names
                              or f["properties"].get("site_type") != "power_plant"]
        after_scored = len(scored["features"])
        with open(SCORED_FILE, "w") as f:
            json.dump(scored, f, indent=2)
        print("  Scored sites: {} -> {} (removed {})".format(
            before_scored, after_scored, before_scored - after_scored))

        # Update opportunities.geojson: remove flagged plants
        print("Updating opportunities.geojson...")
        before_opps = len(opps["features"])
        opps["features"] = [f for f in opps["features"]
                            if (f["properties"].get("plant_name") or f["properties"].get("name", ""),
                                f["properties"].get("state", "")) not in removed_names
                            or f["properties"].get("opportunity_type") != "retired_plant"]
        after_opps = len(opps["features"])
        with open(OPPORTUNITIES_FILE, "w") as f:
            json.dump(opps, f, indent=2)
        print("  Opportunities: {} -> {} (removed {})".format(
            before_opps, after_opps, before_opps - after_opps))

    print("\nDone!")


if __name__ == "__main__":
    main()
