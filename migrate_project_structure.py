import pandas as pd

def format_currency(amount):
    return f"€{amount:,.2f}"

def run_analysis(df):
    # Forecast Category filters
    commit_df = df[df["Forecast Category"].str.contains("Commit", case=False, na=False)]
    upside_df = df[df["Forecast Category"].str.match("Upside", case=False, na=False)]
    green_df = df[df["Forecast Category"].str.contains("Green Upside", case=False, na=False)]
    omitted_df = df[df["Forecast Category"].str.contains("Omitted", case=False, na=False)]
    bookings_df = df[df["Forecast Category"].str.contains("Bookings", case=False, na=False)]

    # Actieve pipeline = alles behalve Bookings en Omitted
    active_df = df[
        ~df["Forecast Category"].str.contains("Bookings", case=False, na=False)
        & ~df["Forecast Category"].str.contains("Omitted", case=False, na=False)
    ]

    total_pipeline = active_df["Amount"].sum()
    total_commit = commit_df["Amount"].sum()
    total_upside = upside_df["Amount"].sum()
    total_green = green_df["Amount"].sum()
    total_omitted = omitted_df["Amount"].sum()
    total_bookings = bookings_df["Amount"].sum()

    print("=== 📊 Forecast Overview ===")
    print(f"Commit:        {format_currency(total_commit)}")
    print(f"Upside:        {format_currency(total_upside)}")
    print(f"Green Upside:  {format_currency(total_green)}")
    print(f"Bookings:      {format_currency(total_bookings)}")
    print(f"Omitted:       {format_currency(total_omitted)}")
    print(f"Active Pipeline (excl. Bookings/Omitted): {format_currency(total_pipeline)}\n")

    # Pipeline per AE (alleen actieve pipeline)
    ae_table = (
        active_df.groupby("Sales Person Name")["Amount"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )

    # Pipeline per Stage (alleen actieve pipeline)
    stage_table = (
        active_df.groupby("Stages")["Amount"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )

    # Other analysis and processing here...

    return active_df, ae_table