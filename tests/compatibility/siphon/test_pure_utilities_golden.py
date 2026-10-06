from __future__ import annotations

from sigma.places.licensing import OSM_LICENSE, join_terms, overture_record_allowed, overture_terms
from sigma.places.overture_policy import evaluate_overture_sources
from sigma.places.text import clean_text, combine, fold


def test_text_contract_examples():
    assert clean_text("  Café  ") == "Café"
    assert fold("Café & BAR / Quezón") == "cafe and bar quezon"
    assert combine("Café", "cafe", "Bakery") == "Café | Bakery"


def test_licensing_contract_examples():
    assert OSM_LICENSE == "ODbL-1.0"
    providers, licenses = overture_terms(
        [{"dataset": "Meta"}, {"dataset": "AllThePlaces"}, {"dataset": "FutureProvider"}]
    )
    assert providers == ("alltheplaces", "futureprovider", "meta")
    assert licenses == ("CC0-1.0", "CDLA-Permissive-2.0", "OVERTURE-PLACES-REVIEW")
    assert not overture_record_allowed(providers)
    assert join_terms(["ODbL-1.0|CC0-1.0", "CC0-1.0"]) == "CC0-1.0|ODbL-1.0"


def test_overture_policy_remains_fail_closed():
    allowed = evaluate_overture_sources([{"dataset": "meta", "provider": None, "license": None}])
    assert allowed.allowed is True
    assert allowed.providers == ("meta",)
    assert allowed.licenses == ("CDLA-Permissive-2.0",)

    excluded = evaluate_overture_sources(
        [{"dataset": "foursquare", "provider": None, "license": "Apache-2.0"}]
    )
    assert excluded.allowed is False
    assert "excluded by source policy" in excluded.reason

    unknown = evaluate_overture_sources([{"dataset": "future-provider", "license": None}])
    assert unknown.allowed is False
    assert "no recognized permissive license" in unknown.reason
