"""
文档解析 Span 追踪器

参考 WeKnora 的 knowledge_span_tracker.go，记录文档解析各阶段的进度。
用于前端瀑布图可视化。

五个标准阶段：docreader → chunking → embedding → multimodal → postprocess
"""

import logging
import uuid
from datetime import timezone as tz

from django.utils import timezone

from .models import Knowledge, KnowledgeProcessingSpan

logger = logging.getLogger(__name__)

# 标准阶段定义
STAGES = ["docreader", "chunking", "embedding", "multimodal", "postprocess"]

# 阶段依赖关系
STAGE_DEPENDENCIES = {
    "chunking": ["docreader"],
    "embedding": ["chunking"],
    "multimodal": ["chunking"],
    "postprocess": ["embedding", "multimodal"],
}


class SpanTracker:
    """文档解析 Span 追踪器。"""

    def __init__(self, knowledge_id: str):
        self.knowledge_id = knowledge_id
        self._knowledge = None

    @property
    def knowledge(self):
        if self._knowledge is None:
            self._knowledge = Knowledge.objects.filter(id=self.knowledge_id).first()
        return self._knowledge

    def open_attempt(self, attempt: int = 1) -> KnowledgeProcessingSpan | None:
        """创建根 Span（新的解析尝试）。"""
        if not self.knowledge:
            return None
        try:
            span = KnowledgeProcessingSpan.objects.create(
                knowledge=self.knowledge,
                attempt=attempt,
                span_id=uuid.uuid4().hex,
                name="process_knowledge",
                kind="root",
                status="running",
                started_at=timezone.now(),
            )
            return span
        except Exception:
            logger.exception("Failed to open attempt span")
            return None

    def begin_stage(self, stage_name: str, attempt: int = 1, input_data: dict = None) -> KnowledgeProcessingSpan | None:
        """开始一个阶段 Span。"""
        if not self.knowledge:
            return None
        try:
            # 查找或创建
            span, created = KnowledgeProcessingSpan.objects.update_or_create(
                knowledge=self.knowledge,
                attempt=attempt,
                name=stage_name,
                kind="stage",
                defaults={
                    "span_id": uuid.uuid4().hex,
                    "status": "running",
                    "input_data": input_data or {},
                    "started_at": timezone.now(),
                    "finished_at": None,
                    "duration_ms": 0,
                    "error_message": "",
                },
            )
            return span
        except Exception:
            logger.exception(f"Failed to begin stage {stage_name}")
            return None

    def begin_subspan(self, parent_span_id: str, name: str, input_data: dict = None) -> KnowledgeProcessingSpan | None:
        """在父 Span 下创建子 Span。"""
        try:
            span = KnowledgeProcessingSpan.objects.create(
                knowledge_id=self.knowledge_id,
                parent_span_id=parent_span_id,
                span_id=uuid.uuid4().hex,
                name=name,
                kind="subspan",
                status="running",
                input_data=input_data or {},
                started_at=timezone.now(),
            )
            return span
        except Exception:
            logger.exception(f"Failed to begin subspan {name}")
            return None

    def end_span(self, span_id: str, output_data: dict = None):
        """结束一个 Span（成功）。"""
        try:
            span = KnowledgeProcessingSpan.objects.filter(span_id=span_id).first()
            if span:
                now = timezone.now()
                span.status = "done"
                span.output_data = output_data or {}
                span.finished_at = now
                if span.started_at:
                    span.duration_ms = int((now - span.started_at).total_seconds() * 1000)
                span.save(update_fields=["status", "output_data", "finished_at", "duration_ms"])
        except Exception:
            logger.exception(f"Failed to end span {span_id}")

    def fail_span(self, span_id: str, error_message: str = "", error_detail: str = ""):
        """标记 Span 失败。"""
        try:
            span = KnowledgeProcessingSpan.objects.filter(span_id=span_id).first()
            if span:
                now = timezone.now()
                span.status = "failed"
                span.error_message = error_message[:1024]
                span.error_detail = error_detail[:8192]
                span.finished_at = now
                if span.started_at:
                    span.duration_ms = int((now - span.started_at).total_seconds() * 1000)
                span.save(update_fields=["status", "error_message", "error_detail", "finished_at", "duration_ms"])
        except Exception:
            logger.exception(f"Failed to fail span {span_id}")

    def skip_stage(self, stage_name: str, attempt: int = 1):
        """跳过一个阶段。"""
        try:
            KnowledgeProcessingSpan.objects.filter(
                knowledge_id=self.knowledge_id,
                attempt=attempt,
                name=stage_name,
                kind="stage",
                status="pending",
            ).update(status="skipped")
        except Exception:
            pass

    def finalize_attempt(self, attempt: int = 1):
        """完成整个尝试（关闭根 Span）。"""
        try:
            root = KnowledgeProcessingSpan.objects.filter(
                knowledge_id=self.knowledge_id,
                attempt=attempt,
                kind="root",
            ).first()
            if root and root.status == "running":
                now = timezone.now()
                root.status = "done"
                root.finished_at = now
                if root.started_at:
                    root.duration_ms = int((now - root.started_at).total_seconds() * 1000)
                root.save(update_fields=["status", "finished_at", "duration_ms"])
        except Exception:
            pass

    def get_spans(self, attempt: int = None) -> list[dict]:
        """获取所有 Span（用于前端展示）。"""
        qs = KnowledgeProcessingSpan.objects.filter(knowledge_id=self.knowledge_id)
        if attempt is not None:
            qs = qs.filter(attempt=attempt)
        qs = qs.order_by("started_at", "id")

        spans = []
        for s in qs:
            spans.append({
                "id": s.span_id,
                "parent_id": s.parent_span_id,
                "name": s.name,
                "kind": s.kind,
                "status": s.status,
                "input": s.input_data,
                "output": s.output_data,
                "metadata": s.metadata,
                "error_code": s.error_code,
                "error_message": s.error_message,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "duration_ms": s.duration_ms,
            })
        return spans
