# Windows 自有 Runtime 打包集成

本阶段完成构建链集成及 Linux 主机上的相关回归，不声明 Windows 安装包或整个 Goal 已完成。未启动产品 GUI、Core HTTP、付费模型，未读取真实用户数据，未执行 stage、commit、reset、push 或发布。源码 TS Core、私有 JSON 协议、Python 解析/评测 worker、Langfuse、安全与源变化门禁继续保留。

新增 `owned-runtime.cjs` 和 `runtime-bootstrap.cjs` 到 desktop、builder、启动器及实际 ASAR 的十二项严格白名单；把 `desktop/native/runtime-job/` 和新增 build helper、三项正式 Runtime 回归文件加入源冻结。原依赖版本和锁文件未改。native 目标为 `payload/owned-runtime/runtime-job.node`，安装后为 `resources/runtime/owned-runtime/runtime-job.node`；ASAR 审计要求其在 manifest 中，并比较完整实际产物字节。

clean build 和 refresh 均使用 payload 中 SHA 固定的 Node22.23.2 调用 native helper。每轮编译使用独立 fresh `runtime-job-work-<uuid>`，refresh 只精确移除前轮该 addon 目标，保留编译日志。冻结报告验证 NAPI8、Windows x64、Node 实际版本、完整 native 源 SHA、公开构建输入的官方精确 SHA、编译器 SHA、各命令退出码、DLL 导入白名单和实际 `.node` 长度/SHA。正式 gate 和启动器均绑定 `runtime-job-build.json` 的原始字节，不能只靠文件存在通过。

payload 探针实际加载 addon、核验 `currentIdentity()` 的 PID/FILETIME/可执行路径并记录 addon SHA；真实 TS IPC 探针还要求原 lifetime 的 Job 已授权且完整关闭。正式 Windows gate 增加普通 Electron main 的同一 addon 加载探针，在独立数据目录记录真实 `process.versions`、原生身份及产物 SHA，不创建窗口或启动 Core。该报告与 native 整树专项验收分开，不把布尔标志当双加载实验。NSIS 输出同时导出 native build、Electron loader 和既有业务验证报告。

Windows Runtime 测试仍保留原全部 test/assert，仅按严格 occurrence 数将 source TS/`--import tsx` 路径转为 staged compiled TS，并明确指定同一 payload addon。Electron Langfuse fixture 同样保留原全部断言，复制所需两个新 CJS 并固定 addon 路径；路径形状变化会明确失败。

实际 RED 为五组、七个失败：白名单/编译命令 2FAIL，native 报告/Windows fixture 路径 2FAIL，重新计算 manifest 后混入不同 addon 1FAIL，ASAR manifest 删除 native 1FAIL，Electron loader 报告错误 addon 1FAIL。其原始输出见 [首组 RED](red-execution.json)、[报告及路径 RED](native-report-red.json)、[重绑 native RED](rebound-native-red.json)、[ASAR RED](asar-native-red.json)、[Electron RED](electron-loader-red.json)。未把全套模拟编译 runner 初次缺 fixture 的失败计入缺陷 RED。

最新相关检查：

- `python -m unittest scripts.test_build_windows`：actual exit0，43 tests，41PASS/2Windows skip。[完整输出](python-green-execution.json)。原真实 SQLite/FTS/vec、60bit ID 与 TS IPC 回归仍运行。
- `node --test scripts/desktop/startup.test.cjs`：actual exit0，133 tests，128PASS/5Windows skip，含新增 26 种 native build/Node loader/Electron loader 报告重算 SHA 后仍拒绝的情况。[完整输出](startup-green-execution.json)。
- 相关 `git diff --check` 与四个 CJS 的 `node --check`：五条 actual exit0。[源码及检查绑定](source-bindings-final.json)。此绑定在 GREEN 后采集；除第一组 RED 外，其余 RED 未保存当时逐文件 SHA，不能冒充逐轮预后冻结。临时记录脚本已[精确归档](finalize.source.py.txt)并删除 `/tmp/marlin-runtime-packaging-finalize-20261013.py`。

逻辑 Git index 使用 `git ls-files --stage` 输出字节 SHA，仍为 `c8f6e0465ed59dcf3111b94d994a2604ebee7868656df9166b7b1ca26f1cb731`；`.git/index` 原始二进制哈希可因 stat cache 改变，两者未混称。保留全部无关工作区修改。

native 代理已另行提供 [真实成功编译样本](../20261013-runtime-job-native/native-build-3.json)，其 schema 与 validator 对齐。此样本不充当新 staging 的编译报告；native 源随后变动时必须在正式 builder 中重新编译、绑定当轮全部源，不能复用旧报告授权 NSIS。

剩余目标平台门禁由 Root 集成执行：在 native Windows x64 Python3.13、独立本地 staging 中 fresh build 或验证 unchanged dependencies 后 refresh；运行当前冻结 gate/双 loader/真实 TS IPC/worker/Langfuse；然后 package-only 重核源与 ASAR，最后验证新包中文空格路径、普通启动、解析后代、托盘退出、关闭后台及重启不重放。不得以本阶段 Linux PASS 或 native 专项替代新包验收。示例命令（Windows source 根目录，填入已核固定 Node 的本机路径）：

```powershell
python scripts/build_windows.py --work-dir "C:\MarlinBuild\OwnedRuntime-20261013" --build-node "C:\BuildNode\node.exe" --prepare-only
python scripts/build_windows.py --work-dir "C:\MarlinBuild\OwnedRuntime-20261013" --build-node "C:\BuildNode\node.exe" --package-only --output-dir "C:\MarlinBuild\OwnedRuntime-output-20261013"
```

这两条正式构建命令尚未由本代理执行；Electron `.exe` 和生成的 main fixture 必须运行在本地 staging，不能把 native 专项记录的 UNC GPU fatal 洗成成功。
