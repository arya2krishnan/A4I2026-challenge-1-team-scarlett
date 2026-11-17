# Chicago hourly and overnight forecast enrichment

## Source and acquisition

The National Weather Service API is public and keyless. Six representative points
(Loop, Rogers Park, Austin, Englewood, South Shore, Pullman) resolve through
`https://api.weather.gov/points/{latitude},{longitude}` to forecast grid URLs.
Requests sharing a grid are deduplicated. Forecast grids are coarser than this
project's approximately 330 m heat-model cells.

- API documentation: <https://www.weather.gov/documentation/services-web-api>
- NOAA/NWS disclaimer and reuse terms: <https://www.weather.gov/disclaimer>
- Example hourly endpoint: <https://api.weather.gov/gridpoints/LOT/76,73/forecast/hourly>

NWS forecasts produced by the US government are public domain; credit NWS/NOAA and
retain the source URL and retrieval time. The disclaimer describes service and
accuracy limitations. This loader collects forecast fields, without third-party
imagery. Set `NWS_USER_AGENT` to a project identifier/contact for ongoing use.

```bash
.venv/bin/python scripts/load_chicago_weather.py
# Explicitly load the two additional tables into your configured dataset:
.venv/bin/python scripts/load_chicago_weather.py --load --project YOUR_PROJECT
```

No BigQuery load occurs without `--load`. The load refreshes `weather_hourly` and
`weather_daily`; it does not modify the existing heat model or its inputs.

Verified acquisition on **2026-11-17 at 19:30 UTC**: all six points resolved to six
distinct grids, yielding **936 hourly periods** and **48 daily/overnight summaries**.
The forecast interval was 2026-11-17 19:00 UTC through 2026-11-24 07:00 UTC.
There were 36 complete overnight windows; edge windows were explicitly partial.
All 936 periods contained temperature, humidity, and dewpoint. No request errors
were recorded. Reruns will produce a different current forecast snapshot.

## Local artifacts and tables

Default output directory: `data/enrichment/weather/` (git-ignored).

| Artifact / new table | Contents |
|---|---|
| `weather_hourly.jsonl` / `weather_hourly` | Grid, representative coordinates, UTC valid intervals, local date/hour, forecast temperature in F, humidity in percent, dewpoint in C, original wind text/direction, short forecast, issue/generation/retrieval times, source URL |
| `weather_daily.jsonl` / `weather_daily` | Local-date forecast high/low, overnight low, coverage and completeness, overnight start/end, grid and provenance |
| `raw/*.json` | Actual NWS point metadata and hourly forecast responses |
| `manifest.json` | Retrieval time, counts, successful grids, valid interval, source URLs and SHA-256 digests, request errors, units and terms |

Missing humidity/dewpoint remain null; unknown units and non-finite values become
null. Wind speed is preserved as NWS text because it can be a range. Forecast
temperature in C is converted to F. All valid and provenance timestamps use UTC.

**Overnight** means 20:00 on `local_date` through 08:00 the next day in
`America/Chicago`. Expected duration is 12 hours normally, 11 or 13 when clocks
change. Coverage counts elapsed hours with valid temperatures and merges
overlapping intervals. A partial forecast window has `overnight_complete=false`;
its minimum should not be presented as a complete overnight low. Daily extrema
likewise have coverage and completeness fields.

## Decision use and limitations

Use hourly humidity alongside temperature for heat-index calculations, and use
overnight lows to identify heat episodes with little recovery. The spatial heat
offset remains a separate campaign-derived ranking signal. These forecasts are
for the acquisition date and must not be added as historical training features
for the single-afternoon Heat Watch labels.

Refresh before dispatch and periodically during an event. The API generally
provides approximately seven days; actual horizon and counts are recorded in the
manifest. The first and last forecast days/nights are often partial. Six locations
offer citywide context, not street-level weather observations. Join by grid or by
nearest representative point with this resolution made explicit.

Facility opening hours and temperatures indoors are not inferred from weather.
This loader does not compute intervention effects, population exposure counts,
or duration-adjusted heat outcomes. A separate downstream rule can count
consecutive hot days after its threshold and use of partial periods are defined.
