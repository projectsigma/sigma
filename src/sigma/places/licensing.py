from __future__ import annotations

import re
from collections.abc import Iterable

OSM_LICENSE = "ODbL-1.0"
OVERTURE_REVIEW = "OVERTURE-PLACES-REVIEW"
# Current Overture Places provider terms, audited 2026-09-30.
_PROVIDER_LICENSES = {
    "meta": "CDLA-Permissive-2.0",
    "microsoft": "CDLA-Permissive-2.0",
    "pinmeto": "CDLA-Permissive-2.0",
    "krick": "CDLA-Permissive-2.0",
    "renderseo": "CDLA-Permissive-2.0",
    "dac": "CDLA-Permissive-2.0",
    "brightquery": "CDLA-Permissive-2.0",
    "alltheplaces": "CC0-1.0",
}
_PROVIDER_ALIASES = {
    "all_the_places": "alltheplaces",
    "all the places": "alltheplaces",
    "pin me to": "pinmeto",
}


def _norm_provider(value: object) -> str:
    text = re.sub(r"[^a-z0-9_ ]+", "", str(value or "").casefold()).strip()
    return _PROVIDER_ALIASES.get(text, text.replace(" ", ""))


def _walk(value: object) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, dict):
        for key in ("dataset", "provider", "source"):
            if key in value and value[key] is not None:
                yield str(value[key])
        for item in value.values():
            if isinstance(item, (dict, list, tuple, set)):
                yield from _walk(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk(item)
        return
    # Arrow/numpy-backed values often expose a Python conversion.
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        converted = tolist()
        if converted is not value:
            yield from _walk(converted)
            return
    text = str(value)
    # Fallback for serialized structs/lists.
    for provider in _PROVIDER_LICENSES:
        if re.search(rf"(?<![a-z0-9]){re.escape(provider)}(?![a-z0-9])", text.casefold()):
            yield provider
    if "all_the_places" in text.casefold() or "all the places" in text.casefold():
        yield "alltheplaces"


def overture_terms(value: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    providers = sorted({_norm_provider(x) for x in _walk(value) if _norm_provider(x)})
    known = [p for p in providers if p in _PROVIDER_LICENSES]
    unknown = [p for p in providers if p not in _PROVIDER_LICENSES]
    licenses = sorted({_PROVIDER_LICENSES[p] for p in known})
    if unknown or not providers:
        licenses.append(OVERTURE_REVIEW)
    return tuple(providers), tuple(dict.fromkeys(licenses))


def join_terms(values: Iterable[object]) -> str:
    terms: set[str] = set()
    for value in values:
        if value is None:
            continue
        for term in str(value).split("|"):
            term = term.strip()
            if term:
                terms.add(term)
    return "|".join(sorted(terms))


def overture_record_allowed(providers: Iterable[str]) -> bool:
    """Fail closed: retain only currently audited, permitted Overture providers."""
    provider_set = {_norm_provider(value) for value in providers if _norm_provider(value)}
    if not provider_set:
        return False
    return provider_set.issubset(_PROVIDER_LICENSES)
