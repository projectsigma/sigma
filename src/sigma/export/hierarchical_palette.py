"""Area-specific hierarchical sector palette for SIGMA.

Only color presentation is changed. Original IO80 codes keep SIGMA's 80-color
palette; IO240 codes use stable HLS lightness variants of their official parent.
IO16 groups use their most frequently *identified* constituent IO80 industry,
falling back to the greatest share of the source IO240 output of group members.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import colorsys
import hashlib
import json
from pathlib import Path
import re

import pandas as pd


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object) -> str:
    return '' if value is None or pd.isna(value) else str(value).strip()


def _io240_shade(base: str, code: str, siblings: list[str]) -> str:
    """Hue from IO80, lightness from official IO240 code position (not area)."""
    try:
        rank = siblings.index(code)
    except ValueError as exc:
        raise ValueError(f'IO240 {code} is missing from official parent listing') from exc
    if len(siblings) == 1:
        return base.upper()
    rgb = tuple(int(base[i:i+2], 16) / 255.0 for i in (1, 3, 5))
    hue, lum, sat = colorsys.rgb_to_hls(*rgb)
    offset = 0.26 * (rank / (len(siblings) - 1) - 0.5)
    lum = min(0.83, max(0.17, lum + offset))
    result = colorsys.hls_to_rgb(hue, lum, sat)
    return '#' + ''.join(f'{round(c * 255):02X}' for c in result)


def _workspace_from(path: str | Path) -> Path | None:
    p = Path(path).expanduser().resolve()
    for parent in (p, *p.parents):
        if (parent / 'hierarchical' / 'economy' / 'membership.csv').is_file():
            return parent
    return None



def _hierarchy_level(code: str) -> tuple[str, str]:
    """Return (source resolution, source code) for legacy or canonical keys."""
    legacy = re.fullmatch(r"(16|80|240):([0-9]+)(?::(?:O|OTHER))?", code, flags=re.I)
    if legacy:
        return legacy.group(1), legacy.group(2)
    if re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{3}", code):
        return '240', code.split(':')[2]
    if re.fullmatch(r"[0-9]{2}:[0-9]{2}(?::o)?", code):
        return '80', code.split(':')[1]
    if re.fullmatch(r"[0-9]{2}(?::o)?", code):
        return '16', code.split(':')[0]
    raise ValueError(f'unsupported hierarchical sector code: {code}')

def build_palette(workspace: str | Path, economy_id: str | None = None) -> dict[str, object]:
    """Build colors from verified hierarchy/membership + local classified places."""
    from sigma.export.qgis import _IO80_PRESENTATION

    workspace = Path(workspace).expanduser().resolve()
    eco_dir = workspace / 'hierarchical' / 'economy'
    member_file = eco_dir / 'membership.csv'
    sector_file = eco_dir / 'sectors.csv'
    places_file = workspace / 'hierarchical' / 'places.parquet'
    meta_file = eco_dir / 'economy.yml'
    if not all(p.is_file() for p in (member_file, sector_file, places_file, meta_file)):
        raise FileNotFoundError(f'hierarchical economy, membership or places missing under {workspace}')

    import yaml
    spec = yaml.safe_load(meta_file.read_text(encoding='utf-8')) or {}
    actual_id = str(spec.get('id', '')).strip()
    if economy_id and economy_id != actual_id:
        raise ValueError(f'wrong hierarchical economy: loaded {actual_id}, expected {economy_id}')

    member = pd.read_csv(member_file, dtype=str, keep_default_na=False)
    sectors = pd.read_csv(sector_file, dtype=str, keep_default_na=False)
    expected = {'economy_code', 'io240_code', 'io80_code', 'io16_code'}
    if not expected.issubset(member) or not {'code', 'label'}.issubset(sectors):
        raise ValueError('hierarchy membership/sector schema invalid')
    codes = sectors.code.tolist()
    if len(codes) != len(set(codes)) or not codes:
        raise ValueError('sector identities are empty or duplicated')
    if member.io240_code.duplicated().any() or len(member) != 240:
        raise ValueError('membership must contain each of 240 industries exactly once')
    if set(member.economy_code) != set(codes):
        raise ValueError('membership and sector codes disagree')
    base80 = {f'{k:02d}': value[0].upper() for k, value in _IO80_PRESENTATION.items()}
    if not set(member.io80_code).issubset(base80):
        raise ValueError('hierarchical membership contains non-IO80 parent')

    # Use the full official crosswalk, never the local subset, for IO240 shades.
    reference = workspace.parent.parent / 'references' / 'psa_2018_io240'
    # A custom SIGMA_HOME may also be used: infer it from workspaces/<slug>.
    xwalk = reference / 'crosswalk.csv'
    if not xwalk.is_file():
        raise FileNotFoundError(f'official IO240 crosswalk missing: {xwalk}')
    cross = pd.read_csv(xwalk, dtype=str, keep_default_na=False)
    if not {'io240_code', 'io80_code'}.issubset(cross):
        raise ValueError('official crosswalk missing required columns')
    if cross.io240_code.duplicated().any() or set(cross.io240_code) != set(member.io240_code):
        raise ValueError('crosswalk must have the same exhaustive IO240 codes as membership')
    official_parents = dict(zip(cross.io240_code, cross.io80_code, strict=True))
    if any(official_parents[row.io240_code] != row.io80_code for row in member.itertuples()):
        raise ValueError('local membership conflicts with official IO240→IO80 crosswalk')
    children = defaultdict(list)
    for child, parent in official_parents.items():
        children[parent].append(child)
    for s in children.values():
        s.sort()
    if set(base80) != set(children):
        raise ValueError('crosswalk does not cover all 80 IO80 parents')

    # Count precise or IO80-level local assignments within each IO16 group.
    local = pd.read_parquet(places_file, columns=['economy_code', 'io240_code', 'io80_code'])
    assigned = defaultdict(Counter)
    allowed = defaultdict(set)
    for r in member.itertuples(index=False):
        allowed[r.economy_code].add(r.io80_code)
    for code, leaf, parent in local[['economy_code', 'io240_code', 'io80_code']].itertuples(index=False, name=None):
        key = _text(code)
        if not key or _hierarchy_level(key)[0] != '16':
            continue
        leaf = _text(leaf)
        parent = official_parents.get(leaf) if leaf else _text(parent)
        if parent in allowed[key]:
            assigned[key][parent] += 1

    # Gross output within the residual group, not an unrelated entire IO80 parent.
    output_file = reference / 'economy' / 'total_output.csv'
    output = {}
    if output_file.is_file():
        x = pd.read_csv(output_file, dtype=str, keep_default_na=False)
        if {'sector', 'total_output'}.issubset(x):
            output = dict(zip(x.sector, pd.to_numeric(x.total_output, errors='raise'), strict=True))
        elif {'code', 'total_output'}.issubset(x):
            output = dict(zip(x.code, pd.to_numeric(x.total_output, errors='raise'), strict=True))
    sector_output = defaultdict(lambda: defaultdict(float))
    for row in member.itertuples(index=False):
        sector_output[row.economy_code][row.io80_code] += float(output.get(row.io240_code, 0.0))

    colors = {}
    dominant = {}
    origins = {}
    for code in codes:
        level, ident = _hierarchy_level(code)
        if level == '80':
            if ident not in base80:
                raise ValueError(f'unknown IO80 sector {code}')
            colors[code] = base80[ident]
            origins[code] = f'fixed_io80:{ident}'
        elif level == '240':
            parent = official_parents.get(ident)
            if not parent:
                raise ValueError(f'unknown IO240 sector {code}')
            colors[code] = _io240_shade(base80[parent], ident, children[parent])
            origins[code] = f'io240_shade_of_io80:{parent}'
        elif level == '16':
            parents = allowed.get(code)
            if not parents:
                raise ValueError(f'no IO80 constituents for {code}')
            counts = assigned[code]
            if counts:
                # Ties resolved by observed residual gross output, then IO80 code.
                parent = sorted(parents, key=lambda p: (-counts[p], -sector_output[code][p], p))[0]
                method = 'local_classified_places'
            else:
                parent = sorted(parents, key=lambda p: (-sector_output[code][p], p))[0]
                method = 'residual_io240_gross_output'
            dominant[code] = {'io80_code': parent, 'method': method,
                              'classified_places': int(counts[parent]),
                              'residual_io240_output': float(sector_output[code][parent])}
            colors[code] = base80[parent]
            origins[code] = f'dominant_io80:{parent}'
        else:
            raise ValueError(f'unsupported hierarchical sector code {code}')
    return {'schema_version': 1, 'economy_id': actual_id, 'area_slug': workspace.name,
            'members_sha256': _sha(member_file), 'places_sha256': _sha(places_file),
            'crosswalk_sha256': _sha(xwalk), 'colors': colors,
            'color_origins': origins, 'dominant_io80': dominant}


def load_sector_palette(workspace: str | Path, economy_id: str) -> dict[str, str]:
    """Lazy computation so future builds and new local partitions are handled."""
    if '-hierarchical-' not in str(economy_id):
        return {}
    root = _workspace_from(workspace)
    if root is None:
        return {}
    import yaml
    metadata = yaml.safe_load((root/'hierarchical'/'economy'/'economy.yml').read_text(encoding='utf-8')) or {}
    if str(metadata.get('id')) != str(economy_id):
        return {}  # e.g., inspecting an old published run, not current hierarchy
    palette = build_palette(root, economy_id)
    # Keep this outside the strictly owned hierarchy package: v7 --replace
    # rejects any extra file inside hierarchical/economy.
    out = root / 'sector_palette.json'
    tmp = out.with_name(out.name + '.tmp')
    tmp.write_text(json.dumps(palette, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(out)
    return palette['colors']


def discover_sector_palette(published_source: str | Path, economy_id: str) -> dict[str, str]:
    return load_sector_palette(published_source, economy_id)
# sigma-canonical-sparse-hierarchy-v1
