# Langfuse 运维手册（Django-Agent 接入）

> 2026-09-22 复核修订。具体修复与本轮验证结果见 langfuse-implementation-report.md。

- 适用版本：langfuse Python SDK `3.15.0`（固定）+ Langfuse Server `3.225.8`（固定，web 与 worker 同版本）
- 部署形态：本机 Docker Compose（`docker-compose.langfuse.yml`），仅向宿主暴露 `127.0.0.1:3000`
- 设计原则：Langfuse 是旁路观测副本。任何上报失败不影响问答/解析/评估主流程，
  也不会导致模型被重复调用。本地事件（SessionEvent/ModelUsage/KnowledgeProcessingSpan）
  始终是业务事实源。

## 1. 首次部署

```bash
cd /home/liuxuedeng/Django-Agent
# 1) 生成服务端密钥（.env.langfuse 已被 gitignore，含真实密码，禁止提交）
test -e .env.langfuse || cp .env.langfuse.example .env.langfuse
chmod 600 .env.langfuse
# 编辑 .env.langfuse，把 CHANGEME 全部替换为随机值：
#   openssl rand -hex 32   # NEXTAUTH_SECRET / SALT / ENCRYPTION_KEY
# 首次初始化（可选，也可在 UI 手动注册）：
#   LANGFUSE_INIT_ORG_ID / LANGFUSE_INIT_PROJECT_ID / LANGFUSE_INIT_USER_EMAIL 等见模板注释

# 2) 校验并启动（必须用 --env-file，避免读取 Django 的 .env）
docker compose --env-file .env.langfuse -f docker-compose.langfuse.yml config --quiet
docker compose --env-file .env.langfuse -f docker-compose.langfuse.yml up -d
docker compose --env-file .env.langfuse -f docker-compose.langfuse.yml ps   # 全部 healthy

# 3) 获取 API Key
#   已配置 LANGFUSE_INIT_PROJECT_PUBLIC_KEY/SECRET_KEY 时直接读 .env.langfuse；
#   否则打开 http://127.0.0.1:3000 注册登录 → 项目设置 → API Keys 创建 pk-lf-/sk-lf-。

# 4) 配置应用（写入应用 .env 或部署环境变量；不覆盖既有 secret）
#   LANGFUSE_ENABLED=true
#   LANGFUSE_BASE_URL=http://127.0.0.1:3000
#   LANGFUSE_PUBLIC_KEY=pk-lf-...
#   LANGFUSE_SECRET_KEY=sk-lf-...
#   # 前端跳转（可选）：
#   LANGFUSE_UI_BASE_URL=http://127.0.0.1:3000
#   LANGFUSE_UI_PROJECT_ID=proj-django-agent-dev
#   LANGFUSE_TRACE_LINKS_ENABLED=true

# 5) 重启应用 worker/进程后验证
python manage.py langfuse_check --smoke
```

首次启动注意：`LANGFUSE_INIT_*` 仅在组织/项目不存在时生效；已初始化后修改这些
变量无效。SALT / ENCRYPTION_KEY 应按持久密钥保管，未经迁移方案不要替换；NEXTAUTH_SECRET 的轮换会影响会话有效性，应按维护计划执行。

## 2. 配置总表（应用侧，settings.py 读取）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| LANGFUSE_ENABLED | false | 总开关；false 时不再创建新的上报；已排队数据仍可能发送。升级自旧版（有密钥即启用）的部署必须显式设置 true |
| LANGFUSE_BASE_URL | http://localhost:3000 | 服务端地址（新首选）；`LANGFUSE_HOST` 为兼容别名 |
| LANGFUSE_PUBLIC_KEY / SECRET_KEY | 空 | 后端凭证；缺失时降级为本地模式 |
| LANGFUSE_LOG_CONTENT | false | 内容采集；true 时问题/回答/工具参数经脱敏+截断后上报（密钥类键任何情况都打码） |
| LANGFUSE_ORPHAN_MODE | skip | 无 trace 上下文时 generation：skip / standalone |
| LANGFUSE_UPLOAD_EVAL_DATASETS | false | 评估题目/参考答案上传为 Dataset；还需 LANGFUSE_LOG_CONTENT=true；同版本同内容使用稳定 item ID |
| LANGFUSE_TRACING_ENVIRONMENT | development | SDK environment 标签 |
| LANGFUSE_SAMPLE_RATE | 1.0 | 门面根级采样（0~1）；子节点随根继承，不与 SDK 采样叠加 |
| LANGFUSE_UI_BASE_URL | =BASE_URL | 浏览器可访问的 UI 地址 |
| LANGFUSE_UI_PROJECT_ID | 空 | 追踪跳转 URL 中的项目 ID |
| LANGFUSE_TRACE_LINKS_ENABLED | false | 轨迹面板"查看 Langfuse 追踪"开关；开启后仅平台运维角色（is_active + is_system_admin）可见链接 |

## 3. 诊断

```bash
# 离线：配置/版本/SDK（退出码 0 通过；1 总开关关；2 SDK 缺失；3 凭证缺失；4 初始化失败）
python manage.py langfuse_check

# 联网：服务可达 + 鉴权（5 不可达；6 鉴权失败）
python manage.py langfuse_check --network

# 冒烟：合成 trace（不调用真实 LLM）→ flush → 服务端回读校验（7 校验失败/超时）
python manage.py langfuse_check --smoke
```

冒烟数据带 `test_run_id=smoke-...` 标记；如需清理可在 UI 按 trace_id 或 test_run_id
过滤删除，命令本身不删除任何服务端数据。

服务端健康：`curl http://127.0.0.1:3000/api/public/health` → `{"status":"OK","version":"3.225.8"}`

initialized ≠ 健康：SDK 客户端构造成功不代表服务端可达/入库；以 `--smoke` 的
"verified" 为准。查询有最终一致性延迟（秒级），`--smoke` 内置退避轮询（默认回读阶段 30s 截止；不含健康/鉴权/flush/进程退出）。trace 已可查但子节点尚未齐全时仍继续等待。

## 4. 已知环境风险

### 4.1 本机代理劫持 loopback

若 shell 设置了 `HTTP_PROXY/HTTPS_PROXY`（如 `http://127.0.0.1:7897`）且 `no_proxy`
使用 `127.*` 通配格式，requests/httpx **不识别该通配**，发往 `127.0.0.1:3000` 的上报
会经代理转发。代理进程可达 loopback 时仍能成功，但代理停止/异常时上报失败。

建议（二选一）：
- 应用进程环境把 `no_proxy`/`NO_PROXY` 设为后缀形式：`127.0.0.1,localhost`；
- 如确需代理，使用已验证的代理配置；不要把“诊断直连成功”等同于“SDK 导出路径成功”。

诊断命令（区分直连与经代理）：

```bash
python3 - <<'PY'
import requests
for label, trust_env in [("direct", False), ("environment proxy", True)]:
    with requests.Session() as session:
        session.trust_env = trust_env
        try:
            response = session.get("http://127.0.0.1:3000/api/public/health", timeout=3)
            print(label, "HTTP", response.status_code)
        except Exception as exc:
            print(label, "FAIL", type(exc).__name__)
PY
```

### 4.2 SDK flush 与进程退出

- 在线请求不逐条 flush；离线验收在明确边界调用 flush，然后真实回读。
- 当前固定 SDK 3.15.0。原报告记录了 flush_interval/score 队列退出等待问题；
  不在生产随意改变该参数。当前真实 SDK 契约测试使用隔离客户端和本地 sink。
- atexit 不是 SIGTERM 清理的保证。是否 flush 取决于应用服务器的信号处理、
  worker 生命周期钩子及终止宽限期；本轮未重新验证进程级优雅退出。
- kill -9 不运行清理代码，内存中的观测队列可能丢失；本地持久业务状态才是恢复依据。

### 4.3 autoreload 与多进程

每个 worker 持有自己的客户端；不要把已初始化的客户端跨 fork 复用。
Django --noreload 的测试不能证明 autoreload 没有重复 exporter；上线前应在实际
启动方式下实测。配置或密钥变更后重启相关 worker；缓存客户端不会自动重载这些参数。

## 5. 日常运维

- 日志：`docker compose --env-file .env.langfuse -f docker-compose.langfuse.yml logs -f langfuse-web langfuse-worker`
- 重启单服务：`... restart langfuse-web`
- 升级：改动 `docker-compose.langfuse.yml` 中的镜像 tag → `config --quiet` → `up -d`。
  升级前阅读官方迁移说明；已升级数据库**不能仅回退镜像 tag**（回退需从备份恢复）。
- 备份：`langfuse-postgres-data`、`langfuse-clickhouse-data`、`langfuse-minio-data`、
  `langfuse-redis-data` 卷 + `.env.langfuse`（含密钥，与数据同等级别保管）。
  恢复演练在隔离实例进行，不直接覆盖生产卷。

## 6. 关闭与回滚

### 6.1 配置关闭（首选回滚手段）

应用 `.env` 设 `LANGFUSE_ENABLED=false` → 重启应用进程。新请求零出网，本地
事件/用量/解析状态照常；已上传的服务端数据保留不删除。队列中已排队的少量数据
在关闭前照常发送或丢弃，不影响业务。

### 6.2 代码回退

本轮改动全部在 git 工作区，可用常规 git 手段（stash/分支/commit revert）回退；
**禁止**用 `reset --hard`、清空工作区或覆盖 `.env` 作为自动回滚手段。回退后：
- 新事件 `observability/trace-linked` 是可忽略增量，旧代码按未知事件拒绝写入
  但不读取，历史数据不受影响（旧代码只读 turn/completed.langfuse_trace_id）；
- 无新增数据库迁移；
- requirements 中 `langfuse==3.15.0` 可保留；但回退到“有密钥即启用”的旧代码时，必须同时移除进程中的 Langfuse 凭证或保留兼容关闭逻辑，不能仅依赖旧代码不认识的 LANGFUSE_ENABLED。

### 6.3 服务端停机

只操作本轮新增的 compose 栈（项目名 django-agent）：
`docker compose --env-file .env.langfuse -f docker-compose.langfuse.yml stop`。
不使用 `down -v`（会删除持久卷）。共享/他人的 Langfuse 实例操作需单独确认。

## 7. 隐私口径

- 默认（LANGFUSE_LOG_CONTENT=false）不上传：原始问题、回答、工具 query/prompt、
  文档标题/正文、图片。
- 明确的认证头、Cookie、密钥键、带凭证 URL、Bearer/Basic 与 JSON 凭证模式会打码。
  默认关闭内容时，邮箱/用户名字段与错误详情也会隐藏；user_id 只传内部标识。
- LOG_CONTENT=true 允许内容字段经脱敏截断后上传；正则脱敏不等于完整的自然语言
  隐私识别。不要把任意新增自由文本塞入“结构化 metadata”绕过内容开关。
- 默认上报：内部标识（session/request/trace id）、模型/供应商、阶段、计数、耗时、
  token 用量、状态、版本。
- 本地 event_log 白名单不是远端上传白名单；远端出口统一经 `_safe_metadata` 脱敏。
- Dataset 内容同时受 LANGFUSE_UPLOAD_EVAL_DATASETS 与 LANGFUSE_LOG_CONTENT 控制。
- 普通用户/API-Key 不返回 Langfuse 跳转地址；链接须同时满足全局开关、活动系统管理员、
  有效 HTTP(S) UI 地址、非空项目 ID 和合法 trace_id。Langfuse 自身登录授权仍独立执行。

## 8. 快速验收清单

1. `langfuse_check` → 退出码 0（或按预期的 1/3）
2. `langfuse_check --smoke` → verified，退出码 0
3. 真实问答回合后 UI 出现 chat.turn trace：根 + retrieval + generation（带用量）
4. 会话轨迹面板（is_active + is_system_admin + 开关开启）出现"查看 Langfuse 追踪"链接
5. `LANGFUSE_ENABLED=false` 重启后：业务正常、无新 trace

## 9. 用量与排障口径

Langfuse usage_details 使用扁平整数分类。缓存输入从 input 中拆出为 input_cached_tokens；
推理输出从 output 中拆出为 output_reasoning_tokens；total 不重复累加。
本地 ModelUsage 保留供应商原始输入/输出合计，两侧按 model_call_id 对账。
例如本地输入 100（缓存 80）、输出 30（推理 10）：
远端 input=20、input_cached_tokens=80、output=20、output_reasoning_tokens=10、total=130。

采样为 0 时内部仍保留空 TraceHandle，以保证整棵子树跳过上报；检查 trace_id/span，
不要把“句柄非 None”当作“已创建远端 trace”。独立 maintenance 通过 originating_trace_id 关联问答。
standalone 只适用于真正没有业务根的模型调用，不用于绕过根采样。

本轮回归与回滚证据见项目 .cache/langfuse-review-20260922/VERIFICATION.txt。
ROLLBACK.sh 只回退本轮复核修复，不等于卸载整个 zcode Langfuse 接入；它不会改动凭证或持久卷。


## 设置入口与思考级别（2026-09-22）

本地 runserver 默认启动 Langfuse；系统管理员登录项目后自动建立本地浏览器会话。
进入「设置 → Langfuse」打开追踪；进入「设置 → 模型管理 → 思考级别」按用途配置。
详细配置、验收与回滚见 langfuse-settings-thinking-implementation.md。

## 2026-09-30：提交前修复后的行为

- API 上报、本地启动与账号桥统一优先读取 `LANGFUSE_BASE_URL`，再读兼容别名
  `LANGFUSE_HOST`，缺省 `http://localhost:3000`。浏览器入口读取
  `LANGFUSE_UI_BASE_URL`，项目 ID 按 `LANGFUSE_UI_PROJECT_ID`、兼容的
  `LANGFUSE_PROJECT_ID`、`.env.langfuse` 初始化项目 ID 的顺序读取。
- 外部 Langfuse 部署设置 `LANGFUSE_AUTOSTART=false`、`LANGFUSE_AUTO_LOGIN=false`。
  已授权账号仍可从设置页或轨迹面板手动打开 UI，在 Langfuse 自己的登录页认证。
  状态接口不转移凭证；真正的自动登录仍要求 API、UI、应用使用相同回环主机名、
  请求来自本机且 Origin 匹配。普通用户/API-Key 不获得平台追踪链接。
- 思考配置 PUT 用原子版本检查：同版本并发保存只有一次成功，其他请求返回
  `409 revision_conflict`。SQLite 锁冲突最多重试三次（50/100/200 毫秒）；
  持续繁忙返回 `503 configuration_busy`，可稍后刷新重试。
- 后台子 Agent 继承当前轮次冻结的思考策略，但建立独立追踪根；新轮次读取新策略。
- 采样仅由业务根执行，SDK 固定 `sample_rate=1.0`，不再将 50% 采样叠加为 25%。
- 评估例子保留原始 ID、行号和失败状态，过滤失败回答不会移动后续评分的归属。
  无法可靠关联的旧 checkpoint 只记录未关联状态，不猜测评分、不追加模型调用。
  未完成评分阶段恢复时按保存的 ID 关联已有评分；身份不确定的异常 checkpoint
  保留已有汇总数据并明确降级，不把它标记为完整验收成功。
- 完成事件不含追踪 ID 时保留已关联的旧 `langfuse_trace_id` 字段。

性能脚本只测观测门面开销。它使用隔离数据库、合成凭证、本地 HTTP sink 与独立
SDK 资源，校验每组的真实观测数量和目标；无效场景或超出性能门槛均返回非零退出码。
不可达组在计时之外验证实际上传请求及连接失败，缺失或错路由的导出器也应使校验失败。
它不使用应用账号，不证明完整问答延迟或真实 Langfuse 入库成功。
