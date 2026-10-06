from sigma.places.overture_policy import evaluate_overture_sources


def test_meta_dataset_is_allowed_when_provider_and_license_are_null():
    decision = evaluate_overture_sources(
        [
            {
                "dataset": "meta",
                "provider": None,
                "license": None,
                "record_id": "123",
            }
        ]
    )
    assert decision.allowed
    assert decision.providers == ("meta",)
    assert decision.licenses == ("CDLA-Permissive-2.0",)


def test_foursquare_dataset_is_rejected_even_if_license_would_be_permissive():
    decision = evaluate_overture_sources(
        [{"dataset": "foursquare", "provider": None, "license": "Apache-2.0"}]
    )
    assert not decision.allowed
    assert "excluded by source policy" in decision.reason


def test_mixed_lineage_is_rejected_when_any_source_is_foursquare():
    decision = evaluate_overture_sources(
        [
            {"dataset": "meta", "provider": None, "license": None},
            {"dataset": "foursquare", "provider": None, "license": None},
        ]
    )
    assert not decision.allowed
    assert "foursquare" in decision.datasets
    assert "excluded by source policy" in decision.reason


def test_known_provider_can_be_used_when_dataset_is_missing():
    decision = evaluate_overture_sources(
        [{"dataset": None, "provider": "microsoft", "license": None}]
    )
    assert decision.allowed
    assert decision.providers == ("microsoft",)
    assert decision.licenses == ("CDLA-Permissive-2.0",)


def test_unknown_unlicensed_future_source_fails_closed():
    decision = evaluate_overture_sources(
        [{"dataset": "future-provider", "provider": None, "license": None}]
    )
    assert not decision.allowed
    assert "no recognized permissive license" in decision.reason


def test_unknown_source_with_explicit_permissive_license_is_allowed():
    decision = evaluate_overture_sources(
        [{"dataset": "future-provider", "license": "Apache-2.0"}]
    )
    assert decision.allowed
    assert decision.licenses == ("Apache-2.0",)


def test_non_permitted_explicit_license_is_rejected():
    decision = evaluate_overture_sources(
        [{"dataset": "future-provider", "license": "CC-BY-NC-4.0"}]
    )
    assert not decision.allowed
    assert "non-permitted license" in decision.reason
