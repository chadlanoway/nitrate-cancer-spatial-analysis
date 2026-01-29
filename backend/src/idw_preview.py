from __future__ import annotations
import os


os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
os.environ.pop("GDAL_DATA", None)



try:
    import pyproj
    from pyproj.datadir import get_data_dir as _pyproj_data_dir
    _proj_dir = _pyproj_data_dir()
    os.environ["PROJ_LIB"] = _proj_dir
    os.environ["PROJ_DATA"] = _proj_dir
except Exception:
    pass

try:
    import rasterio
    from rasterio.env import GDALDataFinder
    os.environ["GDAL_DATA"] = GDALDataFinder().search()
except Exception:
    pass

import argparse
import math
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy.spatial import cKDTree


# ----------------------------
# Paths + fields 
# ----------------------------
ROOT = Path(__file__).resolve().parents[2]  

WELLS_SHP = ROOT / "backend" / "data" / "wells" / "well_nitrate.shp"
TRACTS_SHP = ROOT / "backend" / "data" / "cancer_tracts" / "cancer_tracts.shp"

WELLS_VAL_FIELD = "nitr_ran"
TRACTS_RATE_FIELD = "canrate"
TRACTS_ID_FIELD = "GEOID10"

ANALYSIS_EPSG = 3071  # NAD83 / Wisconsin Transverse Mercator (meters)


def require_fields(gdf: gpd.GeoDataFrame, required: list[str], label: str) -> None:
    cols = set(gdf.columns)
    missing = [f for f in required if f not in cols]
    if missing:
        raise KeyError(
            f"{label}: missing required field(s): {missing}. "
            f"Available fields: {sorted(cols)}"
        )


def build_grid(bounds, cell: float):
    """Return (minx, miny, maxx, maxy, ncols, nrows) aligned to bounds."""
    minx, miny, maxx, maxy = bounds
    width = maxx - minx
    height = maxy - miny
    ncols = int(math.ceil(width / cell))
    nrows = int(math.ceil(height / cell))
    # Expand maxx/maxy to fit exact grid
    maxx2 = minx + ncols * cell
    maxy2 = miny + nrows * cell
    return minx, miny, maxx2, maxy2, ncols, nrows


def idw_block(xy_block: np.ndarray, tree: cKDTree, values: np.ndarray, power: float, knn: int):
    """
    Compute IDW prediction for a block of query points.
    xy_block: (N,2) array of x,y in meters
    returns: (N,) float32 predicted values
    """
    # Query nearest wells
    dists, idx = tree.query(xy_block, k=knn, workers=-1)

    # Ensure 2D shapes even if knn=1
    if knn == 1:
        dists = dists[:, None]
        idx = idx[:, None]

    neigh_vals = values[idx]  

    # Handle exact hits: if distance = 0, return that wells value directly
    hit = (dists == 0.0)
    if hit.any():
        # For rows with a hit, take the first hit value
        out = np.empty((xy_block.shape[0],), dtype=np.float32)
        hit_rows = hit.any(axis=1)
        out[~hit_rows] = np.nan  # fill later
        # Assign exact values
        first_hit_col = hit[hit_rows].argmax(axis=1)
        out[hit_rows] = neigh_vals[hit_rows, first_hit_col].astype(np.float32)

        # For the remaining rows, compute normal IDW
        if (~hit_rows).any():
            d = dists[~hit_rows]
            v = neigh_vals[~hit_rows]
            with np.errstate(divide="ignore", invalid="ignore"):
                w = 1.0 / np.power(d, power)
            num = np.sum(w * v, axis=1)
            den = np.sum(w, axis=1)
            out[~hit_rows] = (num / den).astype(np.float32)
        return out

    # Normal IDW
    with np.errstate(divide="ignore", invalid="ignore"):
        w = 1.0 / np.power(dists, power)
    num = np.sum(w * neigh_vals, axis=1)
    den = np.sum(w, axis=1)
    return (num / den).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description="Compute full IDW nitrate raster (EPSG:3071) using kNN KDTree.")
    ap.add_argument("--k", type=float, default=2.0, help="IDW distance decay exponent (k > 1).")
    ap.add_argument("--cell", type=float, default=500.0, help="Grid cell size in meters (e.g., 500 or 250).")
    ap.add_argument("--knn", type=int, default=32, help="Number of nearest wells to use per cell (e.g., 24-64).")
    ap.add_argument("--block-rows", type=int, default=128, help="How many raster rows to compute per block.")
    ap.add_argument("--out", type=str, default="", help="Optional output GeoTIFF path.")
    args = ap.parse_args()

    if args.k <= 1.0:
        raise ValueError("k must be > 1.0 for this project.")
    if args.cell <= 0:
        raise ValueError("cell size must be > 0.")
    if args.knn < 1:
        raise ValueError("knn must be >= 1.")

    if not WELLS_SHP.exists():
        raise FileNotFoundError(f"Wells shapefile not found: {WELLS_SHP}")
    if not TRACTS_SHP.exists():
        raise FileNotFoundError(f"Tracts shapefile not found: {TRACTS_SHP}")

    t0 = time.time()

    # Load
    wells = gpd.read_file(WELLS_SHP)
    tracts = gpd.read_file(TRACTS_SHP)

    # Verify fields exist FIRST
    require_fields(wells, [WELLS_VAL_FIELD], "WELLS")
    require_fields(tracts, [TRACTS_RATE_FIELD, TRACTS_ID_FIELD], "TRACTS")

    # Clamp negatives to 0
    n_before = len(wells)
    neg_count = int((wells[WELLS_VAL_FIELD] < 0).sum())
    wells[WELLS_VAL_FIELD] = wells[WELLS_VAL_FIELD].clip(lower=0)
    print(f"Clamped nitrate values < 0 to 0: {neg_count} / {n_before} wells")

    # Reproject to meters
    wells = wells.to_crs(epsg=ANALYSIS_EPSG)
    tracts = tracts.to_crs(epsg=ANALYSIS_EPSG)
    crs_wkt = tracts.crs.to_wkt()

    # Build grid extent from tracts
    minx, miny, maxx, maxy = tracts.total_bounds
    minx, miny, maxx, maxy, ncols, nrows = build_grid((minx, miny, maxx, maxy), args.cell)

    # Prepare wells arrays
    wells_xy = np.column_stack([wells.geometry.x.to_numpy(), wells.geometry.y.to_numpy()]).astype(np.float64)
    wells_val = wells[WELLS_VAL_FIELD].to_numpy(dtype=np.float64)

    # KDTree
    tree = cKDTree(wells_xy)

    # Output path
    out_path: Path
    if args.out.strip():
        out_path = Path(args.out).expanduser().resolve()
    else:
        out_dir = ROOT / "backend" / "cache" / "idw"
        out_dir.mkdir(parents=True, exist_ok=True)
        k_tag = str(args.k).replace(".", "p")
        out_path = out_dir / f"idw_k{k_tag}_cs{int(args.cell)}m_knn{args.knn}.tif"

    # Raster metadata
    transform = from_origin(minx, maxy, args.cell, args.cell)  # top-left origin
    nodata = -9999.0

    profile = {
        "driver": "GTiff",
        "height": nrows,
        "width": ncols,
        "count": 1,
        "dtype": "float32",
        "crs": crs_wkt,
        "transform": transform,
        "nodata": nodata,
        "tiled": True,
        "compress": "DEFLATE",
        "predictor": 2,
        "zlevel": 6,
        "blockxsize": 256,
        "blockysize": 256,
    }

    # Streaming stats
    vmin = float("inf")
    vmax = float("-inf")
    vsum = 0.0
    vcount = 0

    print("\n--- IDW FULL RASTER SETTINGS ---")
    print(f"k (decay exponent): {args.k}")
    print(f"cell size (m):      {args.cell}")
    print(f"kNN neighbors:      {args.knn}")
    print(f"grid cols x rows:   {ncols} x {nrows}  (~{ncols*nrows:,} cells)")
    print(f"extent (EPSG:3071): minx={minx:.3f}, miny={miny:.3f}, maxx={maxx:.3f}, maxy={maxy:.3f}")
    print(f"output:             {out_path}")

    # Compute and write in row blocks
    t1 = time.time()
    with rasterio.open(out_path, "w", **profile) as dst:
        # Precompute x centers 
        col_idx = np.arange(ncols, dtype=np.float64)
        xs = minx + (col_idx + 0.5) * args.cell

        for row0 in range(0, nrows, args.block_rows):
            row1 = min(row0 + args.block_rows, nrows)
            rr = row1 - row0

            # y centers for this block
            row_idx = np.arange(row0, row1, dtype=np.float64)
            ys = maxy - (row_idx + 0.5) * args.cell

            # Build query points for the block
            # Meshgrid -> (rr*ncols, 2)
            X, Y = np.meshgrid(xs, ys)
            q = np.column_stack([X.ravel(), Y.ravel()])

            # IDW
            pred = idw_block(q, tree, wells_val, power=args.k, knn=args.knn)
            block = pred.reshape((rr, ncols))

            # Replace NaNs with nodata 
            nan_mask = ~np.isfinite(block)
            if nan_mask.any():
                block = block.copy()
                block[nan_mask] = nodata

            # Update stats ignoring nodata
            valid = block != nodata
            if valid.any():
                b = block[valid]
                bmin = float(b.min())
                bmax = float(b.max())
                vmin = min(vmin, bmin)
                vmax = max(vmax, bmax)
                vsum += float(b.sum())
                vcount += int(b.size)

            # Write window
            dst.write(block.astype(np.float32), 1, window=((row0, row1), (0, ncols)))

            # Progress
            done = row1
            pct = 100.0 * done / nrows
            print(f"\rComputing: row {done}/{nrows} ({pct:5.1f}%)", end="")

    print("\n\n--- DONE ---")
    t2 = time.time()
    mean = (vsum / vcount) if vcount else float("nan")
    print(f"Valid cell stats: min={vmin:.4f}, mean={mean:.4f}, max={vmax:.4f} (n={vcount:,})")
    print(f"Timing: load+prep={t1-t0:.2f}s, compute+write={t2-t1:.2f}s, total={t2-t0:.2f}s")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
