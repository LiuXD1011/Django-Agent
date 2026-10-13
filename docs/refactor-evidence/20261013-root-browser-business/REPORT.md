# Orca 知识库真实业务续验

2026-10-13，真实TypeScript HTTP入口8000+Vite5173、独立QA数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`。正常登录专用QA账户，不注入认证；浏览器profile66b0f45d-ccda-4c77-85b6-491f12a4158b/page d33064fa-a31e-416d-82c6-80339b47543c。原已有资料2库/16条目/10027摘录、5条四类模型配置、174调用、active jobs0。没有新外部模型调用。当前整组B和整个Goal仍未完成。

## 实际操作与结果

所有提交、置顶、打开、复制、筛选、删除通过Orca原生mouse move/down/up；输入通过fill，搜索真实Enter。readonly eval仅读取布局/请求timing/DOM，无DOM.click、router强制跳转、业务API写或认证注入。每个命令的原JSON与attempt分开保存。

| 场景 | 实际结果 | 原始证据 |
| --- | --- | --- |
| 正常QA登录 | 登录成功，列表2库/16条目/10027摘录 | [004登录页](004-login-snapshot.json)、[008鼠标](008-login-move.json)、[011结果](011-after-login.json) |
| 新建空知识库 | 真实库03591ced…，0条目/0摘录，列表增加到3；配置和描述持久化 | [031–033中的最终release](033-create-stable-up.json)、[034结果](034-create-stable-snapshot.json)、[只读核验](created-stable-readonly-db.json) |
| 置顶和刷新 | 置顶badge/取消置顶按钮存在，真实reload后仍保持 | [038操作](038-pin-up.json)、[041刷新](041-reload-state.json) |
| 打开空库 | 文档空状态/0统计，全选、批量删除、移动禁用；Wiki/图谱按未启用配置禁用 | [046详情](046-owned-empty-details.json) |
| 编辑名称及描述 | 详情标题与真实DB立即更新，返回列表保留修订名称/描述；侧栏同页旧名异常见下 | [058保存](058-save-up.json)、[059结果](059-edited-detail.json)、[编辑核验](edited-readonly-db.json)、[069列表](069-list-edit-persistence.json) |
| 复制空库 | 新独立ID990690de…，带copy后缀、描述与原相同，取消原置顶继承；条目/摘录仍0 | [073操作](073-copy-up.json)、[074结果](074-copied.json)、[复制核验](copied-readonly-db.json) |
| 相似名称搜索 | B7K4匹配两个库；加完整copy后缀只返回副本，未混淆ID | [077两库](077-search-two.json)、[089单库](089-search-copy-one.json) |
| 收藏筛选 | 两个匹配结果中只显示已置顶原库，回全部恢复两个 | [082收藏](082-favorite-one.json)、[086全部](086-all-two.json) |
| 不存在关键词 | 明确空列表及0统计 | [092空状态](092-search-empty.json) |
| 删除两个owned空库 | 分别按实际名称确认，只软删除两个owned ID；列表B7K4为空，原库未改变 | [101副本确认](101-delete-copy-dialog.json)、[107结果](107-copy-deleted.json)、[113原库确认](113-delete-original-dialog.json)、[119结果](119-owned-none.json)、[删除核验](deleted-readonly-db.json) |
| 返回现有资料 | 原2库/16条目/10027摘录，5模型/174调用和25受管文件SHA未变 | [131原列表](131-restored-baseline.json)、[最终只读核验](baseline-restored-readonly-db.json) |

## 发现的问题与处置

`KB-SIDEBAR-001`：同一列表页新建/复制/删除以及详情改名后，最近访问只在route.path改变/挂载时重新加载。删除后119列表为空但120侧栏仍有已删除ID。Root通过[121坐标](121-stale-recent-box.json)、[122–124最终release](124-stale-recent-up.json)真实点该入口，[125结果](125-stale-recent-result.json)/[126实际PNG](126-stale-recent-screen.png)进入已删详情并提示加载失败；[127资源时序](127-stale-resource-confirm.json)最后GET真实404/60.2ms、mainText=null。已委派专属前端修复和行为RED/GREEN，Root将再用Orca重跑；本报告当前不宣称修复或整组通过。[修复任务要求](sidebar-fix-brief.md)。

`KB-DETAIL-LOAD-002`：直接访问无效/已删ID，短暂toast后正文没有持久错误状态和返回/重试入口；可使用主导航返回。该相关问题另行保留待修，不因修sidebar而消失。

退役核查另发现当前Langfuse autostart设置缺真实TS owner落点，10旧入口本轮未删除；具体语义核查由旧退役代理独立进行，不能隐藏此功能缺口。

初次新建020–022在弹窗动画期间使用旧位置，未发生创建；023/created-readonly-db记录仍无owned库，不算通过。重新截图/核稳定transform:none、opacity:1，031–033实际创建后才计真实结果。一次返回操作062–064落在未关闭modal遮罩，仅关闭modal；066–068才实际返回列表。没有把工具ok或固定等待当产品通过。024截图解码助手最初期待dataBase64但当前Orca字段data，已按实际工具结果直接解码PNG、移除public JSON中的base64、修正自有助手；没有编辑图片或产品代码。

## 延迟与边界

来自浏览器PerformanceResourceTiming，单次本地HTTP请求，不含工具轮询等待、DOM反馈完整延迟，不宣称P95/并发能力。运行条件Node22.23.2/本地SQLite/现有QA资料；中途Core完整fixture suite并行，不能与生产负载等同。

- [025原始timing](025-create-hit-test.json)：正常登录161.2ms，首次列表203.9ms。
- [061编辑timing](061-edited-timing.json)：空库详情GET161.4ms，空文档列表11.3ms，真实编辑保存请求15.5ms。
- [120完整timing](120-final-timings.json)：复制13.7ms；B7K4搜索14.8ms，copy精准搜索21.5ms，不存在关键词8.8ms；副本删除49.5ms，原库删除21.5ms。scope重新加载21.2/29.3ms为不同条件单次请求，不聚合成分位数。
- 原置顶/新建的请求timing在reload前未单独保存，因此不填估计值；真实操作和持久化证据保留。

两owned库以正常产品删除语义保留soft-delete审计行。受保护原业务表及文件每阶段只读SHA核验不变，认证表因正常登录可更新，未把它们算不变；没有触碰真实管理员、API Key或撤销他人设备。私有QA登录文件与本浏览器profile暂保留用于修复后重跑，两个本轮临时助手仍在使用，整个Goal最终清理未完成。

剩余B组：非空复制/删除及索引关联、同名/极端长度、真实应用重启、最近日期/本空间筛选边界和安装版复核等未由本报告覆盖；不把上述空库子场景替代整组B。

## 修复后真实Orca回归

`KB-SIDEBAR-001`已完成本次浏览器场景修复和复验；整组B仍不标PASS。前端独立19行为回归原RED14FAIL，修复GREEN19/19；现前端389/389及build actual0。[实现证据](../20261013-kb-sidebar-sync-fix/REPORT.md)和[独立spec/quality审查](../20261013-kb-sidebar-sync-review/REPORT.md)均已读，审查通过、没有finding。两个当前production SHA分别Platform46827813…/API22a48b23…；没有修改auth/Core业务。

Root在同一page上显式reload载入新前端后，通过正常鼠标新建owned库`5ccffe77-afb4-4341-8c00-c2dcbb0dc80e`。同页[145即时结果](145-fix-created-immediate.json)同时显示列表和侧栏新名称，未额外reload或导航；[148真实侧栏打开](148-fix-open-recent-up.json)/[149详情](149-fix-details.json)路径对应正确ID。设置保存[160真实release](160-fix-save-up.json)后，[161即时改名](161-fix-renamed-immediate.json)详情与侧栏同时改名，仍同一详情路由。

按该对象实际名称确认[177删除弹窗](177-fix-delete-dialog.json)，[181真实release](181-fix-confirm-up.json)后，[182即时结果](182-fix-deleted-immediate.json)/[183原PNG](183-fix-deleted-screen.png)列表和侧栏都只剩两原库，[184读值](184-fix-final-read.json)再次核对无已删入口，未导航/刷新才能产生此变化。[只读核验](sidebar-fix-deleted-readonly-db.json)原业务表与25文件SHA仍不变、模型5、用量174、active jobs0；第三owned对象也仅正常soft-delete。原故障119–127保持。直接无效链接持久错误态`KB-DETAIL-LOAD-002`仍待修，不把侧栏成功消除该独立缺口。

184原浏览器ResourceTiming记录本次单次创建POST12.1ms/侧栏reload87.5ms；改名10.9ms/侧栏76.4ms；删除20.6ms/侧栏57.9ms。工具执行时间不充当用户感知延迟，不宣称P95或并发能力。164鼠标move因执行工具异步yield，165down先于move终态被观察；两原回执与终态poll5321c7保留，后续动作已等同一session终态才执行，关闭弹窗并正常返回结果单独观察。此不作为产品延迟数据。

本轮Windows869a0401…安装包生成在此侧栏修复之前，不能宣称包含本次修复；已保留原468来源/ASAR/actual0安装包证据，最终新包需要绑定后续源码迭代。Core当前完整698/696/2默认SKIP、显式compiledOwner2/2另有独立记录，没有用条件SKIP冒作PASS。Langfuse autostart由专属Core子代理迁移，旧10入口仍暂缓，整个Goal active/incomplete。
