from python.application.adapters import create_default_pipeline_adapters


class PipelineRunUseCase:
    """Application use case that executes the full pipeline flow."""

    def __init__(
        self,
        source,
        mapper,
        analyzer,
        snapshot_builder,
        report_builder,
        writer,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._analyzer = analyzer
        self._snapshot_builder = snapshot_builder
        self._report_builder = report_builder
        self._writer = writer

    def run(self, ctx, args, mapping_path: str) -> None:
        # Load data
        csv_path = self._source.get_latest_pipeline_path()
        df = self._source.load_pipeline(csv_path)

        # Apply mapping
        try:
            df = self._mapper.apply_mapping(df, mapping_path)
            print("[pipeline] Mapping toegepast. Verwacht canonical kolommen.")
        except Exception as e:
            print("[pipeline][ERROR] Mapping stap faalde. Canonical kolommen mogelijk onvolledig.")
            print(f"[pipeline][ERROR] Exception: {repr(e)}")

        # Run analysis
        active_df, bookings_df, omitted_df = self._analyzer.run(
            df,
            enable_llm=not args.no_llm,
        )

        # Build management snapshot
        management_data = self._snapshot_builder.build(
            ctx,
            active_df,
            bookings_df,
            omitted_df,
            scope=args.output_scope,
        )

        # Build AE report
        report_text = self._report_builder.build(
            ctx,
            active_df,
            bookings_df,
            omitted_df,
        )
        print("[pipeline] AE-rapport klaar, start schrijven naar files...")

        # Write outputs
        self._writer.write_reports(report_text, ctx.output_dir)
        self._writer.write_management_data(management_data, ctx.output_dir)


def run_pipeline(ctx, args, mapping_path: str) -> None:
    """
    Application-level pipeline execution (composition/wiring).
    Creates the use case with concrete adapters and executes it.
    """
    adapters = create_default_pipeline_adapters(ctx)
    use_case = PipelineRunUseCase(
        source=adapters["source"],
        mapper=adapters["mapper"],
        analyzer=adapters["analyzer"],
        snapshot_builder=adapters["snapshot_builder"],
        report_builder=adapters["report_builder"],
        writer=adapters["writer"],
    )
    use_case.run(ctx, args, mapping_path=mapping_path)