# 大文档分块的未保存编辑验收

2026-10-12 使用 Orca 页面 `4fc18a4f-051f-4326-bffd-878f8150d912`，真实数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`，界面版本 0.7.0。目标为格式验收库中的 `14 大文本 40000行.txt`，document id `bb50917d-ed78-47a4-8dc4-921ac502dc4c`，共 11,429 块，其中正文 10,000 块。没有保存、删除、重解析该文件或调用模型。

真实打开分块详情并选择正文，第一页显示 50 块、200 页。在首块输入专用未保存草稿。将页码滚到可见后点击第二页，页面仍为第一页、草稿保持；点击关闭详情，抽屉仍打开、草稿保持。原始操作分别见 [分页前可见性](../refactor-evidence/20261011-browser-model-page/1220-visible-pagination-position.json)、[页码点击](../refactor-evidence/20261011-browser-model-page/1222-click-visible-page-two-unsaved.json)、[页码点击结果](../refactor-evidence/20261011-browser-model-page/1223-dirty-page-two-protected-dom.json)、[关闭操作](../refactor-evidence/20261011-browser-model-page/1225-click-close-dirty-chunks.json) 与 [关闭结果](../refactor-evidence/20261011-browser-model-page/1226-close-unsaved-retains-draft-dom.json)。

补充类型切换采用新鲜 snapshot：当前 Orca 页面可见，草稿存在。实际点击筛选输入，随后 snapshot 显示 `全部类型` 为 `@e15`，再点击该选项。[结果](../refactor-evidence/20261011-browser-model-page/1243-unsaved-filter-protection-result.json) 中正文筛选、10,000 条计数和原草稿均保持，抽屉仍打开；三条实际 `/api/v1/chunks/` Resource Timing 记录与之前一致，没有新的分块请求。见 [类型选项](../refactor-evidence/20261011-browser-model-page/1241-unsaved-filter-current-options.json)、[实际选择](../refactor-evidence/20261011-browser-model-page/1242-select-all-types-with-unsaved-draft.json)。早期 1238 使用了错误的 URL 过滤片段，空数组不作为无请求证据；1240/1243 已按实际路径核对。未抓到短暂警告的画面，因此不宣称警告展示已验证。

最后主动刷新丢弃这条验收草稿，未点击保存。22:48:43Z 刷新后进入登录页，抽屉与草稿标记消失；不能据此声称登录恢复或刷新后路由保持已通过。后续后台诊断确认核心在 22:45:26Z 记录 application.stopping，原进程已退出、8000 无监听，只有 Vite 5173，刷新发生于此服务中断之后。关闭原因尚未查明，现有证据不足以判定认证缺陷。见 [真实刷新](../refactor-evidence/20261011-browser-model-page/1245-discard-only-owned-unsaved-draft-by-reload.json)、[刷新结果](../refactor-evidence/20261011-browser-model-page/1246-owned-unsaved-draft-cleared-after-reload.json) 和 [后续服务诊断](../refactor-evidence/20261012-browser-core-recovery/before.json)。

SQL 使用只读连接与一致性事务，比较完整 document row、全部 chunk rows 和 FTS 内容：[之前](../refactor-evidence/20261012-root-chunk-unsaved-before.json)、[之后](../refactor-evidence/20261012-root-chunk-unsaved-after.json) 完全一致。document SHA `27e5f1d33e83772642f43bd61942ef76e2547719ffe1d48296514c50593468bf`；11,429 块 SHA `e2d4d82db93d985925cf5c1785d3e9b33044d5c41c67830909d222d03d502235`；10,000 条 FTS SHA `e5a4b0f41f611e14f7f6f405bd623757db80e1675676b58bc2b4a820bc773166`。测试标记在数据库中为零。

这些单次真实操作覆盖未保存编辑的分页、关闭和类型切换保护；不代替分块保存、删除、完整文档入库或正式安装链路验收。按钮初次点击时位于视口外、错误 ref `@e14`、Orca 残留原生确认框均属于工具操作问题，未计入产品失败或通过。无 P95 推断。
