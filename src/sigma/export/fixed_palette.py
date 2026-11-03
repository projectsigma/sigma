"""Fixed, user-specified 336-color SIGMA palette (16 + 80 + 240).

Original canonical codes are the source of truth. Residual codes inherit their
explicit 16/80 parent; no color is inferred from a changed sector order.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources
import json
import re


@lru_cache(maxsize=1)
def palette() -> dict[str, str]:
    raw = json.loads(resources.files('sigma.export').joinpath('sector_palette_336.json').read_text(encoding='utf-8'))
    if raw.get('schema') != 'sigma-sector-palette/1' or not isinstance(raw.get('colors'), dict):
        raise ValueError('unexpected SIGMA palette schema')
    colors = raw['colors']
    if len(colors) != 336:
        raise ValueError(f'expected 336 canonical sector colors, found {len(colors)}')
    groups = [sum(bool(re.fullmatch(pattern, code)) for code in colors) for pattern in
              (r'\d{2}', r'\d{2}:\d{2}', r'\d{2}:\d{2}:\d{3}')]
    if groups != [16, 80, 240] or any(not re.fullmatch(r'#[0-9A-Fa-f]{6}', c) for c in colors.values()):
        raise ValueError('invalid canonical palette level or hex color')
    legacy = raw.get('legacy')
    if not isinstance(legacy, dict) or len(legacy) != 336:
        raise ValueError('invalid legacy palette mapping')
    allowed = {v.upper() for v in colors.values()}
    for code, color in legacy.items():
        if not re.fullmatch(r'(16|80|240):\d+', code) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', color):
            raise ValueError(f'invalid legacy entry {code}')
        if color.upper() not in allowed:
            raise ValueError(f'legacy palette is inconsistent for {code}')
    return {**{k: str(v).upper() for k, v in colors.items()},
            **{k: str(v).upper() for k, v in legacy.items()}}


def fixed_color(code: object, *, level: str | None = None, economy_id: str | None = None) -> str | None:
    """Return fixed hex for an unambiguous canonical or legacy sector code.

    Numeric codes are ambiguous among IO16/80/240 without an explicit level.
    Residual X:o takes X; X:Y:o takes X:Y. No hierarchical tint is invented.
    """
    raw = str(code).strip()
    colors = palette()
    direct = colors.get(raw)
    if direct:
        return direct
    if re.fullmatch(r'\d{2}:\d{2}:o', raw, re.I):
        return colors.get(raw[:-2])
    if re.fullmatch(r'\d{2}:o', raw, re.I):
        return colors.get(raw[:-2])
    if re.fullmatch(r'(16|80):\d+:(?:o|other)', raw, re.I):
        return colors.get(raw.rsplit(':', 1)[0].lstrip().lower().replace('16:', '16:').replace('80:', '80:'))
    if raw.isdigit():
        import re as _re
        name = str(level or '').lower()
        if not name and economy_id:
            found = _re.fullmatch(r'psa-2018-io(16|80|240)', economy_id.lower())
            if found:
                name = f'io{found.group(1)}'
        if name in {'16', '80', '240'}:
            name = f'io{name}'
        if name in {'io16', 'io80', 'io240'}:
            width = 3 if name == 'io240' else 2
            return colors.get(f'{name[2:]}:{int(raw):0{width}d}')
    return None
