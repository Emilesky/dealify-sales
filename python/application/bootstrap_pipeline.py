from python.infrastructure.pipeline.pipeline_adapters import create_default_pipeline_adapters
from python.application.workflows.run_pipeline import PipelineRunUseCase, PipelineRunRequest


def run_pipeline_app(ctx, args, mapping_path: str) -> None:
    """Application-level pipeline execution (composition/wiring)."""

    adapters = create_default_pipeline_adapters(ctx)

    use_case = PipelineRunUseCase(
        source=adapters.source,
        mapper=adapters.mapper,
        analyzer=adapters.analyzer,
        next_step_scorer=adapters.next_step_scorer,
        management_builder=adapters.snapshot_builder,
        report_builder=adapters.report_builder,
        writer=adapters.writer,
    )

    request = PipelineRunRequest(
        mapping_path=mapping_path,
        output_scope=args.output_scope,
        enable_llm=not args.no_llm,
    )

    use_case.execute(ctx, request)


def run_pipeline(ctx, args, mapping_path: str) -> None:
    """Backward-compatible wrapper. Prefer `run_pipeline_app`."""

    run_pipeline_app(ctx, args, mapping_path=mapping_path)