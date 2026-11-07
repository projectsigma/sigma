"""Conservative regression checks for the optional zoom-adaptive Explorer bundle.

These supplement existing end-to-end web tests. They do not rewrite SIGMA models.
"""
from pathlib import Path

from sigma.web import builder


def test_lod_is_bounded_and_distinct_from_analysis():
    assert builder.POINT_BUDGET == 8000
    assert builder.AGGREGATE_LEVELS == (11, 13, 15, 17)
    assert builder.GRAPH_SHARD_SIZE == 16
    assert builder.AGGREGATE_BUDGET == 4000


def test_explorer_does_not_eager_load_green_heatmap():
    js = (Path(builder.__file__).parent / 'static' / 'app.js').read_text(encoding='utf-8')
    assert "overview-counts" not in js
    assert "heatmap" not in js
    assert "data/graph-nodes.json" in js
    assert "data/aggregate/index.json" in js
    assert "preloadNetworkAdjacency" in js
    assert "loadPartitionNeighborhood" in js
    assert "voronoiOpacity" in js
    assert "syncRenderedEstablishments" in js
    assert "inVisibleNetwork" in js
    assert "fill-opacity', 0.07" in js
    assert "map.setPaintProperty('partition-fill', 'fill-color', color)" in js
    assert "visiblePointGroups = groups" in js
    assert "network.ring.has(String(properties.node_id || ''))" in js
    # V7 renders scored points through native vector tiles, not a rebuilt
    # GeoJSON scored-feature array. The old GeoJSON source remains empty.
    assert "map.addSource('native-points', {type: 'vector'" in js
    assert 'data/points-v7/{z}/{x}/{y}.pbf' in js
    assert "map.addLayer({id: 'native-establishments', type: 'circle'" in js
    assert "map.setFilter('native-establishments', filter)" in js
    assert "setData('points', EMPTY())" in js
    assert "visibility('partition-linked-line', false)" in js
    assert "visibility('partition-focus-line', foreground)" in js
    assert "const foreground = mode === 'network' && !!network;" in js
