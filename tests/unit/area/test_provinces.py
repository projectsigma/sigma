"""Regression tests for SIGMA's derived provincial areas."""
from __future__ import annotations

import yaml
from shapely import union_all

from sigma.area import load_boundary
from sigma.area.catalog import list_areas, load_areas, resolve_area


def test_all_provinces_have_unique_slugs_and_exact_psgc_memberships():
    areas = load_areas()
    provinces = list_areas(kind="province")
    assert len(areas) == 1727
    assert len(provinces) == 82
    assert len({province.slug for province in provinces}) == 82
    for province in provinces:
        expected = {
            area.psgc_code
            for area in areas.values()
            if area.kind in {"city", "municipality"} and area.province == province.name
        }
        assert expected
        assert province.boundary is not None
        assert set(province.members) == expected
        assert set(province.boundary.value) == expected
        assert province.psgc_code is None


def test_name_resolution_preserves_existing_city_and_municipality_slugs():
    assert resolve_area("palawan").kind == "province"
    assert resolve_area("Province of Palawan").slug == "palawan"
    assert resolve_area("cebu").kind == "city"
    assert resolve_area("cebu_province").kind == "province"
    assert resolve_area("Cebu Province").slug == "cebu_province"
    assert resolve_area("metro_cebu").kind == "composite"
    assert resolve_area("leyte").kind == "municipality"
    assert resolve_area("leyte_province").kind == "province"
    assert resolve_area("mountain_province").kind == "province"


def test_provinces_exclude_independent_highly_urbanized_cities():
    cebu = resolve_area("cebu_province")
    assert len(cebu.members) == 50
    assert "0730600000" not in cebu.members  # Cebu City
    assert "0731100000" not in cebu.members  # Lapu-Lapu
    assert "0731300000" not in cebu.members  # Mandaue


def test_custom_area_catalog_is_not_implicitly_extended(tmp_path):
    area_file = tmp_path / "areas.yml"
    area_file.write_text(
        yaml.safe_dump(
            {"areas": {"sample": {
                "name": "Sample", "kind": "city", "province": "Example",
                "bbox": [0, 0, 1, 1],
            }}}
        ),
        encoding="utf-8",
    )
    assert list(load_areas(area_file)) == ["sample"]


def test_guimaras_geometry_equals_union_of_its_member_geometries():
    areas = load_areas()
    guimaras = resolve_area("guimaras")
    assert len(guimaras.members) == 5
    by_psgc = {
        area.psgc_code: area
        for area in areas.values()
        if area.kind in {"city", "municipality"}
    }
    expected = union_all([load_boundary(by_psgc[code]) for code in guimaras.members])
    assert load_boundary(guimaras).equals(expected)
