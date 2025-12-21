from python.application.adapters import (
    FilePipelineSourceAdapter,
    JsonMappingAdapter,
    PandasPipelineAnalysisAdapter,
    DefaultManagementSnapshotAdapter,
    FileReportWriterAdapter,
    DefaultAeReportBuilderAdapter,
)


def run_pipeline(ctx, args, mapping_path: str) -> None:
    """
    Application-level pipeline execution.
    Executes the full pipeline flow given a prepared AnalysisContext and CLI args.
    """
    # Instantiate adapters
    source = FilePipelineSourceAdapter(ctx.data_dir)
    mapper = JsonMappingAdapter()
    analyzer = PandasPipelineAnalysisAdapter(ctx)
    snapshot_builder = DefaultManagementSnapshotAdapter()
    report_builder = DefaultAeReportBuilderAdapter()
    writer = FileReportWriterAdapter()

    # Load data
    csv_path = source.get_latest_pipeline_path()
    df = source.load_pipeline(csv_path)

    # Apply mapping
    try:
        df = mapper.apply_mapping(df, mapping_path)
        print("[pipeline] Mapping toegepast. Verwacht canonical kolommen.")
    except Exception as e:
        print("[pipeline][ERROR] Mapping stap faalde, fallback mapping actief.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")

    # Run analysis
    active_df, bookings_df, omitted_df = analyzer.run(
        df,
        enable_llm=not args.no_llm,
    )

    # Build management snapshot
    management_data = snapshot_builder.build(
        ctx,
        active_df,
        bookings_df,
        omitted_df,
        scope=args.output_scope,
    )

    # Build AE report
    report_text = report_builder.build(
        ctx,
        active_df,
        bookings_df,
        omitted_df,
    )
    print("[pipeline] AE-rapport klaar, start schrijven naar files...")

    # Write outputs
    writer.write_reports(report_text, ctx.output_dir)
    writer.write_management_data(management_data, ctx.output_dir)