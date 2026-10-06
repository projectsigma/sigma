# Places: acquisition, reconciliation, and classification

The place branch combines OpenStreetMap and Overture Places into one canonical establishment layer before economic classification.

## Source policy

The current implementation directly uses:

- OpenStreetMap from the shared Geofabrik Philippines PBF; and
- Overture Maps Places.

It does not directly ingest Foursquare, and the current Overture policy excludes Foursquare-attributed records.

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

The PSIC result is then mapped to the selected economy, by default PSA 2018 IO80. IO16 and custom economies are supported. This mapping is the bridge from establishments to the economic-type dimension used by all later clustering and graph stages.
