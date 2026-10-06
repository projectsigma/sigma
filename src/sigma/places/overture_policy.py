from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Current official Overture Places source licensing.
#
# Overture's Places documentation lists these sources under permissive
# licenses suitable for normal commercial use. The SourceItem schema permits
# `provider` and `license` to be null, so `dataset` is the primary provenance
# key when it is present.
KNOWN_DATASET_LICENSES: dict[str, str] = {
    "meta": "CDLA-Permissive-2.0",
    "microsoft": "CDLA-Permissive-2.0",
    "pinmeto": "CDLA-Permissive-2.0",
    "krick": "CDLA-Permissive-2.0",
    "renderseo": "CDLA-Permissive-2.0",
    "dac": "CDLA-Permissive-2.0",
    "brightquery": "CDLA-Permissive-2.0",
    "alltheplaces": "CC0-1.0",
}

EXCLUDED_DATASETS = {"foursquare"}

ALLOWED_LICENSES = {
    "CDLA-Permissive-2.0",
    "Apache-2.0",
    "CC0-1.0",
}

_LICENSE_ALIASES = {
    "cdla-permissive-2.0": "CDLA-Permissive-2.0",
    "cdla permissive 2.0": "CDLA-Permissive-2.0",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "cc0-1.0": "CC0-1.0",
    "cc0 1.0": "CC0-1.0",
}

_DATASET_ALIASES = {
    "all_the_places": "alltheplaces",
    "all-the-places": "alltheplaces",
    "all the places": "alltheplaces",
    "foursquare_places": "foursquare",
    "microsoft_places": "microsoft",
    "meta_places": "meta",
}


@dataclass(frozen=True, slots=True)
class OvertureSourceDecision:
    allowed: bool
    providers: tuple[str, ...]
    licenses: tuple[str, ...]
    datasets: tuple[str, ...]
    reason: str


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        # pandas.NA raises on bool(), so do not use truthiness here.
        if value is ...:
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.casefold() in {"", "none", "null", "<na>", "nan"}:
        return ""
    return text


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None

    if hasattr(value, "as_py"):
        try:
            value = value.as_py()
        except Exception:
            return None

    if isinstance(value, Mapping):
        return value

    if hasattr(value, "_asdict"):
        try:
            mapped = value._asdict()
        except Exception:
            return None
        if isinstance(mapped, Mapping):
            return mapped

    return None


def source_items(value: Any) -> list[Mapping[str, Any]]:
    """Normalize Arrow/Pandas/list source representations to plain mappings."""
    if value is None:
        return []

    if hasattr(value, "as_py"):
        try:
            value = value.as_py()
        except Exception:
            return []

    mapped = _mapping(value)
    if mapped is not None:
        return [mapped]

    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.tolist()
        except Exception:
            pass

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        out: list[Mapping[str, Any]] = []
        for item in value:
            mapped = _mapping(item)
            if mapped is not None:
                out.append(mapped)
        return out

    return []


def _normalize_dataset(value: Any) -> str:
    raw = _text(value).casefold()
    if not raw:
        return ""

    # Future/current schemas may use provider/resource-like dataset labels.
    head = raw.split("/", 1)[0].strip()
    head = _DATASET_ALIASES.get(head, head)
    return head.replace(" ", "").replace("-", "").replace("_", "")


def _normalize_provider(value: Any) -> str:
    raw = _text(value).casefold()
    if not raw:
        return ""
    raw = _DATASET_ALIASES.get(raw, raw)
    return raw.replace(" ", "").replace("-", "").replace("_", "")


def _canonical_license(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    return _LICENSE_ALIASES.get(raw.casefold(), raw)


def _source_identity(item: Mapping[str, Any]) -> tuple[str, str, str]:
    dataset = _normalize_dataset(item.get("dataset"))
    provider = _normalize_provider(item.get("provider"))
    license_name = _canonical_license(item.get("license"))
    return dataset, provider, license_name


def evaluate_overture_sources(value: Any) -> OvertureSourceDecision:
    """Evaluate one Overture Places `sources` value.

    Policy:
    - prefer `dataset`, because current Places rows can legitimately have
      provider=null;
    - accept explicitly permissive source licenses;
    - when license is null, infer it only for current documented Places
      datasets/providers;
    - reject unknown unlicensed future sources rather than silently weakening
      the project's commercial-use guardrail.
    """
    items = source_items(value)
    if not items:
        return OvertureSourceDecision(
            allowed=False,
            providers=(),
            licenses=(),
            datasets=(),
            reason="missing source provenance",
        )

    providers: set[str] = set()
    datasets: set[str] = set()
    licenses: set[str] = set()
    unresolved: list[str] = []

    for item in items:
        dataset, provider, explicit_license = _source_identity(item)

        if dataset in EXCLUDED_DATASETS or provider in EXCLUDED_DATASETS:
            label = dataset or provider
            return OvertureSourceDecision(
                allowed=False,
                providers=tuple(sorted(providers | ({provider} if provider else set()))),
                licenses=tuple(sorted(licenses)),
                datasets=tuple(sorted(datasets | ({dataset} if dataset else set()))),
                reason=f"{label} is excluded by source policy",
            )

        if dataset:
            datasets.add(dataset)
        if provider:
            providers.add(provider)

        identity = dataset or provider
        if identity and not provider:
            # Preserve a useful source label even when provider is null.
            providers.add(identity)

        if explicit_license:
            if explicit_license not in ALLOWED_LICENSES:
                unresolved.append(
                    f"{identity or 'unknown'} has non-permitted license "
                    f"{explicit_license}"
                )
                continue
            licenses.add(explicit_license)
            continue

        inferred = KNOWN_DATASET_LICENSES.get(dataset) or KNOWN_DATASET_LICENSES.get(provider)
        if inferred:
            licenses.add(inferred)
            continue

        unresolved.append(
            f"{identity or 'unknown'} has no recognized permissive license"
        )

    if unresolved:
        return OvertureSourceDecision(
            allowed=False,
            providers=tuple(sorted(providers)),
            licenses=tuple(sorted(licenses)),
            datasets=tuple(sorted(datasets)),
            reason="; ".join(unresolved),
        )

    if not licenses:
        return OvertureSourceDecision(
            allowed=False,
            providers=tuple(sorted(providers)),
            licenses=(),
            datasets=tuple(sorted(datasets)),
            reason="no permitted source license resolved",
        )

    return OvertureSourceDecision(
        allowed=True,
        providers=tuple(sorted(providers)),
        licenses=tuple(sorted(licenses)),
        datasets=tuple(sorted(datasets)),
        reason="permitted Overture Places provenance",
    )
