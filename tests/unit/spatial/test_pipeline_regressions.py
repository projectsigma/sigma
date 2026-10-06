import geopandas as gpd
from shapely.geometry import Point, box

from sigma.spatial.pipeline import SpatialPipeline


def test_spatial_cleaners_preserve_custom_economy_codes():
    centers = gpd.GeoDataFrame(
        {"type": ["1"], "cluster": [0], "center_network_node": [7]},
        geometry=[Point(0, 0)],
        crs="EPSG:3857",
    )
    cleaned_centers = SpatialPipeline._clean_center_output(centers)
    assert cleaned_centers.loc[0, "type"] == "1"

    partitions = gpd.GeoDataFrame(
        {"type": ["1"], "cluster": [0]},
        geometry=[box(-1, -1, 1, 1)],
        crs="EPSG:3857",
    )
    cleaned_partitions = SpatialPipeline._clean_partition_output(partitions, {("1", 0)})
    assert cleaned_partitions.loc[0, "type"] == "1"
