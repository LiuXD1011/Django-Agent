# Langfuse 自动启动迁移 iteration-2：独立复审

2026-10-13。复审 [iteration-2 实现报告](../../20261013-local-services-autostart/iteration-2/REPORT.md)、review-fixes.diff、当前 code-complete.diff、15 文件来源绑定、validation-results 和 final-checks，并完整阅读当前 local-services.ts、新增 review-regressions 测试及已安装 fs.promises 类型。首轮 [审查报告](../REPORT.md)、原 RED 输出及 actual exit1 保留原样；本轮没有修改生产代码、索引、原证据或用户数据，没有操作服务、端口、Docker、浏览器或 Windows。

## 独立结论

- **Spec compliance：R1/R2 修复符合原合同。** Docker 解析现在使用原 `remaining()`，保留截止时间和取消优先；旧合法有限 float 表示与非法位置处理已恢复。本轮没有发现其他生产合同问题。真实 Docker、Orca、native Windows/新包装来源门禁仍未完成，不由此结论代替。
- **Code quality：生产修复可以接受。** 改动限于服务解析及一个针对性回归文件，未增加 Python 运行时依赖，也未修改 Owner/desktop/supervisor/默认输出捕获。没有新增生产代码修改请求。归档完整差异的遗漏已补齐并独立核验，E1已闭合。

## R1 闭合

`packages/core/src/integrations/local-services.ts:51–67` 的 dockerExecutable 接收原 remaining 闭包；候选之前、stat 成功后、access 成功后、error 分类前及最终缺失/不可访问分类前均检查同一闭包。正常返回和抛错分支都不会在预算或信号已结束时继续下一候选，也没有新 deadline。剩余值不因锁 grant 或 resolver grant 复位。

已安装 `@types/node/fs/promises.d.ts` 的 stat 参数只有 path/StatOptions，access 只有 path/mode，均没有 AbortSignal。报告所述限制准确：当前单个文件系统请求需等终态，此后立即停止工作；可见超预算来自这一个尚未结束的请求，不是继续遍历或扩充工作预算。原同源码 GREEN 证据显示 1 秒预算下 7 次 160ms 请求约1125–1129ms即停止；40ms abort/close 仅1次请求约162ms。close 仍等待 pending 终态。

新增回归清楚标识只注入 Docker 候选 stat/access，保留真实 SQLite/source/state，并在 finally 恢复 fs API 和删除自身数据目录；不是 Docker 部署成功证据。原独立脚本不变重放3/3，新增回归 RED0/6→GREEN6/6的日志和实际退出值已读取核对，未重复运行它们。

## R2 闭合

`packages/core/src/integrations/local-services.ts:22–35` 先以 Unicode White_Space 处理首尾空白，再把 Decimal_Number codepoint 转为 ASCII 值；连续十进制区块用与区块起点之差 modulo10，保留相邻数学样式的值。完整语法验证之后才删除下划线并交给 Number；下划线只能夹在数字间，整数/小数/exponent 的边界没有放宽。原非法十六进制、双下划线、首尾下划线、小数点/exponent 邻接下划线、BOM/不支持控制字符仍回退45；有限结果继续1–120夹取。普通 saved number 配置及非有限回退保持合同。

针对新增 codepoint 算法，额外独立检查当前 Python Unicode15 的全部680个 Nd：分别构造小数及下划线数字；再比较29个 Python isspace codepoint及BOM的首尾边界，共1420个输入，actual exit0、无差异：[输出](unicode-float-check.log)、[actual exit](unicode-float-check.exit)、[源码](unicode-float-check.source.mjs.txt)。当前 Node Unicode17；此检查明确验证 Python Unicode15 的全部 decimal digits，未冒称 Python oracle覆盖未来Unicode版本。额外 Python 只在审查时用作独立oracle，产品与新增产品测试无 Python/Django 导入依赖。

## 来源、原验证与证据完整性

当前15文件SHA全匹配 iteration-2绑定；服务SHA为 `8c4b6436afd864b4247fdddc4e41a5a36c7b9a18a921eecbdd2a5b9b9bdaa2fa`。与首轮相比，生产只有 service 修改，另新增 regression 文件，其他13文件SHA不变。

原同源码 focused28/28、typecheck/build actual0、fresh plain compiled2/2、targeted6/6、原脚本replay3/3的日志/终态已读取核对。6个targeted包含在28之中，不累加为唯一数量；未无理由重跑相同验证。

**E1已闭合（归档问题，不是生产代码问题）：** 首次归档仅9条新增文件差异，遗漏 application.ts、jobs/owned-process.ts、runtime/owner-client.ts、owner-contracts.ts、owner-host.ts、tools/dev-server.ts 六条原修改；初查 actual1 已保存为 [incomplete-diff-check.actual1.json](incomplete-diff-check.actual1.json)。实现者随后修复差异生成器，保留旧不完整包，完整差异现在为6修改+9新增，共15路径，SHA `d8f48869f3bc7363e5ec5198239d0f477f50f96ef2cf8bff4351c2d241f22ffa`。复审独立验证15路径均存在，并逐个将完整patch应用于已验证的原baseline字节，重建结果全部匹配当前来源SHA及实际源码：[patch重建核对](patch-reconstruction.json)、[核对源码](patch-reconstruction.source.py.txt)。这是证据修正，没有生产变化，无需再次运行相同业务测试。

独立来源和差异范围核对 actual0 见 [review-checks.json](review-checks.json)。报告链接/空白、原RED保留和自身数据目录检查见 [document-checks.json](document-checks.json)。Unicode和核对脚本归档后删除；没有创建业务服务或辅助CLI进程。
