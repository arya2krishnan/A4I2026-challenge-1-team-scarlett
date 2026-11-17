#!/usr/bin/env python3
"""Create a recovery baseline without writing to source tables.

Makes dated read-only snapshots, copies existing models, exports every snapshot
as local gzip JSONL with schemas/hashes, and tests local-data restoration in new
backup tables. Does not implement data enrichment priorities 1–6.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import decimal
import gzip
import hashlib
import io
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from load_enrichment_snapshots import gcloud_credentials

ROOT = Path(__file__).resolve().parents[1]


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if hasattr(value, "items"):
        return {key: json_value(item) for key, item in value.items()}
    raise TypeError(f"Unsupported backup value type: {type(value).__name__}")


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_value(payload), indent=2, allow_nan=False) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_table(client: Any, entry: dict, output_dir: Path) -> dict:
    path = output_dir / "tables" / f"{entry['name']}.jsonl.gz"
    temporary = path.with_suffix(path.suffix + ".partial")
    count = 0
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for row in client.list_rows(entry["snapshot"], page_size=10000):
            handle.write(json.dumps(json_value(row), allow_nan=False, separators=(",", ":")) + "\n")
            count += 1
    if count != entry["rows"]:
        raise ValueError(f"{entry['name']}: exported {count} rows, expected {entry['rows']}")
    temporary.replace(path)
    return {**entry, "local_file": str(path), "exported_rows": count,
            "compressed_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def restore_probe(client: Any, entry: dict, project: str, backup_dataset: str) -> dict:
    from google.cloud.bigquery.job.load import LoadJobConfig
    from google.cloud.bigquery.job.query import QueryJobConfig
    from google.cloud.bigquery.schema import SchemaField

    metadata = json.loads(Path(entry["metadata_file"]).read_text())
    schema = [SchemaField.from_api_repr(field) for field in metadata["snapshot_metadata"]["schema"]["fields"]]
    path = Path(entry["local_file"])
    if sha256_file(path) != entry["sha256"]:
        raise ValueError(f"Backup hash mismatch: {path}")
    destination = f"{project}.{backup_dataset}.restore_check_{entry['name']}"
    payload = gzip.decompress(path.read_bytes())
    job = client.load_table_from_file(
        io.BytesIO(payload), destination,
        job_config=LoadJobConfig(schema=schema, source_format="NEWLINE_DELIMITED_JSON",
                                write_disposition="WRITE_EMPTY"),
    )
    job.result()
    restored = client.get_table(destination)
    if restored.num_rows != entry["rows"]:
        raise ValueError(f"Restored row count mismatch: {destination}")
    if [field.to_api_repr() for field in restored.schema] != [field.to_api_repr() for field in schema]:
        raise ValueError(f"Restored schema mismatch: {destination}")
    sql = f"""SELECT 'snapshot' dataset_role, COUNT(*) row_count,
      BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t))) xor_hash,
      SUM(CAST(FARM_FINGERPRINT(TO_JSON_STRING(t)) AS BIGNUMERIC)) sum_hash
      FROM `{entry['snapshot']}` t
      UNION ALL
      SELECT 'restored', COUNT(*), BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t))),
      SUM(CAST(FARM_FINGERPRINT(TO_JSON_STRING(t)) AS BIGNUMERIC))
      FROM `{destination}` t"""
    check = client.query(sql, job_config=QueryJobConfig(maximum_bytes_billed=500_000_000))
    rows = [dict(row.items()) for row in check.result()]
    if len(rows) != 2 or any(rows[0][key] != rows[1][key] for key in ("row_count", "xor_hash", "sum_hash")):
        raise ValueError(f"Restored data checksum mismatch: {destination}")
    return {"source_table": entry["name"], "restored_table": destination,
            "load_job_id": job.job_id, "verification_job_id": check.job_id,
            "rows": restored.num_rows, "schema_matches": True, "checksums_match": True}


def main() -> int:
    from google.cloud.bigquery.client import Client
    from google.cloud.bigquery.dataset import Dataset
    from google.cloud.bigquery.job.copy_ import CopyJobConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="a4i_climate")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/enrichment/recovery")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", args.project):
        parser.error("invalid project ID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,700}", args.dataset):
        parser.error("invalid dataset ID")
    credentials = gcloud_credentials()
    client = Client(project=args.project, credentials=credentials)
    source_id = f"{args.project}.{args.dataset}"
    source_dataset = client.get_dataset(source_id)
    client = Client(project=args.project, location=source_dataset.location, credentials=credentials)
    source_tables = [client.get_table(entry.reference) for entry in client.list_tables(source_id)]
    if any(table.table_type != "TABLE" for table in source_tables):
        raise ValueError("Baseline includes non-native tables; review their backup method before proceeding")
    source_models = [client.get_model(entry.reference) for entry in client.list_models(source_id)]
    baseline_at = next(iter(client.query("SELECT CURRENT_TIMESTAMP() baseline_at").result()))["baseline_at"]
    run_id = baseline_at.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{args.dataset}_backup_{run_id}"
    backup_id = f"{args.project}.{backup_name}"
    output_dir = args.output_dir / run_id
    if output_dir.exists():
        raise ValueError("Recovery run directory already exists; refusing to replace it")
    output_dir.mkdir(parents=True)
    backup_dataset = Dataset(backup_id)
    backup_dataset.location = source_dataset.location
    backup_dataset.description = f"Recovery baseline of {source_id} at {baseline_at.isoformat()}"
    backup_dataset.labels = {"purpose": "recovery_baseline", "source": args.dataset.lower()}
    client.create_dataset(backup_dataset)
    manifest: dict[str, Any] = {"source_dataset": source_id, "backup_dataset": backup_id,
                               "baseline_at": baseline_at.isoformat(), "location": source_dataset.location,
                               "status": "snapshotting", "tables": [], "models": [], "restore_checks": []}
    manifest_path = output_dir / "manifest.json"
    save_json(output_dir / "source_dataset.metadata.json", source_dataset.to_api_repr())
    save_json(manifest_path, manifest)
    print(f"Recovery baseline: {backup_id}", flush=True)
    print(f"Local archive: {output_dir}", flush=True)
    for source in sorted(source_tables, key=lambda table: table.table_id):
        original = f"{source.project}.{source.dataset_id}.{source.table_id}"
        snapshot = f"{backup_id}.{source.table_id}"
        sql = (f"CREATE SNAPSHOT TABLE `{snapshot}` CLONE `{original}` "
               f"FOR SYSTEM_TIME AS OF TIMESTAMP('{baseline_at.isoformat()}')")
        job = client.query(sql)
        job.result()
        table = client.get_table(snapshot)
        if table.table_type != "SNAPSHOT" or table.expires is not None:
            raise ValueError(f"Expected a non-expiring read-only snapshot: {snapshot}")
        metadata_path = output_dir / "tables" / f"{source.table_id}.metadata.json"
        save_json(metadata_path, {"source_metadata": source.to_api_repr(), "snapshot_metadata": table.to_api_repr()})
        manifest["tables"].append({"name": source.table_id, "source": original, "snapshot": snapshot,
                                   "rows": table.num_rows, "bytes": table.num_bytes,
                                   "metadata_file": str(metadata_path), "snapshot_job_id": job.job_id})
        save_json(manifest_path, manifest)
        print(f"Snapshot {len(manifest['tables'])}/{len(source_tables)}: {source.table_id} ({table.num_rows} rows)", flush=True)
    for source_model in source_models:
        original = f"{source_model.project}.{source_model.dataset_id}.{source_model.model_id}"
        destination = f"{backup_id}.{source_model.model_id}"
        copy_job = client.copy_table(original, destination, job_config=CopyJobConfig(write_disposition="WRITE_EMPTY"))
        copy_job.result()
        copied = client.get_model(destination)
        if copied.model_type != source_model.model_type:
            raise ValueError(f"Copied model type mismatch: {destination}")
        metadata_path = output_dir / "models" / f"{source_model.model_id}.metadata.json"
        save_json(metadata_path, {"source_metadata": source_model.to_api_repr(), "backup_metadata": copied.to_api_repr()})
        manifest["models"].append({"source": original, "backup": destination, "copy_job_id": copy_job.job_id,
                                   "metadata_file": str(metadata_path)})
        save_json(manifest_path, manifest)
        print(f"Copied model: {source_model.model_id}", flush=True)
    manifest["status"] = "exporting"
    save_json(manifest_path, manifest)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(export_table, client, entry, output_dir) for entry in manifest["tables"]]
        completed = []
        for future in as_completed(futures):
            entry = future.result()
            completed.append(entry)
            current = {item["name"]: item for item in completed}
            manifest["tables"] = [current.get(item["name"], item) for item in manifest["tables"]]
            save_json(manifest_path, manifest)
            print(f"Export {len(completed)}/{len(source_tables)}: {entry['name']} ({entry['exported_rows']} rows)", flush=True)
    manifest["status"] = "testing_restore"
    save_json(manifest_path, manifest)
    entries = {entry["name"]: entry for entry in manifest["tables"]}
    for name in ("heat_observations", "community_areas", "weather_hourly"):
        probe = restore_probe(client, entries[name], args.project, backup_name)
        manifest["restore_checks"].append(probe)
        save_json(manifest_path, manifest)
        print(f"Verified local restore: {name} ({probe['rows']} rows)", flush=True)
    manifest["status"] = "verified"
    manifest["verified_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest["total_rows"] = sum(entry["exported_rows"] for entry in manifest["tables"])
    manifest["local_compressed_bytes"] = sum(entry["compressed_bytes"] for entry in manifest["tables"])
    save_json(manifest_path, manifest)
    save_json(args.output_dir / "latest.json", {"manifest": str(manifest_path), "backup_dataset": backup_id,
                                              "status": "verified", "baseline_at": baseline_at.isoformat()})
    print(f"VERIFIED: {len(manifest['tables'])} table snapshots, {len(manifest['models'])} model copies, "
          f"{len(manifest['restore_checks'])} local restore checks", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
