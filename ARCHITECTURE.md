# Dealify Engine – Architectuur (single source of truth)

Complete overzicht van lagen, componenten, functies en wiring, zodat een volgende developer een verdere hexagon-refactor kan doen.

## 1. Doel & principes
- Lokale, file-based sales intelligence pipeline: CSV in → canonicalize → analyse → (optioneel) LLM verrijking → JSON/TXT uit.
- Geen database, stateless per run, deterministisch, local-first (Ollama compatibel).
- Hexagon als structuurdiscipline: ports (contracts), adapters (infra), use cases (app), domain-functies (pandas/LLM/aggregaties).

## 2. Lagen & hoofdflow (as-is)
```
CLI (python/pipeline/pipeline_analyse.py)
  -> Application wiring (python/application/run_pipeline.py)
  -> Use case (PipelineRunUseCase in python/application/workflows/run_pipeline.py)
  -> Ports (python/application/ports.py)
  -> Adapters (python/infrastructure/pipeline/adapters.py)
  -> Domain functies (python/pipeline/*, python/llm/client.py)
  -> Outputs (outputs/*.txt, outputs/*.json)
```

## 3. Componenten per laag (inclusief functies)

### Entrypoints / Presentation
- `python/entrypoints/cli/pipeline_analyse.py`
  - Canonical CLI entrypoint.
  - Parses CLI flags, builds `AnalysisContext`, resolves mapping path and invokes the application layer.
- `python/pipeline/pipeline_analyse.py`
  - Compatibility wrapper that delegates to the canonical CLI entrypoint.
  - Kept temporarily to avoid breaking existing run commands.

### Application (use case + wiring)
- `python/application/run_pipeline.py`
  - `run_pipeline_app(ctx, args, mapping_path)` → `create_default_pipeline_adapters(ctx)` → init `PipelineRunUseCase` → bouw `PipelineRunRequest` → `use_case.execute(ctx, request)`.
  - `run_pipeline(...)` legacy alias.
- `python/application/workflows/run_pipeline.py`
  - `PipelineRunRequest` (mapping_path, output_scope, enable_llm).
  - `PipelineRunUseCase.execute(ctx, request)`:
    1) `source.get_latest_pipeline_path()` → `source.load_pipeline()`
    2) `mapper.apply_mapping(df, mapping_path)`
    3) `analyzer.run(df, enable_llm)`
    4) optional `next_step_scorer` kept injectable (scoring zit nu in analyzer)
    5) `management_builder.build(ctx, active_df, bookings_df, omitted_df, scope)`
    6) `report_builder.build(...)` → `writer.write_reports(...)`; `writer.write_management_data(...)`

### Ports (contracts) – `python/application/ports.py`
- `PipelineSourcePort`: get_latest_pipeline_path(), load_pipeline(path)
- `MappingPort`: apply_mapping(df, mapping_path)
- `PipelineAnalysisPort`: run(df, enable_llm) -> (active_df, bookings_df, omitted_df)
- `ManagementSnapshotPort`: build(ctx, active_df, bookings_df, omitted_df, scope)
- `ReportWriterPort`: write_reports(...), write_management_data(...)
- `NextStepHealthScorerPort`: enrich(deals)
- `AeReportBuilderPort`: build(ctx, active_df, bookings_df, omitted_df)

### Infrastructure adapters & composition – `python/infrastructure/pipeline/adapters.py`

Note: The composition root intentionally lives in the infrastructure layer. The application layer depends only on ports and use cases and does not own adapter construction.

- `PipelineAdapters` dataclass bundelt ports.
- `create_default_pipeline_adapters(ctx)`: composition root; installeert adapters, optioneel LLM scorer bij `ctx.llm_config`.
- Adapters (concrete):
  - `FilePipelineSourceAdapter(data_dir, name_contains="pipeline")`: get_latest_pipeline_path(), load_pipeline(), load_latest_pipeline_dataframe().
  - `JsonMappingAdapter`: apply_mapping(df_raw, mapping_path).
  - `PandasPipelineAnalysisAdapter(ctx)`: run(df, enable_llm, llm_config=None) → `pipeline.analysis.run_analysis`.
  - `DefaultManagementSnapshotAdapter`: build(...) → `pipeline.management.build_management_snapshot`.
  - `DefaultAeReportBuilderAdapter`: build(...) → `pipeline.reports.build_ae_reports`.
  - `FileReportWriterAdapter`: write_reports(output_dir, reports), write_management_data(output_dir, management_data) → calls `pipeline.io.write_reports` / `write_management_data` (as-is signature uses `(output_dir, reports)`, zie io voor huidige signatuur).
  - `OllamaNextStepHealthScorerAdapter(llm_config)`: enrich(deals) → `evaluate_next_steps_batch`.
- `python/application/adapters.py`: bewust leeg (geen bridge, geen re-export).

### Domain / pipeline functies
- `python/pipeline/constants.py`: canonical kolommen (account_name, opportunity_name, stage, forecast_category, amount, close_date, created_date, ae_name, next_steps), afgeleide kolommen (amount_clean, close_date_parsed, stage_class), SF fallback map.
- `python/pipeline/mapping.py`: `load_mapping(mapping_path)` (validate JSON, required), `map_dataframe(df_raw, mapping)` met `_pick_existing_column`, `MappingError`.
- `python/pipeline/analysis.py`: helpers `parse_amount`, `classify_stage`, `extract_health_score`; `run_analysis(ctx, df, enable_llm=True, llm_config=None)` → cleanse amounts, parse close dates, stage class, split active/bookings/omitted op forecast_category, optionele LLM batch via `evaluate_next_steps_batch`, logging + sample stats.
- `python/pipeline/management.py`: fiscal helpers, `build_management_data(ctx, active_df, bookings_df, omitted_df)`, `build_management_snapshot(..., scope)` (scopes: management | extended | full).
- `python/pipeline/management_builders.py`: `_safe_sum_amount`, `_safe_iso`, `build_team_overview`, `build_deals_closing_next_14_days`, `build_quarter_concentration`, `build_discovery_hygiene_alerts`, `build_ae_scorecards`.
- `python/pipeline/reports.py`: `build_ae_reports(ctx, active_df, bookings_df, omitted_df)` → tekstuele AE pipeline summary met hygiene/LLM stats.
- `python/pipeline/io.py`: `get_latest_csv`, `load_csv`, `write_reports(text, output_dir)`, `write_management_data(data, output_dir)`, `write_management_summary(text, output_dir)`, `sanitize_for_json`, helpers for timestamped files.
- `python/pipeline/next_step_health.py`: `load_prompt_template`, `build_prompt`, `call_ollama`, `parse_json_response`, `parse_json_array_response`, `evaluate_next_step`, `evaluate_next_steps_batch` (batch prompt builder, ThreadPoolExecutor, fallbacks).

### LLM utility
- `python/llm/client.py`: centrale LLM runner (`run_llm`), ondersteunt backend `ollama` of `litellm`; payload debug writer; retries/timeouts; helpers `_run_ollama`, `_run_litellm`, `_ollama_cli_available`, `_write_payload`.

### Weekly/ops tools
- `python/weekly/weekly_filter.py`: `build_llm_input` → compacte `weekly_llm_input_latest.json` uit `pipeline_management_data_latest.json` (risico-AE’s, top deals, deals <14d).
- `python/weekly/weekly_management_scan.py`: `build_prompt`, `run_llm`, `save_scan_output`; main verwerkt compact JSON + optionele context file → LLM → `weekly_management_scan_latest.txt`.
- `python/inspect/inspect_management_data.py`: CLI inspectie van management JSON (team, quarter, AE, top10, time buckets).
- `python/scripts/sf_salesforce_dashboard.py`: hulpscript om laatste CSV’s uit ~/Downloads te kopiëren/renamen naar data/.

### Config & assets
- `python/app/config.py`: `load_config` (resolve project_root, data_dir_abs, outputs_dir_abs), `get_llm_config`, `get_path`.
- Assets: `mappings/*.json` (default `salesforce_pipeline.json`), `models/prompt_next_step_health.txt`; data in `data/`, outputs in `outputs/`.

## 4. Dataflow (huidige run)
1) CLI → config + context geladen.  
2) `run_pipeline_app` bouwt adapters + use case.  
3) Use case: find/load CSV → mapping → analyse (pandas, opt. LLM) → management JSON → AE report → schrijf outputs (latest + timestamped).  
4) Weekly flow (optioneel): `weekly_filter` reduceert management JSON → compact weekly JSON → `weekly_management_scan` maakt prompt + LLM output.  

### Visuele weergave (Mermaid)
```mermaid
flowchart TD
    subgraph Entry
        CLI[pipeline_analyse.py]
    end
    subgraph App[Application]
        RP[run_pipeline_app]
        UC[PipelineRunUseCase]
    end
    subgraph Ports
        P1[PipelineSourcePort]
        P2[MappingPort]
        P3[PipelineAnalysisPort]
        P4[NextStepHealthScorerPort (injectable)]
        P5[ManagementSnapshotPort]
        P6[AeReportBuilderPort]
        P7[ReportWriterPort]
    end
    subgraph Infra[Infrastructure adapters\npython/infrastructure/pipeline/adapters.py]
        A1[FilePipelineSourceAdapter]
        A2[JsonMappingAdapter]
        A3[PandasPipelineAnalysisAdapter]
        A4[OllamaNextStepHealthScorerAdapter]
        A5[DefaultManagementSnapshotAdapter]
        A6[DefaultAeReportBuilderAdapter]
        A7[FileReportWriterAdapter]
    end
    subgraph Domain[Domain funcs\npython/pipeline/*]
        D1[io.get_latest_csv/load_csv]
        D2[mapping.load_mapping/map_dataframe]
        D3[analysis.run_analysis (+ optional LLM)]
        D4[next_step_health.evaluate_next_steps_batch]
        D5[management.build_management_snapshot]
        D6[reports.build_ae_reports]
        D7[io.write_reports/write_management_data]
    end
    CLI --> RP --> UC
    UC --> P1 & P2 & P3 & P4 & P5 & P6 & P7
    P1 --> A1 --> D1
    P2 --> A2 --> D2
    P3 --> A3 --> D3
    P4 --> A4 --> D4
    P5 --> A5 --> D5
    P6 --> A6 --> D6
    P7 --> A7 --> D7
    D3 -.->|DataFrames| UC
    D5 --> UC
    D6 --> UC
    UC --> A7
    subgraph Weekly
        WF[weekly_filter -> weekly_llm_input]
        WS[weekly_management_scan -> LLM prompt]
    end
    D7 --> WF --> WS
```

## 5. Ports ↔ adapters ↔ domain (nu)
- `PipelineSourcePort` → `FilePipelineSourceAdapter` → `pipeline.io.get_latest_csv` / `load_csv`.
- `MappingPort` → `JsonMappingAdapter` → `pipeline.mapping.load_mapping` / `map_dataframe`.
- `PipelineAnalysisPort` → `PandasPipelineAnalysisAdapter` → `pipeline.analysis.run_analysis` (LLM scoring nog binnen deze functie).
- `NextStepHealthScorerPort` → `OllamaNextStepHealthScorerAdapter` → `pipeline.next_step_health.evaluate_next_steps_batch` (injecteerbaar, niet gebruikt in use case flow).
- `ManagementSnapshotPort` → `DefaultManagementSnapshotAdapter` → `pipeline.management.build_management_snapshot`.
- `AeReportBuilderPort` → `DefaultAeReportBuilderAdapter` → `pipeline.reports.build_ae_reports`.
- `ReportWriterPort` → `FileReportWriterAdapter` → `pipeline.io.write_reports` / `write_management_data` (let op: adapter signature `(output_dir, reports)` vs. io-signature `(text, output_dir)` as-is).

## 6. Refactor richting volledige hexagon (aanbevolen stappen)
1) **Align writer signatures**: breng `FileReportWriterAdapter` in lijn met `pipeline.io.write_reports(text, output_dir)` of pas io-signatures aan; update use case aanroep (nu `writer.write_reports(report_text, output_dir)` in use case vs. adapter `(output_dir, reports)`).  
2) **LLM uit analyzer halen**: laat `PipelineAnalysisPort` puur data transformeren; gebruik `NextStepHealthScorerPort` expliciet voor verrijking (of aparte use case stap).  
3) **Domain map**: verplaats pure businessfuncties (analysis, mapping, management, reports, health helpers) naar `python/domain/pipeline/` met zo min mogelijk ctx-lekken; pandas/LLM alleen waar nodig.  
4) **Infrastructure opsplitsen**: deel adapters op per concern (io_adapter.py, mapping_adapter.py, analysis_adapter.py, llm_adapter.py, reports_adapter.py) zodat wiring duidelijk blijft.  
5) **Use-case layering**: keep composition in infrastructure or entrypoints; ensure the application layer contains only ports and use cases and has no infrastructure imports.  
6) **Testbaarheid**: voeg gerichte tests per port/use case; mock adapters voor fast tests, separate integration voor pandas/LLM/filesystem.  
7) **Ops/weekly**: houd weekly tools als aparte adapters (consumer van management JSON); evt. nieuwe port voor “ManagementScanPort” als dit first-class flow wordt.  

## 7. Bekende aandachtspunten (as-is)
- Writer signature mismatch (adapter vs. `pipeline.io`): bij refactor expliciet kiezen en e2e run checken.
- Analyzer bevat LLM call; NextStepHealthScorerPort niet gebruikt in flow (wel beschikbaar).
- pandas in domain-functies; acceptabel nu, maar bij strikte hexagon isoleren via adapters of services.
- `python/application/adapters.py` is leeg by design; alle concrete adapters staan in `python/infrastructure/pipeline/adapters.py` (enkelvoudige waarheid).

All processing happens in-memory.

---

## 7. LLM Integration

- LLM usage is optional (`--no-llm`)
- Uses local Ollama models
- LLM logic is isolated in:
  - `next_step_health.py`
  - `NextStepHealthScorerPort`

The core pipeline does **not depend on LLM availability**.

---

## 8. Development Principles

The following rules are enforced during refactoring:

1. One file change at a time
2. Always verify which file is currently edited
3. Ports before adapters
4. No implicit dependencies
5. No refactor without a working run
6. Cleanup (unused imports, linting) is postponed intentionally

---

## 9. Current Refactor Status

Completed:
- All concrete adapters moved to `python/infrastructure/pipeline/adapters.py`
- Composition root (`create_default_pipeline_adapters`) lives in infrastructure
- `PipelineAdapters` dataclass lives in infrastructure
- Application adapters reduced to an empty facade
- Circular imports removed
- Pipeline runs end-to-end with and without LLM

Intentionally empty:
- `python/application/adapters.py` (kept as facade placeholder)

---

## 10. Agreed Next Architectural Step

Introduce an explicit UseCase boundary and reduce application wiring:

1. Promote `PipelineRunUseCase` as the single orchestration entry point
2. Reduce `python/application/run_pipeline.py` to pure wiring or remove it once entrypoints call the use case directly
3. Add minimal port-based tests before any folder-level domain migration

Goal:
- Make business flow explicit and testable
- Prepare for alternative entrypoints (weekly scans, API, scheduler)
- Stabilize the hexagonal boundaries before domain extraction

---

This document reflects the **actual state of the code**, not an aspirational target.
