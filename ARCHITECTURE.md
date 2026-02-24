# GridSite Architecture

Adaptive reuse site intelligence platform for data center development. Identifies and scores locations nationwide by aggregating public infrastructure data — retired power plants, EPA brownfield sites, transmission infrastructure, interconnection queue activity, flood zones, and broadband coverage. First client: Raeden. Deadline: April 30.

## Current State

Single-page Next.js app (`app/page.tsx`, 1,892 lines) with all logic in one client component. Six Python ETL scripts produce static GeoJSON files served from `public/data/`. No backend, no database, no auth. Deployed on Vercel.

### What works today

- 7 toggleable map layers (power plants, substations, transmission lines, queue withdrawals, flood zones, broadband, brownfields)
- 5-dimension scoring engine scores 41,473 sites (793 power plants + 40,680 brownfields), outputs top 100
- Proximity analysis: click any scored site to see substations, transmission lines, and queue withdrawals within adjustable radius (5-20 mi)
- Score Any Location: right-click anywhere on the map for instant 5-dimension score with full breakdown
- Sidebar with collapsible sections: data layers, filters (MW capacity, state), ranked results list
- Map legend, click popups for all layer types

### What doesn't exist yet

- User accounts, saved searches, report generation
- Backend API, database, event logging
- Parcel boundaries, fiber routes, satellite imagery
- Real-time data updates (all data is static GeoJSON)

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Framework | Next.js 16.1.6 | `"use client"` single-page app, static export |
| UI | React 19.2.3 + Tailwind CSS 4 | Dark theme (`#1B2A4A` sidebar, `dark-v11` map) |
| Map | Mapbox GL JS 3.18 | 7 source/layer pairs, custom SDF icons, raster overlays |
| Geospatial | @turf/circle, @turf/boolean-intersects, @turf/helpers | Proximity analysis circle + line intersection |
| ETL | Python 3 (stdlib only) | 6 scripts, no pip dependencies |
| Scoring | Python (offline) + JS (real-time) | Same 5-dimension model in both languages |
| Deployment | Vercel | Static GeoJSON served from `public/data/` |
| Types | TypeScript 5 | Strict mode, single `ScoredSite` interface |

## File Structure

```
gridsite/
  app/
    page.tsx          # 1,892 lines — entire app (map, sidebar, scoring, popups)
    layout.tsx        # Root layout with Geist fonts
    globals.css       # Tailwind import + CSS variables
  public/data/
    power-plants.geojson        # 2.1 MB — EIA-860 retired/retiring plants >= 50 MW
    substations.geojson         # 6.5 MB — HIFLD 19,847 transmission-level substations
    transmission-lines.geojson  # 54 MB  — HIFLD 29,399 lines >= 138 kV
    queue-withdrawals.geojson   # 6.4 MB — LBNL 11,973 withdrawn projects >= 50 MW
    epa-brownfields.geojson     # 11 MB  — EPA FRS 40,680 brownfield sites
    scored-sites.geojson        # 84 KB  — Top 100 scored sites (output of score-sites.py)
  scripts/
    process-eia.py              # EIA-860 CSV -> power-plants.geojson
    fetch-substations.py        # HIFLD API -> substations.geojson
    fetch-transmission-lines.py # HIFLD API -> transmission-lines.geojson
    process-queue.py            # LBNL Excel -> queue-withdrawals.geojson
    fetch-brownfields.py        # EPA FRS national CSV -> epa-brownfields.geojson
    score-sites.py              # Scores all sites, outputs scored-sites.geojson
  .env.local                    # NEXT_PUBLIC_MAPBOX_TOKEN
```

## Scoring Model

All sites scored 0-100 across 5 weighted dimensions. Two site types use the same model with different sub-weights.

### Composite Formula

```
Composite = (Power Access x 0.30) + (Grid Capacity x 0.20) + (Site Characteristics x 0.20)
          + (Connectivity x 0.15) + (Risk Factors x 0.15)
```

### Dimension Details

#### Power Access (30%)

| Factor | Power Plants | Brownfields / Custom |
|--------|-------------|---------------------|
| Distance to nearest 345kV+ sub | 50% weight — 100 at 0 mi, 0 at 50+ mi | 65% weight |
| Existing generation capacity | 30% weight — linear 50-2000 MW | N/A |
| Substation voltage tier | 20% weight — 60/70/85/100 for <345/345/500/765 kV | 35% weight |

#### Grid Capacity (20%)

| Factor | Power Plants | Brownfields / Custom |
|--------|-------------|---------------------|
| Generation capacity | 40% weight — linear 50-3000 MW | N/A |
| Connected transmission lines | 30% weight — linear 0-8 lines | 45% weight |
| Queue withdrawals within 20 mi | 30% weight — count + MW bonus | 55% weight |

Queue withdrawal scoring: base 30 if none, else `min(100, 30 + count*5) + min(20, totalMW/5000*20)`.

#### Site Characteristics (20%)

| Factor | Power Plants | Brownfields / Custom |
|--------|-------------|---------------------|
| Fuel type suitability | 60% weight — NG CC: 95, Coal: 90, Nuclear: 50 | N/A |
| Capacity scale | 40% weight — linear 50-1500 MW | N/A |
| Base reuse score | N/A | Flat 65 |

#### Connectivity (15%)

Same formula for all site types:

| Factor | Weight | Logic |
|--------|--------|-------|
| Longitude proxy | 40% | 100 east of -70, decreasing westward |
| Latitude band | 30% | 90 for 33-43N, 70 for 28-48N, 40 elsewhere |
| Broadband coverage | 30% | State-level FCC BDC lookup, tiered 35-95 |

#### Risk Factors (15%)

| Factor | Power Plants | Brownfields / Custom |
|--------|-------------|---------------------|
| Contamination risk | 50% weight — by fuel type (NG: 85, Coal: 45, Nuclear: 20) | 65% weight — flat 55 (brownfield) or 70 (custom) |
| Operational status | 20% weight — retiring: 80, retired: 65 | N/A |
| Flood zone exposure | 30% weight — coastal heuristic by state/coords | 35% weight |

Flood scoring: 35 (coastal FEMA high-risk), 65 (moderate coastal states), 90 (inland).

### Current Top 5

| # | Site | State | Score | Type |
|---|------|-------|-------|------|
| 1 | Mystic Generating Station | MA | 92.6 | Power Plant |
| 2 | Paradise | KY | 87.8 | Power Plant |
| 3 | Rockport | IN | 87.7 | Power Plant |
| 4 | J M Stuart | OH | 87.7 | Power Plant |
| 5 | W H Sammis | OH | 87.4 | Power Plant |

Top 100 breakdown: 16 power plants, 84 brownfield sites.

## Data Source Matrix

### Tier 1: Implemented (Free Public Data)

| Source | Dataset | Records | File Size | Update Freq | Script |
|--------|---------|---------|-----------|-------------|--------|
| EIA-860 | Retired/retiring power plants >= 50 MW | 793 | 2.1 MB | Annual | `process-eia.py` |
| HIFLD | Transmission-level substations | 19,847 | 6.5 MB | Semi-annual | `fetch-substations.py` |
| HIFLD | Transmission lines >= 138 kV | 29,399 | 54 MB | Semi-annual | `fetch-transmission-lines.py` |
| LBNL | Interconnection queue withdrawals >= 50 MW | 11,973 | 6.4 MB | Quarterly | `process-queue.py` |
| EPA FRS | Brownfield/ACRES assessment sites | 40,680 | 11 MB | Quarterly | `fetch-brownfields.py` |
| FEMA NFHL | Flood Hazard Zones (layer 28) | Raster tiles | Dynamic | Irregular | ArcGIS MapServer export |
| Census/FCC | Broadband coverage indicator | Raster tiles | Dynamic | Semi-annual | ArcGIS MapServer export |

### Tier 2: Planned (Free Public Data)

| Source | Data | Format | Frequency | Risk |
|--------|------|--------|-----------|------|
| WARN Act | Facility closures | HTML/PDF | Varies by state | No federal standard; scraping per state |
| USPS/HUD | Vacancy rates | CSV | Quarterly | Aggregated to ZIP/tract level only |
| County Tax Assessments | Property valuations & zoning | Varies | Annual | No standard schema; county-by-county |
| Utility IRP Filings | Planned capacity & infrastructure | PDF | Biennial | Manual extraction from regulatory filings |
| Census ACS | Demographics & workforce | CSV/API | Annual | 1-year estimates noisy for small areas |

### Tier 3: Paid Enrichment (Future)

| Source | Data | Format | Frequency | Cost | Risk |
|--------|------|--------|-----------|------|------|
| Regrid | Parcel boundaries & ownership | API/Shapefile | Continuous | Per-query | Budget monitoring needed |
| FiberLocator | Fiber routes & lit buildings | API | Continuous | Subscription | Coverage gaps in rural areas |
| Satellite Imagery | Site condition & land use | GeoTIFF/API | On-demand | Per-image | Resolution/cost tradeoff |

### CoStar Avoidance Strategy

CoStar (commercial real estate comps) is explicitly avoided due to expensive licensing, restrictive data terms, and vendor lock-in risk. Alternative approach:

1. **County tax assessor data** for property valuations and ownership (free, public record)
2. **Regrid API** for parcel boundaries when needed (pay-per-query, no lock-in)
3. **Census ACS** for demographic proxies (free)
4. **Manual comps** from public MLS/auction data for high-priority sites

## Map Layer Architecture

All layers follow the same pattern in `page.tsx`:

```
Source constant:  var LAYER_SOURCE = "source-name"
Layer constant:   var LAYER_ID = "layer-id"
State:            layers.layerName (boolean toggle)
useEffect:        watches layers.layerName, calls setupLayer()
setupLayer():     if layer exists -> toggle visibility
                  if first toggle on -> addSource + addLayer + click/hover handlers
```

### Layer Stack (bottom to top)

1. `mapbox://styles/mapbox/dark-v11` (base)
2. `broadband-raster` — Census broadband, 35% opacity
3. `flood-zones-raster` — FEMA NFHL layer 28, 30% opacity
4. `brownfields-circles` — EPA brownfields, brown `#a0845c`
5. `power-plants-circles` — EIA-860, color by status (green/orange/red)
6. `transmission-lines-lines` — HIFLD, color + width by voltage
7. `substations-diamonds` — HIFLD, SDF diamond icon, color by voltage
8. `queue-withdrawals-triangles` — LBNL, orange SDF triangle icon
9. `radius-circle-fill` + `radius-circle-outline` — proximity analysis circle
10. `scored-sites-stars` — top 100, SDF star icon, color by score

Raster layers use ArcGIS MapServer dynamic export with `{bbox-epsg-3857}` token as Mapbox raster tile sources.

## Planned Component Refactor

The 1,892-line `page.tsx` monolith should be split into focused modules:

```
app/
  page.tsx                    # Layout shell: sidebar + map container (~100 lines)
  components/
    Map.tsx                   # Map init, icon creation, contextmenu handler
    layers/
      PowerPlantsLayer.tsx    # Source, layer, click handler, cursor
      SubstationsLayer.tsx
      TransmissionLinesLayer.tsx
      QueueWithdrawalsLayer.tsx
      FloodZonesLayer.tsx
      BroadbandLayer.tsx
      BrownfieldsLayer.tsx
      ScoredSitesLayer.tsx
      RadiusCircleLayer.tsx
    sidebar/
      Header.tsx              # Logo + tagline
      DataLayers.tsx          # 7 checkboxes
      Filters.tsx             # MW slider + state dropdown
      Results.tsx             # Scored site cards
    ProximityPanel.tsx        # Floating analysis panel + radius slider
    Legend.tsx                # Collapsible map legend
    popups/
      PowerPlantPopup.ts      # HTML string builder
      SubstationPopup.ts
      TransmissionLinePopup.ts
      QueueWithdrawalPopup.ts
      ScoredSitePopup.ts
      BrownfieldPopup.ts
  hooks/
    useMap.ts                 # Map ref, loaded state, shared map context
    useProximityAnalysis.ts   # runProximityAnalysis, clearProximityAnalysis, caches
    useScoreLocation.ts       # Right-click scoring logic + constants
    useDataCache.ts           # GeoJSON fetch + cache (substations, lines, withdrawals)
  lib/
    scoring.ts                # 5-dimension scoring functions (JS port of score-sites.py)
    haversine.ts              # haversineDistanceMiles
    constants.ts              # Layer IDs, source IDs, flood states, broadband coverage
    types.ts                  # ScoredSite, ProximityResult interfaces
```

### Refactor priorities

1. **Extract types + constants** (`lib/types.ts`, `lib/constants.ts`) — zero risk, immediate clarity
2. **Extract popup builders** (`popups/*.ts`) — pure functions, easy to test
3. **Extract scoring logic** (`lib/scoring.ts`, `hooks/useScoreLocation.ts`) — enables unit testing
4. **Extract layer components** — each layer is self-contained, follows identical pattern
5. **Extract sidebar components** — straightforward JSX decomposition
6. **Create MapContext** (`hooks/useMap.ts`) — shared map ref via React context

## Development Roadmap

### Phase 1: Current (MVP) — Done
- [x] EIA-860 power plants layer with status coloring
- [x] HIFLD substations layer with voltage-tier diamonds
- [x] HIFLD transmission lines layer with voltage-based width/color
- [x] LBNL queue withdrawals layer with orange triangles
- [x] FEMA flood zones raster overlay
- [x] FCC broadband raster overlay
- [x] EPA brownfield sites layer
- [x] 5-dimension scoring model (Python + JS)
- [x] Sidebar filters (MW capacity, state)
- [x] Proximity analysis panel with adjustable radius
- [x] Score Any Location (right-click)
- [x] Scored sites star layer with ranked sidebar

### Phase 2: Data Enrichment
- [ ] WARN Act facility closure scraper (state-by-state)
- [ ] County tax assessor integration (pilot: OH, PA, IN)
- [ ] Parcel boundary overlay via Regrid API
- [ ] Fiber route overlay via FiberLocator
- [ ] Satellite imagery for top 20 sites

### Phase 3: Platform
- [ ] Supabase backend (auth, saved searches, event logging)
- [ ] Component refactor (see structure above)
- [ ] Site comparison tool (side-by-side scoring)
- [ ] PDF report generation per site
- [ ] Share/export functionality

### Phase 4: Scale
- [ ] Automated data pipeline (cron-based ETL refresh)
- [ ] Real-time queue monitoring (ISO RSS/API feeds)
- [ ] Multi-tenant support (client workspaces)
- [ ] Custom scoring weight configuration per client
