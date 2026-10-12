# 联网搜索配置真实页面缺口

2026-10-12，Goal仍active。本轮在Orca page6 `22e0e212-30aa-4945-8a3d-7176cdfffdff`实际账户按钮进入设置、滚到并点击联网搜索；仅观察，不切开关、不保存、不调用搜索/模型、不修改代码。核心仍1464221，与已冻结中文检索/五题Ragas同实例；Windows clean builder后台运行，GUI独占归本代理。

[05真实页面快照](../refactor-evidence/20261012-web-search-config-browser/005-web-search-visible-snapshot.json)显示duckduckgo/bing/google/searxng四个Provider类型卡片，下面只有“允许联网搜索”（未勾选）、备注和“保存配置”。[06实际DOM](../refactor-evidence/20261012-web-search-config-browser/006-web-search-config-controls-dom.json)完整当前settings-content按钮只有Save，inputs只有checkbox和textarea，没有创建/选定Provider、URL、API Key、编辑/删除或连接测试入口。不存在一个被遗漏的可见配置按钮。

[07一致只读SQLite](../refactor-evidence/20261012-web-search-config-browser/007-web-provider-counts-readonly.json)当前tenant2实际`web_search_providers`活跃和未删除数均0、MCP数0、usage162、0活动任务，只输出计数，不输出provider配置或凭据。该结果不表示四个类型卡片是四个已配置服务，也不表示保存enabled即可连接。

完整阅读实际Settings.vue后，`load()`第328–365行只请求`webSearchProviderTypes()`，第820–835行仅上述静态类型与tenantKV；`frontend/src/api/index.ts:290`仅type读取，无网页搜索Provider CRUD方法；当前router没有另一个搜索配置页面。核心`packages/core/src/adapters/settings-routes.ts:51`已有真实Provider CRUD、credential与test路由，`packages/core/src/agents/tools.ts:127`从本tenant的活跃generic Provider取首个，0条时返回unavailable。这里是前端可配置用户路径缺失；没有触发工具调用，不把代码推导的unavailable冒充本轮真实Agent回合结果。

最小后续方向是由根代理在现有联网搜索分区接已有受权限Provider列表/新增/编辑/禁用/删除及凭据保留/清除和显式连接测试；Provider实际可用状态需要真实适配器结果，不能用enabled保存替代。此次仅上报证据、没有实现或联网请求。四类型读取200/1988.7ms和KV读取200/325.1ms只是n=1应用ResourceTiming、并行设置加载与Windows构建条件，不构成外部搜索延迟或P95。

附带B/F清理后的缓存观察：[02设置快照](../refactor-evidence/20261012-web-search-config-browser/002-settings-account-current-snapshot.json)最近访问已只剩原两库，先前KB列表删除完成后短暂旧自建按钮在正常导航后消失；不据此新增产品补丁。B/F已独立在[空库/Wiki验收](GENERAL-PAGE-BROWSER-ACCEPTANCE.md)冻结，此处不改其证据。

I真实可配置搜索和外部连通尚未通过；后续MCP用独立本地服务测试，不替代此缺口，不标全页/安装版或Goal完成。
