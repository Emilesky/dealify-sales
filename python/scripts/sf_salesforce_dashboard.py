import os
import shutil
from datetime import datetime

from python.app.config import load_config

DOWNLOADS_DIR = os.path.expanduser("~/Downloads")

# Worden in main() gezet op basis van config.json
DATA_DIR = None


def find_latest_csv(folder: str, name_contains: str | None = None, exclude_contains: str | None = None) -> str | None:
    """Zoek de nieuwste .csv in de map, optioneel gefilterd op name_contains en exclude_contains."""
    if not os.path.exists(folder):
        print(f"⚠ Map bestaat niet: {folder}")
        return None

    files: list[str] = []
    for f in os.listdir(folder):
        if not f.lower().endswith(".csv"):
            continue
        fname_lower = f.lower()
        if name_contains and name_contains.lower() not in fname_lower:
            continue
        if exclude_contains and exclude_contains.lower() in fname_lower:
            continue
        files.append(os.path.join(folder, f))

    if not files:
        return None

    return max(files, key=os.path.getctime)


def copy_latest_report(report_pattern: str, output_label: str, exclude_pattern: str | None = None) -> None:
    global DATA_DIR
    if not DATA_DIR:
        raise RuntimeError("[fetch] DATA_DIR is niet gezet. Draai via main() zodat config geladen wordt.")

    print(f"🔎 Zoeken naar nieuwste CSV in: {DOWNLOADS_DIR} met patroon: '{report_pattern}'"
          + (f" (exclude: '{exclude_pattern}')" if exclude_pattern else ""))

    # Debug: toon alle CSV's in Downloads die aan het patroon voldoen
    candidate_files: list[str] = []
    if os.path.exists(DOWNLOADS_DIR):
        for f in os.listdir(DOWNLOADS_DIR):
            if not f.lower().endswith(".csv"):
                continue
            fname_lower = f.lower()
            if report_pattern.lower() not in fname_lower:
                continue
            if exclude_pattern and exclude_pattern.lower() in fname_lower:
                continue
            candidate_files.append(f)

    if candidate_files:
        print("📄 Kandidaten in Downloads:")
        for f in candidate_files:
            print(f"   - {f}")
    else:
        print("📄 Geen kandidaten gevonden in Downloads voor dit patroon.")

    latest = find_latest_csv(DOWNLOADS_DIR, name_contains=report_pattern, exclude_contains=exclude_pattern)
    if not latest:
        print(f"⚠ Geen CSV-bestanden gevonden in ~/Downloads met '{report_pattern}' in de naam.")
        return

    filename = os.path.basename(latest)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    dest_tmp = os.path.join(DATA_DIR, f"{timestamp}_{filename}")

    print(f"📂 Gevonden: {latest}")
    print(f"📥 Kopiëren naar: {dest_tmp}")

    shutil.copy2(latest, dest_tmp)

    renamed_name = f"{timestamp}-{output_label} report{os.path.splitext(filename)[1]}"
    renamed_path = os.path.join(DATA_DIR, renamed_name)
    os.replace(dest_tmp, renamed_path)

    print(f"🏷  Bestand hernoemd naar: {renamed_path}")


def main():
    cfg = load_config()
    global DATA_DIR
    DATA_DIR = cfg["paths"]["data_dir_abs"]
    os.makedirs(DATA_DIR, exist_ok=True)

    print("[fetch] Start data ophalen uit Downloads")
    print(f"[fetch] Downloads: {DOWNLOADS_DIR}")
    print(f"[fetch] Data dir (config): {DATA_DIR}")

    # 1) Pipeline report ophalen (ILT_EMEA, maar NIET bookings)
    copy_latest_report(report_pattern="ILT_EMEA", output_label="pipeline", exclude_pattern="bookings")

    print("\n------------------------------------------------------------\n")

    # 2) Bookings report ophalen
    copy_latest_report(report_pattern="bookings", output_label="bookings")

    print("✅ Klaar. Beide CSV-bestanden staan nu in /data en kunnen gebruikt worden door de analyse scripts.")


if __name__ == "__main__":
    main()