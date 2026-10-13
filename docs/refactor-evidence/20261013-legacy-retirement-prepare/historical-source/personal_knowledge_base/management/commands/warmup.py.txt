"""服务启动预热：消除首条消息的组件冷启动开销。

实测冷启动成本分布：搜索管线（嵌入客户端初始化 + 首次调用）约 4s，
litellm 导入约 2-4s；LLM reasoning 本身的延迟与本项目无关。
在 runserver / 部署后执行一次 `python manage.py warmup`，可让首条消息
省去这些一次性开销。

用法：
    python manage.py warmup            # 预热搜索管线（无 LLM 调用，不花钱）
    python manage.py warmup --llm      # 额外发一个 1 token 的 LLM 探活请求
"""

import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "预热检索管线与模型配置解析，消除首条消息的冷启动延迟"

    def add_arguments(self, parser):
        parser.add_argument("--llm", action="store_true", help="额外发送一个极小 LLM 请求预热 litellm")
        parser.add_argument("--tenant-id", default="", help="指定租户（默认取第一个租户）")

    def handle(self, *args, **options):
        from personal_knowledge_base.models import KnowledgeBase, Tenant

        # 1. 解析模型配置（含 env 兜底链）
        t0 = time.monotonic()
        from personal_knowledge_base.model_providers import active_embedding_config

        active_embedding_config()
        self.stdout.write(f"模型配置解析: {time.monotonic() - t0:.2f}s")

        # 2. 首次混合检索（触发嵌入客户端初始化 + 首次向量化）
        tenant = None
        if options["tenant_id"]:
            tenant = Tenant.objects.filter(id=options["tenant_id"]).first()
        if not tenant:
            tenant = Tenant.objects.first()
        if tenant:
            kb_ids = list(
                KnowledgeBase.objects.filter(tenant=tenant, deleted_at__isnull=True, is_temporary=False)
                .values_list("id", flat=True)[:3]
            )
            if kb_ids:
                from personal_knowledge_base.search import hybrid_search_ex

                t0 = time.monotonic()
                refs, _ = hybrid_search_ex(str(tenant.id), kb_ids, "warmup", 1)
                self.stdout.write(
                    f"首次混合检索: {time.monotonic() - t0:.2f}s (hits={len(refs)}, tenant={tenant.id})"
                )
            else:
                self.stdout.write("租户下没有知识库，跳过检索预热")
        else:
            self.stdout.write("没有租户，跳过检索预热")

        # 3. 可选：LLM 探活（导入 litellm + 最小请求）
        if options["llm"]:
            from personal_knowledge_base.model_providers import chat_completion

            t0 = time.monotonic()
            try:
                chat_completion(tenant, [{"role": "user", "content": "ok"}], max_tokens=1)
                self.stdout.write(f"LLM 探活: {time.monotonic() - t0:.2f}s")
            except Exception as exc:
                self.stdout.write(f"LLM 探活失败（不影响预热）: {exc}")

        self.stdout.write(self.style.SUCCESS("warmup 完成"))
