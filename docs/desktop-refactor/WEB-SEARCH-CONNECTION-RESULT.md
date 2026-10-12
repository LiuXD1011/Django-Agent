# 搜索服务修改后的连接状态

实际 Orca 操作发现：连接返回两条结果后，将同一服务地址从 `/search` 改为 `/failure` 并保存，卡片仍显示旧的连接成功；显式测试得到失败后，改回正确地址仍显示旧失败。问题发生在页面结果缓存，实际后台请求和配置保存正常。

`WebSearchSettings.vue` 将结果按服务 ID 缓存。删除服务和清除凭据已有缓存失效处理，成功编辑没有。最小修复在更新请求成功后只删除该服务的旧结果，再重新加载列表；保存失败不清除结果，也不自动发送连接请求或影响其他服务。

[SEARCH-UI-12 单元回归](../../frontend/src/views/settings/web-search-settings.test.mjs)使用真实 Settings、API wrapper、Vue/TDesign DOM，仅替代认证传输。先得到两张服务卡片的成功结果，编辑第一张并核对旧成功消失、第二张保留、没有额外测试请求；显式失败后改回地址，再核对旧失败消失及其他服务不变。留空凭据不提交 API Key。

- [修复前 RED](../refactor-evidence/20261012-web-search-result-invalidation/red.tap)：1 项失败，旧成功仍存在，断言实际 `1 !== 0`。
- [最小修复 GREEN](../refactor-evidence/20261012-web-search-result-invalidation/green.tap)：1/1，通过后另行修正 Windows 测试路径识别。
- [最终相关检查](../refactor-evidence/20261012-web-search-result-invalidation/related-execution.json)：29/29，51.053 秒；[完整前端](../refactor-evidence/20261012-web-search-result-invalidation/full-execution.json)：361/361，115.302 秒。输入身份在运行前后相同。
- [实际 Orca 回归](../refactor-evidence/20261012-web-search-real-browser/browser/113-p2-actual-browser-regression-and-server-snapshot.json)：成功后改地址、失败后恢复地址均立即移除旧结果；显式重新测试分别经过真实受控 HTTP 200、503、200，应用侧分别为 200、502、200。合成服务凭据仍可用，原模型、密钥及知识资料未变。

Windows 构建还暴露了独立的单元测试平台问题。旧测试通过 `importer.endsWith('/api/index.ts')` 识别需要隔离的认证传输，Windows esbuild 返回反斜杠路径，因此未匹配。实际请求进入真实客户端的 CSRF 初始化，fixture 未提供登录保护令牌，业务 POST 未发送。这不是厂商失败，不能通过伪造 CSRF 或改生产认证来处理。

[Windows 单独诊断](../refactor-evidence/20261012-web-search-result-invalidation/windows-fixture-red.log)保留真实 importer、`matched:false`、GET CSRF 和缺少 POST 的证据，单项退出 1。最终 fixture 使用 `fileURLToPath` 得到本机 API 文件的完整路径并精确比较，保留原断言及生产代码。[Windows 单文件完整检查](../refactor-evidence/20261012-web-search-result-invalidation/windows-fixture-green-execution.json)实际退出 0，14/14，130.518 秒；使用 owned staging、已绑定的实际 SFC，子组件位置单独记录，未调用厂商或操作用户数据。

旧来源 `cf2a6b7a…` 的 Windows prepare 为避免交付已发现问题而中止。[真实终态](../refactor-evidence/20261012-web-search-integrated-windows-build/root-cancellation-terminal.json)记录精确 owned child 的退出请求 125，但 wrapper 实际退出 1，正式 child 结果为 null；JobObject 保留句柄的五秒清理等待失败，不能宣称完整 prepare 通过或进程树已获验证。中止前产生的七项 Windows fixture 失败和未形成的完整计数均保留。后续构建使用另一个全新 staging，不复用该负载。

[前端生产构建](../refactor-evidence/20261012-web-search-result-invalidation/build-execution.json)实际退出 0，44.428 秒，85 个编译文件已记录 SHA；Vite 原有大块提示仍保留。上述单元检查与浏览器结果不替代正式新安装包。新来源的构建、安装、升级、卸载及桌面复核继续执行；Goal 仍为 active。
