# Chicago tract geography for vulnerability enrichment

## Sources

- **US Census TIGERweb ACS2024**, Census Tracts layer 8:
  <https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2024/MapServer/8>
- **US Census TIGERweb ACS2024**, Incorporated Places layer 28, Chicago city:
  <https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2024/MapServer/28>
- **City of Chicago, Boundaries — Community Areas**, all 77 polygons:
  <https://data.cityofchicago.org/resource/igwz-8jzy.json?$limit=100>
- Census source policies: <https://www.census.gov/about/policies/quality.html>
- Chicago data disclaimer: <https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html>

Census government-produced tract geography is public-domain data. Chicago's portal
uses its city data terms/disclaimer. Credit both providers and retain source URLs.

The loader queries Cook County (`STATE='17' AND COUNTY='031'`), validates the
layer's name/fields, requests WGS84 GeoJSON in stable GEOID order, paginates, and
checks the result against an independent count response. Raw pages, layer
metadata, and the city snapshot are saved with SHA-256 file digests.

## Selection and counts

Primary outputs use the **matching-vintage ACS2024 Census Chicago incorporated
place** (`GEOID='1714000'`, `BASENAME='Chicago'`, `NAME='Chicago city'`). A tract is
included when its intersection with this polygon has **positive polygon area**.
Boundary-only touches are excluded. Invalid geometry is repaired before
intersection. The precise scope is **Chicago-intersecting Cook County tracts**,
including tracts crossing the city line. The small part of Chicago in DuPage
County is outside the Cook County ACS source and is not covered.

**ACS counts and margins of error remain whole-tract estimates.** They are never
multiplied by the fraction of a tract's land within Chicago. Accordingly, summing
these rows does not yield an exact Chicago population total. The selected rows'
`geographic_scope` states this explicitly; all numeric estimates remain unchanged.

The verified snapshot on 2026-11-17 contains all **1,332 Cook County tract
geometries** and selects **799 primary Chicago-intersecting Cook County tracts**,
each with a matching ACS2024 row. Comparing against the union of 77 city
community-area polygons yields 867 overlaps, including 68 community-only slivers.
The community-boundary diagnostics are retained separately in local files;
they are not loaded as primary Chicago tables. Of these diagnostic intersections,
65 are below approximately 1 hectare, 32 below 100 m², and 3 below 1 m².
`overlap_area_approx_m2`, `small_overlap_under_1ha`, and manifest counts make the
comparison reviewable. Approximate area uses a local latitude/longitude scale at
41.85°N; it is for overlap diagnostics, not population allocation.

Boundaries use the ACS2024 vintage to match the ACS2024 five-year estimates
(2020–2024). The primary city polygon also uses ACS2024; community polygons are
the current retrieved snapshot and are retained for comparison. The loader
rejects a different ACS estimate year, missing source rows, and duplicate GEOIDs.

Each selected tract gets a representative coordinate **inside the tract/city
intersection**. This is a geographic join/location point, not a population
centroid, an individual address, or a proposed truck parking location.

## Commands and artifacts

```bash
.venv/bin/python scripts/load_chicago_vulnerability.py
.venv/bin/python scripts/clip_chicago_vulnerability.py
# Optional upload of the two additional tables:
.venv/bin/python scripts/clip_chicago_vulnerability.py --load --project YOUR_PROJECT
```

Shapely is required for local geometry processing. No GCP dependency is imported
unless `--load` is used. For Python installations missing certificate discovery,
set `SSL_CERT_FILE` to a trusted local CA bundle; certificate validation must stay
enabled.

Default output directory: `.data/enrichment/geography/`.

| Artifact / new table | Contents |
|---|---|
| `tract_social_vulnerability_chicago.jsonl` / `tract_social_vulnerability_chicago` | Chicago-intersecting ACS2024 tract rows; whole counts/MOEs and clarified scope |
| `tract_boundaries_chicago.jsonl` / `tract_boundaries_chicago` | GEOID, representative latitude/longitude inside Census place intersection, full tract `geojson`, primary Census city intersection `chicago_overlap_geojson`, community comparison geometry/area, source and vintage |
| `community_tract_boundaries_diagnostic.jsonl`, `community_vulnerability_diagnostic.jsonl` | Local-only 867-row community-union comparison; includes slivers excluded from primary outputs |
| `raw/*.geojson`, `raw/*.json` | Complete Cook tract pages, count/metadata, Census Chicago place and city community polygons |
| `manifest.json` | Selection rule, count checks, matching vintage, source digests, acquisition time |

GeoJSON fields are stored as strings in the optional BigQuery table. Convert with
`ST_GEOGFROMGEOJSON(geojson, make_valid => TRUE)` when a geography join is needed.
The default heat-model tables are not rebuilt by this loader.
