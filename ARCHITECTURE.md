# GridSite Architecture

## Purpose
AI-powered adaptive reuse site identification platform for data center development. Identifies 50MW+ opportunities nationwide by aggregating public infrastructure data and scoring sites for conversion potential. First client: Raeden. Deadline: April 30.

## Tech Stack
- Frontend: Next.js + React + Mapbox GL JS + Tailwind CSS
- Data Processing: DuckDB for local CSV/Parquet queries, Python for ETL
- Database: Supabase (PostgreSQL + PostGIS)
- Deployment: Vercel
- Dev Tools: Claude Code

## Data Source Matrix

### Tier 1: Free Public Data (Primary Site Identification)

| Source | Data | Format | Frequency | Risk |
|--------|------|--------|-----------|------|
| ISO/RTO Interconnection Queues | Withdrawn 50MW+ projects | CSV/Excel | Quarterly | Queue formats vary by ISO; manual mapping needed |
| EIA-860/923 | Power plant retirements | CSV | Annual (860) / Monthly (923) | 6-12 month lag on retirement data |
| HIFLD | Substations & transmission lines | Shapefile/GeoJSON | Semi-annual | Classification inconsistencies across regions |
| WARN Act | Facility closures | HTML/PDF | Varies by state | No federal standard; scraping required per state |
| EPA Brownfield | Industrial sites | CSV/API | Quarterly | Cleanup status may be outdated |

### Tier 2: Free Public Data (Screening & Enrichment)

| Source | Data | Format | Frequency | Risk |
|--------|------|--------|-----------|------|
| USPS/HUD | Vacancy rates | CSV | Quarterly | Aggregated to ZIP/tract level only |
| County Tax Assessments | Property valuations & zoning | Varies | Annual | No standard schema; county-by-county integration |
| Utility IRP Filings | Planned capacity & infrastructure | PDF | Biennial | Requires manual extraction from regulatory filings |
| FEMA Flood Zones | Flood risk areas | Shapefile/API | Irregular | Maps may not reflect current conditions |
| FCC Broadband | Broadband availability | CSV/API | Semi-annual | Provider self-reported; overestimates coverage |
| Census ACS | Demographics & workforce | CSV/API | Annual | 1-year estimates noisy for small geographies |

### Tier 3: Paid Enrichment

| Source | Data | Format | Frequency | Risk |
|--------|------|--------|-----------|------|
| Regrid | Parcel boundaries & ownership | API/Shapefile | Continuous | Per-query pricing; budget monitoring needed |
| FiberLocator | Fiber routes & lit buildings | API | Continuous | Subscription cost; coverage gaps in rural areas |
| Satellite Imagery | Site condition & land use | GeoTIFF/API | On-demand | Resolution/cost tradeoff; processing pipeline needed |
| CoStar | Commercial real estate comps | API | Continuous | **AVOID DEPENDENCY** — expensive, restrictive licensing |

## Event Logging

Every feature logs to a Supabase `events` table. This provides usage analytics, debugging context, and an audit trail across all modules.

```sql
CREATE TABLE events (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  event_type TEXT NOT NULL,
  event_data JSONB DEFAULT '{}',
  user_id TEXT,
  session_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### Event Types

| Event Type | Description |
|------------|-------------|
| `page_view` | User navigates to a page or module |
| `map_interaction` | Pan, zoom, or layer visibility change on the map |
| `site_clicked` | User clicks a specific site marker or result |
| `filter_applied` | User applies or modifies search/scoring filters |
| `search_executed` | User runs a site search query |
| `data_layer_toggled` | User enables/disables a map data layer |
| `report_generated` | User exports or generates a site report |
| `error` | Client-side or API error captured for debugging |

## Scoring Model

Sites are scored 0–100 across 5 weighted dimensions:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Power Access | 30% | Proximity to substations, existing interconnection points, retired generation capacity |
| Grid Capacity | 20% | Available transmission capacity, queue position feasibility, utility IRP alignment |
| Site Characteristics | 20% | Parcel size, zoning compatibility, environmental constraints, structural reuse potential |
| Connectivity | 15% | Fiber availability, distance to network POPs, broadband infrastructure density |
| Risk Factors | 15% | Flood zone exposure, contamination status, regulatory complexity, community opposition |

**Composite Score** = (Power Access × 0.30) + (Grid Capacity × 0.20) + (Site Characteristics × 0.20) + (Connectivity × 0.15) + (Risk Factors × 0.15)
