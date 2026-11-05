# Places: acquisition, reconciliation, and classification

The place branch combines OpenStreetMap and Overture Places into one canonical establishment layer before economic classification.

## Source policy

The current implementation directly uses:

- OpenStreetMap from the shared Geofabrik Philippines PBF; and
- Overture Maps Places.

It does not directly ingest Foursquare, and the current Overture policy excludes Foursquare-attributed records.

<!-- sigma-augment-docs-v1:begin:places -->
## Additional observations after loading

After the OSM/Overture load, `sigma augment` accepts user-supplied CSV/Parquet establishments in the **editable loaded-place handoff**. It reuses SIGMA's existing spatial/name reconciliation thresholds and canonical identities rather than performing a second OSM/Overture acquisition. New source attributes are retained with `aug_<source>__` prefixes. Optional explicit PSIC and IO16/IO80/IO240 tags remain auditable; contradictory input tags block modification.

See [Augment user-provided places](augmentation.md). This pathway does **not** change the policy excluding Foursquare-attributed Overture observations.
<!-- sigma-augment-docs-v1:end:places -->

## Candidate matching

An OSM observation and an Overture observation are considered only when their Haversine separation is at most 120 m. For longitude-latitude pairs $(\lambda_1,\phi_1)$ and $(\lambda_2,\phi_2)$ in radians,

$$
h=\sin^2\left(\frac{\phi_2-\phi_1}{2}\right)
 +\cos\phi_1\cos\phi_2\sin^2\left(\frac{\lambda_2-\lambda_1}{2}\right),
$$

$$
d=2R\arcsin\sqrt{h},\qquad R=6{,}371{,}008.8\text{ m}.
$$

Names are normalized and scored with the maximum of RapidFuzz's simple ratio and token-sort ratio, scaled to $s\in[0,1]$.

The acceptance rule is deliberately stricter as distance increases:

| Distance | Required name score |
|---:|---:|
| generic/very short name | $d\le15$ m and $s\ge0.99$ |
| $d\le20$ m | $s\ge0.70$ |
| $20<d\le50$ m | $s\ge0.82$ |
| $50<d\le90$ m | $s\ge0.90$ |
| $90<d\le120$ m | $s\ge0.94$ |

Accepted candidates receive

$$
q=0.82s+0.18\left(1-\frac{d}{120}\right).
$$

Candidates are sorted by descending $q$, then ascending distance, then stable source-row identifiers. SIGMA greedily accepts a pair only if neither source record has already been matched. The result is therefore deterministic one-to-one reconciliation.

For a matched pair, coordinates are normally the midpoint of the two observations. If that midpoint falls outside a concave study boundary or into a hole, SIGMA retains the match but deterministically uses an actual in-boundary source coordinate.

## Canonical identity and provenance

Canonical IDs are stable SHA-256-derived identifiers of the contributing source IDs. The row preserves source-specific names, categories, IDs, license metadata, aliases, matching distance, and name score.

```{admonition} SIGMA-specific rule
:class: important
The distance/name thresholds and the weighted candidate strength are reconciliation policy, not a claim of a published record-linkage optimum. They are versionable implementation rules and should be reported as such.
```

## PSIC and economy mapping

Canonical places are classified into the Philippine Standard Industrial Classification (PSIC) using reviewed deterministic crosswalks and high-precision name rules. Strong source categories take precedence; compatible OSM tag combinations are allowed; incompatible compound activities fail closed into review rather than being forced. Optional LLM assistance is not part of the default path.

When a category matches no reviewed row but a name rule does, and the category has a trusted floor (for example the compound OSM tag `tourism=hotel | cuisine=filipino`), the category takes precedence: the name rule is kept only when it lies inside the category's subtree, and a disjoint name rule is dropped with flag `NAME_RULE_OVERRULED_BY_CATEGORY`. Reviewed category rows point to the deepest PSIC code that the category supports. Under Rev. 5, division 47 (retail) also holds retail of motor vehicles and division 55 (accommodation) also holds booking intermediation, so rows such as `shop=bakery` or Overture `lodging` point below those divisions.

The PSIC result is mapped through PSIC-to-IO concordances to candidate IO240/80/16 industries. The ordinary **new-area** `sigma load AREA` constructs a baseline per-area hierarchical PSA 2018 IO240/IO80/IO16 economy (`min_places=5`, new-profile `coarse_policy=residual`). Fixed IO16/80/240 and custom economies are explicit alternatives; existing unselected legacy workspaces retain IO80. These economic sectors, and any subsequent run-stage K=0 roll-up, govern the economic types used by clustering and network X. See [Hierarchical economy](hierarchical.md).

### Government administrative functions and institutional ownership

After the deterministic PSIC classifier, `places.psic` applies a **conservative administrative-function correction**: unmistakable government health/education administrative offices may be assigned PSIC 84120 before IO tagging, while hospitals, schools and ambiguous names are protected or referred for review. The administrative classifier preserves its original-PSIC audit.

At the `places.classified` stage, SIGMA may conservatively promote public/private **IO ownership** from explicit source evidence, independently verified canonical registry links or official external-ID matches **subject to PSIC/IO consistency**. The production evidence layers include a validated locally installed national hospital index if present, packaged school and higher-education indexes and an area-scoped fallback. A name/city match alone is provisional, not automatic proof of ownership; ambiguous or conflicting cases abstain. Registry evidence does not overwrite PSIC or invent an IO classification outside supported candidate sets. See [Institutional activity and ownership evidence](shadow_classification.md) and [Hierarchical economy](hierarchical.md) for the separation of activity, ownership, and economic-sector resolution.
