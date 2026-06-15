import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from assistant import services as assistant_services
from assistant.memory import search_memories
from assistant.models import AgentEvent, AgentRun, ChatMessage, Conversation, ConversationMemory
from drive import services as drive_services
from drive.models import UserFile
from knowledge.models import KBDocument, KnowledgeBase, WikiPage
from knowledge import services as kb_services
from knowledge import wiki_services


class AssistantTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="StrongPass123!")
        self.client.force_login(self.user)

    def fake_planner_openai(self, plan):
        class FakeChatCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan))])

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeChatCompletions())

        return FakeOpenAI

    def fake_stream_openai(self, tokens=None):
        tokens = tokens or ["好的"]

        class FakeChatCompletions:
            def create(self, **kwargs):
                return iter(
                    [
                        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=token))])
                        for token in tokens
                    ]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeChatCompletions())

        return FakeOpenAI

    def create_drive_files(self, count=10):
        for index in range(1, count + 1):
            UserFile.objects.create(
                user=self.user,
                name=f"{index:02d}. 测试文件.pdf",
                is_folder=False,
                file_size=index * 1024,
                suffix="pdf",
            )

    @override_settings(LLM_API_KEY="")
    def test_drive_stream_works_without_llm_key(self):
        response = self.client.post(reverse("assistant:stream"), {"use_drive": "1", "message": "容量"})
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("已使用", body)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        self.assertEqual(root.status, AgentRun.STATUS_SUCCESS)
        self.assertIn("drive", list(root.child_runs.values_list("agent_name", flat=True)))
        self.assertTrue(AgentEvent.objects.filter(run=root, event_type="planner").exists())

    def test_drive_context_includes_complete_file_list_when_small(self):
        self.create_drive_files(10)

        context = assistant_services.drive_context(self.user, "我现在有多少个文件")

        self.assertIn("数量：10 个文件", context)
        self.assertIn("文件清单（共 10 个，已全部列出）", context)
        for index in range(1, 11):
            self.assertIn(f"{index:02d}. 测试文件.pdf", context)

    @override_settings(LLM_API_KEY="")
    def test_drive_followup_can_list_all_files_without_llm_key(self):
        self.create_drive_files(10)

        response = self.client.post(reverse("assistant:stream"), {"use_drive": "1", "message": "哪10个？"})
        body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("当前文件（共 10 个，已全部列出）", body)
        for index in range(1, 11):
            self.assertIn(f"{index:02d}. 测试文件.pdf", body)

    def test_conversation_history_is_isolated(self):
        first = Conversation.objects.create(user=self.user, title="第一段")
        second = Conversation.objects.create(user=self.user, title="第二段")
        ChatMessage.objects.create(user=self.user, conversation=first, role="user", content="第一段内容")
        ChatMessage.objects.create(user=self.user, conversation=second, role="user", content="第二段内容")

        response = self.client.get(reverse("assistant:index"), {"conversation": first.id})

        self.assertContains(response, "第一段内容")
        self.assertNotContains(response, "第二段内容")
        self.assertContains(response, f'name="conversation_id" value="{first.id}"')

    def test_assistant_index_reuses_existing_conversation_without_query_param(self):
        conversation = Conversation.objects.create(user=self.user, title="已有对话")

        first_response = self.client.get(reverse("assistant:index"))
        second_response = self.client.get(reverse("assistant:index"))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 1)
        self.assertContains(second_response, f'name="conversation_id" value="{conversation.id}"')

    def test_top_navigation_marks_current_section_active(self):
        cases = [
            ("drive:file_list", "文件库"),
            ("assistant:index", "AI助手"),
            ("knowledge:index", "知识库"),
        ]

        for url_name, label in cases:
            with self.subTest(url_name=url_name):
                url = reverse(url_name)
                response = self.client.get(url)
                self.assertContains(
                    response,
                    f'<a class="active" aria-current="page" href="{url}">{label}</a>',
                    html=True,
                )

    @override_settings(LLM_API_KEY="")
    def test_stream_saves_messages_to_selected_conversation(self):
        first = Conversation.objects.create(user=self.user, title="第一段")
        second = Conversation.objects.create(user=self.user, title="第二段")

        response = self.client.post(
            reverse("assistant:stream"),
            {"conversation_id": first.id, "message": "你好"},
        )
        b"".join(response.streaming_content)

        self.assertEqual(ChatMessage.objects.filter(conversation=first).count(), 2)
        self.assertEqual(ChatMessage.objects.filter(conversation=second).count(), 0)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        self.assertEqual(root.metadata["conversation_id"], first.id)

    def test_delete_conversation_removes_messages_but_keeps_memory(self):
        conversation = Conversation.objects.create(user=self.user, title="可删除对话")
        message = ChatMessage.objects.create(
            user=self.user,
            conversation=conversation,
            role="assistant",
            content="需要删除的聊天记录",
        )
        memory = ConversationMemory.objects.create(
            user=self.user,
            scope=ConversationMemory.SCOPE_USER,
            content="用户希望保留长期记忆。",
            source_conversation=conversation,
            source_message=message,
        )

        response = self.client.post(reverse("assistant:conversation_delete", args=[conversation.id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Conversation.objects.filter(id=conversation.id).exists())
        self.assertFalse(ChatMessage.objects.filter(id=message.id).exists())
        memory.refresh_from_db()
        self.assertIsNone(memory.source_conversation)
        self.assertIsNone(memory.source_message)

    def test_conversation_memory_fts_syncs_active_and_archived_items(self):
        memory = ConversationMemory.objects.create(
            user=self.user,
            scope=ConversationMemory.SCOPE_USER,
            kind=ConversationMemory.KIND_PREFERENCE,
            content="用户偏好：回答要简洁并给出明确下一步。",
            content_hash="pref-1",
        )

        self.assertEqual([item.id for item in search_memories(self.user, "回答要简洁")], [memory.id])

        memory.status = ConversationMemory.STATUS_ARCHIVED
        memory.save(update_fields=["status", "updated_at"])

        self.assertEqual(search_memories(self.user, "回答要简洁"), [])

    def test_memory_management_page_lists_and_removes_only_current_user_memory(self):
        other = User.objects.create_user(username="bob", password="StrongPass123!")
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        memory = ConversationMemory.objects.create(
            user=self.user,
            kb=kb,
            scope=ConversationMemory.SCOPE_KB,
            kind=ConversationMemory.KIND_FACT,
            content="知识库包含 SQLite 检索设计。",
            content_hash="memory-1",
        )
        ConversationMemory.objects.create(
            user=other,
            scope=ConversationMemory.SCOPE_USER,
            kind=ConversationMemory.KIND_FACT,
            content="其他用户的私有记忆。",
            content_hash="memory-2",
        )

        response = self.client.get(reverse("assistant:memories"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "长期记忆")
        self.assertContains(response, "知识库包含 SQLite 检索设计")
        self.assertNotContains(response, "其他用户的私有记忆")

        response = self.client.post(reverse("assistant:memory_remove", args=[memory.id]))

        self.assertEqual(response.status_code, 302)
        memory.refresh_from_db()
        self.assertEqual(memory.status, ConversationMemory.STATUS_ARCHIVED)
        self.assertEqual(search_memories(self.user, "SQLite 检索", kb=kb), [])

    def test_run_debug_pages_are_admin_only(self):
        root = AgentRun.objects.create(
            user=self.user,
            agent_name="assistant_orchestrator",
            status=AgentRun.STATUS_SUCCESS,
            input={"message": "你好"},
            output={"answer": "您好"},
            metadata={"agent_plan": {"planner": "fallback"}},
        )
        child = AgentRun.objects.create(
            user=self.user,
            parent_run=root,
            agent_name="answer",
            status=AgentRun.STATUS_SUCCESS,
        )
        AgentEvent.objects.create(run=root, event_type="planner", payload={"use_rag": False})

        response = self.client.get(reverse("assistant:runs"))
        self.assertEqual(response.status_code, 302)

        admin = User.objects.create_superuser(username="root", password="StrongPass123!", email="root@example.com")
        self.client.force_login(admin)

        response = self.client.get(reverse("assistant:runs"))
        self.assertContains(response, "运行调试")
        self.assertContains(response, "assistant_orchestrator")

        response = self.client.get(reverse("assistant:run_detail", args=[root.id]))
        self.assertContains(response, "运行 #")
        self.assertContains(response, "planner")
        self.assertContains(response, "agent_plan")
        self.assertContains(response, f"#{child.id} answer")

    @override_settings(LLM_API_KEY="")
    def test_memory_manager_skips_without_llm_but_titles_conversation(self):
        conversation = Conversation.objects.create(user=self.user, title="新对话")

        response = self.client.post(
            reverse("assistant:stream"),
            {"conversation_id": conversation.id, "message": "帮我整理 SQLite 知识"},
        )
        body = b"".join(response.streaming_content).decode("utf-8")

        conversation.refresh_from_db()
        self.assertIn("conversation", body)
        self.assertEqual(conversation.title, "帮我整理 SQLite 知识")
        self.assertEqual(ConversationMemory.objects.count(), 0)

    @override_settings(
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://example.com/v1",
        LLM_MODEL="test-model",
        ASSISTANT_MEMORY_AUTO_ENABLED=True,
    )
    def test_memory_manager_updates_checkpoint_and_memory_with_mock_llm(self):
        conversation = Conversation.objects.create(user=self.user, title="新对话")
        memory_payload = (
            '{"title":"SQLite 记忆","checkpoint":"用户正在整理 SQLite 相关知识，下一步继续补充检索方案。",'
            '"memories":[{"scope":"user","kind":"preference","content":"用户希望回答包含明确下一步。"}]}'
        )

        with patch("assistant.services.OpenAI", self.fake_stream_openai(["已记录"])), patch(
            "assistant.memory.OpenAI",
            self.fake_planner_openai(memory_payload),
        ):
            response = self.client.post(
                reverse("assistant:stream"),
                {"conversation_id": conversation.id, "message": "记住我想要明确下一步"},
            )
            b"".join(response.streaming_content)

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "SQLite 记忆")
        self.assertIn("SQLite", conversation.checkpoint)
        memory = ConversationMemory.objects.get()
        self.assertEqual(memory.source_conversation, conversation)
        self.assertEqual([item.id for item in search_memories(self.user, "明确下一步")], [memory.id])

    def test_assistant_page_does_not_render_chat_messages_as_django_messages(self):
        ChatMessage.objects.create(user=self.user, role="user", content="你好")
        ChatMessage.objects.create(user=self.user, role="assistant", content="您好")

        response = self.client.get(reverse("assistant:index"))

        self.assertContains(response, "你好")
        self.assertContains(response, "您好")
        self.assertNotContains(response, "ChatMessage object")

    def test_assistant_page_has_single_entry_controls(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")

        response = self.client.get(reverse("assistant:index"), {"kb": kb.id})

        self.assertContains(response, "assistant-page")
        self.assertContains(response, "assistant-thread")
        self.assertContains(response, "assistant-composer")
        self.assertContains(response, "使用文件库")
        self.assertContains(response, "不使用知识库")
        self.assertContains(response, "产品资料")
        self.assertContains(response, "今天想整理什么？")
        self.assertContains(response, "data-delete-confirm")
        self.assertContains(response, "删除这个对话？")
        self.assertNotContains(response, "允许使用文件信息")
        self.assertNotContains(response, "<span>使用文件信息</span>", html=True)
        self.assertNotContains(response, '<span class="field-label">知识库</span>', html=True)
        self.assertNotContains(response, "文档助手")
        self.assertNotContains(response, "统一问答")

    def test_assistant_history_uses_chat_message_markup(self):
        ChatMessage.objects.create(user=self.user, role="user", content="你好")
        ChatMessage.objects.create(user=self.user, role="assistant", content="您好")

        response = self.client.get(reverse("assistant:index"))

        self.assertContains(response, "chat-message-user")
        self.assertContains(response, "chat-message-assistant")
        self.assertContains(response, "chat-message-content")

    def test_assistant_history_renders_basic_markdown(self):
        ChatMessage.objects.create(
            user=self.user,
            role="assistant",
            content="### 报告摘要\n\n1. **报告.pdf**（1.7MB，pdf）\n\n*注：这是说明*",
        )

        response = self.client.get(reverse("assistant:index"))

        self.assertContains(response, "<h5>报告摘要</h5>", html=False)
        self.assertContains(response, "<ol>", html=False)
        self.assertContains(response, "<strong>报告.pdf</strong>", html=False)
        self.assertContains(response, "<em>注：这是说明</em>", html=False)
        self.assertNotContains(response, "### 报告摘要")
        self.assertNotContains(response, "**报告.pdf**")
        self.assertNotContains(response, "*注：这是说明*")

    def test_assistant_frontend_streaming_static_guards(self):
        js = Path(settings.BASE_DIR / "static/js/app.js").read_text(encoding="utf-8")

        self.assertNotIn(".stream-output:last-child", js)
        self.assertNotIn("JSON.stringify(payload.data)", js)
        self.assertNotIn("confirm(", js)
        self.assertIn("function renderReferences", js)
        self.assertIn("function appendChatMessage", js)
        self.assertIn("function renderAssistantMarkdown", js)
        self.assertIn("function renderInlineMarkdown", js)
        self.assertIn("const heading = line.match", js)
        self.assertIn("data-markdown-output", js)
        self.assertIn("openDeleteConfirm", js)
        self.assertIn("data-delete-confirm-submit", js)
        self.assertIn("submit.disabled = true", js)
        self.assertIn('event.key !== "Enter"', js)
        self.assertIn("event.shiftKey", js)
        self.assertIn("assistantForm.requestSubmit()", js)
        self.assertIn('textarea.value = ""', js)
        self.assertIn("function showProcessingIndicator", js)
        self.assertIn("function removeProcessingIndicator", js)
        self.assertIn("assistant-processing", js)
        self.assertIn("响应解析失败", js)

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_chat_stream_ignores_empty_choices_chunks(self):
        class FakeChatCompletions:
            def create(self, **kwargs):
                return iter(
                    [
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(delta=SimpleNamespace(content="您好！"))
                            ]
                        ),
                        SimpleNamespace(choices=[]),
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(delta=SimpleNamespace(content="请问有什么可以帮您？"))
                            ]
                        ),
                    ]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeChatCompletions())

        with patch("assistant.services.OpenAI", FakeOpenAI):
            response = self.client.post(reverse("assistant:stream"), {"message": "你好"})
            body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("您好！", body)
        self.assertIn("请问有什么可以帮您？", body)
        self.assertNotIn("list index out of range", body)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        self.assertEqual(list(root.child_runs.order_by("id").values_list("agent_name", flat=True)), ["answer"])

    @override_settings(
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://example.com/v1",
        LLM_MODEL="test-model",
        TIME_ZONE="Asia/Shanghai",
    )
    def test_llm_tokens_injects_current_environment(self):
        captured = {}

        class FakeChatCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="好的"))])])

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=FakeChatCompletions())

        with patch("assistant.services.OpenAI", FakeOpenAI):
            self.assertEqual("".join(assistant_services.llm_tokens("今天是星期几？", system="系统提示")), "好的")

        system_prompt = captured["messages"][0]["content"]
        self.assertIn("系统提示", system_prompt)
        self.assertIn("<env>", system_prompt)
        self.assertIn("当前日期:", system_prompt)
        self.assertIn("当前星期:", system_prompt)
        self.assertIn("当前时间:", system_prompt)
        self.assertIn("当前时区: Asia/Shanghai", system_prompt)
        self.assertIn("不要声称无法获取当前日期或时间", system_prompt)

    @override_settings(LLM_API_KEY="", TIME_ZONE="Asia/Shanghai")
    def test_date_question_uses_local_fallback_without_llm_key(self):
        answer = "".join(assistant_services.llm_tokens("今天是星期几？"))

        self.assertIn("今天是", answer)
        self.assertIn("星期", answer)
        self.assertNotIn("未配置 LLM_API_KEY", answer)

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_llm_planner_can_call_only_drive_agent(self):
        plan = '{"use_drive": true, "use_wiki": false, "use_rag": false, "reason": "需要查看文件容量"}'
        with patch("assistant.agents.OpenAI", self.fake_planner_openai(plan)), patch(
            "assistant.services.OpenAI", self.fake_stream_openai(["已整理"])
        ), patch("knowledge.wiki_services.search_wiki_pages") as wiki_search, patch(
            "knowledge.services.search"
        ) as rag_search:
            response = self.client.post(reverse("assistant:stream"), {"use_drive": "1", "message": "容量"})
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("已整理", body)
        wiki_search.assert_not_called()
        rag_search.assert_not_called()
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        self.assertEqual(root.metadata["agent_plan"]["planner"], "llm")
        self.assertEqual(list(root.child_runs.order_by("id").values_list("agent_name", flat=True)), ["drive", "answer"])

    @override_settings(LLM_API_KEY="test-key", LLM_BASE_URL="https://example.com/v1", LLM_MODEL="test-model")
    def test_planner_suppresses_unavailable_drive_capability(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        plan = '{"use_drive": true, "use_wiki": false, "use_rag": false, "reason": "想看文件"}'
        with patch("assistant.agents.OpenAI", self.fake_planner_openai(plan)), patch(
            "assistant.services.OpenAI", self.fake_stream_openai(["普通回答"])
        ):
            response = self.client.post(reverse("assistant:stream"), {"kb_id": str(kb.id), "message": "帮我看看"})
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("普通回答", body)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        self.assertIn("drive", root.metadata["agent_plan"]["suppressed_capabilities"])
        self.assertNotIn("drive", list(root.child_runs.values_list("agent_name", flat=True)))

    @override_settings(EMBEDDING_API_KEY="", LLM_API_KEY="test-key", RERANK_API_KEY="")
    def test_selected_kb_filename_match_forces_rag_when_planner_selects_drive_only(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="论文知识库")
        title = "09. Adaptive Partial Momentum Hamiltonian Monte Carlo.pdf"
        kb_services.ingest_text(
            kb,
            "text",
            "manual",
            title,
            "Adaptive Partial Momentum Hamiltonian Monte Carlo 提出自适应动量更新策略。",
        )
        plan = '{"use_drive": true, "use_wiki": false, "use_rag": false, "reason": "文件名搜索"}'

        with patch("assistant.agents.OpenAI", self.fake_planner_openai(plan)), patch(
            "assistant.services.OpenAI", self.fake_stream_openai(["已整理"])
        ), patch("knowledge.services.rewrite_rag_queries", return_value=["Adaptive Partial Momentum Hamiltonian Monte Carlo.pdf"]):
            response = self.client.post(
                reverse("assistant:stream"),
                {
                    "use_drive": "1",
                    "kb_id": str(kb.id),
                    "message": "Adaptive Partial Momentum Hamiltonian Monte Carlo.pdf",
                },
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("references", body)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        child_agents = list(root.child_runs.order_by("id").values_list("agent_name", flat=True))
        self.assertIn("drive", child_agents)
        self.assertIn("knowledge_rag", child_agents)
        self.assertIn("answer", child_agents)
        self.assertTrue(root.metadata["agent_plan"]["use_rag"])
        self.assertEqual(
            root.metadata["agent_plan"]["deterministic_overrides"][0]["reason"],
            "message_matches_ready_document",
        )

    @override_settings(LLM_API_KEY="", EMBEDDING_API_KEY="", RERANK_API_KEY="")
    def test_use_file_library_temporarily_parses_mentioned_txt_without_kb(self):
        drive_services.save_uploaded_file(
            self.user,
            SimpleUploadedFile("notes.txt", "Alpha 项目计划包含检索评估。".encode("utf-8"), content_type="text/plain"),
        )

        response = self.client.post(reverse("assistant:stream"), {"use_drive": "1", "message": "notes.txt 的内容是什么"})
        body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("文件库临时解析内容", body)
        self.assertIn("Alpha 项目计划包含检索评估", body)
        self.assertEqual(KBDocument.objects.count(), 0)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        drive_run = root.child_runs.get(agent_name="drive")
        self.assertEqual(drive_run.output["metadata"]["file_content"]["parsed_files"][0]["name"], "notes.txt")

    @override_settings(LLM_API_KEY="test-key", EMBEDDING_API_KEY="", RERANK_API_KEY="")
    def test_file_library_title_fragment_forces_drive_even_when_planner_selects_rag_without_kb(self):
        drive_services.save_uploaded_file(
            self.user,
            SimpleUploadedFile(
                "01. FedACo - Adaptive Collaboration for Personalized Federated Learning.txt",
                "FedACo 提出面向个性化联邦学习的自适应协作机制。".encode("utf-8"),
                content_type="text/plain",
            ),
        )
        plan = '{"use_drive": false, "use_wiki": false, "use_rag": true, "reason": "需要 RAG"}'

        with patch("assistant.agents.OpenAI", self.fake_planner_openai(plan)), patch(
            "assistant.services.OpenAI", self.fake_stream_openai(["已基于文件内容回答"])
        ):
            response = self.client.post(
                reverse("assistant:stream"),
                {
                    "use_drive": "1",
                    "message": "Adaptive Collaboration for Personalized Federated Learning这个文件的具体内容是啥",
                },
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("已基于文件内容回答", body)
        root = AgentRun.objects.get(agent_name="assistant_orchestrator")
        self.assertIn("drive", list(root.child_runs.order_by("id").values_list("agent_name", flat=True)))
        self.assertTrue(root.metadata["agent_plan"]["use_drive"])
        self.assertIn("knowledge_rag", root.metadata["agent_plan"]["suppressed_capabilities"])
        self.assertEqual(
            root.metadata["agent_plan"]["deterministic_overrides"][0]["reason"],
            "message_matches_file_library_file",
        )
        drive_run = root.child_runs.get(agent_name="drive")
        self.assertEqual(
            drive_run.output["metadata"]["file_content"]["parsed_files"][0]["name"],
            "01. FedACo - Adaptive Collaboration for Personalized Federated Learning.txt",
        )

    @override_settings(LLM_API_KEY="", EMBEDDING_API_KEY="", RERANK_API_KEY="")
    def test_mentioned_file_is_not_parsed_when_file_library_disabled(self):
        drive_services.save_uploaded_file(
            self.user,
            SimpleUploadedFile("notes.txt", b"private text", content_type="text/plain"),
        )

        with patch("knowledge.services.parse_user_file_result") as parser:
            response = self.client.post(reverse("assistant:stream"), {"message": "notes.txt 的内容是什么"})
            body = b"".join(response.streaming_content).decode("utf-8")

        parser.assert_not_called()
        self.assertNotIn("文件库临时解析内容", body)

    @override_settings(LLM_API_KEY="", EMBEDDING_API_KEY="", RERANK_API_KEY="")
    def test_file_library_parse_limit_asks_user_to_narrow_scope(self):
        for index in range(1, 5):
            UserFile.objects.create(
                user=self.user,
                name=f"project-report-{index}.txt",
                is_folder=False,
                file_size=100,
                suffix="txt",
            )

        with patch("knowledge.services.parse_user_file_result") as parser:
            response = self.client.post(reverse("assistant:stream"), {"use_drive": "1", "message": "project-report"})
            body = b"".join(response.streaming_content).decode("utf-8")

        parser.assert_not_called()
        self.assertIn("命中文件超过 3 个", body)

    @override_settings(EMBEDDING_API_KEY="", LLM_API_KEY="", RERANK_API_KEY="")
    def test_kb_stream_returns_references(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        kb_services.ingest_text(kb, "text", "manual", "手动文本", "知识库资料包含向量检索和引用返回。")

        response = self.client.post(reverse("assistant:stream"), {"kb_id": str(kb.id), "message": "知识库资料包含什么"})
        body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("references", body)
        self.assertIn("chunk_id", body)

    @override_settings(EMBEDDING_API_KEY="", LLM_API_KEY="", RERANK_API_KEY="")
    def test_stream_rejects_other_users_kb(self):
        other = User.objects.create_user(username="bob", password="StrongPass123!")
        kb = KnowledgeBase.objects.create(user=other, name="私有资料")

        response = self.client.post(reverse("assistant:stream"), {"kb_id": str(kb.id), "message": "看看资料"})
        body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("选择的知识库不存在或不可用", body)
        self.assertNotIn("私有资料", body)

    @override_settings(EMBEDDING_API_KEY="", LLM_API_KEY="", RERANK_API_KEY="")
    def test_drive_and_kb_stream_keeps_references(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        kb_services.ingest_text(kb, "text", "manual", "手动文本", "知识库资料包含文件管理能力。")

        response = self.client.post(
            reverse("assistant:stream"),
            {"use_drive": "1", "kb_id": str(kb.id), "message": "文件管理能力是什么"},
        )
        body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn("文件信息", body)
        self.assertIn("references", body)
        self.assertIn("chunk_id", body)

    @override_settings(EMBEDDING_API_KEY="", LLM_API_KEY="", RERANK_API_KEY="")
    def test_kb_stream_returns_wiki_and_chunk_reference_types(self):
        kb = KnowledgeBase.objects.create(user=self.user, name="产品资料")
        kb_services.ingest_text(kb, "text", "manual", "手动文本", "原始 chunk 说明 SQLite 检索。")
        page = WikiPage.objects.create(
            kb=kb,
            page_type=WikiPage.TYPE_OVERVIEW,
            slug="overview",
            title="知识库总览",
            content="## Topic Summary\nWiki 页面说明 SQLite 检索和结构化知识。",
            summary="Wiki 页面说明 SQLite 检索和结构化知识。",
            status=WikiPage.STATUS_READY,
        )
        wiki_services.upsert_wiki_page_indexes(page)

        response = self.client.post(reverse("assistant:stream"), {"kb_id": str(kb.id), "message": "SQLite 检索"})
        body = b"".join(response.streaming_content).decode("utf-8")

        self.assertIn('"type": "wiki_page"', body)
        self.assertIn('"type": "chunk"', body)
        self.assertIn("wiki_page_id", body)
        self.assertIn("chunk_id", body)
        self.assertIn("agent_run_id", body)
        assistant = ChatMessage.objects.filter(role="assistant").latest("created_at")
        self.assertIn("run_id", assistant.metadata)
        self.assertIn("child_run_ids", assistant.metadata)
        self.assertIn("agent_plan", assistant.metadata)

    def test_unify_assistant_messages_migration_logic(self):
        ChatMessage.objects.create(user=self.user, agent_type="doc", role="user", content="旧文档")
        ChatMessage.objects.create(user=self.user, agent_type="answer", role="assistant", content="旧统一")
        ChatMessage.objects.create(user=self.user, agent_type="chat", role="user", content="旧聊天")
        ChatMessage.objects.create(user=self.user, agent_type="pan", role="assistant", content="旧文件信息")
        ChatMessage.objects.create(user=self.user, agent_type="kb", role="assistant", content="旧知识库")

        migration = importlib.import_module("assistant.migrations.0003_unify_assistant_entry")
        migration.unify_assistant_messages(apps, None)

        self.assertFalse(ChatMessage.objects.filter(content__in=["旧文档", "旧统一"]).exists())
        merged = ChatMessage.objects.filter(agent_type="assistant").order_by("content")
        self.assertEqual(merged.count(), 3)
        self.assertEqual(
            {item.metadata["legacy_agent_type"] for item in merged},
            {"chat", "pan", "kb"},
        )

    # Create your tests here.
