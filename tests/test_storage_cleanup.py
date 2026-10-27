"""Storage cleanup must never undermine SIGMA's active dependency graph or outputs."""
import json
import os
import time
from pathlib import Path

import pytest

from sigma.storage import inspect_workspace, prune


def workspace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "workspace.json").write_text(json.dumps({"output_dir": str(root / "output")}))
    (root / "output").mkdir()
    (root / "artifacts" / ".state").mkdir(parents=True)
    (root / "artifacts" / ".tmp").mkdir()
    return root


def age(path, days=40):
    stamp = time.time() - days * 86400
    for p in sorted(path.rglob('*'), reverse=True) if path.is_dir() else []:
        os.utime(p, (stamp, stamp))
    os.utime(path, (stamp, stamp))


def artifact(root, stage, fingerprint, ident, deps=None):
    directory = root / 'artifacts' / stage / fingerprint
    directory.mkdir(parents=True)
    (directory / 'results.json').write_text('data')
    manifest = {
        'stage': stage, 'recipe_fingerprint': fingerprint, 'artifact_id': ident,
        'recipe': {'dependencies': deps or {}},
    }
    (directory / 'artifact.json').write_text(json.dumps(manifest))
    age(directory)
    return directory


def active(root, refs):
    items = {}
    for stage, fp, ident in refs:
        items[stage] = {'stage': stage, 'recipe_fingerprint': fp, 'artifact_id': ident,
                        'manifest': f'{stage}/{fp}/artifact.json'}
    (root / 'artifacts' / '.state' / 'active.json').write_text(json.dumps({
        'schema_version': 1, 'artifacts': items,
    }))


def test_debris_preview_then_apply_keeps_real_outputs(tmp_path):
    root = workspace(tmp_path)
    tmp = root / 'artifacts' / '.tmp' / 'road-dead-000000000001-aa'
    tmp.mkdir()
    (tmp / 'junk.bin').write_bytes(b'x' * 30)
    oldexport = root / 'output' / '.sigma-export-stale'
    oldexport.mkdir()
    (oldexport / 'data').write_bytes(b'y' * 20)
    age(tmp)
    age(oldexport)
    current = root / 'output' / 'sigma_points.parquet'
    current.write_bytes(b'good')
    report = inspect_workspace(root)
    assert {c.category for c in report.candidates} == {
        'abandoned artifact staging', 'abandoned export staging'
    }
    assert all(status == 'preview' for _, status in prune(report))
    assert tmp.exists() and oldexport.exists()
    assert all(status == 'deleted' for _, status in prune(report, apply=True))
    assert current.read_bytes() == b'good'
    assert any(path == current for path, _ in report.largest_files)


def test_new_intermediates_not_eligible(tmp_path):
    root = workspace(tmp_path)
    recent = root / 'artifacts' / '.tmp' / 'recent'
    recent.mkdir()
    (recent / 'inprogress').write_text('x')
    assert not inspect_workspace(root).candidates


def test_obsolete_cleanup_keeps_active_and_transitive_dependencies(tmp_path):
    root = workspace(tmp_path)
    source = artifact(root, 'source.pbf', 'a' * 64, 'src-1')
    current = artifact(root, 'analysis.x', 'b' * 64, 'art-2', {
        'source.pbf': {'stage': 'source.pbf', 'recipe_fingerprint': 'a' * 64, 'artifact_id': 'src-1'}
    })
    stale = artifact(root, 'analysis.x', 'c' * 64, 'art-3')
    active(root, [('analysis.x', 'b' * 64, 'art-2')])
    report = inspect_workspace(root, obsolete=True)
    assert [c.path for c in report.candidates] == [stale]
    assert report.protected_reason is None
    prune(report, apply=True)
    assert source.exists() and current.exists() and not stale.exists()


def test_bad_active_pointer_disables_obsolete_pruning(tmp_path):
    root = workspace(tmp_path)
    old = artifact(root, 'analysis.x', 'b' * 64, 'art-old')
    active(root, [('analysis.x', 'a' * 64, 'art-missing')])
    report = inspect_workspace(root, obsolete=True)
    assert report.protected_reason
    assert not report.candidates
    assert old.exists()


def test_history_files_disable_obsolete_pruning(tmp_path):
    root = workspace(tmp_path)
    old = artifact(root, 'analysis.x', 'c' * 64, 'art-old')
    artifact(root, 'analysis.x', 'd' * 64, 'art-current')
    active(root, [('analysis.x', 'd' * 64, 'art-current')])
    (root / 'runs').mkdir()
    (root / 'runs' / 'historical.json').write_text('{}')
    report = inspect_workspace(root, obsolete=True)
    assert report.protected_reason == 'run archives are present'
    assert old.exists() and not report.candidates


def test_explorer_backup_requires_valid_current_bundle(tmp_path):
    root = workspace(tmp_path)
    backup = root / 'output' / ('.explorer.backup-' + 'a' * 32)
    backup.mkdir()
    (backup / 'data').write_text('older')
    age(backup)
    assert not inspect_workspace(root).candidates
    live = root / 'output' / 'explorer'
    live.mkdir()
    (live / 'index.html').write_text('new')
    (live / '.sigma-explorer').write_text('{}')
    report = inspect_workspace(root)
    assert [c.path for c in report.candidates] == [backup]


def test_symlink_candidate_never_deleted(tmp_path):
    root = workspace(tmp_path)
    outside = tmp_path / 'personal'
    outside.mkdir()
    (outside / 'file').write_text('important')
    link = root / 'artifacts' / '.tmp' / 'someone-else'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    assert not inspect_workspace(root).candidates
    assert (outside / 'file').exists()


def test_custom_source_data_and_quarantine_kept_by_default(tmp_path):
    root = workspace(tmp_path)
    custom = root / 'places' / 'reviewed.parquet'
    custom.parent.mkdir()
    custom.write_text('curated')
    q = root / 'artifacts' / '.corrupt' / 'analysis.x' / 'bad'
    q.mkdir(parents=True)
    (q / 'bad.json').write_text('before')
    age(q)
    assert not inspect_workspace(root).candidates
    assert custom.exists() and q.exists()
    report = inspect_workspace(root, quarantine=True)
    assert [c.path for c in report.candidates] == [q]


def test_changed_active_graph_skips_previous_obsolete_candidate(tmp_path):
    root = workspace(tmp_path)
    old = artifact(root, 'analysis.x', 'c' * 64, 'art-old')
    artifact(root, 'analysis.x', 'd' * 64, 'art-current')
    active(root, [('analysis.x', 'd' * 64, 'art-current')])
    preview = inspect_workspace(root, obsolete=True)
    assert [c.path for c in preview.candidates] == [old]
    active(root, [('analysis.x', 'c' * 64, 'art-old')])
    result = prune(preview, apply=True)
    assert result[0][1].startswith('skipped')
    assert old.exists()


def test_explorer_ui_temp_only_with_valid_bundle(tmp_path):
    root = workspace(tmp_path)
    bundle = root / 'output' / 'explorer'
    bundle.mkdir()
    tmp = bundle / '.sigma-ui-crashed'
    tmp.write_text('partial')
    age(tmp)
    assert not inspect_workspace(root).candidates
    (bundle / '.sigma-explorer').write_text('{}')
    assert [c.path for c in inspect_workspace(root).candidates] == [tmp]
