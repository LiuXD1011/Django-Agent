"""Narrow adapter for the Ragas 0.4 public API.

Keeping all Ragas imports here prevents package/import drift from leaking into the
evaluation workflow and gives callers one failure mode to handle.
"""

import math


class RagasAdapterError(RuntimeError):
    """Raised when Ragas cannot generate or evaluate a formal result."""


METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision")


def _ragas_api():
    try:
        from ragas import evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
        from ragas.metrics import AnswerRelevancy, Faithfulness, LLMContextPrecisionWithoutReference
        from ragas.testset.synthesizers.generate import TestsetGenerator
    except Exception as exc:
        raise RagasAdapterError("Ragas 0.4 dependencies are unavailable") from exc
    return {
        "evaluate": evaluate,
        "EvaluationDataset": EvaluationDataset,
        "SingleTurnSample": SingleTurnSample,
        "Faithfulness": Faithfulness,
        "AnswerRelevancy": AnswerRelevancy,
        "ContextPrecision": LLMContextPrecisionWithoutReference,
        "TestsetGenerator": TestsetGenerator,
    }


def _clients(eval_llm_model: str = ""):
    try:
        from django.conf import settings
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        chat = ChatOpenAI(
            model=eval_llm_model or settings.LLM_CHAT_MODEL,
            temperature=0,
            base_url=settings.LLM_CHAT_BASE_URL,
            api_key=settings.LLM_CHAT_API_KEY,
        )
        embeddings = OpenAIEmbeddings(
            model=settings.LLM_EMBEDDING_MODEL,
            base_url=settings.LLM_EMBEDDING_BASE_URL,
            api_key=settings.LLM_EMBEDDING_API_KEY,
        )
    except Exception as exc:
        raise RagasAdapterError("Ragas evaluator clients are unavailable") from exc
    return chat, embeddings


def evaluate_dataset(rows: list[dict], tenant, eval_llm_model: str = "") -> list[dict]:
    """Evaluate single-turn RAG rows and return one formal score mapping per row."""
    if not rows:
        return []
    api = _ragas_api()
    chat, embeddings = _clients(eval_llm_model)
    try:
        dataset = api["EvaluationDataset"](
            samples=[
                api["SingleTurnSample"](
                    user_input=row["question"],
                    response=row["answer"],
                    retrieved_contexts=row["contexts"],
                )
                for row in rows
            ]
        )
        result = api["evaluate"](
            dataset=dataset,
            metrics=[
                api["Faithfulness"](),
                api["AnswerRelevancy"](),
                api["ContextPrecision"](),
            ],
            llm=chat,
            embeddings=embeddings,
            raise_exceptions=True,
            show_progress=False,
        )
        scores = list(result.scores)
    except Exception as exc:
        raise RagasAdapterError("Ragas evaluation failed") from exc

    if len(scores) != len(rows):
        raise RagasAdapterError("Ragas returned an incomplete score set")
    normalized = []
    for score in scores:
        row_score = {}
        for metric in METRIC_NAMES:
            value = score.get(metric) if isinstance(score, dict) else None
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RagasAdapterError(f"Ragas returned no usable {metric} score")
            row_score[metric] = float(value)
        normalized.append(row_score)
    return normalized


def generate_testset_candidates(documents, testset_size: int, eval_llm_model: str = "") -> list[dict]:
    """Generate candidates through ``TestsetGenerator`` and return serializable rows."""
    if not documents or testset_size < 1:
        return []
    api = _ragas_api()
    chat, embeddings = _clients(eval_llm_model)
    try:
        generator = api["TestsetGenerator"].from_langchain(chat, embeddings)
        testset = generator.generate_with_langchain_docs(
            documents=documents,
            testset_size=testset_size,
            raise_exceptions=True,
        )
        return list(testset.to_list())
    except Exception as exc:
        raise RagasAdapterError("Ragas testset generation failed") from exc
