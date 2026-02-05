"""
DATA VALIDATION & REPROJECTION CHECK
-----------------------------------
Utility script for inspecting and validating raw input datasets.

Verifies required fields, prints spatial summaries,
and confirms reprojection to the analysis CRS (EPSG:3071).

Used for sanity checks during development, not by the web app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd


# ----------------------------
# Config 
# ----------------------------
ROOT = Path(__file__).resolve().parents[2]  
WELLS_SHP = ROOT / "backend" / "data" / "wells" / "well_nitrate.shp"
TRACTS_SHP = ROOT / "backend" / "data" / "cancer_tracts" / "cancer_tracts.shp"

# Required fields 
WELLS_REQUIRED_FIELDS = ["nitr_ran"]
TRACTS_REQUIRED_FIELDS = ["canrate", "GEOID10"]

# Analysis CRS (meters)
ANALYSIS_EPSG = 3071  # NAD83 / Wisconsin Transverse Mercator


def require_fields(gdf: gpd.GeoDataFrame, required: list[str], label: str) -> None:
    cols = set(gdf.columns)
    missing = [f for f in required if f not in cols]
    if missing:
        raise KeyError(
            f"{label}: missing required field(s): {missing}. "
            f"Available fields: {sorted(cols)}"
        )


def print_summary(gdf: gpd.GeoDataFrame, label: str) -> None:
    crs = gdf.crs
    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
    print(f"\n--- {label} ---")
    print(f"Features: {len(gdf):,}")
    print(f"CRS: {crs}")
    print(f"Bounds: minx={bounds[0]:.6f}, miny={bounds[1]:.6f}, maxx={bounds[2]:.6f}, maxy={bounds[3]:.6f}")


def main() -> int:
    # 1) Ensure files exist
    if not WELLS_SHP.exists():
        print(f"ERROR: Wells shapefile not found: {WELLS_SHP}")
        return 2
    if not TRACTS_SHP.exists():
        print(f"ERROR: Tracts shapefile not found: {TRACTS_SHP}")
        return 2

    # 2) Read shapefiles
    wells = gpd.read_file(WELLS_SHP)
    tracts = gpd.read_file(TRACTS_SHP)

    # 3) Print before summaries
    print_summary(wells, "WELLS (before reprojection)")
    print_summary(tracts, "TRACTS (before reprojection)")

    # 4) Verify fields exist
    require_fields(wells, WELLS_REQUIRED_FIELDS, "WELLS")
    require_fields(tracts, TRACTS_REQUIRED_FIELDS, "TRACTS")
    print("\nField checks: OK")
    print(f"WELLS nitrate field: nitr_ran")
    print(f"TRACTS fields: canrate, GEOID10")

    # 5) Reproject to EPSG:3071 (meters)
    wells_3071 = wells.to_crs(epsg=ANALYSIS_EPSG)
    tracts_3071 = tracts.to_crs(epsg=ANALYSIS_EPSG)

    # 6) Print after summaries 
    print_summary(wells_3071, "WELLS (after reprojection to EPSG:3071)")
    print_summary(tracts_3071, "TRACTS (after reprojection to EPSG:3071)")
    print("\nReprojection: OK (units should now be meters)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
