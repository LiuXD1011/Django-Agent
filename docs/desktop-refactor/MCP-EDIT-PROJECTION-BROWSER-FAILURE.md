# MCP已配置凭据的编辑400真实发现

2026-10-12，Orca page6 `22e0e212-30aa-4945-8a3d-7176cdfffdff`，专用tenant2。根代理已准备本地官方SDK fixture；本段仅设置UI，没有启动模型/Agent或调用工具，不把SDK服务自检当GUI发现。

[15实际Save](../refactor-evidence/20261012-mcp-real-agent/browser/015-mcp-create-actual-save.json)创建本地服务`e13171b1-5ca7-4622-b579-cc07c5247f1b`，[16快照](../refactor-evidence/20261012-mcp-real-agent/browser/016-mcp-created-current-snapshot.json)正确名称/描述/已启用并捕获“MCP 服务已保存”。首次Add click未打开弹窗，随后显式scroll再实际click打开，不能将第一次回执当成功；Create的Save已在[14可见DOM](../refactor-evidence/20261012-mcp-real-agent/browser/014-mcp-create-visible-dom.json)证实y273.6/height32/viewport518。固定Key仅合成fixture，不是用户Key。

打开编辑后只修改名称，Key保持空；[24唯一保存](../refactor-evidence/20261012-mcp-real-agent/browser/024-mcp-edited-key-blank-save.json)确实发起请求。[25编辑框仍开](../refactor-evidence/20261012-mcp-real-agent/browser/025-mcp-edited-snapshot.json)，[26 ResourceTiming](../refactor-evidence/20261012-mcp-real-agent/browser/026-mcp-edit-first-click-network-dom.json)对应PUT URL实际400/316.2ms，Save可见enabled；[27只读](../refactor-evidence/20261012-mcp-real-agent/browser/027-mcp-edit-first-click-readonly.json)持久名称仍旧、Key字段仍在。没有更换地址、没有重复Save；实际Cancel关闭后保留原有效新增记录，暂缓disable/enable和真实付费回合。

完整阅读源码定位：`frontend/src/views/Settings.vue:506`的editMcpService使用`{...service,api_key:''}`，Save第518行又spread整个form。核心SettingsService.providerProjection返回`credential_fields:{api_key:{configured:true}}`这类公共状态元数据；updateProvider调用settings/internal.ts的merge递归该树，遇到作为secret名称的api_key对象，触发“非string credential”400。这是GET投影误当写入payload，不是旧密钥缺失或endpoint更换。本轮没有读响应错误body，具体invalid_credential code是源码路径推导；真实网络只证实400，短错误toast未捕获，不冒充其文字验证。

最小修复是明确编辑form仅id/name/description/url/enabled/API Key输入，并明确提交允许字段；空Key省略，维持后端原保留语义，不返传credential_fields、credentials_configured、tenant/timestamps等只读元数据。根代理已交独立前端代理按真实protected DTO DOM RED/GREEN修复，本代理不改产品文件。

[34修复前保护](../refactor-evidence/20261012-mcp-real-agent/browser/034-mcp-p1-protected-before-fix-readonly.json)记录新建行SHA `8bcc74985363112cba296395dcddf07ce689e6b8f8afb08a536cdcd651fc46f2`、type=mcp_services、Key存储有enc:v1前缀但不输出内容。历史已删除MCP行SHA `4887e8d205791bcc9c19cd63ac7249233aba68c0e224a5745894016f4b94dcd7`作为后续保护。四模型完整行SHA `13479f65d09d6fe411e46e403e7bccd134970d48f8a67a41d14ca7f24a0946f4`、vault keySHA `1dfc55e984d6f848395d93ac327ce9c6f5fbcfd997bcf89b9fd2d96c9d2238f5`、原两个KB/gold两文档13块/原13Wiki/三个评测集保持General最终精确相同；usage162/0活动任务。17初始只读helper误用不存在payload列，核真实generic_resources.data后21/27/34才是有效断言，失败脚本保留不算产品RED。

实际Chat导航首先打开既有受保护会话，只读取且不更改草稿/发送，马上实际“新对话”进入creatChat。[35](../refactor-evidence/20261012-mcp-real-agent/browser/035-mcp-p1-prepaid-controls-network-dom.json)draft空、Send disabled、web按钮没有active、KB无chip、GLM可见、MCP选择按钮可见。没有0模型工具schema发现入口；Chat只列服务，真实initialize/tools/list在Agent开始时发生，修复后唯一有界回合再测。回合未启动，原≤8新增usage/10分钟授权保留。

最近应用请求：Create因正常access过期先401/317.8ms，refresh后200/263.7ms；随后的服务清单加载1673.9ms，Chat资源列表13.8ms。以上是n=1与Windows后台构建负载条件，Orca4–7秒回执不是业务延迟，不推导P95/外部MCP时延。

本P1发现段单独冻结，server日志仍由根代理持有并继续写入。后续修复与真实工具调用写[独立续验](MCP-REAL-AGENT-BROWSER.md)，不得覆盖400或将未执行项填通过。
