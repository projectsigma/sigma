from __future__ import annotations

import json
from pathlib import Path

import pytest

from sigma.artifacts import ArtifactRecipe, ArtifactStore
from sigma.errors import ArtifactValidationError
from sigma.sources import SourceStore


def _commit(store: ArtifactStore, recipe: ArtifactRecipe, text: str = "payload"):
    write = store.begin_write(recipe)
    write.output("result.txt").write_text(text, encoding="utf-8")
    return store.commit(write)


def test_recipe_fingerprint_is_order_independent():
    left = ArtifactRecipe.build(
        "synthetic.stage",
        implementation_version="1",
        parameters={"b": 2, "a": 1},
        resources={"z": "2", "a": "1"},
    )
    right = ArtifactRecipe.build(
        "synthetic.stage",
        implementation_version="1",
        parameters={"a": 1, "b": 2},
        resources={"a": "1", "z": "2"},
    )
    assert left.fingerprint == right.fingerprint


def test_atomic_commit_lookup_and_content_validation(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    write = store.begin_write(recipe)
    output = write.output("nested/result.txt")
    output.write_text("ok", encoding="utf-8")
    temp = write.path
    ref = store.commit(write, metadata={"rows": 1})

    assert not temp.exists()
    assert ref.path.is_dir()
    assert store.lookup(recipe.stage, recipe.fingerprint) == ref
    validation = store.validate(ref, expected_recipe=recipe)
    assert validation.valid
    assert validation.status == "complete"
    assert store.manifest(ref).metadata["rows"] == 1


def test_file_existence_without_manifest_is_not_reusable(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    directory = store.root / recipe.stage / recipe.fingerprint
    directory.mkdir(parents=True)
    (directory / "result.txt").write_text("looks complete", encoding="utf-8")

    assert store.lookup(recipe.stage, recipe.fingerprint) is None


def test_output_tampering_is_corrupt_not_complete(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    ref = _commit(store, recipe, "before")
    (ref.path / "result.txt").write_text("after", encoding="utf-8")

    validation = store.validate(ref, expected_recipe=recipe)
    assert not validation.valid
    assert validation.status == "corrupt"
    assert validation.reason in {"artifact_size_changed", "artifact_hash_mismatch"}


def test_parameter_change_marks_existing_artifact_stale(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    old = ArtifactRecipe.build("synthetic.stage", implementation_version="1", parameters={"k": 5})
    ref = _commit(store, old)
    new = ArtifactRecipe.build("synthetic.stage", implementation_version="1", parameters={"k": 6})

    validation = store.validate(ref, expected_recipe=new)
    assert validation.status == "stale"
    assert validation.reason == "parameter_changed"


def test_implementation_change_marks_existing_artifact_stale(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    old = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    ref = _commit(store, old)
    new = ArtifactRecipe.build("synthetic.stage", implementation_version="2")

    validation = store.validate(ref, expected_recipe=new)
    assert validation.status == "stale"
    assert validation.reason == "implementation_version_changed"


def test_source_content_change_marks_existing_artifact_stale(tmp_path):
    sources = SourceStore(tmp_path / "sources")
    source_path = tmp_path / "input.txt"
    source_path.write_text("one", encoding="utf-8")
    source_one = sources.register_user_file(source_path)
    old = ArtifactRecipe.build("synthetic.stage", implementation_version="1", sources={"input": source_one})
    store = ArtifactStore(tmp_path / "artifacts")
    ref = _commit(store, old)

    source_path.write_text("two", encoding="utf-8")
    source_two = sources.register_user_file(source_path)
    assert source_one.source_id != source_two.source_id
    new = ArtifactRecipe.build("synthetic.stage", implementation_version="1", sources={"input": source_two})

    validation = store.validate(ref, expected_recipe=new)
    assert validation.status == "stale"
    assert validation.reason == "source_changed"


def test_dependency_identity_change_marks_existing_artifact_stale(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    dep_recipe_1 = ArtifactRecipe.build("synthetic.upstream", implementation_version="1", parameters={"n": 1})
    dep_one = _commit(store, dep_recipe_1, "one")
    old = ArtifactRecipe.build("synthetic.downstream", implementation_version="1", dependencies={"up": dep_one})
    ref = _commit(store, old)

    dep_recipe_2 = ArtifactRecipe.build("synthetic.upstream", implementation_version="1", parameters={"n": 2})
    dep_two = _commit(store, dep_recipe_2, "two")
    new = ArtifactRecipe.build("synthetic.downstream", implementation_version="1", dependencies={"up": dep_two})

    validation = store.validate(ref, expected_recipe=new)
    assert validation.status == "stale"
    assert validation.reason == "dependency_changed"


def test_same_recipe_same_output_is_idempotent(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    first = _commit(store, recipe, "same")
    second = _commit(store, recipe, "same")
    assert second == first


def test_same_recipe_different_output_is_refused(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    _commit(store, recipe, "one")
    with pytest.raises(ArtifactValidationError, match="immutable artifact"):
        _commit(store, recipe, "two")


def test_active_refs_persist_and_status_explains_missing_and_stale(tmp_path):
    root = tmp_path / "artifacts"
    store = ArtifactStore(root)
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1", parameters={"x": 1})
    write = store.begin_write(recipe)
    write.output("result.txt").write_text("ok", encoding="utf-8")
    ref = store.commit(write, make_active=True)

    reopened = ArtifactStore(root)
    assert reopened.active("synthetic.stage") == ref
    complete = reopened.status({"synthetic.stage": recipe})["synthetic.stage"]
    assert complete.valid

    changed = ArtifactRecipe.build("synthetic.stage", implementation_version="1", parameters={"x": 2})
    stale = reopened.status({"synthetic.stage": changed})["synthetic.stage"]
    assert stale.status == "stale"
    assert stale.reason == "parameter_changed"

    missing = reopened.status({"synthetic.other": ArtifactRecipe.build("synthetic.other", implementation_version="1")})
    assert missing["synthetic.other"].status == "missing"
    assert missing["synthetic.other"].reason == "no_active_artifact"


def test_recipe_nested_inputs_are_immutable_after_construction():
    parameters = {"nested": {"values": [1, 2]}}
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1", parameters=parameters)
    fingerprint = recipe.fingerprint
    parameters["nested"]["values"].append(3)
    assert recipe.fingerprint == fingerprint
    with pytest.raises(TypeError):
        recipe.parameters["nested"]["new"] = 1


def test_invalid_active_manifest_is_reported_corrupt(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    write = store.begin_write(recipe)
    write.output("result.txt").write_text("ok", encoding="utf-8")
    ref = store.commit(write, make_active=True)
    ref.manifest_path.write_text("not json", encoding="utf-8")
    status = store.status({"synthetic.stage": recipe})["synthetic.stage"]
    assert status.status == "corrupt"
    assert status.reason == "active_reference_invalid"


def test_corrupt_same_recipe_can_be_recomputed_and_is_quarantined(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    first = _commit(store, recipe, "correct")
    (first.path / "result.txt").write_text("corrupt", encoding="utf-8")
    assert store.validate(first, expected_recipe=recipe).status == "corrupt"

    repaired = _commit(store, recipe, "correct")
    assert store.validate(repaired, expected_recipe=recipe).valid
    quarantined = list((store.root / ".corrupt" / recipe.stage).iterdir())
    assert len(quarantined) == 1
    assert (quarantined[0] / "result.txt").read_text(encoding="utf-8") == "corrupt"


def test_manifest_to_dict_is_deeply_json_serializable(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build(
        "synthetic.stage",
        implementation_version="1",
        parameters={"nested": {"values": [1, 2]}},
    )
    write = store.begin_write(recipe)
    write.output("result.txt").write_text("ok", encoding="utf-8")
    ref = store.commit(
        write,
        metadata={"counts": {"coded": 1}},
        provenance={"nested": {"provider": "fixture"}},
    )
    # Frozen nested mappings must be converted back to ordinary JSON containers.
    json.dumps(store.manifest(ref).to_dict(), sort_keys=True)


def test_nonreusable_artifact_can_be_superseded_without_weakening_immutability(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")

    first_write = store.begin_write(recipe)
    first_write.output("result.txt").write_text("fallback", encoding="utf-8")
    first = store.commit(first_write, metadata={"cache_reusable": False}, make_active=True)

    second_write = store.begin_write(recipe)
    second_write.output("result.txt").write_text("fresh", encoding="utf-8")
    second = store.commit(second_write, metadata={"cache_reusable": True}, make_active=True)

    assert second.artifact_id != first.artifact_id
    assert (second.path / "result.txt").read_text(encoding="utf-8") == "fresh"
    assert store.manifest(second).metadata["cache_reusable"] is True
    quarantined = list((store.root / ".corrupt" / recipe.stage).iterdir())
    assert len(quarantined) == 1
    assert (quarantined[0] / "result.txt").read_text(encoding="utf-8") == "fallback"


def test_unreadable_active_index_is_not_silently_replaced(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    ref = _commit(store, recipe)
    store.mark_active("one", ref)
    active_path = store.root / ".state" / "active.json"
    active_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="active artifact index is unreadable"):
        store.mark_active("two", ref)
    assert active_path.read_text(encoding="utf-8") == "not-json"
