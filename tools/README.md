# tools/

Reproducible data-prep tools. Each one writes files into `data/` that are committed to the repo, so
teammates can load them into BigQuery without re-fetching.

| Tool | What it does |
|---|---|
| `fetch_chicago_sites.py` | Downloads five City of Chicago open-data datasets (cooling centers, libraries, police stations, senior centers, CPS school locations) and writes CSVs, BigQuery schemas and a `manifest.json` (row counts, SHA-256, retrieval time) to `data/chicago/sites/`. Python standard library only. Safe to re-run: it rewrites the folder. |
| `load_chicago_sites_bq.sh` | Loads every CSV in `data/chicago/sites/` into BigQuery as `chi_site_<name>` (replace, never append). Reads `GOOGLE_CLOUD_PROJECT` / `BQ_DATASET` from `.env`, or takes them as arguments. |

```bash
python tools/fetch_chicago_sites.py        # refresh the snapshots (needs internet access to data.cityofchicago.org)
bash   tools/load_chicago_sites_bq.sh      # push them to BigQuery
```

**Can't reach the portal from your machine?** The GitHub Actions workflow
`.github/workflows/fetch-chicago-sites.yml` runs the fetch on GitHub's servers. It triggers when
`tools/fetch_chicago_sites.py` changes on a non-main branch, and can be run manually from the Actions tab
once the workflow is on `main`. On a feature branch it commits the refreshed CSVs to that branch. On
`main` it never commits; it uploads them as a workflow artifact instead.

Offline tests: `python -m pytest tests/test_fetch_chicago_sites.py -q`. Details on each dataset, the added columns and
caveats are in [`data/chicago/sites/README.md`](../data/chicago/sites/README.md).
