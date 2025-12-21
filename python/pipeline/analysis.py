from __future__ import annotations

import re
from typing import Any, Optional, Tuple, cast

import pandas as pd

from python.pipeline.constants import (
    COL_AMOUNT,
    COL_AMOUNT_CLEAN,
    COL_CLOSE_DATE,
    COL_CLOSE_DATE_PARSED,
    COL_FORECAST_CATEGORY,
    COL_NEXT_STEPS,
    COL_STAGE,
    COL_STAGE_CLASS,
)
from python.pipeline.next_step_health import evaluate_next_steps_batch


def extract_health_score(health: Any) -> Optional[float]:
    """Haal een numerieke health score uit het next_step_health veld (dict of primitive)."""
    if isinstance(health, (int, float)):
        return float(health)
    if isinstance(health, str):
        try:
            return float(health.strip())
        except ValueError:
            return None
    if isinstance(health, dict):
        score_raw = health.get("score")
        if isinstance(score_raw, (int, float)):
            return float(score_raw)
        if isinstance(score_raw, str):
            try:
                return float(score_raw.strip())
            except ValueError:
                return None
    return None


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
    enable_llm: bool = True,
    llm_config: Any | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Bereid de data voor:
    - Amount opschonen
    - Close Date parsen
    - Actieve pipeline, bookings, omitted splitsen
    - LLM Next Step health verrijken op actieve pipeline
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

    if not enable_llm:
        print("[pipeline] LLM Next Step health verrijking is uitgeschakeld (--no-llm).")
        return active_df, bookings_df, omitted_df

    print("[pipeline] Start LLM Next Step health verrijking op actieve pipeline...")

    llm_cfg = llm_config
    if llm_cfg is None:
        llm_cfg = getattr(ctx, "llm_config", None)

    if llm_cfg is None:
        print("[pipeline][WAARSCHUWING] Geen llm_config beschikbaar; ga verder zonder Next Step health.")
        return active_df, bookings_df, omitted_df

    scoring_model = getattr(llm_cfg, "model", None)
    print(f"[pipeline] Next step scoring model (config): {scoring_model}")

    records = active_df.to_dict(orient="records")
    from time import perf_counter
    t0 = perf_counter()
    try:
        enriched_records = evaluate_next_steps_batch(
            records,
            next_step_field=COL_NEXT_STEPS,
            llm_config=llm_cfg,
        )
    except FileNotFoundError as e:
        print("[pipeline][ERROR] LLM Next Step health verrijking faalde: Ollama executable niet gevonden.")
        print("[pipeline][ERROR] Check: `which ollama` en `ollama --version` in dezelfde shell/venv.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")
        enriched_records = records
    except Exception as e:
        print("[pipeline][ERROR] LLM Next Step health verrijking is gefaald. Er wordt verder gegaan zonder health scores.")
        print(f"[pipeline][ERROR] Exception: {repr(e)}")
        enriched_records = records
    t1 = perf_counter()
    print(f"[pipeline] LLM-call evaluate_next_steps_batch duurde {t1 - t0:.2f} seconden voor {len(records)} deals.")

    active_df = pd.DataFrame(enriched_records)

    print("[pipeline] LLM verrijking voltooid. Kolommen nu:", list(active_df.columns))
    if "next_step_health" not in active_df.columns:
        print("[pipeline][WAARSCHUWING] Kolom 'next_step_health' ontbreekt na LLM-verrijking.")
    else:
        total_deals = len(active_df)
        non_null_health = active_df["next_step_health"].notna().sum()
        valid_score_count = 0
        for _, deal in active_df.iterrows():
            score_val = extract_health_score(deal.get("next_step_health"))
            if score_val is not None:
                valid_score_count += 1

        print(
            f"[pipeline] next_step_health aanwezig voor {non_null_health}/{total_deals} deals; "
            f"waarvan {valid_score_count} met een bruikbare numerieke score."
        )

        if non_null_health == 0 or valid_score_count == 0:
            print("[pipeline][WAARSCHUWING] LLM lijkt geen bruikbare health scores te hebben geleverd.")

        sample_health = active_df["next_step_health"].head(5).tolist()
        print("[pipeline] Voorbeeld next_step_health (eerste 5 deals):")
        for idx, h in enumerate(sample_health, start=1):
            print(f"  Deal {idx}: {h}")

    return active_df, bookings_df, omitted_df