#!/usr/bin/env python3
"""Premise check for the two-stage design: does Landsat surface-temperature offset track Heat Watch air offset?

    python scripts/enrich_surface_temp.py export     # writes data/enrichment/surface_temp/premise_join.csv
    .venv/bin/python scripts/surface_temp_premise.py data/enrichment/surface_temp/premise_join.csv

Reports correlations (all measured cells and held-out blocks), neighbourhood-smoothed LST, held-out linear fits
trained on non-held-out cells (LST alone, lat/lon quadratic, both), partial correlation after the lat/lon trend, and
how much of LST itself is a lat/lon trend. Needs numpy + pandas only.
"""
import sys, numpy as np, pandas as pd
def sp(a,b): return a.rank().corr(b.rank())
d = pd.read_csv(sys.argv[1])
d["is_holdout"] = d.is_holdout.astype(str).str.lower().eq("true")
# neighbourhood means of LST over the full grid (all cells, so unmeasured neighbours count too)
idx = {(a, o): v for a, o, v in zip(d.lat_i, d.lon_i, d.lst_offset_f)}
def smooth(k):
    out = []
    for a, o in zip(d.lat_i, d.lon_i):
        vals = [idx.get((a + i, o + j)) for i in range(-k, k + 1) for j in range(-k, k + 1)]
        vals = [v for v in vals if v is not None and not np.isnan(v)]
        out.append(np.mean(vals) if vals else np.nan)
    return np.array(out)
for k in (1, 2, 3, 5):
    d[f"lst_s{k}"] = smooth(k)
lat0, lon0 = d.latitude.mean(), d.longitude.mean()
d["y_"] = d.latitude - lat0; d["x_"] = d.longitude - lon0
def quad(df): return np.column_stack([df.x_, df.y_, df.x_**2, df.y_**2, df.x_*df.y_])
def fit_eval(cols_fn, m, name):
    tr, ho = m[~m.is_holdout], m[m.is_holdout]
    X = lambda df: np.column_stack([np.ones(len(df)), cols_fn(df)])
    b, *_ = np.linalg.lstsq(X(tr), tr.offset_f, rcond=None)
    pred = X(ho) @ b
    r2 = 1 - ((ho.offset_f - pred)**2).sum() / ((ho.offset_f - tr.offset_f.mean())**2).sum()
    rmse = np.sqrt(((ho.offset_f - pred)**2).mean())
    print(f"  {name:38s} holdout r2={r2:6.3f} rmse={rmse:.2f}  coefs={np.round(b[1:3],3)}")
m = d[(d.n_obs >= 8) & d.offset_f.notna() & d.lst_offset_f.notna()].copy()
print(f"measured cells n={len(m)} (train {(~m.is_holdout).sum()}, holdout {m.is_holdout.sum()}); baseline holdout rmse={np.sqrt(((m[m.is_holdout].offset_f-m[~m.is_holdout].offset_f.mean())**2).mean()):.2f}")
for c in ["lst_offset_f", "lst_strict", "lst_s1", "lst_s2", "lst_s3", "lst_s5"]:
    mm = m[m[c].notna()]
    print(f"{c:13s} pearson all={mm.offset_f.corr(mm[c]):.3f} spearman={sp(mm.offset_f, mm[c]):.3f} | holdout pearson={mm[mm.is_holdout].offset_f.corr(mm[mm.is_holdout][c]):.3f} spearman={sp(mm[mm.is_holdout].offset_f, mm[mm.is_holdout][c]):.3f}")
land = m[m.water_frac < 0.25]
print(f"land-only (water_frac<0.25) n={len(land)} pearson={land.offset_f.corr(land.lst_offset_f):.3f} s2={land.offset_f.corr(land.lst_s2):.3f}")
print("held-out linear fits (trained on train cells):")
fit_eval(lambda df: df[["lst_offset_f"]].values, m, "air ~ lst")
fit_eval(lambda df: df[["lst_s2"]].values, m, "air ~ lst 5x5 mean")
fit_eval(lambda df: df[["lst_s3"]].values, m, "air ~ lst 7x7 mean")
fit_eval(quad, m, "air ~ lat/lon quadratic")
fit_eval(lambda df: np.column_stack([df.lst_offset_f, quad(df)]), m, "air ~ lst + quadratic")
fit_eval(lambda df: np.column_stack([df.lst_s2, quad(df)]), m, "air ~ lst5x5 + quadratic")
# partial correlation: residuals after lat/lon quadratic, on all measured cells
def resid(y, X):
    X = np.column_stack([np.ones(len(X)), X]); b, *_ = np.linalg.lstsq(X, y, rcond=None); return y - X @ b
Q = quad(m)
for c in ("lst_offset_f", "lst_s2"):
    print(f"partial corr(air, {c} | lat/lon quad) = {np.corrcoef(resid(m.offset_f.values, Q), resid(m[c].values, Q))[0,1]:.3f}")
a = d[d.lst_offset_f.notna()]
Qa = quad(a); ra = resid(a.lst_offset_f.values, Qa)
print(f"LST explained by lat/lon quadratic, all {len(a)} cells: r2={1-ra.var()/a.lst_offset_f.var():.3f}; land-only:", end=" ")
al = a[a.water_frac < 0.25]; rl = resid(al.lst_offset_f.values, quad(al)); print(f"{1-rl.var()/al.lst_offset_f.var():.3f}")
print(f"air offset explained by lat/lon quadratic (measured, in-sample): r2={1-resid(m.offset_f.values,Q).var()/m.offset_f.var():.3f}")
for c in ["green_share", "building_share", "paved_use_share", "dist_to_lake_km", "dist_to_loop_km"]:
    print(f"  corr(lst, {c:16s}) all cells={a.lst_offset_f.corr(a[c]):6.3f} | corr(air, {c})={m.offset_f.corr(m[c]):6.3f}")
