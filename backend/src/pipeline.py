from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IDW_SCRIPT = ROOT / "backend" / "src" / "idw_preview.py"
TABLE_SCRIPT = ROOT / "backend" / "src" / "tract_nitrate_table.py"
REG_SCRIPT = ROOT / "backend" / "src" / "regression_preview.py"

CACHE_IDW = ROOT / "backend" / "cache" / "idw"
CACHE_TABLES = ROOT / "backend" / "cache" / "tables"
CACHE_RESULTS = ROOT / "backend" / "cache" / "results"


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
    if out.exists():
        return out
    subprocess.check_call(
        ["python", str(IDW_SCRIPT), "--k", str(k), "--cell", str(cell), "--knn", str(knn)]
    )
    if not out.exists():
        raise FileNotFoundError(f"IDW output missing after run: {out}")
    return out


def run_table(k: float, cell: float, knn: int) -> Path:
    out = tract_table_csv_path(k, cell, knn)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    subprocess.check_call(
        ["python", str(TABLE_SCRIPT), "--k", str(k), "--cell", str(cell), "--knn", str(knn)]
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
        ["python", str(REG_SCRIPT), "--k", str(k), "--cell", str(cell), "--knn", str(knn)]
    )
    if not out.exists():
        raise FileNotFoundError(f"Regression output missing after run: {out}")
    return out
