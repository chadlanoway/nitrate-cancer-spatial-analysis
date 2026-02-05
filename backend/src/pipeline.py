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

ROOT = Path(__file__).resolve().parents[2]
# set paths to scripts
IDW_SCRIPT = ROOT / "backend" / "src" / "idw_preview.py"
TABLE_SCRIPT = ROOT / "backend" / "src" / "tract_nitrate_table.py"
REG_SCRIPT = ROOT / "backend" / "src" / "regression_preview.py"

CACHE_IDW = ROOT / "backend" / "cache" / "idw"
CACHE_TABLES = ROOT / "backend" / "cache" / "tables"
CACHE_RESULTS = ROOT / "backend" / "cache" / "results"

# path helpers
def _k_tag(k: float) -> str:
    return str(k).replace(".", "p")


def idw_raster_path(k: float, cell: float, knn: int) -> Path:
    return CACHE_IDW / f"idw_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.tif"


def tract_table_csv_path(k: float, cell: float, knn: int) -> Path:
    return CACHE_TABLES / f"tract_mean_nitrate_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.csv"


def regression_json_path(k: float, cell: float, knn: int) -> Path:
    return CACHE_RESULTS / f"regression_k{_k_tag(k)}_cs{int(cell)}m_knn{knn}.json"


def run_idw(k: float, cell: float, knn: int) -> Path:
    out = idw_raster_path(k, cell, knn)
    out.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(out) + ".lock")
    with lock:
        # another request may have generated. was getting random race conditions previously
        if out.exists() and out.stat().st_size > 0:
            return out

        tmp = out.with_suffix(out.suffix + ".tmp")

        # write to tmp, then rename
        subprocess.check_call([
            sys.executable, str(IDW_SCRIPT),
            "--k", str(k), "--cell", str(cell), "--knn", str(knn),
            "--out", str(tmp)
        ])

        os.replace(tmp, out)   # atomic
        return out
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
