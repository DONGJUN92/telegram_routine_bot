import asyncio
import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import main
import personal_notifications
from personal_notifications import (
    _attendance_reminder_text,
    build_monthly_owner_briefing,
)


class AttendanceDeliveryTests(unittest.TestCase):
    def test_reminder_text_uses_distinct_weeks_and_current_week_status(self):
        message = _attendance_reminder_text(
            "u1",
            {"u1": {(2026, 30)}},
            datetime(2026, 7, 20, 21, 0),
        )

        self.assertIn("이번 주: 출석 완료 (100%)", message)
        self.assertIn("4.3% (1/23주)", message)
        self.assertIn("서로 다른 18주", message)

    def test_reminder_text_marks_2026_week_53_as_exception(self):
        message = _attendance_reminder_text(
            "u1",
            {"u1": {(2026, 30), (2026, 53)}},
            datetime(2026, 12, 30, 21, 0),
        )

        self.assertIn("2026년 53주차", message)
        self.assertIn("반영되지 않습니다", message)

    def test_weekly_settlement_writes_binary_and_annual_code_values(self):
        users = [["user_id", "nickname"], ["u1", "Alice"], ["u2", "Bob"]]
        logs = [
            ["log_id", "routine_id", "user_id", "timestamp", "status"],
            ["1", "r1", "u1", "2026-07-20 08:00:00", "success"],
            ["2", "r2", "u1", "2026-07-25 20:00:00", "success"],
        ]
        attendance = [["user_id", "nickname", "overall_attendance_rate"]]
        appended_rows = []
        updated_cells = []

        async def fake_get_all_values(sheet):
            if sheet.title == "Users":
                return users
            if sheet.title == "Logs":
                return logs
            if sheet.title == "출석률":
                return attendance
            raise AssertionError(sheet.title)

        async def fake_append_rows(sheet, rows, value_input_option="RAW"):
            self.assertEqual(sheet.title, "출석률")
            appended_rows.extend(rows)

        async def fake_update_cells(sheet, cells, value_input_option="RAW"):
            self.assertEqual(sheet.title, "출석률")
            updated_cells.extend(cells)

        with patch.object(main, "async_get_all_values", fake_get_all_values), \
             patch.object(main, "async_append_rows", fake_append_rows), \
             patch.object(main, "async_update_cells", fake_update_cells):
            self.assertTrue(asyncio.run(main.update_attendance_sheet("2026-W30")))

        self.assertEqual([row[:2] for row in appended_rows], [["u1", "Alice"], ["u2", "Bob"]])
        values = {(cell.row, cell.col): cell.value for cell in updated_cells}
        headers = {value: col for (row, col), value in values.items() if row == 1}
        self.assertEqual(headers["current_year_attendance_rate"], 3)
        self.assertIn("2026-W30", headers)
        self.assertIn("2026_attended_weeks", headers)
        self.assertIn("2026_attendance_rate", headers)
        self.assertIn("2026_weeks_to_80pct", headers)

        weekly_col = headers["2026-W30"]
        attended_col = headers["2026_attended_weeks"]
        annual_rate_col = headers["2026_attendance_rate"]
        target_col = headers["2026_weeks_to_80pct"]
        self.assertEqual(values[(2, weekly_col)], 100.0)
        self.assertEqual(values[(3, weekly_col)], 0.0)
        self.assertEqual(values[(2, attended_col)], 1)
        self.assertEqual(values[(2, annual_rate_col)], 4.3)
        self.assertEqual(values[(2, target_col)], 18)

    def test_year_boundary_keeps_2026_summary_and_sets_current_year_rate_to_2027(self):
        users = [["user_id", "nickname"], ["u1", "Alice"]]
        logs = [
            ["log_id", "routine_id", "user_id", "timestamp", "status"],
            ["1", "r1", "u1", "2026-07-20 08:00:00", "success"],
            ["2", "r1", "u1", "2026-12-30 08:00:00", "success"],
        ]
        attendance = [["user_id", "nickname", "overall_attendance_rate"]]
        updated_cells = []

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2027, 1, 4, 0, 6, tzinfo=tz)

        async def fake_get_all_values(sheet):
            if sheet.title == "Users":
                return users
            if sheet.title == "Logs":
                return logs
            if sheet.title == "출석률":
                return attendance
            raise AssertionError(sheet.title)

        async def fake_append_rows(sheet, rows, value_input_option="RAW"):
            return None

        async def fake_update_cells(sheet, cells, value_input_option="RAW"):
            updated_cells.extend(cells)

        with patch.object(main, "datetime", FixedDatetime), \
             patch.object(main, "async_get_all_values", fake_get_all_values), \
             patch.object(main, "async_append_rows", fake_append_rows), \
             patch.object(main, "async_update_cells", fake_update_cells):
            self.assertTrue(asyncio.run(main.update_attendance_sheet("2026-W53")))

        values = {(cell.row, cell.col): cell.value for cell in updated_cells}
        headers = {value: col for (row, col), value in values.items() if row == 1}
        self.assertIn("2026_attendance_rate", headers)
        self.assertIn("2027_attendance_rate", headers)
        self.assertEqual(values[(2, headers["2026-W53"])], 100.0)
        self.assertEqual(values[(2, headers["current_year_attendance_rate"])], 0.0)
        self.assertEqual(values[(2, headers["2026_attendance_rate"])], 4.3)
        self.assertEqual(values[(2, headers["2027_attendance_rate"])], 0.0)

    def test_evening_job_appends_the_attendance_block(self):
        messages = []

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 20, 21, 0, tzinfo=tz)

        async def fake_recipients(_):
            return [{"user_id": "u1", "chat_id": "u1"}]

        async def fake_get_all_values(sheet):
            self.assertEqual(sheet.title, "Logs")
            return [
                ["log_id", "routine_id", "user_id", "timestamp", "status"],
                ["1", "r1", "u1", "2026-07-20 08:00:00", "success"],
            ]

        async def fake_send(context, factory, *, label, parse_mode=None, recipients=None):
            messages.append(factory(recipients[0]))
            return 1

        with patch.object(personal_notifications, "datetime", FixedDatetime), \
             patch.object(personal_notifications, "_daily_recipients", fake_recipients), \
             patch.object(personal_notifications, "async_get_all_values", fake_get_all_values), \
             patch.object(personal_notifications, "send_text_notifications", fake_send):
            self.assertEqual(
                asyncio.run(personal_notifications.evening_reminder_notification_job(object())),
                1,
            )

        self.assertIn("📅 2026년 출석 현황", messages[0])
        self.assertIn("이번 주: 출석 완료 (100%)", messages[0])
        self.assertIn("4.3% (1/23주)", messages[0])

    def test_monday_attendance_settlement_job_is_scheduled_at_00_06(self):
        source = Path("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        jobs = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "run_daily" or not node.args or not isinstance(node.args[0], ast.Name):
                continue
            name = node.args[0].id
            kwargs = {keyword.arg: keyword.value for keyword in node.keywords}
            if name == "settle_weekly_attendance":
                jobs[name] = (node.args[1], kwargs)

        self.assertEqual(set(jobs), {"settle_weekly_attendance"})
        time_call, kwargs = jobs["settle_weekly_attendance"]
        self.assertIsInstance(time_call, ast.Call)
        minute = next(
            keyword.value.value
            for keyword in time_call.keywords
            if keyword.arg == "minute"
        )
        self.assertEqual(minute, 6)
        self.assertIsInstance(kwargs["job_kwargs"], ast.Name)
        self.assertEqual(kwargs["job_kwargs"].id, "SCHEDULED_JOB_KWARGS")

    def test_monthly_sync_and_owner_briefing_is_scheduled_on_day_1_at_00_15(self):
        source = Path("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        monthly_calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "run_monthly" and node.args and isinstance(node.args[0], ast.Name):
                monthly_calls.append((node.args[0].id, {kw.arg: kw.value for kw in node.keywords}))

        self.assertEqual(len(monthly_calls), 1)
        func_name, kwargs = monthly_calls[0]
        self.assertEqual(func_name, "monthly_sync_and_owner_briefing_job")
        self.assertEqual(kwargs["day"].value, 1)
        when_call = kwargs["when"]
        hour = next(kw.value.value for kw in when_call.keywords if kw.arg == "hour")
        minute = next(kw.value.value for kw in when_call.keywords if kw.arg == "minute")
        self.assertEqual((hour, minute), (0, 15))

    def test_group_member_sync_adds_missing_group_members_and_removes_left_users(self):
        from types import SimpleNamespace

        users = [
            ["user_id", "nickname", "join_date"],
            ["1001", "ExistingMember", "2026-07-01 09:00:00"],
            ["1002", "LeftMember", "2026-07-01 09:00:00"],
        ]
        logs = [
            ["log_id", "routine_id", "user_id", "timestamp", "status"],
            ["1", "photo_auth", "1003", "2026-09-10 08:00:00", "success"],
        ]
        deleted_rows = []
        appended_rows = []

        class FakeBot:
            async def get_chat_administrators(self, chat_id):
                return [
                    SimpleNamespace(
                        user=SimpleNamespace(id=1004, is_bot=False, first_name="NewAdmin", username="admin")
                    )
                ]

            async def get_chat_member(self, chat_id, user_id):
                status_map = {
                    1001: ("member", "ExistingMember"),
                    1002: ("left", "LeftMember"),
                    1003: ("member", "ActiveFromLog"),
                }
                st, name = status_map[int(user_id)]
                return SimpleNamespace(
                    status=st,
                    is_member=(st == "member"),
                    user=SimpleNamespace(id=int(user_id), is_bot=False, first_name=name, username=name),
                )

        async def fake_get_all_values(sheet):
            if sheet.title == "Users":
                return users
            if sheet.title == "Logs":
                return logs
            raise AssertionError(sheet.title)

        async def fake_delete_rows(sheet, row):
            self.assertEqual(sheet.title, "Users")
            deleted_rows.append(row)

        async def fake_append_rows(sheet, rows, value_input_option="RAW"):
            self.assertEqual(sheet.title, "Users")
            appended_rows.extend(rows)

        main._KNOWN_GROUP_MEMBERS.clear()
        context = SimpleNamespace(bot=FakeBot())
        with patch.object(main, "GROUP_CHAT_ID", "-100123456"), \
             patch.object(main, "async_get_all_values", fake_get_all_values), \
             patch.object(main, "async_delete_rows", fake_delete_rows), \
             patch.object(main, "async_append_rows", fake_append_rows):
            result = asyncio.run(main.sync_group_members_job(context))

        # 1002(left)는 3번째 행이므로 삭제되고, 1003(그룹 내 활성) 및 1004(관리자)는 추가됨
        self.assertEqual(deleted_rows, [3])
        added_ids = {row[0] for row in appended_rows}
        self.assertEqual(added_ids, {"1003", "1004"})
        self.assertEqual(result, {"added": 2, "removed": 1})

    def test_monthly_owner_briefing_lists_weekly_certified_and_uncertified_members(self):
        users = [
            ["user_id", "nickname"],
            ["1001", "홍길동"],
            ["1002", "김철수"],
        ]
        logs = [
            ["log_id", "routine_id", "user_id", "timestamp", "status"],
            ["1", "text_auth", "1001", "2026-10-02 09:00:00", "success"],
            ["2", "photo_auth", "1001", "2026-10-08 09:00:00", "success"],
            ["3", "photo_auth", "1002", "2026-10-09 20:00:00", "success"],
        ]

        report = build_monthly_owner_briefing(users, logs, 2026, 10)
        self.assertIn("2026년 10월 산스 AI루틴클럽 월간 인증률 브리핑", report)
        self.assertIn("Users 시트 기준 전체 인원: 2명", report)
        self.assertIn("월간 전체 인증률 (1회 이상 인증 인원 비율): 100.0% (2/2명)", report)
        self.assertIn("1주차 (2026-W40 | 10/01~10/04) — 인증률 50.0% (1/2명)", report)
        self.assertIn("✅ 인증한 사람 (1명): 홍길동", report)
        self.assertIn("❌ 인증하지 않은 사람 (1명): 김철수", report)
        self.assertIn("2주차 (2026-W41 | 10/05~10/11) — 인증률 100.0% (2/2명)", report)
        self.assertIn("✅ 인증한 사람 (2명): 홍길동, 김철수", report)
        self.assertIn("❌ 인증하지 않은 사람 (0명): 없음", report)


if __name__ == "__main__":
    unittest.main()
