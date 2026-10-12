# 知识库列表续验（2026-10-12）

本轮使用 Orca 的源代码浏览器页面 `22e0e212-30aa-4945-8a3d-7176cdfffdff`，访问 `http://localhost:5173/platform/knowledge-bases`，后端为已有的独立验收目录 `20261010-browser-qa`。只操作测试账号在本轮新建的两个空库；没有改动原管理员密码、原有模型配置或既有文档。本轮不是安装版点击验收，不能据此把 B 组整体标为通过。

两个对象分别为 `e58bb317-bc0f-45ba-819f-90faae0afb2f`（`Orca 列表续验 20261012`）与 `c897759a-fbe8-4b80-b9be-a339ec56da32`（同名加 ` copy`）。对象和保护资料在 [开始核对](../refactor-evidence/20261012-root-kb-list-followup/before-readonly-db.json)、[创建后核对](../refactor-evidence/20261012-root-kb-list-followup/created-readonly-db.json)、[复制后核对](../refactor-evidence/20261012-root-kb-list-followup/copied-readonly-db.json)及[刷新后核对](../refactor-evidence/20261012-root-kb-list-followup/reloaded-readonly-db.json)中绑定。

| 子项 | 实际结果与证据 | 验证边界 |
| --- | --- | --- |
| 创建、置顶、收藏、复制、刷新 | 前序页面操作与只读核对保存于本轮证据目录；复制生成独立空库，刷新后仍有两个对象。 | 不含非空库关联复制、全部配置字段逐项比对、重启恢复。 |
| 按完整名称搜索 | [恢复会话后的搜索值](../refactor-evidence/20261012-root-kb-list-followup/057-restored-search-dom-refresh.json)与[唯一匹配结果](../refactor-evidence/20261012-root-kb-list-followup/058-restored-search-poststate.json)一致，只返回 `… copy`。 | 使用 Orca eval 中标准 DOM `button.click()`；没有调用 Vue 业务函数或直接调用后端接口。普通鼠标点击未确认交付，不计作点击通过。 |
| 删除取消 | [打开删除确认](../refactor-evidence/20261012-root-kb-list-followup/060-copy-delete-confirmation.json)、[取消](../refactor-evidence/20261012-root-kb-list-followup/061-copy-delete-dom-cancel.json)后，[目标清空且空库保留](../refactor-evidence/20261012-root-kb-list-followup/062-delete-cancel-preserved-readonly.json)。 | 同为标准 DOM 按钮触发，仅限本轮复制的空库。 |
| 删除确认 | [复制空库确认删除](../refactor-evidence/20261012-root-kb-list-followup/064-copy-delete-dom-confirm.json)后[搜索为空](../refactor-evidence/20261012-root-kb-list-followup/065-copy-deleted-empty-result.json)；[原始空库确认删除](../refactor-evidence/20261012-root-kb-list-followup/075-own-original-delete-dom-confirm.json)后，[页面恢复为既有两库、16 条目、10027 摘录](../refactor-evidence/20261012-root-kb-list-followup/077-cleanup-current-readonly.json)。 | 未删除既有资料；不含非空库关联删除验证。 |
| 取消置顶、收藏为空 | [取消置顶](../refactor-evidence/20261012-root-kb-list-followup/070-own-original-dom-unpin.json)后，[前置状态核对并切换收藏](../refactor-evidence/20261012-root-kb-list-followup/071-unpinned-favorite-filter-dom-activation.json)，[收藏范围为空](../refactor-evidence/20261012-root-kb-list-followup/072-empty-favorites-readonly.json)。 | 不含“最近”“本空间”或类型筛选的全部分支。 |
| 清理与资料保护 | [最终只读核对](../refactor-evidence/20261012-root-kb-list-followup/cleaned-readonly-db.json)确认两个空库均已软删除且未置顶，受保护表与凭据、设置、媒体文件摘要完全一致，模型用量记录仍为 174。 | 保护表范围以核对文件为准；认证会话表不在该保护清单中，正常登录可创建测试账号会话。 |

普通 CLI `click`/`keypress` 多次返回成功，但输入未清除、页面未变化且没有搜索请求。这些回执保留，不能作为业务成功证据。只读 [输入与 Vue 状态](../refactor-evidence/20261012-root-kb-list-followup/038-list-state-readonly.json)、[刷新前请求观察](../refactor-evidence/20261012-root-kb-list-followup/039-safe-load-state-readonly.json)和[切换聚焦后观察](../refactor-evidence/20261012-root-kb-list-followup/045-unprefixed-ref-readonly.json)显示搜索值存在，但没有相应请求。

随后[标准 DOM 刷新触发](../refactor-evidence/20261012-root-kb-list-followup/046-dom-refresh-activation.json)使页面[转到登录页](../refactor-evidence/20261012-root-kb-list-followup/048-dom-after-route-readonly.json)。使用已有独立测试账号在正常登录表单恢复会话，密码填入操作仅保存[脱敏回执](../refactor-evidence/20261012-root-kb-list-followup/051-qa-secret-fill-redacted.json)，[正常表单按钮触发](../refactor-evidence/20261012-root-kb-list-followup/052-normal-login-dom-activation.json)后，[只读请求观察](../refactor-evidence/20261012-root-kb-list-followup/054-auth-safe-request-observation.json)确认登录请求返回 200，浏览器回到知识库页面。没有重置账号或跳过认证。现有证据不足以把这次现象归因为搜索逻辑故障，普通点击交付和会话续期仍需独立验收。

失败与过渡观察未覆盖：`027` 的 `--ref` 参数错误、`031` 空值不被 CLI 接受、`076` 在删除后页面尚未稳定时断言失败，分别保留原退出码 1。`077` 随后只读确认稳定结果，未重放删除。`047`、`067` 的空页面快照亦保留，未据此判定产品空白页故障。工具耗时、未稳定的快照和 DOM 操作不作为产品延迟或 P95。

[临时脚本清理回执](../refactor-evidence/20261012-root-kb-list-followup/cleanup.json)确认本轮四份已消费脚本逐一归档、核对摘要后从 `/tmp` 删除；归档的是最终消费版本，已有私有凭据文件保留。B 组仍为部分验证：待真实鼠标点击、其他筛选分支、编辑、相似名称、重启恢复及非空库关联行为。
