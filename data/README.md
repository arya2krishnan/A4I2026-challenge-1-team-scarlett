# data/

Seed and reference data that ships with this challenge.

Anything the load notebook pulls from a live public source goes into **BigQuery in your own
project**, not here. This folder is only for small files we generate or stage in advance.

If it's empty apart from this note, everything you need comes from the notebook.

## What's here now

- [`chicago/sites/`](chicago/sites/README.md): snapshots of City of Chicago open data on cooling centers,
  libraries, police stations, senior centers and CPS schools, with provenance, BigQuery schemas and a loader
  (`bash tools/load_chicago_sites_bq.sh`). Regenerate with `python tools/fetch_chicago_sites.py`.
