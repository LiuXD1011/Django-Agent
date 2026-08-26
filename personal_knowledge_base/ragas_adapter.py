"""Narrow adapter for the Ragas 0.4 public API.

Keeping all Ragas imports here prevents package/import drift from leaking into the
evaluation workflow and gives callers one failure mode to handle.
"""

import math
import logging
import sys
import types


class RagasAdapterError(RuntimeError):
    """Raised when Ragas cannot generate or evaluate a formal result."""


logger = logging.getLogger(__name__)


METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision")
_LEGACY_VERTEX_MODULE = "langchain_community.chat_models.vertexai"


def is_usable_ragas_score(score) -> bool:
    return isinstance(score, dict) and all(
        isinstance(score.get(metric), (int, float)) and math.isfinite(score[metric])
        for metric in METRIC_NAMES
    )


def _import_ragas_symbols():
    from ragas import evaluate
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
    from ragas.metrics import AnswerRelevancy, ContextPrecision, Faithfulness, LLMContextPrecisionWithoutReference
    from ragas.testset.synthesizers.generate import TestsetGenerator
    try:
        from ragas.run_config import RunConfig
    except ImportError:
        RunConfig = None
    return {
        "evaluate": evaluate,
        "EvaluationDataset": EvaluationDataset,
        "SingleTurnSample": SingleTurnSample,
        "Faithfulness": Faithfulness,
        "AnswerRelevancy": AnswerRelevancy,
        "ContextPrecision": ContextPrecision,
        "ContextPrecisionWithoutReference": LLMContextPrecisionWithoutReference,
        "TestsetGenerator": TestsetGenerator,
        "RunConfig": RunConfig,
    }


def _install_legacy_vertex_compatibility():
    """Provide the optional Ragas 0.4.3 Vertex import for newer LangChain builds.

    The application creates OpenAI-compatible clients. Ragas imports this class
    unconditionally for an optional type check, even when VertexAI is unused.
    """
    if _LEGACY_VERTEX_MODULE in sys.modules:
        return
    module = types.ModuleType(_LEGACY_VERTEX_MODULE)
    module.ChatVertexAI = type("ChatVertexAI", (), {"__module__": _LEGACY_VERTEX_MODULE})
    sys.modules[_LEGACY_VERTEX_MODULE] = module


def _ragas_api():
    try:
        return _import_ragas_symbols()
    except ModuleNotFoundError as exc:
        if exc.name != _LEGACY_VERTEX_MODULE:
            raise RagasAdapterError("Ragas 0.4 dependencies are unavailable") from exc
        _install_legacy_vertex_compatibility()
        try:
            return _import_ragas_symbols()
        except Exception as retry_exc:
            raise RagasAdapterError("Ragas 0.4 dependencies are unavailable") from retry_exc
    except Exception as exc:
        raise RagasAdapterError("Ragas 0.4 dependencies are unavailable") from exc


def _clients(tenant, eval_llm_model: str = ""):
    try:
        from django.conf import settings
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from .model_providers import active_embedding_config, default_model, is_env_chat_model_id
        from .models import ModelConfig

        if (not eval_llm_model or is_env_chat_model_id(eval_llm_model)) and settings.LLM_USE_ENV_CHAT and settings.LLM_CHAT_API_KEY:
            chat_config = {
                "model": settings.LLM_CHAT_MODEL,
                "base_url": settings.LLM_CHAT_BASE_URL,
                "api_key": settings.LLM_CHAT_API_KEY,
                "source": "env",
            }
        else:
            model = (
                ModelConfig.objects.filter(id=eval_llm_model, tenant=tenant, deleted_at__isnull=True).first()
                if eval_llm_model
                else default_model(tenant, "chat")
            )
            if not model:
                raise RagasAdapterError("Ragas chat evaluator is not configured")
            params = model.parameters or {}
            chat_config = {
                "model": params.get("model") or model.name,
                "base_url": (params.get("base_url") or params.get("baseURL") or "").rstrip("/"),
                "api_key": params.get("api_key") or params.get("apiKey") or params.get("token") or "",
                "source": model.source or "",
            }
        embedding_config = active_embedding_config(tenant)
        if not chat_config["base_url"] or not chat_config["api_key"] or not embedding_config:
            raise RagasAdapterError("Ragas evaluator clients are unavailable")

        chat_kwargs = {
            "model": chat_config["model"],
            "temperature": 0,
            "base_url": chat_config["base_url"],
            "api_key": chat_config["api_key"],
            "max_tokens": 4096,
            "timeout": settings.LLM_CHAT_MODEL_TIMEOUT,
            "max_retries": min(max(int(getattr(settings, "LLM_MODEL_NUM_RETRIES", 2) or 0), 0), 1),
        }
        model_name = str(chat_config["model"] or "").lower()
        if "qwen" in model_name or "qwq" in model_name:
            chat_kwargs["extra_body"] = {
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        chat = ChatOpenAI(**chat_kwargs)
        embeddings = OpenAIEmbeddings(
            model=embedding_config["model"],
            base_url=embedding_config["base_url"],
            api_key=embedding_config["api_key"],
        )
    except RagasAdapterError:
        raise
    except Exception as exc:
        raise RagasAdapterError("Ragas evaluator clients are unavailable") from exc
    return chat, embeddings


def evaluate_dataset(
    rows: list[dict],
    tenant,
    eval_llm_model: str = "",
    *,
    progress_callback=None,
    cancel_callback=None,
    existing_scores: list[dict] | None = None,
) -> list[dict]:
    """Evaluate single-turn RAG rows and return one formal score mapping per row."""
    if not rows:
        return []
    api = _ragas_api()
    chat, embeddings = _clients(tenant, eval_llm_model)
    normalized = []
    for index in range(len(rows)):
        existing = existing_scores[index] if existing_scores and index < len(existing_scores) else None
        normalized.append(dict(existing) if is_usable_ragas_score(existing) else {})
    for index, row in enumerate(rows):
        if not str(row.get("question") or "").strip() or not str(row.get("answer") or "").strip() or not any(
            str(context or "").strip() for context in (row.get("contexts") or [])
        ):
            normalized[index] = {"valid": False, "error": "ragas_input_invalid"}
    groups = {
        True: [(index, row) for index, row in enumerate(rows) if row.get("ground_truth") and not normalized[index]],
        False: [(index, row) for index, row in enumerate(rows) if not row.get("ground_truth") and not normalized[index]],
    }
    processed = sum(bool(score) for score in normalized)
    for has_reference, indexed_rows in groups.items():
        for offset in range(0, len(indexed_rows), 10):
            if cancel_callback:
                cancel_callback()
            batch = indexed_rows[offset:offset + 10]
            try:
                dataset = api["EvaluationDataset"](
                    samples=[
                        api["SingleTurnSample"](
                            user_input=row["question"],
                            response=row["answer"],
                            retrieved_contexts=row["contexts"],
                            reference=row.get("ground_truth") or None,
                        )
                        for _index, row in batch
                    ]
                )
                evaluate_kwargs = {
                    "dataset": dataset,
                    "metrics": [
                        api["Faithfulness"](),
                        api["AnswerRelevancy"](),
                        api["ContextPrecision"]() if has_reference else api["ContextPrecisionWithoutReference"](),
                    ],
                    "llm": chat,
                    "embeddings": embeddings,
                    "raise_exceptions": False,
                    "show_progress": False,
                }
                run_config_factory = api.get("RunConfig") if isinstance(api, dict) else None
                if run_config_factory:
                    evaluate_kwargs["run_config"] = run_config_factory(max_workers=2)
                result = api["evaluate"](**evaluate_kwargs)
                scores = list(result.scores)
            except Exception as exc:
                logger.exception("Ragas batch evaluation failed")
                raise RagasAdapterError("Ragas evaluation failed") from exc
            if len(scores) != len(batch):
                raise RagasAdapterError("Ragas returned an incomplete score set")
            for (index, _row), score in zip(batch, scores, strict=True):
                normalized_score = {}
                for metric in METRIC_NAMES:
                    value = score.get(metric) if isinstance(score, dict) else None
                    if metric == "context_precision" and not has_reference and value is None and isinstance(score, dict):
                        value = score.get("llm_context_precision_without_reference")
                    if not isinstance(value, (int, float)) or not math.isfinite(value):
                        normalized_score = {"valid": False, "error": "ragas_score_invalid"}
                        break
                    normalized_score[metric] = float(value)
                normalized[index] = normalized_score
            processed += len(batch)
            if progress_callback:
                progress_callback(processed, len(rows), normalized)
    return normalized


def generate_testset_candidates(
    documents,
    testset_size: int,
    eval_llm_model: str = "",
    question_types: list[str] | None = None,
    tenant=None,
) -> list[dict]:
    """Generate candidates through ``TestsetGenerator`` and return serializable rows."""
    if not documents or testset_size < 1:
        return []
    api = _ragas_api()
    chat, embeddings = _clients(tenant, eval_llm_model)
    try:
        llm_context = None
        if question_types:
            llm_context = (
                "Generate a balanced RAG evaluation testset using these requested question types: "
                + ", ".join(question_types)
                + ". Prefer those types when selecting query evolutions."
            )
        generator = api["TestsetGenerator"].from_langchain(chat, embeddings, llm_context=llm_context)
        testset = generator.generate_with_langchain_docs(
            documents=documents,
            testset_size=testset_size,
            raise_exceptions=True,
        )
        return list(testset.to_list())
    except Exception as exc:
        raise RagasAdapterError("Ragas testset generation failed") from exc
