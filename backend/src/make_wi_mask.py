from shapely.geometry import box
import geopandas as gpd


wi = gpd.read_file("../data/wi_mask/wi_border.geojson").geometry.iloc[0]


world = box(-180, -90, 180, 90)


mask = world.difference(wi)

gpd.GeoDataFrame(geometry=[mask], crs="EPSG:4269")\
   .to_file("../data/wi_mask/wi_mask.geojson", driver="GeoJSON")
