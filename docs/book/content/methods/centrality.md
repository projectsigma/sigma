# Tile-area-adjusted balanced sender-receiver Katz centrality (stages 15–16)

*Pipeline stages 15–16 of 17 · `sigma run`. Under the Hood computes the balanced Katz scores live on the worked X example (sections “Stage 15” and “Stage 16”).*

Canonical SIGMA centrality preserves the full directed X graph and asks a node to be important in **both** directions: it should be able to receive weighted influence through incoming structure and to send influence through outgoing structure.

This is implemented by computing two raw Katz vectors, taking their nodewise geometric mean, and normalizing only once after combination.

Before Katz, SIGMA attenuates each tile's own incoming and outgoing connections by a factor estimated, for each geography, from how total directed degree scales with final Voronoi tile area. The section *Tile-area adjustment* below gives the details.

## Weighted directed Katz

Let $W$ be the nonnegative adjacency matrix of X with $W_{ij}=w_{ij}$ for edge $i\to j$. With baseline $\beta>0$ and attenuation $\alpha>0$, NetworkX's incoming orientation corresponds to

$$
K^{in}=\beta(I-\alpha W^T)^{-1}\mathbf 1,
$$

or equivalently

$$
K^{in}_i=\beta+\alpha\sum_j W_{ji}K^{in}_j.
$$

SIGMA obtains the outgoing analogue by computing the same Katz rule on the reversed graph:

$$
K^{out}=\beta(I-\alpha W)^{-1}\mathbf 1.
$$

Both components use the **same** $\alpha$ and $\beta$, and both are computed with `normalized=False`.

## Tile-area adjustment

Under positive-area overlap eligibility, a Voronoi polygon that occupies more space tends to overlap more polygons and therefore acquires more X edges. The adjustment targets this **topological area advantage**, not an independently estimated trade flow. The original `analysis.x` edge weights $W$ are not changed; the adjustment exists only inside the centrality stage.

### One area exponent for each run

For each X node with a final Voronoi polygon, including zero-degree nodes, let $A_i$ be its final polygon area in km² (equal-area CRS EPSG:6933) and let $k_i=k_i^{in}+k_i^{out}$ be its total **directed** degree. SIGMA fits a PPML (Poisson pseudo-maximum-likelihood) log-link model with HC1 sandwich standard errors:

$$
\mathbb E[k_i\mid A_i]=\exp(\beta_0)\,A_i^{\gamma}.
$$

$\hat\gamma$ is estimated separately for the current geography; the Metro Manila estimate is never hardcoded. An X center with no final tile is excluded only if it has zero incoming and outgoing degree; its neutral factor $f_i=1$ cannot affect Katz, and the exclusion is recorded. An untiled node with an edge is an error. If the exponent cannot be estimated, the stage stops with a clear error. There are two exceptions, and in both the area factor has no effect for any $\gamma$. If every tile has the same area, then $F=cI$, the constant $c$ cancels in $\alpha F W$, and the scores equal unadjusted balanced Katz exactly (`not_identified_constant_area`). If X has no edges, every Katz value equals $\beta$ (`not_identified_no_edges`, scale 1 as in unadjusted Katz). SIGMA reports these cases with `gamma = null` instead of substituting an exponent.

### Two tile-perspective operators

With

$$
f_i=A_i^{-\hat\gamma},\qquad F=\operatorname{diag}(f_i),
$$

SIGMA adjusts each tile's *own* connections, without using the neighbor's polygon area:

$$
\boxed{W'^{out}=FW,\qquad W'^{in}=FW^{\mathsf T}.}
$$

$FW^{\mathsf T}$ is **not** in general the transpose of $FW$, so the two operators are kept separate. The Katz components above are computed on these operators:

$$
K^{out}=\beta(I-\alpha FW)^{-1}\mathbf 1,\qquad K^{in}=\beta(I-\alpha FW^{\mathsf T})^{-1}\mathbf 1,
$$

or, for node $i$,

$$
K^{out}_i=\beta+\alpha f_i\sum_j W_{ij}K^{out}_j,\qquad K^{in}_i=\beta+\alpha f_i\sum_j W_{ji}K^{in}_j.
$$

The Katz equations have no other area term. SIGMA writes the regression, the per-node area factors and strengths, and the remaining area diagnostics with the centrality artifact.

The PPML tile-area correction is a SIGMA modeling choice. It is not a theorem that the adjusted rankings measure true economic influence.

## Choosing alpha safely

The default configuration is

$$
\text{alpha\_factor}=0.85,\qquad \beta=1.
$$

For a cyclic graph where the spectral radius $\rho(W)>0$ is successfully estimated,

$$
\alpha=\frac{0.85}{\rho(W)},
$$

so $\alpha<1/\rho(W)$ as required for the usual Katz resolvent.

If X is a DAG, then $\rho(W)=0$ and the Katz walk expansion is finite. SIGMA uses the maximum weighted outgoing row sum only as a numerical scale:

$$
s=\max_i\sum_j W_{ij},\qquad
\alpha=\frac{0.85}{s}.
$$

The same conservative row-sum bound is used if the sparse spectral-radius solver fails. A graph with no edges uses scale 1.

The row sum has no lower bound. For cyclic X, SIGMA first scales the adjacency matrix to $\widetilde W=W/s$, with $s=\max_i\sum_jW_{ij}$. It then estimates $\rho(\widetilde W)$ and uses $\alpha=0.85/[s\rho(\widetilde W)]$, equivalently $0.85/\rho(W)$. The near-zero spectral-radius cutoff is applied to the normalized matrix, not to absolute X weights. If the solver fails, $\alpha=0.85/s$ is a conservative bound.

Consequently, uniformly multiplying every positive X weight by any representable scale leaves $\alpha W$ (and the resulting Katz scores) unchanged, provided the required attenuation remains finite. This matters because coefficient-over-distance weights are often much smaller than 1; a fixed floor of 1 would make scores nearly equal.

### Alpha for the adjusted operators

The rules above apply to the adjusted operators. For positive $f_i$, $\rho(FW)=\rho(FW^{\mathsf T})$, because $FW^{\mathsf T}$ is the transpose of $WF$ and $WF=F^{-1}(FW)F$; one $\alpha=0.85/\rho(FW)$ therefore serves both components. When a row-sum scale is needed (acyclic X, zero radius, or solver failure), SIGMA retains the original **outgoing** weighted row-sum convention, $s=\max_i f_i\sum_j W_{ij}$. This bounds the spectral radius of both operators because their radii are equal. Whether X is acyclic is decided from the edge table (strongly connected components); a positive diagonal $F$ does not change which entries are nonzero, so $FW$ and $FW^{\mathsf T}$ are acyclic exactly when $W$ is.


## Sender-receiver combination

SIGMA forms

$$
g_i=\sqrt{K^{in}_iK^{out}_i}
$$

and then performs exactly one L2 normalization:

$$
C_i=\frac{g_i}{\sqrt{\sum_j g_j^2}}.
$$

This is the reported canonical centrality.

### Why the geometric mean?

Sharkey (2017) derives a directed Katz control score proportional to the **product** of receiver and sender terms,

$$
\sigma_i=r_i s_i,
$$

and emphasizes that a dynamically central node should be able both to receive and pass on flux. SIGMA uses the square root of that same nonnegative product before normalization. Because $\sqrt{x}$ is strictly increasing for $x\ge0$, the geometric mean has the **same pre-normalization node ranking** as the raw product while restoring the scale toward that of a single centrality component.

Everett & Schoch (2022) provide adjacent directed-centrality theory in which in- and out-roles are explicitly coupled, generalizing the hub/authority idea. Kleinberg's HITS provides the classic paired hub-authority precedent.

```{admonition} Provenance claim
:class: important
The exact geometric-mean-and-one-final-L2 rule is a **SIGMA construction**. The literature supports the Katz sender/receiver decomposition and product interpretation; SIGMA takes a monotone square-root rescaling of that product. The documentation therefore does not label “geometric-mean Katz” as an independently published named algorithm.
```

## Why not normalize the two components first?

Normalizing $K^{in}$ and $K^{out}$ separately would inject two graph-wide scale transformations before combination. SIGMA instead preserves their common Katz parameterization, combines the raw magnitudes, and applies one final normalization. This makes the implemented formula exactly the one shown above.

## Edge cases and the eigenvector alternative

Only strictly positive finite X weights enter canonical Katz; negative or non-finite weights are rejected and zero edges are absent from support.

An isolated X center without a tile has no edges; its factor is set to 1 and it is excluded from the degree-area PPML, but remains in Katz and receives the normal baseline. If a center without a tile has any edge, the run stops and reports the inconsistency.

The eigenvector mode (`--centrality-method eigenvector`, used by the legacy `--equivalent` profile) is explicit only. It first forms the positive-weight **undirected projection** of X, summing reciprocal weights, then computes weighted eigenvector centrality. It is retained for compatibility, not as the canonical model, and it does not use the tile-area adjustment.
