# Langfuse 设置入口、自动启动/登录与模型思考级别实施方案

- 编写日期：2026-09-22
- 项目：/home/liuxuedeng/Django-Agent
- 状态：设计方案，尚未实施本方案代码。
- 延续现有 Langfuse SDK 3.15.0、Server 3.225.8 和 LiteLLM 1.93.0；本次设计不以升级这些组件为前提。
- 目标：交给 zcode 以 goal 模式分阶段执行，交付功能、测试、操作文档和真实验收记录。

## 1. 用户最终看到的效果

### 1.1 Langfuse

1. 按项目正常开发启动方式启动 Django，系统默认尝试启动本项目的 Langfuse Compose 栈。
2. 已运行则复用；首次启动等待有界就绪；Docker 不可用时聊天仍启动，设置页显示具体状态。
3. 项目管理员登录应用后，前端自动发起一次 Langfuse 会话准备，后台读取本机账号并建立浏览器登录态。
4. 设置页新增“可观测性 / Langfuse”，显示服务状态、登录状态和“打开 Langfuse”按钮。
5. 点击按钮进入已配置项目，不再要求手工复制邮箱和密码。现有“查看 Langfuse 追踪”链接也复用这一登录准备流程。
6. 登录失效时，在明确打开操作中重新登录一次；错误密码等问题清晰显示，不反复提交密码。
7. 本机默认账号仅服务于活动的项目系统管理员，不把这个共享管理账号授予普通租户用户。

**时间点说明：**“服务自动启动”发生在项目进程启动时；“浏览器自动登录”发生在用户已登录应用、浏览器发起受鉴权请求后。后台启动进程不持有浏览器，不能把一次服务器登录测试当成浏览器已经登录。最终体验仍是：启动项目 → 登录项目 → 从设置直接进入 Langfuse。

### 1.2 模型思考级别

在“设置 → 模型管理”中增加“思考级别”：

- 跟随模型默认；
- 关闭思考；
- 模型实际支持的等级，例如低 / 高 / 最大；
- 只支持开关的模型显示“开启”，不虚构多个等级；
- 不支持或未识别的模型标明状态，不显示一个看似可用、实际无效的下拉框。

当前 .env 模型也可以编辑思考设置，但 API Key、地址等环境管理字段仍保持原有只读规则。

保存后，后续新轮次的普通问答、流式问答和 Agent 调用使用新设置；正在生成的一轮使用开始时的配置快照。Langfuse 与本地用量记录能看到“请求的等级”和“最终发出的配置”。

## 2. 已核实的项目现状

| 位置 | 实际情况 | 设计影响 |
| --- | --- | --- |
| frontend/src/views/Settings.vue | 已有模型管理/系统信息，无独立 Langfuse 设置区 | 增加 section，复用现有设置页，不另做后台系统 |
| frontend/src/api/client.ts | 使用 localStorage 中的 Bearer token，通过请求头鉴权 | 普通超链接不会自动带 Bearer；不能只写一个后端跳转链接 |
| personal_knowledge_base/authentication.py | 自定义 User/AuthToken，支持租户 API-Key | 登录桥必须识别真实 user，单独检查 is_active/is_system_admin |
| personal_knowledge_base/models.py | ModelConfig.parameters 是 JSON；Tenant 尚无思考配置字段 | 数据库模型可用 parameters；环境模型需要新增持久化位置 |
| model_providers.py::env_models | 环境模型是动态生成项，没有对应 ModelConfig 行；多个角色合并展示 | 要按真实角色保存覆盖值，不能对 env 模型调用普通数据库模型 PUT |
| Settings.vue 模型卡片 | managed_by=env 隐藏编辑按钮 | 为 env 模型单独开放“思考设置”，不是解锁全部凭证配置 |
| accounts/views.py::tenant_kv | 不存在对应 Tenant 字段时仍返回成功样式，但不落库 | 不能直接新增一个任意 KV key 就宣称“已保存” |
| llm_providers.py::_litellm_completion | 已支持部分 enable_thinking，并对 Qwen 做特殊处理；drop_params=True | 新参数可能被 SDK 静默丢掉，要验证最终 HTTP 请求体 |
| BaseLLMProvider.chat_stream / chat_completion_stream | 思考参数传递不完整 | 流式路径必须单独补齐，不能只测试非流式 |
| chat_completion_raw / role_completion | Agent、内部角色有独立入口 | 统一解析策略，并保留既有显式关闭思考的内部调用约束 |
| manage.py | runserver 前存在按端口结束进程的逻辑 | 启动联动不能沿用“按端口杀未知进程”；需核查 autoreload 行为 |
| 当前运行配置 | 对话/内部文字角色使用 deepseek-v4-flash，实际主机 api.deepseek.com | 首批针对当前 DeepSeek 通路落地，不把硬编码的 aliyun 标签当作真实供应商 |
| 本机 Langfuse | 已有项目、初始化账号和凭证；GET /api/auth/providers 返回 credentials | 账号可复用；“初始化账号”与“建立浏览器会话”是两回事 |

不要在本方案中擅自修改已有模型名称、默认模型、API Key、业务数据或 Langfuse 项目。

## 3. 总体设计选择

采用两个相互独立、各自可关闭的模块：

~~~text
应用启动入口 ── 本机服务协调器 ── 现有 Langfuse Compose 栈
                                ↓
设置页 / 应用登录完成 ── Django 鉴权 ── 本机登录桥 ── Langfuse Web 会话

模型设置页 ── 思考策略持久化 ── 能力判定 + 策略快照
                                ↓
              普通问答 / 流式 / Agent / 内部角色
                                ↓
                    每次调用的供应商参数适配
                                ↓
                    LiteLLM → 实际模型接口
                                ↓
                    ModelUsage + Langfuse
~~~

当前本机开发环境使用**账号登录桥**，满足“默认读取账号进行登录”。
未来多人部署/不同域名环境使用 Langfuse 支持的 OAuth/OIDC 等统一登录，不把本机账号桥扩展成通用的共享管理员登录入口。

Langfuse 官方提供账号密码和 SSO 认证，并提供初始化默认账号的配置；但初始化不是免登录。
官方当前页面已标记 v4，因此具体 Web 登录协议和 cookie 名必须以本机固定 v3.225.8 的源码/协议实证为准。
参考：[认证说明](https://langfuse.com/self-hosting/security/authentication-and-sso)、[初始化说明](https://langfuse.com/self-hosting/administration/headless-initialization)。

## 4. Langfuse 自动启动

### 4.1 入口与开关

建议增加轻量服务模块 scripts/local_services.py，独立于 Django AppConfig.ready。

- 兼容现有 python manage.py runserver：仅主启动进程触发一次。
- 推荐增加统一入口 scripts/start_local.py 与 package.json 的 start:local 命令。
- 统一入口和 runserver hook 共用一个幂等函数/锁，不能重复启动。
- 不在 import、HTTP 请求、migrate、test、collectstatic 或每个 gunicorn worker 中启动 Docker。
- 生产部署由进程管理器/Compose 管理依赖，不让应用 worker 管理 Docker。
- 初次实现不修改镜像版本、不重建服务端账号、不删除卷。

新增配置，名称为设计值：

| 配置 | 本机开发默认 | 含义 |
| --- | --- | --- |
| LANGFUSE_AUTOSTART | true | runserver/本机启动器尝试启动现有栈 |
| LANGFUSE_STARTUP_TIMEOUT_SECONDS | 45 | 就绪等待总时限；超时后项目继续运行 |
| LANGFUSE_AUTOLOGIN_ENABLED | true | 活动系统管理员的浏览器自动准备登录态 |
| LANGFUSE_AUTOLOGIN_MODE | local_credentials | 当前本机账号桥；未来可增加 oidc |
| LANGFUSE_LOGIN_EMAIL | 空 | 显式登录账号，可覆盖初始化账号来源 |
| LANGFUSE_LOGIN_PASSWORD | 空 | 显式登录密码，不出现在 API 响应中 |
| LANGFUSE_LOGIN_TIMEOUT_SECONDS | 10 | 一次登录准备的总时限 |

LANGFUSE_ENABLED 继续控制观测上报；与“是否管理本机 Docker 服务”分开。部署到外部 Langfuse 时关闭 AUTOSTART/本机账号桥，观测仍可正常启用。

### 4.2 启动流程

1. 校验本项目根路径、Compose 文件、服务端 env 文件和 Docker 可用性。
2. 读取当前 Compose 项目标签，沿用已有栈身份；不臆造新的 project name 导致重复栈。
3. 获取跨进程锁，检查栈状态。
4. 已运行则直接健康检查；否则执行固定参数的 compose config --quiet 和 up -d。
5. 网络检查仅访问固定配置的本机地址，精确绕过 loopback 代理。
6. 有界等待健康；输出 sanitized 状态到本机状态文件/日志。
7. 主应用继续启动；Docker 失败、端口被别的服务占用、鉴权失败分别显示不同状态。
8. 退出 Django 时默认保留 Langfuse 栈，避免关闭其他正在使用它的任务。

额外约束：
- 管理脚本不自动关闭未知端口进程，不执行 down -v。
- 核对 manage.py 现有 _close_port 在 autoreloader 子进程上的行为；改为只管理本启动器明确记录的子进程，或端口冲突时报告并退出，不能影响不相关进程。
- 开发重载只重启 Django 子进程，不再次执行容器生命周期操作。
- 修改启动 env 后明确提示重启；UI 状态查询不能偷偷修改 .env 或执行 Docker 命令。

## 5. 设置入口与自动登录

### 5.1 页面与接口

设置页新增“可观测性”，内容：

~~~text
Langfuse
服务：运行中 / 启动中 / 不可达 / Docker 未就绪
追踪：已启用 / 已关闭
登录：已就绪 / 未配置 / 已过期 / 登录失败
项目：development（从已验证项目取得显示名称）
内容采集：关闭
[打开 Langfuse] [重新检查]
~~~

拟新增接口：

| 方法与路径 | 行为 |
| --- | --- |
| GET /api/v1/observability/langfuse/status | 返回服务、配置存在性、登录模式等非敏感状态；健康结果短缓存 |
| POST /api/v1/observability/langfuse/session | 验证项目用户，复用/创建 Langfuse 浏览器会话；响应设置 HttpOnly cookie |
| POST /api/v1/observability/langfuse/session/clear | 清除本机桥建立的当前浏览器 cookie；不重置账号，不注销别的浏览器 |

status 不返回邮箱密码、API Key、原始 upstream body 或 cookie 值。是否返回具体项目入口同样按系统管理员权限过滤。

### 5.2 账号来源

读取优先级：
1. 显式 LANGFUSE_LOGIN_EMAIL / LANGFUSE_LOGIN_PASSWORD；
2. 仅在本机模式，读取项目根 .env.langfuse 中的 LANGFUSE_INIT_USER_EMAIL / LANGFUSE_INIT_USER_PASSWORD。

只读取这两个指定字段，不能把整个服务端 env 文件加载到 Django 的全局环境。
初始化变量后来可能已与实际密码不同：登录失败后提示维护登录凭证，不自动注册、改密或重复初始化账号。
观测 Public/Secret API Key 不能替代 Web 登录密码。

### 5.3 本机登录桥具体过程

1. 浏览器使用现有 API client 发送带 Bearer 的 POST；校验来源 Origin、真实活动系统管理员和固定服务目标。
2. 读取当前浏览器传来的、属于 Langfuse 的允许名单 session cookie，向固定 Langfuse 地址检查会话。
3. 会话有效且属于预期账号：复用，不再提交密码；有效但属于其他账号：返回 account_mismatch，由用户明确点击“切换到默认账号”，不要静默覆盖。
4. 没有有效会话时，创建独立后端 HTTP client；按固定版本协议获取 CSRF，提交 credentials 登录。
5. 用同一个 cookie jar 再读取 /api/auth/session，检查真实登录身份及项目可访问性。不能把 200/302 或返回 callback URL 当作登录成功。
6. Django 响应只转交已核验的 session cookie（包括固定协议允许的分片），设置正确的 HttpOnly、Path、SameSite、Secure 和有效期。
7. JSON 仅返回状态和后端构造的允许列表内 open_url。密码、session token、CSRF token 不放 JSON/URL/localStorage。
8. 浏览器随后打开 Langfuse 项目；通过真实浏览器检查“离开登录页且能访问指定项目”，才算成功。

**这是本项目为固定本机版本设计的适配层，不是声称 Langfuse 存在稳定的公开 password-login API。**
P0 必须验证实际 credential 字段、CSRF、cookie 分片、会话验证和登出协议，并把它们固化为契约测试。

### 5.4 自动触发与浏览器约束

- App 登录成功且确认管理员后，自动准备一次会话；页面刷新可检查并复用。
- settings 页面进入时补做一次准备；“打开”按钮遇到会话过期可重试一次。
- 不在轮询 status 时反复尝试密码登录；认证失败设置短暂冷却。
- 如果新标签页打开，点击事件内先创建空白页，再等待 session 接口完成并导航，避免浏览器拦截异步弹窗；也可使用当前页导航。
- 同一个应用登录周期内，用户主动退出 Langfuse 后不持续强制重新登录；再次明确点击打开时才重新准备。
- 应用退出登录清除本机桥的浏览器 session cookie；不全局注销共享账号。
- 当前 8000 和 3000 使用相同主机 127.0.0.1。cookie 不按端口隔离，这正是本机方案能转交 cookie 的条件，也意味着它只用于该受控本机部署。
- localhost 与 127.0.0.1 不是同一个 cookie host；检测到主机不一致时显示规范入口，不假报登录成功。
- 不跨域设置别的域名 cookie，不用修改 CORS 为任意来源来迁就此流程。
- 不把网页登录密码渲染到前端自动填写，不在浏览器脚本中硬编码密码。

### 5.5 部署边界

当前默认：单机开发、固定 loopback 目标、仅系统管理员使用默认账号。
远程访问、多用户独立 Langfuse 权限、不同域名或正式 HTTPS 部署：改走官方支持的统一登录并映射个人身份。
只更换配置开关不够把本机桥变成多人 SSO；这属于后续独立验收项。

## 6. 模型思考策略的数据设计

### 6.1 统一内部结构

~~~json
{
  "mode": "on",
  "effort": "high"
}
~~~

- mode = default：不新增思考覆盖参数，保留模型/供应商默认行为；
- mode = off：明确关闭；只有支持关闭的模型才允许保存；
- mode = on：明确开启；effort 可为空，表示只开思考、不覆盖强度；
- effort 是供应商能力允许的枚举，不是自由字符串；
- mode=default/off 时 effort 必须为空，后端拒绝矛盾组合；
- “默认”不等于关闭，也不偷偷映射为 medium。

UI 可显示为一个“思考级别”下拉框，但后端保留开关与强度两个语义。

### 6.2 持久化：数据库模型与环境模型都能编辑

**数据库模型**
- 存入 ModelConfig.parameters.thinking；
- 原有 API Key 等参数合并保留；
- 所有写入路径（普通模型更新、专用思考接口）共用验证器；
- credentials 接口不能成为写入 thinking 的绕行入口。

**环境模型**
- 为 Tenant 新增 model_thinking_config = JSONField(default=dict)，提供增量迁移；
- 通过专用服务和接口读写，不修改 .env 中的模型名、地址、密钥；
- 按稳定角色 chat/summary/title/question/extract/vlm 存储，而不是依赖展示项合并后的模型 ID；
- 保存时记录 model/endpoint 的非敏感指纹。以后 .env 换了模型或端点，旧策略标为 stale，重新验证后才应用；
- 当前页面将同一模型的多种角色合并展示，弹窗必须显示“本次应用于哪些角色”；
- 普通“对话”级别默认只改 chat；不要顺带把标题/摘要/视觉全改为最高强度。

建议结构：

~~~json
{
  "schema_version": 1,
  "revision": 3,
  "roles": {
    "chat": {
      "mode": "on",
      "effort": "high",
      "binding_fingerprint": "derived-nonsecret-model-endpoint-fingerprint"
    }
  }
}
~~~

- 更新使用版本校验/CAS及项目既有 SQLite 重试机制，防止同时编辑不同角色互相覆盖。
- 增加真实“保存 → 新请求读回 → 重启后读回”测试。
- 为已新增字段处理通用 tenant_kv 的写入绕行：调用同一授权/验证服务，或明确禁止通过通用 KV 写入。活动 accounts 路由及遗留同名入口都要审查。
- 写权限默认给活动用户中的租户 owner / 系统管理员；普通查看者、仅 API-Key 身份不修改此配置。
- 切换租户后的覆盖值必须隔离。

### 6.3 接口

拟新增，最终路径与现有路由约定对齐：

~~~text
GET /api/v1/models/<model_id>/thinking
PUT /api/v1/models/<model_id>/thinking
~~~

GET 返回：
- normalized policy；
- capability profile、支持的选项、是否允许 off；
- policy_source = model / tenant_env_role / provider_default；
- role 列表、版本和 stale 状态；
- 能力证据状态：declared / transport_verified / upstream_verified。

PUT：
- 明确区分 env 与 DB model；
- env 模型要求传入合法 roles，且属于该展示项；
- 校验租户、真实用户写权限、版本、类型、字段白名单和能力约束；
- 不接受客户端自报“supports_thinking=true”作为授权依据；
- 参数错误返回 400，权限错误 403，版本冲突 409；不是返回 200 然后无声忽略。

## 7. 供应商能力与参数映射

### 7.1 不采用统一的“所有模型 low/medium/high”

新增 reasoning_config.py / reasoning_capabilities.py：
- 基于真实端点、模型标识、接口类型和显式配置的兼容 profile；
- API-compatible 只说明接口格式，不证明支持相同思考参数；
- 不能只根据 model.source 判断：当前 env 列表硬编码 aliyun-bailian，但实际请求发往 DeepSeek；
- 保留旧 env 模型 ID，避免破坏历史引用；新增 resolved_provider/profile 表达实际连接；
- 未识别模型只提供默认行为，直到为明确端点配置经过验证的 profile；
- 能力清单由后端提供，前端不维护第二套猜测逻辑。

### 7.2 当前 DeepSeek 优先支持

DeepSeek 当前官方文档将思考开关与强度分开：Chat Completions 使用 thinking.type，强度使用 reasoning_effort；列出的原生强度有 low/high/max。
文档中的模型名和别名会变化，不能因此擅自把当前 deepseek-v4-flash 改成别的模型。
参考：[DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。

对于验证支持的当前配置，预期最终 HTTP body：

~~~json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "synthetic test"}],
  "thinking": {"type": "enabled"},
  "reasoning_effort": "high"
}
~~~

对应关闭：

~~~json
{
  "thinking": {"type": "disabled"}
}
~~~

这里是**最终 JSON body**；Python SDK/LiteLLM 调用层可能需要将 thinking 放在 extra_body，不能把 SDK 包装层和最终请求体混为一谈。
默认选项不主动新增这两项；是否支持 low 必须结合当前精确模型 ID/端点做兼容核对，未验证时显示明确状态，而不是凭名称放行。
思考模式下不生效的 temperature 等参数按已核实的供应商契约处理，并记录省略原因，不显示“已生效”。
工具调用涉及供应商返回的 reasoning_content 时，按该端点协议保留必要的原始上下文；不伪造推理文本，也不因此开启 Langfuse 正文上传。

首批验收聚焦当前 DeepSeek 通路。Qwen、其他兼容网关后续按各自 profile 扩充；没有证据时不把一种供应商参数复制到全部模型。

### 7.3 LiteLLM 的关键处理

官方明确 drop_params=True 会删除不支持的参数。
参考：[LiteLLM Drop Unsupported Params](https://docs.litellm.ai/docs/completion/drop_params)。

因此：
- 先解析并验证支持的参数，再调用 LiteLLM；
- 检查安装版本实际支持面，不直接按最新文档升级依赖；
- 可针对经过确认的参数采用该版本支持的传递机制，但不能对任意未知字段“全放行”；
- 测试必须在 LiteLLM 下游的本地 HTTP 捕获服务检查最终 JSON；只 mock litellm.completion 的 kwargs 不足以验收；
- 不为本功能打开新的 Langfuse 自动 callback，以免和现有手工 generation 重复。

## 8. 运行时贯穿设计

### 8.1 优先级

从高到低：

1. 内部调用明确约束（如既有 enable_thinking=False / 超时与输出预算要求）；
2. 显式单次调用选项（首期不新增聊天输入框开关，但保留接口扩展位）；
3. 租户角色覆盖值（环境模型）或模型保存值（数据库模型）；
4. 模型供应商默认。

保留 enable_thinking 兼容参数。None 表示未覆盖，False 不能被 truthy 判断误当成“未设置”。
冲突必须明确转换或报错，并记录来源；不要让默认参数无意覆盖页面设置。

### 8.2 覆盖的调用入口

- chat_completion；
- chat_completion_stream；
- chat_completion_raw（Agent）；
- role_completion / _env_text_completion；
- openai_compatible_chat_raw / openai_compatible_chat_stream；
- BaseLLMProvider.chat / chat_stream；
- _litellm_completion；
- 真正使用 chat 协议的 VLM 分支；
- fallback/retry 的每一个实际候选模型。

新增不可变 ThinkingOptions / ResolvedThinkingConfig，作为**每次调用选项**传递。
不要修改工厂缓存中共享 provider 实例的可变 thinking 字段，否则不同租户/并发调用会串值。

业务轮次开始时取得配置快照；线程池/后台任务显式传递。真正的后台维护任务在自己的任务边界取得快照。
如果把任意思考字段放入 ProviderConfig，则必须同步修改 signature；首选 per-call 选项，避免依赖共享实例更新。

### 8.3 失败与备用模型

- 参数验证错误不触发付费供应商重试，也不通过删掉参数后重发来掩盖问题。
- 主模型失败后，对备用模型重新做能力映射，不复制主模型的原始 kwargs。
- 本轮明确要求 high 而备用模型不支持时，默认跳过该候选并记录原因；不要无声改成 low/关闭。
- 只有已定义、用户可见的 allow-degrade 策略才允许能力降级。
- 流式已向用户输出内容后，保持项目现有禁止重复生成的语义。
- 思考预算与最大输出预算不是同一个字段，不把 max_tokens 偷换成 thinking_budget。

## 9. 本地轨迹与 Langfuse 联动

在 ModelUsage.metadata 和 generation metadata 增加经过枚举校验的低敏字段：

~~~json
{
  "think_level_requested": "high",
  "think_level_applied": "high",
  "think_policy_source": "tenant_env_role",
  "think_profile": "deepseek_chat",
  "think_policy_revision": 3,
  "think_transport_verified": true
}
~~~

- applied 表示本次最终发出的请求配置，不声称能够测量模型内部实际用了多大“思考强度”。
- 供应商只接受请求但无法证明内部效果时，用 sent/accepted 等精确证据状态，不捏造 verified_effect。
- reasoning_tokens 继续使用供应商实际 usage；缺失则保持未知/既有估算口径，不根据选择等级编造 token 数。
- 当前隐私过滤会隐藏带 reasoning 语义的自由文本字段，所以专用 think_* 枚举字段须有明确测试；不要为了展示级别而放开所有 reasoning 文本。
- LOG_CONTENT=false 时，级别/来源/计数仍可见，原始思考内容、问题、答案仍受原隐私策略约束。
- 通过 model_call_id 对齐每次调用，保持“一次实际调用只有一个 generation”。

## 10. 文件改动范围建议

| 文件/模块 | 计划改动 |
| --- | --- |
| manage.py | 受控 runserver 前置启动；autoreload 去重；修正危险端口清理行为 |
| scripts/local_services.py（新增） | 本机 Compose 协调、锁、超时、状态文件 |
| scripts/start_local.py（新增）、package.json | 明确的项目联合启动入口 |
| config/settings.py、.env.example | 新配置、默认值、登录凭证读取边界 |
| personal_knowledge_base/langfuse_access.py（新增） | 固定版本登录适配、会话验证、cookie 允许列表 |
| observability 对应新 views/urls | status/session/clear 接口，沿用项目路由结构 |
| frontend/src/App.vue 或现有鉴权完成入口 | 管理员浏览器会话一次性准备，登出时清理 |
| Settings.vue、新 LangfuseSettings/ModelThinkingSettings 组件 | 设置入口、状态、思考级别编辑 |
| frontend/src/api/index.ts | 类型化接口；复用现有 Bearer client |
| TrajectoryPanel.vue | 追踪跳转前复用会话准备 |
| models.py + 新迁移 | Tenant.model_thinking_config |
| models_config/views.py / urls.py、serializers.py | 能力/策略接口、参数验证与 env 模型支持 |
| accounts/views.py 与遗留 tenant_kv | 防止通用 KV 绕行校验 |
| reasoning_config.py / reasoning_capabilities.py（新增） | 配置解析、能力注册和最终参数构造 |
| model_providers.py / llm_providers.py | 全调用路径透传，缓存/并发/备用模型一致性 |
| model_usage.py / observability.py | 低敏 think_* 元数据，保持既有用量和隐私口径 |
| docs/langfuse-operations.md、相关模型说明 | 启动、登录、修改级别、排障及回滚步骤 |

实施时按真实调用图收敛文件；不要因表中出现文件名就无条件重写整个文件。

## 11. 分阶段执行与退出条件

### P0：建立基线与契约
- 保存当前未提交工作，不用 Git HEAD 冒充本轮基线。
- 复跑已有相关测试；记录当前新增/既有失败。
- 检查固定 Langfuse 版本的 credentials/CSRF/cookie 协议。
- 检查精确模型标识和当前 LiteLLM 传递行为，建立本地 HTTP 请求捕获测试。
- 核实启动命令、Compose 标签、浏览器 origin 与真实角色。
- 退出条件：两条核心链路有明确契约和自动化测试入口。

### P1：服务启动
- 实现幂等启动器、配置、锁、超时与状态。
- 验证 runserver、--noreload、autoreload、Docker 缺失、服务已运行/未运行。
- 退出条件：正常开发启动能自动拉起 Langfuse，重复启动不建重复栈，失败不拖死聊天。

### P2：设置入口与浏览器登录
- 新增设置卡片、受鉴权登录桥、自动准备与按钮跳转。
- 实际浏览器验证新会话/已登录/过期/错误密码/权限拒绝。
- 退出条件：管理员从应用进入指定 Langfuse 项目无需手输密码；普通用户不获得共享管理会话。

### P3：思考设置持久化与 UI
- 新增迁移、env 角色覆盖、DB model 参数验证及能力接口。
- 验证真实保存读回/进程重启/租户隔离/并发编辑。
- 退出条件：当前 env DeepSeek 模型可在设置页修改，且修改确实持久化。

### P4：全链路传参及观测
- 普通/流式/Agent/内部角色/备用模型统一贯通。
- 添加最终 HTTP 请求体测试及 think_* 元数据。
- 退出条件：各入口发出的参数符合该模型 profile；默认行为无变化、并发无串扰。

### P5：综合验收与交付
- 复跑相关 Django、前端类型检查/构建/组件/E2E 测试。
- 合成数据验证 Langfuse 服务与自动登录。
- 如需真实模型调用，先明确次数/预算，再做少量端到端测试；未运行的上游验证标为 NOT_RUN，不伪报通过。
- 文档记录精确命令、输出、版本、改动文件、回滚结果。
- 修改代码后执行 graphify update .，保持知识图谱同步。

## 12. 必需验收矩阵

| 编号 | 场景 | 通过标准 |
| --- | --- | --- |
| L01 | 原栈停止后启动项目 | 仅本项目栈启动，健康后 status 正确 |
| L02 | 原栈已运行/重复启动/autoreload | 无重复栈、无重复初始化、无无关进程被结束 |
| L03 | Docker 不可用/启动超时 | 主应用仍可用，设置页状态明确 |
| L04 | test/migrate/collectstatic | 不启动 Docker、不尝试网页登录 |
| L05 | 全新浏览器管理员登录项目 | 自动准备后点击按钮直达指定项目，无手输密码 |
| L06 | 普通用户/API-Key/失效 token | session 接口拒绝，无账号/cookie 泄露 |
| L07 | 密码错误、账号不匹配、会话过期 | 明确状态、次数有界、不创建新账号 |
| L08 | cookie 分片/退出登录/主机不一致 | 无残留误登录、无虚假成功 |
| L09 | 敏感信息检查 | 页面、JSON、URL、日志无明文凭证或 session token |
| T01 | 当前 ENV 模型保存与重启 | 配置读回一致、仅所选角色变化 |
| T02 | DB 模型更新 | API Key 不被清空，非法参数被拒绝 |
| T03 | 默认/关闭/各支持等级 | 最终 HTTP body 正确；default 不新增覆盖字段 |
| T04 | 非流式/流式/Agent/内部角色 | 设置实际到达调用边界，不只是 UI 展示 |
| T05 | LiteLLM 真实适配层 | 传输捕获能看到参数，没有被 drop_params 丢弃 |
| T06 | 并行调用与双租户 | 不共享可变思考设置，不串租户 |
| T07 | 备用模型与非法等级 | 按能力重新映射，拒绝无声降级/删参重试 |
| T08 | 模型/端点更换 | 旧 env 覆盖标记 stale，不错误套用 |
| T09 | 内部 enable_thinking=False | 保留显式约束，并记录覆盖来源 |
| T10 | Langfuse 内容关闭 | think_* 枚举可见，原始推理/正文不因此上传 |
| T11 | 工具调用多轮 | 满足当前供应商上下文协议，调用 ID/用量不重复 |
| R01 | 关闭新功能与隔离回滚 | 原有聊天/模型默认行为正常，卷与凭证保留 |

至少三层测试：业务单元测试 → 真实 LiteLLM + 本地 HTTP sink → 真实浏览器/服务集成。
“接口 200”“页面能打开登录页”“kwargs 中有 reasoning_effort”都不是最终验收标准。

## 13. 回滚设计

- 启动/登录：关闭 LANGFUSE_AUTOSTART 与 LANGFUSE_AUTOLOGIN_ENABLED，保留普通手动打开入口；不影响既有 Langfuse 上报。
- 思考策略：设回 mode=default 或清除该角色覆盖值，下个新轮次恢复原有默认。
- 服务端：不删除 Compose 卷、不重新生成已有账号/加密密钥。
- 数据库：新增 JSON 字段是兼容性迁移。优先回退读取逻辑而保留字段；如需逆迁移，先导出策略且在隔离数据库演练。
- 代码：按本轮提交或审查前快照恢复，不覆盖前期 Langfuse 修复、不覆盖用户其他未提交修改。
- 回滚后分别测试原有问答、默认思考参数与手动 Langfuse 登录；记录已恢复行为。

## 14. 可直接交给 zcode 的 goal 执行提示词

~~~text
请使用 goal 模式执行 docs/langfuse-settings-thinking-level-plan.md，完成以下目标：

1. 设置页可直接进入本机 Langfuse；项目开发启动时默认启动现有 Langfuse 栈；
   项目管理员登录后默认读取已有账号建立真实浏览器登录态，而不是仅打开登录页面。
2. 设置页支持模型思考级别；必须覆盖当前 .env 提供的 DeepSeek 模型，
   保存真实持久化，普通/流式/Agent/内部角色都能正确传参。

先阅读 AGENTS.md 和项目 graphify 图谱，检查实际代码/依赖版本/模型标识。
保护既有未提交修改、.env、服务端密钥与卷；不要擅自更换模型或升级依赖。
按 P0→P5 执行，每阶段跑测试并记录证据，不以 Fake 全通过替代浏览器和传输边界验证。
登录仅对活动系统管理员生效；密码和 cookie 不进入前端 JSON、URL或日志。
ENV 模型没有 ModelConfig 行，不能用虚假的 KV 保存成功替代持久化。
不同模型按实际能力展示等级，禁止静默丢参数后宣称已生效。
保留现有 enable_thinking=False 约束、fallback/流式终结和 Langfuse 隐私行为。
真实模型测试先说明调用次数和预算；未运行的检查写 NOT_RUN。
交付改动代码、测试、迁移、更新后的运维说明、实施报告和已演练的回滚方式。
只有必需验收矩阵完成后才标记整个目标完成；有外部阻塞时精确记录，不伪报 PASS。
~~~
