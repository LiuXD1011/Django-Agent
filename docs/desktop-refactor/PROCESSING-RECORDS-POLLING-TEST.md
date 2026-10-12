# 解析记录轮询测试的时钟修复

新39feca…Windows clean prepare真实346/347，在解析记录活动轮询测试失败，完整[失败收据](../refactor-evidence/20261012-integrated-chinese-query-windows-build/prepare-execution.json)保留。该测试Node等待2100ms后立即读取Node的route计数，生产轨迹在浏览器每2000ms轮询；100ms余量没有保证Chrome定时器及跨进程请求已到Node。原日志没有调度时间戳，不能还原当时具体迟到原因。根代理另跑旧Windows单文件[5/5对照](../refactor-evidence/20261012-processing-poll-windows-diagnostic/execution.json)，不抹原失败或称已定位具体Windows调度轨迹。

先完整读取实际test/fixture、TraceTimeline轮询和parent状态刷新/代次逻辑、已有受控父轮询测试，核已安装Playwright1.61.1的Clock install/pauseAt/runFor类型与request/response API。用原真实编译DOM夹具的/tmp副本，只调整相对模块路径并在挂载前安装/冻结官方Clock。原Node等待仍真实失败；同产品callbacks经runFor/实际响应等待后通过。见[探针与原来源SHA](../refactor-evidence/20261012-processing-records-polling/clock-probe.json)。这个隔离控制证明两个时间来源的断言缺口，不将模拟暂停当历史Windows根因复现。

最小修复仅[这一个测试](../../frontend/src/views/KnowledgeDetail.processing-records.test.mjs)：其fixture通过可选controlledClock在导航前安装官方Clock，空壳导航后、组件挂载前暂停，虚拟起点取未来一小时避免初始化期间目标变成过去；没有实际睡眠或已注册生产interval。只有轮询case启用，其他case仍原行为。真实click/LIVE加载后推进1999ms要求尚无新请求，再推进1ms并等待真实spans响应，保留reads增加断言。设置终态fixture后推进父3000ms并等records响应，再保留原失败/错误DOM条件。终态后推进6000ms覆盖三次轨迹/两次父周期，保留无新增请求、四条历史/旧root done、展开态及无pageerror断言。

不改任何生产Vue/API、轮询周期或数据。没有自造interval registry，没有删除断言或扩大固定sleep。当前验证只针对隔离Chromium和相关五项；新Windows全套/构建/正式安装验收由根代理绑定新freeze后执行。完整结果及最终源码SHA见[验证冻结](../refactor-evidence/20261012-processing-records-polling/freeze.json)。
