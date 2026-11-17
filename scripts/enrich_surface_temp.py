#!/usr/bin/env python3
"""Landsat land surface temperature (LST) per grid cell, via BigQuery ST_REGIONSTATS on Earth Engine assets.

    python scripts/enrich_surface_temp.py probe    # list candidate summer scenes, measure clear-sky fraction
    python scripts/enrich_surface_temp.py build    # render sql/enrich_surface_temp.sql with the chosen scenes, run it
    python scripts/enrich_surface_temp.py check    # premise check: LST offset vs Heat Watch air offset
    python scripts/enrich_surface_temp.py export   # write data/enrichment/surface_temp/premise_join.csv for
                                                   # scripts/surface_temp_premise.py (held-out fits, smoothing)
    python scripts/enrich_surface_temp.py render   # print the rendered SQL only

Uses the `bq` CLI (no application-default credentials needed). On the team Mac run from the repo root with
CLOUDSDK_CONFIG=$PWD/.gcloud. Writes data/enrichment/surface_temp/ (git-ignored): scene_probe.csv, scenes.json.

Scenes: Landsat 8 and 9 Collection 2 Level-2, WRS-2 path 023 row 031 (covers all of Chicago, ~40.7-42.8 N).
L8 revisits every 16 days (anchor 2020-07-05); L9 is offset 8 days and usable from 2022-02. Candidate dates
are June-August 2019-2025; a scene is kept when >= MIN_CLEAR of a ~4% cell sample is cloud-free by QA_PIXEL.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_sql import load_vars, render  # noqa: E402

OUT = ROOT / "data" / "enrichment" / "surface_temp"
TEMPLATE = ROOT / "sql" / "enrich_surface_temp.sql"
L8_ANCHOR = dt.date(2020, 7, 5)
L9_START = dt.date(2022, 2, 1)
YEARS = range(2019, 2026)
MONTHS = (6, 7, 8)
MIN_CLEAR = 0.80


def bq(sql: str, project: str, fmt: str = "csv") -> str:
    cmd = ["bq", f"--project_id={project}", "query", "--use_legacy_sql=false", f"--format={fmt}",
           "--max_rows=100000", "--quiet"]
    p = subprocess.run(cmd, input=sql, capture_output=True, text=True)  # stdin: SQL starting with "--" is not a flag
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip())
    return p.stdout


def asset(scene_id: str) -> str:
    return f"LANDSAT/{scene_id[:4]}/C02/T1_L2/{scene_id}"


def candidates() -> list[str]:
    out = []
    for k in range(-300, 300):
        d = L8_ANCHOR + dt.timedelta(days=16 * k)
        for sat, day in (("LC08", d), ("LC09", d + dt.timedelta(days=8))):
            if sat == "LC09" and day < L9_START:
                continue
            if day.year in YEARS and day.month in MONTHS:
                out.append(f"{sat}_023031_{day:%Y%m%d}")
    return sorted(out, key=lambda s: s[-8:])


def cell_poly(v: dict) -> str:
    a, o = v["LAT_STEP"], v["LON_STEP"]
    return (f"ST_GEOGFROMTEXT(FORMAT('POLYGON((%f %f, %f %f, %f %f, %f %f, %f %f))', "
            f"lon_i*{o}, lat_i*{a}, (lon_i+1)*{o}, lat_i*{a}, (lon_i+1)*{o}, (lat_i+1)*{a}, "
            f"lon_i*{o}, (lat_i+1)*{a}, lon_i*{o}, lat_i*{a}))")


def probe_one(scene: str, v: dict) -> dict:
    ee = f"ee://{asset(scene)}"
    sql = f"""
    WITH c AS (SELECT {cell_poly(v)} AS g FROM `{v['PROJECT']}.{v['DATASET']}.grid_cells`
               WHERE MOD(ABS(FARM_FINGERPRINT(cell_id)), 25) = 0),
    s AS (SELECT ST_REGIONSTATS(g, '{ee}', 'ST_B10') st, ST_REGIONSTATS(g, '{ee}', 'QA_PIXEL') qa FROM c),
    k AS (SELECT *, qa.min >= 21824 AND qa.max <= 21956 AND st.min > 0 AS clear FROM s)
    SELECT COUNT(*) n, COUNTIF(clear) n_clear,
           ROUND(((AVG(IF(clear, st.mean, NULL)) * 0.00341802 + 149) - 273.15) * 1.8 + 32, 1) mean_f,
           ROUND(STDDEV(IF(clear, st.mean, NULL)) * 0.00341802 * 1.8, 2) sd_f
    FROM k"""
    try:
        row = next(csv.DictReader(io.StringIO(bq(sql, v["PROJECT"]))))
        n, nc = int(row["n"]), int(row["n_clear"])
        return {"scene_id": scene, "exists": True, "n": n, "n_clear": nc, "clear_frac": round(nc / n, 3),
                "mean_f": row["mean_f"], "sd_f": row["sd_f"], "error": ""}
    except RuntimeError as e:
        msg = str(e).splitlines()[-1][:160]
        return {"scene_id": scene, "exists": "not found" not in msg, "n": 0, "n_clear": 0, "clear_frac": 0.0,
                "mean_f": "", "sd_f": "", "error": msg}


def cmd_probe(v: dict, args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cands = candidates()
    print(f"probing {len(cands)} candidate scenes ...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(lambda s: probe_one(s, v), cands))
    with (OUT / "scene_probe.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    keep = [r["scene_id"] for r in rows if r["clear_frac"] >= args.min_clear]
    for r in rows:
        flag = "KEEP" if r["scene_id"] in keep else ""
        print(f"{r['scene_id']}  clear={r['clear_frac']:.2f}  mean={r['mean_f']:>6}F  sd={r['sd_f']:>5}  {flag} {r['error'][:60]}")
    (OUT / "scenes.json").write_text(json.dumps({"min_clear": args.min_clear, "scenes": keep}, indent=2))
    print(f"\n{len(keep)} scenes kept -> {OUT / 'scenes.json'}")


def rendered(v: dict) -> str:
    scenes = json.loads((OUT / "scenes.json").read_text())["scenes"]
    arr = "[" + ", ".join(f"'{asset(s)}'" for s in scenes) + "]"
    return render(TEMPLATE.read_text(), {**v, "SCENE_IDS": arr})


def cmd_build(v: dict, args) -> None:
    sql = rendered(v)
    for stmt in [s for s in sql.split(";\n") if "CREATE" in s]:
        name = stmt.split("TABLE", 1)[1].split()[0]
        print(f">> {name}")
        bq(stmt, v["PROJECT"])
    print(bq(f"SELECT 'scenes' t, COUNT(*) n, COUNTIF(is_clear) n_clear FROM `{v['PROJECT']}.{v['DATASET']}.cell_surface_temp_scenes` "
             f"UNION ALL SELECT 'cells', COUNT(*), COUNTIF(n_scenes > 0) FROM `{v['PROJECT']}.{v['DATASET']}.cell_surface_temp`",
             v["PROJECT"], "pretty"))


CHECK_SQL = """
WITH j AS (
  SELECT g.cell_id, g.offset_f, g.is_holdout, g.latitude, g.longitude, s.lst_offset_f, s.n_scenes
  FROM `{P}.{D}.grid_cells` g JOIN `{P}.{D}.cell_surface_temp` s USING (cell_id)
  WHERE g.n_obs >= {MIN_OBS} AND g.offset_f IS NOT NULL AND s.lst_offset_f IS NOT NULL
),
r AS (
  SELECT *, RANK() OVER (PARTITION BY grp ORDER BY offset_f) ra, RANK() OVER (PARTITION BY grp ORDER BY lst_offset_f) rl
  FROM (SELECT *, 'all' grp FROM j UNION ALL SELECT *, IF(is_holdout, 'holdout', 'train') FROM j)
)
SELECT grp, COUNT(*) n,
       ROUND(CORR(offset_f, lst_offset_f), 3) pearson,
       ROUND(CORR(ra, rl), 3) spearman,
       ROUND(COVAR_SAMP(offset_f, lst_offset_f) / VAR_SAMP(lst_offset_f), 4) slope_air_per_lst,
       ROUND(AVG(offset_f) - COVAR_SAMP(offset_f, lst_offset_f) / VAR_SAMP(lst_offset_f) * AVG(lst_offset_f), 3) intercept,
       ROUND(POW(CORR(offset_f, lst_offset_f), 2), 3) r2,
       ROUND(STDDEV(offset_f), 2) sd_air, ROUND(STDDEV(lst_offset_f), 2) sd_lst
FROM r GROUP BY grp ORDER BY grp
"""


EXPORT_SQL = """
WITH strict AS (
  SELECT DISTINCT cell_id, PERCENTILE_CONT(lst_offset_f, 0.5) OVER (PARTITION BY cell_id) AS lst_strict
  FROM `{P}.{D}.cell_surface_temp_scenes` WHERE is_clear AND scene_clear_frac >= 0.9)
SELECT g.cell_id, g.lat_i, g.lon_i, g.latitude, g.longitude, g.offset_f, g.n_obs, g.is_holdout,
       g.dist_to_lake_km, g.dist_to_loop_km, g.green_share, g.building_share, g.paved_use_share,
       s.lst_offset_f, s.n_scenes, s.water_frac, s.lst_offset_iqr_f, st.lst_strict
FROM `{P}.{D}.grid_cells` g JOIN `{P}.{D}.cell_surface_temp` s USING (cell_id) LEFT JOIN strict st USING (cell_id)
"""


def cmd_export(v: dict, args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "premise_join.csv"
    path.write_text(bq(EXPORT_SQL.format(P=v["PROJECT"], D=v["DATASET"]), v["PROJECT"]))
    print(f"wrote {path}")


def cmd_check(v: dict, args) -> None:
    print(bq(CHECK_SQL.format(P=v["PROJECT"], D=v["DATASET"], MIN_OBS=v["MIN_OBS"]), v["PROJECT"], "pretty"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["probe", "build", "check", "export", "render"])
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-04-3e58e01275b8"))
    ap.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    ap.add_argument("--min-clear", type=float, default=MIN_CLEAR)
    args = ap.parse_args()
    v = load_vars(args.project, args.dataset)
    if args.command == "render":
        print(rendered(v))
    else:
        {"probe": cmd_probe, "build": cmd_build, "check": cmd_check, "export": cmd_export}[args.command](v, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
