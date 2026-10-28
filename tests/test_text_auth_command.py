import asyncio
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main


class FakePhotoFile:
    file_path = "https://telegram.example/photo.jpg"

    async def download_as_bytearray(self):
        return bytearray(b"\x89PNG\r\n")


class FakeBot:
    async def get_file(self, _file_id):
        return FakePhotoFile()

    async def send_message(self, **kwargs):
        return None

    async def copy_message(self, **kwargs):
        return None


class FakeMessage:
    def __init__(self, message_id=101, caption=None, with_photo=False):
        self.chat = SimpleNamespace(type="private")
        self.chat_id = 9001
        self.from_user = SimpleNamespace(id=9001, first_name="Tester", username="tester")
        self.message_id = message_id
        self.link = None
        self.caption = caption
        self.photo = [SimpleNamespace(file_id="photo-file-1")] if with_photo else []
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}
        self.bot = FakeBot()


class AuthenticationAndAutoUserRegistrationTests(unittest.TestCase):
    def _update(self, message_id=101, caption=None, with_photo=False):
        return SimpleNamespace(
            message=FakeMessage(message_id=message_id, caption=caption, with_photo=with_photo)
        )

    def test_text_auth_records_input_without_routines_sheet_lookup(self):
        update = self._update()
        context = FakeContext(["Finished", "30", "minutes"])
        captured = {}

        async def fake_process_auth(**kwargs):
            captured.update(kwargs)

        with patch.object(main, "process_auth", fake_process_auth):
            asyncio.run(main.reg_text_auth(update, context))

        self.assertIsNone(captured["routine_row"])
        self.assertEqual(captured["routine_id"], main.TEXT_AUTH_ROUTINE_ID)
        self.assertEqual(captured["routine_name"], "Finished 30 minutes")
        self.assertEqual(captured["caption"], "Finished 30 minutes")
        self.assertEqual(captured["source_message_id"], 101)
        self.assertFalse(update.message.replies)

    def test_photo_auth_records_caption_immediately_without_routines_sheet(self):
        update = self._update(message_id=303, caption="오전 독서 30분 완료", with_photo=True)
        context = FakeContext()
        captured = {}

        async def fake_process_auth(**kwargs):
            captured.update(kwargs)

        with patch.object(main, "process_auth", fake_process_auth):
            asyncio.run(main.handle_photo(update, context))

        self.assertIsNone(captured["routine_row"])
        self.assertEqual(captured["routine_id"], main.PHOTO_AUTH_ROUTINE_ID)
        self.assertEqual(captured["routine_name"], "오전 독서 30분 완료")
        self.assertEqual(captured["caption"], "오전 독서 30분 완료")
        self.assertEqual(captured["file_id"], "photo-file-1")
        self.assertEqual(captured["source_message_id"], 303)
        self.assertFalse(context.user_data)

    def test_new_member_is_auto_added_to_users_sheet_and_authenticated(self):
        update = self._update(message_id=404, caption="첫 루틴 인증!", with_photo=True)
        context = FakeContext()
        appended_users = []
        appended_logs = []

        async def fake_find_in_col(sheet, query, column=1):
            self.assertEqual(sheet.title, "Users")
            self.assertEqual(query, "9001")
            return None  # 미등록 신규 회원

        async def fake_append_row(sheet, row_data):
            if sheet.title == "Users":
                appended_users.append(row_data)
            elif sheet.title == "Logs":
                appended_logs.append(row_data)
            else:
                raise AssertionError(f"Unexpected sheet write: {sheet.title}")

        with patch.object(main, "async_find_in_col", fake_find_in_col), \
             patch.object(main, "async_append_row", fake_append_row), \
             patch.object(main, "create_tracked_task", lambda coro, _label: coro.close()):
            asyncio.run(main.handle_photo(update, context))

        self.assertEqual(len(appended_users), 1)
        self.assertEqual(appended_users[0][0], "9001")
        self.assertEqual(appended_users[0][1], "Tester")
        self.assertEqual(len(appended_logs), 1)
        self.assertEqual(appended_logs[0][1], main.PHOTO_AUTH_ROUTINE_ID)
        self.assertEqual(appended_logs[0][2], "9001")
        self.assertEqual(appended_logs[0][4], "success")
        self.assertEqual(appended_logs[0][6], "첫 루틴 인증!")
        self.assertEqual(len(update.message.replies), 1)
        self.assertIn("인증입니다", update.message.replies[0][0])

    def test_only_active_commands_are_registered(self):
        source = Path("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        commands = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "CommandHandler" or len(node.args) < 2:
                continue
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[1], ast.Name):
                commands[node.args[0].value] = node.args[1].id

        self.assertEqual(
            commands,
            {
                "start": "start",
                "status": "status",
                "reg": "reg_text_auth",
            },
        )

    def test_status_reports_logs_and_attendance_without_routines_sheet(self):
        update = self._update(message_id=505)
        context = FakeContext()
        logs = [
            ["log_id", "routine_id", "user_id", "timestamp", "status", "link", "caption", "score", "routine_name"],
            ["1", "photo_auth", "9001", "2026-07-20 08:00:00", "success", "", "오전 운동 30분 완료", "", "오전 운동 30분 완료"],
        ]

        async def fake_get_all_values(sheet):
            self.assertEqual(sheet.title, "Logs")
            return logs

        with patch.object(main, "async_get_all_values", fake_get_all_values):
            asyncio.run(main.status(update, context))

        self.assertEqual(len(update.message.replies), 1)
        reply_text = update.message.replies[0][0]
        self.assertIn("누적 총 인증: 1건", reply_text)
        self.assertIn("출석률 현황", reply_text)
        self.assertIn("오전 운동 30분 완료", reply_text)

    def test_openrouter_free_model_ranking_and_sequential_fallback(self):
        import ai_utils

        sample_models = [
            {
                "id": "liquid/lfm-2.5-2.6b:free",
                "name": "Liquid 2.6B",
                "context_length": 65536,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            },
            {
                "id": "google/gemma-4-31b-it:free",
                "name": "Gemma 4 31B",
                "context_length": 262144,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            },
            {
                "id": "nvidia/nemotron-3.5-content-safety:free",
                "name": "Safety Guard",
                "context_length": 128000,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            },
            {
                "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "name": "Nemotron Ultra 550B",
                "context_length": 1000000,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            },
        ]

        ai_utils._CACHED_FREE_MODELS = sample_models
        ranked_text = asyncio.run(
            ai_utils.fetch_ranked_free_models(require_vision=False, force_refresh=False)
        )
        # Safety 모델은 제외되고 Gemma 4 31B -> Nemotron Ultra 550B -> Liquid 2.6B 순으로 정렬
        self.assertEqual(
            ranked_text,
            [
                "google/gemma-4-31b-it:free",
                "nvidia/nemotron-3-ultra-550b-a55b:free",
                "liquid/lfm-2.5-2.6b:free",
            ],
        )

        # 1순위 모델이 429 에러를 반환할 때 2순위 모델로 자동 전환되어 성공하는지 검증
        tried_models = []

        class FakeResponse:
            def __init__(self, status, payload):
                self.status = status
                self._payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def json(self, content_type=None):
                return self._payload

        def fake_post(self_session, url, headers=None, json=None, timeout=None):
            model_id = json["model"]
            tried_models.append(model_id)
            if len(tried_models) == 1:
                return FakeResponse(429, {"error": {"message": "Rate limit exceeded"}})
            return FakeResponse(
                200,
                {"choices": [{"message": {"content": "두 번째 모델에서 정상 생성된 코칭 응답입니다!"}}]},
            )

        async def fake_fetch_ranked(session=None, *, require_vision=False, force_refresh=True):
            return ranked_text

        with patch.object(ai_utils, "_get_openrouter_api_key", lambda: "sk-or-test-key"), \
             patch.object(ai_utils, "fetch_ranked_free_models", fake_fetch_ranked), \
             patch("aiohttp.ClientSession.post", fake_post):
            result = asyncio.run(
                ai_utils._call_openrouter_with_fallback(
                    [{"role": "user", "content": "테스트"}],
                    label="폴백 테스트",
                )
            )

        self.assertEqual(
            tried_models,
            ["google/gemma-4-31b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free"],
        )
        self.assertEqual(result, "두 번째 모델에서 정상 생성된 코칭 응답입니다!")

    def test_health_check_server_and_bundled_korean_fonts(self):
        import os
        import urllib.request
        import card_news

        self.assertTrue(os.path.exists(card_news.FONT_BOLD_PATH))
        self.assertTrue(os.path.exists(card_news.FONT_REGULAR_PATH))
        self.assertIn("NanumGothic", card_news.FONT_BOLD_PATH)

        with patch.dict(os.environ, {"PORT": "0"}):
            port = main.start_health_check_server()
            try:
                self.assertIsNotNone(port)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn(b'"status":"ok"', resp.read())
                head_req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="HEAD")
                with urllib.request.urlopen(head_req, timeout=5) as head_resp:
                    self.assertEqual(head_resp.status, 200)
            finally:
                main.stop_health_check_server()


if __name__ == "__main__":
    unittest.main()
