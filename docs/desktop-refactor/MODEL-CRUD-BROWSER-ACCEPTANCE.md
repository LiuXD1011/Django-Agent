# 当前核心的模型配置真实页面验收

2026-10-12 05:08（北京时间）。入口为 Orca 第 6 页签 `http://127.0.0.1:5173/platform/settings?section=models`，同一套 TypeScript 核心 PID245516；来源为 [当前取消任务冻结清单](../refactor-evidence/20261012-root-cancel-source-freeze.json)。数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`，专用账户 `orca-perf-qa-20261011`、空间 3，开始时无模型。全部业务写入通过实际表单、按钮、Tab/Enter 完成；数据库仅用于只读后置核对。

验收对象使用自定义 OpenAI 兼容厂商、对话角色、默认模型，名称 `orca-crud-fixture-20261012`，服务地址 `https://models-qa.example.invalid/v1`，以及临时生成的合成凭据。没有调用该地址，也没有使用真实厂商密钥完成清除或删除试验。合成凭据输入由私有工具包装处理，公共证据只有脱敏操作收据；密钥值没有进入截图、日志或报告。

| 操作 | 实际结果 | 证据 |
| --- | --- | --- |
| 添加并保存自定义模型 | 表单保存实际创建一条默认对话模型；页面显示 1 个可见、1 个已配置模型，凭据以 `enc:v1:` 加密存储 | [创建后置核对](../refactor-evidence/20261012-root-model-crud-created.json)、[1034 页面](../refactor-evidence/20261011-browser-model-page/1034-model-created-card.json) |
| 编辑名称，密钥留空保存 | 密钥输入为空且不回显；新名称持久化，页面仍显示已配置，数据库仍是有效加密凭据。保存会重新加密，因此不声称密文哈希不变；创建时未保留明文摘要，不把此步骤称为创建前后明文逐字比较 | [编辑后置核对](../refactor-evidence/20261012-root-model-crud-edited.json)、[1046 页面](../refactor-evidence/20261011-browser-model-page/1046-temporary-model-edited-card.json) |
| 修改 Base URL，密钥留空保存 | 表单保持打开，数据库保留旧地址；与编辑后基线比较，合成凭据明文摘要及密文摘要均未变化。随后取消编辑；短暂错误提示未被工具捕获，不声称核对了提示文字 | [拒绝后置核对](../refactor-evidence/20261012-root-model-crud-endpoint-rejected.json)、[1056 表单](../refactor-evidence/20261011-browser-model-page/1056-temporary-endpoint-save-result.json) |
| 清密钥先取消 | 键盘激活“取消”后弹窗关闭，模型及密钥保留；前一次鼠标点击没有关闭弹窗，不计入成功操作 | [保留核对](../refactor-evidence/20261012-root-model-crud-clear-cancelled.json)、[1067 关闭状态](../refactor-evidence/20261011-browser-model-page/1067-temporary-model-clear-cancel-poststate.json) |
| 清密钥再确认 | 实际移除合成密钥；页面已配置数由 1 变 0，清密钥按钮禁用，模型保留 | [清除核对](../refactor-evidence/20261012-root-model-crud-cleared.json)、[1078 页面](../refactor-evidence/20261011-browser-model-page/1078-model-cleared-card.json) |
| 删除模型先取消 | 关闭弹窗，模型仍保留且未软删 | [取消核对](../refactor-evidence/20261012-root-model-crud-delete-cancelled.json)、[1084 页面](../refactor-evidence/20261011-browser-model-page/1084-model-delete-cancelled-card.json) |
| 删除模型再确认 | 实际软删，专用空间可见模型恢复为 0，临时凭据已清除；不宣称软删行从数据库物理消失 | [删除核对](../refactor-evidence/20261012-root-model-crud-deleted.json)、[1090 空状态](../refactor-evidence/20261011-browser-model-page/1090-model-crud-final-empty-snapshot.json) |
| 长表单滚动与空密钥校验 | 1289×659 视口中展开高级表单，最初保存按钮位于视口下方；聚焦可见描述框后 PageDown 将弹窗滚动 163px，保存按钮到 y520.39。实际点击可见保存按钮时，空密钥表单保留；随后点击可见取消按钮正常关闭。没有捕获短暂提示文字，也未将工具耗时当作产品延迟 | [1098 滚动几何](../refactor-evidence/20261011-browser-model-page/1098-model-long-form-keyboard-scroll-geometry.json)、[1100 保存点击](../refactor-evidence/20261011-browser-model-page/1100-visible-model-missing-key-save-click.json)、[1101 留空状态](../refactor-evidence/20261011-browser-model-page/1101-visible-model-missing-key-poststate.json)、[1103 取消关闭](../refactor-evidence/20261011-browser-model-page/1103-empty-model-form-cancelled.json) |

每次数据库后置核对都验证原空间中四个真实模型的完整行摘要及 `.secrets/credentials.key` 哈希不变。全局调用记录一直为 101，本轮 CRUD 新增厂商请求为 0。[开始基线](../refactor-evidence/20261012-root-model-crud-before.json)与[结束核对](../refactor-evidence/20261012-root-model-crud-deleted.json)保留具体摘要；[临时核对脚本清理](../refactor-evidence/20261012-root-model-crud-audit-cleanup.json)记录删除事实。

视口外鼠标点击被 Orca 报为成功但没有业务效果的尝试均保留在原始步骤中，不计入通过。真实生效的操作另有表单关闭、页面变更及数据库核对。上述记录补齐自定义对话模型及清除/删除确认子项，不能代替所有厂商/角色、新地址加新密钥、内置模型、思考保存、Windows 最终安装版及整组 I-03 验收。

同一来源的 Windows 新包已通过 [root 独立文件审计](../refactor-evidence/20261012-root-cancel-windows-independent-audit.json)：37 份构建证据、350 个来源输入、435 个编译产物全部匹配；installer 为 401,834,288 字节，SHA256 `633a2efe7e8cc1115be94cfc0a675882e4ebb3872a50afb7e62f6a5617c8ad6c`。桌面版本 0.6.2、核心版本 0.7.0；此审计不表示已经安装或完成安装后的业务页面验收。
