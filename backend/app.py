"""
FLASK API SERVER
----------------
Serves as the backend API for the web app.

Exposes endpoints that:
- Generate or retrieve cached IDW rasters
- Compute tract level nitrate summaries
- Run regression analysis
- Serve GeoJSON and PNG to the frontend

This file does not do analysis logic directly.
it orchestrates cached steps via src/pipeline.py
"""

import io
import zipfile
from datetime import datetime, timezone
from flask import Response
import os
from pyproj.datadir import get_data_dir as _pyproj_data_dir
import pandas as pd
from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
from pathlib import Path
import json
import math
from src.pipeline import (
    ensure_idw_outputs,
    idw_png_path,
    idw_meta_path,
    tract_table_csv_path,
    regression_json_path,
)

def _safe_num(x):
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    return v if math.isfinite(v) else None

app = Flask(__name__)
CORS(app)

@app.route("/api/health")
def health():
    return jsonify(status="ok")

@app.get("/api/regression")
def api_regression():
    # default params for page load
    k = float(request.args.get("k", 2.0))
    cell = float(request.args.get("cell", 500.0))
    knn = int(request.args.get("knn", 32))

    if k <= 1:
        return jsonify({"error": "k must be > 1"}), 400

    ensure_idw_outputs(k, cell, knn, want_png=False, want_table=True, want_reg=True)
    result = regression_json_path(k, cell, knn)
    table = tract_table_csv_path(k, cell, knn)


    payload = json.loads(Path(result).read_text(encoding="utf-8"))
    payload.update({
        "k": k,
        "cell": cell,
        "knn": knn,
        "table_path": str(table),
        "result_path": str(result),
    })
    return jsonify(payload)

@app.get("/api/tracts")
def api_tracts():
    # same as above
    k = float(request.args.get("k", 2.0))
    cell = float(request.args.get("cell", 500.0))
    knn = int(request.args.get("knn", 32))
    if k <= 1:
        return jsonify({"error": "k must be > 1"}), 400

    ensure_idw_outputs(k, cell, knn, want_png=False, want_table=True, want_reg=True)

    # base tracts geojson (saves space in the cache storing the geom once)
    base_path = Path(__file__).resolve().parent / "cache" / "web" / "tracts_4326.geojson"
    tracts = json.loads(base_path.read_text(encoding="utf-8"))

    table_csv = tract_table_csv_path(k, cell, knn)
    df_table = pd.read_csv(table_csv, dtype={"GEOID10": str})
    lut_n = df_table.set_index("GEOID10")["mean_nitrate"].to_dict()
    # residuals csv produced by regression_preview.py. used in the tooltip in main
    k_tag = str(k).replace(".", "p")
    resid_csv = Path(__file__).resolve().parents[0] / "cache" / "results" / f"tract_residuals_k{k_tag}_cs{int(cell)}m_knn{knn}.csv"

    df = pd.read_csv(resid_csv, dtype={"GEOID10": str})
    keep = df[["GEOID10", "pred_canrate", "resid_canrate"]].copy()
    lut = keep.set_index("GEOID10").to_dict(orient="index")

    for f in tracts.get("features", []):
        props = f.get("properties") or {}
        geoid = str(props.get("GEOID10") or "")
        if geoid in lut:
            props["pred_canrate"]  = _safe_num(lut[geoid].get("pred_canrate"))
            props["resid_canrate"] = _safe_num(lut[geoid].get("resid_canrate"))

        if geoid in lut_n:
            props["mean_nitrate"] = _safe_num(lut_n[geoid])

        f["properties"] = props


    return jsonify(tracts)

@app.post("/api/report.zip")
def api_report_zip_post():
    q, err = _idw_params_from_query()
    if err:
        return err
    k, cell, knn = q

    # Ensure cached artifacts exist (like other endpoints)
    ensure_idw_outputs(k, cell, knn, want_png=True, want_table=True, want_reg=True)

    # Get uploaded png
    f = request.files.get("scatter_png")
    png_bytes = f.read() if f else None

    # Load regression + tracts (reuse your existing paths/logic)
    reg_path = regression_json_path(k, cell, knn)
    reg = json.loads(Path(reg_path).read_text(encoding="utf-8"))

    base_path = Path(__file__).resolve().parent / "cache" / "web" / "tracts_4326.geojson"
    tracts = json.loads(base_path.read_text(encoding="utf-8"))

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Residuals report</title>
<style>
  body {{
    font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    margin: 24px;
    background: #000;
    color: #fff;
  }}

  h1, h2 {{
    color: #fff;
  }}

  p {{
    color: #ddd;
  }}

  img {{
    max-width: 100%;
    height: auto;
    border: 1px solid #444;
    border-radius: 6px;
    margin-top: 8px;
  }}

  pre {{
    background: #111;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
    color: #0f0;  /* optional: green JSON vibe */
  }}
</style>
</head>
<body>

<h1>Residuals report</h1>
<p>k={k} &nbsp; cell={int(cell)}m &nbsp; knn={knn}</p>

<h2>Scatter</h2>
{"<img src='scatter.png' alt='Scatter plot'/>" if png_bytes else "<p>(no scatter image)</p>"}

<h2>Regression</h2>
<pre>{json.dumps(reg, indent=2)}</pre>

</body>
</html>"""
    
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.html", html)
        z.writestr("regression.json", json.dumps(reg, indent=2))
        z.writestr("tracts.geojson", json.dumps(tracts))
        if png_bytes:
            z.writestr("scatter.png", png_bytes)

    mem.seek(0)
    return Response(
        mem.getvalue(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=report.zip",
            "Cache-Control": "no-store",
        },
    )

def _idw_params_from_query():
    k = float(request.args.get("k", 2.0))
    cell = float(request.args.get("cell", 500.0))
    knn = int(request.args.get("knn", 32))
    if k <= 1:
        return None, (jsonify({"error": "k must be > 1"}), 400)
    return (k, cell, knn), None


@app.get("/api/idw_meta")
def api_idw_meta():
    q, err = _idw_params_from_query()
    if err:
        return err
    k, cell, knn = q

    max_dim = int(request.args.get("max", 1400))
    ensure_idw_outputs(k, cell, knn, want_png=True, want_table=False, want_reg=False, max_dim=max_dim)

    meta_path = idw_meta_path(k, cell, knn)
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return jsonify(payload)

@app.get("/api/idw.png")
def api_idw_png():
    q, err = _idw_params_from_query()
    if err:
        return err
    k, cell, knn = q

    max_dim = int(request.args.get("max", 1400))
    ensure_idw_outputs(k, cell, knn, want_png=True, want_table=False, want_reg=False, max_dim=max_dim)

    png_path = idw_png_path(k, cell, knn, max_dim)
    resp = send_file(png_path, mimetype="image/png", conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


if __name__ == "__main__":
    app.run(debug=True)
