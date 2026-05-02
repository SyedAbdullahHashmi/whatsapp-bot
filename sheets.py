import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1imSb1a-uq8K_XYwiru0IJYjGdssRC5QGr6kDHolQysk")
SHEET_NAME = os.environ.get("SHEET_NAME", "Master Tasks")   # Tab name in your sheet
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_service():
    """Build and return the Sheets API service using credentials from env or file."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # Fallback: load from local file (for local dev)
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def get_all_rows():
    """Fetch all rows from the sheet. Returns list of lists."""
    try:
        service = _get_service()
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:G")
            .execute()
        )
        return result.get("values", [])
    except Exception as e:
        print(f"[sheets] get_all_rows error: {e}")
        return []


def append_row(row_data: list):
    """Append a new row to the bottom of the sheet."""
    try:
        service = _get_service()
        body = {"values": [row_data]}
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:G",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
        return True
    except Exception as e:
        print(f"[sheets] append_row error: {e}")
        return False


def update_cell(row: int, col: int, value: str):
    """
    Update a single cell.
    row and col are 1-indexed (row 1 = header, row 2 = first data row).
    col 1 = A, col 2 = B, etc.
    """
    try:
        service = _get_service()
        col_letter = chr(ord("A") + col - 1)
        cell_range = f"{SHEET_NAME}!{col_letter}{row}"
        body = {"values": [[value]]}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=cell_range,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        return True
    except Exception as e:
        print(f"[sheets] update_cell error: {e}")
        return False


def find_row_by_task(task_name: str):
    """Find the 1-indexed row number of a task by its name (column B)."""
    rows = get_all_rows()
    for i, row in enumerate(rows, start=1):
        if len(row) > 1 and task_name.lower() in row[1].lower():
            return i
    return None
