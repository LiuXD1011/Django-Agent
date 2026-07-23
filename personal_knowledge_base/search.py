import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import Chunk, Tenant


logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
PARTIAL_OVERLAP_THRESHOLD = 0.85
SEARCHABLE_CHUNK_TYPES = ("text", "image_ocr", "image_caption")

# ── 中英文停用词（用于查询扩展）─────────────────────────────────────
STOPWORDS = frozenset({
    # 中文
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "他", "她", "它", "们", "那", "些", "什么", "怎么", "如何", "哪",
    "哪个", "哪些", "为什么", "为何", "请问", "请", "帮", "我", "想", "知道", "了解",
    # 英文
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
})

# 中文问题前缀
QUESTION_PREFIX_RE = re.compile(
    r"^(什么是|什么|如何|怎么|怎样|为什么|为何|哪个|哪些|谁|何时|何地|请问|请告诉我|帮我|我想知道|我想了解)"
)


def pack_embedding(vec: Iterable[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(list(vec))


# ── 索引表与向量索引状态治理 ─────────────────────────────────────────
def ensure_search_tables():
    dim = settings.LLM_EMBEDDING_DIM
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(chunk_id UNINDEXED, tenant_id UNINDEXED, knowledge_base_id UNINDEXED,
                       knowledge_id UNINDEXED, title, content)
            """
        )
        cursor.execute("CREATE TABLE IF NOT EXISTS search_index_meta (key TEXT PRIMARY KEY, value TEXT)")
        row = cursor.execute("SELECT sql FROM sqlite_master WHERE name = 'chunk_embeddings_vec'").fetchone()
        if row and f"float[{dim}]" not in (row[0] or ""):
            # 维度变化后旧向量全部失效：重建空表并标记需要全量重建
            cursor.execute("DROP TABLE chunk_embeddings_vec")
            row = None
            cursor.execute("INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('index_status', 'needs_rebuild')")
            cursor.execute("INSERT OR REPLACE INTO search_index_meta(key, value) VALUES ('rebuild_reason', 'embedding_dimension_changed')")
        if row is None:
            cursor.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings_vec USING vec0(embedding float[{dim}])")
        # 全新安装默认为 ready；维度迁移路径上面已显式置为 needs_rebuild
        cursor.execute("INSERT OR IGNORE INTO search_index_meta(key, value) VALUES ('index_status', 'ready')")
        cursor.execute("INSERT OR IGNORE INTO search_index_meta(key, value) VALUES ('embedding_signature', '')")


def _meta_get(key: str, default: str = "") -> str:
    try:
        with connection.cursor() as cursor:
            row = cursor.execute("SELECT value FROM search_index_meta WHERE key = %s", [key]).fetchone()
    except Exception:
        return default
    return row[0] if row else default


def _meta_set(key: str, value: str):
    with connection.cursor() as cursor:
        cursor.execute("INSERT OR REPLACE INTO search_index_meta(key, value) VALUES (%s, %s)", [key, value])


def get_vector_index_state() -> dict:
    """向量索引状态：status=ready/needs_rebuild、签名（模型:维度）、重建原因。"""
    return {
        "status": _meta_get("index_status", "ready"),
        "signature": _meta_get("embedding_signature", ""),
        "reason": _meta_get("rebuild_reason", ""),
        "dim": settings.LLM_EMBEDDING_DIM,
    }


def mark_vector_index_needs_rebuild(reason: str = ""):
    ensure_search_tables()
    _meta_set("index_status", "needs_rebuild")
    _meta_set("rebuild_reason", reason)


def mark_vector_index_ready(signature: str = ""):
    ensure_search_tables()
    _meta_set("index_status", "ready")
    _meta_set("embedding_signature", signature)
    _meta_set("rebuild_reason", "")


def update_vector_index_signature(signature: str):
    """单 Chunk 成功写入后补记签名（仅在尚未记录时）。"""
    if signature and not _meta_get("embedding_signature", ""):
        _meta_set("embedding_signature", signature)


def _searchable_chunks():
    return Chunk.objects.filter(
        is_enabled=True,
        chunk_type__in=SEARCHABLE_CHUNK_TYPES,
        deleted_at__isnull=True,
        knowledge__deleted_at__isnull=True,
        knowledge__enable_status="enabled",
        knowledge_base__deleted_at__isnull=True,
    )


def _chunk_is_searchable(chunk: Chunk) -> bool:
    return bool(
        chunk.is_enabled
        and chunk.chunk_type in SEARCHABLE_CHUNK_TYPES
        and chunk.deleted_at is None
        and chunk.knowledge.deleted_at is None
        and chunk.knowledge.enable_status == "enabled"
        and chunk.knowledge_base.deleted_at is None
    )


def index_chunk(chunk: Chunk, *, ensure_tables: bool = True):
    """写入 FTS5 与 BGE-M3 向量双索引；向量失败只降级该 Chunk 的向量部分并记录原因。"""
    if ensure_tables:
        ensure_search_tables()
    rowid = chunk.seq_id if chunk.seq_id is not None else _rowid(chunk.id)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = %s", [chunk.id])
        cursor.execute("DELETE FROM chunk_embeddings_vec WHERE rowid = %s", [rowid])
    if not _chunk_is_searchable(chunk):
        return
    knowledge = chunk.knowledge
    index_content = chunk.embedding_content()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [chunk.id, chunk.tenant_id, chunk.knowledge_base_id, chunk.knowledge_id, knowledge.title, index_content],
        )
    vec = None
    vector_warning = ""
    try:
        from .model_providers import EmbeddingDimensionMismatchError, embedding

        vec = embedding(chunk.tenant, [index_content], chunk.knowledge.embedding_model_id)[0]
    except EmbeddingDimensionMismatchError:
        # D1 严格模式：维度不匹配直接报错，绝不静默降级（"未配置/服务失败"才走 FTS-only 降级）
        raise
    except Exception as exc:
        vector_warning = str(exc)[:300]
    if vec is not None:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
                [rowid, pack_embedding(vec)],
            )
        if chunk.seq_id is None:
            Chunk.objects.filter(id=chunk.id).update(seq_id=rowid)
        from .model_providers import embedding_signature

        update_vector_index_signature(embedding_signature(chunk.tenant, chunk.knowledge.embedding_model_id))
    elif vector_warning:
        logger.warning("Vector index skipped for chunk %s: %s", chunk.id, vector_warning)
        metadata = dict(chunk.metadata or {})
        warnings = list(metadata.get("index_warnings") or [])
        warnings.append({"stage": "vector", "message": vector_warning})
        metadata["index_warnings"] = warnings[-5:]
        Chunk.objects.filter(id=chunk.id).update(metadata=metadata, updated_at=timezone.now())


def delete_chunk_index(chunk_id: str, seq_id: int | None = None, *, ensure_tables: bool = True):
    if ensure_tables:
        ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = %s", [chunk_id])
        if seq_id is not None:
            cursor.execute("DELETE FROM chunk_embeddings_vec WHERE rowid = %s", [seq_id])


def _bounded_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(parsed, max_value))


# ── 查询扩展 ─────────────────────────────────────────────────────────
def expand_query(query: str) -> list[str]:
    """当召回不足时，生成查询变体以提高召回率。参考同类知识库系统的 query_expansion.go。"""
    variants: list[str] = []
    seen = {query.lower().strip()}

    # 1. 去停用词
    tokens = TOKEN_RE.findall(query)
    keywords = [t for t in tokens if t.lower() not in STOPWORDS and len(t) > 1]
    if len(keywords) >= 2:
        kw_query = " ".join(keywords)
        if kw_query.lower() not in seen:
            variants.append(kw_query)
            seen.add(kw_query.lower())

    # 2. 引号内容提取
    for match in re.finditer(r'[""「](.+?)[""」]', query):
        phrase = match.group(1).strip()
        if len(phrase) >= 3 and phrase.lower() not in seen:
            variants.append(phrase)
            seen.add(phrase.lower())

    # 3. 分隔符切分
    parts = re.split(r"[,，;；、。！？!?\s]+", query)
    for part in parts:
        part = part.strip()
        if len(part) >= 5 and part.lower() not in seen:
            variants.append(part)
            seen.add(part.lower())

    # 4. 去问题前缀
    stripped = QUESTION_PREFIX_RE.sub("", query).strip()
    if len(stripped) >= 3 and stripped.lower() not in seen:
        variants.append(stripped)
        seen.add(stripped.lower())

    return variants[:5]


# ── MMR 多样性过滤 ───────────────────────────────────────────────────
def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard 相似度。"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / max(union, 1)


def tokenize_for_mmr(text: str) -> set[str]:
    """分词用于 MMR 相似度计算。"""
    tokens = TOKEN_RE.findall((text or "").lower())
    return {t for t in tokens if len(t) > 1}


def apply_mmr(results: list[dict], k: int, lambda_param: float = 0.7) -> list[dict]:
    """
    Maximal Marginal Relevance (MMR) 多样性过滤。
    lambda_param: 0.7 表示 70% 相关性 + 30% 多样性。
    """
    if len(results) <= k:
        return results

    # 预计算 token sets
    token_sets = [tokenize_for_mmr(r.get("content", "")) for r in results]

    # 归一化 relevance 分数到 [0, 1]
    scores = [r.get("score", 0) for r in results]
    max_score = max(scores) if scores else 1.0
    min_score = min(scores) if scores else 0.0
    score_range = max_score - min_score or 1.0
    normalized_scores = [(s - min_score) / score_range for s in scores]

    selected: list[int] = []
    remaining = list(range(len(results)))

    for _ in range(k):
        if not remaining:
            break
        best_idx = -1
        best_mmr = -float("inf")

        for idx in remaining:
            relevance = normalized_scores[idx]
            # 计算与已选结果的最大相似度
            max_sim = 0.0
            for sel in selected:
                sim = jaccard_similarity(token_sets[idx], token_sets[sel])
                max_sim = max(max_sim, sim)
            mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        if best_idx >= 0:
            selected.append(best_idx)
            remaining.remove(best_idx)

    return [results[i] for i in selected]


# ── 知识条目级多样性去重 ──────────────────────────────────────────────
def diversify_by_knowledge(results: list[dict], max_per_knowledge: int = 2) -> list[dict]:
    """
    确保结果来自不同的知识条目，每个条目最多保留 max_per_knowledge 个 chunk。
    参考同类知识库系统的文档级多样性策略。
    """
    knowledge_counts: dict[str, int] = {}
    diversified = []
    for item in results:
        kid = item.get("knowledge_id", "")
        count = knowledge_counts.get(kid, 0)
        if count < max_per_knowledge:
            diversified.append(item)
            knowledge_counts[kid] = count + 1
    return diversified


# ── 短 chunk 相邻扩展 ────────────────────────────────────────────────
def expand_short_chunks(results: list[dict], min_chars: int = 350, max_chars: int = 850) -> list[dict]:
    """
    对内容过短的 chunk，用相邻 chunk 的内容进行扩展。
    参考同类知识库系统的 merge_expand.go。
    """
    chunk_ids = [r.get("chunk_id") or r.get("id") for r in results]
    if not chunk_ids:
        return results

    # 批量查询所有涉及的 chunk 及其前后邻居
    chunks_map = {}
    for c in Chunk.objects.filter(id__in=chunk_ids).select_related("knowledge"):
        chunks_map[c.id] = c

    # 查询相邻 chunk（同 knowledge_id，按 chunk_index 排序）
    knowledge_ids = list({c.knowledge_id for c in chunks_map.values() if c})
    neighbors: dict[str, dict] = {}  # chunk_id -> {prev: chunk, next: chunk}
    if knowledge_ids:
        all_chunks = Chunk.objects.filter(
            knowledge_id__in=knowledge_ids, is_enabled=True
        ).exclude(chunk_type="parent_text").order_by("knowledge_id", "chunk_index").values("id", "knowledge_id", "chunk_index", "content")

        by_knowledge: dict[str, list] = {}
        for c in all_chunks:
            by_knowledge.setdefault(c["knowledge_id"], []).append(c)

        for kid, chunk_list in by_knowledge.items():
            for i, c in enumerate(chunk_list):
                if c["id"] in chunks_map:
                    entry = {}
                    if i > 0:
                        entry["prev"] = chunk_list[i - 1]
                    if i < len(chunk_list) - 1:
                        entry["next"] = chunk_list[i + 1]
                    neighbors[c["id"]] = entry

    expanded = []
    for item in results:
        cid = item.get("chunk_id") or item.get("id")
        content = item.get("content", "")

        if item.get("parent_chunk_id") or getattr(chunks_map.get(cid), "context_parent_id", None):
            expanded.append(item)
            continue

        if len(content) >= min_chars:
            expanded.append(item)
            continue

        # 尝试扩展
        parts = [content]
        total_len = len(content)
        nb = neighbors.get(cid, {})

        # 向前扩展
        prev = nb.get("prev")
        while prev and total_len < max_chars:
            prev_content = prev.get("content", "")
            if prev_content and prev_content not in content:
                parts.insert(0, prev_content)
                total_len += len(prev_content)
            # 继续向前找
            prev_id = prev.get("id")
            prev_nb = neighbors.get(prev_id, {})
            prev = prev_nb.get("prev")

        # 向后扩展
        nxt = nb.get("next")
        while nxt and total_len < max_chars:
            next_content = nxt.get("content", "")
            if next_content and next_content not in content:
                parts.append(next_content)
                total_len += len(next_content)
            next_id = nxt.get("id")
            next_nb = neighbors.get(next_id, {})
            nxt = next_nb.get("next")

        expanded_item = {**item, "content": "\n".join(parts)}
        expanded.append(expanded_item)

    return expanded


# ── 双路召回（排名列表）─────────────────────────────────────────────
def _fts_ranked(tenant_id: int, kb_set: set, query: str, limit: int) -> list[str]:
    """FTS5 BM25 召回，按相关度排序返回 chunk_id 列表（rank 从 1 开始）。"""
    ranked: list[str] = []
    seen: set[str] = set()
    fts_query = " OR ".join(TOKEN_RE.findall(query)) or query
    tenant_filter = int(tenant_id)
    with connection.cursor() as cursor:
        if fts_query:
            try:
                cursor.execute(
                    """
                    SELECT chunk_id, knowledge_base_id
                    FROM chunks_fts
                    WHERE chunks_fts MATCH %s AND tenant_id = %s
                    ORDER BY bm25(chunks_fts)
                    LIMIT %s
                    """,
                    [fts_query, tenant_filter, limit],
                )
                for chunk_id, kb_id in cursor.fetchall():
                    if (not kb_set or kb_id in kb_set) and chunk_id not in seen:
                        seen.add(chunk_id)
                        ranked.append(chunk_id)
            except Exception:
                cursor.execute(
                    """
                    SELECT chunk_id, knowledge_base_id FROM chunks_fts
                    WHERE tenant_id = %s AND content LIKE %s
                    LIMIT %s
                    """,
                    [tenant_filter, f"%{query}%", limit],
                )
                for chunk_id, kb_id in cursor.fetchall():
                    if (not kb_set or kb_id in kb_set) and chunk_id not in seen:
                        seen.add(chunk_id)
                        ranked.append(chunk_id)
    return ranked


def _vector_ranked(tenant_id: int, kb_set: set, query: str, limit: int, tenant: Tenant | None) -> list[str]:
    """BGE-M3 向量召回，按距离升序返回 chunk_id 列表。embedding 失败直接抛错。"""
    from .model_providers import EmbeddingDimensionMismatchError, embedding

    vec = embedding(tenant, [query])[0]
    expected_dim = settings.LLM_EMBEDDING_DIM
    if len(vec) != expected_dim:
        raise EmbeddingDimensionMismatchError(
            f"query embedding dimension mismatch: expected {expected_dim}, got {len(vec)}"
        )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT rowid, distance
            FROM chunk_embeddings_vec
            WHERE embedding MATCH %s AND k = %s
            ORDER BY distance
            """,
            [pack_embedding(vec), limit],
        )
        rows = cursor.fetchall()
    if not rows:
        return []
    seq_ids = [int(row[0]) for row in rows]
    chunks = _searchable_chunks().filter(seq_id__in=seq_ids, tenant_id=tenant_id)
    if kb_set:
        chunks = chunks.filter(knowledge_base_id__in=kb_set)
    by_seq = {c.seq_id: c.id for c in chunks}
    ranked: list[str] = []
    seen: set[str] = set()
    for rowid, _distance in rows:
        chunk_id = by_seq.get(int(rowid))
        if chunk_id and chunk_id not in seen:
            seen.add(chunk_id)
            ranked.append(chunk_id)
    return ranked[:limit]


# ── RRF 融合 ─────────────────────────────────────────────────────────
def _fused_entry(chunk_id: str) -> dict:
    return {"chunk_id": chunk_id, "keyword_rank": None, "vector_rank": None, "rrf_score": 0.0, "match_sources": []}


def rrf_fuse(keyword_ranked: list[str], vector_ranked: list[str], rrf_k: int) -> list[dict]:
    """
    标准 Reciprocal Rank Fusion：score = Σ 1/(rrf_k + rank_i)，rank 从 1 开始。
    只看两路各自排名，不累加 BM25 与向量的原始分数。
    """
    fused: dict[str, dict] = {}
    for rank, chunk_id in enumerate(keyword_ranked, start=1):
        entry = fused.setdefault(chunk_id, _fused_entry(chunk_id))
        entry["keyword_rank"] = rank
        entry["rrf_score"] += 1.0 / (rrf_k + rank)
        entry["match_sources"].append("keyword")
    for rank, chunk_id in enumerate(vector_ranked, start=1):
        entry = fused.setdefault(chunk_id, _fused_entry(chunk_id))
        entry["vector_rank"] = rank
        entry["rrf_score"] += 1.0 / (rrf_k + rank)
        entry["match_sources"].append("vector")

    def _sort_key(entry: dict):
        best_rank = min(
            (r for r in (entry["keyword_rank"], entry["vector_rank"]) if r is not None),
            default=10**9,
        )
        return (-entry["rrf_score"], best_rank, entry["chunk_id"])

    return sorted(fused.values(), key=_sort_key)


def _hydrate_candidates(entries: list[dict]) -> list[dict]:
    """把 RRF 候选条目水合成完整结果字典，保留可观测排名字段。"""
    chunks = {
        c.id: c
        for c in _searchable_chunks().filter(id__in=[e["chunk_id"] for e in entries]).select_related(
            "knowledge", "knowledge_base"
        )
    }
    results = []
    for entry in entries:
        chunk = chunks.get(entry["chunk_id"])
        if not chunk:
            continue
        results.append(
            {
                "chunk_id": chunk.id,
                "id": chunk.id,
                "content": chunk.content,
                "score": entry["rrf_score"],
                "keyword_rank": entry["keyword_rank"],
                "vector_rank": entry["vector_rank"],
                "rrf_score": entry["rrf_score"],
                "rerank_score": None,
                "match_sources": list(entry["match_sources"]),
                "retrieval_path": "document",
                "knowledge_id": chunk.knowledge_id,
                "knowledge_base_id": chunk.knowledge_base_id,
                "knowledge_title": chunk.knowledge.title,
                "knowledge_description": getattr(chunk.knowledge, "description", "") or "",
                "knowledge_base_name": chunk.knowledge_base.name,
                "chunk_type": chunk.chunk_type,
                "image_info": chunk.image_info,
                "match_type": "hybrid",
                "metadata": chunk.metadata or {},
            }
        )
    return results


def _record_degradation(meta: dict, stage: str, reason: str) -> None:
    meta["degraded"] = True
    meta["degradations"].append({"stage": stage, "reason": reason})


def _error_reason(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    message = str(exc)[:300] or exc.__class__.__name__
    return f"{code}: {message}" if code else message


def _vector_recall(tenant_id: int, kb_set: set, query: str, limit: int, tenant: Tenant | None, meta: dict) -> list[str]:
    """向量召回守卫：待重建、未配置或失败时显式降级 FTS5-only 并记录原因。"""
    from .model_providers import EmbeddingDimensionMismatchError, active_embedding_config

    state = get_vector_index_state()
    if state["status"] != "ready":
        _record_degradation(meta, "vector", f"reindex_required: {state.get('reason') or 'vector index rebuild pending'}")
        return []
    cfg = active_embedding_config(tenant)
    if not cfg:
        _record_degradation(meta, "vector", "embedding model is not configured")
        return []
    meta["embedding_model"] = cfg["model"]
    try:
        return _vector_ranked(tenant_id, kb_set, query, limit, tenant)
    except EmbeddingDimensionMismatchError as exc:
        _record_degradation(meta, "vector", f"embedding_dimension_mismatch: {exc}")
    except Exception as exc:
        _record_degradation(meta, "vector", _error_reason(exc))
    return []


# ── 搜索主流程 ───────────────────────────────────────────────────────
def hybrid_search_ex(
    tenant_id: int,
    kb_ids: list[str],
    query: str,
    top_k: int = 10,
    *,
    keyword_top_k: int | None = None,
    vector_top_k: int | None = None,
    rerank_top_k: int | None = None,
    rrf_k: int | None = None,
    _resolve_parents: bool = True,
) -> tuple[list[dict], dict]:
    """
    混合检索核心管线：FTS5 BM25 与 BGE-M3 双路召回 → 标准 RRF 融合 → BGE-Reranker 重排。
    返回 (results, meta)；meta 携带降级阶段与原因、候选数量与生效模型。
    """
    ensure_search_tables()
    top_k = _bounded_int(top_k, 10, 1, 200)
    keyword_n = _bounded_int(keyword_top_k, settings.SEARCH_KEYWORD_CANDIDATE_MULTIPLIER * top_k, top_k, settings.SEARCH_MAX_CANDIDATES)
    vector_n = _bounded_int(vector_top_k, settings.SEARCH_VECTOR_CANDIDATE_MULTIPLIER * top_k, top_k, settings.SEARCH_MAX_CANDIDATES)
    rerank_n = _bounded_int(rerank_top_k, settings.SEARCH_RERANK_CANDIDATE_MULTIPLIER * top_k, top_k, settings.SEARCH_MAX_CANDIDATES)
    rrf_k = _bounded_int(rrf_k, settings.SEARCH_RRF_K, 1, 10000)
    kb_set = set(kb_ids or [])
    query = query or ""
    tenant = Tenant.objects.filter(id=tenant_id).first()

    meta = {
        "degraded": False,
        "degradations": [],
        "rrf_k": rrf_k,
        "embedding_model": "",
        "rerank_model": "",
        "candidate_counts": {"keyword": 0, "vector": 0, "fused": 0, "rerank_input": 0},
    }

    # SQLite 的虚拟表和事务连接不能安全地跨线程共享；其他数据库保留并发路径
    if connection.vendor == "sqlite":
        keyword_ranked = _fts_ranked(tenant_id, kb_set, query, keyword_n)
        vector_ranked = _vector_recall(tenant_id, kb_set, query, vector_n, tenant, meta)
    else:
        with ThreadPoolExecutor(max_workers=2) as search_pool:
            fts_future = search_pool.submit(_fts_ranked, tenant_id, kb_set, query, keyword_n)
            vec_future = search_pool.submit(_vector_recall, tenant_id, kb_set, query, vector_n, tenant, meta)
            keyword_ranked = fts_future.result()
            vector_ranked = vec_future.result()

    meta["candidate_counts"]["keyword"] = len(keyword_ranked)
    meta["candidate_counts"]["vector"] = len(vector_ranked)

    fused = rrf_fuse(keyword_ranked, vector_ranked, rrf_k)
    meta["candidate_counts"]["fused"] = len(fused)
    candidates = deduplicate_results(_hydrate_candidates(fused))

    final = candidates
    rerank_input = candidates[:rerank_n]
    if rerank_input:
        from .model_providers import active_rerank_config, rerank

        rerank_cfg = active_rerank_config(tenant)
        if not rerank_cfg:
            _record_degradation(meta, "rerank", "rerank model is not configured")
        else:
            meta["rerank_model"] = rerank_cfg["model"]
            meta["candidate_counts"]["rerank_input"] = len(rerank_input)
            try:
                final = rerank(query, rerank_input, top_k=None, tenant=tenant) + candidates[rerank_n:]
            except Exception as exc:
                _record_degradation(meta, "rerank", _error_reason(exc))

    results = final[:top_k]
    for item in results:
        item.setdefault("retrieval_path", "document")
    if _resolve_parents:
        from .parent_context import resolve_parent_context

        results = resolve_parent_context(
            results,
            tenant_id=tenant_id,
            max_context_chars=getattr(settings, "SEARCH_MAX_CONTEXT_CHARS", 4096),
        )
    return results, meta


def hybrid_search(tenant_id: int, kb_ids: list[str], query: str, top_k: int = 10, *, return_meta: bool = False):
    """
    混合检索（兼容旧签名）：核心 RRF 管线 + 查询扩展/MMR/多样化/GraphRAG 上下文扩展。
    聊天与 Agent 使用该入口；知识库检索接口使用严格排序的 hybrid_search_ex。
    return_meta=True 时返回 (results, meta)，供聊天/Agent 上报降级；默认仅返回 results 列表。
    """
    top_k = _bounded_int(top_k, 10, 1, 100)
    results, meta = hybrid_search_ex(
        tenant_id,
        kb_ids,
        query,
        top_k * 2,
        keyword_top_k=settings.SEARCH_KEYWORD_CANDIDATE_MULTIPLIER * top_k,
        vector_top_k=settings.SEARCH_VECTOR_CANDIDATE_MULTIPLIER * top_k,
        rerank_top_k=settings.SEARCH_RERANK_CANDIDATE_MULTIPLIER * top_k,
        _resolve_parents=False,
    )
    results = expand_retrieval_context(results, tenant_id, kb_ids, query, top_k)
    from .parent_context import resolve_parent_context

    results = resolve_parent_context(
        results,
        tenant_id=tenant_id,
        max_context_chars=getattr(settings, "SEARCH_MAX_CONTEXT_CHARS", 4096),
    )
    results = results[:top_k]
    return (results, meta) if return_meta else results


def _tag_graph_results(items: list[dict]) -> list[dict]:
    """GraphRAG 属于独立检索路径：明确标记来源，不伪装成双路召回结果。"""
    tagged = []
    for item in items or []:
        row = dict(item)
        sources = list(row.get("match_sources") or [])
        if "graph" not in sources:
            sources.append("graph")
        row["match_sources"] = sources
        row["retrieval_path"] = "graph"
        tagged.append(row)
    return tagged


def expand_retrieval_context(results: list[dict], tenant_id: int, kb_ids: list[str], query: str, top_k: int) -> list[dict]:
    """聊天/Agent 上下文扩展：查询扩展、MMR、文档多样化、GraphRAG 与短 Chunk 扩展。"""
    from .graph_rag import expand_relation_context, graph_search_results

    kb_set = set(kb_ids or [])
    # ── 查询扩展（召回不足时，FTS 变体补充召回）──────────────────────
    if len(results) < max(1, top_k):
        existing = {item.get("chunk_id") for item in results}
        for variant in expand_query(query):
            extra_ranked = _fts_ranked(tenant_id, kb_set, variant, top_k * 2)
            new_entries = []
            for rank, chunk_id in enumerate(extra_ranked, start=1):
                if chunk_id in existing:
                    continue
                existing.add(chunk_id)
                new_entries.append(
                    {
                        "chunk_id": chunk_id,
                        "keyword_rank": rank,
                        "vector_rank": None,
                        "rrf_score": 1.0 / (settings.SEARCH_RRF_K + rank + len(results)),
                        "match_sources": ["keyword_expansion"],
                    }
                )
            if new_entries:
                results = [*results, *_hydrate_candidates(new_entries)]

    # ── MMR 多样性过滤 + 知识条目级多样性 ────────────────────────────
    results = deduplicate_results(results)
    results = apply_mmr(results, k=min(len(results), max(1, top_k * 2)), lambda_param=0.7)
    results = diversify_by_knowledge(results, max_per_knowledge=2)

    # ── Graph RAG（独立检索路径，明确标记来源）──────────────────────
    graph_results = _tag_graph_results(
        graph_search_results(tenant_id, kb_ids or [], query, {item["chunk_id"] for item in results}, top_k)
    )
    relation_results = _tag_graph_results(expand_relation_context([*results, *graph_results], tenant_id, min(3, top_k)))
    results = deduplicate_results([*results, *graph_results, *relation_results])

    # ── 短 chunk 扩展 ──────────────────────────────────────────────
    return expand_short_chunks(results[:top_k], min_chars=350, max_chars=850)


# ── 评估基线（旧方案：原始分数直接相加，仅供检索评估对比）────────────
def _baseline_score_addition_search(tenant_id: int, kb_ids: list[str], query: str, limit: int = 40) -> list[str]:
    """旧“BM25 转换分 + 向量相似度直接相加”方案的排序结果，仅用于 MRR/Recall 基线对比。"""
    ensure_search_tables()
    kb_set = set(kb_ids or [])
    scores: dict[str, float] = {}
    with connection.cursor() as cursor:
        fts_query = " OR ".join(TOKEN_RE.findall(query)) or query
        if fts_query:
            try:
                cursor.execute(
                    """
                    SELECT chunk_id, knowledge_base_id, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    WHERE chunks_fts MATCH %s AND tenant_id = %s
                    LIMIT %s
                    """,
                    [fts_query, int(tenant_id), limit],
                )
                for chunk_id, kb_id, rank in cursor.fetchall():
                    if not kb_set or kb_id in kb_set:
                        scores[chunk_id] = scores.get(chunk_id, 0.0) + max(0.0, 10.0 - abs(float(rank)))
            except Exception:
                pass
    try:
        from .model_providers import embedding

        tenant = Tenant.objects.filter(id=tenant_id).first()
        vec = pack_embedding(embedding(tenant, [query])[0])
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rowid, distance
                FROM chunk_embeddings_vec
                WHERE embedding MATCH %s AND k = %s
                """,
                [vec, limit],
            )
            row_scores = {int(rowid): 1.0 / (1.0 + float(distance)) for rowid, distance in cursor.fetchall()}
        if row_scores:
            chunks = Chunk.objects.filter(seq_id__in=row_scores.keys(), tenant_id=tenant_id, is_enabled=True).exclude(
                chunk_type="parent_text"
            )
            if kb_set:
                chunks = chunks.filter(knowledge_base_id__in=kb_set)
            for chunk in chunks:
                scores[chunk.id] = scores.get(chunk.id, 0.0) + row_scores.get(chunk.seq_id or 0, 0.0)
    except Exception:
        pass
    return [cid for cid, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)]


# ── 向量索引重建 ─────────────────────────────────────────────────────
def _current_signature_safe() -> str:
    """以第一个拥有 Chunk 的租户解析当前生效签名；多租户 DB 配置场景下为近似值。"""
    from .model_providers import embedding_signature

    tenant_id = _searchable_chunks().values_list("tenant_id", flat=True).first()
    tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
    try:
        return embedding_signature(tenant)
    except Exception:
        return ""


def rebuild_vector_index(task_id: str = "") -> dict:
    """全量重建 BGE-M3 向量索引：分批重嵌入启用 Chunk，完成后标记 ready。"""
    from .model_providers import embedding
    from .models import TaskRecord

    ensure_search_tables()
    if task_id and TaskRecord.objects.filter(id=task_id, status="cancelled").exists():
        return {"indexed": 0, "errors": 0, "batches": 0, "cancelled": True}

    searchable = _searchable_chunks()
    valid_chunks = list(searchable.values_list("id", "seq_id"))
    valid_ids = {chunk_id for chunk_id, _seq_id in valid_chunks}
    valid_rowids = {
        seq_id if seq_id is not None else _rowid(chunk_id)
        for chunk_id, seq_id in valid_chunks
    }
    with connection.cursor() as cursor:
        stale_fts_ids = [
            row[0]
            for row in cursor.execute("SELECT chunk_id FROM chunks_fts").fetchall()
            if row[0] not in valid_ids
        ]
        stale_vector_rowids = [
            int(row[0])
            for row in cursor.execute("SELECT rowid FROM chunk_embeddings_vec").fetchall()
            if int(row[0]) not in valid_rowids
        ]
        if stale_fts_ids:
            cursor.executemany("DELETE FROM chunks_fts WHERE chunk_id = %s", [(chunk_id,) for chunk_id in stale_fts_ids])
        if stale_vector_rowids:
            cursor.executemany(
                "DELETE FROM chunk_embeddings_vec WHERE rowid = %s",
                [(rowid,) for rowid in stale_vector_rowids],
            )

    batch_size = max(1, getattr(settings, "VECTOR_REINDEX_BATCH_SIZE", 32))
    tenant_ids = list(searchable.values_list("tenant_id", flat=True).distinct())
    indexed = 0
    errors = 0
    batches = 0
    cancelled = False
    for tenant_id in tenant_ids:
        tenant = Tenant.objects.filter(id=tenant_id).first()
        qs = searchable.filter(tenant_id=tenant_id).select_related("knowledge").order_by("id")
        offset = 0
        while True:
            if task_id and TaskRecord.objects.filter(id=task_id, status="cancelled").exists():
                cancelled = True
                break
            batch = list(qs[offset : offset + batch_size])
            if not batch:
                break
            offset += batch_size
            batches += 1
            try:
                vectors = embedding(tenant, [c.embedding_content() for c in batch])
            except Exception as exc:
                errors += len(batch)
                logger.warning("Vector rebuild batch failed (tenant %s): %s", tenant_id, exc)
                continue
            with connection.cursor() as cursor:
                for chunk, vec in zip(batch, vectors):
                    rowid = chunk.seq_id if chunk.seq_id is not None else _rowid(chunk.id)
                    cursor.execute("DELETE FROM chunk_embeddings_vec WHERE rowid = %s", [rowid])
                    cursor.execute("INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)", [rowid, pack_embedding(vec)])
                    if chunk.seq_id is None:
                        Chunk.objects.filter(id=chunk.id).update(seq_id=rowid)
                    indexed += 1
        if cancelled:
            break

    if cancelled:
        return {"indexed": indexed, "errors": errors, "batches": batches, "cancelled": True}
    if indexed == 0 and errors:
        # 全部失败：保持 needs_rebuild，让任务以失败状态暴露原因
        from .model_providers import ModelConfigurationError

        raise ModelConfigurationError(f"vector index rebuild failed for all batches ({errors} chunks)")
    mark_vector_index_ready(_current_signature_safe())
    return {"indexed": indexed, "errors": errors, "batches": batches, "cancelled": False}


def ensure_rebuild_task_enqueued(reason: str = "") -> str:
    """存在待重建标记且没有进行中的重建任务时入队一个。返回任务 id 或空串。"""
    from .models import TaskRecord

    state = get_vector_index_state()
    if state["status"] == "ready":
        return ""
    active = TaskRecord.objects.filter(task_type="rebuild_vector_index", status__in=("pending", "running")).first()
    if active:
        return str(active.id)
    if not _searchable_chunks().exists():
        mark_vector_index_ready(_current_signature_safe())
        return ""
    from .tasks import enqueue

    holder: dict[str, str] = {}

    def _run():
        return rebuild_vector_index(task_id=holder.get("id", ""))

    record = enqueue("rebuild_vector_index", _run, {"reason": reason or state.get("reason", "")})
    holder["id"] = str(record.id)
    return str(record.id)


def notify_embedding_config_changed(tenant: Tenant | None = None) -> dict:
    """models_config 在生效 Embedding 配置变化后调用：标记需要重建并入队重建任务。"""
    ensure_search_tables()
    from .model_providers import embedding_signature

    current = embedding_signature(tenant)
    state = get_vector_index_state()
    if not current:
        return {"changed": False, "needs_reindex": state["status"] != "ready", "task_id": ""}
    has_chunks = _searchable_chunks().exists()
    if state["status"] == "ready" and state["signature"] == current:
        return {"changed": False, "needs_reindex": False, "task_id": ""}
    if state["status"] == "ready" and not state["signature"] and not has_chunks:
        mark_vector_index_ready(current)
        return {"changed": False, "needs_reindex": False, "task_id": ""}
    mark_vector_index_needs_rebuild("embedding_model_changed")
    task_id = ensure_rebuild_task_enqueued("embedding_model_changed")
    return {"changed": True, "needs_reindex": True, "task_id": task_id}


# ── 去重工具 ─────────────────────────────────────────────────────────
def content_signature(content: str) -> str:
    normalized = normalize_content(content)
    if not normalized:
        return ""
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def normalize_content(content: str) -> str:
    return " ".join((content or "").lower().strip().split())


def token_set(content: str) -> set[str]:
    return {token for token in TOKEN_RE.findall((content or "").lower()) if len(token) > 1}


def content_overlap_ratio(left: str, right: str) -> float:
    left_tokens = token_set(left)
    right_tokens = token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    smaller, larger = (left_tokens, right_tokens) if len(left_tokens) <= len(right_tokens) else (right_tokens, left_tokens)
    return len(smaller & larger) / max(len(smaller), 1)


def is_content_redundant(candidate: dict, kept: dict) -> bool:
    candidate_norm = normalize_content(candidate.get("content", ""))
    kept_norm = normalize_content(kept.get("content", ""))
    if not candidate_norm or not kept_norm:
        return False
    shorter, longer = (candidate_norm, kept_norm) if len(candidate_norm) <= len(kept_norm) else (kept_norm, candidate_norm)
    if len(shorter) >= 80 and shorter in longer:
        return True
    return content_overlap_ratio(candidate.get("content", ""), kept.get("content", "")) >= PARTIAL_OVERLAP_THRESHOLD


def prefer_result(left: dict, right: dict) -> dict:
    left_score = float(left.get("score") or 0)
    right_score = float(right.get("score") or 0)
    if left_score != right_score:
        return left if left_score > right_score else right
    if len(left.get("content", "")) != len(right.get("content", "")):
        return left if len(left.get("content", "")) > len(right.get("content", "")) else right
    return left


def deduplicate_results(results: list[dict]) -> list[dict]:
    by_chunk: dict[str, dict] = {}
    by_signature: dict[str, dict] = {}
    for item in results:
        chunk_id = item.get("chunk_id") or item.get("id")
        if chunk_id and chunk_id in by_chunk:
            by_chunk[chunk_id] = prefer_result(by_chunk[chunk_id], item)
            continue
        sig = content_signature(item.get("content", ""))
        if sig and sig in by_signature:
            preferred = prefer_result(by_signature[sig], item)
            old = by_signature[sig]
            old_id = old.get("chunk_id") or old.get("id")
            if preferred is item and old_id in by_chunk:
                by_chunk.pop(old_id, None)
            by_signature[sig] = preferred
            if preferred is old:
                continue
        if chunk_id:
            by_chunk[chunk_id] = item
        if sig:
            by_signature[sig] = item

    ordered = sorted(by_chunk.values(), key=lambda row: float(row.get("score") or 0), reverse=True)
    unique: list[dict] = []
    for item in ordered:
        duplicate_index = next((idx for idx, kept in enumerate(unique) if is_content_redundant(item, kept)), None)
        if duplicate_index is None:
            unique.append(item)
            continue
        preferred = prefer_result(unique[duplicate_index], item)
        if preferred is item:
            unique[duplicate_index] = item
    return sorted(unique, key=lambda row: float(row.get("score") or 0), reverse=True)


def _rowid(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:15], 16)
