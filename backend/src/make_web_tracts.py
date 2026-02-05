"""
WEB READY TRACTS EXPORT
----------------------
Converts analysis GeoJSON outputs from the projected CRS (EPSG:3071)
to geographic coordinates (EPSG:4326) for web mapping.

Strips attributes to only what the frontend needs,
producing a lightweight GeoJSON served by the API.
"""

from pathlib import Path
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
INP = ROOT / "backend" / "cache" / "tables" / "cancer_tracts_with_nitrate_k2p0_cs500m_knn32.geojson"
OUT = ROOT / "backend" / "cache" / "web" / "tracts_4326.geojson"

OUT.parent.mkdir(parents=True, exist_ok=True)

gdf = gpd.read_file(INP)
if gdf.crs is None:
    gdf = gdf.set_crs(epsg=3071)

gdf = gdf.to_crs(epsg=4326)

# Keep only what the frontend needs
keep = ["GEOID10", "canrate", "mean_nitrate", "geometry"]
gdf = gdf[keep]

gdf.to_file(OUT, driver="GeoJSON")
print("Wrote:", OUT)
