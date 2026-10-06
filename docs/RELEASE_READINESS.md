# Release readiness

SIGMA is currently `0.1.0.dev0`.

The codebase is suitable for private development use. Stable `0.1.0` promotion should wait until a
representative real-area run is completed in an environment with all declared runtime dependencies,
using the **default managed Geofabrik road source**.

Before stable promotion, verify:

1. a clean install from the built wheel;
2. `sigma doctor` and `sigma classification-check`;
3. the complete automated test suite;
4. one representative real-area end-to-end run with managed Geofabrik roads;
5. an identical rerun that reuses valid artifacts;
6. a `transaction_preprocessing: none -> mwas_ras_fast` change that recomputes only the intended
   economy/analysis/export descendants; and
7. final source/data attribution and proprietary-code licensing review.

Historical construction checkpoint logs are intentionally not part of the product repository. Git
history and the active test suite are the ongoing record of implementation changes and regressions.
