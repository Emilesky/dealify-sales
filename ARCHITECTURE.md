

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

python/
├── application/
│   ├── ports.py              # Interfaces (contracts)
│   ├── adapters.py           # Concrete implementations
│   ├── run_pipeline.py       # Temporary orchestrator
│
├── pipeline/
│   ├── pipeline_analyse.py   # CLI entrypoint
│   ├── analysis.py           # Core pipeline analysis
│   ├── mapping.py            # CSV → canonical mapping
│   ├── constants.py
│   ├── io.py                 # File I/O
│   ├── management.py
│   ├── management_builders.py
│   ├── reports.py
│   ├── next_step_health.py   # LLM enrichment
│
├── weekly/
│   └── weekly_filter.py

---

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


