import hashlib
import math
import re
from typing import Iterable

from django.conf import settings
from django.db import connection

from .models import Chunk


TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
PARTIAL_OVERLAP_THRESHOLD = 0.85

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


def stable_embedding(text: str, dim: int | None = None) -> list[float]:
    dim = dim or settings.WEKNORA_EMBEDDING_DIM
    vec = [0.0] * dim
    tokens = TOKEN_RE.findall((text or "").lower())
    if not tokens:
        tokens = [text or ""]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for i, byte in enumerate(digest):
            idx = (byte + i * 31) % dim
            vec[idx] += 1.0 if byte % 2 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def pack_embedding(vec: Iterable[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(list(vec))


def ensure_search_tables():
    dim = settings.WEKNORA_EMBEDDING_DIM
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(chunk_id UNINDEXED, tenant_id UNINDEXED, knowledge_base_id UNINDEXED,
                       knowledge_id UNINDEXED, title, content)
            """
        )
        cursor.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings_vec USING vec0(embedding float[{dim}])"
        )


def index_chunk(chunk: Chunk):
    ensure_search_tables()
    knowledge = chunk.knowledge
    from .model_providers import embedding

    vec = pack_embedding(embedding(chunk.tenant, [chunk.content], chunk.knowledge.embedding_model_id)[0])
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = %s", [chunk.id])
        cursor.execute("DELETE FROM chunk_embeddings_vec WHERE rowid = %s", [chunk.seq_id or _rowid(chunk.id)])
        cursor.execute(
            """
            INSERT INTO chunks_fts(chunk_id, tenant_id, knowledge_base_id, knowledge_id, title, content)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [chunk.id, chunk.tenant_id, chunk.knowledge_base_id, chunk.knowledge_id, knowledge.title, chunk.content],
        )
        rowid = chunk.seq_id or _rowid(chunk.id)
        cursor.execute(
            "INSERT INTO chunk_embeddings_vec(rowid, embedding) VALUES (%s, %s)",
            [rowid, vec],
        )
    if not chunk.seq_id:
        Chunk.objects.filter(id=chunk.id).update(seq_id=rowid)


def delete_chunk_index(chunk_id: str, seq_id: int | None = None):
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = %s", [chunk_id])
        if seq_id:
            cursor.execute("DELETE FROM chunk_embeddings_vec WHERE rowid = %s", [seq_id])


# ── 查询扩展 ─────────────────────────────────────────────────────────
def expand_query(query: str) -> list[str]:
    """当召回不足时，生成查询变体以提高召回率。参考 WeKnora 的 query_expansion.go。"""
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

    selected: list[int] = []
    remaining = list(range(len(results)))

    for _ in range(k):
        if not remaining:
            break
        best_idx = -1
        best_mmr = -float("inf")

        for idx in remaining:
            relevance = results[idx].get("score", 0)
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
    参考 WeKnora 的文档级多样性策略。
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
    参考 WeKnora 的 merge_expand.go。
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
        ).order_by("knowledge_id", "chunk_index").values("id", "knowledge_id", "chunk_index", "content")

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


# ── 搜索主流程 ───────────────────────────────────────────────────────
def hybrid_search(tenant_id: int, kb_ids: list[str], query: str, top_k: int = 10) -> list[dict]:
    ensure_search_tables()
    kb_set = set(kb_ids)
    scores: dict[str, float] = {}
    query = query or ""

    # ── 第一轮检索 ──────────────────────────────────────────────────
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
                    [fts_query, str(tenant_id), top_k * 4],
                )
                for chunk_id, kb_id, rank in cursor.fetchall():
                    if not kb_set or kb_id in kb_set:
                        scores[chunk_id] = scores.get(chunk_id, 0.0) + max(0.0, 10.0 - abs(float(rank)))
            except Exception:
                cursor.execute(
                    """
                    SELECT chunk_id, knowledge_base_id FROM chunks_fts
                    WHERE tenant_id = %s AND content LIKE %s
                    LIMIT %s
                    """,
                    [str(tenant_id), f"%{query}%", top_k * 4],
                )
                for chunk_id, kb_id in cursor.fetchall():
                    if not kb_set or kb_id in kb_set:
                        scores[chunk_id] = scores.get(chunk_id, 0.0) + 3.0
        try:
            vec = pack_embedding(stable_embedding(query))
            cursor.execute(
                """
                SELECT rowid, distance
                FROM chunk_embeddings_vec
                WHERE embedding MATCH %s AND k = %s
                """,
                [vec, top_k * 4],
            )
            row_scores = {int(rowid): 1.0 / (1.0 + float(distance)) for rowid, distance in cursor.fetchall()}
            if row_scores:
                chunks = Chunk.objects.filter(seq_id__in=row_scores.keys(), tenant_id=tenant_id, is_enabled=True)
                if kb_set:
                    chunks = chunks.filter(knowledge_base_id__in=kb_set)
                for chunk in chunks:
                    scores[chunk.id] = scores.get(chunk.id, 0.0) + row_scores.get(chunk.seq_id or 0, 0.0)
        except Exception:
            pass

    # ── 查询扩展（召回不足时）────────────────────────────────────────
    if len(scores) < max(1, top_k):
        for variant in expand_query(query):
            with connection.cursor() as cursor:
                exp_fts = " OR ".join(TOKEN_RE.findall(variant)) or variant
                if exp_fts:
                    try:
                        cursor.execute(
                            """
                            SELECT chunk_id, knowledge_base_id, bm25(chunks_fts) AS rank
                            FROM chunks_fts WHERE chunks_fts MATCH %s AND tenant_id = %s LIMIT %s
                            """,
                            [exp_fts, str(tenant_id), top_k * 2],
                        )
                        for chunk_id, kb_id, rank in cursor.fetchall():
                            if not kb_set or kb_id in kb_set:
                                scores[chunk_id] = scores.get(chunk_id, 0.0) + max(0.0, 8.0 - abs(float(rank)))
                    except Exception:
                        pass

    # ── 排序 + 去重 ─────────────────────────────────────────────────
    ranked_ids = [cid for cid, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[: top_k * 4]]
    chunks = {c.id: c for c in Chunk.objects.filter(id__in=ranked_ids).select_related("knowledge", "knowledge_base")}
    results = []
    for cid in ranked_ids:
        chunk = chunks.get(cid)
        if not chunk:
            continue
        results.append(
            {
                "chunk_id": chunk.id,
                "id": chunk.id,
                "content": chunk.content,
                "score": scores[cid],
                "knowledge_id": chunk.knowledge_id,
                "knowledge_base_id": chunk.knowledge_base_id,
                "knowledge_title": chunk.knowledge.title,
                "knowledge_description": getattr(chunk.knowledge, "description", "") or "",
                "knowledge_base_name": chunk.knowledge_base.name,
                "match_type": "hybrid",
                "metadata": chunk.metadata or {},
            }
        )

    from .model_providers import rerank
    from .graph_rag import expand_relation_context, graph_search_results
    from .models import Tenant

    results = deduplicate_results(results)
    results = rerank(query, results, top_k * 2, tenant=Tenant.objects.filter(id=tenant_id).first())
    results = deduplicate_results(results)

    # ── MMR 多样性过滤 ──────────────────────────────────────────────
    results = apply_mmr(results, k=min(len(results), max(1, top_k * 2)), lambda_param=0.7)

    # ── 知识条目级多样性 ────────────────────────────────────────────
    results = diversify_by_knowledge(results, max_per_knowledge=2)

    # ── Graph RAG ───────────────────────────────────────────────────
    graph_results = graph_search_results(tenant_id, kb_ids, query, {item["chunk_id"] for item in results}, top_k)
    relation_results = expand_relation_context([*results, *graph_results], tenant_id, min(3, top_k))
    results = deduplicate_results([*results, *graph_results, *relation_results])

    # ── 短 chunk 扩展 ──────────────────────────────────────────────
    results = expand_short_chunks(results[:top_k], min_chars=350, max_chars=850)

    return results[:top_k]


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
