Salesforce AI Sales Intelligence

Lokale Python-based AI sales intelligence tool voor het analyseren van CRM-exportdata (CSV) en het genereren van wekelijkse managementinzichten met behulp van een LLM (Ollama of SaaS).

De tool is CRM-agnostisch, config-driven en ontworpen om later eenvoudig te embedden in een web app of SaaS.

⸻

Projectstructuur

SalesforceSelenium/
├─ config.json              # Centrale configuratie (paths, LLM)
├─ data/                    # Ruwe input (CSV exports)
├─ outputs/                 # Gegenereerde outputs (JSON, TXT)
├─ scripts/                 # Ingest / automation (Downloads → data)
│
├─ python/
│  ├─ app/
│  │  └─ config.py
│  ├─ llm/
│  │  └─ client.py
│  ├─ pipeline/
│  │  ├─ pipeline_analyse.py
│  │  └─ next_step_health.py
│  ├─ weekly/
│  │  ├─ weekly_filter.py
│  │  ├─ management_summary.py
│  │  └─ weekly_management_scan.py
│  └─ inspect/
│     └─ inspect_management_data.py
│
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
    "outputs_dir_abs": "/Users/you/Automations/SalesforceSelenium/outputs"
  },
  "llm": {
    "backend": "ollama",
    "model": "llama3.1:8b",
    "timeout_sec": 180,
    "ollama_path": "/usr/local/bin/ollama"
  }
}

Belangrijk:
	•	outputs_dir_abs is de single source of truth voor alle output
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

Filtert managementdata naar compacte LLM-input voor de week.

python -m python.weekly.weekly_filter

Output:
	•	outputs/weekly_llm_input_latest.json

⸻

3. Weekly management scan (LLM)

Genereert een kritische RVP-level managementanalyse.

python -m python.weekly.weekly_management_scan

Optioneel extra context:

python -m python.weekly.weekly_management_scan --context-file extra_context.txt

Output:
	•	outputs/weekly_management_scan_latest.txt
	•	Timestamped variant per run

⸻

4. Inspect / debug

Inspecteer managementdata of sanity-check JSON.

python -m python.inspect.inspect_management_data --team

Of met expliciet bestand:

python -m python.inspect.inspect_management_data --file /pad/naar/json --team


⸻

Scripts (ingest / automation)

Scripts in scripts/ zijn niet bedoeld om geïmporteerd te worden.
Ze verzorgen alleen aanvoer, bijvoorbeeld:
	•	CSV’s uit Downloads kopiëren
	•	Selenium exports
	•	Bestanden normaliseren naar data/

Voorbeeld:

python scripts/move_latest_from_downloads.py

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
	•	Check of je project root (SalesforceSelenium) als folder geopend is
	•	Controleer of __init__.py aanwezig is in subfolders
	•	Gebruik altijd python -m python.<module>

outputs_dir_abs ontbreekt
	•	Voeg "paths.outputs_dir_abs" toe aan config.json

Ollama werkt in terminal maar niet in Python
	•	Check llm.ollama_path in config.json
	•	Geen reliance op PATH of .zshrc

⸻
