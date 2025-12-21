from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import pandas as pd

from python.application.ports import (
    PipelineSourcePort,
    MappingPort,
    PipelineAnalysisPort,
    ManagementSnapshotPort,
    ReportWriterPort,
    NextStepHealthScorerPort,
    AeReportBuilderPort,
)

from python.pipeline.io import get_latest_csv, load_csv, write_reports, write_management_data
from python.pipeline.mapping import load_mapping, map_dataframe
from python.pipeline.analysis import run_analysis
from python.pipeline.management import build_management_snapshot
from python.pipeline.reports import build_ae_reports
from python.pipeline.next_step_health import evaluate_next_steps_batch


class FilePipelineSourceAdapter(PipelineSourcePort):
    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def get_latest_pipeline_path(self) -> str:
        return get_latest_csv(self.data_dir, name_contains="pipeline")

    def load_pipeline(self, path: str) -> pd.DataFrame:
        return load_csv(path)


class JsonMappingAdapter(MappingPort):
    def apply_mapping(self, df: pd.DataFrame, mapping_path: str) -> pd.DataFrame:
        mapping = load_mapping(mapping_path)
        return map_dataframe(df, mapping)


class PandasPipelineAnalysisAdapter(PipelineAnalysisPort):
    def __init__(self, ctx: Any):
        self.ctx = ctx

    def run(
        self,
        df: pd.DataFrame,
        enable_llm: bool,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        return run_analysis(self.ctx, df, enable_llm=enable_llm)


class DefaultManagementSnapshotAdapter(ManagementSnapshotPort):
    def build(
        self,
        ctx: Any,
        active_df: pd.DataFrame,
        bookings_df: pd.DataFrame,
        omitted_df: pd.DataFrame,
        scope: str,
    ) -> Dict[str, Any]:
        return build_management_snapshot(
            ctx,
            active_df,
            bookings_df,
            omitted_df,
            scope=scope,
        )


class FileReportWriterAdapter(ReportWriterPort):
    def write_reports(self, report_text: str, output_dir: str) -> None:
        write_reports(report_text, output_dir)

    def write_management_data(self, data: Dict[str, Any], output_dir: str) -> None:
        write_management_data(data, output_dir)


class OllamaNextStepHealthScorerAdapter(NextStepHealthScorerPort):
    def __init__(self, llm_config):
        self.llm_config = llm_config

    def enrich(self, deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return evaluate_next_steps_batch(
            deals,
            llm_config=self.llm_config,
        )


class DefaultAeReportBuilderAdapter(AeReportBuilderPort):
    def build(
        self,
        ctx: Any,
        active_df: pd.DataFrame,
        bookings_df: pd.DataFrame,
        omitted_df: pd.DataFrame,
    ) -> str:
        return build_ae_reports(ctx, active_df, bookings_df, omitted_df)

@dataclass
class PipelineAdapters:
    source: PipelineSourcePort
    mapper: MappingPort
    analyzer: PipelineAnalysisPort
    snapshot_builder: ManagementSnapshotPort
    report_builder: AeReportBuilderPort
    writer: ReportWriterPort

def create_default_pipeline_adapters(ctx: Any) -> PipelineAdapters:
    """Create the default concrete adapters implementing the application ports.

    This is a small composition helper so wiring can move out of the use case later
    without changing the underlying adapters.
    """

    return PipelineAdapters(
        source=FilePipelineSourceAdapter(ctx.data_dir),
        mapper=JsonMappingAdapter(),
        analyzer=PandasPipelineAnalysisAdapter(ctx),
        snapshot_builder=DefaultManagementSnapshotAdapter(),
        report_builder=DefaultAeReportBuilderAdapter(),
        writer=FileReportWriterAdapter(),
    )