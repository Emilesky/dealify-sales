Salesforce AI Sales Intelligence

Lokale Python-based AI sales intelligence tool voor het analyseren van CRM-exportdata (CSV) en het genereren van wekelijkse managementinzichten met behulp van een LLM (Ollama of SaaS).

De tool is CRM-agnostisch, config-driven en ontworpen om later eenvoudig te embedden in een web app of SaaS.

⸻

Projectstructuur

DealifyEngine/
├─ config.json                 # Centrale configuratie (paths, LLM, calendar, rules)
├─ data/                       # Ruwe input (CSV exports)
├─ logs/                       # Run-logs (optioneel)
├─ mappings/                   # Mapping van CRM-export naar canonieke velden
├─ models/                     # Prompts/templates (bijv. prompt_next_step_health.txt)
├─ outputs/                    # Gegenereerde outputs (JSON, TXT)
├─ python/
│  ├─ app/
│  │  └─ config.py
│  ├─ llm/
│  │  └─ client.py
│  ├─ pipeline/                # Analyse + managementdata builders
│  │  ├─ analysis.py
│  │  ├─ constants.py
│  │  ├─ io.py
│  │  ├─ management.py
│  │  ├─ management_builders.py
│  │  ├─ mapping.py
│  │  ├─ next_step_health.py
│  │  ├─ pipeline_analyse.py
│  │  └─ reports.py
│  ├─ weekly/
│  │  ├─ weekly_filter.py
│  │  ├─ management_summary.py
│  │  └─ weekly_management_scan.py
│  ├─ inspect/
│  │  └─ inspect_management_data.py
│  ├─ scripts/
│  │  └─ sf_salesforce_dashboard.py
│  └─ ui/                      # (placeholder)
├─ migrate_project_structure.py
└─ README.md


⸻

Setup

Python environment

Aanbevolen: conda

conda create -n crm-ai python=3.11
conda activate crm-ai

Installeer dependencies (voorbeeld):

pip install pandas python-dateutil


⸻

Configuratie (config.json)

Voorbeeld:

{
  "paths": {
    "data_dir": "data",
    "outputs_dir": "outputs"
  },
  "llm": {
    "backend": "ollama",
    "model": "llama3.1:8b",
    "timeout_sec": 180,
    "retries": 1,
    "ollama_path": "/usr/local/bin/ollama",
    "payload_debug_file": "outputs/llm_payload_latest.txt",
    "litellm": {
      "provider": "openai",
      "api_key": "",
      "api_base": ""
    }
  },
  "run": {
    "verbose": true,
    "target": 4500000,
    "bookings_to_date": 1400000
  },
  "calendar": {
    "fiscal_year_start_month": 2,
    "fiscal_year_start_day": 1
  },
  "rules": {
    "horizon_days_short": 14,
    "horizon_days_medium": 30,
    "next_step_low_score_threshold": 5.0
  }
}

Belangrijk:
	•	paden worden dynamisch als absolute paden ingevuld vanuit config.json (data_dir_abs, outputs_dir_abs)
	•	Geen paden worden afgeleid uit __file__
	•	LLM-config wordt centraal geïnjecteerd

⸻

End-to-end flow

1. Pipeline analyse

Leest pipeline- en bookings-CSV’s en genereert managementdata.

python -m python.pipeline.pipeline_analyse

Output:
	•	outputs/pipeline_management_data_latest.json

⸻

2. Weekly filter

Filtert managementdata naar compacte LLM-input voor de week (risico account managers, topdeals, deals met close binnen 14 dagen).

python -m python.weekly.weekly_filter

Output:
	•	outputs/weekly_llm_input_latest.json

⸻

3. Weekly management scan (LLM)

Genereert een kritische management-level managementanalyse op basis van weekly_llm_input_latest.json (+ optionele contextfile).
Schrijft zowel een latest als timestamped variant.

python -m python.weekly.weekly_management_scan

Optioneel extra context:

python -m python.weekly.weekly_management_scan --context-file extra_context.txt

Output:
	•	outputs/weekly_management_scan_latest.txt
	•	Timestamped variant per run

⸻

Management summary helper (optioneel)

Genereer een samenvatting via Ollama op basis van het Accountmanager-rapport + management JSON.

python -m python.weekly.management_summary

Schrijft payload debug naar outputs/last_llm_payload.txt; gebruikt model uit config of CLI override.

⸻

4. Inspect / debug

Inspecteer managementdata of sanity-check JSON.

python -m python.inspect.inspect_management_data --team

Of met expliciet bestand:

python -m python.inspect.inspect_management_data --file /pad/naar/json --team


⸻

Scripts (ingest / automation)

Scripts in python/scripts/ zijn niet bedoeld om geïmporteerd te worden.
Ze verzorgen alleen aanvoer, bijvoorbeeld:
	•	CSV’s uit Downloads kopiëren
	•	Selenium exports
	•	Bestanden normaliseren naar data/

Voorbeeld:

python -m python.scripts.sf_salesforce_dashboard

Analysecode leest altijd uit data/, nooit direct uit Downloads.

⸻

Ontwerpprincipes
	•	Config-driven (geen magic paths)
	•	Pipeline injecteert config in executors
	•	Geen LLM-calls via subprocess buiten de LLM-laag
	•	Verplaatsbare modules
	•	CLI-first, later API/SaaS-ready

⸻

Troubleshooting

No module named python.xxx
	•	Check of je project root (DealifyEngine) als folder geopend is
	•	Controleer of __init__.py aanwezig is in subfolders
	•	Gebruik altijd python -m python.<module>

outputs_dir_abs ontbreekt
	•	Voeg "paths.outputs_dir" toe aan config.json (absolute paden worden automatisch afgeleid)

Ollama werkt in terminal maar niet in Python
	•	Check llm.ollama_path in config.json
	•	Geen reliance op PATH of .zshrc

⸻
