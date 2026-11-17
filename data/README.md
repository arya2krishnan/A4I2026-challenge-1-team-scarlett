# data/

Seed and reference data that ships with this challenge.

Anything the load notebook pulls from a live public source goes into **BigQuery in your own
project**, not here. This folder is only for small files we generate or stage in advance.

If it's empty apart from this note, everything you need comes from the notebook.


Additional Chicago public-source acquisitions are written locally to the git-ignored
`data/enrichment/` directory, with normalized JSONL and source manifests. The loaded
tables are in BigQuery; rerun the `make enrich-*` targets to rebuild local copies.
See [DATA_ENRICHMENT.md](../docs/DATA_ENRICHMENT.md) for acquisition commands,
coverage and source terms.

## What's here now

- [`chicago/sites/`](chicago/sites/README.md): snapshots of City of Chicago open data on cooling centers,
  libraries, police stations, senior centers and CPS schools, with provenance, BigQuery schemas and a loader
  (`bash tools/load_chicago_sites_bq.sh`). Regenerate with `python tools/fetch_chicago_sites.py`.

