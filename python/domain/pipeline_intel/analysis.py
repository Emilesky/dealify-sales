from __future__ import annotations

import re
from typing import Any, Tuple

import pandas as pd

from python.domain.pipeline_intel.constants import (
    COL_AMOUNT,
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE,
    COL_CLOSE_DATE_PARSED,
    COL_FORECAST_CATEGORY,
    COL_STAGE,
    COL_STAGE_CLASS,
)


def parse_amount(value: Any) -> float:
    """Zorg dat het bedrag als float wordt geïnterpreteerd, inclusief valuta-tekens en EU notatie."""
    try:
        import pandas as _pd
        if _pd.isna(value):
            return 0.0
    except Exception:
        if value is None:
            return 0.0

    text = str(value).strip()
    if not text:
        return 0.0

    text = text.replace("€", "").replace("$", "")
    text = text.replace(" ", "")
    text = re.sub(r"[^0-9.,-]", "", text)

    if "." in text and "," in text:
        last_dot = text.rfind(".")
        last_comma = text.rfind(",")
        if last_dot > last_comma:
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        pass

    try:
        return float(text)
    except ValueError:
        return 0.0


def classify_stage(stage: Any) -> str:
    """Vertaal stage naar commit/upside/green/other."""
    s = (str(stage) if stage is not None else "").strip()
    if s == "Negotiation":
        return "commit"
    if s in ("Discovery", "Qualification"):
        return "upside"
    if s == "Evaluation":
        return "green upside"
    return "other"


def run_analysis(
    ctx: Any,
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Bereid de data voor:
    - Amount opschonen
    - Close Date parsen
    - Actieve pipeline, bookings, omitted splitsen
    """
    df = df.copy()
    print("[pipeline] Start run_analysis()")
    print(f"[pipeline] Kolommen in dataframe: {list(df.columns)}")

    # Amount opschonen naar float (canonical: COL_AMOUNT)
    if COL_AMOUNT in df.columns:
        amount_source_col = COL_AMOUNT
    else:
        amount_source_col = None
        for col in df.columns:
            if str(col).strip().lower() in ("amount", "amount\ufeff") or "amount" in str(col).lower():
                amount_source_col = col
                break
        if amount_source_col is None:
            raise KeyError(
                f"Geen geschikte amount-kolom gevonden. Verwacht '{COL_AMOUNT}' (canonical) of iets met 'Amount'. "
                f"Beschikbare kolommen: {list(df.columns)}"
            )

    print(f"[pipeline] Amount kolom gevonden: {amount_source_col} -> wordt opgeschoond naar '{COL_AMOUNT_CLEAN}'")
    df[COL_AMOUNT_CLEAN] = df[amount_source_col].apply(parse_amount)
    print(f"[pipeline] Amount opschonen gereed (min={df[COL_AMOUNT_CLEAN].min():.2f}, max={df[COL_AMOUNT_CLEAN].max():.2f})")

    if COL_CLOSE_DATE in df.columns:
        df[COL_CLOSE_DATE_PARSED] = pd.to_datetime(df[COL_CLOSE_DATE], errors="coerce").dt.date
    else:
        print(f"[pipeline] Waarschuwing: kolom '{COL_CLOSE_DATE}' niet gevonden, {COL_CLOSE_DATE_PARSED} wordt None")
        df[COL_CLOSE_DATE_PARSED] = None

    if COL_STAGE not in df.columns:
        raise KeyError(f"Verwachte kolom '{COL_STAGE}' niet gevonden in CSV.")
    df[COL_STAGE_CLASS] = df[COL_STAGE].apply(classify_stage)

    if COL_FORECAST_CATEGORY not in df.columns:
        raise KeyError(f"Verwachte kolom '{COL_FORECAST_CATEGORY}' niet gevonden in CSV.")

    bookings_df = df[
        df[COL_FORECAST_CATEGORY].str.contains("Bookings", case=False, na=False)
    ].copy()
    omitted_df = df[
        df[COL_FORECAST_CATEGORY].str.contains("Omitted", case=False, na=False)
    ].copy()
    print(f"[pipeline] Bookings deals: {len(bookings_df)} | Omitted deals: {len(omitted_df)}")

    active_df = df[
        ~df[COL_FORECAST_CATEGORY].str.contains("Bookings", case=False, na=False)
        & ~df[COL_FORECAST_CATEGORY].str.contains("Omitted", case=False, na=False)
    ].copy()
    print(f"[pipeline] Actieve pipeline deals (excl. Bookings/Omitted): {len(active_df)}")

    return active_df, bookings_df, omitted_df