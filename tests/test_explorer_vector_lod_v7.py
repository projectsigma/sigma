"""Regression tests for MVT real-point LOD (no external vector-tile package)."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from sigma.web.mvt_points import _keep, _lod_rank, _mercator, write_point_tiles, ZOOM_RATES


def _read_uvarint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
        shift += 7


def _fields(data: bytes):
    pos = 0
    while pos < len(data):
        tag, pos = _read_uvarint(data, pos)
        wire = tag & 7
        if wire == 0:
            value, pos = _read_uvarint(data, pos)
        elif wire == 2:
            length, pos = _read_uvarint(data, pos)
            value = data[pos:pos + length]
            pos += length
        elif wire == 1:
            value = data[pos:pos + 8]
            pos += 8
        else:
            raise AssertionError(f'unsupported wire {wire}')
        yield tag >> 3, value


def _tile_ids(path: Path) -> set[str]:
    contents = path.read_bytes()
    layer = next(v for f, v in _fields(contents) if f == 3)
    features = [v for f, v in _fields(layer) if f == 2]
    keys = [v.decode() for f, v in _fields(layer) if f == 3]
    values = [v for f, v in _fields(layer) if f == 4]
    assert next(v for f, v in _fields(layer) if f == 15) == 2
    assert next(v for f, v in _fields(layer) if f == 1) == b'places'
    ids = set()
    for feature in features:
        tags = next(v for f, v in _fields(feature) if f == 2)
        pairs = []
        pos = 0
        while pos < len(tags):
            key, pos = _read_uvarint(tags, pos)
            val, pos = _read_uvarint(tags, pos)
            pairs.append((keys[key], values[val]))
        identity = next(v for k, v in pairs if k == 'id')
        ident = next(v.decode() for f, v in _fields(identity) if f == 1)
        # Every scored MVT feature carries the SAME deterministic hash rank
        # used by z8–11 previews. Ghost context never adds artificial points.
        lod_bytes = next(v for key, v in pairs if key == 'lod_rank')
        rank = struct.unpack('<d', next(v for f, v in _fields(lod_bytes) if f == 3))[0]
        assert rank == _lod_rank(ident)
        assert 0 <= rank < 1
        assert len([1 for f, v in _fields(feature) if f == 4]) == 1
        ids.add(ident)
    return ids


def test_real_point_vector_lod_complete_and_stable(tmp_path):
    # All z12/z13 scored records, previews a nested subset; unscored never leak.
    from collections import defaultdict
    tiles = defaultdict(list)
    for i in range(200):
        lon, lat = 121.0 + i * 0.00025, 14.66
        props = {'id': f'point-{i:04d}', 'name': f'Shop {i}',
                 'type': '06:55:178', 'original_type': '06:55:178',
                 'node_id': 'genuine-X-cluster', 'cluster': 3, 'score': 0.3,
                 'unclustered': False}
        tx, ty = _mercator(lon, lat, 13)
        tiles[(int(tx), int(ty))].append({'type':'Feature', 'properties':props,
            'geometry':{'type':'Point','coordinates':[lon,lat]}})
    tiles[(1, 1)].append({'properties': {'id':'unscored', 'type':'06', 'unclustered':True},
        'geometry':{'type':'Point','coordinates':[121.0,14.66]}})
    meta = write_point_tiles(tmp_path, tiles)
    assert meta['exact_from_zoom'] == 12
    ids_by_zoom = {}
    for zoom in ZOOM_RATES:
        paths=list((tmp_path/'data/points-v7'/str(zoom)).rglob('*.pbf'))
        assert paths
        ids_by_zoom[zoom]=set().union(*(_tile_ids(path) for path in paths))
        assert 'unscored' not in ids_by_zoom[zoom]
    full = {f'point-{i:04d}' for i in range(200)}
    assert ids_by_zoom[12] == full
    assert ids_by_zoom[13] == full
    for z in (8,9,10,11):
        assert ids_by_zoom[z] == {p for p in full if _keep(p,ZOOM_RATES[z])}
    assert ids_by_zoom[8] <= ids_by_zoom[9] <= ids_by_zoom[10] <= ids_by_zoom[11]
    assert ids_by_zoom[11] < full
