# 本地MCP真实页面与Agent验收

2026-10-12，Goal仍active。根代理已准备官方SDK的loopback计算服务并独立[记录计划](MCP-REAL-AGENT-TEST-PLAN.md)。本代理只负责Orca独立page6 `22e0e212-30aa-4945-8a3d-7176cdfffdff`业务GUI与browser子目录证据，不改产品/根协议服务/主报告。

服务`http://127.0.0.1:44842/mcp`及固定API Key均为专用合成fixture，非用户模型凭据；唯一工具`qa_purchase_total`输入quantity12/unit_price79，预期948及新的唯一服务回执。根setup用回执`:1`，不能当本轮GUI或Agent成功。

先通过真实设置新增自己的服务、编辑名称Key留空、禁用/启用并在Chat发现工具，0模型。只有服务正常/四真实模型与vault保护/0活动任务满足后，根明确授权一次已有GLM Agent回合：显式空KB、联网关闭，仅此MCP，最多8新增用量行/10分钟，不重放失败或unknown，不以GLM自行乘法当工具执行。结果须实际轨迹、server tools/call、最终回答、后台任务/维护/账本核对。随后真实页面删除自有服务，原服务/评测/知识数据保留；这段不替代正式安装IPC或联网搜索缺口。

以下按实际证据追加，不预填完成。

第一段新建成功后遇到已配置凭据的编辑400，已[独立冻结真实失败](MCP-EDIT-PROJECTION-BROWSER-FAILURE.md)，暂缓其他保存与付费回合。根代理协调前端修复；原服务保留，usage162/0任务，修复后再继续此文档。

后续判定严格区分：设置card的enabled是保存配置，Chat中的服务option只表示live行可选，没有连接/工具schema已验证的含义。当前Chat资源加载未按enabled过滤，popover显示通用status=active；实际core MCP disabled会返回state=disabled/tools=[]。因此不能将禁用记录仍可选当工具实际可用，也不能将创建/开关保存成功当握手成功。GUI目前无独立tools/list入口，服务握手、真实工具发现与工具调用须由唯一授权Agent回合和服务器日志证实；根SDKsetup仅服务自检。

## 修复后实际配置与清理

前端修复由根代理及独立实现代理负责，原400与P1冻结不覆盖。实现代理[源码冻结与验证](../refactor-evidence/20261012-web-search-provider-ui-implementation/freeze.json)记录真实父组件回归、相关28/28、全前端360/360及生产build退出0。这些自动检查不替代以下GUI。修复后仍使用原服务e13171b1-5ca7-4622-b579-cc07c5247f1b，未重复新建。

真实表单[名称修改、Key留空保存](../refactor-evidence/20261012-mcp-real-agent/browser/047-mcp-retest-name-blank-key-actual-save.json)后[card和dialog状态](../refactor-evidence/20261012-mcp-real-agent/browser/048-mcp-name-edited-green-snapshot.json)正确，[后置只读记录](../refactor-evidence/20261012-mcp-real-agent/browser/049-mcp-name-edited-green-readonly.json)显示新名称和已加密凭据字段。随后实际[禁用保存](../refactor-evidence/20261012-mcp-real-agent/browser/054-mcp-disable-save.json)与[读回disabled](../refactor-evidence/20261012-mcp-real-agent/browser/056-mcp-disabled-readonly.json)，再[启用保存](../refactor-evidence/20261012-mcp-real-agent/browser/061-mcp-enable-save.json)及[读回enabled](../refactor-evidence/20261012-mcp-real-agent/browser/063-mcp-enabled-before-chat-protection-readonly.json)。三次Key都留空，usage162没有增长。此时只能证明配置保存；后述服务器认证成功再证明留空保留的密钥可以使用，未解密比较明文，也不声称每次随机加密后的ciphertext相同。

聊天页通过[实际选择自有服务](../refactor-evidence/20261012-mcp-real-agent/browser/068-mcp-chat-own-service-select.json)显示唯一选中chip，知识库[0已选](../refactor-evidence/20261012-mcp-real-agent/browser/071-mcp-chat-empty-kb-picker-snapshot.json)明确本轮不检索。发送前[只读DOM](../refactor-evidence/20261012-mcp-real-agent/browser/074-mcp-only-tool-before-send-dom.json)和[保护记录](../refactor-evidence/20261012-mcp-real-agent/browser/075-mcp-only-tool-prepaid-protection-readonly.json)核对GLM、联网未启用、usage162、0活动任务；01:38:16.786UTC只有[一次实际发送](../refactor-evidence/20261012-mcp-real-agent/browser/076-mcp-single-authorized-agent-send.json)，没有失败重放。

结束后针对唯一自有服务实际[删除取消](../refactor-evidence/20261012-mcp-real-agent/browser/099-mcp-delete-cancel.json)，[100只读记录](../refactor-evidence/20261012-mcp-real-agent/browser/100-mcp-delete-cancel-protection-readonly.json)全行SHA与075一致；再次打开精确名称确认框后[确认删除](../refactor-evidence/20261012-mcp-real-agent/browser/104-mcp-delete-confirm.json)，[105只读记录](../refactor-evidence/20261012-mcp-real-agent/browser/105-mcp-deleted-final-protection-readonly.json)仅该行soft-delete时间01:46:25.824UTC，[真实列表空态](../refactor-evidence/20261012-mcp-real-agent/browser/106-mcp-deleted-list-empty-snapshot.json)与[107DOM](../refactor-evidence/20261012-mcp-real-agent/browser/107-mcp-cleanup-final-requests-dom.json)没有遗留弹窗。原先已软删的b0134fd6服务行SHA全程相同。没有清除真实用户密钥，soft-delete保留加密字段属于现有契约。自己的聊天会话保留用于审计；GUI于01:47UTC后明确释放给根代理，未自行停核心或SDK。

## 唯一真实Agent回合

会话3c0d3ccd-3b6d-4e05-9908-e25b09d6dc28、请求23a4e5b6-78a2-410b-b3ce-5fd3f5b58b12。[运行中页面](../refactor-evidence/20261012-mcp-real-agent/browser/077-mcp-agent-started-snapshot.json)实际显示停止按钮，后续[完成页面](../refactor-evidence/20261012-mcp-real-agent/browser/079-mcp-agent-progress-result-snapshot.json)回答948及完整新回执`62243c11-8d31-4df1-b4ff-9f411d5635ba:2`。[轨迹](../refactor-evidence/20261012-mcp-real-agent/browser/083-mcp-agent-trajectory-snapshot.json)有真实MCP工具70ms、两次Agent迭代及维护结果；[滚动后实际展开schema](../refactor-evidence/20261012-mcp-real-agent/browser/087-mcp-agent-tool-schema-visible-click.json)与[DOM](../refactor-evidence/20261012-mcp-real-agent/browser/088-mcp-agent-tool-schema-visible-dom.json)显示quantity、unit_price整数必填。[实际截图](../refactor-evidence/20261012-mcp-real-agent/browser/089-mcp-agent-trajectory-render-screenshot.png)已查看；图片只覆盖可见片段，其他维护状态以轨迹snapshot为准。

[090持久化及协议快照](../refactor-evidence/20261012-mcp-real-agent/browser/090-mcp-turn-actual-ledger-and-protocol-readonly.json)和清理后的[108终态](../refactor-evidence/20261012-mcp-real-agent/browser/108-mcp-turn-final-readonly.json)关联如下：

| 项目 | 实际证据 |
| --- | --- |
| 来源范围 | session配置KB=[]且selection_explicit=true，联网false，仅e131 MCP；保留原enable_memory=true |
| 真实服务交互 | 13条setupSmoke=false协议事件；tools/list一次、tools/call一次；所有protocol_request认证matched=true |
| 工具结果 | qa_purchase_total(12,79)实际subtotal948，新receipt实例`:2`，与setup`:1`不同；持久化tool/result和最终回答一致 |
| 模型用量 | memory_keywords138、agent_chat1239、agent_chat1375、memory_extraction601；4条成功、request_count均1、唯一model_call_id，总3353tokens=2761输入+592输出，reasoning166 |
| 任务终态 | chat.turn与chat.maintenance各attempt1、completed、progress1、无错误，0活动任务；2messages、18session_events |
| 维护警告 | 本地记忆已保存，远程图谱无权限的memory_graph_permission_denied明确保留；未知记忆检索结果没有伪标完成 |

usage162→166，小于授权8次。正式回答任务01:38:21.121→01:38:39.858，实际18.737秒，assistant元数据18705ms，GUI18.7秒；维护01:38:39.831→01:38:44.506实际4.675秒，与主任务尾部有27ms重叠，不能简单相加为独占耗时。此处是一次样本，根全套/构建同时运行，不报告P95。MCP70ms为应用实际tool duration。107 ResourceTiming记录清理DELETE200/329.2ms，随后列表200/1834.8ms；名称成功PUT的timing在导航后已丢失，没有补造。旧400/316.2ms属于保留失败段。Orca工具等待时长不充当业务延迟。

注意聊天ModelCaller实际写4条model_usage并关联model_call_id，未使用评测的独立预调用ledger，不能把它描述为4条评测invocation完成。raw tool/call公开arguments被现有投影脱敏为空；参数实值由持久化Agent步骤、可见轨迹及服务日志共同验证。请求header允许若干内置工具，并非配置层关闭它们；此次实际唯一tool/call是MCP，没有其他工具执行。

## 保护、检查与范围

075→105四个真实模型完整行SHA、vault key SHA、原2知识库、gold2文档/13块、原13Wiki、三个测试集全部exact相同，usage增量仅本回合4条；原MCP历史记录SHA未变。108保存结束时全库计数，包含软删行，不将总models5误称当前空间配置5个（本空间仍4个）。最终[证据冻结与检查](../refactor-evidence/20261012-mcp-real-agent/browser/freeze.json)绑定本报告、截图、实际协议快照及全部browser历史，记录链接/diff检查、临时脚本归档哈希和移除；SDK的根日志仍由根代理管理，未冻结正在变化的原文件。

首个新增按钮和schema按钮的视口外点击虽然工具回执ok，却没有改变页面；原回执保留，只有后来滚动后实际点击算通过。conversation原生disclosure没有独立展开，不能声称全部工具详情子入口已测试。此验收覆盖受控官方SDK、浏览器HTTP、真实GLM工具发现/调用、维护、MCP配置CRUD及自有清理；不覆盖任意外部MCP厂商、禁用后Agent零调用端到端、Windows安装IPC、联网搜索、所有页面或Goal完成。
