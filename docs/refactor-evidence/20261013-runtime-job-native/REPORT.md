# Win32 Runtime Job adapter 实施与独立真实验收

本项完成极小 NAPI8 adapter、独立构建 helper 和自有 Windows fixtures。相同二进制在 bundled Node22.23.2、Electron44.7.0 RunAsNode／Node24.21.0，以及普通 Electron main／Node24.21.0 实际加载和运行。最终分别6／6、6／6、3／3通过，三个运行器实际 exit0，51个记录的原进程 HANDLE 最后均为真实终态。普通 main 全程 BrowserWindow 数量为0。

这是 native adapter 的独立验收，正式 Runtime／bootstrap、安装包和产品 GUI 仍由 Root 与打包代理集成复验；本报告不能替代该阶段。此前原 PID25268 的未知终态／死因保持未验证，也不归因于旧 taskkill 路径或本次新 adapter。

## 实现与归属

- [runtime_job.cc](../../../desktop/native/runtime-job/runtime_job.cc) SHA `9d56cbb4e29693e10b54e684de13bf831248b8832d0748e9880464cf96300755`，仅暴露约定的 `currentIdentity` 和 `bindRoot`；opaque 对象仅提供 `status/terminate/close`。
- `currentIdentity()` 使用自身 Win32 HANDLE 取得 pid、真实创建 FILETIME 十进制字符串和 UTF-16 image。`bindRoot()` 在同一个新打开 HANDLE 核 pid、原 FILETIME、image、liveness，再将该 HANDLE Assign；Assign 前后再次核 liveness。错误身份在建立非空 Job 前拒绝，没有任意 PID 终止 API。
- 新建 unnamed Job 只设置 KILL_ON_JOB_CLOSE，无 breakaway、无继承；保留原 root HANDLE 和 Job HANDLE。`status()` 读取原 HANDLE wait／真实 exit code 和原 Job accounting，未退出时 `rootExitCode:null`。`terminate()` 只对保留的 Job HANDLE 调用 TerminateJobObject；Query／Terminate／Close 失败抛错，不伪装 empty。显式 close 幂等，Node-API type tag 拒绝伪造／原型继承 receiver，RAII 与 finalizer 负责句柄释放。
- [build-runtime-job.py](../../../scripts/desktop/build-runtime-job.py) 固定 `--source-dir --work-dir --node-executable --output --report`，要求 native Windows、fresh work、未存在 output／report和官方 Node22.23.2 x64字节。仅编译时使用 Python；普通 main／bootstrap 没有 Python guard。Source目录正式文件清单与 SHA、编译器、官方输入、实际命令码、产物和 Node identity smoke 写入 schemaVersion1报告。
- 只用公开 Node-API、Win32和 MSVC delay-load hook；未使用 ChildProcess `_handle`，没有裸 PID／名称／端口清理，未更改既有 Runtime／main、其他代理文件、历史冻结、Git index，也没有 stage／commit。

同一 HANDLE 的创建时间核验约束迟到 ACK 与整数 PID 复用之间的竞态；这是 API 和实现保证，不是机器上的陌生 PID 复用压力实验。[Windows句柄与标识](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)、[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)、[AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)。NAPI8 type tag 是公开 ABI，Win32对象未传给 renderer。[Node22 Node-API](https://nodejs.org/download/release/v22.23.2/docs/api/n-api.html)。

## 真实 RED 与保留的失败

| 实际执行 | 真实结果 | 证据与限制 |
| --- | --- | --- |
| 首次 RED | 工具1 | 自有 idle root 已启动，但观察器在 root结束后重新读 image 返回 Win32 31，finally又读image而未落完整回执。保留[工具错误](red-observer-failed-tool.json)、[原日志](red-observer-failed-test.log)，其原 HANDLE最终状态未记录，不补写推断结果 |
| 第二次 RED | 工具1／Node1，0PASS／1FAIL | [缺失 addon assertion](red-2-test.log)；root PID22108／FT134363373993406927 从 wait258 到同 HANDLE wait0／exit0，outer Job实际 active0，[回执](red-2-execution.json) |
| native build1、2 | 工具1／wrapper1；vswhere0但输出[] | [build1](native-build-1.json)、[build2](native-build-2.json)。clean env遗漏 ProgramData；使用公开 SHGetFolderPathW得到 OS目录后，保持实际编译及依赖门禁，第三次通过 |
| 首次 Node GREEN | Node1，4PASS／1FAIL | [日志](node-green-test.log)。普通 fork 被 libuv自己的 parent Job在 root exit时一并终止，不能证明 root先退后的剩余后代清理；全部已记录自有 HANDLE最终退出。仅修改fixture创建方式后复验 |
| 首次 Electron main | OS2147483651／0x80000003，工具3；业务case0 | [日志](electron-main-green-test.log)、[真实回执](electron-main-green-execution.json)。UNC运行位置发生 Chromium GPU launch error18，不能计 main通过；保持原字节、参数、Job，独立 native C盘副本下一轮通过。仅此差异不足以证明具体 GPU死因 |

测试fixture改为 detached descendants，是为了保留实际 live children。Node22 libuv明确该分支使用 DETACHED_PROCESS／CREATE_NEW_PROCESS_GROUP，**没有** CREATE_BREAKAWAY_FROM_JOB；native Job和outer Job仍必须覆盖它们。普通 fork 的 parent Job行为和 detached flags见[同版本公开源码](https://raw.githubusercontent.com/nodejs/node/v22.23.2/deps/uv/src/win/process.c)。不是删除待测后代，也没有放宽产品 Job限制。

## 编译和加载

[第三次实际构建](native-build-3.json) actual exit0；MSVC14.29.30133／WinSDK10.0.19041.0，`/LD /MT /O2 /W4 /WX /EHsc /std:c++17 /utf-8 /DNAPI_VERSION=8 /DBUILDING_NODE_EXTENSION /D_WIN32_WINNT=0x0602`，Win x64，延迟加载 node.exe。编译器实际无 warning／error；编译日志的系统中文编码字节原样保留。[原编译日志](build-work-3-compile.log)、[dumpbin imports](build-work-3-imports.log)。只有 KERNEL32.dll 和延迟 node.exe，无额外 VC runtime DLL；host hook仅把该延迟 Node-API import指向当前宿主。[Electron公开 delay-load要求](https://www.electronjs.org/docs/latest/tutorial/using-native-node-modules)。

官方输入下载已核[发布 SHASUMS](https://nodejs.org/download/release/v22.23.2/SHASUMS256.txt)，并固定四项SHA：[独立下载投影](official-input-download.json)。

| 输入 | SHA256 |
| --- | --- |
| Node22.23.2 win-x64/node.exe | `0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4` |
| headers.tar.gz | `daaf13ec5d45a38bbcfcff06d0723f72a6813b89ab27bb5af2ac8e1f6259dde0` |
| win-x64/node.lib | `ac15f1e9d7c8279353723a77f6319967f1a41c06026521094a8234c2e6fbe052` |
| SHASUMS256.txt | `778ac5b2fcdbd68d9c0ae9f4310674faa3af0910bd0d18e7f6597787c40a3e39` |

产物126976字节，SHA `b4f053aa1732e07220cd56b37fa5434b953d48e1b26c29e65f60d31f39c8eecb`；保留供 Root审查／集成的路径：`C:\Users\lxd\AppData\Local\Temp\Marlin Runtime Job Native QA 20261013\build\runtime-job.node`。真实 Node／Electron versions保存在各次 cases，而不是由DEPS推测。源码／工具／原日志与这个二进制的绑定见[执行投影](execution-projection.json)。

| Loader／固定自有runner | Node／NAPI／UV | 实际结果 |
| --- | --- | --- |
| bundled Node22.23.2 | 22.23.2／10／1.51.0 | 6／6，exit0，outer Job0，[日志](node-green-2-test.log)、[原 HANDLE回执](node-green-2-execution.json)、[cases](node-green-2-cases.json) |
| Electron44.7.0 RunAsNode | 24.21.0／10／1.52.1 | 6／6，exit0，outer Job0，[日志](electron-node-green-test.log)、[回执](electron-node-green-execution.json)、[cases](electron-node-green-cases.json) |
| 普通 Electron44.7.0 main | 24.21.0／10／1.52.1 | 3／3，exit0，outer Job0，无 BrowserWindow／Core／renderer，[回执](electron-main-green-2-execution.json)、[cases](electron-main-green-2-cases.json) |

普通 main使用完整 dist的独立 native副本，exe SHA与原 source同为 `2529b494f4123f152bce346051f7bd855ef95006424a561953cf17c49a3d1ba8`，[逐文件复制校验](electron-native-copy.json)。无产品app.asar、用户资料或配置被复制／启动。用户数据库、模型、密码、Key、device、业务 HTTP请求均为0；构建请求仅用于上述官方编译输入下载，API审查使用公开文档。

## 进程树与终态证据

Node和RunAsNode两轮各持19个原 HANDLE，main轮持13个，共51个。只读观察器在每个动作前打开其自有fixture HANDLE并核真实FILETIME和image，之后保持这个HANDLE至检查结束。进程结束后使用保留的初始image，继续用同HANDLE读取创建时间、wait及真实exitCode；不再次用PID定位终态。各runner由已完整审阅的 `windows-job.py` 创建 suspended child→private outer Job→resume，有界90秒；其正常返回必须经过全部自有树reap及真实 accounting active0检查。

6项正式测试覆盖：精确自身identity／FILETIME无Number丢精度和非法参数；创建时间或image不匹配时原child仍可pong；terminate和close分别只处理root／child／grandchild；root先exit0、两后代仍alive且active2，再Terminate到active0并保留原root exit0；owner被公开原ChildProcess对象突然终止后，最后JobHANDLE由OS关闭，完整树终态。每项旁实例动作后仍wait258／可pong，随后自己的cleanup才正常exit0。

Job terminate实际root／子／孙exit1；Job close实际exit0；root-first保留root0、后代force1。owner abrupt实际owner1、其Job内root／子／孙0；这些不同结果按原HANDLE记录，未把force的1改为graceful0。main三项重复证明terminate、close、root-first，包括其旁实例；整个main无窗口，未测试任何产品页面。

自有fixture的创建／IPC和检查耗时约0.1–0.5秒／case不能当产品启动或退出延迟；Root仍需验证30秒graceful、force后5秒、真实业务取消和产品后代行为。

## 清理、审查边界

原失败产物、逐次fixture源码、最终native源／helper与真实工具结果均保存。自己消费的临时脚本归档后精确删除；独立build-work／fixture／Electron副本清理按自有marker和逐文件／目录清单执行，产物与owner marker保留供Root集成。[清理回执](consumed-cleanup.json)、[最终验证](validation.json)、[冻结清单](freeze.json)。历史169d／0718冻结SHA保持原值。

本项不制造陌生PID复用、权限剥夺或损坏的OS HANDLE；真实 Win32 Query／Terminate拒绝路径按C++检查抛错，Root的可控adapter正式测试验证 Runtime如何消费这些错误。本机以外平台／机器、正式打包应用的普通启动／托盘退出、业务worker／解析后代均待其对应阶段；本轮成功不替代这些验证。仍须保持normal运行无system Node／Python依赖、最终manifest绑定及GUI验收。
