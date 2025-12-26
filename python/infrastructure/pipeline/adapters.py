"""Infrastructure adapters for the pipeline.

This module is the home for concrete adapters (file IO, pandas transforms, mapping, analysis, and LLM calls)
and contains the composition root used by the CLI (`create_default_pipeline_adapters`).

The application layer should depend only on ports and use cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from python.application.ports import AeReportBuilderPort, MappingPort, ManagementSnapshotPort, NextStepHealthScorerPort, PipelineAnalysisPort, PipelineSourcePort, ReportWriterPort
from python.pipeline.io import get_latest_csv, load_csv, write_management_data, write_reports
from python.pipeline.mapping import load_mapping, map_dataframe
from python.pipeline.analysis import run_analysis
from python.pipeline.management import build_management_snapshot
from python.pipeline.reports import build_ae_reports
from python.pipeline.next_step_health import evaluate_next_steps_batch

__all__ = [
    "PipelineAdapters",
    "create_default_pipeline_adapters",
    "FilePipelineSourceAdapter",
    "JsonMappingAdapter",
    "PandasPipelineAnalysisAdapter",
    "DefaultManagementSnapshotAdapter",
    "DefaultAeReportBuilderAdapter",
    "FileReportWriterAdapter",
    "OllamaNextStepHealthScorerAdapter",
]


@dataclass
class PipelineAdapters:
    source: PipelineSourcePort
    mapper: MappingPort
    analyzer: PipelineAnalysisPort
    snapshot_builder: ManagementSnapshotPort
    report_builder: AeReportBuilderPort
    writer: ReportWriterPort
    next_step_scorer: NextStepHealthScorerPort | None = None


def create_default_pipeline_adapters(ctx) -> PipelineAdapters:
    """Create the default set of concrete adapters.

    This is the composition point used by the CLI run.
    """

    next_step_scorer = None
    if getattr(ctx, "llm_config", None) is not None:
        next_step_scorer = OllamaNextStepHealthScorerAdapter(ctx.llm_config)

    return PipelineAdapters(
        source=FilePipelineSourceAdapter(data_dir=ctx.data_dir),
        mapper=JsonMappingAdapter(),
        analyzer=PandasPipelineAnalysisAdapter(ctx),
        snapshot_builder=DefaultManagementSnapshotAdapter(),
        report_builder=DefaultAeReportBuilderAdapter(),
        writer=FileReportWriterAdapter(),
        next_step_scorer=next_step_scorer,
    )


class OllamaNextStepHealthScorerAdapter(NextStepHealthScorerPort):
    def __init__(self, llm_config: Any):
        self.llm_config = llm_config

    def enrich(self, deals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return evaluate_next_steps_batch(
            deals,
            llm_config=self.llm_config,
        )


@dataclass
class FilePipelineSourceAdapter(PipelineSourcePort):
    """Load the latest pipeline CSV from the configured data directory."""

    data_dir: str
    name_contains: str = "pipeline"

    def get_latest_pipeline_path(self) -> str:
        csv_path = get_latest_csv(self.data_dir, name_contains=self.name_contains)
        if not csv_path:
            raise FileNotFoundError(
                f"No pipeline CSV found in '{self.data_dir}' (name_contains='{self.name_contains}')"
            )
        return csv_path

    def load_pipeline(self, csv_path: str) -> pd.DataFrame:
        df = load_csv(csv_path)
        if df is None:
            raise ValueError(f"load_csv returned None for path: {csv_path}")
        return df

    def load_latest_pipeline_dataframe(self) -> pd.DataFrame:
        csv_path = self.get_latest_pipeline_path()
        return self.load_pipeline(csv_path)




@dataclass
class JsonMappingAdapter(MappingPort):
    """Apply a JSON mapping file to a raw pipeline dataframe."""

    def apply_mapping(self, df_raw: pd.DataFrame, mapping_path: str) -> pd.DataFrame:
        mapping = load_mapping(mapping_path)
        return map_dataframe(df_raw, mapping)



@dataclass
class PandasPipelineAnalysisAdapter(PipelineAnalysisPort):
    """Run the pipeline analysis using the pandas-based domain function."""

    ctx: object

    def run(self, df: pd.DataFrame, enable_llm: bool, llm_config=None):
        result = run_analysis(self.ctx, df, enable_llm=enable_llm, llm_config=llm_config)
        if result is None:
            raise ValueError("run_analysis returned None")
        return result


@dataclass
class DefaultManagementSnapshotAdapter(ManagementSnapshotPort):
    """Build management snapshot JSON using the domain builder."""

    def build(self, *args, **kwargs):
        result = build_management_snapshot(*args, **kwargs)
        if result is None:
            raise ValueError("build_management_snapshot returned None")
        return result


@dataclass
class DefaultAeReportBuilderAdapter(AeReportBuilderPort):
    """Build AE report text outputs using the domain builder."""

    def build(self, *args, **kwargs):
        result = build_ae_reports(*args, **kwargs)
        if result is None:
            raise ValueError("build_ae_reports returned None")
        return result


@dataclass
class FileReportWriterAdapter(ReportWriterPort):
    """Write management JSON and AE report TXT files to the output directory."""

    def write_reports(self, report_text: str, output_dir: str) -> None:
        """Write the human-readable pipeline report to disk."""

        write_reports(report_text, output_dir)

    def write_management_data(self, management_data: dict, output_dir: str) -> None:
        """Write the management snapshot JSON to disk."""

        write_management_data(management_data, output_dir)
