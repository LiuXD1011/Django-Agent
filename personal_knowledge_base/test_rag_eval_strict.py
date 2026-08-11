from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase, override_settings

from . import rag_eval


class RagEvalStrictFailureTests(SimpleTestCase):
    def test_ragas_failure_is_not_replaced_with_heuristic_scores(self):
        with patch.object(rag_eval, "_run_rag_pipeline", return_value=("answer", ["context"])), patch.object(
            rag_eval, "_ragas_evaluation", side_effect=RuntimeError("judge unavailable")
        ), patch.object(rag_eval, "_simple_evaluation") as simple:
            with self.assertRaises(Exception) as raised:
                rag_eval.run_rag_evaluation(
                    tenant=object(),
                    questions=[{"question": "q", "ground_truth": "answer"}],
                )

        self.assertEqual(raised.exception.__class__.__name__, "RagasEvaluationError")
        simple.assert_not_called()


@override_settings(ALLOW_AUTO_SETUP=True)
class RagEvalEndpointFailureTests(TestCase):
    def test_endpoint_returns_dedicated_ragas_failure_code(self):
        client = Client()
        setup = client.post("/api/v1/auth/auto-setup", content_type="application/json")
        headers = {"HTTP_AUTHORIZATION": f"Bearer {setup.json()['data']['token']}"}
        with patch(
            "personal_knowledge_base.eval_views.run_rag_evaluation",
            side_effect=rag_eval.RagasEvaluationError("judge unavailable"),
        ):
            response = client.post(
                "/api/v1/rag-eval/run",
                data="{}",
                content_type="application/json",
                **headers,
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "ragas_evaluation_failed")
