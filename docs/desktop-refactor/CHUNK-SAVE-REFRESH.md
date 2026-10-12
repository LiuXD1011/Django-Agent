# 保存分块后的详情刷新

## 已确认问题与范围

Orca 在专用无模型空间编辑正文并禁用最后一个子块后，服务端清理了不再有有效子块的父块，关键词索引也已同步清理。但抽屉仍显示两条及旧父块关系，关闭再打开才显示实际一条。真实步骤为 `747–756`，只读结果见 [禁用后状态](../refactor-evidence/20261011-root-gui-chunk-disabled.json)。

`KnowledgeDetail.vue` 的 `saveChunk` 仅调用更新接口、清除脏标记并刷新知识库统计/文档列表，没有重新读取当前分块页。现有 `loadChunksForDoc` 已有知识库、文档、引用代际与未保存内容检查，可以直接复用。

## 方案

采用服务端重新读取当前分块页的方案，保留当前页与类型筛选。只在保存完成后仍是同一知识库、文档和引用代际，并且当前没有未保存编辑时读取；服务端总数、父块关系和内容一起更新。其它分块或请求期间新输入尚未保存时，保留编辑，最后一次保存完成再刷新。引用单块模式沿用其现有显示，不强制切为整页。

手工预测父块清理容易偏离核心的关系规则；每次保存无条件覆盖整页则会丢失其它编辑，因此都不采用。保存失败继续抛出原错误并保留脏标记。只改变详情刷新，不改后端启停、父块清理或关键词发布语义。

本次设计与执行已由 Goal 第二节第3、4项授权；不提交、不等待重复批准、不覆盖无关改动。

## 实施与验收

- [x] 在现有编译 Vue setup 行为测试中复现：禁用最后一个子块后总数与父块关系未更新；保存期间新编辑不能误清脏状态。
- [x] 保留同页其它脏分块、更新失败和页码/类型筛选检查。
- [x] 在 `saveChunk` 捕获文档、知识库、代际和提交值；确认当前状态后清除真正已保存的脏标记，条件满足时调用现有 `loadChunksForDoc`。
- [x] 执行定向 RED/GREEN、`frontend npm run test:unit` 与构建，绑定当前源码及原始日志。
- [ ] Orca 对专用短文档再次禁用并保存，直接核对抽屉总数、父块关系、重新启用与索引，不通过关闭重开掩盖问题。安装版另验。

当前状态：3项目标失败已实际观察，[RED](../refactor-evidence/20261011-root-chunk-save-refresh-red.tap) 后 [21/21 GREEN](../refactor-evidence/20261011-root-chunk-save-refresh-green.tap)；完整前端338/338、0失败/取消/跳过，构建exit0，109份已列输入前后SHA一致。[命令与原始日志](../refactor-evidence/20261011-root-chunk-save-refresh-checks/result.json)。单元API使用明确替身，不计真实业务通过。

Orca 817–831 在同一打开的短文档抽屉中禁用并保存，直接显示2→1、1个编辑块、0旧父关系；再启用并保存仍1条。真实业务成功PUT分别47.9/33.3ms，重新读页11.6/12.4ms；首次遇自然access到期后正常refresh，不重放第二次成功业务请求。只读SQLite核对禁用FTS0、重新启用FTS1，精确64位rowid保留、模型SHA不变、全局usage101/本空间0。稳定截图实际查看，抽屉内容及按钮可见。[综合步骤与源码](../refactor-evidence/20261011-root-chunk-counts-labels-real.json)、[禁用后](../refactor-evidence/20261011-root-chunk-fixed-disabled-real.json)、[启用后](../refactor-evidence/20261011-root-chunk-fixed-reenabled-real.json)。安装版和模型问答仍待独立验收，故最后一项未整体勾选。
