from python.pipeline.mapping import load_mapping, map_dataframe
from python.pipeline.analysis import run_analysis
from python.pipeline.constants import (
    COL_ACCOUNT,
    COL_OPPORTUNITY,
    COL_STAGE,
    COL_FORECAST_CATEGORY,
    COL_AMOUNT,
    COL_CLOSE_DATE,
    COL_CREATED_DATE,
    COL_AE,
    COL_NEXT_STEPS,
    SF_EXPORT_TO_CANONICAL,
)
from python.pipeline.io import get_latest_csv, load_csv, write_reports, write_management_data
from python.pipeline.reports import build_ae_reports
from python.pipeline.management import build_management_snapshot


def run_pipeline(ctx, args, mapping_path: str) -> None:
    """
    Application-level pipeline execution.
    Executes the full pipeline flow given a prepared AnalysisContext and CLI args.
    """

    csv_path = get_latest_csv(ctx.data_dir, name_contains="pipeline")
    df = load_csv(csv_path)

    mapping_applied = False
    try:
        mapping = load_mapping(mapping_path)
        df = map_dataframe(df, mapping)
        mapping_applied = True
        print("[pipeline] Mapping toegepast. Verwacht canonical kolommen.")
    except Exception as e:
        print("[pipeline][ERROR] Mapping stap faalde. Probeer Salesforce export te canonicalizen via fallback mapping.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")

    if not mapping_applied:
        df = df.rename(columns={k: v for k, v in SF_EXPORT_TO_CANONICAL.items() if k in df.columns})
        required = (
            COL_ACCOUNT,
            COL_OPPORTUNITY,
            COL_STAGE,
            COL_FORECAST_CATEGORY,
            COL_AMOUNT,
            COL_CLOSE_DATE,
            COL_CREATED_DATE,
            COL_AE,
            COL_NEXT_STEPS,
        )
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"[pipeline][WAARSCHUWING] Niet alle canonical kolommen aanwezig na fallback canonicalize: {missing}")

    active_df, bookings_df, omitted_df = run_analysis(ctx, df, enable_llm=not args.no_llm)

    management_data = build_management_snapshot(
        ctx,
        active_df,
        bookings_df,
        omitted_df,
        scope=args.output_scope,
    )

    report_text = build_ae_reports(ctx, active_df, bookings_df, omitted_df)
    print("[pipeline] AE-rapport klaar, start schrijven naar files...")

    write_reports(report_text, ctx.output_dir)
    write_management_data(management_data, ctx.output_dir)