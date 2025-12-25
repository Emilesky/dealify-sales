

# Dealify Engine – Architecture

## 1. Purpose

The Dealify Engine is a **local, file-based sales intelligence pipeline** designed to:

- Ingest CRM exports (CSV)
- Canonicalize data via mappings
- Analyze pipeline health, timing and risk
- Optionally enrich deals using a local LLM (Next Step Health)
- Produce management-ready outputs (JSON and TXT)

The system is intentionally:
- **Database-less**
- **Stateless per run**
- **Deterministic**
- **Local-first (Ollama-compatible)**

Each execution is a full pipeline run from input to output.

---

## 2. Key Architectural Decisions

### 2.1 No Database (by design)

- Input: CSV files
- Output: JSON + TXT files
- All processing is in-memory
- No persistence layer required

This simplifies:
- Debugging
- Testing
- Local AI usage
- Later migration to SaaS or DB-backed architectures

A database can be added later **without changing core logic**.

---

### 2.2 Hexagonal Architecture (Ports & Adapters)

The codebase is refactored towards **Hexagonal Architecture** to:

- Separate business logic from infrastructure
- Make flows explicit and testable
- Enable multiple input/output implementations later

Hexagonal architecture is used here as a **structural discipline**, not as an over-engineered framework.

---

## 3. High-Level Architecture

CLI (pipeline_analyse.py)
|
v
Application Layer
(run_pipeline.py → later: UseCase)
|
v
Ports (interfaces)
|
v
Adapters (CSV, Pandas, Ollama, filesystem)

---

## 4. Directory Structure

---

Latest dir structure:
(base) macbookpro@mac DealifyEngine % find python -maxdepth 3 -type d
python
python/ui
python/ui/__pycache__
python/pipeline
python/pipeline/__pycache__
python/llm
python/llm/__pycache__
python/inspect
python/inspect/__pycache__
python/app
python/app/__pycache__
python/__pycache__
python/scripts
python/scripts/__pycache__
python/entrypoints
python/entrypoints/__pycache__
python/entrypoints/cli
python/entrypoints/cli/__pycache__
python/application
python/application/workflows
python/application/workflows/__pycache__
python/application/__pycache__
python/infrastructure
python/infrastructure/pipeline
python/infrastructure/pipeline/__pycache__
python/infrastructure/__pycache__
python/weekly
python/weekly/__pycache__

## 5. Layer Responsibilities

### 5.1 Presentation Layer

**pipeline_analyse.py**

Responsibilities:
- CLI argument parsing
- Build `AnalysisContext`
- Call application-level orchestration

Contains:
- No business logic
- No infrastructure wiring

---

### 5.2 Application Layer

**run_pipeline.py**

Responsibilities:
- Coordinate the pipeline flow
- Call ports only (no concrete implementations)
- Decide *what happens*, not *how*

Current state:
- Acts as a temporary orchestrator
- Will later be replaced by a dedicated UseCase class

---

### 5.3 Ports (Application Contracts)

**ports.py**

Defines *what the application needs*, not *how it is done*.

Examples:
- `PipelineSourcePort`
- `MappingPort`
- `PipelineAnalysisPort`
- `ManagementSnapshotPort`
- `ReportWriterPort`
- `NextStepHealthScorerPort`
- `AeReportBuilderPort`

Rules:
- No pandas imports
- No file system logic
- No LLM logic

---

### 5.4 Adapters (Infrastructure)

**adapters.py**

Concrete implementations of ports:

- CSV file loading
- Pandas-based analysis
- Ollama-based LLM scoring
- File-based output writing

Adapters:
- Depend on external systems
- Are replaceable
- Are wired together explicitly

---

## 6. Data Flow (Current)

1. CLI starts `pipeline_analyse`
2. `AnalysisContext` is constructed
3. `run_pipeline(...)` is called
4. Default adapters are created
5. Pipeline executes:
   - Locate latest CSV
   - Load CSV into DataFrame
   - Apply mapping
   - Run analysis
   - Optionally enrich with LLM
   - Build management snapshot
   - Build AE report
   - Write outputs

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
- Ports defined
- Adapters implemented
- Orchestration extracted from CLI
- End-to-end pipeline works with and without LLM

Pending (next steps):
- Introduce explicit UseCase class
- Reduce `run_pipeline.py` to wiring only
- Add alternative flows (weekly, management-only)
- Optional: add automated tests per port

---

## 10. Next Architectural Step

Introduce a dedicated **Use Case**:

python/application/use_cases/run_pipeline_usecase.py

Goal:
- Make the business flow explicit
- Support multiple execution modes
- Prepare for future extensions (API, scheduling, DB)

---

This document reflects the **actual state of the code**, not an aspirational target.

# Dealify Engine – Architectuur (update t.b.v. Hexagonal refactor)

## Huidige lagen & flow (e2e)
- Entrypoint: python/pipeline/pipeline_analyse.py (CLI) parse args → load config (python/app/config.py) → bouw AnalysisContext → run_pipeline_app.
- Wiring: python/application/run_pipeline.py installeert adapters via python/infrastructure/pipeline/adapters.create_default_pipeline_adapters (re-export van python/application/adapters) → init PipelineRunUseCase (python/application/workflows/run_pipeline.py) → execute().
- Use case: PipelineRunUseCase.execute stappen:
  1) source.get_latest_pipeline_path() + load_pipeline()
  2) mapper.apply_mapping()
  3) analyzer.run() → levert active_df, bookings_df, omitted_df (LLM optioneel)
  4) management_builder.build()
  5) report_builder.build() → writer.write_reports/write_management_data (output_dir uit ctx)
- Data & hulpmiddelen: config.json levert data_dir/outputs_dir + llm_config; mapping JSON default mappings/salesforce_pipeline.json; outputs in outputs/.

## Directory & modules (imports, functies, classes, wiring)
- python/application/ports.py: Protocols: PipelineSourcePort (get_latest_pipeline_path, load_pipeline), MappingPort (apply_mapping), PipelineAnalysisPort (run), ManagementSnapshotPort (build), ReportWriterPort (write_reports/write_management_data), NextStepHealthScorerPort (enrich), AeReportBuilderPort (build). Geen infra imports.
- python/application/adapters.py:
  - Imports: pandas, ports + pipeline.io (get_latest_csv/load_csv/write_reports/write_management_data), pipeline.mapping (load_mapping/map_dataframe), pipeline.analysis.run_analysis, pipeline.management.build_management_snapshot, pipeline.reports.build_ae_reports, pipeline.next_step_health.evaluate_next_steps_batch.
  - Adapters: FilePipelineSourceAdapter, JsonMappingAdapter, PandasPipelineAnalysisAdapter(ctx), DefaultManagementSnapshotAdapter, FileReportWriterAdapter, OllamaNextStepHealthScorerAdapter(llm_config), DefaultAeReportBuilderAdapter.
  - PipelineAdapters dataclass bundelt ports; create_default_pipeline_adapters(ctx) bouwt defaults (LLM scorer optioneel op basis van ctx.llm_config).
- python/infrastructure/pipeline/adapters.py:
  - Re-export PipelineAdapters/create_default_pipeline_adapters uit application/adapters (tijdelijke bridge).
  - FilePipelineSourceAdapter dataclass (name_contains filter) met load_latest_pipeline_dataframe(data_dir) → get_latest_csv/load_csv.
- python/application/workflows/run_pipeline.py:
  - PipelineRunRequest dataclass (mapping_path, output_scope, enable_llm).
  - PipelineRunUseCase met execute() zoals hierboven; vereist alleen ports + ctx/output_dir attribute.
- python/application/run_pipeline.py: Composition root voor CLI; maakt adapters, init PipelineRunUseCase, bouwt PipelineRunRequest uit CLI-args (output_scope, no_llm toggled).
- Entrypoints:
  - python/pipeline/pipeline_analyse.py: CLI parser (--team-target, --bookings-to-date, --mapping, --today, --no-llm, --output-scope); bouwt AnalysisContext (today, data_dir, output_dir, calendar/rules defaults, targets uit env/CLI, llm_config via get_llm_config); bepaalt mapping_path; roept run_pipeline_app.
  - python/entrypoints/cli/pipeline_analyse.py: dunne wrapper naar python.pipeline.pipeline_analyse.main.
- Domein/pipeline logica:
  - python/pipeline/constants.py: canonical kolomnamen + SF_EXPORT_TO_CANONICAL mapping.
  - python/pipeline/mapping.py: load_mapping() (validate JSON, required), map_dataframe(df_raw, mapping) met _pick_existing_column helper; MappingError exceptions.
  - python/pipeline/analysis.py: parse_amount(), classify_stage(), extract_health_score(); run_analysis(ctx, df, enable_llm, llm_config=None) → schoon amount, parse close_date, splits active/bookings/omitted op forecast_category, optionele LLM batch via evaluate_next_steps_batch (Next Step health) met logging/metrics; retourneert drie DataFrames.
  - python/pipeline/management.py: get_fiscal_quarter_bounds(), build_management_data(ctx, active_df, bookings_df, omitted_df) met hygiene/health stats; build_management_snapshot(..., scope) assembleert management JSON (management/extended/full) en roept builders.
  - python/pipeline/management_builders.py: helpers voor extended/full scopes: build_team_overview, build_deals_closing_next_14_days, build_quarter_concentration, build_discovery_hygiene_alerts, build_ae_scorecards (per-AE hygiene/top deals), incl. _safe_sum_amount/_safe_iso.
  - python/pipeline/reports.py: build_ae_reports(ctx, active_df, bookings_df, omitted_df) → tekstuele AE pipeline summary met hygiene/next_step_health stats en slechte next steps.
  - python/pipeline/io.py: get_latest_csv(data_dir, name_contains), load_csv(path), ensure_output_dir(), write_reports(), write_management_data(), write_management_summary(); JSON sanitization via sanitize_for_json.
  - python/pipeline/next_step_health.py: LLM helpers; load_prompt_template(), build_prompt(); call_ollama(prompt, llm_config); parse_json_response/parse_json_array_response; evaluate_next_step(); evaluate_next_steps_batch(deals, next_step_field, llm_config, template) met batching, ThreadPoolExecutor en fout-fallbacks.
- Hulpprocessen:
  - python/weekly/weekly_filter.py: bouwt compacte LLM-input uit pipeline_management_data_latest.json (risico-AE’s, top deals, deals binnen 14d) → weekly_llm_input_latest.json; gebruikt load_config().
  - python/inspect/inspect_management_data.py: CLI inspectie van pipeline_management_data_latest.json (team/quarter/ae/etc).
  - python/app/config.py: load_config() resolveert project_root/data_dir_abs/outputs_dir_abs; get_llm_config() levert LLMConfig (backend/model/timeout/retries/ollama_path); get_path helper.
- Data/artefacten: mappings/salesforce_pipeline.json (default mapping), models/prompt_next_step_health.txt (LLM prompt), outputs/* geschreven door io.py.

## Future-state richting volledige hexagon
- Schil-lagen strak scheiden:
  - Entry adapters: python/entrypoints/cli/* blijft dun; later API/worker adapters naast CLI.
  - Application layer: verhuis wiring/composition naar nieuw python/application/wiring of bootstrap; gebruik use_cases/RunPipelineUseCase als enige coördinator; PipelineRunRequest blijft klein.
  - Ports: laat python/application/ports.py leidend zijn; breid uit met aparte NextStepHealthPort als scoring buiten analysis komt.
- Adapters reorganiseren:
  - Verplaats concrete adapters uit python/application/adapters.py naar python/infrastructure/pipeline/ (submodules: io_adapter.py, mapping_adapter.py, analysis_adapter.py, llm_adapter.py, reports_adapter.py).
  - Maak create_default_pipeline_adapters in infrastructure de enige factory; application/adapters.py kan verdwijnen of alleen façade blijven.
  - Laat analysis adapter enkel de domain-functie aanroepen (zonder ctx-lek); verplaats pandas/LLM dependencies definitief naar infra.
- Domeinlaag consolideren:
  - Introduceer python/domain/pipeline/ voor pure business-functies (parse_amount, classify_stage, aggregation builders) zonder IO/CLI; pas run_pipeline_usecase aan om alleen domain-functies te roepen via adapters.
  - Splits LLM logic in aparte service (NextStepHealthService) zodat analyzer.run enkel DataFrame-in/out zonder subprocess.
- Dependency regels (doel):
  - entrypoints → application (use cases, ports) → domain
  - infrastructure implementeert ports en wordt alleen vanuit wiring ge-importeerd.
  - Geen infra/LLM/OS imports in domain/use_cases.
- Migratiestappen:
  1) Kopieer adapters uit application/adapters.py naar infrastructure/pipeline/* en laat create_default_pipeline_adapters verwijzen naar nieuwe paden.
  2) Pas PipelineRunUseCase aan om NextStepHealthScorerPort expliciet te gebruiken (niet meer verborgen in analyzer).
  3) Trek pipeline/analysis.py en management_builders.py onder domain/; houd pandas afhankelijkheden in domain toegestaan of wikkel in dataframeservice.
  4) Houd python/application/run_pipeline.py puur als composition root; voeg tests per port toe zodra split stabiel is.

