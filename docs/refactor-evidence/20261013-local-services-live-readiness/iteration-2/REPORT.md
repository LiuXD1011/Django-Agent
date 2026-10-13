# 真实 Linux Langfuse fixture：只准备，不执行

2026-10-13。Root授权将只读readiness推进到可审核输入；本轮未执行Docker up/down/pull、Core、Vite、GUI或任何模型请求，没有改生产/正式tests/deps/主文档/Git，没有重跑current324 full/Owner。

已创建专属 `/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93`（0700），其source/data/cache/receipts/docker-config/temp目录0700。合成 `.env.langfuse`0600，随机秘密独立生成；没有复制/读取真实.env、QA DB、private-auth或Keys。证据仅保留秘密文件路径、SHA和变量名，秘密字节不归档。data目录为空，未建立Core DB/Key。

| 输入/验证 | 实际结果 | 证据 |
| --- | --- | --- |
| 当前工作区compose对公开HEAD | SHA均 `34b365a66ca7f97867547fcb956dfe148f4d783f33499b87f8a0e27664404062`，字节相同；复制基线是工作区 | [完整非秘密配置](compose-nonsecret-audit.json) |
| 唯一project | `marlin-autostart-live-20261013-3d90135bf46d`；container/network/volume label零碰撞 | [实际只读记录](project-no-collision.json) |
| fixture host端口 | Langfuse3300、Core18080、UI18173；实际bind检测空闲后立即释放，没有服务监听/永久预留 | [待执行输入](prepared-fixture.json) |
| Compose差异 | 仅web host port 3000→3300；其余六 pinned服务/depends_on/五 local named卷语义相同，无固定container/project名、外部卷/网络或bind mount | [配置审计](compose-nonsecret-audit.json) |
| fixture真实config --quiet | exit0，stdout/stderr丢弃；静态检查，不算部署/启动PASS | [实际记录](fixture-compose-config.result.json) |
| prepared helper语法 | Python py_compile0、Node --check0；运行程序未消费 | [机器回执](prepared-fixture.json) |
| 已验证Core来源 | 324 source+441 dist，再含已读依赖类型，总767SHA绑定全部匹配；service8c4b…，未build | [输入绑定与文件hash](prepared-fixture.json)、[此前独立current324](../../20261013-current-core-324-validation/REPORT.md) |
| 既有六容器及3000 | 只取ID/created/image/status/health，before/after完全相同，全球运行ID集合仍六；3000 IPv4health仍200，没有读取env/log/name | [before与资源](existing-stack-and-resources.before.json)、[after](existing-stack.after.json) |

只读资源样本：MemAvailable约15.4GiB、disk free约459GiB、12CPU/load≈0.7；既有栈约3.4GiB（ClickHouse1.707GiB、web1.002GiB、worker514MiB等）。不是持续压力保证。未来完整独立栈须再次满足14GiB可用/10GiB disk与8GiB既有工作保留；本轮仅准备，不为可选能力增加运行规模或复用现有服务凭据。程序取消会停止自己的Core/UI，长期containers仍由Root按唯一project决定cleanup，不能靠Core关闭自动释放栈内存。

已完整读当前dev CLI、Owner client/host/contracts及实际dist类型。准确可信参数是`sourceRoot`/`--source-root`，没有`projectRoot`，也没有普通HTTP/renderer命令入口。为Root的Orca保存true/false准备独立Vite程序，实际Vue UI来自当前源码，所有/api/files/health代理指自有Core18080；configFile=false/envDir=false/cache私有，不写原Vite配置、不复用5173/8000。须用全新Orca profile，因为Cookie不按端口隔离。

[控制器源码](fixture-control.source.py.txt)、[独立UI源码](fixture-ui.source.mjs.txt)、[设计/准备顺序](DESIGN-PLAN.md)、[Root精确命令与真实断言](RUNBOOK.md)给出源与输入门禁、资源门槛、Popen+PID/startTicks+pidfd取消、30秒终态等待、单次180秒外部watchdog不改服务1–120秒预算、分次失败保留、真实strace process-only exec/exit、saved true/false且四个业务envoverride全unset、独立project cleanup和非干扰核对。程序未实际运行，不宣称其执行/取消/cleanup已经通过；Root须review及实际验收。

准备中两项自有helper失败全部保留：Docker Go模板直接.State.Health遇无healthcheck missing-key，改用index后实际只读inventory0；它不是原容器unhealthy。生成器首exit1因内嵌控制器newline转义造成SyntaxError，只修私有程序该行并复用同fixture/project/secrets，随后语法0。见 [模板诊断](inspect-template-diagnosis.json)、[原syntax失败](preparation-initial-syntax-failure.json)、[原控制器](fixture-control.initial-syntax-failure.source.py.txt)、[修复回执](preparation-syntax-repair.json)。不改生产或放宽assert，也不覆盖首失败。

使用后的三个自有prepare/repair/finalize助手按SHA/逐字对照归档后精确删；语法bytecode精确移除。两个未消费runtime程序及独立私有输入保留，原因是Root下一真实阶段的review/Orca使用；没有隐式启动，见 [助手清理与保留原因](helper-cleanup.json)、[bytecode清理](syntax-cache-cleanup.json)。新链接、文档差异、来源SHA与文件权限见 [最终检查](final-checks.json)，证据SHA见 [完整性](artifacts.sha256.json)。本轮仅prepared，不算真实autostart、设置保存、Windows、I/J或完整Goal PASS。
