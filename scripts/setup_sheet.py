"""
Standalone helper: create and format both Google Sheets tabs.
Run: python scripts/setup_sheet.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from scripts.push_sheet import (
    HEATMAP_CHAPTERS,
    THEO_DOI_HEADERS,
    get_gspread_client,
    setup_heatmap_sheet,
    setup_theo_doi_sheet,
)


def main():
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        print("Error: GOOGLE_SHEET_ID not set in .env")
        sys.exit(1)

    try:
        gc = get_gspread_client()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    spreadsheet = gc.open_by_key(sheet_id)
    worksheet_titles = [ws.title for ws in spreadsheet.worksheets()]

    if "Theo_doi" not in worksheet_titles:
        theo_doi_ws = spreadsheet.add_worksheet(title="Theo_doi", rows=1000, cols=10)
        print("Created sheet: Theo_doi")
    else:
        theo_doi_ws = spreadsheet.worksheet("Theo_doi")
        print("Sheet Theo_doi already exists")

    if "Heatmap" not in worksheet_titles:
        heatmap_ws = spreadsheet.add_worksheet(title="Heatmap", rows=20, cols=5)
        print("Created sheet: Heatmap")
    else:
        heatmap_ws = spreadsheet.worksheet("Heatmap")
        print("Sheet Heatmap already exists")

    setup_theo_doi_sheet(theo_doi_ws)
    print("✓ Theo_doi sheet formatted")

    setup_heatmap_sheet(heatmap_ws)
    print("✓ Heatmap sheet formatted with COUNTIFS formulas")

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    print(f"\n✓ Sheet URL: {url}")


if __name__ == "__main__":
    main()
