"""
Push session wrong-answer data to Google Sheet master tracker.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console

console = Console()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "ma_tran_chuan.yaml"
SESSIONS_DIR = ROOT / "sessions"
PROCESSED_DIR = ROOT / "question_bank" / "processed"

THEO_DOI_HEADERS = [
    "session_date", "exam_id", "phan", "stt", "y",
    "chuong", "chuong_ten", "muc_do", "sai_ngu", "on_tap_nhac_lai",
]

HEATMAP_CHAPTERS = [
    "DT_PT", "DT_TB", "CH_TV", "CH_DV", "DT_BD",
    "QL_DT", "DT_QT", "DT_HP", "UD_DT", "TH", "ST_MT",
]

PALETTES = {
    "red": ("#f5e8e9", "#D32F2F"),
    "green": ("#E8F5E9", "#1B5E20"),
    "purple": ("#e8e9f5", "#6A1B9A"),
}

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_gspread_client():
    load_dotenv(ROOT / ".env")
    service_account_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not service_account_path:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON not set in .env.\n"
            "Setup: create a service account in Google Cloud Console, download the JSON key,\n"
            "save it to config/service_account.json, and set GOOGLE_SERVICE_ACCOUNT_JSON=config/service_account.json"
        )

    sa_path = ROOT / service_account_path
    if not sa_path.exists():
        raise RuntimeError(
            f"Service account JSON not found at {sa_path}.\n"
            "Create one at: Google Cloud Console → IAM → Service Accounts → Create Key (JSON).\n"
            "Then share your Google Sheet with the service account email."
        )

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
        return gspread.authorize(creds)
    except ImportError as e:
        raise RuntimeError(f"Missing dependency: {e}. Run: uv pip install gspread google-auth")


def setup_theo_doi_sheet(ws):
    import gspread

    existing = ws.get_all_values()
    if existing and existing[0] == THEO_DOI_HEADERS:
        return

    ws.append_row(THEO_DOI_HEADERS)
    ws.freeze(rows=1)

    try:
        ws.format("A1:J1", {"textFormat": {"bold": True}})
        ws.set_column_width(1, 120)   # session_date
        ws.set_column_width(2, 100)   # exam_id
        ws.set_column_width(3, 50)    # phan
        ws.set_column_width(4, 50)    # stt
        ws.set_column_width(5, 50)    # y
        ws.set_column_width(6, 70)    # chuong
        ws.set_column_width(7, 200)   # chuong_ten
        ws.set_column_width(8, 50)    # muc_do
        ws.set_column_width(9, 80)    # sai_ngu
        ws.set_column_width(10, 120)  # on_tap_nhac_lai
    except Exception:
        pass

    sheet_id = ws._properties["sheetId"]
    spreadsheet = ws.spreadsheet

    validation_requests = [
        {
            "setDataValidation": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 8, "endColumnIndex": 9},
                "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True},
            }
        },
        {
            "setDataValidation": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 9, "endColumnIndex": 10},
                "rule": {
                    "condition": {"type": "ONE_OF_LIST", "values": [
                        {"userEnteredValue": "not_yet"},
                        {"userEnteredValue": "pass"},
                        {"userEnteredValue": "redo"},
                    ]},
                    "showCustomUi": True,
                },
            }
        },
        {
            "setDataValidation": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 2, "endColumnIndex": 3},
                "rule": {
                    "condition": {"type": "ONE_OF_LIST", "values": [
                        {"userEnteredValue": "P1"},
                        {"userEnteredValue": "P2"},
                        {"userEnteredValue": "P3"},
                    ]},
                    "showCustomUi": True,
                },
            }
        },
        {
            "setDataValidation": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 7, "endColumnIndex": 8},
                "rule": {
                    "condition": {"type": "ONE_OF_LIST", "values": [
                        {"userEnteredValue": "B"},
                        {"userEnteredValue": "H"},
                        {"userEnteredValue": "VD"},
                    ]},
                    "showCustomUi": True,
                },
            }
        },
    ]
    spreadsheet.batch_update({"requests": validation_requests})


def setup_heatmap_sheet(heatmap_ws, theo_doi_ws_title: str = "Theo_doi"):
    heatmap_ws.clear() # Clear to refresh formulas and remove old text
    theo_doi_ref = f"'{theo_doi_ws_title}'"
    
    # Use semicolon separator for Vietnam locale Google Sheets
    sep = ";" 
    
    headers = ["Chương", "P1", "P2", "P3", "Tổng"]
    chapter_rows = []
    
    # Dynamically build rows for each chapter with semicolons
    for i, ch in enumerate(HEATMAP_CHAPTERS, 2):
        chapter_rows.append([
            ch,
            f'=COUNTIFS({theo_doi_ref}!$C:$C{sep} "P1"{sep} {theo_doi_ref}!$F:$F{sep} "{ch}")',
            f'=COUNTIFS({theo_doi_ref}!$C:$C{sep} "P2"{sep} {theo_doi_ref}!$F:$F{sep} "{ch}")',
            f'=COUNTIFS({theo_doi_ref}!$C:$C{sep} "P3"{sep} {theo_doi_ref}!$F:$F{sep} "{ch}")',
            f'=SUM(B{i}:D{i})'
        ])
    
    # Add Total row
    last_row = len(HEATMAP_CHAPTERS) + 1
    chapter_rows.append([
        "Tổng",
        f"=SUM(B2:B{last_row})",
        f"=SUM(C2:C{last_row})",
        f"=SUM(D2:D{last_row})",
        f"=SUM(E2:E{last_row})"
    ])

    # Batch update the text and formulas
    heatmap_ws.update("A1", [headers] + chapter_rows, value_input_option="USER_ENTERED")
    
    # --- CONDITIONAL FORMATTING & STYLING ---
    sheet_id = heatmap_ws._properties["sheetId"]
    spreadsheet = heatmap_ws.spreadsheet
    num_chapters = len(HEATMAP_CHAPTERS)

    def _hex_to_rgb01(hex_color: str):
        hex_color = hex_color.lstrip("#")
        return {
            "red": int(hex_color[0:2], 16) / 255,
            "green": int(hex_color[2:4], 16) / 255,
            "blue": int(hex_color[4:6], 16) / 255,
        }
    
    def _mono_scale(hex_base, strength):
    
        base = _hex_to_rgb01(hex_base)
        return {
            "red": 1 - (1 - base["red"]) * strength,
            "green": 1 - (1 - base["green"]) * strength,
            "blue": 1 - (1 - base["blue"]) * strength,
        }

    def _gradient(start_col, end_col, start_row, end_row, palette):
        min_hex, max_hex = PALETTES[palette]

        return {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": start_row,
                        "endRowIndex": end_row,
                        "startColumnIndex": start_col,
                        "endColumnIndex": end_col
                    }],
                    "gradientRule": {
                        "minpoint": {"color": _hex_to_rgb01(min_hex), "type": "MIN"},
                        "maxpoint": {"color": _hex_to_rgb01(max_hex), "type": "MAX"},
                    },
                },
                "index": 0,
            }
        }
    # Combine all formatting requests
    requests = [
        {"deleteConditionalFormatRule": {"index": 0, "sheetId": sheet_id}},
        {"deleteConditionalFormatRule": {"index": 0, "sheetId": sheet_id}},
        {"deleteConditionalFormatRule": {"index": 0, "sheetId": sheet_id}},

        # Inner grid → red
        _gradient(1, 4, 1, num_chapters + 1, "red"),

        # Totals → green
        _gradient(4, 5, 1, num_chapters + 1, "green"),

        # Bottom totals → purple
        _gradient(1, 5, num_chapters + 1, num_chapters + 2, "purple"),

        # 3. Bold the Header Row
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"
        }},
        
        # 4. Bold the "Tổng" Row at the bottom
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": num_chapters + 1, "endRowIndex": num_chapters + 2},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"
        }}
    ]

    try:
        # Ignore errors if deleting rules fails (e.g., if there are no rules to delete on the first run)
        spreadsheet.batch_update({"requests": requests})
    except Exception:
        # If deletion fails, just send the add/format requests
        add_requests = [r for r in requests if "deleteConditionalFormatRule" not in r]
        spreadsheet.batch_update({"requests": add_requests})   

def resolve_session_path(session_arg: str) -> Path:
    p = Path(session_arg)
    if p.is_absolute() and p.exists():
        return p
    if (SESSIONS_DIR / p).exists():
        return SESSIONS_DIR / p
    direct = SESSIONS_DIR / session_arg
    if direct.exists():
        return direct
    raise ValueError(f"Session folder not found: {session_arg}")


def run_push(session_arg: str):
    load_dotenv(ROOT / ".env")
    config = load_config()
    # Map chapter IDs to their full names
    chapter_names = {k: v["ten"] for k, v in config["chuong"].items()}

    session_dir = resolve_session_path(session_arg)
    session_yaml_path = session_dir / "session.yaml"

    if not session_yaml_path.exists():
        raise FileNotFoundError(f"session.yaml not found in {session_dir}")

    with open(session_yaml_path, encoding="utf-8") as f:
        sessions_list = yaml.safe_load(f)

    if not isinstance(sessions_list, list):
        sessions_list = [sessions_list]

    all_rows_to_push = []

    # --- PROCESS EACH EXAM INDIVIDUALLY ---
    for session_data in sessions_list:
        session_date = str(session_data["date"])
        exam_id = session_data["exam_id"]
        wrong_questions = session_data.get("wrong_questions", [])

        # Load metadata for THIS specific exam
        classify_json_path = PROCESSED_DIR / exam_id / "classify.json"
        if not classify_json_path.exists():
            console.print(f"[yellow]⚠ Bỏ qua {exam_id}: Không tìm thấy classify.json[/yellow]")
            continue

        with open(classify_json_path, encoding="utf-8") as f:
            classify_data = json.load(f)

        # Create lookup map for this exam
        classify_map = {}
        for c in classify_data.get("classifications", []):
            key = f"{c['phan']}:{c['stt']}"
            if c.get("y"): key += f":{c['y']}"
            classify_map[key] = c

        # Build the full 10-column rows
        for wq in wrong_questions:
            phan = wq["phan"]
            stt = str(wq["stt"])
            y = wq.get("y", "")

            key = f"{phan}:{stt}:{y}" if y else f"{phan}:{stt}"
            cls = classify_map.get(key, {})

            chuong = cls.get("chuong", "")
            muc_do = cls.get("muc_do", "")
            chuong_ten = chapter_names.get(chuong, "Unknown")

            all_rows_to_push.append([
                session_date,    # A: session_date
                exam_id,         # B: exam_id
                phan,            # C: phan
                int(stt),        # D: stt
                y,               # E: y
                chuong,          # F: chuong (Crucial for Heatmap)
                chuong_ten,      # G: chuong_ten
                muc_do,          # H: muc_do
                False,           # I: sai_ngu
                "not_yet",       # J: on_tap_nhac_lai
            ])

    # --- GOOGLE SHEETS SYNC ---
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    gc = get_gspread_client()
    spreadsheet = gc.open_by_key(sheet_id)

    # Get/Create sheets
    worksheet_titles = [ws.title for ws in spreadsheet.worksheets()]
    theo_doi_ws = spreadsheet.worksheet("Theo_doi") if "Theo_doi" in worksheet_titles else spreadsheet.add_worksheet("Theo_doi", 1000, 10)
    heatmap_ws = spreadsheet.worksheet("Heatmap") if "Heatmap" in worksheet_titles else spreadsheet.add_worksheet("Heatmap", 20, 5)

    setup_theo_doi_sheet(theo_doi_ws)
    # Re-run heatmap setup to ensure formulas are fresh
    setup_heatmap_sheet(heatmap_ws, "Theo_doi")

    if all_rows_to_push:
        theo_doi_ws.append_rows(all_rows_to_push, value_input_option="USER_ENTERED")
        
        # Sort Column A (Date) Descending (Latest on top)
        theo_doi_ws.sort((1, 'des'))
        
        console.print(f"[green]✓ Đã đẩy {len(all_rows_to_push)} câu hỏi vào Google Sheet và sắp xếp theo ngày.[/green]")