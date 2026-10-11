# 个人知识库跨设备：第一批实施记录

日期：2026-10-02。主线：[架构方案](../个人知识库跨设备架构方案.md)。

本次不是整份方案的完成声明。交付个人空间与同源网页/PWA设备会话、移动交互与公开静态壳，保留旧成员、Bearer/API Key、本地启动及 Neo4j 功能。未修改实际业务数据库、media 或解密密钥，未提交、签名或发布安装包。

## 1. 实际进度

| 阶段 | 本批事实 | 仍需实施或实测 |
|---|---|---|
| P0 | 原工作区388个非忽略文件的副本、SHA256和git状态；相关后端/前端基线 | 真实Android/iPhone、容量与运营政策确认；旧用户/文件数据归属盘点 |
| P1 | 新账号原子建立个人owner空间；同账号两Cookie设备读写同服务数据；统一API地址/服务身份 | 全资源revision、保存状态、前台条件刷新；个人界面和引用交互完整验收 |
| P2 网页 | HttpOnly Cookie、CSRF、摘要与单次刷新家族、设备撤销/改密、跨标签页协调、流授权守卫 | 原生凭据适配；实际浏览器兼容矩阵；旧Bearer长流授权周期仍为原行为 |
| M1/M2 基础 | 四项手机导航、选库收集/文件与拍照入口、上传确认、输入法/换行、小屏布局、manifest/SW公开静态缓存 | Android/iOS真机安装/权限/键盘/锁屏/换网；持久页面草稿、完整离线不是本批交付 |
| P3—P7、P6A/P6B | 未实现；capabilities明确返回未支持 | 增量同步/CAS、耐久生成/文档修订、PG检索/FileStore、五平台原生包、备份恢复/导出删除 |

只刷新另一台设备已能读到服务器写入；没有SyncChange协议，不承诺已打开页面5秒自动更新。当前DeviceStore是按服务/账号/空间隔离的适配基础，尚未把全部编辑输入接入持久草稿。页面断网提示说明未提交输入仅在当前页面，不宣称关闭/杀进程后仍保留。

## 2. 后端改造

- `Tenant.space_type` 默认 `legacy`，新增可空 `personal_owner`。数据库约束保证个人空间必须有owner，一个用户至多一个活动个人空间。旧多人空间不会被自动认领。
- 新注册在同一事务创建User、Tenant和owner成员；个人空间授权以明确归属和活动成员为准，其他人的成员记录、系统管理员身份不自动获得正文访问。旧空间授权兼容保留。
- 个人空间普通DTO不再带空间API Key；配置状态可读，owner显式轮换接口仍返回新值。原有模型加密凭据管理未倒退。
- `DeviceSession` / `DeviceRefreshToken` 只存新Cookie登录凭据SHA256摘要及刷新历史，不存可复用明文。Access 10分钟、refresh不活动30天、绝对90天；生产Cookie为HttpOnly/Secure/SameSite=Lax。
- Refresh原子消费旧值并轮换；旧值重放撤销该设备家族。一个设备被撤销不影响其他设备；改密、退出所有设备也撤销原Bearer令牌。
- SQLite使用有界跨进程写门控，PostgreSQL使用用户/设备行锁；超时503 `auth_busy`。PG路径仅核对了安装的Django API，本批未跑真实PG数据库测试。
- Cookie修改接口保留CSRF，即使旧视图有csrf_exempt、同时带Authorization或X-API-Key也不绕过；首次Cookie登录/注册也需CSRF。旧纯Bearer/API Key调用方式仍可用。
- Cookie流按设备家族而不是旧access摘要重新授权；正常轮换不误断流。撤销、用户/空间停用、成员取消会结束迭代；阻塞期间不输出新数据，下一次输出前按最长30秒检查间隔重查。该守卫不等于已完成async SSE或耐久generation协议。
- 偏好GET不写数据库；修改在短事务锁定用户并合并提交字段，保留其他设备改动的不同字段。本批尚无preferences revision冲突协议。

新增兼容迁移：`personal_knowledge_base/0026_personal_spaces`、`accounts/0001_initial`。本次只在Django临时测试库/独立测试数据目录应用，不在原业务库执行migrate。

## 3. 当前实际API契约

所有路径位于`/api/v1/`；成功保持原有`data`封装。

| 路径 | 实际用途 |
|---|---|
| GET `capabilities` | 持久service_id、协议范围1、Cookie/legacy Bearer；incremental_sync/durable_generations/native_clients为false |
| GET `auth/csrf` | 初始化同源CSRF；响应no-store |
| POST `auth/register` / `auth/login` | 前端明确发送auth_mode=cookie；不在JSON返回access/refresh |
| POST `auth/refresh` | CSRF与refresh Cookie，单次轮换；不提供旧值宽松复用 |
| GET `auth/me` | 重新核实身份、空间与设备，而非相信本机缓存 |
| GET `auth/devices` | 本账号登录实例、最近刷新时间、不活动/绝对期限、当前设备与撤销状态；没有token |
| DELETE `auth/devices/{id}` | 仅撤销本人的目标会话 |
| POST `auth/logout` / `auth/logout-all` | 当前/全部设备退出，清Cookie |
| POST `auth/change-password` | 验证旧密码后修改并全撤销 |

service_id位于`APP_DATA_DIR/.settings/service-id`（未配置数据根则按既有根策略）；必须和同一服务一起保留，损坏时503，不静默重建。`recovery_epoch=1`是起步协议值，还没有恢复后递增的管理流程。上传max_upload_bytes为null，因为当前内存阈值不是已执行的文件字节配额，不能伪造限制。

## 4. 前端与手机

- EndpointResolver统一同源`/api/v1/`；能力协商后绑定service_id与协议。跨源、带凭据重定向、非业务路径拒绝，不提供中央PWA代转任意服务器Cookie。
- Axios、fetch/SSE、Langfuse请求走AuthTransport。新网页登录不将token/refresh写入localStorage；只保存低敏身份与Cookie模式提示，启动后实际读取me。旧Bearer存量协议保留。
- 页内刷新singleflight；登录、注册、初始化、刷新、退出、改密、设备撤销共用一个同源Web Lock，避免Set-Cookie响应乱序。锁内认证修改401直接清理状态并要求登录，不重入refresh获取同一锁。退出/换账号取消在途刷新，世代检查禁止晚到响应恢复已退出状态；账号变更使其他标签页重新核实服务身份与me。缺Web Locks时保留同页操作队列，但不保证跨标签互斥，严格刷新轮换可能要求其他标签重新登录。
- 新增注册入口和设备管理：查看会话、确认撤销某设备/全部设备；撤销当前设备返回登录。
- 手机底部“知识库/问答/收集/我的”；收集先选知识库，再选文件/拍照并确认。图片入口声明JPEG/PNG/WebP；HEIC等未支持格式明确提示，不偷偷转换原文。
- 手机Enter换行、中文输入法组合不误发，显式发送；新交互采用44px触控尺寸，支持safe-area和动态视口。旧复杂页面仍需真机逐项验收。
- PWA仅缓存构建生成的不可变公开壳、白名单静态资产。API、私有文件、导出、模型配置、上传与SSE不进入公共CacheStorage；联网导航响应不写公共缓存。新版本提示关闭其他窗口后重开，不强制刷新丢输入。
- Django仅提供已构建的manifest、SW、图标、版本化公开壳/资产，不把整个media映射为生产公共资源。SW/manifest使用正确MIME和no-cache；版本化资产immutable。

## 5. 实际验证

| 检查 | 字面结果 | 退出码 |
|---|---|---|
| 执行前Django check | System check identified no issues (0 silenced). | 0 |
| 执行前相关后端 | Ran 44 tests；OK | 0 |
| 执行前frontend test:unit | tests 63；pass 63；fail 0 | 0 |
| 最终相关后端 | Ran 170 tests；OK | 0 |
| 最终Django check | System check identified no issues (0 silenced). | 0 |
| makemigrations --check --dry-run | No changes detected | 0 |
| 最终frontend test:unit | tests 112；pass 112；fail 0 | 0 |
| npm run build | 构建成功；保留既有大chunk提示，没有依赖/锁文件变更 | 0 |
| Playwright移动/PWA | 4 passed | 0 |
| Playwright真实认证 | 3 passed | 0 |
| 文档本地链接/围栏、差异 | 23本地链接存在；围栏闭合；无新增行尾空白 | 0 |
| 独立副本回退 | 恢复62文件；388/388原哈希；44后端+63前端通过；主工作区仍为修改版 | 0 |

相关后端用独立APP_DATA_DIR、APP_MODE=api；固定测试文件与临时媒体目录，未调用付费模型。前端单元是项目默认`test:unit`，不是未经授权的全仓库后端套件。

浏览器结果分栏：

- 移动Chromium自动化：360/390/430 CSS px导航、上传确认、问答换行、设备入口；API夹具模拟，SW安装、CacheStorage与断网边界为真实浏览器。4/4通过。
- 真实同源Django Cookie联调：3/3通过，独立桌面/390px手机context同账号A建库B读回、B撤销A而B仍可用；同浏览器跨标签换账号不显示旧知识库；移除access Cookie后通过HttpOnly refresh恢复。认证与知识库API没有mock，隔离SQLite数据目录，未调用模型。
- Android Chrome、iOS Safari主屏幕、真实相机、OS权限/锁屏/杀进程、原生安装包：尚未验收。桌面Chromium模拟视口不替代真机。

## 6. 再部署步骤与回退

1. 保留当前数据库、文件、`.secrets`（尤其凭据加密密钥）和`.settings/service-id`；不要创建新密钥覆盖原数据。
2. 在当前锁定依赖环境运行`python manage.py check`、相关测试和`cd frontend && npm run build`。部署前保持HTML、公开shell、SW和assets同一构建批次，保留旧指纹资产到旧客户端退出。
3. 数据库变更与服务切换另行确认后，在维护窗口停止写/领取任务，先副本迁移核对，再对真实数据根运行`python manage.py migrate --plan`及`python manage.py migrate`。不能只上线前端而没有新表/字段。
4. 网页/PWA与API使用同一HTTPS来源，`DJANGO_DEBUG=false`且Hosts只允许服务域名；不要匿名映射media。前端API不需要放模型Key或数据库地址。
5. TLS在反向代理终止时，仅在Django入口不对外暴露且代理删除/重写用户传入的X-Forwarded-Proto后配置`DJANGO_TRUST_PROXY_PROTO=true`，使CSRF正确识别HTTPS；否则保留未启用。生产Secure Cookie不用于HTTP访问。
6. 本批继续受控单实例SQLite试用。PG ORM可配置不代表检索已实现；PG SearchAdapter与中文oracle通过前不宣布切换完成。独立文档worker沿用既有队列，不使用尚不存在的chat队列。

本机证据在`.cache/cross-device-p1/`，不进Git；正式测试与本报告保留。MODIFIED_FILE.tar.gz含本批修改文件和原副本/清单，DIFF_FILE.patch是相对于执行前工作区而非HEAD的变化，VERIFICATION.txt记录命令/退出码/字面结果。

ROLLBACK.sh只接受显式目标，先检查所有目标文件仍为本批修改哈希，再逐文件恢复原内容/模式；新增文件删除，用户原有修改保留。独立副本回退后重跑相同基线检查和单元测试。它是源码回退，不回退任何数据库schema/用户数据；主工作区保持修改版。

## 7. 下一批工作与提示词

优先P3，再P4/P5。不要先用原生壳掩盖业务版本、任务恢复和检索缺口。生产签名和真实数据迁移仍按方案单独确认。

```text
继续执行docs/个人知识库跨设备架构方案.md，先阅读本实施报告与AGENTS.md。
当前只有新个人空间、同源Cookie网页设备会话与M1/M2静态壳基础已经验证。
在保留现有成员/本地启动/图谱、未提交用户改动的前提下推进P3：
先为实际可编辑资源定义revision与固定条件写契约，再添加SpaceChangeHead、
SyncChange、幂等记录与绑定身份/空间的分页游标；锁顺序保证提交顺序，
不要以全局自增id或updated_at冒充提交水位。bootstrap需要不可变一致元数据清单。
把页面草稿接入按(service_id,user_id,space_id)隔离的DeviceStore，
版本冲突保留输入，删除标记阻止旧草稿复活，前台恢复合并触发、单飞补拉。
建立反向提交、重复/分页/崩溃、游标过期、账号切换和两设备冲突回归。
每批运行相关Django tests/check和frontend test:unit，改构建时再build。
只报告真实结果；P4耐久generation、P5 PG检索、桌面及Android/iOS原生包、
真机/签名/恢复发布尚未完成，不拿mock或Chromium模拟替代这些证据。
```
