# Publishing the SIGMA Jupyter Book on GitHub Pages

The repository now contains a Jupyter Book at `docs/book/` and an official GitHub Pages workflow at `.github/workflows/deploy_docs.yml`.

## Local preview

Install the documentation extra and build the book:

```powershell
python -m pip install -e ".[docs]"
jupyter-book build docs/book
```

Open:

```text
docs/book/_build/html/index.html
```

## Publish on GitHub

Commit and push the repository to `projectsigma/sigma` on branch `main`.

Then, once for the repository:

1. Open **Settings** → **Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Open the **Actions** tab and run **Build and deploy SIGMA documentation** if the push did not already trigger it.
4. After a successful deployment, the site will be available at `https://projectsigma.github.io/sigma/`.

The workflow rebuilds when `docs/book/`, `src/sigma/`, `pyproject.toml`, or the documentation workflow changes, so method documentation can track code changes.

## Documentation architecture

`docs/book/_toc.yml` defines the navigation. The book is organized as:

- Start here: quickstart, full workflow, notation;
- Geospatial ecosystem construction: places, roads, HDBSCAN*, centers, network Voronoi;
- Economic and spatial-economic network: IO economy, X graph, balanced Katz, point scoring;
- Reproducibility and interpretation: artifact recipes, defaults, outputs, method lineage; and
- consolidated references.

The mathematical pages describe the implementation rather than a hypothetical design. Recovery paths and SIGMA-specific rules are labeled explicitly.
