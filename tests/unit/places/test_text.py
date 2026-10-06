from __future__ import annotations

from sigma.places.text import clean_text, combine, fold


def test_clean_text_preserves_content_and_normalizes_nullish_values():
    assert clean_text(None) == ""
    assert clean_text("  Café  ") == "Café"
    for value in ("none", "NULL", "nan", "n/a", "NA", "unknown", "   "):
        assert clean_text(value) == ""


def test_fold_is_case_accent_and_punctuation_insensitive():
    assert fold(" Café & BAR / Quezón ") == "cafe and bar quezon"


def test_combine_deduplicates_by_folded_identity_but_preserves_first_text():
    assert combine(" Café ", "cafe", None, "Bakery", "BAKERY", "Unknown") == "Café | Bakery"
