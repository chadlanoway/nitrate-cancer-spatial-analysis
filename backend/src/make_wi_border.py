import geopandas as gpd

tracts = gpd.read_file("../cache/web/tracts_4326.geojson")
tracts = tracts.to_crs(4269)  

wi_outline = tracts.unary_union
gpd.GeoDataFrame(geometry=[wi_outline], crs=tracts.crs)\
   .to_file("../data/wi_mask/wi_border.geojson", driver="GeoJSON")
