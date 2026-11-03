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

    # Match the exact crosswalk used to build this local economy, not an
    # unrelated/default snapshot under SIGMA_HOME/references. Fail closed when
    # the original source has changed; do not silently remap sector membership.
    audit_file = eco_dir / 'audit.json'
    if not audit_file.is_file():
        raise FileNotFoundError(f'hierarchical audit missing: {audit_file}')
    audit = json.loads(audit_file.read_text(encoding='utf-8'))
    lineage = audit.get('crosswalk_input', {})
    path = lineage.get('path') if isinstance(lineage, dict) else None
    checksum = lineage.get('sha256') if isinstance(lineage, dict) else None
    if not isinstance(path, str) or not path.strip() or not isinstance(checksum, str) or not checksum:
        raise ValueError('hierarchical crosswalk provenance missing; rebuild the area hierarchy')
    xwalk = Path(path).expanduser().resolve()
    if not xwalk.is_file():
        raise FileNotFoundError(f'hierarchical build crosswalk missing: {xwalk}')
    if _sha(xwalk) != checksum:
        raise ValueError('hierarchical build crosswalk changed; refresh the area hierarchy')
    derivation = spec.get('derivation', {})
    if not isinstance(derivation, dict) or derivation.get('crosswalk_file_sha256') != checksum:
        raise ValueError('hierarchical economy and audit crosswalk provenance disagree')
    # Existing gross-output fallback remains unchanged by this targeted fix.
    # PR #19 crosswalk hash validation above remains authoritative.
    # Select the national gross-output fallback by EXACT source fingerprint.
    from sigma.economy import Economy as _NationalEconomy
    from sigma.economy.hierarchical_auto import packaged_reference as _packaged_reference
    from sigma.economy.hierarchical_auto import read_profile as _read_profile
    source_manifest = workspace / 'hierarchical' / '.sigma-hierarchical-manifest.json'
    if not source_manifest.is_file():
        raise FileNotFoundError('hierarchical source-identity manifest missing')
    source_fingerprint = json.loads(source_manifest.read_text(encoding='utf-8')).get('source_economy_fingerprint')
    if not source_fingerprint:
        raise ValueError('hierarchical source economy fingerprint is missing')
    source_dirs = [workspace.parent.parent / 'references' / 'psa_2018_io240' / 'economy']
    problems = []
    for _lookup in (lambda: _packaged_reference()['io240_dir'], lambda: (_read_profile() or {}).get('io240_dir')):
        try:
            found = _lookup()
            if found:
                source_dirs.append(Path(found))
        except Exception as exc:  # report below only if nothing matches
            problems.append(str(exc))
    matching, seen = [], set()
    for candidate in source_dirs:
        key = str(candidate.expanduser().resolve())
        if key in seen or not (candidate / 'economy.yml').is_file():
            continue
        seen.add(key)
        if _NationalEconomy.from_directory(candidate).economy_fingerprint == source_fingerprint:
            matching.append(candidate)
    if not matching:
        raise ValueError('no national IO240 economy matches this hierarchy (looked in: '
                         + ', '.join(sorted(seen)) + ('; ' + '; '.join(problems) if problems else '')
                         + '); rebuild it with sigma load or sigma economy hierarchical-refresh')
    reference = matching[0].parent
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
    # SIGMA_FIXED_PALETTE_ORIGIN_VORONOI_V1: override heuristic colors only.
    # Keep all existing audits, hierarchy validation and gross-output lineage.
    from sigma.export.fixed_palette import fixed_color as _fixed_sector_color
    for code in codes:
        chosen = _fixed_sector_color(code)
        if chosen is None:
            raise ValueError(f'no fixed 336-sector palette entry for {code!r}')
        colors[code] = chosen
        origins[code] = 'fixed_sigma_sector_palette_336'
    return {'schema_version': 1, 'economy_id': actual_id, 'area_slug': workspace.name,
            'members_sha256': _sha(member_file), 'places_sha256': _sha(places_file),
            'crosswalk_sha256': _sha(xwalk), 'colors': colors,
            'color_origins': origins, 'dominant_io80': dominant}


def _validated_rollup_sector_codes(root: Path, economy_id: str, base_id: str) -> list[str] | None:
    """Read an immutable, hash-verified residual roll-up with this exact Economy ID.

    No guessed palette or fallback-to-sorted-colors is permitted for an identified
    roll-up. All surviving sector codes inherit their unchanged baseline colors.
    """
    if not re.fullmatch(re.escape(base_id) + r'-rollup-[0-9a-f]{16}', economy_id):
        return None
    import yaml
    from sigma.economy.model import Economy

    base_dir = root / 'hierarchical' / 'economy'
    base = Economy.from_directory(base_dir)
    if base.economy_id != base_id:
        raise ValueError('roll-up palette base Economy identity changed')
    rollup_dir = root / 'hierarchical' / 'iterative_rollup'
    candidates: list[Path] = []
    if rollup_dir.is_dir() and not rollup_dir.is_symlink():
        for item in rollup_dir.iterdir():
            if not item.is_dir() or item.is_symlink() or not re.fullmatch(r'[0-9a-f]{24}', item.name):
                continue
            specification = item / 'economy' / 'economy.yml'
            if not specification.is_file() or specification.is_symlink():
                continue
            meta = yaml.safe_load(specification.read_text(encoding='utf-8')) or {}
            if isinstance(meta, dict) and str(meta.get('id', '')).strip() == economy_id:
                candidates.append(item)
    if len(candidates) != 1:
        raise ValueError(f'Expected one derived roll-up package for {economy_id}; found {len(candidates)}')
    package = candidates[0]
    manifest_path = package / 'rollup_manifest.json'
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError('derived roll-up palette requires its package manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    receipt = manifest.get('receipt')
    hashes = manifest.get('file_hashes')
    digest = manifest.get('recipe_sha256')
    scheme = 'sigma-iterative-residual-rollup-v1'
    if (manifest.get('scheme') != scheme or not isinstance(digest, str)
            or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or package.name != digest[:24] or not isinstance(receipt, dict)
            or not isinstance(hashes, dict) or not hashes):
        raise ValueError('derived roll-up manifest identity is invalid')
    mapping = receipt.get('rollup_map')
    if (receipt.get('scheme') != scheme or
            receipt.get('base_economy_fingerprint') != base.economy_fingerprint or
            not isinstance(mapping, dict) or not mapping or
            not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())):
        raise ValueError('derived roll-up is not linked to the current baseline Economy')
    required = {'economy/economy.yml', 'economy/sectors.csv',
                'economy/membership.csv', 'places.parquet'}
    if not required.issubset(hashes):
        raise ValueError('derived roll-up manifest is missing required checksums')
    # Verify every manifest-listed file; do not silently use altered packages.
    for rel, expected in hashes.items():
        if (not isinstance(rel, str) or not isinstance(expected, str)
                or not re.fullmatch(r'[0-9a-f]{64}', expected)):
            raise ValueError('derived roll-up has invalid file hash entries')
        candidate = (package / rel).resolve()
        if (not candidate.is_relative_to(package.resolve()) or
                not candidate.is_file() or candidate.is_symlink() or _sha(candidate) != expected):
            raise ValueError(f'derived roll-up file failed integrity check: {rel}')

    derived_dir = package / 'economy'
    spec = yaml.safe_load((derived_dir / 'economy.yml').read_text(encoding='utf-8')) or {}
    provenance = spec.get('derivation', {})
    if (not isinstance(provenance, dict) or
            provenance.get('source_kind') != 'hierarchical_io240_iterative_rollup' or
            provenance.get('base_economy_fingerprint') != base.economy_fingerprint or
            provenance.get('rollup_map') != mapping or
            provenance.get('rollup_scheme') != scheme or
            provenance.get('recipe_sha256') != digest):
        raise ValueError('derived roll-up economy provenance does not match its manifest')
    derived = Economy.from_directory(derived_dir)
    if derived.economy_id != economy_id:
        raise ValueError('derived roll-up Economy ID does not match the published run')
    original_codes = list(base.sectors.codes)
    derived_codes = list(derived.sectors.codes)
    if (any(k not in original_codes or v not in original_codes or k == v for k, v in mapping.items())
            or any(v in mapping for v in mapping.values())
            or derived_codes != [c for c in original_codes if c not in mapping]):
        raise ValueError('roll-up sectors do not preserve the baseline sector partition')
    old_members = pd.read_csv(base_dir / 'membership.csv', dtype=str, keep_default_na=False)
    new_members = pd.read_csv(derived_dir / 'membership.csv', dtype=str, keep_default_na=False)
    fields = {'economy_code', 'io240_code', 'io80_code', 'io16_code'}
    if (not fields.issubset(old_members.columns) or not fields.issubset(new_members.columns)
            or len(new_members) != len(old_members)
            or old_members.io240_code.duplicated().any()
            or new_members.io240_code.duplicated().any()):
        raise ValueError('derived roll-up membership is incomplete')
    old = old_members.set_index('io240_code')
    new = new_members.set_index('io240_code').reindex(old.index)
    if (new['economy_code'].isna().any() or
            not old['economy_code'].replace(mapping).equals(new['economy_code']) or
            any(not old[f].equals(new[f]) for f in ('io80_code', 'io16_code'))):
        raise ValueError('derived membership does not equal the declared sector roll-up')
    return derived_codes


def load_sector_palette(workspace: str | Path, economy_id: str) -> dict[str, str]:
    """Keep hierarchical sector colors stable through exact residual roll-ups."""
    if '-hierarchical-' not in str(economy_id):
        return {}
    root = _workspace_from(workspace)
    if root is None:
        return {}
    import yaml
    metadata = yaml.safe_load((root/'hierarchical'/'economy'/'economy.yml').read_text(encoding='utf-8')) or {}
    base_id = str(metadata.get('id', '')).strip()
    if base_id != str(economy_id):
        surviving = _validated_rollup_sector_codes(root, str(economy_id), base_id)
        if surviving is None:
            return {}  # A different, unrelated hierarchical Economy.
        baseline = build_palette(root, base_id)
        colors = baseline['colors']
        if any(code not in colors for code in surviving):
            raise ValueError('derived roll-up has a sector without a baseline color')
        # Do not write/overwrite the baseline sector_palette.json for derived runs.
        return {code: colors[code] for code in surviving}
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
