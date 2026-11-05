# Economy: transactions, coefficients, and directed structure (stage 13)

*Pipeline stage 13 of 17 · `sigma run`. Under the Hood shows the table, the coefficients and the optional MWAS branch (section “Stage 13”).*

SIGMA separates the economic data definition from the graph used in spatial-economic analysis.

## Transaction table

Let $Z=(z_{ij})$ be the intermediate transaction matrix. Row $i$ is the supplying sector and column $j$ is the purchasing/user sector. Values must be finite and nonnegative with aligned sector axes.

Which table is used depends on the area's selection, recorded by `sigma load` in `economy-selection.json` and followed by `sigma run`:

- **default:** a per-area hierarchical IO240/IO80/IO16 economy (stage 5), aggregated from the validated packaged PSA 2018 IO240 table, and possibly rolled up further by stage 9;
- `--io-level 16`, `80` or `240`: a fixed national resolution;
- `--economy`: a custom code/label/transaction system.

The Python API's `Economy.default()` and a workspace without a recorded selection use the PSA 2018 IO80 table. These are **different defaults for different entry points**, not interchangeable descriptions of the same area run.

## Derived hierarchical economies and colors

`sigma load` records a **baseline** hierarchical partition (stage 5). For a generated hierarchy, `sigma run AREA` produces an **iteratively rolled-up derived economy** (stage 9) when a baseline sector yields no retained HDBSCAN* clusters and a residual merge is accepted; `--no-iterative-rollup` keeps the baseline. The effective economy ID governs how national transactions and outputs are aggregated ($M Z M^\top$, $M x$); X edges and scores correspond to that exact catalog. The original sector code remains auditable but is not an additional row or column of the effective IO matrix.

The 336-color palette is a stable mapping of official IO16, IO80 and IO240 identifiers (and their sparse and tiered forms) to display colors. Residuals use their parent color. The palette is **not** an economic coefficient matrix and never changes the IO calculation.

## Technical coefficients

With total output $x_j$ for user sector $j$, SIGMA uses the preserved input-output convention

$$
a_{ij}=\frac{z_{ij}}{x_j}.
$$

Thus $a_{ij}$ is the amount of input from supplying sector $i$ required per unit of total output of sector $j$.

Every positive effective coefficient generates a directed economic edge $i\to j$. Positive diagonal terms are retained: sector self-use remains legitimate economic structure. Reciprocal edges and directed cycles are also retained by default.

These entries encode national input requirements, **not verified suppliers,
local purchases, or flows between the study area's establishments**. The
current X graph uses the direct coefficient matrix $A$; it does **not** yet
substitute the Leontief inverse $(I-A)^{-1}$ or provide an A-versus-Leontief
analysis toggle. See [The X graph](x_graph.md) for its additional spatial and
cluster-share assumptions.

## Default: no preprocessing

With `transaction_preprocessing="none"`, the effective transaction matrix is the raw transaction matrix, unless a valid explicit coefficient matrix is supplied under the compatibility rules. The canonical economic graph is therefore the **full positive directed technical-coefficient graph**.

## Optional `mwas_ras_fast`

This option exists for large or special IO systems when a sparse support is useful, but it is not the default.

### 1. Greedy fast MWAS proposal

Convert every positive non-self transaction to a directed weighted edge and sort candidate edges by descending transaction weight, using source/target strings only to break equal-weight ties. Starting from an empty graph, accept edge $u\to v$ only when there is not already a path $v\rightsquigarrow u$. The accepted off-diagonal support is therefore acyclic.

This is a deterministic greedy approximation to a maximum-weight acyclic subgraph, not a claim of an exact optimum.

### 2. Restore diagonals and feasibility

All original positive diagonal cells are restored. SIGMA then asks whether nonnegative flows on the proposed support can satisfy the original row and column margins. Feasibility is reduced to a capacitated bipartite max-flow problem.

If support is infeasible, removed original-positive cells are restored in descending raw transaction weight with deterministic source/target ties. SIGMA finds the smallest prefix that restores feasibility. It never invents support where the raw table was zero.

### 3. RAS / iterative proportional fitting

On the final admissible support, alternating row and column scaling seeks a balanced matrix $Z^*$ with

$$
\sum_j z^*_{ij}=\sum_j z_{ij},
\qquad
\sum_i z^*_{ij}=\sum_i z_{ij}.
$$

Default tolerances are absolute $10^{-8}$ and relative $10^{-10}$, with at most 10,000 iterations.

### 4. Recompute coefficients

Technical coefficients are recomputed from the balanced effective table. **MWAS proposal weights are never used as downstream economic weights.**

```{admonition} Why the default remains `none`
:class: note
The optional preprocessor deliberately alters support before restoring IO margins. When there is no computational reason to sparsify, retaining the original directed transaction structure requires fewer modeling assumptions.
```
