import asyncio
import json
import logging
import os
import random
import threading
import time
from collections import deque

import gspread
from dotenv import load_dotenv
from requests.exceptions import RequestException


load_dotenv()

SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "")
LOGGER = logging.getLogger("routine_bot.sheets")

# Sheets is intentionally connected lazily. A temporary network failure at
# process startup should not terminate the bot before polling can begin.
_CONNECTION_LOCK = threading.RLock()
_DOCUMENT = None
_WORKSHEETS = {}


def _resolve_credentials_client():
    raw_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if raw_json:
        LOGGER.info("Authenticating Google Sheets via GOOGLE_CREDENTIALS_JSON env var")
        return gspread.service_account_from_dict(json.loads(raw_json))

    configured_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
    candidate_paths = [
        configured_file,
        "/etc/secrets/credentials.json",
        "credentials.json",
    ]
    for path in candidate_paths:
        if path and os.path.exists(path):
            LOGGER.info("Authenticating Google Sheets via file: %s", path)
            return gspread.service_account(filename=path)

    return gspread.service_account(filename=configured_file or "credentials.json")


def _get_document():
    global _DOCUMENT
    with _CONNECTION_LOCK:
        if _DOCUMENT is None:
            if not SHEET_NAME:
                raise RuntimeError("GOOGLE_SHEET_NAME is not configured")
            LOGGER.info("Connecting to Google Sheets: %s", SHEET_NAME)
            client = _resolve_credentials_client()
            _DOCUMENT = client.open(SHEET_NAME)
            LOGGER.info("Google Sheets connection established")
        return _DOCUMENT


def _get_worksheet(title):
    with _CONNECTION_LOCK:
        if title not in _WORKSHEETS:
            _WORKSHEETS[title] = _get_document().worksheet(title)
        return _WORKSHEETS[title]


class LazyWorksheet:
    """Resolve a worksheet only when a Sheets operation actually needs it."""

    def __init__(self, title):
        self.title = title

    def __getattr__(self, attribute):
        return getattr(_get_worksheet(self.title), attribute)


users_sheet = LazyWorksheet("Users")
logs_sheet = LazyWorksheet("Logs")
insights_sheet = LazyWorksheet("Insights")
attendance_sheet = LazyWorksheet("출석률")

# Google Sheets quota is shared by the service account. Leave a wide safety
# margin and serialize writes in this process so scheduled jobs and commands
# cannot create a burst that exceeds the per-minute write quota.
try:
    _WRITE_LIMIT_PER_MINUTE = max(
        1,
        int(os.environ.get("GOOGLE_SHEETS_WRITE_LIMIT_PER_MINUTE", "30")),
    )
except ValueError:
    _WRITE_LIMIT_PER_MINUTE = 30
try:
    _WRITE_MAX_RETRIES = max(1, int(os.environ.get("GOOGLE_SHEETS_MAX_RETRIES", "5")))
except ValueError:
    _WRITE_MAX_RETRIES = 5
try:
    _QUOTA_COOLDOWN_SECONDS = max(
        1, int(os.environ.get("GOOGLE_SHEETS_QUOTA_COOLDOWN_SECONDS", "65"))
    )
except ValueError:
    _QUOTA_COOLDOWN_SECONDS = 65

_WRITE_TIMESTAMPS = deque()
_WRITE_LOCK = asyncio.Lock()
_WRITE_COOLDOWN_UNTIL = 0.0


def _status_code(error):
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) or getattr(response, "status", None)


def _is_retryable(error):
    status_code = _status_code(error)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    if isinstance(error, (ConnectionError, TimeoutError, RequestException)):
        return True
    return any(
        token in str(error)
        for token in (
            "[429]",
            "[500]",
            "[502]",
            "[503]",
            "[504]",
            "Quota exceeded",
            "RESOURCE_EXHAUSTED",
        )
    )


def _retry_after_seconds(error):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        return max(0.0, float(headers.get("Retry-After")))
    except (TypeError, ValueError):
        return None


async def _reserve_write_slot():
    while True:
        now = time.monotonic()
        if now < _WRITE_COOLDOWN_UNTIL:
            await asyncio.sleep(_WRITE_COOLDOWN_UNTIL - now)
            continue

        while _WRITE_TIMESTAMPS and now - _WRITE_TIMESTAMPS[0] >= 60:
            _WRITE_TIMESTAMPS.popleft()

        if len(_WRITE_TIMESTAMPS) < _WRITE_LIMIT_PER_MINUTE:
            _WRITE_TIMESTAMPS.append(now)
            return

        wait_seconds = max(0.05, 60 - (now - _WRITE_TIMESTAMPS[0]))
        LOGGER.info("Sheets write rate limit reached; waiting %.1f seconds", wait_seconds)
        await asyncio.sleep(wait_seconds)


def _activate_quota_cooldown(error):
    global _WRITE_COOLDOWN_UNTIL
    retry_after = _retry_after_seconds(error)
    cooldown = max(_QUOTA_COOLDOWN_SECONDS, retry_after or 0)
    _WRITE_COOLDOWN_UNTIL = max(_WRITE_COOLDOWN_UNTIL, time.monotonic() + cooldown)
    LOGGER.warning(
        "Google Sheets write quota reached; pausing writes for %.1f seconds. Error: %s",
        cooldown,
        error,
    )


async def _run_sheet_call(operation, *, is_write=False, label="Sheets request"):
    async def execute_with_retry():
        for attempt in range(_WRITE_MAX_RETRIES):
            if is_write:
                await _reserve_write_slot()
            try:
                return await asyncio.to_thread(operation)
            except Exception as error:
                if not _is_retryable(error) or attempt == _WRITE_MAX_RETRIES - 1:
                    LOGGER.error(
                        "%s failed after %s attempt(s)",
                        label,
                        attempt + 1,
                        exc_info=(type(error), error, error.__traceback__),
                    )
                    raise

                delay = min(2 ** attempt + random.random(), 32)
                if is_write and _status_code(error) == 429:
                    _activate_quota_cooldown(error)
                    delay = max(delay, _WRITE_COOLDOWN_UNTIL - time.monotonic())
                LOGGER.warning(
                    "%s retry %s/%s in %.1f seconds: %s",
                    label,
                    attempt + 1,
                    _WRITE_MAX_RETRIES - 1,
                    delay,
                    error,
                )
                await asyncio.sleep(delay)

    if not is_write:
        return await execute_with_retry()

    async with _WRITE_LOCK:
        return await execute_with_retry()


async def async_find_in_col(sheet, query, column=1):
    def find():
        try:
            return sheet.find(query, in_column=column)
        except gspread.exceptions.CellNotFound:
            return None

    return await _run_sheet_call(find, label="Sheets find")


async def async_findall_in_col(sheet, query, column=1):
    def findall():
        try:
            return sheet.findall(query, in_column=column)
        except gspread.exceptions.CellNotFound:
            return []

    return await _run_sheet_call(findall, label="Sheets findall")


async def async_append_row(sheet, row_data):
    await async_append_rows(sheet, [row_data])


async def async_append_rows(sheet, rows, value_input_option="RAW"):
    if not rows:
        return
    await _run_sheet_call(
        lambda: sheet.append_rows(rows, value_input_option=value_input_option),
        is_write=True,
        label="Sheets append_rows",
    )


async def async_update_cell(sheet, row, col, value):
    await _run_sheet_call(
        lambda: sheet.update_cell(row, col, value),
        is_write=True,
        label="Sheets update_cell",
    )


async def async_update_range(sheet, range_name, values, value_input_option="RAW"):
    await _run_sheet_call(
        lambda: sheet.update(
            values,
            range_name=range_name,
            value_input_option=value_input_option,
        ),
        is_write=True,
        label=f"Sheets update {range_name}",
    )


async def async_update_cells(sheet, cells, value_input_option="RAW"):
    if not cells:
        return
    await _run_sheet_call(
        lambda: sheet.update_cells(cells, value_input_option=value_input_option),
        is_write=True,
        label="Sheets update_cells",
    )


async def async_delete_rows(sheet, row):
    await _run_sheet_call(
        lambda: sheet.delete_rows(row),
        is_write=True,
        label="Sheets delete_rows",
    )


async def async_get_all_records(sheet):
    return await _run_sheet_call(sheet.get_all_records, label="Sheets get_all_records")


async def async_get_all_values(sheet):
    return await _run_sheet_call(sheet.get_all_values, label="Sheets get_all_values")


async def async_row_values(sheet, row):
    return await _run_sheet_call(lambda: sheet.row_values(row), label="Sheets row_values")


async def async_cell(sheet, row, col):
    return await _run_sheet_call(lambda: sheet.cell(row, col).value, label="Sheets cell")
