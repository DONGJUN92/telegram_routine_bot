import asyncio
import os
import gspread
from dotenv import load_dotenv

load_dotenv()

# DB(구글 시트) 연결 설정 (.env 파일에서 로드)
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "(산스 AI클럽)루틴클럽")
gc = gspread.service_account(filename=os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
doc = gc.open(SHEET_NAME)

users_sheet = doc.worksheet('Users')
routines_sheet = doc.worksheet('Routines')
logs_sheet = doc.worksheet('Logs')
insights_sheet = doc.worksheet('Insights')
ai_recommendations_sheet = doc.worksheet('AI_Recommendations')
weekly_achievement_sheet = doc.worksheet('Weekly_Achievement')

async def async_find_in_col(sheet, query, column=1):
    def _find():
        try:
            return sheet.find(query, in_column=column)
        except gspread.exceptions.CellNotFound:
            return None
    return await asyncio.to_thread(_find)

async def async_findall_in_col(sheet, query, column=1):
    def _findall():
        try:
            return sheet.findall(query, in_column=column)
        except gspread.exceptions.CellNotFound:
            return []
    return await asyncio.to_thread(_findall)

async def async_append_row(sheet, row_data):
    await asyncio.to_thread(sheet.append_row, row_data)

async def async_update_cell(sheet, row, col, val):
    await asyncio.to_thread(sheet.update_cell, row, col, val)

async def async_delete_rows(sheet, row):
    await asyncio.to_thread(sheet.delete_rows, row)

async def async_get_all_records(sheet):
    return await asyncio.to_thread(sheet.get_all_records)

async def async_row_values(sheet, row):
    return await asyncio.to_thread(sheet.row_values, row)

async def async_cell(sheet, row, col):
    def _get_cell():
        try:
            return sheet.cell(row, col).value
        except:
            return None
    return await asyncio.to_thread(_get_cell)
