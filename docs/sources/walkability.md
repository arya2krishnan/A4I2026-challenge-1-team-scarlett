# Walking access: OpenStreetMap Loop pilot

The public Overpass backends tried during acquisition timed out. A single small
extract from the official OpenStreetMap map API succeeded. The result is a **Loop
pilot**, with bounding box west -87.633, south 41.872, east -87.623, north 41.882.
It does not provide citywide walking coverage. The official editing API should
not be tiled to perform a citywide bulk download; use a regional OSM extract or a
working Overpass backend for that expansion.

Acquired 2026-11-17:

- 4,527 mapped network nodes and 5,528 segments from tagged highway ways.
- One sample walking-access record to the listed Harold Washington library,
  originating at 41.8781, -87.6298.
- About 367 metres on the mapped network plus 5.5 metres of unverified
  straight-line connectors, approximately 6.2 minutes at an assumed 60 m/min.

## Interpretation

Private/no pedestrian-access tags and restricted nodes are excluded. Foot access
can explicitly override a general access restriction. Vehicle one-way rules do
not restrict pedestrians; explicit `oneway:foot` does. Motorways, trunks and
construction/proposed ways are excluded. Surface, sidewalk and wheelchair tags
are preserved where present.

Unmapped or disconnected destinations have null walking estimates. Routes may
include steps and cannot establish wheelchair accessibility, crossing safety,
shade or a verified entrance. Incomplete OSM tagging is not proof that a route is
usable. The shortest path is computed only on the acquired network; alternative
paths outside the extract may be missing. Facility opening for the heat event
remains unknown.

The assumed speed is configurable. It is not an estimate of how fast older adults
or residents with disabilities can walk. Network distances and connector
distances are separate fields so the assumptions can be inspected.

## Reproduce

```bash
.venv/bin/python scripts/load_chicago_cooling_inventory.py
.venv/bin/python scripts/load_chicago_walkability.py
.venv/bin/python scripts/load_chicago_walkability.py \
  --source-xml data/enrichment/walkability/map.osm
```

Default outputs in git-ignored `data/enrichment/walkability/`:

- `map.osm`: original official map response.
- `walking_network_nodes.jsonl`, `walking_network_edges.jsonl`.
- `cooling_walk_access_pilot.jsonl`.
- `manifest.json`: source URL, SHA-256, retrieval timestamp, bounds, origin,
  counts, license, assumptions and coverage limitations.

`--load --project PROJECT --dataset DATASET` loads these three new table names.
For a local-file replay, the source retrieval timestamp is retained from its
manifest; normalization time is not substituted for acquisition time.

## Attribution and terms

© OpenStreetMap contributors. Data is provided under the **Open Database License
(ODbL) 1.0**. Preserve attribution and follow database redistribution obligations
when publishing extracts or derivative databases.

- [Source map API](https://api.openstreetmap.org/api/0.6/map?bbox=-87.633,41.872,-87.623,41.882)
- [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright)
- [API usage policy](https://operations.osmfoundation.org/policies/api/)

The City of Chicago terms separately apply to the cooling inventory used as
destinations. See [transit and facilities](transit_facilities.md).
