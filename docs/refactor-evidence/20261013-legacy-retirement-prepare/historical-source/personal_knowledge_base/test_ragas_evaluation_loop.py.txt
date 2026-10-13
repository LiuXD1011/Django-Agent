import json
from unittest.mock import Mock, patch

from django.test import Client, TestCase, override_settings

from . import rag_eval, ragas_adapter
from .models import AuthToken, GenericResource, ModelConfig, Tenant, User


class RagasAdapterTests(TestCase):
    @override_settings(LLM_USE_ENV_CHAT=False, LLM_USE_ENV_EMBEDDING=False)
    def test_ragas_clients_use_selected_tenant_models(self):
        tenant = Tenant.objects.create(name="ragas-model-tenant", api_key="ragas-model-key")
        ModelConfig.objects.create(
            id="judge-model-id",
            tenant=tenant,
            name="judge-model",
            type="KnowledgeQA",
            source="openai",
            parameters={"base_url": "https://judge.example/v1", "api_key": "judge-key", "model": "judge-model"},
        )
        ModelConfig.objects.create(
            id="embedding-model-id",
            tenant=tenant,
            name="embedding-model",
            type="Embedding",
            source="openai",
            is_default=True,
            parameters={"base_url": "https://embedding.example/v1", "api_key": "embedding-key", "model": "embedding-model", "dimension": 1024},
        )

        with patch("langchain_openai.ChatOpenAI") as chat_class, patch("langchain_openai.OpenAIEmbeddings") as embedding_class:
            chat, embeddings = ragas_adapter._clients(tenant, "judge-model-id")

        self.assertIs(chat, chat_class.return_value)
        self.assertIs(embeddings, embedding_class.return_value)
        self.assertEqual(chat_class.call_args.kwargs["model"], "judge-model")
        self.assertEqual(chat_class.call_args.kwargs["base_url"], "https://judge.example/v1")
        self.assertEqual(chat_class.call_args.kwargs["max_tokens"], 4096)
        self.assertEqual(chat_class.call_args.kwargs["timeout"], 60)
        self.assertEqual(chat_class.call_args.kwargs["max_retries"], 1)
        self.assertNotIn("extra_body", chat_class.call_args.kwargs)
        self.assertEqual(embedding_class.call_args.kwargs["model"], "embedding-model")
        self.assertEqual(embedding_class.call_args.kwargs["base_url"], "https://embedding.example/v1")

    @override_settings(LLM_USE_ENV_CHAT=False, LLM_USE_ENV_EMBEDDING=False)
    def test_ragas_clients_only_send_thinking_controls_to_qwen_judges(self):
        tenant = Tenant.objects.create(name="qwen-ragas-tenant", api_key="qwen-ragas-key")
        ModelConfig.objects.create(
            id="qwen-judge",
            tenant=tenant,
            name="Qwen Judge",
            type="KnowledgeQA",
            source="qwen",
            parameters={"base_url": "https://judge.example/v1", "api_key": "judge-key", "model": "qwen3-32b"},
        )
        ModelConfig.objects.create(
            id="qwen-embedding",
            tenant=tenant,
            name="embedding-model",
            type="Embedding",
            source="openai",
            is_default=True,
            parameters={"base_url": "https://embedding.example/v1", "api_key": "embedding-key", "model": "embedding-model", "dimension": 1024},
        )

        with patch("langchain_openai.ChatOpenAI") as chat_class, patch("langchain_openai.OpenAIEmbeddings"):
            ragas_adapter._clients(tenant, "qwen-judge")

        self.assertEqual(chat_class.call_args.kwargs["extra_body"], {
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        })

    @override_settings(LLM_USE_ENV_CHAT=False, LLM_USE_ENV_EMBEDDING=False)
    def test_bailian_non_qwen_judge_does_not_receive_qwen_controls(self):
        tenant = Tenant.objects.create(name="bailian-deepseek-tenant", api_key="bailian-deepseek-key")
        ModelConfig.objects.create(
            id="bailian-deepseek-judge",
            tenant=tenant,
            name="DeepSeek Judge",
            type="KnowledgeQA",
            source="aliyun-bailian",
            parameters={"base_url": "https://judge.example/v1", "api_key": "judge-key", "model": "deepseek-v3"},
        )
        ModelConfig.objects.create(
            id="bailian-embedding",
            tenant=tenant,
            name="embedding-model",
            type="Embedding",
            source="openai",
            is_default=True,
            parameters={"base_url": "https://embedding.example/v1", "api_key": "embedding-key", "model": "embedding-model", "dimension": 1024},
        )

        with patch("langchain_openai.ChatOpenAI") as chat_class, patch("langchain_openai.OpenAIEmbeddings"):
            ragas_adapter._clients(tenant, "bailian-deepseek-judge")

        self.assertNotIn("extra_body", chat_class.call_args.kwargs)

    def test_ragas_api_retries_legacy_vertex_import_for_openai_workflows(self):
        sentinel = {"evaluate": object()}
        missing_vertex = ModuleNotFoundError("No module named 'langchain_community.chat_models.vertexai'")
        missing_vertex.name = "langchain_community.chat_models.vertexai"
        with patch.object(ragas_adapter, "_import_ragas_symbols", side_effect=[missing_vertex, sentinel]), patch.object(
            ragas_adapter, "_install_legacy_vertex_compatibility"
        ) as install:
            self.assertIs(ragas_adapter._ragas_api(), sentinel)
        install.assert_called_once_with()

    def test_adapter_normalizes_reference_and_no_reference_context_precision(self):
        class FakeSample:
            def __init__(self, **kwargs):
                self.values = kwargs

        class FakeDataset:
            def __init__(self, samples):
                self.samples = samples

        class FakeMetric:
            def __init__(self, name):
                self.name = name

        def fake_evaluate(*, dataset, metrics, **_kwargs):
            metric_names = {metric.name for metric in metrics}
            if "context_precision" in metric_names:
                return type("Result", (), {"scores": [{
                    "faithfulness": 0.8,
                    "answer_relevancy": 0.7,
                    "context_precision": 0.6,
                }]})()
            return type("Result", (), {"scores": [{
                "faithfulness": 0.5,
                "answer_relevancy": 0.4,
                "llm_context_precision_without_reference": 0.3,
            }]})()

        api = {
            "evaluate": fake_evaluate,
            "EvaluationDataset": FakeDataset,
            "SingleTurnSample": FakeSample,
            "Faithfulness": lambda: FakeMetric("faithfulness"),
            "AnswerRelevancy": lambda: FakeMetric("answer_relevancy"),
            "ContextPrecision": lambda: FakeMetric("context_precision"),
            "ContextPrecisionWithoutReference": lambda: FakeMetric("llm_context_precision_without_reference"),
        }
        with patch.object(ragas_adapter, "_ragas_api", return_value=api), patch.object(
            ragas_adapter, "_clients", return_value=(object(), object())
        ):
            scores = ragas_adapter.evaluate_dataset(
                [
                    {"question": "with ref", "answer": "a", "contexts": ["c"], "ground_truth": "truth"},
                    {"question": "without ref", "answer": "a", "contexts": ["c"], "ground_truth": ""},
                ],
                tenant=object(),
            )

        self.assertEqual(scores, [
            {"faithfulness": 0.8, "answer_relevancy": 0.7, "context_precision": 0.6},
            {"faithfulness": 0.5, "answer_relevancy": 0.4, "context_precision": 0.3},
        ])

    def test_adapter_marks_one_invalid_score_without_failing_the_batch(self):
        class FakeSample:
            def __init__(self, **kwargs):
                self.values = kwargs

        api = {
            "evaluate": lambda **kwargs: type("Result", (), {"scores": [{
                "faithfulness": float("nan"),
                "answer_relevancy": 0.7,
                "context_precision": 0.6,
            }]})(),
            "EvaluationDataset": lambda samples: samples,
            "SingleTurnSample": FakeSample,
            "Faithfulness": object,
            "AnswerRelevancy": object,
            "ContextPrecision": object,
            "ContextPrecisionWithoutReference": object,
        }
        with patch.object(ragas_adapter, "_ragas_api", return_value=api), patch.object(
            ragas_adapter, "_clients", return_value=(object(), object())
        ):
            scores = ragas_adapter.evaluate_dataset(
                [{"question": "q", "answer": "a", "contexts": ["c"], "ground_truth": "truth"}],
                tenant=object(),
            )

        self.assertEqual(scores, [{"valid": False, "error": "ragas_score_invalid"}])

    def test_adapter_marks_empty_answer_invalid_without_calling_ragas(self):
        api = {"evaluate": Mock()}
        with patch.object(ragas_adapter, "_ragas_api", return_value=api), patch.object(
            ragas_adapter, "_clients", return_value=(object(), object())
        ):
            scores = ragas_adapter.evaluate_dataset(
                [{"question": "q", "answer": "", "contexts": ["c"], "ground_truth": "truth"}],
                tenant=object(),
            )

        self.assertEqual(scores, [{"valid": False, "error": "ragas_input_invalid"}])
        api["evaluate"].assert_not_called()

    def test_ragas_scores_are_preserved_per_question(self):
        details = [
            rag_eval.EvalDetail(question="first", answer="a1", contexts=["c1"], ground_truth="reference"),
            rag_eval.EvalDetail(question="second", answer="a2", contexts=["c2"], ground_truth=""),
        ]
        scores = [
            {"faithfulness": 0.2, "answer_relevancy": 0.4, "context_precision": 0.6},
            {"faithfulness": 0.8, "answer_relevancy": 1.0, "context_precision": 0.5},
        ]

        with patch("personal_knowledge_base.ragas_adapter.evaluate_dataset", return_value=scores) as evaluate:
            result = rag_eval._ragas_evaluation(details, tenant=object())

        self.assertEqual(result.faithfulness, 0.5)
        self.assertEqual(result.answer_relevancy, 0.7)
        self.assertEqual(result.context_precision, 0.55)
        self.assertEqual(result.details[0].faithfulness, 0.2)
        self.assertEqual(result.details[1].faithfulness, 0.8)
        self.assertEqual(result.details[0].context_precision, 0.6)
        self.assertEqual(result.details[1].context_precision, 0.5)
        self.assertEqual(evaluate.call_args.args[0][0]["ground_truth"], "reference")

    def test_ragas_failure_is_exposed_without_scores(self):
        details = [rag_eval.EvalDetail(question="q", answer="a", contexts=["c"], ground_truth="")]
        with patch(
            "personal_knowledge_base.ragas_adapter.evaluate_dataset",
            side_effect=RuntimeError("judge unavailable"),
        ):
            with self.assertRaises(rag_eval.RagasEvaluationError):
                rag_eval._ragas_evaluation(details, tenant=object())


@override_settings(ALLOW_AUTO_SETUP=True)
class RagasEvaluationLoopApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant_a, self.headers_a = self._tenant("a")
        self.tenant_b, self.headers_b = self._tenant("b")

    def _tenant(self, suffix):
        tenant = Tenant.objects.create(name=f"tenant-{suffix}", api_key=f"key-{suffix}")
        user = User.objects.create(
            username=f"user-{suffix}",
            email=f"user-{suffix}@example.test",
            password_hash="unused",
            tenant=tenant,
        )
        token = AuthToken.objects.create(user=user, token=f"token-{suffix}", token_type="access", expires_at="2099-01-01T00:00:00Z")
        return tenant, {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}

    def _post(self, path, payload, headers):
        return self.client.post(path, data=json.dumps(payload), content_type="application/json", **headers)

    def test_manual_review_changes_only_candidate_status(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {
                "name": "manual dataset",
                "review_mode": "manual",
                "entries": [{"question": "What is it?", "answer": "An answer", "evidence": []}],
            },
            self.headers_a,
        )
        self.assertEqual(created.status_code, 201)
        dataset = created.json()["data"]
        entry = dataset["entries"][0]
        self.assertEqual(entry["status"], "pending_review")

        reviewed = self._post(
            f"/api/v1/rag-eval/datasets/{dataset['id']}/review",
            {"entry_ids": [entry["id"]], "status": "approved", "answer": "mutated"},
            self.headers_a,
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json()["data"]["entries"][0]["status"], "approved")
        self.assertEqual(reviewed.json()["data"]["entries"][0]["answer"], "An answer")

    def test_auto_review_rejects_missing_evidence_without_a_score(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {
                "name": "unverified dataset",
                "entries": [{"question": "What is it?", "answer": "An answer", "evidence": []}],
            },
            self.headers_a,
        )
        self.assertEqual(created.status_code, 201)
        data = created.json()["data"]
        self.assertEqual(data["entries"][0]["status"], "rejected")
        self.assertIn("evidence", data["entries"][0]["validation_errors"])
        self.assertEqual(data["entries"][0]["ground_truth"], "")

        run = self._post("/api/v1/rag-eval/run", {"dataset_id": data["id"]}, self.headers_a)
        self.assertEqual(run.status_code, 422)
        self.assertEqual(run.json()["error"]["code"], "unverified_eval_dataset")

    def test_dataset_is_tenant_scoped(self):
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {"name": "private", "entries": []},
            self.headers_a,
        )
        dataset_id = created.json()["data"]["id"]

        listing = self.client.get("/api/v1/rag-eval/datasets", **self.headers_b)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["data"]["datasets"], [])

        foreign = self.client.get(f"/api/v1/rag-eval/datasets/{dataset_id}", **self.headers_b)
        self.assertEqual(foreign.status_code, 404)

    def test_run_rejects_non_evaluation_resource(self):
        resource = GenericResource.objects.create(
            tenant=self.tenant_a,
            resource_type="unrelated_resource",
            data={"entries": []},
        )
        response = self._post("/api/v1/rag-eval/run", {"dataset_id": resource.id}, self.headers_a)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "dataset_not_found")

    @patch("personal_knowledge_base.eval_views._validate_eval_entry", return_value=[])
    def test_sample_review_marks_a_fixed_ten_percent_without_dropping_other_candidates(self, _validate):
        entries = [
            {"question": f"question-{index}", "answer": "answer", "evidence": []}
            for index in range(20)
        ]
        created = self._post(
            "/api/v1/rag-eval/datasets",
            {"name": "sample dataset", "review_mode": "sample", "entries": entries},
            self.headers_a,
        )
        self.assertEqual(created.status_code, 201)
        entries = created.json()["data"]["entries"]
        self.assertEqual(sum(bool(entry["review_sampled"]) for entry in entries), 2)
        self.assertTrue(all(entry["status"] == "approved" for entry in entries))

    def test_published_dataset_cannot_be_reviewed_or_published_in_place(self):
        resource = GenericResource.objects.create(
            tenant=self.tenant_a,
            resource_type="rag_eval_datasets",
            name="immutable",
            status="published",
            data={
                "schema_version": "evaluation_v2",
                "entries": [{"id": "q1", "status": "approved"}],
            },
        )

        reviewed = self._post(
            f"/api/v1/rag-eval/datasets/{resource.id}/review",
            {"entry_ids": ["q1"], "status": "rejected"},
            self.headers_a,
        )
        published = self._post(
            f"/api/v1/rag-eval/datasets/{resource.id}/publish",
            {},
            self.headers_a,
        )

        self.assertEqual(reviewed.status_code, 409)
        self.assertEqual(reviewed.json()["error"]["code"], "dataset_immutable")
        self.assertEqual(published.status_code, 409)
        resource.refresh_from_db()
        self.assertEqual(resource.data["entries"][0]["status"], "approved")

    def test_run_uses_saved_questions_before_defaults(self):
        self._post(
            "/api/v1/rag-eval/questions",
            {"question": "saved question", "ground_truth": "saved reference"},
            self.headers_a,
        )
        result = rag_eval.EvalResult(total_questions=1)
        with patch("personal_knowledge_base.eval_views.run_rag_evaluation", return_value=result) as run:
            response = self._post("/api/v1/rag-eval/run", {}, self.headers_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(run.call_args.kwargs["questions"][0]["question"], "saved question")

    @patch("personal_knowledge_base.eval_views._ragas_testset_entries", return_value=[])
    def test_knowledge_base_testset_accepts_a_hundred_questions(self, generate):
        response = self._post(
            "/api/v1/rag-eval/testsets",
            {"testset_size": 100, "review_mode": "auto", "question_types": ["simple"]},
            self.headers_a,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(generate.call_args.args[1], 100)

    @patch("personal_knowledge_base.eval_views._ragas_testset_entries", return_value=[])
    def test_knowledge_base_testset_defaults_to_a_hundred_questions(self, generate):
        response = self._post(
            "/api/v1/rag-eval/testsets",
            {"review_mode": "auto", "question_types": ["simple"]},
            self.headers_a,
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(generate.call_args.args[1], 100)
