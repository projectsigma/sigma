# Balanced sender-receiver Katz centrality

Canonical SIGMA centrality preserves the full directed X graph and asks a node to be important in **both** directions: it should be able to receive weighted influence through incoming structure and to send influence through outgoing structure.

This is implemented by computing two raw Katz vectors, taking their nodewise geometric mean, and normalizing only once after combination.

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
s=\max\left(1,\max_i\sum_j W_{ij}\right),\qquad
\alpha=\frac{0.85}{s}.
$$

The same conservative row-sum bound is used if the sparse spectral-radius solver fails. A graph with no edges uses scale 1.

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

## Edge cases and legacy alternative

Only strictly positive finite X weights enter canonical Katz; negative or non-finite weights are rejected and zero edges are absent from support.

The previous eigenvector mode remains explicit. It first forms the positive-weight **undirected projection** of X, summing reciprocal weights, then computes weighted eigenvector centrality. It is retained for compatibility, not as the canonical model.
