import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

import gspread
import pymysql

CONFIG_PATH = os.getenv("FORMS_CONFIG_PATH", "forms_config.json")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT", "service_account.json")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "nas_user"),
    "password": os.getenv("DB_PASSWORD", "nas_password"),
    "database": os.getenv("DB_NAME", "nas_surveys"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}


class SyncError(Exception):
    pass


def load_config(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise SyncError("forms_config.json must contain a list of survey configs")
    return data


def save_config(path: str, data: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def open_sheet(client: gspread.Client, sheet_url: str):
    return client.open_by_url(sheet_url)


def ensure_synced_column(worksheet: gspread.Worksheet, headers: List[str]) -> Tuple[List[str], int]:
    if headers and headers[-1].strip().lower() == "synced":
        return headers, len(headers)
    new_headers = headers + ["Synced"]
    worksheet.resize(rows=worksheet.row_count, cols=len(new_headers))
    worksheet.update("1:1", [new_headers])
    return new_headers, len(new_headers)


def get_or_create_survey(cursor, survey: Dict[str, Any]) -> int:
    query = (
        "SELECT id FROM survey_info WHERE client_name=%s AND course_name=%s AND manager=%s "
        "AND date=%s AND category=%s AND survey_name=%s"
    )
    values = (
        survey["client"],
        survey["course"],
        survey["manager"],
        survey["date"],
        survey["category"],
        survey["survey_name"],
    )
    cursor.execute(query, values)
    existing = cursor.fetchone()
    if existing:
        return int(existing["id"])

    insert_query = (
        "INSERT INTO survey_info (client_name, course_name, manager, date, category, survey_name) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    cursor.execute(insert_query, values)
    return int(cursor.lastrowid)


def get_or_create_question(cursor, category: str, question_text: str) -> int:
    select_query = "SELECT id FROM question_bank WHERE question_text=%s"
    cursor.execute(select_query, (question_text,))
    existing = cursor.fetchone()
    if existing:
        return int(existing["id"])

    insert_query = (
        "INSERT INTO question_bank (category, type, question_text) VALUES (%s, %s, %s)"
    )
    cursor.execute(insert_query, (category, "자동생성", question_text))
    return int(cursor.lastrowid)


def response_exists(cursor, survey_id: int, respondent_id: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM responses WHERE survey_id=%s AND respondent_id=%s LIMIT 1",
        (survey_id, respondent_id),
    )
    return cursor.fetchone() is not None


def insert_response(cursor, survey_id: int, respondent_id: str, question_id: int, answer_value: str) -> None:
    cursor.execute(
        "INSERT IGNORE INTO responses (survey_id, respondent_id, question_id, answer_value) "
        "VALUES (%s, %s, %s, %s)",
        (survey_id, respondent_id, question_id, answer_value),
    )


def sync_sheet(survey: Dict[str, Any], client: gspread.Client, connection) -> Dict[str, Any]:
    spreadsheet = open_sheet(client, survey["sheet_url"])
    worksheet = spreadsheet.sheet1
    all_values = worksheet.get_all_values()
    if not all_values:
        return {"survey_name": survey["survey_name"], "synced_rows": 0}

    headers = all_values[0]
    headers, synced_col = ensure_synced_column(worksheet, headers)
    question_headers = headers[:-1]

    synced_rows = 0
    with connection.cursor() as cursor:
        survey_id = get_or_create_survey(cursor, survey)
        question_map = {
            question: get_or_create_question(cursor, survey["category"], question)
            for question in question_headers
        }

        for index, row in enumerate(all_values[1:], start=2):
            row = row + [""] * (len(headers) - len(row))
            synced_flag = row[synced_col - 1].strip().lower()
            respondent_id = f"{survey_id}_{index}"
            if synced_flag in {"y", "yes", "true", "1", "synced"}:
                continue
            if response_exists(cursor, survey_id, respondent_id):
                worksheet.update_cell(index, synced_col, "Y")
                continue
            for question, answer in zip(question_headers, row[: len(question_headers)]):
                question_id = question_map[question]
                insert_response(cursor, survey_id, respondent_id, question_id, answer)
            worksheet.update_cell(index, synced_col, "Y")
            synced_rows += 1

    return {"survey_name": survey["survey_name"], "synced_rows": synced_rows}


def run_sync() -> Dict[str, Any]:
    config = load_config(CONFIG_PATH)
    if not config:
        return {"synced": [], "message": "No surveys configured."}

    client = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    results = []
    with pymysql.connect(**DB_CONFIG) as connection:
        try:
            for survey in config:
                results.append(sync_sheet(survey, client, connection))
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise SyncError(str(exc)) from exc

    return {"synced": results, "message": "Sync completed"}


def add_survey_config(new_entry: Dict[str, Any]) -> None:
    required = {"client", "course", "manager", "date", "category", "survey_name", "sheet_url"}
    missing = required - set(new_entry.keys())
    if missing:
        raise SyncError(f"Missing required fields: {', '.join(sorted(missing))}")

    try:
        datetime.strptime(new_entry["date"], "%Y-%m-%d")
    except ValueError as exc:
        raise SyncError("date must be in YYYY-MM-DD format") from exc

    config = load_config(CONFIG_PATH)
    config.append(new_entry)
    save_config(CONFIG_PATH, config)


if __name__ == "__main__":
    summary = run_sync()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
