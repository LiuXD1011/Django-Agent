# KB-DETAIL-LOAD-002 最新布局与加载状态独立审查

2026-10-13。审查对象为 `KnowledgeDetail.vue` 最终 SHA-256 `017504cd4c59fec91250acaf3d9235b355caddc20b23e224c881b20fd605f128`、行为回归 `c456d809…` 与布局回归 `9a682525…`。完整 SHA 见 [source.sha256](source.sha256)。本审查只覆盖本次源码及隔离组件检查，真实 Orca 复验继续由 Root 执行。

## 两项结论

- **Spec compliance：通过。** 持久加载/错误 main、安全错误文案、返回、真实重试、旧请求与卸载保护、轮询停止/恢复满足 [批准计划](../20261013-kb-detail-load-state-fix/PLAN.md)。最新 scoped 布局解决首轮真实证据明确指出的 112px 面板裁剪路径，正常文档 main 保留 `kb-detail-page`。
- **Code quality：通过。Finding：0。** 未发现本次差异中可复现的需求违反或应修复问题。改动局限于详情组件及两份回归，未删除正常功能或新增依赖。新布局测试覆盖真实 CSS、编译 scoped CSS、实际 Vue/router 和 TDesign Button，明确断言裁剪祖先、viewport、中心命中及正常 pointer 点击。

这两项结论不是真实 Orca、网络认证或整个 Goal 的验收结论。首轮 [审查报告](../20261013-kb-detail-load-state-review/REPORT.md) 对状态逻辑的结论不能代替布局验证；其未覆盖 CSS 的边界已被 Root 实测证伪，原报告和 RED/GREEN 证据保持原样。

## 审查范围与证据

已完整阅读 AGENTS.md、批准计划、[实施报告](../20261013-kb-detail-load-state-fix/REPORT.md)、[完整差异](../20261013-kb-detail-load-state-fix/code-complete.diff)、完整生产 Vue 和两份新增测试。检查实际 app.css 的 shell/workspace/content/detail/panel 规则及 1180/1080/760 等相关媒体分支、完整 mobile.css 与 main.ts 的 CSS 导入顺序。核对实际 API client 的拒绝形态与 getKb/listTags/listKnowledge 路径，及已安装 Vue watch、Vue Router memory history、TDesign Button variant/onClick、Playwright click 类型定义。

| 核对项 | 具体证据与判断 |
| --- | --- |
| 首轮裁剪原因 | 只读核对 Root [004 截图](../20261013-kb-detail-load-state-orca/004-deleted-screen.png)、[005 GET404/正文](../20261013-kb-detail-load-state-orca/005-deleted-proof-box.json)、[006 几何](../20261013-kb-detail-load-state-orca/006-button-visibility-audit.json)：返回按钮 bottom=185.84375，panel bottom=122/overflow:hidden，中心命中 MAIN。DOM/AX 存在不能代表能点击。 |
| 最新错误页布局隔离 | KnowledgeDetail.vue:982 错误/初始 pending main 使用 `content kb-load-page`；1359–1361 的 scoped 规则使该 main 为 block/height100%，panel 为 block/auto/visible，按钮容器可以换行。没有复用 app.css:1169 的 `112px minmax(0,1fr)` grid，也不再由 app.css:1532 的 panel overflow:hidden 裁剪。 |
| 正常 KB 与 1024 媒体分支 | KnowledgeDetail.vue:998 的正常 main 仍为 `content kb-detail-page`。新增三条 scoped 选择器在正常 main/header/workbench 上均不匹配；app.css:4188、4356 的正常页 grid/height/overflow 媒体规则保留。1024 错误页仍继承 content 的 auto 滚动，独立 block 面板不受正常页媒体布局牵连。独立补查也确认 docs 完成后恢复两行正常 grid，标题、文档及返回可用。 |
| 旧请求保护 | KnowledgeDetail.vue:245–272 的 current 同时检查 detailClosed、KB 代次、kbId 和当前路由，覆盖成功、await docs 后、catch/finally；249 立即废弃旧 docs，282 阻止旧 docs 发布。895–909 清空旧库/标签/统计并重新 load；971–974 废弃卸载实例。现有正式行为回归实际调度 A→B、同 ID 新 load 与卸载晚响应，断言旧成功/错误不能覆盖新结果或关闭新 loading。 |
| retry 与错误文案 | KnowledgeDetail.vue:266–267 仅按 status 分类；987 的两种固定文案不回显异常详情。991 绑定真实 load，按钮仅在 retryable 且非 loading 时渲染；load 在首个 await 前同步设置 loading 并清除错误，下一次 Vue 更新即移除重试入口。正式测试通过 deferred 验证 pending 无重试按钮；布局测试:114–122 用正常 pointer click 实际触发第二次 getKb 并等待成功，未 force 或 DOM.click。 |
| docs 与状态轮询 | KnowledgeDetail.vue:280–288 保持现有 docs/状态计数/处理记录发布；921–927 将加载及错误纳入 isProcessing，268 停止失败轮询，960–963 复用原启停路径。成功恢复后 `loading=false` 使处理中库恢复轮询；正式测试:252–266 验证恢复与卸载清理。原引用、Wiki、图谱、处理记录、分块和快速设置代码保留。 |
| 新布局回归的可信边界 | KnowledgeDetail.load-layout.test.mjs:14–52 使用完整生产 SFC 与真实全局/mobile/scoped CSS、installed Button；79–99 检查几何、全部裁剪祖先、viewport 与 elementFromPoint；105–130 两尺寸三状态验证实际导航/重试。其他 UI/子组件与 API IO 被隔离，不能据此声称认证、Drawer/Wiki 或 Root 浏览器已验收。 |

## 验证

核对实施者已归档的 [LAYOUT-RED](../20261013-kb-detail-load-state-fix/LAYOUT-RED.stdout) 与 actualexit=1：1289×921 三项确实因 panel 裁剪失败，1024×768 三项通过；[LAYOUT-GREEN](../20261013-kb-detail-load-state-fix/LAYOUT-GREEN.stdout) 与 actualexit=0 记录布局+行为 25/25；[最终 unit](../20261013-kb-detail-load-state-fix/LAYOUT-test-unit.stdout) 414/414 与 [最终 build](../20261013-kb-detail-load-state-fix/LAYOUT-build.stdout) 均有独立 actualexit=0，build 只有已记录的大 chunk 提示。本审查没有无理由重复这些完整套件，也不将它们称为审查者独立执行。

对正式布局测试未覆盖的“KB 已成功、docs 仍 pending”边界，审查者独立运行 `node --test frontend/src/views/.kb-detail-layout-review.mjs`，使用相同真实 CSS/SFC/Button/router 边界，只改隔离 API 延迟：**2/2 pass，0 fail，实际退出码 0**。见 [源码](partial-load-helper.source.mjs.txt)、[完整输出](partial-load.stdout)、[退出码](partial-load.actualexit)。

- 1289×921：pending 时正常 main 暂时为三行 grid，返回 top164.97/bottom194.97、中心命中 BUTTON，文档滚动区高402，工作台 bottom907 在 main bottom921 内；docs 完成后恢复 `112px 777px` 两行，滚动区高609。
- 1024×768：pending 返回 top72/bottom104.89、中心命中 BUTTON，滚动区高402；完成后恢复 `134.891px 601.109px` 两行。两尺寸均明确断言正常 main class、无错误页 class、正的文档滚动区域、工作台未超出 main、完整按钮几何与中心命中，并用正常 pointer click 返回实际 memory router 列表。

该补查记录了加载提示造成的临时布局重排，但没有复现返回被裁剪、正文丢失或恢复后布局异常，因此不将其列为 finding。所用浏览器是独立 headless Chromium；没有接触 Root 浏览器、真实服务、认证、用户数据或安装包，也没有启动/停止项目服务。

## 产物与清理

只新增本审查目录报告、源码副本、日志、SHA 与 [精准清理记录](temporary-cleanup.json)。临时 helper 归档内容和 SHA 核对一致后删除；未改生产代码、正式测试、原首轮 review/RED/GREEN、依赖锁文件，未执行 Git 暂存、提交或其他 Git 写操作。报告链接及本次文档差异另作检查。
