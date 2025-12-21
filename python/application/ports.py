from typing import Any, Protocol

import pandas as pd


class PipelineSourcePort(Protocol):
    """Leest pipeline data uit een bron (CSV, API, DB, etc)."""

    def get_latest_pipeline_path(self) -> str: ...

    def load_pipeline(self, path: str) -> pd.DataFrame: ...


class MappingPort(Protocol):
    """Past een CRM-specifieke mapping toe naar canonical kolommen."""

    def apply_mapping(self, df: pd.DataFrame, mapping_path: str) -> pd.DataFrame: ...


class PipelineAnalysisPort(Protocol):
    """Voert core pipeline analyse uit (pure business logic)."""

    def run(
        self,
        df: pd.DataFrame,
        enable_llm: bool,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: ...


class ManagementSnapshotPort(Protocol):
    """Bouwt management JSON snapshot uit analyse-resultaten."""

    def build(
        self,
        ctx: Any,
        active_df: pd.DataFrame,
        bookings_df: pd.DataFrame,
        omitted_df: pd.DataFrame,
        scope: str,
    ) -> dict[str, Any]: ...


class ReportWriterPort(Protocol):
    """Schrijft output artifacts (txt, json, etc)."""

    def write_reports(self, report_text: str, output_dir: str) -> None: ...

    def write_management_data(self, data: dict[str, Any], output_dir: str) -> None: ...


class NextStepHealthScorerPort(Protocol):
    """Verrijkt deals met Next Step health via LLM of andere engine."""

    def enrich(self, deals: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class AeReportBuilderPort(Protocol):
    """Builds the human-readable AE pipeline summary report."""

    def build(
        self,
        ctx: Any,
        active_df: pd.DataFrame,
        bookings_df: pd.DataFrame,
        omitted_df: pd.DataFrame,
    ) -> str: ...