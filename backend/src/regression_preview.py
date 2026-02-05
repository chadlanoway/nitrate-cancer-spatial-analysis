"""
REGRESSION ANALYSIS
------------------
Runs a simple bivariate linear regression:
    canrate ~ mean_nitrate

Uses the tract level nitrate CSV and produces:
- Regression summary statistics (JSON)
- Tract level predicted values and residuals (CSV)

Results are used by the frontend for display and mapping.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm


ROOT = Path(__file__).resolve().parents[2]  


def default_table_path(k: float, cell: float, knn: int) -> Path:
    k_tag = str(k).replace(".", "p")
    return ROOT / "backend" / "cache" / "tables" / f"tract_mean_nitrate_k{k_tag}_cs{int(cell)}m_knn{knn}.csv"


def main() -> int:
    ap = argparse.ArgumentParser(description="Bivariate linear regression: canrate ~ mean_nitrate")
    ap.add_argument("--csv", type=str, default="", help="Path to tract_mean_nitrate_*.csv")
    ap.add_argument("--k", type=float, default=2.0, help="k used for default cached CSV name (only if --csv blank)")
    ap.add_argument("--cell", type=float, default=500.0, help="cell used for default cached CSV name (only if --csv blank)")
    ap.add_argument("--knn", type=int, default=32, help="knn used for default cached CSV name (only if --csv blank)")
    ap.add_argument("--out-json", type=str, default="", help="Optional output JSON path (summary + diagnostics)")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser().resolve() if args.csv.strip() else default_table_path(args.k, args.cell, args.knn)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)

    # Expects GEOID10, canrate, mean_nitrate
    for col in ("canrate", "mean_nitrate"):
        if col not in df.columns:
            raise KeyError(f"Missing column '{col}' in {csv_path}. Columns: {list(df.columns)}")

    # Drop NaNs / infs
    before = len(df)
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["canrate", "mean_nitrate"]).copy()
    after = len(df)

    y = df["canrate"].astype(float).to_numpy()
    x = df["mean_nitrate"].astype(float).to_numpy()
    X = sm.add_constant(x)  # intercept + slope

    model = sm.OLS(y, X).fit()

    intercept = float(model.params[0])
    slope = float(model.params[1])
    r2 = float(model.rsquared)
    p_slope = float(model.pvalues[1])
    n = int(model.nobs)

    # residual diagnostics
    resid = model.resid
    rmse = float(np.sqrt(np.mean(resid**2)))
    mae = float(np.mean(np.abs(resid)))

    print("\n--- REGRESSION: canrate ~ mean_nitrate ---")
    print(f"Input table: {csv_path}")
    print(f"Rows used:   {after:,} / {before:,} (dropped {before-after:,} with NaN/inf)")
    print(f"n: {n:,}")
    print(f"Intercept: {intercept:.6g}")
    print(f"Slope (per 1 nitrate unit): {slope:.6g}")
    print(f"R^2: {r2:.6g}")
    print(f"p-value (slope): {p_slope:.6g}")
    print(f"RMSE: {rmse:.6g}")
    print(f"MAE:  {mae:.6g}")

    # save a JSON summary for the API/frontend
    out_dir = ROOT / "backend" / "cache" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.out_json.strip():
        out_json = Path(args.out_json).expanduser().resolve()
    else:
        k_tag = str(args.k).replace(".", "p")
        out_json = out_dir / f"regression_k{k_tag}_cs{int(args.cell)}m_knn{args.knn}.json"

    payload = {
        "table": str(csv_path),
        "rows_before": int(before),
        "rows_used": int(after),
        "n": n,
        "model": "OLS",
        "formula": "canrate ~ mean_nitrate",
        "params": {"intercept": intercept, "slope": slope},
        "r2": r2,
        "p_value_slope": p_slope,
        "rmse": rmse,
        "mae": mae,
    }

    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote JSON: {out_json}")

    # write a tract-level residuals CSV for mapping later
    out_resid = out_dir / f"tract_residuals_k{str(args.k).replace('.','p')}_cs{int(args.cell)}m_knn{args.knn}.csv"
    df_out = df.copy()
    df_out["pred_canrate"] = model.fittedvalues
    df_out["resid_canrate"] = resid
    df_out.to_csv(out_resid, index=False)
    print(f"Wrote residuals CSV: {out_resid}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
