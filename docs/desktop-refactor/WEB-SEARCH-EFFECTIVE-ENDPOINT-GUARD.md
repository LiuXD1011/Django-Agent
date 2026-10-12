# 联网搜索实际端点与凭据保护

2026-10-12，Root 审查前端保留旧 `base_url` 字段时，使用当前编译核心、真实 Auth/SQLite/CredentialVault 复现了一处核心缺陷。专用临时数据中创建 `base_url=http://127.0.0.1:18080/search`、已保存合成密钥的 SearXNG 服务，再提交另一主机 `url=http://127.0.0.1:18081/search` 和空密钥。实际更新成功，新增 URL 被保存，原凭据继续配置。没有使用真实用户数据，没有发 HTTP 或模型请求。

根因是 [SettingsService](../../packages/core/src/settings/settings.ts) 逐字段调用 `protectEndpoint`：新增 `url` 没有 `previous.url`，检查提前返回；原 `base_url` 没变，因此另一检查也通过。[搜索适配器](../../packages/core/src/integrations/search.ts) 实际按 `url || base_url` 选地址，新增 `url` 已改变了凭据将发送的目标。反向清空 `url`、改用已有另一主机 `base_url` 也需要按同一规则防护。只让前端保留旧字段不能保护直接 API 写入。

实施选择是在 `web_search_providers` 的原同步更新事务内，先对 `previous.url || previous.base_url` 与 `next.url || next.base_url` 调用既有 `protectEndpoint`，再保留原逐字段校验。只构造检查用的临时对象，不迁移、重写或删除真实 URL 字段、凭据及扩展配置，不修改密钥 merge 或其他 Provider 的语义。继续要求换主机时显式提供新凭据，或先通过既有清除接口清除旧凭据。

Root 独占核心源和测试。旧冻结 `758144f6…` 的 109 文件全套先实际结束，692 项中 688 通过、2 失败、2 个编译专用条件跳过，才开始编辑。两项失败分别是 Root 在 PATH 中优先放入不含 Django 的辅助解析 Python，导致旧密码兼容测试无法导入 Django；以及旧超时测试在重负载下先触发 300 毫秒期限、再等待 HTTP 请求，导致等待前置条件永远不成立。前者换回开发机正确 Python 后 11/11 通过；后者保留 300 毫秒边界与真实 HTTP/断连断言，仅控制期限触发时机，27/27 通过，没有修改生产队列或放宽期限。旧失败日志保留。

新增真实数据库回归先 RED，再最小修复：

- `base_url` 服务新增另一主机 `url`、留空或省略密钥时，拒绝且整行保持不变。
- 双字段服务清空 `url`、落到另一主机 `base_url` 时，拒绝且整行保持不变。
- 同主机别名及路径调整允许留空保留凭据；显式新密钥允许换主机；明确清除后允许匿名换主机。安全投影不回显合成密钥。

验证执行新增搜索配置测试、相关设置/集成/Agent 测试、类型检查和构建；更新核心来源后执行最终完整核心与独立 plain Node 编译入口检查，再统一冻结最新前端和核心。新的 Windows 普通完整 prepare 使用已确认带 pip 的 `C:\Python313\python.exe`，不复用旧失败 payload，之后再打包、安装和真实页面验收。

当前保护已实现。新增搜索回归真实 RED 为 8/10 通过、2 项应拒绝而未拒绝；修复后 10/10 通过。检查对象补上空字符串类型后，最终相关 106/106、类型检查和核心构建均退出 0。[检查收据](../refactor-evidence/20261012-web-search-core/alias-verification.json)记录首次类型失败、修正及原始日志，不覆盖历史。最终核心来源已冻结为 `5cc5960195d5f8e48900beec4973b7b7f4aa9175ae0b9b8e45bde79ab68cde38`，274 输入、438 编译文件。新的 109 文件完整检查实际结束：695 项中 693 通过、0 失败、2 编译入口条件跳过，700.756 秒；独立 plain Node 编译入口 2/2、退出 0、16.380 秒。两次执行前后源码和编译输出均保持一致。[完整结果](../refactor-evidence/20261012-web-search-alias-final-core-checks/full-execution.json)、[独立编译入口](../refactor-evidence/20261012-web-search-alias-final-core-checks/compiled-execution.json)。

旧 46a Windows prepare 因 Root 错用应用内 Python 而失败，旧失败收据保留；正式应用 Python 仍保持隔离且不添加 pip。上述测试是本地集成检查，没有真实用户数据或厂商调用，不替代 Orca 联网搜索与最终 Windows 安装版验收。
