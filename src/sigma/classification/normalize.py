from __future__ import annotations

import re
import unicodedata

import pandas as pd
from pandas.api.types import is_scalar

_NULLS = {"", "n/a", "na", "none", "null", "-", "others", "other", "unknown"}


def clean_literal(value: object) -> str | None:
    if value is None:
        return None
    try:
        if is_scalar(value) and bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return text or None


def clean_source_text(value: object) -> str | None:
    text = clean_literal(value)
    if text is None or text.casefold() in _NULLS:
        return None
    return text


def _fold_key(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"[^\w=:+&/.-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def normalize_key(value: object) -> str:
    return _fold_key(clean_source_text(value) or "")


def normalize_match_key(value: object) -> str:
    return _fold_key(clean_literal(value) or "")
