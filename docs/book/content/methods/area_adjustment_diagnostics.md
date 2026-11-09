# Area-adjusted Katz: empirical diagnostics and interpretation

*Methods companion to stages 14–17 · Reviewed methodology: 9 November 2026.*

This chapter reports what the tile-perspective correction **was observed to do**, what it **does not establish**, and how it differs from the separate establishment inverse-distance score. For the production equations, see [X](x_graph.md), [Centrality](centrality.md), and [Scoring](scoring.md). No cluster memberships, network edges, or polygons are modified by the correction.

## Model being evaluated

For original positive directed X weights $W_{ij}$, compute every tile's total directed degree $k_i^{total}=k_i^{in}+k_i^{out}$, including zero-degree nodes. For its **final** network Voronoi polygon area $A_i$ in km², fit a *pooled, geography-specific* Poisson pseudo-maximum-likelihood regression:

$$
\mathbb E[k_i^{total}\mid A_i]=\exp(\beta_0)A_i^{\gamma}.
$$

The estimated $\hat\gamma$ expresses an **average degree–area association**, not an estimate of false edges, true economic interactions, edge strength, or a physical gravity constant. Define $f_i=A_i^{-\hat\gamma}$ and $F=\mathrm{diag}(f_1,\ldots,f_n)$. The two *focal-tile-perspective* weight operators are:

$$
W^{\prime\,out}=FW, \qquad W^{\prime\,in}=FW^{\mathsf T}.
$$

In general $FW^{\mathsf T}\ne (FW)^{\mathsf T}$. The same tile's area scales both its own incoming and outgoing direct connections. Katz indirect walks still traverse other tiles and their factors. One shared spectrally safe $\alpha$, with factor 0.85 when the spectral radius is identified, is used for both:

$$
K^{out}=(I-\alpha FW)^{-1}\mathbf1,\qquad
K^{in}=(I-\alpha FW^{\mathsf T})^{-1}\mathbf1.
$$

The canonical normalized cluster centrality is $C_i=\sqrt{K_i^{in}K_i^{out}}/\sqrt{\sum_j K_j^{in}K_j^{out}}$. **Neither** the published original X weights **nor** the topology is changed. The area correction is applied **before** Katz, never again to $C_i$ or an establishment score. Use `sigma run AREA --no-area-adjustment` only for a deliberate unadjusted-Katz comparison.

## Metro Manila: read-only methodology evaluation

The preproduction *read-only diagnostic* used 14,631 clusters and 2,031,788 directed X edges from cached Metro Manila artifacts. It did **not** constitute a production deployment or an external economic benchmark. Pooled total-directed-degree PPML estimated $\hat\gamma=0.44457936$. A doubling of tile area was associated with $2^{0.44457936}-1\approx36.1\%$ more expected directed connections.

Two properties of that X graph matter for reading the estimate. First, **19 X nodes had zero degree**; they stayed in the PPML fit, which needs no logarithm of the outcome. Second, **every one of the 14,631 nodes had equal incoming and outgoing degree** (maximum $\lvert k_i^{in}-k_i^{out}\rvert=0$), so in-degree, out-degree and total-degree regressions gave the same exponent. This was an observed property of that graph, not a requirement: in another geography the three fits may differ, and the defined estimator remains **total** directed degree. SIGMA now records `degree_balance` and `degree_orientation_regressions` with every run so this can be checked.

| Diagnostic | Original X / balanced Katz | Tile-perspective adjustment |
|---|---:|---:|
| Spearman correlation of tile area with balanced Katz | +0.4220 | −0.0266 |
| PPML outgoing-strength area exponent | +0.5602 | −0.1552 |
| PPML incoming-strength area exponent | +1.0055 | +0.2041 |
| Top-100 clusters from smallest-area decile | 0 | 28 |
| Top-100 clusters from largest-area decile | 56 | 11 |
| Top-10 share of summed Katz scores | 0.85% | 1.92% |
| Top-100 share of summed Katz scores | 2.59% | 7.25% |

Original versus adjusted balanced-Katz rank correlation was **0.8529**, but **only 15 of the original top 100** remained among the adjusted top 100. The correction substantially changed the ranking tail and increased score concentration, even while reducing the overall area correlation.

Direction-specific *adjusted raw Katz* area correlations were −0.0243 (outgoing) and −0.0132 (incoming); the combined balanced score was −0.0266. Thus the combined near-zero correlation in this geography was **not just cancellation of large, opposite-sign raw Katz biases**. The incoming- and outgoing-**strength** PPML exponents did retain opposite signs: strength, degree and recursive Katz are different objects.

### Small tiles and specification limits

For the descriptive diagnostic $f_i k_i^{total}$, the mean in the **smallest-area decile** was **2.30×** its overall mean. Across deciles from smallest to largest, the corresponding ratios were:

| Area decile | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Relative mean $f_i k_i^{total}$ | **2.30** | 1.34 | 1.07 | 0.93 | 0.83 | 0.76 | 0.70 | 0.68 | 0.64 | 0.74 |

The pooled power law does **not** flatten every area decile. Very small tiles may be overcompensated; they might also represent genuinely dense activity. The available data do not identify which explanation dominates. Final Voronoi polygons are defined sector by sector; small polygons may retain an overlap baseline from other sectors that a pure power law cannot represent perfectly.

The pooled $\hat\gamma$ may mix within-sector tile-size variation with between-sector composition. Sector fixed effects are a **diagnostic sensitivity comparison**, not part of the adopted estimator. Connectivity and polygons are spatially dependent, so ordinary HC1 sandwich uncertainty can be too optimistic. A near-zero post-adjustment correlation cannot establish that links are economically spurious or that revised rankings measure true market importance.

## Pasig: completed incremental workflow validation

After the lineage-reuse repair, canonical `sigma run pasig` reused clustering, centers, distances, partitions, economy, and X. It recomputed centrality, establishment scores and exports, and Explorer loaded successfully:

- **1,047 clusters** and **103,312 directed X edges**;
- fitted $\hat\gamma=0.376620537$, reported 95% interval **[0.352419, 0.400822]**;
- **11,005 retained establishments** scored;
- no spatial or clustering stage was recomputed.

This validates the completed Pasig execution and output pipeline, **not** independent economic impact or correctness of every ranking. Metro Manila's post-lineage-repair full incremental run was still pending at the time of this documented evaluation; do not re-label the earlier read-only diagnostic as that run.

## Separate establishment-score change

Canonical Katz uses **full inverse-distance** establishment scoring:

$$
S_p=\frac{C_{c(p)}}{\max(d_R(p,m_{c(p)})/(1\,\mathrm m),1)}.
$$

This is distinct from the area correction and from Newtonian gravity's inverse-square kernel. The notional masses in the motivating analogy are normalized to one; $q_iq_j$ in the original X weight represents sector-relative establishment participation, **not physical masses or polygon density**. With $C_c=0.40$, an establishment at 200 m receives $0.002$; at 500 m, $0.0008$; at or below 1 m, $0.40$. The former bounded 15% p90 rule remains only for explicit legacy eigenvector scoring.

The Metro Manila **cluster-level** comparison did **not** validate the new establishment-level score or show that more distant businesses are necessarily less economically influential. Such economic validation requires independent outcomes or benchmarks. Because $\hat\gamma$ and graph-wide Katz L2 normalization are area/run-specific, compare normalized scores primarily **within** one geography.

## Diagnostics recorded with every run

The table above came from a separate read-only review. Production runs now record the same kinds of evidence with `analysis.centrality` and in `sigma_run_metadata.json` → `tile_area_adjustment` (see *Diagnostics recorded with every run* in [Centrality](centrality.md)): the unadjusted balanced-Katz comparison (area correlation, rank correlation, retained top 100, area-decile counts, concentration), adjusted concentration, the shared equal-count area-decile assignments for $k_i$, $f_ik_i$ and top-100 counts, the in/out degree balance, orientation-specific degree fits and the extreme factor ratio. The comparison never changes a score; if it fails, the failure is recorded. Under the Hood can display the current run's decile table and comparison beside the Metro Manila figures.

## Implementation notes relative to the reviewed specification

The implementation follows the reviewed specification of 9 November 2026, with three documented differences in scope:

- **Isolated X centers without a final tile.** The specification's computation step says to reject missing areas. The implementation stops for any X center that has an edge but no tile; an X center with **zero** degree and no tile is excluded from the PPML fit, given $f_i=1$, and counted in `excluded_isolated_without_tile`. Such a node has $K^{in}=K^{out}=\beta$ for every factor, so no score can change; the regression sample does lose that zero-degree observation.
- **X distance exponent.** The specification fixes the X kernel exponent at 1. The implementation keeps the existing `--x-distance-decay-lambda` option (default 1.0) and records the value used with the centrality diagnostics.
- **Opt-out.** `--no-area-adjustment` (or `area_adjustment=False`) gives ordinary balanced Katz for deliberate comparisons; the correction is on by default.

## Reproducibility and decisions

Re-estimate $\hat\gamma$ only when topology, final tile areas or other regression inputs/configuration change; otherwise reuse a valid immutable centrality artifact. The method records its PPML and area-factor diagnostics with `analysis.centrality`. Input X weights remain unchanged. Missing positive tile areas for connected X nodes, nonfinite weights, and unidentifiable fits require an explicit error or a *mathematically exact* documented no-op case (equal areas / edgeless graph), not a substitute coefficient from another geography.

**Adopted method:** one pooled total-directed-degree exponent per geography and two focal-tile perspective operators. Spline corrections, additional sector fixed effects, overlap-share weights, edge eligibility redesign, and arbitrary factor clipping are **not** silently introduced.
