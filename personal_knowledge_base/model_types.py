WEKNORA_MODEL_TYPES = {
    "chat": "KnowledgeQA",
    "summary": "KnowledgeQA",
    "title": "KnowledgeQA",
    "question": "KnowledgeQA",
    "extract": "KnowledgeQA",
    "knowledgeqa": "KnowledgeQA",
    "knowledge_qa": "KnowledgeQA",
    "KnowledgeQA": "KnowledgeQA",
    "embedding": "Embedding",
    "Embedding": "Embedding",
    "rerank": "Rerank",
    "Rerank": "Rerank",
    "vlm": "VLLM",
    "vllm": "VLLM",
    "VLLM": "VLLM",
    "vision": "VLLM",
    "asr": "ASR",
    "ASR": "ASR",
}

MODEL_TYPE_ALIASES = {
    "KnowledgeQA": {"KnowledgeQA", "chat", "summary", "title", "question", "extract"},
    "Embedding": {"Embedding", "embedding"},
    "Rerank": {"Rerank", "rerank"},
    "VLLM": {"VLLM", "vlm", "vllm", "vision"},
    "ASR": {"ASR", "asr"},
}


def canonical_model_type(value: str = "") -> str:
    return WEKNORA_MODEL_TYPES.get(str(value or "").strip(), str(value or "").strip() or "KnowledgeQA")


def model_type_aliases(value: str = "") -> set[str]:
    canonical = canonical_model_type(value)
    return MODEL_TYPE_ALIASES.get(canonical, {canonical, str(value or "").strip()})


def frontend_model_group(value: str = "") -> str:
    canonical = canonical_model_type(value)
    return {
        "KnowledgeQA": "chat",
        "Embedding": "embedding",
        "Rerank": "rerank",
        "VLLM": "vlm",
        "ASR": "asr",
    }.get(canonical, str(value or "").lower())
