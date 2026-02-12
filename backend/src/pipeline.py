"""
PIPELINE ORCHESTRATOR
---------------------
Coordinates the analysis pipeline with caching and file locking.

Responsible for:
- Determining cache paths
- Running IDW, tract aggregation, and regression steps only when needed
- Ensuring concurrent API requests do not recompute the same artifacts

Acts as middleman between Flask endpoints and standalone analysis scripts.
"""

from __future__ import annotations

from filelock import FileLock
import os, sys, subprocess
from pathlib import Path

import json, tempfile
import rasterio
import numpy as np
from rasterio.enums import Resampling
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
# set paths to scripts
IDW_SCRIPT = ROOT / "backend" / "src" / "idw_preview.py"
TABLE_SCRIPT = ROOT / "backend" / "src" / "tract_nitrate_table.py"
REG_SCRIPT = ROOT / "backend" / "src" / "regression_preview.py"

CACHE_TABLES = ROOT / "backend" / "cache" / "tables"
CACHE_RESULTS = ROOT / "backend" / "cache" / "results"

CACHE_PNG = ROOT / "backend" / "cache" / "png"
CACHE_META = ROOT / "backend" / "cache" / "meta"

# path helpers
def idw_png_path(k: float, cell: float, knn: int, max_dim: int = 1400) -> Path:
    return CACHE_PNG / f"idw_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}_max{int(max_dim)}.png"

def idw_meta_path(k: float, cell: float, knn: int) -> Path:
    return CACHE_META / f"idw_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.json"

def bundle_lock_path(k: float, cell: float, knn: int) -> Path:
    # one lock per parameter combo
    d = ROOT / "backend" / "cache" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"idw_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.lock"

def _k_tag(k: float) -> str:
    return str(k).replace(".", "p")


def tract_table_csv_path(k: float, cell: float, knn: int) -> Path:
    return CACHE_TABLES / f"tract_mean_nitrate_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.csv"


def regression_json_path(k: float, cell: float, knn: int) -> Path:
    return CACHE_RESULTS / f"regression_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.json"

# make the csv of residuals
def run_table(k: float, cell: float, knn: int) -> Path:
    out = tract_table_csv_path(k, cell, knn)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    subprocess.check_call(
        [sys.executable, str(TABLE_SCRIPT), "--k", str(k), "--cell", str(cell), "--knn", str(knn)]
    )
    if not out.exists():
        raise FileNotFoundError(f"Table output missing after run: {out}")
    return out

def run_regression(k: float, cell: float, knn: int) -> Path:
    out = regression_json_path(k, cell, knn)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    subprocess.check_call(
        [sys.executable, str(REG_SCRIPT), "--k", str(k), "--cell", str(cell), "--knn", str(knn)]
    )
    if not out.exists():
        raise FileNotFoundError(f"Regression output missing after run: {out}")
    return out

# Temp tif
def ensure_idw_outputs(k: float, cell: float, knn: int, *, want_png=True, want_table=False, want_reg=False, max_dim: int = 1400):
    png_out  = idw_png_path(k, cell, knn, max_dim)
    meta_out = idw_meta_path(k, cell, knn)
    csv_out  = tract_table_csv_path(k, cell, knn)
    reg_out  = regression_json_path(k, cell, knn)

    CACHE_PNG.mkdir(parents=True, exist_ok=True)
    CACHE_META.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(bundle_lock_path(k, cell, knn)))
    with lock:
        # fast path: everything already exists
        if (not want_png or png_out.exists()) and (not want_table or csv_out.exists()) and (not want_reg or reg_out.exists()) and meta_out.exists():
            return

        # build a tif in temp
        with tempfile.TemporaryDirectory() as td:
            tmp_tif = Path(td) / f"idw_tmp_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.tif"

            # run IDW into tmp tif (no cache/idw write)
            subprocess.check_call([
                sys.executable, str(IDW_SCRIPT),
                "--k", str(k), "--cell", str(cell), "--knn", str(knn),
                "--out", str(tmp_tif)
            ])

            # write meta once (needed for idw_meta without a tif on disk)
            with rasterio.open(tmp_tif) as src:
                b = src.bounds
            tfm = Transformer.from_crs("EPSG:3071", "EPSG:4326", always_xy=True)
            tl = tfm.transform(b.left,  b.top)
            tr = tfm.transform(b.right, b.top)
            br = tfm.transform(b.right, b.bottom)
            bl = tfm.transform(b.left,  b.bottom)
            meta_out.write_text(json.dumps({
                "k": k, "cell": cell, "knn": knn,
                "coordinates": [list(tl), list(tr), list(br), list(bl)],
                "url": f"/api/idw.png?k={k}&cell={cell}&knn={knn}&max={max_dim}"
            }), encoding="utf-8")

            # build tract CSV/GeoJSON if needed (target tmp_tif)
            if want_table and (not csv_out.exists() or csv_out.stat().st_size == 0):
                subprocess.check_call([
                    sys.executable, str(TABLE_SCRIPT),
                    "--k", str(k), "--cell", str(cell), "--knn", str(knn),
                    "--raster", str(tmp_tif),
                    "--out-csv", str(csv_out),
                ])

            # regression 
            if want_reg and (not reg_out.exists() or reg_out.stat().st_size == 0):
                if not csv_out.exists():
                    raise FileNotFoundError(f"Missing tract CSV: {csv_out}")
                subprocess.check_call([
                    sys.executable, str(REG_SCRIPT),
                    "--k", str(k), "--cell", str(cell), "--knn", str(knn),
                    "--csv", str(csv_out),
                    "--out-json", str(reg_out)
                ])

            # build PNG if needed (from tmp_tif)
            if want_png and (not png_out.exists() or png_out.stat().st_size == 0):
                with rasterio.open(tmp_tif) as src:
                    w, h = src.width, src.height
                    scale = min(1.0, max_dim / max(w, h))
                    out_w = max(1, int(w * scale))
                    out_h = max(1, int(h * scale))
                    data = src.read(1, out_shape=(out_h, out_w), resampling=Resampling.bilinear).astype(np.float32)
                    nodata = src.nodata

                mask = (data == nodata) if nodata is not None else np.zeros_like(data, dtype=bool)

                vmin, vmax = 0.0, 16.0
                t = (np.clip(data, vmin, vmax) - vmin) / (vmax - vmin + 1e-9)

                r = np.zeros_like(t); g = np.zeros_like(t); b = np.zeros_like(t)
                m1 = t <= 0.5; tt = t[m1] / 0.5
                r[m1] = 0; g[m1] = tt; b[m1] = 1
                m2 = (t > 0.5) & (t <= 0.75); tt = (t[m2] - 0.5) / 0.25
                r[m2] = tt; g[m2] = 1; b[m2] = 1 - tt
                m3 = t > 0.75; tt = (t[m3] - 0.75) / 0.25
                r[m3] = 1; g[m3] = 1 - tt; b[m3] = 0

                alpha = np.full_like(t, 160, dtype=np.uint8)
                alpha[mask] = 0
                rgba = np.dstack([(r*255).astype(np.uint8),(g*255).astype(np.uint8),(b*255).astype(np.uint8),alpha])

                img = Image.fromarray(rgba, mode="RGBA")
                png_out.parent.mkdir(parents=True, exist_ok=True)
                tmp = png_out.with_suffix(".tmp")
                img.save(tmp, format="PNG", optimize=True)
                os.replace(tmp, png_out)