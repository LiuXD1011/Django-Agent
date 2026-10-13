import json
from unittest.mock import patch

from django.test import TestCase

from personal_knowledge_base.agent_engine import AgentResult
from personal_knowledge_base.agent_history import build_agent_history_messages
from personal_knowledge_base.authentication import issue_tokens
from personal_knowledge_base.models import Message, Session, Tenant, User
from personal_knowledge_base.stream_manager import stream_manager
from personal_knowledge_base.stream_protocol import GENERATION_FAILED_MESSAGE


class ImageGenerationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Image tenant", api_key="image-test-key")
        self.user = User.objects.create(
            username="image-user", password_hash="unused", tenant=self.tenant,
        )
        token, _ = issue_tokens(self.user)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.session = Session.objects.create(tenant=self.tenant, title="Image test")
        self.query = "图中的测试码和形状是什么？"
        self.image_url = "data:image/png;base64,AA=="
        self.caption = "测试码 ORCA-5827，左侧红色正方形，右侧蓝色圆形。"
        self.answer = "ORCA-5827；红色正方形；蓝色圆形。"
        self.vision = self.enterContext(patch(
            "personal_knowledge_base.model_providers.vision_completion",
            return_value=self.caption,
        ))
        self.engine = self.enterContext(patch("chat.views.AgentEngine")).return_value
        self.engine.execute.return_value = AgentResult(
            content=self.answer, steps=[], total_iterations=1, duration_ms=1,
        )
        self.enterContext(patch("chat.views.schedule_chat_maintenance"))
        self.enterContext(patch("chat.views._save_session_after_chat"))
        self.enterContext(patch("chat.views._build_agent_prefetch_context", return_value=("", "")))

    def tearDown(self):
        for message in Message.objects.filter(session=self.session, role="assistant"):
            stream_manager.remove_stream(message.id)

    def send(self, *, stream, images=None, query=None, attachments=None):
        with patch("chat.views.run_database_background") as background:
            response = self.client.post(
                f"/api/v1/agent-chat/{self.session.id}",
                data=json.dumps({
                    "query": self.query if query is None else query,
                    "images": [{"data": self.image_url}] if images is None else images,
                    "attachment_uploads": attachments or [],
                    "stream": stream,
                    "enable_memory": False,
                }),
                content_type="application/json",
                **self.headers,
            )
        self.assertEqual(response.status_code, 200)
        if stream:
            # 图像处理与生成留在已注册流的工作线程中，不阻塞响应头。
            self.vision.assert_not_called()
            background.call_args.args[0]()
            body = b"".join(response.streaming_content).decode("utf-8")
        else:
            body = response.json()["data"]["answer"]
        return body

    def test_streaming_image_content_reaches_agent_and_followup_history(self):
        body = self.send(stream=True)
        self.assertIn(self.answer, body)
        agent_query = self.engine.execute.call_args.args[0]
        self.assertIn(self.query, agent_query)
        self.assertIn(self.caption, agent_query)
        self.vision.assert_called_once()
        self.assertEqual(self.vision.call_args.args[1], self.image_url)
        user_message = Message.objects.get(session=self.session, role="user")
        self.assertEqual(user_message.content, self.query)
        self.assertEqual(user_message.images[0]["url"], self.image_url)
        self.assertEqual(user_message.images[0]["caption"], self.caption)
        history = build_agent_history_messages(Message.objects.filter(session=self.session))
        self.assertIn(self.caption, history[0]["content"])

    def test_synchronous_image_content_reaches_agent(self):
        self.send(stream=False)
        self.assertIn(self.caption, self.engine.execute.call_args.args[0])

    def test_plain_text_does_not_call_vision_or_change_query(self):
        self.send(stream=True, images=[])
        self.vision.assert_not_called()
        self.assertEqual(self.engine.execute.call_args.args[0], self.query)

    def test_multiple_images_keep_their_individual_descriptions(self):
        self.vision.side_effect = ["第一张是红色正方形。", "第二张是蓝色圆形。"]
        self.send(stream=True, images=[{"url": self.image_url}, self.image_url])
        query = self.engine.execute.call_args.args[0]
        self.assertIn("第一张是红色正方形。", query)
        self.assertIn("第二张是蓝色圆形。", query)
        self.assertEqual(self.vision.call_count, 2)

    def test_vision_failure_finishes_stream_without_fabricated_answer(self):
        self.vision.side_effect = RuntimeError("vision service unavailable")
        body = self.send(stream=True)
        self.engine.execute.assert_not_called()
        self.assertIn(GENERATION_FAILED_MESSAGE, body)
        assistant = Message.objects.get(session=self.session, role="assistant")
        self.assertTrue(assistant.is_completed)
        self.assertEqual(assistant.content, GENERATION_FAILED_MESSAGE)

    def test_empty_vision_response_finishes_stream_as_error(self):
        self.vision.return_value = "  "
        body = self.send(stream=True)
        self.engine.execute.assert_not_called()
        self.assertIn(GENERATION_FAILED_MESSAGE, body)

    def test_synchronous_vision_failure_persists_terminal_error_for_retry(self):
        self.headers["HTTP_X_REQUEST_ID"] = "image-sync-error"
        self.vision.side_effect = RuntimeError("vision service unavailable")
        with self.assertRaisesRegex(RuntimeError, "vision service unavailable"):
            self.send(stream=False)
        assistant = Message.objects.get(session=self.session, role="assistant")
        self.assertTrue(assistant.is_completed)
        self.assertEqual(assistant.content, GENERATION_FAILED_MESSAGE)
        self.vision.side_effect = None
        retry = self.client.post(
            f"/api/v1/agent-chat/{self.session.id}",
            data=json.dumps({"query": self.query, "stream": False}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["data"]["idempotent"])
        self.assertEqual(retry.json()["data"]["message"]["content"], GENERATION_FAILED_MESSAGE)
        self.assertTrue(retry.json()["data"]["message"]["is_completed"])
        self.assertEqual(Message.objects.filter(session=self.session).count(), 2)
        self.engine.execute.assert_not_called()

    def test_synchronous_empty_vision_response_persists_terminal_error(self):
        self.vision.return_value = "  "
        with self.assertRaises(ValueError):
            self.send(stream=False)
        assistant = Message.objects.get(session=self.session, role="assistant")
        self.assertTrue(assistant.is_completed)
        self.assertEqual(assistant.content, GENERATION_FAILED_MESSAGE)

    def test_image_enrichment_preserves_attachment_context_in_history(self):
        self.send(stream=True, attachments=[{"file_name": "notes.txt", "file_size": 123}])
        user_message = Message.objects.get(session=self.session, role="user")
        self.assertIn("notes.txt (123 bytes)", user_message.rendered_content)
        history = build_agent_history_messages(Message.objects.filter(session=self.session))
        self.assertIn(self.caption, history[0]["content"])
        self.assertIn("notes.txt (123 bytes)", history[0]["content"])
