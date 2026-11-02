"""Isolated regression tests for opt-in shadow classifier; no SIGMA workspace access."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from sigma.classification.shadow import (
    ShadowResolver, compress_tree, domain_of, entity_gate, explicit_evidence, load_registry_links,
)


@dataclass
class Node:
    title: str


class FakeTaxonomy:
    def __init__(self):
        self.nodes = {
            "861": Node("Hospital activities"),
            "8611": Node("Public hospital activities"),
            "86111": Node("Public general hospital activities"),
            "86112": Node("Public specialized hospital activities"),
            "8612": Node("Private hospital activities"),
            "86121": Node("Private general hospital activities"),
            "852": Node("Primary education"),
            "85201": Node("Public elementary education"),
            "85202": Node("Private elementary education"),
            "85203": Node("Public special elementary education"),
            "85204": Node("Private special elementary education"),
            "85205": Node("Primary education n.e.c., ownership unspecified"),
            "85": Node("Education"),
            "8590": Node("Other education activities"),
        }
        self._children = {
            "861": ["8611", "8612"], "8611": ["86111", "86112"], "8612": ["86121"],
            "852": ["85201", "85202", "85203", "85204", "85205"],
            "85": ["852", "8590"],
        }

    def get(self, code):
        return self.nodes[code]

    def children(self, code):
        return self._children.get(code, [])

    def leaves(self, code):
        if code not in self._children:
            return frozenset([code])
        return frozenset.union(*(self.leaves(c) for c in self.children(code)))


class FakeMapping:
    def __init__(self, bad=False):
        self.bad = bad

    def map_psic(self, code):
        if code == "8611":
            return {"io80_codes": "76", "io240_codes": "231" if not self.bad else "232"}
        if code == "8612":
            return {"io80_codes": "77", "io240_codes": "232"}
        if code in ("85201", "85203"):
            return {"io80_codes": "74", "io240_codes": "229"}
        if code in ("85202", "85204"):
            return {"io80_codes": "75", "io240_codes": "230"}
        return {"io80_codes": "74;75", "io240_codes": "229;230"}


def row(domain="health", **overrides):
    data = {
        "canonical_id": "ss_test123", "name": "Lung Center of the Philippines",
        "osm_name": "Lung Center of the Philippines", "overture_name": "",
        "osm_category": "amenity=hospital | healthcare=hospital",
        "overture_category": "hospital", "psic_status": "SINGLE",
        "psic_code": "861", "io80_codes": "76; 77", "io240_codes": "231; 232",
        "io80_code": "", "io240_code": "", "ownership_side": "", "economy_code": "",
    }
    if domain == "education":
        data.update(name="Public Elementary School", psic_code="852", osm_category="amenity=school",
                    overture_category="elementary_school", io80_codes="74; 75", io240_codes="229; 230")
    data.update(overrides)
    return data


def resolver(**kw):
    return ShadowResolver(FakeTaxonomy(), FakeMapping(), **kw)


def test_no_name_guess_public_hospital():
    result = resolver().resolve(row())
    assert result["shadow_status"] == "NO_OWNERSHIP_EVIDENCE"
    assert result["shadow_side"] == ""


def test_public_operator_refines_hospital_to_8611():
    result = resolver().resolve(row(osm_category="amenity=hospital | operator=Department of Health"))
    assert result["shadow_side"] == "public"
    assert result["shadow_basis"] == "government_operator_proxy"
    assert result["shadow_psic_candidates"] == "8611"
    assert result["shadow_psic_single"] == "8611"
    assert (result["shadow_io80"], result["shadow_io240"]) == ("76", "231")
    assert result["shadow_status"] == "PROPOSED_IO"


def test_private_explicit_refines_8612():
    result = resolver().resolve(row(osm_category="amenity=hospital | ownership=private"))
    assert result["shadow_side"] == "private"
    assert result["shadow_psic_candidates"] == "8612"
    assert result["shadow_io80"] == "77"


def test_religious_name_not_private_and_school_operator():
    result = resolver().resolve(row("education", name="Holy Spirit Elementary School",
        osm_category="amenity=school | operator=School District VII, City Schools Division - Quezon City",
        io80_code="75", ownership_side="private"))
    assert result["shadow_side"] == "public"
    assert result["shadow_psic_single"] == ""  # No unsupported subclass proposal
    assert result["shadow_psic_candidates"] == ""  # Coarse PSIC retained
    assert result["shadow_refinement_status"] == "MAPPED_IO_ONLY_PSIC_COARSE"
    assert result["shadow_io80"] == "74"
    assert result["shadow_baseline_conflict"] == "baseline_private_vs_public"


def test_no_government_inference_from_hospital_name():
    result = resolver().resolve(row(name="National Children’s Hospital", osm_category="amenity=hospital"))
    assert result["shadow_side"] == ""


def test_subunits_and_transport_gate_before_ownership():
    a = resolver().resolve(row(name="6Th Floor East Avenue Medical Center", osm_category="amenity=hospital | operator=DOH"))
    b = resolver().resolve(row(name="Lung Center", osm_category="public_transport=platform | operator=DOH"))
    assert a["shadow_status"] == "ENTITY_REVIEW"
    assert b["shadow_status"] == "BLOCKED_UPSTREAM"
    assert not a["shadow_side"] and not b["shadow_side"]


def test_conflict_is_not_forced():
    result = resolver().resolve(row(osm_category="amenity=hospital | ownership=private | ownership=public"))
    assert result["shadow_status"] == "EXPLICIT_OR_REGISTRY_CONFLICT"
    assert result["shadow_side"] == ""


def test_operator_is_not_private_ownership():
    result = resolver().resolve(row(osm_category="amenity=hospital | ownership=private | operator=Department of Health"))
    assert result["shadow_status"] == "OPERATOR_VS_PRIVATE_CONFLICT"
    assert result["shadow_side"] == ""


def test_psic_upstream_activity_gate():
    result = resolver().resolve(row("education", name="UERM Memorial Medical Center", psic_code="85",
                                    osm_category="amenity=hospital", overture_category="hospital"))
    assert result["shadow_entity_reason"] == "hospital_activity_conflicts_with_education_psic"


def test_broad_psic_education_can_only_propose_io_without_psic_subclass():
    result = resolver().resolve(row("education", psic_code="85", osm_category="amenity=school | ownership=public"))
    assert result["shadow_status"] == "PROPOSED_IO"
    assert result["shadow_refinement_status"] == "MAPPED_IO_ONLY_PSIC_COARSE"
    assert result["shadow_psic_single"] == result["shadow_psic_candidates"] == ""
    assert result["shadow_io80"] == "74"


def test_io_mapping_mismatch_abstains():
    result = ShadowResolver(FakeTaxonomy(), FakeMapping(bad=True)).resolve(
        row(osm_category="amenity=hospital | ownership=public")
    )
    assert result["shadow_status"] == "OWNERSHIP_ONLY_IO_ABSTAIN"
    assert result["shadow_refinement_status"] == "PSIC_IO_MAPPING_UNPROVEN"
    assert result["shadow_io240"] == ""


def test_reject_unverified_or_benchmark_roster():
    with pytest.raises(ValueError):
        load_registry_links({"institutions": []})
    with pytest.raises(ValueError):
        load_registry_links({"schema": "sigma-verified-canonical-links-v1", "links": [
            {"canonical_id": "ss_test123", "domain": "health", "ownership": "public", "verified": False,
             "source_url": "https://hospital.example", "registry_id": "X", "verified_as_of": "2026-01-01"}
        ]})


def test_verified_id_link_not_alias_driven():
    registry = load_registry_links({"schema": "sigma-verified-canonical-links-v1", "links": [
        {"canonical_id": "ss_test123", "domain": "health", "ownership": "public", "verified": True,
         "source_url": "https://hospital.example", "registry_id": "X", "verified_as_of": "2026-01-01"}
    ]})
    good = resolver(registry_links=registry).resolve(row())
    bad = resolver(registry_links=registry).resolve(row(canonical_id="ss_other", name="Lung Center of the Philippines"))
    assert good["shadow_status"] == "PROPOSED_IO"
    assert bad["shadow_status"] == "NO_OWNERSHIP_EVIDENCE"


def test_frame_additive_and_refuses_existing_shadow_columns():
    input_frame = pd.DataFrame([row(), row(osm_category="amenity=hospital | ownership=private")])
    original = input_frame.copy(deep=True)
    output = resolver().resolve_frame(input_frame)
    pd.testing.assert_frame_equal(input_frame, original)
    for column in input_frame.columns:
        assert output[column].equals(input_frame[column])
    with pytest.raises(ValueError):
        resolver().resolve_frame(output)


def test_domain_pair_required():
    assert domain_of(row()) == "health"
    assert domain_of(row(io80_codes="75", io240_codes="")) == ""
    assert explicit_evidence(row("education", overture_category="private_school"), "education") == [("private", "overture:private_school")]


def test_builtin_psic_io_refinement_contract():
    """Real built-in reference smoke test when running from the SIGMA checkout."""
    pytest.importorskip("pyarrow")
    reference = pytest.importorskip("sigma.classification.reference")
    io_module = pytest.importorskip("sigma.classification.io_mapping")
    taxonomy = reference.load_builtin_psic_taxonomy()
    mapping = io_module.IOMapping.load_builtin(taxonomy)
    examples = (
        ("861", "health", "public", "hospital", "76", "231"),
        ("861", "health", "private", "hospital", "77", "232"),
        ("852", "education", "public", "school", "74", "229"),
        ("852", "education", "private", "school", "75", "230"),
    )
    for psic, domain, side, category, io80, io240 in examples:
        entry = row(domain, psic_code=psic, osm_category=f"amenity={category} | ownership={side}")
        proposed = ShadowResolver(taxonomy, mapping).resolve(entry)
        assert proposed["shadow_status"] == "PROPOSED_IO", (psic, side, proposed)
        assert proposed["shadow_io80"] == io80
        assert proposed["shadow_io240"] == io240
        if proposed["shadow_refinement_status"] == "MAPPED_IO_ONLY_PSIC_COARSE":
            assert proposed["shadow_psic_single"] == ""
            assert proposed["shadow_psic_candidates"] == ""
        else:
            assert proposed["shadow_refinement_status"] == "MAPPED_FROM_PSIC"


def test_standalone_clinic_is_not_automatically_a_subunit():
    sample = row(name="Community Clinic", osm_category="healthcare=clinic | ownership=private")
    role, reason = entity_gate(sample, "health")
    assert role == "main_candidate", reason


def test_io_only_fallback_keeps_unknown_psic_leaves_and_does_not_fabricate_subclass():
    value = resolver().resolve(row("education", osm_category="amenity=school | ownership=private"))
    assert value["shadow_status"] == "PROPOSED_IO"
    assert value["shadow_refinement_status"] == "MAPPED_IO_ONLY_PSIC_COARSE"
    assert value["shadow_psic_candidates"] == value["shadow_psic_single"] == ""
    assert value["shadow_io80"] == "75" and value["shadow_io240"] == "230"


def test_io_only_fallback_requires_both_original_candidate_pairs():
    value = resolver().resolve(row("education", io240_codes="229", osm_category="amenity=school | ownership=public"))
    assert value["shadow_status"] == "OWNERSHIP_ONLY_IO_ABSTAIN"
    assert value["shadow_refinement_status"] == "ROW_IO_PAIR_INCOMPLETE"
    assert value["shadow_io80"] == value["shadow_io240"] == ""


def test_io_only_fallback_requires_mapping_to_exact_pair():
    class WrongParentMap(FakeMapping):
        def map_psic(self, code):
            if code == "852":
                return {"io80_codes": "74;75;76", "io240_codes": "229;230;231"}
            return super().map_psic(code)
    value = ShadowResolver(FakeTaxonomy(), WrongParentMap()).resolve(
        row("education", osm_category="amenity=school | ownership=public")
    )
    assert value["shadow_status"] == "OWNERSHIP_ONLY_IO_ABSTAIN"
    assert value["shadow_refinement_status"] == "PARENT_PSIC_IO_PAIR_MISMATCH"


def test_hospital_proposal_still_uses_taxonomy_class():
    value = resolver().resolve(row(osm_category="amenity=hospital | ownership=private"))
    assert value["shadow_refinement_status"] == "MAPPED_FROM_PSIC"
    assert value["shadow_psic_single"] == "8612"
    assert value["shadow_io80"] == "77"

# v3 external registry tests. Built-in QC source snapshots contain official names
# and publishable codes/sequence indices; no evaluation benchmark labels.
from pathlib import Path
from sigma.classification.registry import (
    Institution, RegistryIndex, records_from_csv, key as registry_key, import_export,
)


def _registry_record(name, side="public", source="deped_public", code="136544", domain="education"):
    return Institution(source, code, name, domain, side, "Quezon City", "", (),
                       "https://www.depedncr.com.ph/directory-of-public-schools/",
                       "2026-11-01", "official_code", "official_public_directory")


def test_v3_exact_public_school_reference_can_override_weak_private_name_signal():
    registry = RegistryIndex([_registry_record("Holy Spirit ES")])
    result = resolver(registry_index=registry).resolve(row("education", name="Holy Spirit Elementary School",
        osm_name="Holy Spirit Elementary School", osm_category="amenity=school", ownership_side="private", io80_code="75"))
    assert result["shadow_status"] == "PROPOSED_IO"
    assert result["shadow_side"] == "public"
    assert result["shadow_basis"] == "official_registry_name_city_provisional"
    assert result["shadow_baseline_conflict"] == "baseline_private_vs_public"
    assert result["shadow_registry_ids"] == "deped_public:136544"
    assert result["shadow_psic_single"] == ""


def test_v3_exact_match_never_borrows_neighboring_school_name():
    registry = RegistryIndex([_registry_record("Fairview ES", code="136543"),
                              _registry_record("North Fairview ES", code="136537"),
                              _registry_record("West Fairview Elementary School", code="222501")])
    for name, ident in (("Fairview Elementary School", "136543"),
                        ("North Fairview Elementary School", "136537"),
                        ("West Fairview Elementary School", "222501")):
        m = registry.match(row("education", name=name, osm_name=name), "education")
        assert m.status == "EXACT_NAME_CITY" and m.source_ids == f"deped_public:{ident}"
    assert registry.match(row("education", name="Fairview School", osm_name="Fairview School"), "education").status == "NO_MATCH"


def test_v3_registered_private_hospital_is_not_inferred_for_its_tenant():
    hospital = Institution("philhealth_hospitals", "533", "Providence Hospital, Inc.", "health",
                           "private", "Quezon City", "", (),
                           "https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_053125.pdf",
                           "2025-05-31", "publication_row", "explicit_sector")
    ix = RegistryIndex([hospital])
    assert ix.match(row(name="Tec Orthopedics @ Providence Hospital", osm_name=""), "health").status == "NO_MATCH"
    v = resolver(registry_index=ix).resolve(row(name="Tec Orthopedics @ Providence Hospital", osm_name=""))
    assert v["shadow_side"] == "" and v["shadow_status"] == "ENTITY_REVIEW"


def test_v3_registry_ownership_conflict_is_review_not_assignment():
    a = _registry_record("Test College", side="public", code="100")
    b = _registry_record("Test College", side="private", code="200")
    m = RegistryIndex([a, b]).match(row("education", name="Test College", osm_name=""), "education")
    assert m.status == "OWNERSHIP_CONFLICT"
    v = resolver(registry_index=RegistryIndex([a, b])).resolve(row("education", name="Test College", osm_name=""))
    assert v["shadow_status"] == "REGISTRY_MATCH_REVIEW" and v["shadow_side"] == ""


def test_v3_wrong_city_rejected():
    reg = RegistryIndex([_registry_record("Holy Spirit ES")])
    assert reg.match(row("education", name="Holy Spirit Elementary School", osm_name="", city="Makati City"), "education").status == "CITY_CONFLICT"


def test_v3_exact_external_school_id_checks_name_agreement():
    reg = RegistryIndex([_registry_record("Holy Spirit ES")])
    ok = reg.match(row("education", name="Holy Spirit Elementary School", osm_name="", deped_school_id="136544"), "education")
    assert ok.status == "EXACT_EXTERNAL_ID"
    wrong = reg.match(row("education", name="Holy Spirit School", osm_name="", deped_school_id="136544"), "education")
    assert wrong.status == "EXTERNAL_ID_NAME_CONFLICT"


def test_v3_seed_has_both_health_sides_and_both_school_sides():
    sample = Path(__file__).resolve().parents[3] / "scripts" / "registry_qc_official_sources.csv"
    rows = records_from_csv(sample)
    groups = {(r.domain, r.ownership) for r in rows}
    assert groups == {("health", "public"), ("health", "private"), ("education", "public"), ("education", "private")}
    assert len(rows) >= 70
    assert any(r.name == "Holy Spirit ES" and r.source_id == "136544" for r in rows)
    assert any(r.name == "St. Luke's Medical Center" and r.ownership == "private" for r in rows)


def test_v3_rejects_fake_registry_source(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("source,source_id,name,domain,ownership,city,address,aliases,source_url,as_of,id_kind,evidence_type\n"
                 "deped_public,9,Bad School,education,public,Quezon City,,,https://evil.example/a,2026,official_code,official_public_directory\n")
    with pytest.raises(ValueError):
        records_from_csv(f)


def test_v3_nhfr_export_requires_explicit_ownership_and_hospital_type(tmp_path):
    f = tmp_path / "doh.csv"
    f.write_text("Health Facility Code,Health Facility Name,Ownership Major Classification,Health Facility Type,City/Municipality\n"
                 "A1,QC Sample Hospital,Government,Hospital,Quezon City\n"
                 "A2,QC Private Hospital,Private,Hospital,Quezon City\n"
                 "A3,QC Laboratory,Private,Laboratory,Quezon City\n"
                 "A4,QC Unknown Hospital,Unknown,Hospital,Quezon City\n"
                 "A5,Other City Hospital,Government,Hospital,Makati City\n")
    r = import_export(f, "doh_nhfr", as_of="2026-11-01", source_url="https://nhfr.doh.gov.ph/VActivefacilitiesList")
    assert {(x.source_id, x.ownership) for x in r} == {("A1", "public"), ("A2", "private")}


def test_v3_ched_unknown_institution_type_not_guessed(tmp_path):
    f = tmp_path / "ched.csv"
    f.write_text("HEI Code,HEI Name,Type,Address\n"
                 "101,Some Private College,Private Non-Sectarian Stock,Street Quezon City\n"
                 "102,Some SUC,SUC Main,Quezon City\n"
                 "103,Not Verifiable,Others please specify,Quezon City\n")
    r = import_export(f, "ched_hei", as_of="2026-11-01", source_url="https://heida.ched.gov.ph/hei-directory/13")
    assert {(x.source_id, x.ownership) for x in r} == {("101", "private"), ("102", "public")}


def test_v3_deped_import_requires_explicit_sector(tmp_path):
    f = tmp_path / "deped.csv"
    f.write_text("School ID,School Name,Sector,Division\n"
                 "30001,Public ES,Public,Quezon City\n"
                 "40001,Private ES,Private,Quezon City\n"
                 "50001,Unknown School,,Quezon City\n")
    r = import_export(f, "deped_masterlist", as_of="2026-11-01", source_url="https://www.deped.gov.ph/")
    assert {(x.source_id, x.ownership) for x in r} == {("30001", "public"), ("40001", "private")}


def test_v3_registry_incorrect_upstream_psic_cannot_override_classification():
    hospital = Institution("philhealth_hospitals", "553", "World Citi Medical Center", "health", "private",
                           "Quezon City", "", (),
                           "https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_053125.pdf",
                           "2025-05-31", "publication_row", "explicit_sector")
    v = resolver(registry_index=RegistryIndex([hospital])).resolve(row(name="World Citi Medical Center",osm_name="World Citi Medical Center",psic_status="CANDIDATES_ONLY"))
    assert v["shadow_status"] == "BLOCKED_UPSTREAM"
    assert v["shadow_registry_ownership"] == "private"
    assert v["shadow_side"] == ""


def test_v3_canonical_name_disagreement_does_not_transfer_owner():
    reg = RegistryIndex([_registry_record("Holy Spirit ES")])
    sample = row("education", name="Holy Spirit Church School Shop",
                 osm_name="Holy Spirit Elementary School", overture_name="",
                 osm_category="amenity=school")
    m = reg.match(sample, "education")
    assert m.status == "CANONICAL_NAME_CONFLICT"
    result = resolver(registry_index=reg).resolve(sample)
    assert result["shadow_status"] == "REGISTRY_MATCH_REVIEW"
    assert result["shadow_side"] == ""


def test_v3_a_subunit_hidden_in_secondary_source_name_is_reviewed():
    sample = row(name="East Avenue Medical Center", osm_name="6th Floor East Avenue Medical Center",
                 overture_name="East Avenue Medical Center")
    v = resolver().resolve(sample)
    assert v["shadow_status"] == "ENTITY_REVIEW"
    assert v["shadow_entity_reason"] == "possible_subunit_in_source_name"


def test_v3_ched_public_web_table_combined_name_and_code(tmp_path):
    f = tmp_path / "hei.csv"
    f.write_text('HEI Name & Code,Type,Address\n'
                 '"ABE International College of Business and Accountancy Inc. - Cubao 13308",Private Non-Sectarian Non-Stock,Quezon City\n'
                 '"Unnamed College 99999",Others please specify,Quezon City\n')
    r = import_export(f, "ched_hei", as_of="2026-11-01", source_url="https://heida.ched.gov.ph/hei-directory/13")
    assert [(x.source_id, x.name, x.ownership) for x in r] == [
        ("13308", "ABE International College of Business and Accountancy Inc. - Cubao", "private")]
