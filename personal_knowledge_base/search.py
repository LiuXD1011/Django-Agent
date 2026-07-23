import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from django.conf import settings
from django.db import connection
from django.db.models import F
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


def _scoped_searchable_chunks(tenant_id: int, kb_ids: Iterable[str] | None = None):
    kb_set = set(kb_ids or [])
    chunks = _searchable_chunks().filter(
        tenant_id=tenant_id,
        knowledge__tenant_id=tenant_id,
        knowledge_base__tenant_id=tenant_id,
        knowledge__knowledge_base_id=F("knowledge_base_id"),
    )
    if kb_set:
        chunks = chunks.filter(
            knowledge_base_id__in=kb_set,
            knowledge__knowledge_base_id__in=kb_set,
        )
    return chunks


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
    chunk_ids = [
        r.get("chunk_id") or r.get("id")
        for r in results
        if r.get("retrieval_path") == "document" and r.get("chunk_type") == "text"
    ]
    if not chunk_ids:
        return results

    chunks_map = {
        chunk.id: chunk
        for chunk in _searchable_chunks().filter(
            id__in=chunk_ids,
            chunk_type="text",
            context_parent_id__isnull=True,
            knowledge__tenant_id=F("tenant_id"),
            knowledge_base__tenant_id=F("tenant_id"),
            knowledge__knowledge_base_id=F("knowledge_base_id"),
        ).select_related("knowledge", "knowledge_base")
    }

    # 查询相邻 flat text（同 tenant/knowledge/KB，按 chunk_index 排序）
    knowledge_ids = list({c.knowledge_id for c in chunks_map.values() if c})
    neighbors: dict[str, dict] = {}  # chunk_id -> {prev: chunk, next: chunk}
    if knowledge_ids:
        all_chunks = _searchable_chunks().filter(
            knowledge_id__in=knowledge_ids,
            chunk_type="text",
            context_parent_id__isnull=True,
            knowledge__tenant_id=F("tenant_id"),
            knowledge_base__tenant_id=F("tenant_id"),
            knowledge__knowledge_base_id=F("knowledge_base_id"),
        ).order_by("tenant_id", "knowledge_id", "knowledge_base_id", "chunk_index", "id").values(
            "id", "tenant_id", "knowledge_id", "knowledge_base_id", "chunk_index", "content"
        )

        by_knowledge: dict[tuple[int, str, str], list] = {}
        for c in all_chunks:
            key = (c["tenant_id"], c["knowledge_id"], c["knowledge_base_id"])
            by_knowledge.setdefault(key, []).append(c)

        for chunk_list in by_knowledge.values():
            for i, c in enumerate(chunk_list):
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

        if item.get("retrieval_path") != "document" or item.get("chunk_type") != "text":
            expanded.append(item)
            continue

        if item.get("parent_chunk_id") or cid not in chunks_map:
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


def _hydrate_candidates(entries: list[dict], *, tenant_id: int, kb_ids: Iterable[str]) -> list[dict]:
    """把 RRF 候选条目水合成完整结果字典，保留可观测排名字段。"""
    chunks = {
        c.id: c
        for c in _scoped_searchable_chunks(tenant_id, kb_ids).filter(
            id__in=[e["chunk_id"] for e in entries]
        ).select_related(
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
                "context_parent_id": chunk.context_parent_id,
                "image_info": chunk.image_info,
                "match_type": "hybrid",
                "metadata": chunk.metadata or {},
            }
        )
    return results


def _deduplicate_candidate_ids(results: list[dict]) -> list[dict]:
    by_id: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for item in results:
        chunk_id = str(item.get("chunk_id") or item.get("id") or "")
        if not chunk_id:
            continue
        key = (str(item.get("retrieval_path") or "document"), chunk_id)
        if key not in by_id:
            by_id[key] = item
            order.append(key)
            continue
        if float(item.get("score") or 0) > float(by_id[key].get("score") or 0):
            by_id[key] = item
    return [by_id[key] for key in order]


def _context_group_count(results: list[dict]) -> int:
    groups = set()
    for item in results:
        if item.get("retrieval_path") != "document":
            continue
        chunk_id = item.get("chunk_id") or item.get("id")
        if not chunk_id:
            continue
        if item.get("chunk_type") == "text":
            parent_id = item.get("context_parent_id")
            groups.add(("parent", parent_id) if parent_id else ("flat", chunk_id))
        elif item.get("chunk_type") in {"image_ocr", "image_caption"}:
            groups.add(("media", chunk_id))
    return len(groups)


def _record_degradation(meta: dict, stage: str, reason: str) -> None:
    meta["degraded"] = True
    meta["degradations"].append({"stage": stage, "reason": reason})


def _error_reason(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    message = str(exc)[:300] or exc.__class__.__name__
    return f"{code}: {message}" if code else message


def _stamp_final_ranks(candidates: list[dict]) -> list[dict]:
    return [
        {**candidate, "final_rank": rank}
        for rank, candidate in enumerate(candidates, start=1)
    ]


def _rerank_candidates(
    query: str,
    candidates: list[dict],
    *,
    tenant: Tenant | None,
    meta: dict,
    limit: int,
) -> list[dict]:
    rerank_input = candidates[: max(0, limit)]
    if not rerank_input:
        return _stamp_final_ranks(candidates)

    from .model_providers import active_rerank_config, rerank

    rerank_cfg = active_rerank_config(tenant)
    if not rerank_cfg:
        if not any(item.get("stage") == "rerank" for item in meta["degradations"]):
            _record_degradation(meta, "rerank", "rerank model is not configured")
        return _stamp_final_ranks(candidates)
    meta["rerank_model"] = rerank_cfg["model"]
    meta["candidate_counts"]["rerank_input"] = len(rerank_input)
    try:
        ranked = rerank(query, rerank_input, top_k=None, tenant=tenant) + candidates[len(rerank_input):]
        return _stamp_final_ranks(ranked)
    except Exception as exc:
        _record_degradation(meta, "rerank", _error_reason(exc))
        return _stamp_final_ranks(candidates)


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
    _defer_rerank: bool = False,
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
    candidates = _deduplicate_candidate_ids(
        _hydrate_candidates(fused, tenant_id=tenant_id, kb_ids=kb_set)
    )

    final = candidates
    if not _defer_rerank:
        final = _rerank_candidates(query, candidates, tenant=tenant, meta=meta, limit=rerank_n)

    results = final
    for item in results:
        item.setdefault("retrieval_path", "document")
    if _resolve_parents:
        from .parent_context import resolve_parent_context

        results = resolve_parent_context(
            results,
            tenant_id=tenant_id,
            max_context_chars=getattr(settings, "SEARCH_MAX_CONTEXT_CHARS", 4096),
        )
        results = deduplicate_results(results)
        results = results[:top_k]
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
        _defer_rerank=True,
    )
    results = expand_retrieval_context(results, tenant_id, kb_ids, query, top_k, meta=meta)
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


def expand_retrieval_context(
    results: list[dict],
    tenant_id: int,
    kb_ids: list[str],
    query: str,
    top_k: int,
    *,
    meta: dict | None = None,
) -> list[dict]:
    """聊天/Agent 上下文扩展：查询扩展、MMR、文档多样化、GraphRAG 与短 Chunk 扩展。"""
    from .graph_rag import expand_relation_context, graph_search_results

    kb_set = set(kb_ids or [])
    # ── 查询扩展（召回不足时，FTS 变体补充召回）──────────────────────
    if _context_group_count(results) < max(1, top_k):
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
                results = [
                    *results,
                    *_hydrate_candidates(new_entries, tenant_id=tenant_id, kb_ids=kb_set),
                ]
            if _context_group_count(results) >= max(1, top_k):
                break

    results = _deduplicate_candidate_ids(results)
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if meta is None:
        meta = {
            "degraded": False,
            "degradations": [],
            "rerank_model": "",
            "candidate_counts": {"rerank_input": 0},
        }
    results = _rerank_candidates(
        query,
        results,
        tenant=tenant,
        meta=meta,
        limit=len(results),
    )

    # ── Graph RAG（独立检索路径，明确标记来源）──────────────────────
    graph_results = _tag_graph_results(
        graph_search_results(tenant_id, kb_ids or [], query, {item["chunk_id"] for item in results}, top_k)
    )
    relation_results = _tag_graph_results(expand_relation_context([*results, *graph_results], tenant_id, min(3, top_k)))
    results = _deduplicate_candidate_ids([*results, *graph_results, *relation_results])

    # ── 短 chunk 扩展 ──────────────────────────────────────────────
    results = expand_short_chunks(results, min_chars=350, max_chars=850)

    from .parent_context import resolve_parent_context

    results = resolve_parent_context(
        results,
        tenant_id=tenant_id,
        max_context_chars=getattr(settings, "SEARCH_MAX_CONTEXT_CHARS", 4096),
    )
    documents, graph_results = _deduplicate_result_cohorts(results)
    documents = apply_mmr(
        documents,
        k=min(len(documents), max(1, top_k * 2)),
        lambda_param=0.7,
    )
    documents = _order_cohort(documents, documents=True)
    documents = diversify_by_knowledge(documents, max_per_knowledge=max(2, top_k))
    graph_results = diversify_by_knowledge(graph_results, max_per_knowledge=max(2, top_k))
    return _merge_document_and_graph_results(documents, graph_results)


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
    """Choose within the reranked document cohort only."""
    left_rank = _positive_final_rank(left)
    right_rank = _positive_final_rank(right)
    if left_rank is not None and right_rank is not None:
        return left if left_rank <= right_rank else right
    return _prefer_unranked_result(left, right)


def _prefer_unranked_result(left: dict, right: dict) -> dict:
    left_score = float(left.get("score") or 0)
    right_score = float(right.get("score") or 0)
    if left_score != right_score:
        return left if left_score > right_score else right
    if len(left.get("content", "")) != len(right.get("content", "")):
        return left if len(left.get("content", "")) > len(right.get("content", "")) else right
    return left


def _positive_final_rank(item: dict) -> int | None:
    try:
        rank = int(item.get("final_rank"))
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def _order_cohort(results: list[dict], *, documents: bool) -> list[dict]:
    indexed = list(enumerate(results))
    if documents and any(_positive_final_rank(item) is not None for _index, item in indexed):
        indexed.sort(key=lambda entry: (_positive_final_rank(entry[1]) or 10**9, entry[0]))
    else:
        indexed.sort(key=lambda entry: (-float(entry[1].get("score") or 0), entry[0]))
    return [item for _index, item in indexed]


def _merge_document_and_graph_results(
    documents: list[dict], graph_results: list[dict]
) -> list[dict]:
    """Interleave preselected cohorts as the final ordering operation."""
    documents = _order_cohort(documents, documents=True)
    graph_results = _order_cohort(graph_results, documents=False)

    merged = []
    for index in range(max(len(documents), len(graph_results))):
        if index < len(documents):
            merged.append(documents[index])
        if index < len(graph_results):
            merged.append(graph_results[index])
    return merged


def _deduplicate_cohort(results: list[dict], *, documents: bool) -> list[dict]:
    by_chunk: dict[str, dict] = {}
    by_signature: dict[str, dict] = {}
    for item in results:
        chunk_id = item.get("chunk_id") or item.get("id")
        if chunk_id and chunk_id in by_chunk:
            chooser = prefer_result if documents else _prefer_unranked_result
            by_chunk[chunk_id] = chooser(by_chunk[chunk_id], item)
            continue
        sig = content_signature(item.get("content", ""))
        if sig and sig in by_signature:
            chooser = prefer_result if documents else _prefer_unranked_result
            preferred = chooser(by_signature[sig], item)
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

    ordered = _order_cohort(list(by_chunk.values()), documents=documents)
    unique: list[dict] = []
    for item in ordered:
        duplicate_index = next((idx for idx, kept in enumerate(unique) if is_content_redundant(item, kept)), None)
        if duplicate_index is None:
            unique.append(item)
            continue
        chooser = prefer_result if documents else _prefer_unranked_result
        preferred = chooser(unique[duplicate_index], item)
        if preferred is item:
            unique[duplicate_index] = item
    return _order_cohort(unique, documents=documents)


def _graph_provenance_key(item: dict) -> tuple[str, str, str]:
    return (
        str(item.get("chunk_id") or item.get("id") or ""),
        str(item.get("relation_type") or ""),
        content_signature(str(item.get("content") or "")),
    )


def _merge_graph_attribution(document: dict, graph: dict) -> dict:
    row = dict(document)
    sources = list(row.get("match_sources") or [])
    for source in graph.get("match_sources") or []:
        if source not in sources:
            sources.append(source)
    row["match_sources"] = sources

    provenance = [dict(item) for item in row.get("graph_provenance") or [] if isinstance(item, dict)]
    seen = {_graph_provenance_key(item) for item in provenance}
    for item in graph.get("graph_provenance") or [graph]:
        if not isinstance(item, dict):
            continue
        key = _graph_provenance_key(item)
        if key not in seen:
            provenance.append(dict(item))
            seen.add(key)
    row["graph_provenance"] = provenance
    return row


def _deduplicate_result_cohorts(results: list[dict]) -> tuple[list[dict], list[dict]]:
    documents = _deduplicate_cohort(
        [item for item in results if item.get("retrieval_path") != "graph"],
        documents=True,
    )
    graph_results = _deduplicate_cohort(
        [item for item in results if item.get("retrieval_path") == "graph"],
        documents=False,
    )
    remaining_graphs = []
    for graph in graph_results:
        duplicate_index = next(
            (index for index, document in enumerate(documents) if is_content_redundant(graph, document)),
            None,
        )
        if duplicate_index is None:
            remaining_graphs.append(graph)
            continue
        documents[duplicate_index] = _merge_graph_attribution(documents[duplicate_index], graph)
    return _order_cohort(documents, documents=True), _order_cohort(remaining_graphs, documents=False)


def deduplicate_results(results: list[dict]) -> list[dict]:
    documents, graph_results = _deduplicate_result_cohorts(results)
    return _merge_document_and_graph_results(documents, graph_results)


def _rowid(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:15], 16)
