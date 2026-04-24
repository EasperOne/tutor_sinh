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
    existing = heatmap_ws.get_all_values()
    if existing and len(existing) > 1:
        return

    sheet_id = heatmap_ws._properties["sheetId"]
    theo_doi_ref = f"'{theo_doi_ws_title}'"

    col_headers = ["Chương", "P1", "P2", "P3", "Tổng"]
    heatmap_ws.update("A1:E1", [col_headers])

    chapter_rows = []
    for i, ch in enumerate(HEATMAP_CHAPTERS, 2):
        p1 = f'=COUNTIFS({theo_doi_ref}!C:C,"P1",{theo_doi_ref}!F:F,"{ch}")'
        p2 = f'=COUNTIFS({theo_doi_ref}!C:C,"P2",{theo_doi_ref}!F:F,"{ch}")'
        p3 = f'=COUNTIFS({theo_doi_ref}!C:C,"P3",{theo_doi_ref}!F:F,"{ch}")'
        total = f"=SUM(B{i}:D{i})"
        chapter_rows.append([ch, p1, p2, p3, total])

    tong_row = [
        "Tổng",
        "=SUM(B2:B12)",
        "=SUM(C2:C12)",
        "=SUM(D2:D12)",
        "=SUM(E2:E12)",
    ]
    chapter_rows.append(tong_row)

    for i, row in enumerate(chapter_rows, 2):
        heatmap_ws.update(f"A{i}:E{i}", [row])

    spreadsheet = heatmap_ws.spreadsheet
    cf_request = {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 13, "startColumnIndex": 1, "endColumnIndex": 5}],
                "gradientRule": {
                    "minpoint": {"color": {"red": 1, "green": 1, "blue": 1}, "type": "MIN"},
                    "midpoint": {"color": {"red": 1, "green": 1, "blue": 0}, "type": "PERCENTILE", "value": "50"},
                    "maxpoint": {"color": {"red": 1, "green": 0, "blue": 0}, "type": "MAX"},
                },
            },
            "index": 0,
        }
    }
    try:
        spreadsheet.batch_update({"requests": [cf_request]})
    except Exception:
        pass


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
    chapter_names = {k: v["ten"] for k, v in config["chuong"].items()}

    session_dir = resolve_session_path(session_arg)
    session_yaml_path = session_dir / "session.yaml"

    if not session_yaml_path.exists():
        raise FileNotFoundError(f"session.yaml not found in {session_dir}")

    with open(session_yaml_path, encoding="utf-8") as f:
        session = yaml.safe_load(f)

    session_date = str(session["date"])
    exam_id = session["exam_id"]
    wrong_questions = session.get("wrong_questions", [])

    classify_json_path = PROCESSED_DIR / exam_id / "classify.json"
    if not classify_json_path.exists():
        raise FileNotFoundError(
            f"classify.json not found for {exam_id}. Run: tutor classify question_bank/raw/{exam_id}.pdf"
        )

    with open(classify_json_path, encoding="utf-8") as f:
        classify_data = json.load(f)

    classify_map: dict[str, dict] = {}
    for c in classify_data.get("classifications", []):
        key_parts = [c["phan"], str(c["stt"])]
        if c.get("y"):
            key_parts.append(c["y"])
        classify_map[":".join(key_parts)] = c

    rows = []
    for wq in wrong_questions:
        phan = wq["phan"]
        stt = str(wq["stt"])
        y = wq.get("y", "")

        key = f"{phan}:{stt}:{y}" if y else f"{phan}:{stt}"
        cls = classify_map.get(key, {})

        chuong = cls.get("chuong", "")
        muc_do = cls.get("muc_do", "")
        chuong_ten = chapter_names.get(chuong, "")

        rows.append([
            session_date,
            exam_id,
            phan,
            int(stt),
            y,
            chuong,
            chuong_ten,
            muc_do,
            False,
            "not_yet",
        ])

    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID not set in .env")

    try:
        gc = get_gspread_client()
    except RuntimeError as e:
        console.print(f"[red]Google Sheets setup required:[/red]\n{e}")
        return

    spreadsheet = gc.open_by_key(sheet_id)

    worksheet_titles = [ws.title for ws in spreadsheet.worksheets()]

    if "Theo_doi" not in worksheet_titles:
        theo_doi_ws = spreadsheet.add_worksheet(title="Theo_doi", rows=1000, cols=10)
    else:
        theo_doi_ws = spreadsheet.worksheet("Theo_doi")

    if "Heatmap" not in worksheet_titles:
        heatmap_ws = spreadsheet.add_worksheet(title="Heatmap", rows=20, cols=5)
    else:
        heatmap_ws = spreadsheet.worksheet("Heatmap")

    setup_theo_doi_sheet(theo_doi_ws)
    setup_heatmap_sheet(heatmap_ws)

    theo_doi_ws.append_rows(rows, value_input_option="USER_ENTERED")

    console.print(
        f"[green]✓ Đã thêm {len(rows)} câu hỏi sai vào Google Sheet "
        f"(session: {session_date}, đề: {exam_id})[/green]"
    )


