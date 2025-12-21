from typing import Protocol, List, Dict, Any, Tuple
import pandas as pd


class PipelineSourcePort(Protocol):
    """Leest pipeline- en bookingsdata uit een bron (CSV, API, DB, etc)."""

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
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: ...


class ManagementSnapshotPort(Protocol):
    """Bouwt management JSON snapshot uit analyse-resultaten."""

    def build(
        self,
        ctx: Any,
        active_df: pd.DataFrame,
        bookings_df: pd.DataFrame,
        omitted_df: pd.DataFrame,
        scope: str,
    ) -> Dict[str, Any]: ...


class ReportWriterPort(Protocol):
    """Schrijft output artifacts (txt, json, etc)."""

    def write_reports(self, report_text: str, output_dir: str) -> None: ...
    def write_management_data(self, data: Dict[str, Any], output_dir: str) -> None: ...


class NextStepHealthScorerPort(Protocol):
    """Verrijkt deals met Next Step health via LLM of andere engine."""

    def enrich(
        self,
        deals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]: ...


class AeReportBuilderPort(Protocol):
    """Builds the human-readable AE pipeline summary report."""

    def build(
        self,
        ctx: Any,
        active_df: pd.DataFrame,
        bookings_df: pd.DataFrame,
        omitted_df: pd.DataFrame,
    ) -> str: ...