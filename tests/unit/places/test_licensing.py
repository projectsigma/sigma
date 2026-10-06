from sigma.places.licensing import OSM_LICENSE, overture_record_allowed, overture_terms


def test_osm_license_identity():
    assert OSM_LICENSE == "ODbL-1.0"


def test_overture_provider_terms_are_preserved():
    providers, licenses = overture_terms([{"dataset": "Meta"}, {"dataset": "AllThePlaces"}])
    assert providers == ("alltheplaces", "meta")
    assert set(licenses) == {"CC0-1.0", "CDLA-Permissive-2.0"}


def test_unknown_overture_provider_is_flagged_for_review():
    providers, licenses = overture_terms([{"dataset": "FutureProvider"}])
    assert providers == ("futureprovider",)
    assert "OVERTURE-PLACES-REVIEW" in licenses


def test_unknown_overture_provider_is_not_allowed():
    providers, licenses = overture_terms([{"dataset": "future-provider"}])
    assert providers == ("futureprovider",)
    assert "OVERTURE-PLACES-REVIEW" in licenses
    assert not overture_record_allowed(providers)


def test_missing_overture_provenance_is_not_allowed():
    providers, licenses = overture_terms(None)
    assert providers == ()
    assert "OVERTURE-PLACES-REVIEW" in licenses
    assert not overture_record_allowed(providers)
