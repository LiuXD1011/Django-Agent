# 知识库加载错误：Root Orca 实测

2026-10-13。`KB-DETAIL-LOAD-002` 的持久错误页、可见返回按钮及真实网络失败后重试流程已完成本次 Orca 复验。正常知识库的文档、Wiki、解析记录入口也通过本次点击回归。该结论限于这些流程，不代表知识库全部功能、安装版或整个 Goal 已完成。

生产详情组件 SHA `017504cd4c59fec91250acaf3d9235b355caddc20b23e224c881b20fd605f128`。实现与自动化证据见 [修复报告](../20261013-kb-detail-load-state-fix/REPORT.md)；最新 [独立布局审查](../20261013-kb-detail-layout-review/REPORT.md) 两项通过、finding 0。对应来源的定向 25/25、前端 414/414、build exit0；审查另外补查两尺寸正常部分加载 2/2。计数有重叠，不累计为独立样本数；后续 Platform 修改需要自己的验证。

## 环境和方法

- 页面 `d33064fa-a31e-416d-82c6-80339b47543c`，专用 profile `66b0f45d-ccda-4c77-85b6-491f12a4158b`，标签 `Marlin Browser Business 20261013 B7K4`。
- 实际浏览器入口 `http://127.0.0.1:5173`，真实 TS CoreOwner HTTP 在 `127.0.0.1:8000`。独立数据 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`；使用此前正常登录的专用 QA 账号，没有注入认证或更改真实管理员密码。
- 实测 viewport 1289×921；1024×768 的布局验证属于独立 headless 测试，本次没有把它写成 Orca 实测。
- 操作采用 Orca mouse move/down/up，每步等实际工具终态，导航后重新 snapshot。只读 eval 记录 DOM 几何、elementFromPoint、可见性及 PerformanceResourceTiming；没有 DOM.click、force click、mock 后端或成功响应替身。

## 原失败与修复后的返回

删除对象为前一轮正常创建、随后经页面确认软删除的专用 QA KB `03591ced-c5b0-4c1d-841a-35701aa724be`，未操作真实用户对象。

首轮有持久错误和 AX 按钮，但 [004 截图](004-deleted-screen.png)、[005 读取](005-deleted-proof-box.json)、[006 几何](006-button-visibility-audit.json) 证明返回被原共享 grid 裁剪：button bottom185.84，祖先 panel bottom122/overflow:hidden，中心命中 MAIN。该轮不能记按钮可用。

独立 scoped `kb-load-page` 修复后，[019 导航](019-visible-deleted-goto.json)、[020 状态](020-visible-deleted-state.json)、[021 几何和真实 GET404](021-visible-deleted-box.json) 显示固定安全文案、按钮 bottom171.84、panel bottom196.84、中心命中 BUTTON，document.hidden=false、main opacity=1。[022 可读截图](022-visible-deleted-screen.png) 已由 Root 实际查看。连续 [023 move](023-visible-return-move.json)、[024 down](024-visible-return-down.json)、[025 up](025-visible-return-up.json) 正常点击后，[026](026-visible-return-list.json) 已返回真实列表：2库、16条目、10027摘录。

此前 [009 截图](009-fixed-screen.png) 淡出、[015](015-main-visibility.json) 与 [017](017-focused-visibility.json) opacity=0，是 Orca 被放在后台时 document.hidden=true、page-in 动画 currentTime=0/startTime=null 的工具环境状态。tab focus 调用未恢复可见性；native computer-use restore 后 [018](018-restored-visibility.json) hidden=false、动画 finished、opacity=1。未修改产品样式或跳过动画来制造截图通过，原淡出证据保留。

## 正常详情回归

[027–030](030-normal-kb.json) 正常点击 QA“Orca 全流程验收 20261010”：KB `86f94109-c3f2-4cba-819e-d7bfdea42709`，2文档，7摘录、13总块，0处理中。[031](031-normal-kb-layout.json) 确认正常 main 仍为 `kb-detail-page`、无错误区域、opacity=1、真实 KB/tags/docs GET200。

[032](032-normal-tabs-box.json) 记录实际按钮中心命中；正常 pointer 点击 [033–036 Wiki](036-wiki-state.json) 显示已有页面与来源，[037–040 解析记录](040-records-state.json) 显示两条已完成记录，[041–044 文档](044-docs-state.json) 回到正确列表。未生成新 Wiki、重解析或发起模型请求；禁用的图谱入口不计作图谱通过。

## 真实中断、持久提示和重试

[停止前审计](transport-core-stop-native-audit.json) 确认 active jobs=0、原保护业务/文件不变。仅对自己启动的旧 QA Core PID3622114、Linux start ticks26564594、精确 exe/cwd/argv 取得原 pidfd，再核身份后 SIGTERM。[原 pidfd 回执](transport-core-stop-native-stop-result.json) 同原句柄终态 true，约160.71ms；原 exec session21756 也实际 exit0。没有按端口或进程名杀进程。

已有正常认证的 SPA 中，[045](045-transport-target-box.json) 验证目标中心命中后，[046–049](049-transport-error.json) 正常侧栏点击“Orca 格式验收 20261011”，实际 Vite 对 Core 连接失败产生 GET500。[050](050-transport-persistent-proof.json) 在约47秒后仍显示持久固定错误、返回和重试，而不是空白页或短暂 toast；重试中心命中且 opacity=1。[051 截图](051-transport-error-screen.png) 已实际查看。

Root 使用同 dataRoot/parser/evaluation 参数重启真实 TS dev-server，显式 `LANGFUSE_AUTOSTART=false`，以隔离可选 Docker 副作用；没有修改保存配置。新 exec session66476 实际输出 `Langfuse local startup: disabled.` 和 `TypeScript core listening at http://127.0.0.1:8000`，仍作为测试服务运行。它加载当前 Core 修复来源，独立服务启动的真实 Docker/Windows 门禁仍未完成。

不用刷新、重新登录或换页，正常 [052 move](052-retry-move.json)、[053 down](053-retry-down.json)、[054 up](054-retry-up.json) 点击重试；[055 snapshot](055-retry-recovered.json)、[056 读取](056-retry-success-proof.json) 确认相同路由恢复真实 KB GET200、tags GET200、docs GET200，14文档、正常详情布局、错误区域已消失。[057 恢复截图](057-recovered-screen.png) 归档。

## 延迟与数据保护

| 浏览器资源耗时，单次 n=1 | 实际结果 |
| --- | --- |
| 删除对象 KB GET | 404，9.0ms |
| 正常 KB / tags / docs | 200，58.8 / 59.9 / 11.2ms |
| 中断期间 KB / tags | 500，13.2 / 14.2ms |
| 恢复后重试 KB / tags / docs | 200，82.9 / 85.5 / 49.7ms |

以上来自浏览器 ResourceTiming，不是 Orca 命令等待时间；不作为稳定 P95、首屏总耗时或并发结论。无付费模型请求。

[前审计](before-transport-retry-audit.json) 和 [后审计](after-transport-retry-audit.json) 均相对前一轮原基线核对 12组保护业务与25个 managed 文件 SHA：完全不变，models5（此前四类配置）、model_usage174、active jobs0。`.secrets`仅作文件哈希，未解密或打印；未读取专用登录秘密文件。auth运行表允许正常启动/会话活动，不声称数据库全文件逐字节不变。

## 新发现与后续

`KB-SIDEBAR-003`：真实 GET500 时侧栏把先前2条最近记录清为“暂无最近记录”；详情重试恢复后 [056](056-retry-success-proof.json) 仍错误为空。随后已由独立代理修复并完成下述独立审查和 Root 实测，本开发浏览器对应缺陷闭合。没有用详情页通过掩盖这处问题。

### 侧栏修复后的真实复验

[实现报告](../20261013-sidebar-network-recovery-fix/REPORT.md) 与 [独立审查](../20261013-sidebar-network-recovery-fix/INDEPENDENT-REVIEW.md) 确认最小 Platform 修复，来源 SHA `808282890044ef3aa36cdc1b7518449bc8aec48229e533defa1355b20d75a592`。定向27/27、最新前端422/422、build exit0；不累计与前轮414或定向重叠项。

[059](059-sidebar-fixed-target.json) 确认两条最近记录与可见导航。第二次仅停止 Root 自有 Core PID4096365/start ticks26929578：[审计](sidebar-recovery-core-stop-audit.json)、[同原 pidfd 终态](sidebar-recovery-core-stop-stop-result.json) 约66.49ms、active jobs0；原session66476实际exit0。正常 [060–063](063-sidebar-failure-state.json) 点击另一个QA库触发真实 list/KB/tags GET500。[064](064-sidebar-failure-proof.json) 确认保留两条最近记录、固定安全错误文案及可命中“重试加载”按钮，而不是显示空记录；list失败10.0ms。[065截图](065-sidebar-error-screen.png) 已实际查看。

按相同隔离参数第二次重启 Core（session68767），实际 disabled/listening stdout 后，正常 [066–069](069-sidebar-recovered.json) 点击侧栏重试；[070](070-sidebar-recovered-proof.json) list真实GET200/93.6ms，两条记录、错误/重试消失。此时详情错误仍等待自己的重试，未伪装成已加载。随后正常 [071–074](074-final-recovered.json) 点击详情重试；[075](075-final-recovery-proof.json) KB/tags/docs GET200（13.6/15.0/14.9ms），两条文档、main opacity=1、两个错误区域都已清除、最近记录保持。[076截图](076-final-recovered-screen.png) 已实际查看。

[第二次后审计](after-sidebar-network-recovery-audit.json) 同12组保护业务/25文件完全不变，models5/model_usage174/active jobs0。延迟仍为各单次ResourceTiming，不代表P95。首次加载失败/成功空列表/晚响应与键盘路径由独立回归覆盖，不冒称本次Orca故障流程包含这些独立场景。

当前真实服务身份见 [最终运行检查点](final-current-core-live-services.json)；仍运行，不是进程终态完成。此前 [第一次重启检查点](live-services-after-retry.json) 保留，不能据其旧pid再做进程操作。这两份 observer 的 `saved_settings_unchanged` 来自保护业务/managed文件比较，没有单独比较数据库设置表；仅应作为该保护范围相等的证据，不能扩展成全部设置逐字节未变。Root本流程设置保存操作为0，重启采用的是进程环境覆盖。

仅开发浏览器本项通过；Windows 正常 GUI及最终新版包、本次两个问题以外的全页面验收仍待继续。38组整体计数不在本报告增加。

临时服务控制 helper 首次系统 Python 无 os.pidfd_open，改用3.12解释器仍缺该构建 API，两次 actual exit1 均在发信号前退出。旧源码分别保留 [初版](service-helper-initial.source.py.txt)、[API能力检查版](service-helper-py312-check.source.py.txt)；随后根据本机 x86_64 unistd 434/424 类型和编号使用原 pidfd syscall，实际安全终态见上。原两份早期审计的 `credential_files_read=false` 指未读取私有登录文件，字段名不准确：managed `.secrets`确实被哈希；后续审计已改明确字段，原证据未重写。

Orca/version guide 的 `exec help` 当前实现返回 Unknown command/help（actual1），没有产生页面或业务修改，也未继续猜测离线命令。正常真实 backend 中断和恢复用于完成本用例。自有 helper 完整来源与精确清理见 [消费记录](consumed-helpers.json)，本次两个流程完成后删除自己的两个临时helper，保留实际测试服务和后续Goal仍需的私有登录文件。报告/关键来源、原始操作及链接核对见 [检查点](validation-checkpoint.json)。
