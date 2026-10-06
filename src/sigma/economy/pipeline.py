"""Managed numerical Economy stages for canonical and optional sparse-table paths."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import networkx as nx
import pandas as pd

from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.errors import EconomyValidationError
from sigma.execution import ExecutionPlanner
from sigma.stages import StageSpec
from sigma.workspace import SigmaWorkspace

from .coefficients import effective_technical_coefficients
from .graph import EconomicGraphResult, build_economic_graph
from .model import Economy
from .preprocess import preprocess_transactions
from .mwas import exact_mwas, fast_mwas, io_network


TransactionPreprocessing = Literal["none", "mwas_ras_fast"]


@dataclass(frozen=True, slots=True)
class EconomyRunConfig:
    """Economic execution policy for canonical and optional sparse-table modes."""

    transaction_preprocessing: TransactionPreprocessing = "none"
    ras_absolute_tolerance: float = 1e-8
    ras_relative_tolerance: float = 1e-10
    ras_max_iterations: int = 10_000
    legacy_mwas_method: Literal["fast", "exact"] | None = None

    def __post_init__(self) -> None:
        mode = str(self.transaction_preprocessing).strip().casefold()
        if mode not in {"none", "mwas_ras_fast"}:
            raise ValueError("transaction_preprocessing must be 'none' or 'mwas_ras_fast'")
        object.__setattr__(self, "transaction_preprocessing", mode)
        absolute = float(self.ras_absolute_tolerance)
        relative = float(self.ras_relative_tolerance)
        iterations = int(self.ras_max_iterations)
        if not math.isfinite(absolute) or not math.isfinite(relative):
            raise ValueError("RAS tolerances must be finite")
        if not (absolute >= 0.0 and relative >= 0.0):
            raise ValueError("RAS tolerances must be non-negative")
        if absolute == 0.0 and relative == 0.0:
            raise ValueError("at least one RAS tolerance must be positive")
        if iterations < 1:
            raise ValueError("ras_max_iterations must be >= 1")
        object.__setattr__(self, "ras_absolute_tolerance", absolute)
        object.__setattr__(self, "ras_relative_tolerance", relative)
        object.__setattr__(self, "ras_max_iterations", iterations)
        legacy = self.legacy_mwas_method
        if legacy is not None:
            legacy = str(legacy).strip().casefold()
            if legacy not in {"fast", "exact"}:
                raise ValueError("legacy_mwas_method must be None, 'fast', or 'exact'")
            if mode != "none":
                raise ValueError("legacy MWAS profile requires transaction_preprocessing='none'")
            object.__setattr__(self, "legacy_mwas_method", legacy)


class EconomyPipeline:
    """Materialize raw/effective transactions, coefficients, and directed graph."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        *,
        economy: Economy,
        config: EconomyRunConfig | None = None,
        progress=None,
    ):
        self.workspace = workspace
        self.economy = economy
        self.config = config or EconomyRunConfig()
        if self.config.transaction_preprocessing == "mwas_ras_fast" and economy.x is None:
            raise EconomyValidationError(
                "mwas_ras_fast requires total output x so A_effective can be recomputed; "
                "an explicit-A-only Economy may use transaction_preprocessing='none' only"
            )
        self.progress = progress
        self.planner = ExecutionPlanner(workspace, self._build_stages(), progress=progress)

    def _build_stages(self) -> dict[str, StageSpec]:
        stages = {
            "economy.definition": StageSpec(
                "economy.definition", (), self._recipe_definition, self._exec_definition
            ),
            "economy.transactions.raw": StageSpec(
                "economy.transactions.raw",
                ("economy.definition",),
                self._recipe_raw,
                self._exec_raw,
            ),
            "economy.transactions.effective": StageSpec(
                "economy.transactions.effective",
                ("economy.transactions.raw",),
                self._recipe_effective,
                self._exec_effective,
            ),
            "economy.coefficients": StageSpec(
                "economy.coefficients",
                ("economy.transactions.effective",),
                self._recipe_coefficients,
                self._exec_coefficients,
            ),
            "economy.graph": StageSpec(
                "economy.graph",
                ("economy.transactions.effective", "economy.coefficients"),
                self._recipe_graph,
                self._exec_graph,
            ),
        }
        if self.config.legacy_mwas_method is not None:
            stages["economy.graph.legacy_mwas"] = StageSpec(
                "economy.graph.legacy_mwas",
                ("economy.transactions.raw", "economy.coefficients"),
                self._recipe_legacy_graph,
                self._exec_legacy_graph,
            )
        return stages

    def _definition_identities(self) -> dict[str, object]:
        e = self.economy
        return {
            "economy_id": e.economy_id,
            "economy_fingerprint": e.economy_fingerprint,
            "sector_fingerprint": e.sector_fingerprint,
            "transaction_fingerprint": e.transaction_fingerprint,
            "output_fingerprint": e.output_fingerprint,
            "coefficient_fingerprint": e.coefficient_fingerprint,
        }

    def _recipe_definition(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "economy.definition",
            implementation_version="economy-definition-v1",
            identities=self._definition_identities(),
        )

    def _recipe_raw(self, planner, deps) -> ArtifactRecipe:
        # Stage ordering still ensures economy.definition exists, but the raw table
        # identity deliberately depends only on the sector universe and Z itself.
        # This lets an x/A-only change reuse an unchanged Z_raw artifact.
        return ArtifactRecipe.build(
            "economy.transactions.raw",
            implementation_version="economy-zraw-v1",
            dependencies={
                "economy.definition": {
                    "sector_fingerprint": self.economy.sector_fingerprint,
                    "transaction_fingerprint": self.economy.transaction_fingerprint,
                }
            },
            identities={
                "sector_fingerprint": self.economy.sector_fingerprint,
                "transaction_fingerprint": self.economy.transaction_fingerprint,
            },
        )

    def _recipe_effective(self, planner, deps) -> ArtifactRecipe:
        parameters: dict[str, object] = {
            "transaction_preprocessing": self.config.transaction_preprocessing
        }
        implementation_version = "economy-preprocess-none-v1"
        if self.config.transaction_preprocessing == "mwas_ras_fast":
            implementation_version = "economy-preprocess-mwas-ras-fast-v1"
            parameters.update(
                {
                    "ras_absolute_tolerance": self.config.ras_absolute_tolerance,
                    "ras_relative_tolerance": self.config.ras_relative_tolerance,
                    "ras_max_iterations": self.config.ras_max_iterations,
                }
            )
        return ArtifactRecipe.build(
            "economy.transactions.effective",
            implementation_version=implementation_version,
            dependencies={"economy.transactions.raw": deps["economy.transactions.raw"]},
            parameters=parameters,
        )

    def _recipe_coefficients(self, planner, deps) -> ArtifactRecipe:
        explicit = (
            self.config.transaction_preprocessing == "none"
            and self.economy.coefficient_fingerprint is not None
        )
        identities: dict[str, object] = {
            "sector_fingerprint": self.economy.sector_fingerprint,
            "coefficient_source": "explicit_matrix" if explicit else "derived_from_total_output",
        }
        if explicit:
            identities["coefficient_fingerprint"] = self.economy.coefficient_fingerprint
        else:
            identities["output_fingerprint"] = self.economy.output_fingerprint
        return ArtifactRecipe.build(
            "economy.coefficients",
            implementation_version="economy-effective-coefficients-v1",
            dependencies={"economy.transactions.effective": deps["economy.transactions.effective"]},
            parameters={"transaction_preprocessing": self.config.transaction_preprocessing},
            identities=identities,
        )

    def _recipe_graph(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "economy.graph",
            implementation_version="directed-economic-graph-v1",
            dependencies={
                "economy.transactions.effective": deps["economy.transactions.effective"],
                "economy.coefficients": deps["economy.coefficients"],
            },
            identities={"sector_fingerprint": self.economy.sector_fingerprint},
        )

    @property
    def analysis_graph_stage(self) -> str:
        return "economy.graph.legacy_mwas" if self.config.legacy_mwas_method else "economy.graph"

    def _recipe_legacy_graph(self, planner, deps) -> ArtifactRecipe:
        method = self.config.legacy_mwas_method
        if method is None:
            raise RuntimeError("legacy MWAS stage requested outside the equivalent profile")
        return ArtifactRecipe.build(
            "economy.graph.legacy_mwas",
            implementation_version="legacy-mwas-graph-v1",
            dependencies={
                "economy.transactions.raw": deps["economy.transactions.raw"],
                "economy.coefficients": deps["economy.coefficients"],
            },
            parameters={"mwas_method": method},
            identities={"sector_fingerprint": self.economy.sector_fingerprint},
        )

    def _exec_legacy_graph(self, planner, recipe, deps, write: ArtifactWrite):
        method = self.config.legacy_mwas_method
        if method is None:
            raise RuntimeError("legacy MWAS stage requested outside the equivalent profile")
        z = _read_matrix(deps["economy.transactions.raw"].path / "transactions.csv")
        a = _read_matrix(deps["economy.coefficients"].path / "technical_coefficients.csv")
        source = io_network(z)
        mwas = fast_mwas(source) if method == "fast" else exact_mwas(source)
        graph = nx.DiGraph()
        graph.add_nodes_from(str(code) for code in z.index)
        rows: list[dict[str, object]] = []
        for u, v in sorted(mwas.graph.edges(), key=lambda edge: (str(edge[0]), str(edge[1]))):
            source_type, target_type = str(u), str(v)
            transaction_value = float(z.loc[source_type, target_type])
            technical_coefficient = float(a.loc[source_type, target_type])
            if transaction_value <= 0 or technical_coefficient <= 0:
                raise EconomyValidationError(
                    f"legacy MWAS edge {source_type!r}->{target_type!r} lacks a positive Z/A value"
                )
            graph.add_edge(
                source_type, target_type,
                transaction_value=transaction_value,
                technical_coefficient=technical_coefficient,
                weight=technical_coefficient,
                mwas_method=method,
            )
            rows.append({
                "source_type": source_type,
                "target_type": target_type,
                "transaction_value": transaction_value,
                "technical_coefficient": technical_coefficient,
                "mwas_method": method,
            })
        pd.DataFrame(rows, columns=[
            "source_type", "target_type", "transaction_value",
            "technical_coefficient", "mwas_method",
        ]).to_csv(
            write.output("io_dag.csv"), index=False, float_format="%.17g", lineterminator="\n"
        )
        metadata = {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "is_dag": True,
            "mwas_method": method,
            "retained_transaction_weight": float(mwas.retained_weight),
            "removed_transaction_weight": float(mwas.removed_weight),
        }
        write.output("graph.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return metadata, {"economic_weight": "technical_coefficient", "legacy_profile": True}

    def _exec_definition(self, planner, recipe, deps, write: ArtifactWrite):
        e = self.economy
        payload = {
            "economy_id": e.economy_id,
            "label": e.label,
            "version": e.version,
            "reference_year": e.reference_year,
            "sectors": [{"code": s.code, "label": s.label} for s in e.sectors],
            "sector_fingerprint": e.sector_fingerprint,
            "transaction_fingerprint": e.transaction_fingerprint,
            "output_fingerprint": e.output_fingerprint,
            "coefficient_fingerprint": e.coefficient_fingerprint,
            "economy_fingerprint": e.economy_fingerprint,
            "provenance": dict(e.provenance),
        }
        write.output("economy.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return ({"sector_count": len(e.sectors)}, {"economy_fingerprint": e.economy_fingerprint})

    def _exec_raw(self, planner, recipe, deps, write: ArtifactWrite):
        z = self.economy.Z_raw
        _write_matrix(write.output("transactions.csv"), z)
        return (
            {
                "sector_count": len(z),
                "nonzero_count": int((z.to_numpy(dtype=float) > 0).sum()),
                "transaction_sum": float(z.to_numpy(dtype=float).sum()),
            },
            {"transaction_fingerprint": self.economy.transaction_fingerprint},
        )

    def _exec_effective(self, planner, recipe, deps, write: ArtifactWrite):
        raw = _read_matrix(deps["economy.transactions.raw"].path / "transactions.csv")
        result = preprocess_transactions(
            raw,
            mode=self.config.transaction_preprocessing,
            ras_absolute_tolerance=self.config.ras_absolute_tolerance,
            ras_relative_tolerance=self.config.ras_relative_tolerance,
            ras_max_iterations=self.config.ras_max_iterations,
        )
        _write_matrix(write.output("transactions_effective.csv"), result.table)
        write.output("preprocessing.json").write_text(
            json.dumps(dict(result.diagnostics), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return (dict(result.diagnostics), {"transaction_preprocessing": self.config.transaction_preprocessing})

    def _exec_coefficients(self, planner, recipe, deps, write: ArtifactWrite):
        z = _read_matrix(
            deps["economy.transactions.effective"].path / "transactions_effective.csv"
        )
        a = effective_technical_coefficients(
            self.economy,
            z,
            transaction_preprocessing=self.config.transaction_preprocessing,
        )
        _write_matrix(write.output("technical_coefficients.csv"), a)
        source = str(a.attrs.get("technical_coefficient_source") or "unknown")
        write.output("coefficients.json").write_text(
            json.dumps(
                {
                    "technical_coefficient_source": source,
                    "transaction_preprocessing": self.config.transaction_preprocessing,
                    "orientation": "A_ij = Z_ij / x_j",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return ({"sector_count": len(a), "coefficient_source": source}, {})

    def _exec_graph(self, planner, recipe, deps, write: ArtifactWrite):
        z = _read_matrix(
            deps["economy.transactions.effective"].path / "transactions_effective.csv"
        )
        a = _read_matrix(deps["economy.coefficients"].path / "technical_coefficients.csv")
        result = build_economic_graph(z, a, self.economy.sectors)
        result.rows.to_csv(
            write.output("economic_graph.csv"),
            index=False,
            float_format="%.17g",
            lineterminator="\n",
        )
        metadata = {
            "node_count": result.graph.number_of_nodes(),
            "edge_count": result.graph.number_of_edges(),
            "self_loop_count": nx.number_of_selfloops(result.graph),
            "is_directed": True,
            "is_dag": nx.is_directed_acyclic_graph(result.graph),
            "edge_weight": "technical_coefficient",
        }
        write.output("graph.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return (metadata, {"economic_weight": "technical_coefficient"})

    def definition(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("economy.definition", force=force)

    def raw_transactions(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("economy.transactions.raw", force=force)

    def effective_transactions(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("economy.transactions.effective", force=force)

    def coefficients(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("economy.coefficients", force=force)

    def graph(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure(self.analysis_graph_stage, force=force)

    def run(self, *, force: bool = False) -> ArtifactRef:
        return self.graph(force=force)

    @staticmethod
    def load_transactions(ref: ArtifactRef) -> pd.DataFrame:
        name = "transactions.csv" if ref.stage == "economy.transactions.raw" else "transactions_effective.csv"
        return _read_matrix(ref.path / name)

    @staticmethod
    def load_coefficients(ref: ArtifactRef) -> pd.DataFrame:
        if ref.stage != "economy.coefficients":
            raise ValueError("ArtifactRef is not an economy.coefficients artifact")
        return _read_matrix(ref.path / "technical_coefficients.csv")

    def load_graph(self, ref: ArtifactRef) -> EconomicGraphResult:
        if ref.stage not in {"economy.graph", "economy.graph.legacy_mwas"}:
            raise ValueError("ArtifactRef is not an economic graph artifact")
        filename = "economic_graph.csv" if ref.stage == "economy.graph" else "io_dag.csv"
        rows = pd.read_csv(
            ref.path / filename,
            dtype=str,
            keep_default_na=False,
        )
        for column in ("transaction_value", "technical_coefficient"):
            rows[column] = rows[column].map(float)
        if "weight" in rows.columns:
            rows["weight"] = rows["weight"].map(float)
        else:
            rows["weight"] = rows["technical_coefficient"]
        graph = nx.DiGraph()
        for sector in self.economy.sectors:
            graph.add_node(sector.code, label=sector.label)
        for row in rows.itertuples(index=False):
            graph.add_edge(
                str(row.source_type),
                str(row.target_type),
                transaction_value=float(row.transaction_value),
                technical_coefficient=float(row.technical_coefficient),
                weight=float(row.weight),
            )
        return EconomicGraphResult(graph, rows)


def _write_matrix(path: Path, frame: pd.DataFrame) -> None:
    out = frame.copy(deep=True)
    out.index = [str(value) for value in out.index]
    out.columns = [str(value) for value in out.columns]
    out.rename_axis("sector").to_csv(
        path,
        float_format="%.17g",
        lineterminator="\n",
    )


def _read_matrix(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if frame.shape[1] < 2:
        raise ValueError(f"economic matrix artifact is invalid: {path}")
    frame = frame.set_index(frame.columns[0])
    frame.index = [str(value) for value in frame.index]
    frame.columns = [str(value) for value in frame.columns]
    # Parse with Python float so the %.17g serialization round-trips IEEE-754
    # values exactly; pandas' fast numeric parser can choose an adjacent float.
    return frame.apply(lambda column: column.map(float)).astype(float)
