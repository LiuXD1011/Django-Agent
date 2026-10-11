# 真实五题召回缺陷修复

2026-10-11，R-VECTOR-METADATA。五题实际评测完成，但四题未取到手册证据。私有副本中10个可检索分块只有3个符合当前向量指纹；真实SQLite回归证明仅更新摘要、Wiki及处理状态就使正文未变的向量消失。

采用嵌入正文与来源身份的明确指纹：保留分块/文档/空间身份、精确seq_id、类型、位置、父关系、模型绑定、来源代次和实际embedding输入。摘要、显示名称、流程状态及时间等非嵌入输入不参与指纹。继续通过实时权限、启停、删除过滤及来源变更围栏拒绝失效内容。

不采用每次更新摘要都重新付费嵌入的方案，也不接受忽略全部指纹的方案。检索前核对当前分块与已存指纹，发现失效时返回vector_reindex_required，避免无用的付费query embedding。新规则下既有旧格式指纹仍需正常重建索引；不改写旧评测报告，不自动重复未知请求。

执行顺序：保存实际低分与只读诊断；隔离SQLite先复现RED；增加永久回归并修改指纹；运行相关检索与文档测试及类型检查；通过现有知识库页面的重解析在独立验收库重建，核对全部可用向量和真实问答；修复完成后重新正式构建与安装验收。

实际复测：Orca点击手册重解析一次，任务正常结束；只读核对7个可检索分块全部有有效向量，摘要、处理状态等更新后仍保持ready，无运行任务。该次问题生成另有model_output_invalid，按独立辅助策略缺陷继续处理，不将全流程记为通过。[索引实际核对](../refactor-evidence/20261011-browser-model-page/126-root-index-after-reparse.json)。

证据：[五题原始归档](../refactor-evidence/20261011-root-five-gold-integrated/archive.json)、[逐题答案](../refactor-evidence/20261011-root-five-gold-integrated/row-inspection.json)、[向量指纹诊断](../refactor-evidence/20261011-root-five-gold-integrated/vector-fingerprint-inspection.json)。
