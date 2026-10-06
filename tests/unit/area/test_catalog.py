from sigma.area.catalog import load_areas, resolve_area


def test_packaged_area_catalog_contains_all_current_lgus_and_three_composites():
    areas = load_areas()
    localities = [a for a in areas.values() if a.kind in {"city", "municipality"}]
    composites = [a for a in areas.values() if a.kind == "composite"]

    assert len(areas) == 1645
    assert len(localities) == 1642
    assert sum(area.kind == "city" for area in localities) == 149
    assert sum(area.kind == "municipality" for area in localities) == 1493
    assert all(area.psgc_code for area in localities)
    assert all(area.boundary for area in localities)
    assert {area.slug for area in composites} == {
        "metro_manila",
        "metro_cebu",
        "metro_davao",
    }
    assert all(area.psgc_code is None for area in composites)
    assert all(area.boundary for area in composites)


def test_psgc_is_an_alias():
    area = resolve_area("1381300000")
    assert area.name.casefold() == "quezon city"
    assert area.psgc_code == "1381300000"


def test_name_resolution_works_when_unambiguous():
    area = resolve_area("Quezon City")
    assert area.psgc_code == "1381300000"


def test_composite_memberships_are_fixed_and_resolvable():
    areas = load_areas()
    assert len(areas["metro_manila"].members) == 17
    assert len(areas["metro_cebu"].members) == 13
    assert len(areas["metro_davao"].members) == 15
    assert resolve_area("NCR").slug == "metro_manila"
    assert resolve_area("Metropolitan Davao").slug == "metro_davao"


def test_load_areas_cache_returns_fresh_mapping():
    first = load_areas()
    first.pop("quezon_city")
    second = load_areas()
    assert "quezon_city" in second


def test_custom_catalog_cache_refreshes_when_file_metadata_changes(tmp_path):
    import os
    import yaml

    path = tmp_path / "areas.yml"

    def write(name: str) -> None:
        path.write_text(
            yaml.safe_dump(
                {
                    "areas": {
                        "sample": {
                            "name": name,
                            "kind": "city",
                            "bbox": [0, 0, 1, 1],
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    write("Alpha")
    assert load_areas(path)["sample"].name == "Alpha"
    before = path.stat()
    write("Bravo")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    assert load_areas(path)["sample"].name == "Bravo"
