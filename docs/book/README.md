# SIGMA Jupyter Book

This directory is the source for the SIGMA GitHub Pages methodological documentation.

Build locally with:

```bash
python -m pip install -e ".[docs]"
jupyter-book build docs/book
```

The built site is written to `docs/book/_build/html`.

The GitHub Actions workflow in `.github/workflows/deploy_docs.yml` builds this book and deploys it through GitHub Pages on pushes to `main` that affect documentation, source code, configuration, or the workflow itself.
