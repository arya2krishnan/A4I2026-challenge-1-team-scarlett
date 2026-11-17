# Chicago heat-dispatch data enrichment

## What the team can use

Actual public-source snapshots were acquired on **November 17, 2026**. Normalized
BigQuery-ready JSONL files, source responses and provenance manifests are saved
locally in `data/enrichment/`, which is git-ignored: the data lives in BigQuery,
and only the loaders and source documentation are committed.

**Uploaded and verified:** all 16 enrichment tables are now in
`qwiklabs-gcp-04-3e58e01275b8.a4i_climate` (US), containing **291,107 rows**.
Every load job completed successfully; table row counts and explicit schemas
were independently checked against the acquired files. Local copies remain
available in `data/enrichment/`.

| Enhancement | Acquired data | Decision supported |
|---|---|---|
| Social vulnerability | ACS 2024 five-year estimates for older adults living alone, disability, children under five and population denominators, with count margins of error | Area-level wellness-check priorities |
| Chicago tract geography | 799 Chicago-intersecting Cook County tracts using matching-vintage Census boundaries; city community-area comparison saved separately | Geographic joins and coverage review |
| Tree canopy | 799 tract records, 795 with usable canopy fractions, derived from Ecopia 2023 imagery via CMAP; reuse terms need confirmation | Additional physical heat-model context after checking temporal alignment |
| Housing vulnerability | 799 ACS 2024 tract records for rental housing cost burden, with count margins of error; 796 computable rates | Area-level housing vulnerability context |
| Hourly/overnight weather | 936 hourly rows across six NWS grids; 48 daily/overnight summaries, 36 complete nights | Humidity, wind and overnight relief during the forecast event |
| Transit access | 11,107 CTA stop/station records, 132 routes, calendars and 263,715 scheduled stop/route/hour aggregates | Planning transit access to cooling |
| Cooling inventory | 287 listed sites: 134 screened as indoor, including 79 libraries; published hours and contact information | Locating cooling options and checking operating readiness |
| Walking access pilot | 4,527 OSM nodes, 5,528 network segments and one sample library walking estimate in the Loop | Demonstrating network-based access calculations |
| Satellite surface temperature | Landsat 8/9 C2 L2 `ST_B10` from 14 clear summer scenes (2019–2025) via BigQuery `ST_REGIONSTATS`; per-cell median offset for all 5,053 grid cells in `cell_surface_temp` (+ `cell_surface_temp_scenes`) | Stage-1 "why" layer: which blocks run hot by surface; tracks Heat Watch air offset only moderately (r ≈ 0.4) |
| Per-cell land cover | `cell_land_cover`: 5,053 grid cells with NLCD 2021 impervious % and USFS/NLCD 2021 tree canopy % (cell and 300 m disc), computed in BigQuery via Earth Engine; public domain | Changeable heat-model features (pavement vs. canopy) for explanations |

Social-vulnerability acquisition contains 1,332 **Cook County** tracts. The
geography loader selects Chicago-intersecting tracts using the ACS2024 Chicago
place polygon. It also retains a separate diagnostic set intersecting the city's
community-area polygons. Population estimates remain whole-tract values; do not
sum repeated tract counts after joining them to grid cells. Chicago's territory
in DuPage County is outside the county acquisition.

## Sources, meaning and freshness

- [Social vulnerability](sources/vulnerability.md): official Census bulk files;
  ACS 2024 represents 2020–2024, with aggregate estimates and approximate sum MOEs.
- [Tract boundaries](sources/tract_boundaries.md): official ACS2024 TIGERweb plus
  Chicago community polygons; matching vintages avoid city-boundary slivers.
- [Canopy and housing](sources/environment.md): CMAP/Ecopia 2023 canopy and ACS
  rental cost burden. Canopy redistribution terms are unspecified; keep the
  downloaded source local until reuse is confirmed. Rental cost burden measures
  rent relative to income; it does not measure AC availability or energy burden.
- [Weather](sources/weather.md): current NWS forecasts for November 17–24, 2026;
  refresh before dispatch. These are forecast context, not heat-campaign labels.
- [Transit and facilities](sources/transit_facilities.md): CTA feed valid roughly
  October 29–December 31, 2026; scheduled service aggregates are for November 17.
  CTA's license limits reuse to rider assistance or promoting public transit.
- [Land cover](sources/land_cover.md): NLCD 2021 imperviousness and TCC v2021-4
  canopy per grid cell (public domain); canopy reads low in cities, so use it as a relative measure.
- [Walking pilot](sources/walkability.md): © OpenStreetMap contributors, ODbL;
  bounded Loop coverage, assumed walking speed and unverified connectors.
- [Surface temperature](sources/surface_temperature.md): USGS Landsat, public domain;
  ~10:30 overpass, 100 m thermal, per-cell QA cloud mask; surface ≠ air temperature.

The cooling portal labels its inventory **Summer 2024**, with a July 24, 2026
row update. Fetching it today does not verify opening for a particular heat event.
`open_for_event`, capacity, staffing, working AC and confirmed wheelchair access
are null until supplied by an operator. Citywide walking routes, shade along
routes, live transit disruptions and historical Google traffic have not been
acquired in these snapshots.

## Reproduce acquisition

Use Python 3.11. The standalone requirements avoid installing the full agent/UI
stack for acquisition:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-enrichment.txt
make enrich-data SERVICE_DATE=2026-11-17
make typecheck
```

Individual targets are `enrich-vulnerability`, `enrich-geography`,
`enrich-environment`, `enrich-weather`, `enrich-transit`, `enrich-cooling` and `enrich-walkability`.
`make enrich-data` pins ACS 2024 to match tract geometry; upgrading the ACS vintage
also requires updating the geography source. The walking target performs one
small official map request. Citywide expansion should use a regional bulk extract
or a working Overpass endpoint.

On this Mac, the managed Python required the installed trusted certificate
bundle. If this machine's default certificate lookup fails, prefix acquisition
commands with `SSL_CERT_FILE=/opt/homebrew/etc/openssl@3/cert.pem`. Other machines
should use their own trusted CA setup.

## BigQuery upload and refresh

The configured destination is
`qwiklabs-gcp-04-3e58e01275b8.a4i_climate`. The successful upload used the active
lab account through `--gcloud-auth`, because separately saved application
credentials were stale. For a future refresh, sign in with an account that has
access to the lab project:

```bash
gcloud auth login --update-adc
```

Then validate the persisted files and their explicit schemas before loading:

```bash
.venv/bin/python scripts/load_enrichment_snapshots.py \
  --dry-run --project qwiklabs-gcp-04-3e58e01275b8 --dataset a4i_climate
.venv/bin/python scripts/load_enrichment_snapshots.py \
  --gcloud-auth --project qwiklabs-gcp-04-3e58e01275b8 --dataset a4i_climate --location US
```

`--dry-run` makes no Cloud requests. `--sources weather transit` can select subsets. The dataset must exist
and match `--location` (default `US`). Authenticated BigQuery load access is
required for the second command.

`--gcloud-auth` uses the active CLI account and keeps access tokens in memory.
Without that flag the loader uses application default credentials. Completed
job IDs and source hashes are saved after each table in
`data/enrichment/upload-result.json`; independent job/schema/count verification
is recorded in `data/enrichment/upload-verification.json`.

Destinations are a fixed list of enrichment tables. County vulnerability, canopy
and housing append snapshots; select the latest vintage/retrieval per tract
before joining. Other enrichment
tables replace their acquired snapshots on refresh. Loads are separate jobs, so
a failed load may leave earlier selected tables loaded. The original source
tables, `site_context`, trained model and deployed agent have not been changed.
The agent will need an explicit query/tool integration to consume these tables.

## Verification

Focused offline tests cover Census missing values and MOEs, geographic clipping,
weather units and DST overnight coverage, GTFS service exceptions and departures
after midnight, unknown facility readiness, and pedestrian-network restrictions.
`make typecheck` checks the acquisition/geography/upload scripts.

The acquisition passed **40 focused tests**, the eight-script typecheck,
and local schema validation of all **16 proposed enrichment tables**. No Cloud
request was made by that local load-plan validation.
