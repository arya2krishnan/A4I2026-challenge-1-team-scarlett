# Chicago transit and cooling inventory

## Obtained snapshots

Fetched 2026-11-17 into ignored `.data/enrichment/`:

| Artifact | Count | Coverage |
|---|---:|---|
| `transit/transit_stops.jsonl` | 11,107 | Entire CTA network: bus stops, rail platforms and parent stations, including suburbs |
| `transit/transit_routes.jsonl` | 132 | CTA bus and rail routes |
| `transit/transit_calendar.jsonl` | 128 | GTFS service calendars |
| `transit/transit_calendar_dates.jsonl` | 170 | Date-specific additions/removals of service |
| `transit/transit_departures.jsonl` | 263,715 | Stop/route/service-hour aggregates for service date 2026-11-17; 21,195 active scheduled trips |
| `facilities/cooling_inventory_snapshot.jsonl` | 287 | Chicago's published Cooling Centers inventory, with usable coordinates |

The cooling inventory contains **134 sites screened as indoor**, including **79 libraries**.
Other categories are 7 community colleges, 6 community service centers, 22 police districts,
6 regional senior centers, 14 satellite senior centers, 43 Park District facilities and
110 Park District spray features. Park District facilities and spray features are excluded
from the indoor subset by the existing loader's rule. Inventory screening does not verify AC.

Each directory has a `manifest.json` with retrieval timestamp, counts, sources and limitations.
The CTA raw ZIP is saved locally as `transit/google_transit.zip`. Raw source data are ignored by Git.

## Fetch and refresh

```bash
.venv/bin/python scripts/load_chicago_transit.py --service-date 2026-11-17
.venv/bin/python scripts/load_chicago_cooling_inventory.py
```

Select the actual heat-event service date, using `--service-date YYYY-MM-DD`. The obtained feed's
calendar range is 2026-10-29 through 2026-12-31; individual service IDs have their own dates.
Refresh the feed before planning outside its validity or when CTA publishes schedule changes.
To recompute from an existing official download:

```bash
.venv/bin/python scripts/load_chicago_transit.py \
  --source-zip .data/enrichment/transit/google_transit.zip --service-date 2026-11-18
```

Both scripts default to local acquisition. `--load --project PROJECT --dataset DATASET` opts into
loading only the new table names listed above, with `WRITE_TRUNCATE` for those enrichment snapshots.
Existing `cooling_facilities`, `site_context`, source tables and model are unaffected.
The BigQuery Python package and credentials are required only for `--load`.

On this macOS machine, the uv Python needed the installed trusted CA bundle for Chicago's portal:

```bash
SSL_CERT_FILE=/opt/homebrew/etc/openssl@3/cert.pem \
  .venv/bin/python scripts/load_chicago_cooling_inventory.py
```

TLS verification stays enabled. Other machines should use their own trusted CA installation.

## Transit interpretation and joining

`stop_id`, `route_id` and `service_id` remain strings; preserve leading zeros. Latitude and longitude
are WGS84. `wheelchair_boarding` follows GTFS: 0 or absent means unknown, 1 means possible,
2 means not possible; parent-station inheritance rules may apply. The loader preserves this field
without turning unknown into accessible.

`transit_departures` counts scheduled, boardable stop-time rows for active service after calendar
exceptions. `pickup_type=1` (no pickup) and missing departure times are excluded. Other pickup types
may require arrangements. Frequency-template trips would be excluded and counted in the manifest;
the obtained CTA feed contains none.

`service_hour` and departure seconds are measured from the selected GTFS service date, in
`America/Chicago`. GTFS times such as 25:10 are retained as hour 25, not incorrectly reassigned
to hour 1 of the service date. The two time fields describe the first and last departure in an
hour; an hourly count is not a guarantee of evenly spaced headways. The summary combines directions
at a stop/route and should not be used as an itinerary planner.

To add proximity to a city grid, spatially join each cell to stops with boardable departures on
the event service date. Use a pedestrian network for walking time. Nearest-stop distance alone
does not establish an accessible route to cooling: transfers, direction, service hours, walking
legs and facility opening need a routing step. Static GTFS also does not describe current
disruptions, elevator outages or live arrival predictions.

## Cooling readiness and freshness

The source's metadata labels its time period **Summer 2024**, while `rowsUpdatedAt` is 2026-07-24.
This is the currently published inventory fetched today, not a verified current operating roster.
The loader saves that metadata alongside the raw source records. It preserves published hours
as free text, including holiday wording; it does not infer whether a site opens during a specific
heat event.

These added fields are explicitly null until an operator verifies them:

- `open_for_event`
- `available_capacity`
- `working_ac_confirmed`
- `staffing_confirmed`
- `wheelchair_accessible_confirmed`
- `readiness_verified_at`

Public inventory does not supply those operational facts. Operator confirmation should identify
the heat-event date, verification time and who supplied the update before dispatch relies on it.

## Sources and terms

- [CTA GTFS information](https://www.transitchicago.com/developers/gtfs/)
- [Official CTA feed](https://www.transitchicago.com/downloads/sch_data/google_transit.zip)
- [CTA Developer License Agreement and Terms of Use](https://www.transitchicago.com/developers/terms/)
- [Chicago Cooling Centers](https://data.cityofchicago.org/Health-Human-Services/Cooling-Centers/msrk-w9ih)
- [Cooling Centers metadata](https://data.cityofchicago.org/api/views/msrk-w9ih.json)
- [Chicago data disclaimer](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html)
- [GTFS reference](https://gtfs.org/documentation/schedule/reference/)

CTA's limited license permits use, reproduction, distribution and derivative works **solely to
assist bus/rail riders or promote public transportation**. Other purposes require CTA permission.
The intended use here is helping residents reach cooling by transit. This is not a general open-data
license; do not describe the full feed as freely reusable for unrelated purposes. CTA retains
ownership and provides the data as-is. Follow its full terms for any published rider-facing product.

Chicago's metadata says “See Terms of Use,” attributes the City of Chicago and provides the inventory
without a guarantee of accuracy. Preserve source attribution and refresh/confirm before operational use.

## Verification

Focused offline tests cover calendar exception precedence, after-midnight GTFS departures,
no-pickup exclusion, unknown accessibility, invalid coordinates and readiness remaining null.
Both new scripts pass mypy with imported third-party modules ignored.
