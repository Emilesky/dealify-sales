

from typing import Dict

# === Canonical kolomnamen (CRM-agnostic) ===
COL_ACCOUNT = "account_name"
COL_OPPORTUNITY = "opportunity_name"
COL_STAGE = "stage"
COL_FORECAST_CATEGORY = "forecast_category"
COL_AMOUNT = "amount"
COL_CLOSE_DATE = "close_date"
COL_CREATED_DATE = "created_date"
COL_AE = "ae_name"
COL_NEXT_STEPS = "next_steps"

# === Interne / afgeleide kolommen ===
COL_AMOUNT_CLEAN = "amount_clean"
COL_CLOSE_DATE_PARSED = "close_date_parsed"
COL_STAGE_CLASS = "stage_class"

# === Salesforce-export fallback mapping ===
# Alleen gebruikt als mapping JSON niet toegepast is
SF_EXPORT_TO_CANONICAL: Dict[str, str] = {
    "Account Name": COL_ACCOUNT,
    "Opportunity Name": COL_OPPORTUNITY,
    "Stages": COL_STAGE,
    "Stage": COL_STAGE,
    "Forecast Category": COL_FORECAST_CATEGORY,
    "ForecastCategory": COL_FORECAST_CATEGORY,
    "Amount": COL_AMOUNT,
    "Close Date": COL_CLOSE_DATE,
    "Created Date": COL_CREATED_DATE,
    "Sales Person Name": COL_AE,
    "Owner": COL_AE,
    "Next Steps": COL_NEXT_STEPS,
    "Next Step": COL_NEXT_STEPS,
}