# 最终交付报告

状态：实施中，Goal active；已有真实桌面运行、基线安装和四模型业务证据，尚未达到最终交付标准。未提交、未推送、未发布。

## 当前可核对结果

- 主业务使用 `packages/core` 的 TypeScript核心、SQLite、FTS5/sqlite-vec；Electron通过正式preload/IPC访问核心，随包Python只用于解析与Ragas辅助工作。已运行的Windows正式smoke无需系统Node/Python或Vite，不监听旧桌面HTTP端口。
- 旧数据完整副本31表、2445文件已导入，重复导入通过；44表、2446文件备份和独立恢复核对记录、文件hash与FK。没有对原库重放旧Django迁移。[迁移与恢复](MIGRATION.md)。
- 用户重新配置的对话、Embedding、ReRank、视觉四角色均已有实际厂商调用；自编五份资料完成入库及摘要。相似实体与图片问题经事实、计算及机器引用核对，并实际打开图片OCR的准确来源。[厂商与来源记录](../refactor-evidence/20261010-windows-model-vendor-regression.json)。
- 新发布的5条不同、已审核且来源有效的题目已通过唯一一次真实Ragas评测，164.721秒、45次成功调用、39505 tokens；Faithfulness为1，Answer Relevancy为0.9472539593197356，Context Precision为0.9999999999。Context Recall和Answer Correctness为null/未运行。已实际下载并打开报告，核对5样本、配置、来源和用量；这些结果只代表此次小样本，不作整体质量或P95结论。[真实页面、账本与报告](EVALUATION-CHINESE-QUERY-BROWSER.md)。
- 基线NSIS已在专用中文空格路径安装并通过当时的正式smoke；验收专用账户完成密码修改，真实管理员密码、模型Key及其他用户设备未修改。最新来源代码升级已通过，随后隐藏smoke在截图阶段失败；正常窗口关闭到后台、托盘退出和退出后资料保护已另行验证，卸载保留数据、异常重开和完整生命周期仍待执行。

## 基线安装器与版本

以下为第二个基线包的历史记录，不包含后续全部修复，不能作为最终包交付；最新来源代码升级结果见下文：

```text
C:\Users\lxd\AppData\Local\Temp\Marlin TS Installers 20261010\Marlin-Setup-0.6.2-x64.exe
SHA256: 1d431f64f9d9de54a2e3c169fc12d774ef2a439786ecec852e5ba84052b52ee7
401698923 bytes
```

Electron44.7.0，携带Node22.23.2、Python3.13.16；桌面包版本0.6.2、核心0.7.0。原生Windows x64是本次必须交付的平台，macOS/Linux桌面包尚未验收。[实际构建](../evidence/20261010-windows-nsis-build.json)、[安装](../refactor-evidence/20261010-windows-nsis-installation.json)、[安装版smoke](../refactor-evidence/20261010-windows-installed-smoke.json)。

默认用户数据位于 `%LOCALAPPDATA%\Marlin`，与安装位置分离。验收使用专用目录；默认真实数据没有被安装或卸载测试覆盖。

## 运行与检查

开发前构建核心与界面，然后分别启动同一核心的HTTP适配和Vue：

```bash
npm run build
npm run start:local -- --data-root /path/to/isolated-marlin-data
npm run dev
npm run typecheck
npm run test:core
npm run test:frontend
npm run test:desktop
npm run test:startup
```

源码桌面需要原生Windows构建器准备完整资源，不能直接运行缺payload的desktop目录。运行和辅助进程参数见[README](../../README.md)、[桌面说明](../desktop.md)及[Windows构建](../windows-installer.md)。启动入口与正式构建门槛仍在独立复核，最终报告会记录最终源码、完整资源与安装器hash。

## 尚需完成的必做验收

- Orca所有核心页面真实操作、正式Electron复核与其余标准问答；工具送达但没有业务变化的操作没有计通过。
- 评测其余审核模式、取消/恢复/失败场景及最终安装版复核，逐项以[验收矩阵](TEST-MATRIX.md)记录；已完成的五题运行与下载不替代这些子项。
- 最终NSIS、升级/卸载保留数据、异常重开及其余生命周期、各页面窗口尺寸与缩放检查；已验证的正常托盘退出和两种评测页尺寸不替代其余子项。
- 最终代码清理、秘密材料与临时认证文件清理、最后的源码/资源一致性检查。

Windows已解锁，Orca真实页面操作正在继续。最新中文检索修复已接入同一TypeScript核心，五题无模型检索的Hit/MRR/Recall均为1；原前端346/347的[失败收据](../refactor-evidence/20261012-integrated-chinese-query-windows-build/prepare-execution.json)保留。轮询测试修复后，Windows前端347/347、Vite和核心build均通过，但完整prepare因根代理选用了不含pip的应用内Python而失败，完整[终态](../refactor-evidence/20261012-integrated-poll-clock-windows-build/prepare-execution.json)仍是exit1。正确构建解释器 `C:\Python313\python.exe` 已确认。搜索 Provider 管理、默认服务与总开关、MCP 编辑 DTO 已补齐，前一轮前端为 360/360。实际搜索页面又发现修改地址后旧连接提示残留，已最小修复并完成 Orca 成功与失败两类复验；最终相关 29/29、完整前端 361/361、生产构建退出 0、Windows 单文件 14/14。同时修正单元 fixture 的 Windows 路径识别，保留真实认证逻辑与原断言。[修复与证据](WEB-SEARCH-CONNECTION-RESULT.md)、[最终前端冻结](../refactor-evidence/20261012-web-search-result-invalidation/freeze.json)。该来源安装包已生成并通过独立文件核对，实际升级与安装版业务仍在验收。

108 个核心测试文件共 685 项的原[全套结果](../refactor-evidence/20261012-final-core-suite/execution.json)为 682 通过、3 失败。其中 2 项编译入口因根代理误用 tsx 启动，正确 plain Node 入口已[2/2通过](../refactor-evidence/20261012-final-core-compiled-correct-launch/execution.json)；另 1 项旧查询命中文档标题，已调整独立资料并直接核对物理 FTS，相关[24/24通过](../refactor-evidence/20261012-knowledge-unicode-edit-fixture/verification.json)。后续 109 文件全套 692 项为 688 通过、2 失败、2 编译条件跳过，原[失败结果](../refactor-evidence/20261012-web-search-final-core-checks/full-execution.json)保留。两项分别为 Root 的 Python PATH 选择错误和 HTTP 请求开始前已触发测试期限，正确环境的密码兼容 11/11、控制期限的真实 HTTP 任务 27/27 已通过。另发现搜索实际 URL 别名可绕过密钥换主机保护，已最小修复，最终相关 106/106、类型与构建通过。[根因、修复及检查](WEB-SEARCH-EFFECTIVE-ENDPOINT-GUARD.md)。最新核心完整检查为：[693 通过、0 失败、2 编译条件跳过](../refactor-evidence/20261012-web-search-alias-final-core-checks/full-execution.json)，700.756 秒；两项用正确 plain Node 入口另行[2/2通过](../refactor-evidence/20261012-web-search-alias-final-core-checks/compiled-execution.json)。核心输入和编译文件未因前端修复改变。最新[集成来源](../refactor-evidence/20261012-web-search-result-integrated-source-freeze.json)为 457 输入、5 额外测试、523 编译文件，SHA256 `5cabb11adcff22acf3c02f6cb70dce381acc3b19597d662ac95c6e2d471a7bac`。原 `cf2a6b7a…` 的 prepare 已中止，wrapper 退出 1、正式 child 结果 null，清理等待超时，不能称该轮 prepare 通过；中止前的七项 Windows fixture 失败保留。[真实中止终态](../refactor-evidence/20261012-web-search-integrated-windows-build/root-cancellation-terminal.json)。新来源使用正确宿主 Python 和全新 Windows staging，已完成真实原生 prepare：退出 0、所属进程树收尾通过，1806.244 秒；完整 Windows 前端 361/361、Vite、核心、原生 SQLite/IPC、Python worker 及 Electron 检查通过。[本轮 prepare](../refactor-evidence/20261012-web-search-result-integrated-windows-build/prepare-execution.json)。package 已实际退出 0，安装器详情如下；安装版业务仍待实际验收。

最新来源的原生 package 已实际退出 0，所属进程树正常收尾，824.276 秒；安装器为 `C:\Users\lxd\AppData\Local\Temp\Marlin TS Search Result Installers 20261012\Marlin-Setup-0.6.2-x64.exe`，401841299 字节，SHA256 `99baabeeb82dd4af6312356810a91d0a2b51ec1c62726a8de3d917305fe5a8f6`。资源审计与 25378 个待安装文件核对通过；随后在固定验收目录实际完成同版本代码升级，NSIS 退出 0、345.244 秒，所属进程树正常退出，25379 个安装文件及 25304 个运行资源全部核对。94 个验收数据文件、12 个业务表和凭据材料与升级前完全一致；此验收目录本来无模型，不将它当作四模型恢复证据。[实际 package](../refactor-evidence/20261012-web-search-result-integrated-windows-build/package-execution.json)、[独立产物绑定](../refactor-evidence/20261012-web-search-result-install-preparation/iteration-1/artifact-binding.json)、[实际升级](../refactor-evidence/20261012-web-search-result-install-preparation/iteration-1/executed-upgrade.json)。

随后正式隐藏 smoke 的应用进程退出 0、所属树正常收尾，但产品在 `capturePage` 阶段返回 `UnknownVizError`，只留下 `ok:false` 的结果；完整验收命令退出 1，不能将进程正常退出计为界面、preload 或页面就绪通过。[失败原始收据](../refactor-evidence/20261012-web-search-result-install-preparation/iteration-1/executed-hidden-smoke.json)保持。同一安装版的可见窗口对照已实际执行：产品返回 `ok:true`、登录页就绪、正式 IPC、TypeScript 核心且无 HTTP listener，启动到页面就绪为 3170.342 毫秒；1264×821 的 PNG 已实际打开核对。但诊断脚本的后置进程核查返回 `native_candidate_path_unavailable`，整条命令仍退出 1，原收据不改为通过。此对照没有修改产品或放宽原 smoke 断言。[实际诊断](../refactor-evidence/20261012-installed-smoke-visible-diagnostic/executed-visible-smoke-diagnostic.json)、[截图复核](../refactor-evidence/20261012-installed-smoke-visible-diagnostic/root-visual-review.json)。

Windows 正式恢复实际退出 0、72.233 秒，额外只读核对退出 0、5.709 秒，两个所属进程树均正常收尾；72 张表的完整摘要由正式恢复核对，26 个文件和 24 个本地媒体引用通过，79 个加密凭据字段已认证解密，仅报告统计。任务与待认证收据均无活动项，整个恢复未发送认证或模型请求；原 Linux 数据目录未被此恢复脚本打开。恢复副本位于 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\浏览器资料副本 20261012 第1轮`。[实际 Windows 恢复](../refactor-evidence/20261012-offline-windows-restore-launch/executed-restore.json)。

该副本已通过安装版的正常登录页面登录自有验收账号，显示原有两个知识库、16 个条目和 10027 个分块，地址为正式链路 `https://marlin.local/platform/knowledge-bases`。此前保存的凭据先仅与冻结备份作单候选只读核对，再从密码输入框和登录按钮完成认证；没有重置真实管理员密码或注入认证记录。[凭据可用性核对](../refactor-evidence/20261012-offline-windows-restore-launch/root-owned-source-login-availability.json)、[实际登录后页面](../refactor-evidence/20261012-root-native-clone-gui/005-after-login.json)。后续正常窗口已完成现有图片 OCR/描述查看、准确图片来源的第 2 子块定位，以及现有五题 Ragas 报告的真实另存。新下载 JSON 为 8275 字节、SHA256 `2d94a554c2f9ae468c1dc853a4e14140c5aafc52de985547d1dd5d7778b8e0c2`，与原报告一致，原下载文件未覆盖；没有重跑付费评测。旧手册会话的已失效分块引用显示“引用来源不存在或已删除”，不计为当前有效引用通过。[安装版页面专项](INSTALLED-CLONE-GUI-ACCEPTANCE.md)。

该正常窗口关闭后进程继续在后台运行，随后通过所属 PID 的托盘菜单“退出”结束；正式启动验收命令退出 0、完整所属进程树正常结束，未靠通用 kill 收尾。退出后的受保护表、凭据与设置文件、受保护桌面元数据及媒体核对结果均与启动前一致；认证会话相关表因正常登录有所增加，未称整个数据库逐行完全相同。3879232.337 毫秒是整次窗口停留寿命，16651.61 毫秒是 bootstrap reap，不作启动延迟或 P95。[正常启动与退出终态](../refactor-evidence/20261012-installed-clone-visible-launch/executed-visible-clone.json)。评测页在实际 1440×900 和 1024×768 窗口下可读，但 1024 宽度的收起侧栏存在导航名称缺失。源码已最小补充按钮名称、提示和当前页标记；前端完整 361/361 与生产构建实际通过，源码浏览器实际 DOM 属性核对通过。新来源冻结为 `6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8`，唯一源变更是该组件，438 核心编译文件保持，85 前端产物绑定新构建。新安装包和实际 1024 收起侧栏复验仍待完成。[侧栏修复及验证边界](SIDEBAR-ACCESSIBLE-NAMES.md)。125%/150% 缩放和其他页面尚未按此轮尺寸检查。

源代码浏览器的两个本轮空知识库已完成搜索、取消置顶、收藏空态及删除取消/确认子项，并清理到原有两库、16 条目、10027 摘录。最终只读核对确认受保护资料与凭据材料未变，模型用量记录仍为 174。该批普通 CLI 点击没有确认交付，搜索和清理采用 Orca eval 中标准 DOM 按钮触发；没有调用 Vue 业务函数或直接调用后端接口，也没有据此把鼠标点击或 B 组整体标为通过。[知识库列表续验与限制](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)。

独立普通验收账号已完成真实鼠标的默认 600 秒自然过期后续期与当前设备撤销、两个共享登录页面的退出联动，以及新代次的当前设备撤销后另一 Cookie partition 保持正常读取。只关闭自有登录页后，从自有空页打开新 document 能恢复身份；未将其称作完整浏览器进程重启。共享页 logout 当时没有其他有效独立设备，自然过期和多设备保持也是两个独立案例，均按实际边界记录。四个自建设备已退出，模型调用和任务始终为零，12 个临时助手及合成口令文件已清理；独立核心实际退出 0、Vite 收到 SIGTERM 后退出 143，原源代码服务保持。迟到刷新竞态、权限补验和安装版认证仍待执行。[隔离认证浏览器专项](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)。

侧栏修复的新 Windows stage 已完成实际独立复制，81263 个文件、2146851880 字节，所属进程树收尾通过；旧、新 payload 与锁文件通过正式核验，旧产物保持。[新复制终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/copy-execution.json)。随后正式 prepare 返回 0、完整所属树退出，1293.909 秒；本轮 Windows 完整前端 361/361、Vite 与核心构建、SQLite/IPC、11 类 Python 用例和 Electron/NextAuth 检查通过，零模型调用。新安装器 package 和实际安装/1024 侧栏复验尚待终态，旧隐藏截图失败不改写。[新 prepare 终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-execution.json)。

MCP 已完成真实官方 SDK 握手、工具发现和唯一 Agent 回合，工具执行 12×79=948，轨迹、协议调用与保存结果关联一致；新增 4 次成功模型调用、3353 tokens。仅删除验收创建的服务，原模型、密钥和知识资料保持，受控 SDK 服务已正常退出。[真实 MCP 页面与协议](MCP-REAL-AGENT-BROWSER.md)。联网搜索已完成配置、失败处理、唯一真实 Agent 回合及两条来源的实际打开核对，正确回答 37 天；新增 4 次成功调用、3846 tokens。受控 HTTP 已正常退出，自有配置经 GUI 清理后，在离线维护中仅将本次总设置条件恢复原 NULL；原模型、密钥和资料保持。[真实联网页面](WEB-SEARCH-REAL-AGENT-BROWSER.md)、[HTTP 终态](../refactor-evidence/20261012-web-search-real-browser/server-stop.json)。安装版资料副本已完成实际 Linux 正式导出：72 表、26 文件、24 本地媒体引用；原目录完整清单保持，所有备份文件重新核对 SHA。[实际导出](../refactor-evidence/20261012-offline-source-stop/export-execution.json)。Windows 正式恢复、正常 GUI 登录及图片引用/报告下载的已验子项见上文，不将备份恢复替代其余页面步骤。[副本准备边界](OFFLINE-CLONE-HARNESS.md)。

Neo4j旧配置的真实只读连接失败，原图数量未知；不能写成空图或已迁移。可选外部Langfuse、搜索等真实服务尚未全部验收，受控协议测试与厂商结果分开记录。

具体进度与修复结果见[STATUS](STATUS.md)和[TEST-REPORT](TEST-REPORT.md)，完整完成门槛见[SPEC](SPEC.md)和[TEST-MATRIX](TEST-MATRIX.md)。上述缺失的核心条件没有用“未验证”替代或计为通过。
