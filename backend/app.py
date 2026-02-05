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

import os
from pyproj.datadir import get_data_dir as _pyproj_data_dir

import io
import numpy as np
import rasterio
from rasterio.enums import Resampling
from PIL import Image
from pyproj import Transformer


from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
import geopandas as gpd
from pathlib import Path
import json

from src.pipeline import run_idw, run_table, run_regression, idw_raster_path, tract_table_csv_path, regression_json_path

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

    # ensure items exist in cache
    raster = run_idw(k, cell, knn)
    table = run_table(k, cell, knn)
    result = run_regression(k, cell, knn)

    payload = json.loads(Path(result).read_text(encoding="utf-8"))
    payload.update({
        "k": k,
        "cell": cell,
        "knn": knn,
        "raster_path": str(raster),
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

    run_idw(k, cell, knn)       
    run_table(k, cell, knn)
    run_regression(k, cell, knn)


    # base tracts geojson (already has id/canrate/mean nitrate)
    base_path = Path(__file__).resolve().parent / "cache" / "web" / "tracts_4326.geojson"
    tracts = json.loads(base_path.read_text(encoding="utf-8"))

    # residuals csv produced by regression_preview.py. used in the tooltip in main
    k_tag = str(k).replace(".", "p")
    resid_csv = Path(__file__).resolve().parents[0] / "cache" / "results" / f"tract_residuals_k{k_tag}_cs{int(cell)}m_knn{knn}.csv"

    import pandas as pd
    df = pd.read_csv(resid_csv, dtype={"GEOID10": str})
    keep = df[["GEOID10", "pred_canrate", "resid_canrate"]].copy()
    lut = keep.set_index("GEOID10").to_dict(orient="index")

    for f in tracts.get("features", []):
        props = f.get("properties") or {}
        geoid = str(props.get("GEOID10") or "")
        if geoid in lut:
            props["pred_canrate"] = float(lut[geoid]["pred_canrate"])
            props["resid_canrate"] = float(lut[geoid]["resid_canrate"])
        f["properties"] = props

    return jsonify(tracts)


def _idw_path_from_query():
    k = float(request.args.get("k", 2.0))
    cell = float(request.args.get("cell", 500.0))
    knn = int(request.args.get("knn", 32))
    if k <= 1:
        return None, (jsonify({"error": "k must be > 1"}), 400)
    p = run_idw(k, cell, knn)
    return (k, cell, knn, p), None


@app.get("/api/idw_meta")
def api_idw_meta():
    q, err = _idw_path_from_query()
    if err:
        return err
    k, cell, knn, tif_path = q

    with rasterio.open(tif_path) as src:
        b = src.bounds  # EPSG:3071 meters

    # Force CRS. This was a huge headache to figure out
    tfm = Transformer.from_crs("EPSG:3071", "EPSG:4326", always_xy=True)


    tl = tfm.transform(b.left,  b.top)
    tr = tfm.transform(b.right, b.top)
    br = tfm.transform(b.right, b.bottom)
    bl = tfm.transform(b.left,  b.bottom)

    return jsonify({
        "k": k, "cell": cell, "knn": knn,
        "url": f"/api/idw.png?k={k}&cell={cell}&knn={knn}",
        "coordinates": [list(tl), list(tr), list(br), list(bl)],
    })


@app.get("/api/idw.png")
def api_idw_png():
    q, err = _idw_path_from_query()
    if err:
        return err
    k, cell, knn, tif_path = q

    # Read + downsample for web speed
    max_dim = int(request.args.get("max", 1400))  # limit png size
    with rasterio.open(tif_path) as src:
        w, h = src.width, src.height
        scale = min(1.0, max_dim / max(w, h))
        out_w = max(1, int(w * scale))
        out_h = max(1, int(h * scale))

        data = src.read(
            1,
            out_shape=(out_h, out_w),
            resampling=Resampling.bilinear
        ).astype(np.float32)

        nodata = src.nodata

    # Mask nodata
    if nodata is not None:
        mask = (data == nodata)
    else:
        mask = np.zeros_like(data, dtype=bool)

    # Color ramp for nitrate, leaned heavily on chatgtp for help
    # Clamp expected nitrate range 
    vmin, vmax = 0.0, 16.0
    t = (np.clip(data, vmin, vmax) - vmin) / (vmax - vmin + 1e-9)

    # piecewise gradient
    r = np.zeros_like(t)
    g = np.zeros_like(t)
    b = np.zeros_like(t)

    # 0..0.5: blue -> cyan
    m1 = t <= 0.5
    tt = t[m1] / 0.5
    r[m1] = 0
    g[m1] = tt
    b[m1] = 1

    # 0.5..0.75: cyan -> yellow
    m2 = (t > 0.5) & (t <= 0.75)
    tt = (t[m2] - 0.5) / 0.25
    r[m2] = tt
    g[m2] = 1
    b[m2] = 1 - tt

    # 0.75..1: yellow -> red
    m3 = t > 0.75
    tt = (t[m3] - 0.75) / 0.25
    r[m3] = 1
    g[m3] = 1 - tt
    b[m3] = 0

    alpha = np.full_like(t, 160, dtype=np.uint8)  # opacity
    alpha[mask] = 0

    rgba = np.dstack([
        (r * 255).astype(np.uint8),
        (g * 255).astype(np.uint8),
        (b * 255).astype(np.uint8),
        alpha
    ])

    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)

    return send_file(buf, mimetype="image/png")

if __name__ == "__main__":
    app.run(debug=True)
