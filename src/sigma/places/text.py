from __future__ import annotations

import re
import unicodedata


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if text.casefold() in {"", "none", "null", "nan", "n/a", "na", "unknown"}:
        return ""
    return text


def fold(value: object) -> str:
    text = clean_text(value).casefold().replace("&", " and ")
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    # Every run of other characters, whitespace included, becomes one space,
    # so no second whitespace pass is needed.
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def combine(*values: object) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        key = fold(text)
        if key and key not in seen:
            seen.add(key)
            out.append(text)
    return " | ".join(out)
