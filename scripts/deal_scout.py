"""
Deal Scout — Availability & competitor research agent for GridSite.

Reads scored-sites.geojson and opportunities.geojson, uses the Anthropic API
with web search to research each site's availability status, and writes
structured results to availability.json. All research calls are logged to
a local SQLite database for auditability.

Usage:
    python deal_scout.py                        # Research all sites
    python deal_scout.py --top 50               # Research only top N sites
    python deal_scout.py --site "Homer City"    # Research a single site by name
    python deal_scout.py --force                # Ignore cache, re-research all
    python deal_scout.py --dry-run              # Show what would be researched
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import anthropic

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "public", "data")
SCORED_FILE = os.path.join(DATA_DIR, "scored-sites.geojson")
OPPORTUNITIES_FILE = os.path.join(DATA_DIR, "opportunities.geojson")
OUTPUT_FILE = os.path.join(DATA_DIR, "availability.json")
DB_FILE = os.path.join(SCRIPT_DIR, "..", "deal_scout.db")

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1500
CONCURRENCY = 5
CACHE_DAYS = 7

# Cost per token (Sonnet pricing as of 2025)
INPUT_COST_PER_TOKEN = 3.0 / 1_000_000
OUTPUT_COST_PER_TOKEN = 15.0 / 1_000_000


def build_site_key(site):
    """Build a unique key for a site from name + state + coords."""
    name = site.get("plant_name", "Unknown")
    state = site.get("state", "")
    lat = round(site.get("latitude", 0), 3)
    lon = round(site.get("longitude", 0), 3)
    return "{}|{}|{},{}".format(name, state, lat, lon)


def build_research_prompt(site):
    """Build the per-site research prompt for Claude."""
    name = site.get("plant_name", "Unknown")
    state = site.get("state", "")
    capacity = site.get("total_capacity_mw", 0)
    lat = site.get("latitude", 0)
    lon = site.get("longitude", 0)
    fuel = site.get("fuel_type", "")
    status = site.get("status", "")
    opp_type = site.get("opportunity_type", "")

    if opp_type == "retired_plant" or status in ("retired", "retiring"):
        site_type = "Retired Power Plant"
    elif opp_type == "adaptive_reuse" or fuel == "Brownfield":
        site_type = "Brownfield / Industrial"
    elif opp_type == "greenfield":
        site_type = "Greenfield"
    else:
        site_type = "Power Plant ({})".format(status)

    capacity_str = "{} MW".format(capacity) if capacity > 0 else "N/A"

    return (
        "You are a commercial real estate research analyst specializing in "
        "data center site selection. Research the following site and return "
        "ONLY a JSON object with your findings. No other text.\n\n"
        "Site: {name}\n"
        "Location: {state}\n"
        "Type: {site_type}\n"
        "Capacity: {capacity}\n"
        "Coordinates: {lat}, {lon}\n\n"
        "Research these questions:\n"
        "1. Is this site currently available for redevelopment, or has it been "
        "claimed/sold/leased?\n"
        "2. Are there any active data center development proposals or competitor "
        "activity at this site?\n"
        "3. Is there active environmental remediation (coal ash, superfund, "
        "brownfield cleanup) that would delay development?\n"
        "4. Who currently owns the site or land?\n"
        "5. Are there any recent news articles, planning filings, or transactions "
        "involving this site?\n\n"
        'Return ONLY this JSON:\n'
        '{{\n'
        '  "status": "available" | "competitor_activity" | "taken" | '
        '"still_operating" | "environmental_hold" | "unknown",\n'
        '  "confidence": "high" | "medium" | "low",\n'
        '  "owner": "string or null",\n'
        '  "competitor": "string or null if competitor identified",\n'
        '  "competitor_details": "string or null",\n'
        '  "environmental_issues": "string or null",\n'
        '  "recent_activity": "brief summary of most relevant finding",\n'
        '  "sources": ["url1", "url2"],\n'
        '  "notes": "any other relevant context"\n'
        '}}'
    ).format(
        name=name,
        state=state,
        site_type=site_type,
        capacity=capacity_str,
        lat=lat,
        lon=lon,
    )


def parse_response(text):
    """Extract JSON from Claude's response text."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code block
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue

    # Try to find JSON object in text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None


# ── Database ──────────────────────────────────────────────────────────────


def init_db_sync():
    """Create the database and table if they don't exist (synchronous)."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_log (
            site_key TEXT PRIMARY KEY,
            site_name TEXT,
            state TEXT,
            status TEXT,
            confidence TEXT,
            response_json TEXT,
            prompt TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            researched_at TEXT,
            model TEXT
        )
    """)
    conn.commit()
    conn.close()


async def get_cached(db, site_key, force=False):
    """Check if a site was researched within CACHE_DAYS. Returns row or None."""
    if force:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)).isoformat()
    async with db.execute(
        "SELECT response_json, researched_at FROM research_log "
        "WHERE site_key = ? AND researched_at > ?",
        (site_key, cutoff),
    ) as cursor:
        row = await cursor.fetchone()
    return row


async def save_result(db, site_key, site, result, prompt, input_tokens, output_tokens, cost):
    """Save or update a research result in the database."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT OR REPLACE INTO research_log
        (site_key, site_name, state, status, confidence, response_json,
         prompt, input_tokens, output_tokens, cost_usd, researched_at, model)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            site_key,
            site.get("plant_name", "Unknown"),
            site.get("state", ""),
            result.get("status", "unknown"),
            result.get("confidence", "low"),
            json.dumps(result),
            prompt,
            input_tokens,
            output_tokens,
            cost,
            now,
            MODEL,
        ),
    )
    await db.commit()


# ── Research ──────────────────────────────────────────────────────────────


async def research_site(client, db, site, semaphore, stats, force=False):
    """Research a single site using the Anthropic API with web search."""
    site_key = build_site_key(site)
    name = site.get("plant_name", "Unknown")
    state = site.get("state", "")

    # Check cache
    cached = await get_cached(db, site_key, force)
    if cached:
        result = json.loads(cached[0])
        stats["skipped_cached"] += 1
        print("  CACHED  {:.<50} {} ({})".format(
            name[:48] + " ", result.get("status", "?"), cached[1][:10]
        ))
        return site_key, result, cached[1]

    prompt = build_research_prompt(site)

    async with semaphore:
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text from response
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = (input_tokens * INPUT_COST_PER_TOKEN +
                    output_tokens * OUTPUT_COST_PER_TOKEN)

            stats["input_tokens"] += input_tokens
            stats["output_tokens"] += output_tokens
            stats["cost"] += cost

            result = parse_response(text)
            if result is None:
                result = {
                    "status": "unknown",
                    "confidence": "low",
                    "owner": None,
                    "competitor": None,
                    "competitor_details": None,
                    "environmental_issues": None,
                    "recent_activity": "Failed to parse response",
                    "sources": [],
                    "notes": "Raw response: " + text[:500],
                }

            now = datetime.now(timezone.utc).isoformat()
            await save_result(db, site_key, site, result, prompt,
                              input_tokens, output_tokens, cost)

            status = result.get("status", "unknown")
            confidence = result.get("confidence", "?")
            status_icon = {
                "available": "AVAIL",
                "taken": "TAKEN",
                "competitor_activity": "COMP",
                "still_operating": "OPER",
                "environmental_hold": "ENV",
                "unknown": "UNK",
            }.get(status, "???")

            stats["researched"] += 1
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            print("  {:6s}  {:.<50} {} conf={} (${:.3f})".format(
                status_icon, name[:48] + " ", state, confidence, cost
            ))

            return site_key, result, now

        except anthropic.APIError as e:
            stats["errors"] += 1
            print("  ERROR   {:.<50} {} — {}".format(name[:48] + " ", state, e))
            error_result = {
                "status": "unknown",
                "confidence": "low",
                "owner": None,
                "competitor": None,
                "competitor_details": None,
                "environmental_issues": None,
                "recent_activity": "API error: {}".format(str(e)),
                "sources": [],
                "notes": None,
            }
            return site_key, error_result, datetime.now(timezone.utc).isoformat()


# ── Main ──────────────────────────────────────────────────────────────────


def load_sites():
    """Load and deduplicate sites from scored-sites.geojson and opportunities.geojson."""
    sites = {}

    for filepath in [SCORED_FILE, OPPORTUNITIES_FILE]:
        if not os.path.exists(filepath):
            print("  Warning: {} not found, skipping".format(filepath))
            continue
        with open(filepath) as f:
            geojson = json.load(f)
        for feat in geojson["features"]:
            p = feat["properties"]
            coords = feat["geometry"]["coordinates"]
            site = dict(p)
            site["latitude"] = coords[1]
            site["longitude"] = coords[0]
            key = build_site_key(site)
            if key not in sites:
                sites[key] = site

    return sites


async def run(args):
    """Main async entry point."""
    print("=" * 70)
    print("DEAL SCOUT — Site Availability Research Agent")
    print("=" * 70)
    print()

    # Load sites
    print("Loading sites...")
    all_sites = load_sites()
    print("  Total unique sites: {}".format(len(all_sites)))

    # Filter sites
    site_list = list(all_sites.values())

    if args.site:
        query = args.site.lower()
        site_list = [s for s in site_list
                     if query in s.get("plant_name", "").lower()]
        if not site_list:
            print("  No sites matching '{}'".format(args.site))
            sys.exit(1)
        print("  Matched {} site(s) for '{}'".format(len(site_list), args.site))
    elif args.top:
        site_list.sort(key=lambda s: -s.get("composite_score", 0))
        site_list = site_list[:args.top]
        print("  Using top {} sites by score".format(len(site_list)))

    if args.dry_run:
        print()
        print("DRY RUN — would research {} sites:".format(len(site_list)))
        print("-" * 70)
        for i, site in enumerate(site_list):
            print("  {:>3}. {} ({}) — score {}".format(
                i + 1,
                site.get("plant_name", "?"),
                site.get("state", "?"),
                site.get("composite_score", "?"),
            ))
        return

    # Check API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print()
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Init
    init_db_sync()
    client = anthropic.Anthropic()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    stats = {
        "researched": 0,
        "skipped_cached": 0,
        "errors": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": 0.0,
        "by_status": {},
    }

    print()
    print("Researching {} sites (concurrency={}, cache={}d)...".format(
        len(site_list), CONCURRENCY, CACHE_DAYS
    ))
    print("-" * 70)

    results = {}
    start_time = time.time()

    async with aiosqlite.connect(DB_FILE) as db:
        tasks = [
            research_site(client, db, site, semaphore, stats, force=args.force)
            for site in site_list
        ]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                stats["errors"] += 1
                print("  EXCEPTION: {}".format(item))
                continue
            site_key, result, researched_at = item
            results[site_key] = dict(result)
            results[site_key]["researched_at"] = researched_at

    elapsed = time.time() - start_time

    # Write availability.json
    output = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_sites": len(site_list),
            "researched": stats["researched"],
            "skipped_cached": stats["skipped_cached"],
            "errors": stats["errors"],
            "model": MODEL,
            "elapsed_seconds": round(elapsed, 1),
        },
        "sites": results,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("  Sites researched:  {}".format(stats["researched"]))
    print("  Skipped (cached):  {}".format(stats["skipped_cached"]))
    print("  Errors:            {}".format(stats["errors"]))
    print("  Elapsed:           {:.1f}s".format(elapsed))
    print()
    print("  Status breakdown:")
    for status, count in sorted(stats["by_status"].items(), key=lambda x: -x[1]):
        print("    {:20s} {}".format(status, count))
    print()
    print("  Token usage:")
    print("    Input:   {:>10,}".format(stats["input_tokens"]))
    print("    Output:  {:>10,}".format(stats["output_tokens"]))
    print("    Cost:    ${:.4f}".format(stats["cost"]))
    print()
    print("  Output: {}".format(OUTPUT_FILE))
    print("  Database: {}".format(DB_FILE))


def main():
    parser = argparse.ArgumentParser(description="Deal Scout — site availability research agent")
    parser.add_argument("--top", type=int, help="Research only top N sites by score")
    parser.add_argument("--site", type=str, help="Research a single site by name (partial match)")
    parser.add_argument("--force", action="store_true", help="Ignore cache, re-research all")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be researched")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
