"""
TRACT-LEVEL NITRATE AGGREGATION
------------------------------
Aggregates the IDW nitrate raster to census tracts by computing
the mean nitrate value per tract.

Produces:
- A CSV used for regression analysis
- (Optionally) a GeoJSON with mean nitrate appended

This script bridges raster analysis and statistical modeling
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

# deal with local conflicts
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
os.environ.pop("GDAL_DATA", None)

try:
    from pyproj.datadir import get_data_dir as _pyproj_data_dir
    _p = _pyproj_data_dir()
    os.environ["PROJ_LIB"] = _p
    os.environ["PROJ_DATA"] = _p
except Exception:
    pass

try:
    import rasterio
    from rasterio.env import GDALDataFinder
    os.environ["GDAL_DATA"] = GDALDataFinder().search()
except Exception:
    pass

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

# Paths + fields
ROOT = Path(__file__).resolve().parents[2]  

TRACTS_SHP = ROOT / "backend" / "data" / "cancer_tracts" / "cancer_tracts.shp"

TRACT_ID_FIELD = "GEOID10"
CANCER_RATE_FIELD = "canrate"


def require_fields(gdf: gpd.GeoDataFrame, required: list[str], label: str) -> None:
    cols = set(gdf.columns)
    missing = [f for f in required if f not in cols]
    if missing:
        raise KeyError(f"{label}: missing required field(s): {missing}. Available: {sorted(cols)}")


def default_raster_path(k: float, cell: float, knn: int) -> Path:
    k_tag = str(k).replace(".", "p")
    return ROOT / "backend" / "cache" / "idw" / f"idw_k{k_tag}_cs{int(cell)}m_knn{knn}.tif"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compute mean IDW nitrate per tract by rasterizing tracts and aggregating raster values."
    )
    ap.add_argument("--raster", type=str, default="", help="Path to IDW GeoTIFF. If blank, uses cache naming.")
    ap.add_argument("--k", type=float, default=2.0, help="k used for cached raster name (only used if --raster blank)")
    ap.add_argument("--cell", type=float, default=500.0, help="cell used for cached raster name (only used if --raster blank)")
    ap.add_argument("--knn", type=int, default=32, help="knn used for cached raster name (only used if --raster blank)")
    ap.add_argument("--out-csv", type=str, default="", help="Output CSV path (optional)")
    ap.add_argument("--out-geojson", type=str, default="", help="Output GeoJSON path with mean_nitrate appended (optional)")
    args = ap.parse_args()

    # Resolve raster path
    raster_path = Path(args.raster).expanduser().resolve() if args.raster.strip() else default_raster_path(args.k, args.cell, args.knn)
    if not raster_path.exists():
        raise FileNotFoundError(f"Raster not found: {raster_path}")

    if not TRACTS_SHP.exists():
        raise FileNotFoundError(f"Tracts shapefile not found: {TRACTS_SHP}")

    # Load tracts
    tracts = gpd.read_file(TRACTS_SHP)
    require_fields(tracts, [TRACT_ID_FIELD, CANCER_RATE_FIELD], "TRACTS")

    # Open raster + read band
    with rasterio.open(raster_path) as src:
        r_crs = src.crs
        r_transform = src.transform
        height, width = src.height, src.width
        nodata = src.nodata
        nitrate = src.read(1).astype(np.float64)  # use float64 for stable sums

    # Reproject tracts to the raster grid CRS 
    # For this project, the raster grid is always EPSG:3071
    tracts = tracts.to_crs("EPSG:3071")




    # Map each tract to an integer zone id 
    tracts = tracts[[TRACT_ID_FIELD, CANCER_RATE_FIELD, "geometry"]].copy()
    tracts["zone_id"] = np.arange(1, len(tracts) + 1, dtype=np.int32)

    # Rasterize zone IDs onto the raster grid
    shapes = ((geom, int(zid)) for geom, zid in zip(tracts.geometry, tracts["zone_id"]))
    zones = rasterize(
        shapes=shapes,
        out_shape=(height, width),
        transform=r_transform,
        fill=0,
        dtype="int32",
        all_touched=False,  # edge cells included
    )

    # Validate cells
    valid = (zones > 0)
    if nodata is not None:
        valid &= (nitrate != nodata)
    valid &= np.isfinite(nitrate)

    z = zones[valid].astype(np.int32)
    v = nitrate[valid]

    # Aggregate sums and counts per zone id
    n_zones = len(tracts)
    sums = np.bincount(z, weights=v, minlength=n_zones + 1)
    counts = np.bincount(z, minlength=n_zones + 1)

    means = np.full(n_zones + 1, np.nan, dtype=np.float64)
    nonzero = counts > 0
    means[nonzero] = sums[nonzero] / counts[nonzero]

    tracts["mean_nitrate"] = means[tracts["zone_id"].to_numpy()]

    # Report quick stats
    print("\n--- TRACT NITRATE TABLE ---")
    print(f"Raster: {raster_path}")
    print(f"Raster grid: {width} x {height}  (cells={width*height:,})")
    print(f"Tracts: {len(tracts):,}")
    print(f"Cells used: {int(valid.sum()):,}")
    print(f"Tracts with >=1 cell: {int((tracts['mean_nitrate'].notna()).sum()):,}")
    print(f"Mean nitrate (tracts): min={tracts['mean_nitrate'].min():.4f}, mean={tracts['mean_nitrate'].mean():.4f}, max={tracts['mean_nitrate'].max():.4f}")

    # Default outputs
    out_dir = ROOT / "backend" / "cache" / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.out_csv.strip():
        out_csv = Path(args.out_csv).expanduser().resolve()
    else:
        k_tag = str(args.k).replace(".", "p")
        out_csv = out_dir / f"tract_mean_nitrate_k{k_tag}_cs{int(args.cell)}m_knn{args.knn}.csv"

    if args.out_geojson.strip():
        out_geojson = Path(args.out_geojson).expanduser().resolve()
    else:
        k_tag = str(args.k).replace(".", "p")
        out_geojson = out_dir / f"cancer_tracts_with_nitrate_k{k_tag}_cs{int(args.cell)}m_knn{args.knn}.geojson"

   # Write CSV always
    tracts[[TRACT_ID_FIELD, CANCER_RATE_FIELD, "mean_nitrate"]].to_csv(out_csv, index=False)
    print(f"Wrote CSV: {out_csv}")


    # Write GeoJSON only if --out-geojson was provided
    if args.out_geojson.strip():
        tracts.to_file(out_geojson, driver="GeoJSON")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
