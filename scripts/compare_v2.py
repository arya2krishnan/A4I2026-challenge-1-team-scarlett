"""Compare the live heat model with the v2 candidate on the Today outputs, without promoting v2.

Runs the deployed tools' own SQL (toolbox/tools.yaml: rank_priority_sites, equity_audit) twice: as-is, and with
the model/table swapped to heat_offset_lst / site_context_lst. Prints the equity audit side by side and how the
top-N truck sites change. Uses the bq CLI (no ADC needed).

    CLOUDSDK_CONFIG=$PWD/.gcloud .venv/bin/python scripts/compare_v2.py --project qwiklabs-gcp-04-3e58e01275b8 [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LIVE = ("heat_offset_model`", "site_context`")
V2 = ("heat_offset_lst`", "site_context_lst`")


def tool_statements() -> dict[str, dict]:
    return {d["name"]: d for d in yaml.safe_load_all((ROOT / "toolbox" / "tools.yaml").read_text())
            if d and d.get("name") in ("rank_priority_sites", "equity_audit")}


def sql_for(tool: dict, project: str, dataset: str, swap: tuple[str, str] | None) -> str:
    sql = re.sub(r"\$\{GOOGLE_CLOUD_PROJECT\}", project, tool["statement"])
    sql = re.sub(r"\$\{BQ_DATASET(:[^}]*)?\}", dataset, sql)
    if swap:
        for old, new in zip(LIVE, swap):
            sql = sql.replace(f".{old}", f".{new}")
    return sql


def run(sql: str, project: str, params: dict[str, tuple[str, object]]) -> list[dict]:
    cmd = ["bq", f"--project_id={project}", "--location=US", "query", "--nouse_legacy_sql", "--format=json",
           "--max_rows=1000"] + [f"--parameter={k}:{t}:{v}" for k, (t, v) in params.items()]
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True, check=True).stdout
    return json.loads(out[out.index("["):])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="a4i_climate")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--heat-weight", type=float, default=0.5)
    a = ap.parse_args()
    tools = tool_statements()
    params = {"limit": ("INT64", a.limit), "heat_weight": ("FLOAT64", a.heat_weight), "min_density": ("FLOAT64", 3000),
              "spacing_cells": ("INT64", 5), "min_offset": ("FLOAT64", -99)}
    res = {}
    for label, swap in (("live", None), ("v2", V2)):
        res[label] = {n: run(sql_for(tools[n], a.project, a.dataset, swap), a.project, params) for n in tools}

    print(f"== equity_audit (top {a.limit} truck sites, heat_weight {a.heat_weight})")
    for label in ("live", "v2"):
        for row in res[label]["equity_audit"]:
            print(label.ljust(5), json.dumps(row))

    sites = {k: res[k]["rank_priority_sites"] for k in res}
    ids = {k: {s["cell_id"] for s in v} for k, v in sites.items()}
    areas = {k: sorted({s.get("neighborhood") or "?" for s in v}) for k, v in sites.items()}
    print(f"\n== top-{a.limit} truck sites: {len(ids['live'] & ids['v2'])} cells in both")
    print("areas only in live:", sorted(set(areas["live"]) - set(areas["v2"])))
    print("areas only in v2:  ", sorted(set(areas["v2"]) - set(areas["live"])))
    for k in ("live", "v2"):
        print(f"\n{k} top 10:")
        for s in sites[k][:10]:
            print(f"  {s['rank']:>2} {str(s.get('neighborhood')):22} offset {float(s['predicted_offset_f']):+5.2f}  "
                  f"vuln {float(s['vulnerability_index']):.2f}  priority {float(s['priority_score']):.3f}")


if __name__ == "__main__":
    main()
