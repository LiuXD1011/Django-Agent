# KB-SIDEBAR-003 最近访问网络失败与重试修复

代码、隔离浏览器回归验证与独立审查已通过。问题关闭仍须 Root 的真实 Orca 网络故障/恢复复验；本报告不表示全部验收通过。

## 真实发现与最小修复

Root 的 [049 错误快照](../20261013-kb-detail-load-state-orca/049-transport-error.json)、[050 持续错误证明](../20261013-kb-detail-load-state-orca/050-transport-persistent-proof.json) 与 [051 截图](../20261013-kb-detail-load-state-orca/051-transport-error-screen.png) 证明正常侧栏导航触发真实 Vite 500 后，最近访问显示“暂无最近记录”。重启 Root 自有 QA 后端并重试详情后，[055 恢复快照](../20261013-kb-detail-load-state-orca/055-retry-recovered.json)、[056 恢复证明](../20261013-kb-detail-load-state-orca/056-retry-success-proof.json) 和 [057 截图](../20261013-kb-detail-load-state-orca/057-recovered-screen.png) 显示详情请求已恢复 200、14 条文档，侧栏仍为空。

Platform.vue 原 catch 清空 recentItems；模板未区分失败和成功空列表。现在最新请求失败仅设置固定文案“最近访问加载失败，请稍后重试”，保留同一 Platform 实例最近成功列表；首次失败也显示错误。“重试加载”使用原 API 路径，pending 时 button disabled，处理函数同时阻止重复调用。最新成功清除错误，成功空列表才显示空状态。保留原有 route/CRUD 刷新、排序、5 条上限、request generation/disposed 保护；不增加轮询或新通知。

仅新增局部 scoped 错误/重试样式、aria-live 与 aria-busy。无异常、URL 或凭据回显；Platform 实例卸载后不复用列表。

## 来源与完整差异

起始 HEAD：`98ce6b5a96afb5aad68beb9c51f4b0701d3944dc`。完整 before 保存在 [Platform.vue.before.txt](Platform.vue.before.txt) 和 [Platform.recent-sync.test.mjs.before.txt](Platform.recent-sync.test.mjs.before.txt)。差异从这两份副本到最终工作区生成，包含新增测试全文，不依赖未暂存 diff：[task-complete.diff](task-complete.diff)，SHA256 `00ab54a78e35775c8ae28a082f0e936e37581ef1fef018a2bb308ce63edaceb2`。

| 文件 | before SHA256 | after SHA256 |
| --- | --- | --- |
| Platform.vue | `46827813528834e5bdacd80c467c777e51b82c4d94e6612dfbd0d3371985901a` | `808282890044ef3aa36cdc1b7518449bc8aec48229e533defa1355b20d75a592` |
| Platform.recent-sync.test.mjs | `1429b448bb1fa452dd399ba2d7e658802101dfe9c7a6614a167a7da0e42aeede` | `3f660195823f166f83786b615f73fe0e9e958b45d689dd72a943a838c6377230` |
| Platform.recent-recovery.test.mjs | 新增，before 不存在 | `01673a1775c5302f7f76fc9b880c0e0bc047227cac5c0dd6ecf9e247b2978e58` |

机器记录：[before-source.json](before-source.json)、[after-source.json](after-source.json)。全过程未提交、未暂存、未修改 index；验证期间外部流程将部分本任务早期版本暂存，保留这些 index 状态并记录只读观察。

## 验证结果

| 检查 | 实际结果 | 完整记录 |
| --- | --- | --- |
| 原实现 RED，node --test 两份 Platform 测试 | actual 1，17/27 通过，10 失败 | [red-confirmed.log.txt](red-confirmed.log.txt)、[red-confirmed.exit](red-confirmed.exit) |
| 修改后同定向命令 GREEN | actual 0，27/27 通过 | [green.log.txt](green.log.txt)、[green.exit](green.exit) |
| frontend `npm run test:unit` | actual 0，422/422 通过 | [test-unit.log.txt](test-unit.log.txt)、[test-unit.exit](test-unit.exit) |
| frontend `npm run build` | actual 0，13.84s | [build.log.txt](build.log.txt)、[build.exit](build.exit) |
| `git diff --check`、完整 patch 重建、源码/证据 SHA、报告链接 | actual 0 | [final-checks.json](final-checks.json) |

RED 包含真实行为差异：已有两条成功结果失败后变成空列表；错误状态与重试入口缺失。首轮 [red.log.txt](red.log.txt) 另外发现 1024px 依据已有全局响应式 CSS 隐藏最近访问区；保持现有布局，改用侧栏实际可见的 1289×921、1440×900，重新获得 confirmed RED，未放宽命中断言或强制显示元素。

23 项 script/API 行为测试运行现有生产 API 与 Vue SFC，覆盖 CRUD 成功通知、失败通知抑制、旧请求/最新请求代次、晚成功/晚错误、真实空结果、重复 retry、卸载后失败、排序/条数/字段/名称回退。4 项隔离浏览器测试编译真实 SFC 与 scoped CSS，使用安装的 Vue/router/TDesign Dialog、真实 app/mobile CSS，仅控制 HTTP 客户端与 auth store；pointer/keyboard 真实事件调用 retry，pending 禁用，不使用 force 或 DOM.click。测试监听 pageerror，无未处理拒绝。

两种桌面宽度重试 button 的实际 rect 为 left 10、top 325、right 229、bottom 359；无父级裁切，中心命中真实 BUTTON。截图：[失败 1289](failure-1289.png)、[恢复 1289](recovered-1289.png)、[失败 1440](failure-1440.png)、[恢复 1440](recovered-1440.png)。构建仅有既有超过 500kB 的包体提示，无编译失败。

## 清理与边界

所有隔离 headless browser 均通过 finally 关闭；esbuild write:false，不创建虚拟构建目录或持久测试服务。未创建磁盘临时脚本，未读取 Root 私密 auth，未操作 Root 浏览器/QA 服务/数据。构建输出 frontend/dist 按既有 .gitignore 忽略，未暂存。日志改用 .log.txt 保留在证据目录，避免 *.log 忽略规则造成证据缺失。未更改依赖/锁文件、API/Core、KnowledgeDetail 或全局样式。

独立审查由只读 `/root/sidebar_network_recovery_fix/independent_review` 执行，[完整返回](INDEPENDENT-REVIEW.md) 判定无阻塞发现，并独立运行相同定向测试 actual 0、27/27；审查范围仅为代码与隔离 headless 检查。Root 真实复验应在正常 SPA 最近访问已有两条时造成自有后端传输故障，验证原列表/错误/真实命中按钮，然后恢复服务，通过侧栏“重试加载”确认真实读取成功并清除错误；首次失败、空成功由隔离回归覆盖，不操作用户数据。
