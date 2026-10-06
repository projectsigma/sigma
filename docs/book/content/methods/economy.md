# Economy: transactions, coefficients, and directed structure

SIGMA separates the economic data definition from the graph used in spatial-economic analysis.

## Transaction table

Let $Z=(z_{ij})$ be the intermediate transaction matrix. Row $i$ is the supplying sector and column $j$ is the purchasing/user sector. Values must be finite and nonnegative with aligned sector axes.

The default built-in economy is PSA 2018 IO80. IO16 and custom code/label/transaction systems are supported.

## Technical coefficients

With total output $x_j$ for user sector $j$, SIGMA uses the preserved input-output convention

$$
a_{ij}=\frac{z_{ij}}{x_j}.
$$

Thus $a_{ij}$ is the amount of input from supplying sector $i$ required per unit of total output of sector $j$.

Every positive effective coefficient generates a directed economic edge $i\to j$. Positive diagonal terms are retained: sector self-use remains legitimate economic structure. Reciprocal edges and directed cycles are also retained by default.

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
