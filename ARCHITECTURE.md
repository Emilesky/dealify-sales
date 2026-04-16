# Architecture

## Current intent

DealifyEngine is evolving toward a stricter hexagonal architecture.
The practical rule is:

- outer adapters collect input or expose output
- config loading stays outside the business core
- deterministic business rules stay in dedicated business-logic modules
- optional LLM usage remains supporting infrastructure only

The system is local, file-based, and deterministic by default.

## Layer model

### Outer adapters

Examples:

- CLI entrypoints such as [`python/pipeline/pipeline_analyse.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/pipeline/pipeline_analyse.py)
- optional UI adapters such as [`python/ui/weekly_attention_config_app.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/ui/weekly_attention_config_app.py)

Responsibilities:

- parse user input
- call existing application or business functions
- expose outputs to files or UI

Must not:

- derive business signals inline
- aggregate AE metrics inline
- determine actions inline
- reinterpret config into decision logic

### Config boundary

Files:

- [`python/app/config.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/app/config.py)
- [`python/app/weekly_attention_config.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/app/weekly_attention_config.py)

Responsibilities:

- resolve paths
- load raw config files
- map loaded values into typed config structures

Must not:

- derive signals
- compute pressure, rescue potential, or execution risk
- determine actions

Note:

- `python/app/config.py` currently contains fallback values for missing Weekly AE Attention config fields.
- These are tolerated loader defaults for now, not a target pattern for future business logic growth.

### Business-logic slice

Current pragmatic location:

- [`python/pipeline/weekly_attention_signals.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/pipeline/weekly_attention_signals.py)
- [`python/pipeline/weekly_attention_engine.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/pipeline/weekly_attention_engine.py)

Responsibilities:

- deterministic per-deal signal derivation
- deterministic AE-level aggregation
- deterministic action mapping

Must not:

- load files directly
- write files directly
- depend on Streamlit
- depend on CLI internals

Important:

- These files live under `python/pipeline/` as a pragmatic source location only.
- They should be treated as dedicated business slices, not as general pipeline helpers.
- If the repository later gains a stable `python/domain/` or real source-backed `python/application/` business package, these modules can be moved there.

## Weekly AE Attention slice

The current deterministic slice is:

1. config boundary
2. per-deal signals
3. AE aggregation
4. action mapping
5. additive output exposure

### Per-deal signals

Current file:

- [`python/pipeline/weekly_attention_signals.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/pipeline/weekly_attention_signals.py)

Current scope:

- `close_this_week`
- `close_this_quarter`
- `forecast_priority`
- `amount_weight`
- `missing_next_step_flag`
- `next_step_health_score`
- `next_step_health_band`
- `poor_next_step_flag`
- `execution_risk_flag`
- `attention_value`

### AE aggregation

Current file:

- [`python/pipeline/weekly_attention_engine.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/pipeline/weekly_attention_engine.py)

Current aggregate fields include:

- `gap_to_target`
- `gap_to_verbal`
- `bookings_to_date`
- `commit_value_this_week`
- `green_upside_value_this_week`
- `pipeline_value_this_week`
- `pipeline_value_this_quarter`
- `poor_next_step_value`
- `poor_next_step_commit_value`
- `missing_next_step_value_this_week`
- `count_risk_deals_this_week`
- `count_risk_deals_this_quarter`
- `concentration_top_deals`
- `coverage_vs_gap`
- `avg_next_step_health`

### Action mapping

Current actions:

- `NO_ACTION`
- `MONITOR`
- `AE_ATTENTION`
- `MANAGER_ATTENTION`
- `URGENT_MANAGER_ATTENTION`

Guardrails:

- next-step health is supporting only
- unknown next-step health must degrade safely
- weekly and quarterly urgency must stay explicit
- supporting next-step signals must not alone determine the outcome

## Streamlit UI

Current file:

- [`python/ui/weekly_attention_config_app.py`](/Users/macbookpro/Automations-Projects-AI/DealifyEngine/python/ui/weekly_attention_config_app.py)

Role:

- outer adapter only
- writes config files for the engine

It may:

- collect user input
- perform basic validation
- write:
  - `data/weekly_attention/ae_inputs.csv`
  - `data/weekly_attention/settings.json`

It must not:

- derive signals
- aggregate AE metrics
- determine actions
- run the pipeline automatically

## Runtime file model

Weekly AE Attention runtime config files:

- `data/weekly_attention/ae_inputs.csv`
- `data/weekly_attention/settings.json`

Template files committed to the repo:

- `data/weekly_attention/ae_inputs.template.csv`
- `data/weekly_attention/settings.template.json`

Runtime files are ignored in git.
Template files remain committable.

## Current architectural caution

The Weekly AE Attention slice is now present end-to-end, but the repository is still transitional.

Known compromises:

- business modules currently live under `python/pipeline/`
- loader fallback values still live in `python/app/config.py`

These compromises are acceptable for now only if:

- business logic does not spread further into config loading
- business logic does not move into UI, CLI, or report builders
- new growth continues to respect the current dedicated slice boundaries
