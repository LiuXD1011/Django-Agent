# Langfuse 设置与模型思考级别：实施记录

日期：2026-09-22

## 已交付

### Langfuse

- 设置新增 **Langfuse** 页面，查看服务与账号配置状态、重试登录、打开当前项目。
- 本地 runserver 外层进程自动启动/复用现有 Docker Compose 栈，默认开启、45 秒有界等待，失败不阻断 Django。测试、迁移、导入与自动重载子进程不启动 Docker。
- 使用既有 .env.langfuse 初始化账号，不重置用户，不创建重复项目，不删除数据卷。
- 项目系统管理员登录后自动建立 Langfuse 浏览器会话；追踪链接也会先验证会话。
- 仅同主机名回环访问可用，例如项目 127.0.0.1:8000 与 Langfuse 127.0.0.1:3000。
- 密码仅在后端读取。NextAuth CSRF → credentials → session 验证成功且账号属于目标项目，才写入 HttpOnly session-token Cookie（支持分片）。
- 浏览器已有其他账号时显示冲突，不静默替换。失败有 60 秒冷却，状态有短期缓存，响应禁止缓存。
- 退出项目清理本浏览器 Langfuse 会话；项目 token 过期后，同源本地清理仍可执行。
- 这是**本地单机便利登录**，不是远程部署的 SSO。同主机名不同端口共享 Cookie 主机；共享机器/远程部署应关闭桥接并配置正式身份登录。

### 思考级别

- 设置 → 模型管理 → **思考级别**。ENV 锁定模型也有独立入口，无需解锁密钥和端点。
- ENV 模型按 chat / summary / title / question / extract / vlm 分别保存，默认编辑对话用途。
- ENV 策略存于 Tenant.model_thinking_config，不创建假的 ModelConfig 行；数据库模型存于 ModelConfig.parameters.thinking。
- 独立接口校验管理员身份、模型能力、版本冲突；通用配置接口禁止绕过此入口写入策略。
- 规范结构为 mode 与 effort：mode 为 default/off/on；effort 为 null/low/high/max。非 on 模式的 effort 必须为空。
- 根据**端点 + 精确模型名**识别能力，不依赖已有供应商标签。首个适配覆盖官方 DeepSeek 端点的 deepseek-v4-flash、deepseek-v4-pro、deepseek-flash。
- 其他模型当前仅提供供应商默认，不猜测通用参数。不替换项目现有模型名。
- 旧版 V4 接口可能把 low 映射为 high，页面已提示；报文保留用户选择。
- 默认策略不增加新参数；既有内部 enable_thinking=False 优先于用户配置。
- 策略通过不可变对象按调用传递，不写共享 Provider。请求/Agent 轮次快照防止中途变更，并传递至后台线程。
- 普通对话、流式、Agent raw、辅助任务、视觉 chat 均接入；备用模型重新校验能力，不静默丢弃强度。
- DeepSeek 工具调用后的 assistant 消息保留供应商返回的 reasoning_content，供后续请求使用；不额外增加 Langfuse 思考内容上传。
- 本地用量、轨迹与 Langfuse 使用 think_ 元数据记录策略、来源、版本、profile。请求前/失败时 applied 为 unconfirmed；调用成功后标记所传配置，**不代表测量了模型内部思考强度**。

## 使用

1. 在原 Django Python 环境运行 python manage.py runserver，或 python scripts/start_local.py。
2. Langfuse 就绪后，项目管理员进入 **设置 → Langfuse → 打开 Langfuse**。
3. 进入 **设置 → 模型管理 → 思考级别**，选择用途、模式与强度，保存。
4. 下一轮调用生效；正在执行的轮次继续使用原快照。
5. 要恢复原行为，选择“供应商默认”。

当前模型策略保持默认，没有替用户选择更高成本的级别。

## 配置

| 配置 | 默认 | 作用 |
|---|---|---|
| LANGFUSE_AUTOSTART | true | 开发入口启动本项目 Compose 栈 |
| LANGFUSE_STARTUP_TIMEOUT_SECONDS | 45 | 等待时间，范围 1–120 秒 |
| LANGFUSE_AUTO_LOGIN | true | 本地管理员浏览器登录 |
| LANGFUSE_LOGIN_EMAIL | .env.langfuse 的 INIT_USER_EMAIL | 可显式覆盖账号 |
| LANGFUSE_LOGIN_PASSWORD | .env.langfuse 的 INIT_USER_PASSWORD | 可显式覆盖密码，勿提交版本库 |
| LANGFUSE_BASE_URL / LANGFUSE_HOST | 现有配置 | 固定服务地址，不接收客户端代理目标 |

自动登录关闭后，“打开”按钮进入标准 Langfuse 登录流程。初始化账号变量只在空数据库初始化时生效；若在 Langfuse 修改密码，应更新 LOGIN_PASSWORD，勿清库重建。

## 接口

- GET /api/v1/observability/langfuse/status
- POST /api/v1/observability/langfuse/session
- POST /api/v1/observability/langfuse/session/clear
- GET /api/v1/models/<id>/thinking
- PUT /api/v1/models/<id>/thinking；输入 role / revision / policy。

状态与建会话要求真实有效的系统管理员，API-Key 身份不等价。修改桥接接口校验 Origin 与本地地址。思考写入要求租户 owner/admin 或系统管理员。

## 验证

- 原始基线：110 项相关测试通过。
- 新增测试：值校验、角色/租户隔离、版本冲突、快照、ENV/DB 保存、内部关闭、未知备用模型、登录权限、Origin、Cookie、账号冲突及退出清理。
- 真实 LiteLLM → 本地 HTTP 捕获：非流式/流式的默认、关闭、low、high、max，共 10 次报文；字段在最终 JSON 顶层，未被 drop_params 丢弃。
- 本地真实 Langfuse 验证完整登录合约，未输出账号密码、Cookie、Token。
- Chromium + 隔离项目数据库：自动登录、HttpOnly、项目打开、思考设置保存/重新加载、摘要角色独立、会话清理、无页面异常。
- 前端生产构建通过；数据库迁移仅新增 0024 的 Tenant 字段，迁移前做 SQLite 在线备份，无其他待迁移项，模型检查无差异。
- DeepSeek 真实付费推理：**NOT_RUN**。本次验证请求适配，不声称实际上游已执行指定强度。
- 既有 SDK 故障测试日志可能包含合成 401；以断言与退出码为准，与真实浏览器登录测试分开记录。

最终命令、输出、退出码、哈希与回滚演练见项目 .cache/langfuse-settings-implementation/VERIFICATION.txt。

## 回滚

提供 MODIFIED_FILE.zip、DIFF_FILE.patch、VERIFICATION.txt 与可执行 ROLLBACK.sh。
回滚脚本要求显式目标目录，写入前校验全部文件哈希，避免覆盖后续修改，并在独立副本测试。

源码回滚保留 .env、真实数据库、容器与数据卷。新增数据库字段向后兼容，旧代码可以忽略，不自动删除已保存策略。真实回滚后需重新构建前端并重启应用；不要直接用旧数据库备份覆盖正在使用的数据库。

## 后续执行提示词

> 为一个明确供应商的精确端点和模型扩展思考 profile。先查官方文档，默认不发送参数，保持内部关闭优先级。补充最终 HTTP 报文、流式/非流式、工具调用、租户隔离、备用适配与快照测试。不要用 source 标签推断能力，不修改真实账号，不发起付费调用。更新验收记录并运行 graphify update .。

## 官方参考

- [DeepSeek 思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)


## 2026-09-22：本地 admin 打开失败修复

实际项目 admin 并非系统管理员。新增 LANGFUSE_LOCAL_LOGIN_USER_ID，显式绑定一个本地账号，仅授予回环 Langfuse 登录能力，不修改 User.is_system_admin 或任何全局权限；未绑定的普通账号仍拒绝。
前端按统一 API 客户端返回的 message/error.code 显示真实错误。先验证会话，再打开项目，失败时不再闪出并关闭空白窗口。现有会话可复用，浏览器阻止新窗口时在当前页打开。

## 2026-09-30：提交前审查修复

轨迹链接改用项目 Bearer 用户身份鉴权。启动与账号桥统一 API 地址优先级，
浏览器入口使用 UI 地址和 UI 项目 ID。关闭本地自动登录后，已授权账号可以手动
打开远程 UI；凭证转移仍受原有本机、主机名及 Origin 限制。

思考配置改为原子版本检查和同事务保存；并发旧版本返回 409，持续 SQLite 繁忙
返回 503。后台子 Agent 显式继承父轮次思考快照，独立维护任务仍在自身边界取值。
本轮不新增 schema 或依赖升级。隔离回归与构建结果见实施报告新增的日期章节；
此前真实浏览器/服务端验收记录属于历史证据，不作为本轮重新验收的结果。
