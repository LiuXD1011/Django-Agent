# 轮询测试修复后的完整 Windows 构建

本轮绑定[全项目源码冻结](../20261012-integrated-poll-clock-source-freeze.json)，SHA256 `46a4ad77664f71d593f6f53a7504ed95e1651c8a806ec80fe5b16af66112007e`，454份构建输入、5份额外桌面测试、523份Linux编译产物。与原39feca来源相比，仅`KnowledgeDetail.processing-records.test.mjs`改用官方Playwright Clock，所有产品源码、依赖和编译产物相同，不需要重跑已经冻结的真实五题Ragas。

[原完整prepare失败](../20261012-integrated-chinese-query-windows-build/prepare-execution.json)仍为exit1：前端346/347，一项轮询断言失败，845.318秒。原日志SHA `a6dc272a60feb17ae56fcc3b62b994a12399572cfd951066b323fb8cac9d337f`不修改。[原测试单文件Windows对照](../20261012-processing-poll-windows-diagnostic/execution.json)5/5通过、49.075秒，不替代失败的全套测试；具体历史调度顺序无法从原日志还原。[修复与确定性RED/GREEN](../../desktop-refactor/PROCESSING-RECORDS-POLLING-TEST.md)保留真实组件、响应及所有原断言。

构建继续使用builder专用目录`C:\Users\lxd\AppData\Local\Temp\Marlin TS Chinese Query Final Build 20261012`。重建前实际核旧失败收据、日志、marker、旧测试摘要、未存在app/prepared/gates/output。正式builder的普通`--prepare-only`会重置它自己拥有的frontend/core-build/core-prod源码和依赖目录，重新执行npm ci、完整前端测试和后续全部门禁；没有使用`--refresh`、复用失败payload或修改其manifest。缓存只用于构建工具和经过SHA验证的官方Node压缩包。

[完整审阅runner](reviewed-build-runner.source.txt)采用精确绝对路径、只含公开配置的构建环境、3600秒私有JobObject。原installed应用、用户目录、四模型QA窗口和浏览器核心均未操作。新prepare的[实际启动收据](prepare-attempt.json)为`2026-10-12T00:36:35.538191Z`；已实际运行Windows前端347/347通过、Vite build退出0及核心TypeScript build退出0。完整[终态收据](prepare-execution.json)仍为exit1，1085.573秒，日志SHA `bc38af1dbfe8ead6d584f586043b750c52c407f0339825ff02125f2d473cd24b`：根代理将应用内Python用作构建解释器，该解释器没有pip，正式Python载荷准备因`No module named pip`终止。这是构建启动器选型错误，尚无后续门禁、NSIS、安装或pageReady结果。正确构建主机`C:\Python313\python.exe`已实际确认Windows AMD64、Python3.13.3与pip25.0.1；目标载荷版本仍由正式锁文件固定为3.13.16。

该runner的package阶段要求实际prepare退出0，因此本轮失败来源不允许打包。真实页面另外确认联网搜索配置入口未接上，根代理将先补齐该功能，再冻结新的来源并用正确构建解释器执行普通完整prepare，不复用本轮失败payload或修改其manifest。后续产物写到专用`Marlin TS Readiness Generation Installers 20261012`，不发布，实际installer大小/SHA及收据另行保存后再绑定已审安装harness `6926f388…`。目前没有最终来源的可交付安装包。
