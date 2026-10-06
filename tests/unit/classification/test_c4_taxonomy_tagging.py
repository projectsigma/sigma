from __future__ import annotations

import pandas as pd
import pytest

from sigma import Economy, PsicTaxonomy, TaggingReferences
from sigma.classification import EconomicTagger, PsicClassifier
from sigma.classification.crosswalk import CrosswalkIndex
from sigma.classification.reference import PsicNode, load_builtin_io_reference
from sigma.economy import Sector, SectorCatalog
from sigma.errors import TaxonomyValidationError


def custom_taxonomy() -> PsicTaxonomy:
    frame = pd.DataFrame([
        {"scheme":"custom-activity","version":"2026","code":"A","level":"section","title":"Alpha","parent_code":""},
        {"scheme":"custom-activity","version":"2026","code":"A1","level":"division","title":"Alpha One","parent_code":"A"},
    ])
    return PsicTaxonomy.from_frame(frame)


def custom_economy() -> Economy:
    sectors=SectorCatalog([Sector("E1","Economy One"),Sector("E2","Economy Two")])
    z=pd.DataFrame([[1.0,0.0],[0.5,2.0]],index=["E1","E2"],columns=["E1","E2"])
    x=pd.Series([5.0,6.0],index=["E1","E2"])
    return Economy(economy_id="custom-economy",sectors=sectors,raw_transactions=z,total_output=x)


def test_custom_taxonomy_scheme_and_version_are_allowed():
    taxonomy=custom_taxonomy()
    assert taxonomy.scheme == "custom-activity"
    assert taxonomy.version == "2026"
    assert taxonomy.origin == "custom"
    assert taxonomy.asset_sha256 is None
    assert taxonomy.children("A") == ["A1"]


def test_mixed_taxonomy_identity_is_rejected():
    with pytest.raises(ValueError, match="one nonblank taxonomy scheme/version"):
        PsicTaxonomy([
            PsicNode("A","section","A",scheme="x",version="1"),
            PsicNode("B","section","B",scheme="x",version="2"),
        ])


def test_custom_classifier_does_not_implicitly_load_rev5_crosswalk():
    taxonomy=custom_taxonomy()
    classifier=PsicClassifier(taxonomy=taxonomy, min_score=1.1, min_margin=1.1)
    assert classifier.crosswalk.entries == []


def test_builtin_references_reject_custom_taxonomy_before_mapping_load():
    with pytest.raises(TaxonomyValidationError, match="exact bundled Rev. 5 taxonomy"):
        TaggingReferences.builtin(custom_taxonomy(), Economy.default())


def test_custom_reference_validation_binds_both_taxonomy_and_economy():
    taxonomy=custom_taxonomy(); economy=custom_economy()
    refs=TaggingReferences.custom(taxonomy=taxonomy,economy=economy,source_to_psic=CrosswalkIndex([]),psic_to_economy={"A1":"E2"})
    refs.validate_for(taxonomy,economy)
    with pytest.raises(TaxonomyValidationError,match="unknown taxonomy codes"):
        TaggingReferences.custom(taxonomy=taxonomy,economy=economy,psic_to_economy={"ZZ":"E2"})
    with pytest.raises(TaxonomyValidationError,match="unknown Economy sectors"):
        TaggingReferences.custom(taxonomy=taxonomy,economy=economy,psic_to_economy={"A1":"ZZ"})


def test_custom_economic_tagger_adds_canonical_fields_only_from_explicit_mapping():
    taxonomy=custom_taxonomy(); economy=custom_economy()
    refs=TaggingReferences.custom(taxonomy=taxonomy,economy=economy,psic_to_economy={"A1":"E2"})
    tagger=EconomicTagger(taxonomy=taxonomy,economy=economy,references=refs)
    out=tagger.tag(pd.DataFrame([{"psic_code":"A1"},{"psic_code":""}]))
    assert out.loc[0,"economy_code"] == "E2"
    assert out.loc[0,"economy_label"] == "Economy Two"
    assert out.loc[0,"economy_status"] == "PSIC_MAP"
    assert out.loc[0,"economy_source"] == "psic"
    assert out.loc[1,"economy_code"] == ""
    assert out.loc[1,"economy_status"] == "UNRESOLVED"


def test_reference_fingerprint_mismatch_fails_closed():
    taxonomy=custom_taxonomy(); economy=custom_economy()
    refs=TaggingReferences.custom(taxonomy=taxonomy,economy=economy,psic_to_economy={"A1":"E2"})
    other=PsicTaxonomy.from_frame(pd.DataFrame([
        {"scheme":"custom-activity","version":"2026","code":"B","level":"section","title":"Beta","parent_code":""},
    ]))
    with pytest.raises(TaxonomyValidationError,match="taxonomy fingerprint"):
        refs.validate_for(other,economy)


def test_builtin_io_reference_codes_fit_builtin_economy_sector_universes():
    ref=load_builtin_io_reference()
    for resolution in ("io16","io80"):
        economy=Economy.builtin(resolution)
        known=set(economy.sectors.codes)
        referenced=set()
        for row in ref.concordance:
            referenced.update(getattr(row,f"{resolution}_codes"))
        assert referenced <= known


def test_custom_taxonomy_directory_csv_roundtrip(tmp_path):
    frame=pd.DataFrame([
        {"scheme":"activity-x","version":"1","code":"A","level":"section","title":"Alpha","parent_code":""},
        {"scheme":"activity-x","version":"1","code":"01","level":"division","title":"One","parent_code":"A"},
    ])
    frame.to_csv(tmp_path/"nodes.csv",index=False)
    taxonomy=PsicTaxonomy.from_directory(tmp_path)
    assert taxonomy.scheme == "activity-x"
    assert taxonomy.version == "1"
    assert taxonomy.origin.startswith("directory:")
    assert taxonomy.get("01").parent_code == "A"


def test_packaged_classification_manifest_hashes_all_assets():
    import hashlib, json
    from importlib import resources
    root=resources.files("sigma.resources.classification")
    payload=json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["assets"]) == 7
    from sigma.classification.reference import _canonical_manifest_bytes
    for rel,spec in payload["assets"].items():
        raw=root.joinpath(*rel.split("/")).read_bytes()
        canonical=_canonical_manifest_bytes(rel, raw)
        assert len(canonical) == int(spec["size_bytes"])
        assert hashlib.sha256(canonical).hexdigest() == spec["sha256"]


def test_classification_manifest_canonicalizes_windows_csv_line_endings():
    from sigma.classification.reference import _canonical_manifest_bytes
    raw = b"a,b\r\n1,2\r\n"
    assert _canonical_manifest_bytes("crosswalks/example.csv", raw) == b"a,b\n1,2\n"
    assert _canonical_manifest_bytes("manifest.json", raw) == raw


def _synthetic_builtin_taxonomy_for_io_bridge() -> PsicTaxonomy:
    import hashlib
    from importlib import resources
    from sigma.classification.reference import load_builtin_io_reference
    ref=load_builtin_io_reference()
    nodes = [PsicNode(row.rev5_code,row.rev5_level,row.rev5_title) for row in ref.bridge]
    known = {node.code for node in nodes}
    level_for_length = {1: "section", 2: "division", 3: "group", 4: "class", 5: "subclass"}
    for rule in CrosswalkIndex.load_builtin().entries:
        for code in rule.codes:
            if code in known:
                continue
            nodes.append(PsicNode(code, level_for_length[len(code)], f"Synthetic {code}"))
            known.add(code)
    taxonomy=PsicTaxonomy(nodes)
    taxonomy.origin="builtin:psic_rev5"
    raw=resources.files("sigma.resources.classification").joinpath("psic_rev5","nodes.parquet").read_bytes()
    taxonomy.asset_sha256=hashlib.sha256(raw).hexdigest()
    return taxonomy


def test_builtin_economic_tagger_preserves_legacy_columns_and_adds_canonical_io80():
    from sigma.classification.hybrid_io import apply_hybrid_io
    from sigma.classification.io_mapping import IOMapping, enrich_frame_with_io
    taxonomy=_synthetic_builtin_taxonomy_for_io_bridge()
    economy=Economy.default()
    mapping=IOMapping.load_builtin(taxonomy)
    chosen=None
    for row in mapping.reference.bridge:
        result=mapping.map_psic(row.rev5_code)
        if result.get("io80_map_code"):
            chosen=row.rev5_code
            break
    assert chosen is not None
    frame=pd.DataFrame([{"psic_code":chosen,"psic_status":"SINGLE","psic_flags":"","name":"","category":""}])
    legacy=apply_hybrid_io(enrich_frame_with_io(frame,taxonomy=taxonomy,mapping=mapping))
    refs=TaggingReferences.builtin(taxonomy,economy)
    tagged=EconomicTagger(taxonomy=taxonomy,economy=economy,references=refs).tag(frame)
    for column in legacy.columns:
        pd.testing.assert_series_equal(tagged[column],legacy[column],check_names=True)
    assert tagged.loc[0,"economy_code"] == tagged.loc[0,"io80_code"]
    assert tagged.loc[0,"economy_label"] == economy.sectors.label_for(tagged.loc[0,"economy_code"])
    assert tagged.loc[0,"economy_status"] == tagged.loc[0,"io80_status"]
    assert tagged.loc[0,"economy_source"] == tagged.loc[0,"io80_source"]


def test_builtin_economic_tagger_keeps_its_output_schema_for_zero_rows():
    taxonomy = _synthetic_builtin_taxonomy_for_io_bridge()
    economy = Economy.default()
    refs = TaggingReferences.builtin(taxonomy, economy)
    frame = pd.DataFrame(columns=["psic_code", "psic_status", "psic_flags", "name", "category"])
    out = EconomicTagger(taxonomy=taxonomy, economy=economy, references=refs).tag(frame)
    assert out.empty
    for column in (
        "io_mapping_status",
        "direct_io_status",
        "io16_code",
        "io80_code",
        "io80_status",
        "io240_code",
        "economy_code",
        "economy_label",
        "economy_status",
        "economy_source",
    ):
        assert column in out.columns
