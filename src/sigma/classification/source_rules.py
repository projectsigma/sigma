from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from importlib import resources

from .normalize import clean_literal, normalize_key
from .reference import PsicTaxonomy
from .retrieval import PsicRetriever
from .types import MappingKind, MappingRule

OVERTURE_NON_ACTIVITY = frozenset(
    ["beach", "bridge", "historic_site", "landmark", "monument", "park", "road"]
)

OSM_NON_ACTIVITY_PREFIXES = ('boundary=', 'highway=', 'natural=', 'waterway=')


OSM_AUXILIARY_ACTIVITY_KEYS = frozenset({
    "brand",
    "cuisine",
    "delivery",
    "drive_through",
    "internet_access",
    "opening_hours",
    "operator",
    "outdoor_seating",
    "takeaway",
    "wheelchair",
})

OSM_AUXILIARY_ACTIVITY_PREFIXES = ("contact:", "payment:")


def _load_osm_coherent_compounds() -> frozenset[frozenset[tuple[str, str]]]:
    target = resources.files("sigma.resources.classification").joinpath(
        "crosswalks", "osm_compound_compatibility.csv"
    )
    raw = target.read_bytes().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"left_tag", "right_tag"}
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise ValueError(
            f"OSM compound compatibility table is missing columns {sorted(missing)}"
        )
    pairs: set[frozenset[tuple[str, str]]] = set()
    for row in reader:
        components: list[tuple[str, str]] = []
        for field in ("left_tag", "right_tag"):
            raw_tag = str(row.get(field) or "").strip().casefold()
            if "=" not in raw_tag:
                raise ValueError(f"invalid OSM compatibility tag {raw_tag!r}")
            key, value = raw_tag.split("=", 1)
            components.append((key.strip(), value.strip()))
        pair = frozenset(components)
        if len(pair) != 2:
            raise ValueError(f"invalid OSM compatibility pair {components!r}")
        pairs.add(pair)
    return frozenset(pairs)


OSM_COHERENT_COMPOUNDS = _load_osm_coherent_compounds()


def _osm_auxiliary_key(key: str) -> bool:
    folded = str(key).strip().casefold()
    return folded in OSM_AUXILIARY_ACTIVITY_KEYS or folded.startswith(
        OSM_AUXILIARY_ACTIVITY_PREFIXES
    )

OSM_NON_ACTIVITY_EXACT = frozenset(['leisure=park',
 'leisure=pitch',
 'man_made=bridge',
 'man_made=mast',
 'man_made=street_cabinet',
 'man_made=surveillance',
 'man_made=tower',
 'public_transport=platform',
 'public_transport=stop_position',
 'tourism=artwork'])

OVERTURE_UNCODEABLE = frozenset(['arts_and_entertainment',
 'basketball_court',
 'campus_building',
 'community_and_government',
 'community_center',
 'corporate_or_business_office',
 'shopping_mall',
 'social_or_community_service',
 'sports_and_recreation',
 'swimming_pool',
 'travel_and_transportation'])

OSM_UNCODEABLE_EXACT = frozenset(['amenity=atm',
 'amenity=bus_station | public_transport=station',
 'amenity=community_centre',
 'amenity=marketplace',
 'amenity=parking',
 'amenity=parking_entrance',
 'amenity=recycling',
 'amenity=taxi',
 'industrial=depot',
 'leisure=playground',
 'leisure=sports_hall',
 'man_made=works',
 'office=company',
 'office=ngo',
 'office=yes',
 'public_transport=station',
 'shop=mall',
 'tourism=attraction'])

OVERTURE_COHERENT_COMPOUNDS = frozenset(['attorney_or_law_firm',
 'bank_or_credit_union',
 'bar_and_grill_restaurant',
 'building_or_construction_service',
 'flowers_and_gifts_store',
 'food_and_drink',
 'freight_and_cargo_service',
 'social_or_community_service',
 'tattoo_and_piercing'])

OVERTURE_RULES = {
 'accountant': ('accounting bookkeeping auditing and tax consultancy activities', ('692',)),
 'advertising_agency': ('advertising activities', ('731',)),
 'animal_or_pet_service': ('pet care services', ('96902',)),
 'attorney_or_law_firm': ('legal activities', ('691',)),
 'auto_dealer': ('retail sale of motor vehicles', ('4781',)),
 'auto_detailing': ('motor vehicle and motorcycle washing and detailing', ('9534',)),
 'auto_parts_store': ('retail sale motor vehicle parts accessories', ('4782',)),
 'automotive_repair': ('repair and maintenance of motor vehicles', ('953',)),
 'b2b_advertising_and_marketing_service': ('advertising activities', ('731',)),
 'bakery': ('bakery products manufacture retail sale', ('1071', '47214')),
 'bank': ('banking activities', ('64',)),
 'bank_or_credit_union': ('banking and credit cooperative activities', ('64',)),
 'bar': ('beverage serving activities', ('563',)),
 'barbecue_restaurant': ('restaurants and mobile food service activities', ('561',)),
 'barber': ('hairdressing and barber activities', ('962',)),
 'beauty_salon': ('hairdressing and beauty treatment activities', ('962',)),
 'beauty_supply_store': ('retail sale beauty and personal care goods', ('47',)),
 'bike_store': ('retail trade activities', ('47',)),
 'bookstore': ('retail sale books newspapers stationery and school supplies', ('4761',)),
 'bottled_water_company': ('bottled water manufacturing wholesale or retail activities',
                           ('11', '46', '47')),
 'bubble_tea_shop': ('beverage serving activities', ('563',)),
 'building_or_construction_service': ('construction activities', ('F',)),
 'cafe': ('operation of cafes or coffee shops', ('563',)),
 'car_rental_service': ('rental and leasing of motor vehicles', ('771',)),
 'car_wash': ('motor vehicle and motorcycle washing and detailing activities', ('9534',)),
 'caterer': ('event catering activities', ('5621',)),
 'christian_place_of_worship': ('activities of religious organizations', ('9491',)),
 'clothing_store': ('retail sale garments clothing apparel', ('4771',)),
 'coffee_shop': ('operation of cafes or coffee shops', ('563',)),
 'college_university': ('tertiary education', ('854',)),
 'computer_store': ('retail sale computers and peripheral equipment', ('474',)),
 'contractor': ('construction activities', ('F',)),
 'convenience_store': ('retail selling in convenience stores', ('4711',)),
 'cupcake_shop': ('bakery manufacture retail or food service activities', ('10', '47', '56')),
 'dental_clinic': ('medical and dental practice activities', ('862',)),
 'dessert_shop': ('dessert retail or food service activities', ('47', '56')),
 'doctors_office': ('medical and dental practice activities', ('862',)),
 'driving_school': ('driving school activities', ('8553',)),
 'dry_cleaning': ('washing and cleaning of textile and fur products', ('961',)),
 'education': ('education activities', ('85',)),
 'electronics_store': ('retail sale of information communication equipment consumer electronics',
                       ('474',)),
 'elementary_school': ('primary education', ('852',)),
 'employment_agency': ('employment activities', ('78',)),
 'event_photography_service': ('photographic activities', ('742',)),
 'eyewear_store': ('retail sale eyewear and related supplies', ('47736',)),
 'family_practice': ('medical and dental practice activities', ('862',)),
 'fast_food_restaurant': ('fast-food restaurant operations', ('561',)),
 'filipino_restaurant': ('restaurants and mobile food service activities', ('561',)),
 'financial_service': ('financial and insurance activities', ('L',)),
 'flowers_and_gifts_store': ('retail sale flowers gifts and novelty goods', ('47',)),
 'food_and_drink': ('food and beverage service activities', ('56',)),
 'food_beverage_distributor': ('wholesale and retail trade activities', ('G',)),
 'food_delivery_service': ('food delivery food service courier activities', ('56', '532')),
 'food_truck_stand': ('mobile food service activities', ('561',)),
 'freight_and_cargo_service': ('transportation and storage activities', ('H',)),
 'funeral_service': ('funeral and related activities', ('963',)),
 'furniture_store': ('retail sale household equipment and furniture', ('475',)),
 'gas_station': ('retail sale of automotive fuel', ('473',)),
 'general_dentistry': ('medical and dental practice activities', ('862',)),
 'government_office': ('general public administration activities', ('84',)),
 'grocery_store': ('retail selling in groceries', ('4711',)),
 'gym': ('operation of sports facilities fitness centers', ('931',)),
 'hair_salon': ('hairdressing and beauty treatment activities', ('962',)),
 'hardware_store': ('retail sale hardware building materials', ('4752',)),
 'health_care': ('human health activities', ('86',)),
 'high_school': ('education activities', ('85',)),
 'holiday_rental_home': ('accommodation activities', ('55',)),
 'home_improvement_store': ('retail sale household and building supplies', ('475',)),
 'hospital': ('hospital activities', ('861',)),
 'hotel': ('hotels and similar accommodation activities', ('551',)),
 'hvac_service': ('construction installation activities', ('F',)),
 'ice_cream_shop': ('ice cream retail or food service activities', ('47', '56')),
 'industrial_equipment_manufacturer': ('manufacturing activities', ('C',)),
 'information_technology_company': ('computer programming consultancy and related activities',
                                    ('62',)),
 'installment_loans': ('other credit granting activities', ('6495',)),
 'internet_cafe': ('provision of internet access in facilities open to the public', ('61202',)),
 'it_service_and_computer_repair': ('information technology service and computer repair activities',
                                    ('62', '951')),
 'jewelry_store': ('retail sale jewelry watches and clocks', ('47734',)),
 'laboratory_testing': ('technical testing and analysis', ('712',)),
 'laundromat': ('washing and cleaning of textile and fur products', ('961',)),
 'legal_service': ('legal activities', ('691',)),
 'lodging': ('accommodation activities', ('55',)),
 'manufacturer': ('manufacturing activities', ('C',)),
 'meat_wholesaler': ('wholesale trade activities', ('46',)),
 'metal_fabricator': ('manufacture of fabricated metal products except machinery and equipment',
                      ('25',)),
 'mobile_phone_store': ('retail sale mobile phones and communication equipment', ('474',)),
 'motorcycle_dealer': ('retail sale motorcycles and related parts', ('4783',)),
 'motorcycle_repair': ('repair and maintenance of motorcycles', ('9532',)),
 'nail_salon': ('beauty treatment activities', ('962',)),
 'notary_public': ('legal activities', ('691',)),
 'party_and_event_planning': ('event planning and organization services', ('96901', '823', '5621')),
 'pawn_shop': ('pawnshop operations', ('6496',)),
 'pest_control_service': ('pest control services non-agricultural', ('81291',)),
 'pet_groomer': ('pet care services grooming sitting and training pets', ('9690',)),
 'pet_store': ('retail sale pet and pet supplies', ('4776',)),
 'pharmacy': ('retail sale pharmaceutical medical goods', ('4772',)),
 'preschool': ('education activities', ('85',)),
 'printing_service': ('printing and service activities related to printing', ('181',)),
 'professional_service': ('professional scientific and technical activities', ('N',)),
 'real_estate_agent': ('real estate activities on a fee or contract basis', ('68',)),
 'real_estate_service': ('real estate activities', ('68',)),
 'religious_organization': ('activities of religious organizations', ('9491',)),
 'resort': ('accommodation activities', ('55',)),
 'restaurant': ('restaurants and mobile food service activities', ('561',)),
 'roman_catholic_place_of_worship': ('activities of religious organizations', ('9491',)),
 'school': ('education activities primary secondary tertiary education', ('85',)),
 'seafood_restaurant': ('restaurants and mobile food service activities', ('561',)),
 'shipping_center': ('postal and courier activities', ('53',)),
 'shoe_store': ('retail sale clothing footwear and leather articles', ('4771',)),
 'shopping': ('retail trade activities', ('47',)),
 'smoothie_juice_bar': ('beverage serving activities', ('563',)),
 'social_or_community_service': ('social work activities without accommodation', ('88',)),
 'software_development': ('computer programming and related activities', ('62',)),
 'spa': ('day spa sauna and steam bath activities', ('962',)),
 'tattoo_and_piercing': ('personal service activities', ('96',)),
 'tea_room': ('beverage serving activities', ('563',)),
 'tour_operator': ('tour operator activities', ('7912',)),
 'towing_service': ('supporting land transport activities towing and roadside assistance',
                    ('5221',)),
 'travel_service': ('travel agency and other travel related activities', ('79',)),
 'veterinarian': ('veterinary activities', ('75',)),
 'warehouse_club_store': ('retail trade activities', ('47',)),
 'womens_clothing_store': ('retail sale clothing footwear and leather articles', ('4771',))}

OSM_AMENITY_RULES = {'bank': ('banking activities', ('64',)),
 'bar': ('beverage serving activities', ('563',)),
 'cafe': ('operation of cafes or coffee shops', ('563',)),
 'car_wash': ('motor vehicle and motorcycle washing and detailing', ('9534',)),
 'clinic': ('medical and dental practice activities', ('862',)),
 'college': ('tertiary education', ('854',)),
 'dentist': ('medical and dental practice activities', ('862',)),
 'doctors': ('medical and dental practice activities', ('862',)),
 'driving_school': ('driving school activities', ('8553',)),
 'fast_food': ('fast-food restaurant operations', ('561',)),
 'fire_station': ('public administration and public safety activities', ('84',)),
 'fuel': ('retail sale of automotive fuel', ('473',)),
 'hospital': ('hospital activities', ('861',)),
 'internet_cafe': ('provision of internet access in facilities open to the public', ('61202',)),
 'kindergarten': ('education activities', ('85',)),
 'library': ('library activities', ('9111',)),
 'pharmacy': ('retail sale pharmaceutical medical goods', ('4772',)),
 'place_of_worship': ('activities of religious organizations', ('9491',)),
 'police': ('public administration and public order activities', ('84',)),
 'post_office': ('postal activities', ('531',)),
 'pub': ('beverage serving activities', ('563',)),
 'restaurant': ('restaurants and mobile food service activities', ('561',)),
 'school': ('education activities primary secondary education', ('85',)),
 'social_facility': ('social work activities', ('87', '88')),
 'townhall': ('general public administration activities', ('84',)),
 'university': ('tertiary education', ('854',)),
 'veterinary': ('veterinary activities', ('75',))}

OSM_SHOP_RULES = {'appliance': ('retail sale household equipment', ('475',)),
 'bakery': ('retail sale bakery products', ('47',)),
 'beauty': ('retail sale beauty and personal care goods', ('47',)),
 'bicycle': ('retail trade activities', ('47',)),
 'books': ('retail trade activities', ('47',)),
 'butcher': ('retail sale meat meat products and poultry', ('47213',)),
 'car': ('retail sale of motor vehicles', ('4781',)),
 'car_parts': ('retail sale motor vehicle parts accessories', ('4782',)),
 'car_repair': ('repair and maintenance of motor vehicles', ('953',)),
 'clothes': ('retail sale garments clothing apparel', ('4771',)),
 'computer': ('retail sale computers and peripheral equipment', ('474',)),
 'convenience': ('retail selling in convenience stores', ('4711',)),
 'copyshop': ('printing and service activities related to printing', ('181',)),
 'dry_cleaning': ('washing and cleaning of textile and fur products', ('961',)),
 'electronics': ('retail sale information and communication equipment', ('474',)),
 'funeral_directors': ('funeral and related activities', ('963',)),
 'furniture': ('retail sale household equipment and furniture', ('475',)),
 'gas': ('retail trade activities', ('47',)),
 'general': ('retail trade activities', ('47',)),
 'hairdresser': ('hairdressing and beauty treatment activities', ('962',)),
 'hardware': ('retail sale hardware building materials', ('4752',)),
 'jewelry': ('retail sale jewelry watches and clocks', ('47734',)),
 'laundry': ('washing and cleaning of textile and fur products', ('961',)),
 'medical_supply': ('retail sale pharmaceutical and medical goods', ('4772',)),
 'mobile_phone': ('retail sale mobile phones and communication equipment', ('474',)),
 'motorcycle': ('retail sale motorcycles and related parts', ('4783',)),
 'optician': ('retail sale eyewear and related supplies', ('47736',)),
 'pastry': ('retail sale bakery products', ('47',)),
 'pawnbroker': ('pawnshop operations', ('6496',)),
 'pet': ('retail sale pet and pet supplies', ('4776',)),
 'pharmacy': ('retail sale pharmaceutical medical goods', ('4772',)),
 'photo': ('retail sale photographic equipment and supplies', ('47737',)),
 'printing': ('printing and service activities related to printing', ('181',)),
 'rice': ('retail sale food', ('472',)),
 'shoes': ('retail sale clothing footwear and leather articles', ('4771',)),
 'supermarket': ('retail selling in supermarkets and hypermarkets', ('4711',)),
 'tailor': ('custom tailoring and dressmaking', ('144',)),
 'travel_agency': ('travel agency activities', ('7911',)),
 'tyres': ('retail sale motor vehicle parts and accessories', ('4782',)),
 'variety_store': ('retail trade activities', ('47',)),
 'water': ('retail trade activities', ('47',)),
 'yes': ('retail trade activities', ('47',))}

OSM_OFFICE_RULES = {'association': ('membership organization activities', ('94',)),
 'courier': ('courier activities', ('532',)),
 'educational_institution': ('education activities', ('85',))}

OSM_HEALTHCARE_RULES = {'clinic': ('medical and dental practice activities', ('862',)),
 'dentist': ('medical and dental practice activities', ('862',)),
 'laboratory': ('medical and diagnostic laboratory service activities', ('869',)),
 'pharmacy': ('retail sale pharmaceutical medical goods', ('4772',))}

TRUSTED_OVERTURE_FLOORS = frozenset(['accountant',
 'advertising_agency',
 'animal_or_pet_service',
 'attorney_or_law_firm',
 'auto_dealer',
 'auto_detailing',
 'auto_parts_store',
 'automotive_repair',
 'b2b_advertising_and_marketing_service',
 'bank',
 'bank_or_credit_union',
 'bar',
 'barbecue_restaurant',
 'barber',
 'beauty_salon',
 'beauty_supply_store',
 'bike_store',
 'bookstore',
 'bubble_tea_shop',
 'building_or_construction_service',
 'cafe',
 'car_rental_service',
 'car_wash',
 'caterer',
 'christian_place_of_worship',
 'clothing_store',
 'coffee_shop',
 'college_university',
 'computer_store',
 'contractor',
 'convenience_store',
 'dental_clinic',
 'doctors_office',
 'driving_school',
 'dry_cleaning',
 'education',
 'electronics_store',
 'elementary_school',
 'employment_agency',
 'event_photography_service',
 'eyewear_store',
 'family_practice',
 'fast_food_restaurant',
 'filipino_restaurant',
 'financial_service',
 'flowers_and_gifts_store',
 'food_and_drink',
 'food_beverage_distributor',
 'food_truck_stand',
 'freight_and_cargo_service',
 'funeral_service',
 'furniture_store',
 'gas_station',
 'general_dentistry',
 'government_office',
 'grocery_store',
 'gym',
 'hair_salon',
 'hardware_store',
 'health_care',
 'high_school',
 'holiday_rental_home',
 'home_improvement_store',
 'hospital',
 'hotel',
 'hvac_service',
 'industrial_equipment_manufacturer',
 'information_technology_company',
 'installment_loans',
 'internet_cafe',
 'jewelry_store',
 'laboratory_testing',
 'laundromat',
 'legal_service',
 'lodging',
 'manufacturer',
 'meat_wholesaler',
 'metal_fabricator',
 'mobile_phone_store',
 'motorcycle_dealer',
 'motorcycle_repair',
 'nail_salon',
 'notary_public',
 'pawn_shop',
 'pest_control_service',
 'pet_groomer',
 'pet_store',
 'pharmacy',
 'preschool',
 'printing_service',
 'professional_service',
 'real_estate_agent',
 'real_estate_service',
 'religious_organization',
 'resort',
 'restaurant',
 'roman_catholic_place_of_worship',
 'school',
 'seafood_restaurant',
 'shipping_center',
 'shoe_store',
 'smoothie_juice_bar',
 'software_development',
 'spa',
 'tattoo_and_piercing',
 'tea_room',
 'tour_operator',
 'towing_service',
 'travel_service',
 'veterinarian',
 'warehouse_club_store',
 'womens_clothing_store'])

def source_rules_fingerprint() -> str:
    """Semantic fingerprint of the deterministic source-category rule tables."""
    def mapping_payload(mapping):
        return [
            [str(key), str(value[0]), [str(code) for code in value[1]]]
            for key, value in sorted(mapping.items())
        ]

    payload = {
        "overture_non_activity": sorted(OVERTURE_NON_ACTIVITY),
        "osm_non_activity_prefixes": list(OSM_NON_ACTIVITY_PREFIXES),
        "osm_non_activity_exact": sorted(OSM_NON_ACTIVITY_EXACT),
        "osm_auxiliary_activity_keys": sorted(OSM_AUXILIARY_ACTIVITY_KEYS),
        "osm_auxiliary_activity_prefixes": list(OSM_AUXILIARY_ACTIVITY_PREFIXES),
        "osm_coherent_compounds": [
            sorted([f"{key}={value}" for key, value in pair])
            for pair in sorted(
                OSM_COHERENT_COMPOUNDS,
                key=lambda pair: sorted(f"{key}={value}" for key, value in pair),
            )
        ],
        "overture_uncodeable": sorted(OVERTURE_UNCODEABLE),
        "osm_uncodeable_exact": sorted(OSM_UNCODEABLE_EXACT),
        "overture_coherent_compounds": sorted(OVERTURE_COHERENT_COMPOUNDS),
        "overture_rules": mapping_payload(OVERTURE_RULES),
        "osm_amenity_rules": mapping_payload(OSM_AMENITY_RULES),
        "osm_shop_rules": mapping_payload(OSM_SHOP_RULES),
        "osm_office_rules": mapping_payload(OSM_OFFICE_RULES),
        "osm_healthcare_rules": mapping_payload(OSM_HEALTHCARE_RULES),
        "trusted_overture_floors": sorted(TRUSTED_OVERTURE_FLOORS),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class QueryPlan:
    query_text: str
    branch_roots: tuple[str, ...] = ()
    rule: str = "raw_category"


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    query_text: str
    branch_codes: tuple[str, ...] = ()
    branch_titles: tuple[str, ...] = ()
    rule: str = "raw_category"
    block_reason: str | None = None
    floor_code: str | None = None
    terminal_kind: MappingKind | None = None


@dataclass(frozen=True, slots=True)
class AutoMapping:
    mapping: MappingRule | None
    query_text: str
    rule: str
    candidate_codes: tuple[str, ...] = ()
    candidate_scores: tuple[float, ...] = ()
    retrieval_score: float | None = None
    reason: str = ""


def _unwrap(value: str) -> str:
    text = clean_literal(value) or ""
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, (list, tuple)) and parsed:
            text = " | ".join(str(x) for x in parsed)
        else:
            text = text[1:-1]
    return text.replace("\\'", "'").strip(" '[]\"")


def _multiple_components(source: str, value: str) -> bool:
    source = source.casefold().strip()
    raw = _unwrap(value).strip()
    if source == "osm":
        if raw.casefold() in OSM_UNCODEABLE_EXACT:
            return False
        items = [item.strip() for item in raw.split(" | ") if item.strip()]
        tags: dict[str, str] = {}
        for item in items:
            if "=" not in item:
                return True
            key, val = item.split("=", 1)
            key = key.strip().casefold()
            # Descriptive auxiliaries enrich the retrieval text but do not create a
            # second principal economic activity. The allow-list is intentionally
            # conservative and separately fingerprinted.
            if _osm_auxiliary_key(key):
                continue
            tags[key] = val.strip().casefold()
        if len(tags) <= 1:
            return False
        pairs = frozenset(tags.items())
        return pairs not in OSM_COHERENT_COMPOUNDS
    if source == "overture":
        folded = raw.casefold()
        if folded in OVERTURE_UNCODEABLE or folded in OVERTURE_COHERENT_COMPOUNDS:
            return False
        return "_and_" in folded or "_or_" in folded
    return False


def _ambiguous_pet_shop(source: str, value: str) -> bool:
    if source.casefold().strip() != "osm":
        return False
    parts = {part.strip().casefold() for part in _unwrap(value).split(" | ") if part.strip()}
    return "shop=pet_grooming" in parts


def _proposal_guard(source: str, source_value: str, plan: QueryPlan) -> str | None:
    if _multiple_components(source, source_value):
        return "compound_source"
    if (
        source.casefold().strip() == "overture"
        and _unwrap(source_value).casefold().strip() == "flowers_and_gifts_store"
    ):
        return "mixed_category_ceiling"
    if len(plan.branch_roots) > 1:
        return "ambiguous_branch_roots"
    if plan.rule == "overture:store_suffix":
        return "heuristic_store_suffix"
    if _ambiguous_pet_shop(source, source_value):
        return "ambiguous_pet_shop"
    return None


def category_query(source: str, value: str) -> str:
    text = _unwrap(value)
    source = source.casefold().strip()
    if source == "overture":
        text = text.replace("_", " ")
    elif source == "osm":
        parts: list[str] = []
        for item in text.split("|"):
            item = item.strip()
            if "=" in item:
                key, val = item.split("=", 1)
                parts.extend((val.replace("_", " "), key.replace("_", " ")))
            else:
                parts.append(item.replace("_", " "))
        text = " ".join(parts)
    return re.sub(r"\s+", " ", text).strip()


def _is_non_activity(source: str, value: str) -> bool:
    source = source.casefold().strip()
    raw = _unwrap(value).casefold().strip()
    if source == "overture":
        return raw in OVERTURE_NON_ACTIVITY
    if source == "osm":
        return raw in OSM_NON_ACTIVITY_EXACT or raw.startswith(OSM_NON_ACTIVITY_PREFIXES)
    return False


def _is_uncodeable(source: str, value: str) -> bool:
    source = source.casefold().strip()
    raw = _unwrap(value).casefold().strip()
    if source == "overture":
        return raw in OVERTURE_UNCODEABLE
    if source == "osm":
        return raw in OSM_UNCODEABLE_EXACT
    return False


def _osm_tags(value: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for item in _unwrap(value).split("|"):
        item = item.strip()
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        tags[key.strip().casefold()] = val.strip().casefold()
    return tags


def category_plan(source: str, value: str) -> QueryPlan:
    source = source.casefold().strip()
    raw = _unwrap(value)
    folded = raw.casefold().strip()

    if source == "overture":
        rule = OVERTURE_RULES.get(folded)
        if rule:
            return QueryPlan(rule[0], tuple(rule[1]), f"overture:{folded}")
        if folded.endswith("_restaurant"):
            return QueryPlan(
                "restaurants and mobile food service activities",
                ("561",),
                "overture:restaurant_suffix",
            )
        if folded.endswith("_store"):
            return QueryPlan(
                f"retail sale {folded.removesuffix('_store').replace('_', ' ')}",
                ("47",),
                "overture:store_suffix",
            )
        if folded.endswith("_clinic"):
            return QueryPlan(
                "medical and dental practice activities",
                ("86",),
                "overture:clinic_suffix",
            )

    if source == "osm":
        tags = _osm_tags(value)
        if "amenity" in tags:
            val = tags["amenity"]
            rule = OSM_AMENITY_RULES.get(val)
            if rule:
                return QueryPlan(rule[0], tuple(rule[1]), f"osm:amenity={val}")
        if "shop" in tags:
            val = tags["shop"]
            rule = OSM_SHOP_RULES.get(val)
            if rule:
                return QueryPlan(rule[0], tuple(rule[1]), f"osm:shop={val}")
            return QueryPlan(f"retail sale {val.replace('_', ' ')}", ("47",), "osm:shop")
        if "healthcare" in tags:
            val = tags["healthcare"]
            rule = OSM_HEALTHCARE_RULES.get(val)
            if rule:
                return QueryPlan(rule[0], tuple(rule[1]), f"osm:healthcare={val}")
        if tags.get("office") == "government":
            return QueryPlan("general public administration activities", ("84",), "osm:government")
        if "office" in tags:
            val = tags["office"]
            rule = OSM_OFFICE_RULES.get(val)
            if rule:
                return QueryPlan(rule[0], tuple(rule[1]), f"osm:office={val}")
            return QueryPlan(f"{val.replace('_', ' ')} professional service activities")
        if tags.get("tourism") == "hotel":
            return QueryPlan("hotels and similar accommodation activities", ("551",), "osm:hotel")
        if tags.get("tourism") in {"guest_house", "hostel", "chalet", "apartment"}:
            return QueryPlan("short term accommodation activities", ("55",), "osm:lodging")

    return QueryPlan(category_query(source, value))


def _trusted_floor(source: str, source_value: str, plan: QueryPlan) -> str | None:
    if len(plan.branch_roots) != 1 or _multiple_components(source, source_value):
        return None
    rule = plan.rule
    source = source.casefold().strip()
    trusted = False
    if source == "overture":
        folded = _unwrap(source_value).casefold().strip()
        trusted = folded in TRUSTED_OVERTURE_FLOORS or rule == "overture:restaurant_suffix"
    elif source == "osm":
        trusted = (
            rule.startswith("osm:amenity=")
            or rule.startswith("osm:shop=")
            or rule.startswith("osm:healthcare=")
            or rule.startswith("osm:office=")
            or rule in {"osm:government", "osm:hotel", "osm:lodging"}
        )
    return plan.branch_roots[0] if trusted else None


def prepare_source_evidence(
    taxonomy: PsicTaxonomy,
    source: str,
    source_value: str,
) -> PreparedEvidence:
    plan = category_plan(source, source_value)
    compound = _multiple_components(source, source_value)
    branches = tuple(code for code in plan.branch_roots if code in taxonomy.nodes)
    titles = tuple(taxonomy.get(code).title for code in branches)
    floor = _trusted_floor(source, source_value, plan)
    if floor not in branches:
        floor = None

    if not compound and _is_non_activity(source, source_value):
        return PreparedEvidence(
            query_text=plan.query_text,
            rule=plan.rule,
            terminal_kind=MappingKind.NOT_ACTIVITY,
        )
    if not compound and _is_uncodeable(source, source_value):
        return PreparedEvidence(
            query_text=plan.query_text,
            rule=plan.rule,
            terminal_kind=MappingKind.UNCODEABLE,
        )

    tokens = [token for token in normalize_key(plan.query_text).split() if len(token) > 2]
    guard = _proposal_guard(source, source_value, plan)
    if guard is None and len(tokens) < 2:
        guard = "short_query"
    return PreparedEvidence(
        query_text=plan.query_text,
        branch_codes=branches,
        branch_titles=titles,
        rule=plan.rule,
        block_reason=guard,
        floor_code=floor,
    )


def automatic_mapping(
    taxonomy: PsicTaxonomy,
    retriever: PsicRetriever,
    source: str,
    source_value: str,
    *,
    top_n: int = 5,
    min_score: float = 0.45,
    min_margin: float = 0.12,
) -> AutoMapping:
    prepared = prepare_source_evidence(taxonomy, source, source_value)
    if prepared.terminal_kind is not None:
        mapping = MappingRule(
            source=source,
            source_value=source_value,
            mapping_kind=prepared.terminal_kind,
        )
        return AutoMapping(
            mapping=mapping,
            query_text=prepared.query_text,
            rule=prepared.rule,
            reason="high_precision_source_policy",
        )

    hits = retriever.search_hierarchical(
        prepared.query_text,
        top_n=top_n,
        branch_roots=prepared.branch_codes,
    )
    codes = tuple(hit.code for hit in hits)
    scores = tuple(float(hit.score) for hit in hits)
    top = scores[0] if scores else None
    margin = (scores[0] - scores[1]) if len(scores) > 1 else (scores[0] if scores else 0.0)

    chosen: str | None = None
    origin = ""
    if (
        hits
        and top is not None
        and top >= min_score
        and margin >= min_margin
        and prepared.block_reason is None
    ):
        chosen = hits[0].code
        origin = "semantic_refinement"
    elif prepared.floor_code is not None and prepared.block_reason is None:
        chosen = prepared.floor_code
        origin = "trusted_source_floor"

    mapping = None
    if chosen is not None:
        mapping = MappingRule(
            source=source,
            source_value=source_value,
            mapping_kind=(
                MappingKind.SUBTREE if taxonomy.has_children(chosen) else MappingKind.EXACT
            ),
            codes=(chosen,),
        )

    reason = origin or prepared.block_reason or ("no_candidates" if not hits else "candidate_only")
    return AutoMapping(
        mapping=mapping,
        query_text=prepared.query_text,
        rule=prepared.rule,
        candidate_codes=codes,
        candidate_scores=scores,
        retrieval_score=top,
        reason=reason,
    )
