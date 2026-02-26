"""Application workflow: run the CRM pipeline analysis.

This module contains the use case (application-layer orchestration) for running the pipeline.
It must only depend on application-level ports (interfaces) and simple data structures.

No concrete adapters, no pandas, no filesystem paths, no CLI parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from python.application.ports import (
    AeReportBuilderPort,
    ManagementSnapshotPort,
    MappingPort,
    NextStepHealthScorerPort,
    PipelineAnalysisPort,
    PipelineSourcePort,
    ReportWriterPort,
)


@dataclass(frozen=True)
class PipelineRunRequest:
    """Input for the Run Pipeline workflow.

    Kept intentionally small: entrypoints may pass richer objects, but the workflow should
    only require what it truly needs.
    """

    mapping_path: str
    output_scope: str
    enable_llm: bool


class PipelineRunUseCase:
    """Run the pipeline end-to-end using injected ports."""

    def __init__(
        self,
        *,
        source: PipelineSourcePort,
        mapper: MappingPort,
        analyzer: PipelineAnalysisPort,
        next_step_scorer: NextStepHealthScorerPort | None,
        management_builder: ManagementSnapshotPort,
        report_builder: AeReportBuilderPort,
        writer: ReportWriterPort,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._analyzer = analyzer
        self._next_step_scorer = next_step_scorer
        self._management_builder = management_builder
        self._report_builder = report_builder
        self._writer = writer

    def execute(self, ctx: Any, request: PipelineRunRequest) -> None:
        # 1) Read raw data
        pipeline_path = self._source.get_latest_pipeline_path()
        df = self._source.load_pipeline(pipeline_path)

        # 2) Map raw columns to canonical columns
        df = self._mapper.apply_mapping(df, mapping_path=request.mapping_path)

        # 3) Analyze / transform
        # Analysis should be deterministic and free of external side effects.
        # LLM enrichment is orchestrated explicitly in the use case (step 4).
        active_df, bookings_df, omitted_df = self._analyzer.run(
            df,
            enable_llm=False,
        )

        # 4) Optional: LLM enrichment (explicit orchestration)
        if request.enable_llm:
            if self._next_step_scorer is None:
                raise ValueError(
                    "LLM enrichment requested (enable_llm=True) but no NextStepHealthScorerPort was provided. "
                    "Ensure ctx.llm_config is set so the composition root can inject a scorer."
                )

            # Convert to records, enrich, then write enrichment fields back onto the dataframe.
            # Note: we avoid importing pandas here; we only rely on the DataFrame protocol used at runtime.
            records = active_df.to_dict(orient="records")
            if not records:
                # Nothing to enrich
                enriched = []
            else:
                enriched = self._next_step_scorer.enrich(records)

            if len(enriched) != len(records):
                raise ValueError(
                    f"LLM enrichment returned {len(enriched)} records for {len(records)} input records."
                )

            if not enriched:
                enrichment_columns = set()
            else:
                original_columns = set(getattr(active_df, "columns", []))
                enrichment_columns = {
                    k
                    for k in enriched[0].keys()
                    if k not in original_columns
                    or k
                    in {
                        "next_step_health",
                        "next_step_health_score",
                        "next_step_health_rationale",
                        "next_step_health_json",
                    }
                }

            for col in sorted(enrichment_columns):
                active_df[col] = [row.get(col) for row in enriched]

        # 5) Build management JSON
        management_data = self._management_builder.build(
            ctx,
            active_df,
            bookings_df,
            omitted_df,
            scope=request.output_scope,
        )

        # 6) Build and write reports
        output_dir = getattr(ctx, "output_dir", None) or "outputs"

        report_text = self._report_builder.build(ctx, active_df, bookings_df, omitted_df)
        self._writer.write_reports(report_text, output_dir)
        self._writer.write_management_data(management_data, output_dir)
