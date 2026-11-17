# data/

Seed and reference data that ships with this challenge.

Anything the load notebook pulls from a live public source goes into **BigQuery in your own
project**, not here. This folder is only for small files we generate or stage in advance.

If it's empty apart from this note, everything you need comes from the notebook.

Additional Chicago public-source acquisitions are staged locally in the ignored
`.data/enrichment/` directory, with normalized JSONL and source manifests. They
can be loaded into new BigQuery enrichment tables once the destination is set.
See [DATA_ENRICHMENT.md](../docs/DATA_ENRICHMENT.md) for acquisition commands,
coverage and source terms.
