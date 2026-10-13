# 自有 Runtime 退出修复实施计划

> 在现有 Goal 授权范围内执行。用户已批准普通设计、修复、依赖选择、隔离构建与独立子代理；不再逐步请求许可，不提交或发布。本计划接续 [只读审查与实际 RED](OWNED-RUNTIME-SHUTDOWN-REVIEW.md)。

**目标：** 保留30秒正常退出期限，超时或根进程提前退出后只清理本次应用创建的完整 Windows 进程树；退出 Promise 有界且不能在后代仍活着时成功。

**架构：** 保留 ChildProcess、JSON 私有协议、TypeScript Core 和现有每任务 Job。新增 Node-API 的 Win32 Job 适配器，fork 的小型 bootstrap 必须等父进程核验真实创建时间并绑定 Job 后才导入业务入口。所有后续退出操作使用原 Job 与原 HANDLE，取消裸 PID taskkill。

**技术：** Electron44.7.0／父 Node24、bundled Node22.23.2、NAPI_VERSION8、Win32 Job、CJS bootstrap；无新增正常运行 Python 依赖或 renderer 系统接口。

## 全局约束

- 原用户数据库、管理员密码、密钥、模型、设备和媒体不参与此项测试。
- 正常启动30秒期限和正常退出30秒期限保持不变；force 后等待上限5秒，观察超时必须失败，不能冒充实际退出。
- 文件归属明确：native 实现代理只负责 `desktop/native/runtime-job/`、`scripts/desktop/build-runtime-job.py` 和自己的专项证据；Root 负责 Runtime、bootstrap、生命周期、main 的失败处理与打包集成。
- 既有 frontend auth、Core 业务、迁移、Langfuse和协议编码不改；保留其他工作区及 Git index 改动。
- `stop()` 幂等；旧 generation 的异步回调只持有旧对象，不能触达新实例。
- 不读取 ChildProcess `_handle`，不启动 Python guard，不按 PID/image/port 降级杀进程。
- Windows 源码及 synthetic 通过不能替代双加载、嵌套 Job、中文空格路径和已打包应用的实际验收。

## 固定跨模块接口

native 模块只由可信 main 和 bootstrap 加载：

```js
const identity = native.currentIdentity();
// { pid: positive safe integer, createdAt: unsigned decimal string, executable: string }
const job = native.bindRoot(child.pid, identity.createdAt, expectedExecutable);
// OpenProcess之后在同一HANDLE验证pid、FILETIME、path与liveness，再Assign。
const status = job.status();
// { rootExited: boolean, rootExitCode: number|null, activeProcesses: nonnegative integer }
job.terminate(); // TerminateJobObject on the original retained Job; failure throws.
job.close();     // Idempotent CloseHandle; kill-on-close remains set.
```

不存在传出 HANDLE 数字或重新按 PID 终止的 API。identity 不匹配时只关闭新建空 Job 和观察句柄，不能对所打开对象 Assign 或 Terminate。Bootstrap 报告的 `createdAt` 来自自身 `GetProcessTimes(GetCurrentProcess())`；nonce 不能代替该值。

bootstrap 私有启动信令限定为：

```js
{ type: 'owned-bootstrap', protocol: 1, generation, pid, createdAt }
{ type: 'owned-start', protocol: 1, generation }
```

父子双方严格拒绝多余字段、错误类型、错误 generation 和二次授权。收到普通 shutdown 或授权前断开时退出而不导入业务。授权后恢复原 `process.argv` 并动态导入原入口，保留原业务 JSON 字节协议。

## 任务1：native 身份与 Job adapter

**创建：** `desktop/native/runtime-job/runtime_job.cc`、该目录下正式自有 Windows fixture／test、`scripts/desktop/build-runtime-job.py`。

- [ ] 先写真实 Windows 自有进程测试，实际观测实现缺失的 RED；synthetic RED 已有3条，不能作为 native 真实 GREEN。
- [ ] 实现上述固定接口；NAPI包装的对象持有root和Job，receiver校验、RAII释放、无句柄继承、无breakaway。
- [ ] 验证绑定之前目标仍活着；Assign 后再检查 root liveness，父级授权只在成功后发送。
- [ ] 编译只依赖公开 Node-API 与系统DLL；确定 header／node.lib 的官方版本和哈希，不引入额外 VC runtime 安装要求。
- [ ] 在 bundled Node22 与实际 Electron44/Node24加载同一二进制，记录真实 `process.versions`；自有 root/子/孙进程、旁实例、nested outer Job 均持句柄核验实际终态。
- [ ] 所有helper有界、只清理自己创建的目录、句柄和进程；保留失败的实际退出码及原日志。

## 任务2：正式 Runtime 回归与启动授权

**Root 创建：** `desktop/runtime-shutdown.test.cjs`、`desktop/runtime-bootstrap.cjs`、`desktop/owned-runtime.cjs`；修改 `desktop/runtime.cjs`。

- [ ] 在修改产品前，把已复现的迟到动作、提前resolve、失败挂起迁为正式测试；VM替身明确标注，验证的是原Runtime的真实分支。
- [ ] 增加旧ACK、身份不匹配、startup取消、双实例迟到回调、root先退出而Job后代存活和Query/Terminate失败用例。
- [ ] Windows parent 先加载adapter，再fork bootstrap；严格信令核验、创建绑定成功后授权。没有addon或绑定失败时明确启动失败，业务不能产生数据库或模型调用。
- [ ] lifecycle 固定原child/generation/job；stop优先原IPC shutdown，30秒后force；root提前退出时清理自有余留后代，再观察root实际终态与active0。
- [ ] force后最多5秒，所有poll/deadline清理；失败保留安全错误，不再启动taskkill、不报告成功，不出现未处理rejection。
- [ ] 运行 `node --test desktop/runtime-shutdown.test.cjs desktop/runtime.test.cjs`；业务IPC集成使用真实TSCore、SQLite和受控本地服务，不额外真实付费请求。

## 任务3：main 和构建链集成

**Root 修改：** `desktop/main.cjs`、`desktop/package.json`、`scripts/build_windows.py`、对应打包测试／payload审计脚本。

- [ ] 阅读完整文件与现有实际行为后修改；main 明确消费stop失败并在退出路径保存诊断，最终退出时由OS关闭该实例的Job。
- [ ] bootstrap／owned-runtime加入ASAR白名单，`.node`放 `runtime/owned-runtime/runtime-job.node`；manifest精确包含native源与生成目标，锁文件只作必要一致更新。
- [ ] `python -m unittest scripts.test_build_windows`、相关startup／desktop测试和Windows真实构建。
- [ ] 新包在独立目录普通启动，真实IPC、解析后代、托盘退出、关闭后台及重启不重放复核；新包不能只复用6e历史证据。

## 进度与证据

2026-10-13：Root独立核对旧sidebar／Orca／退出审查104文件绑定、Git index及diff check均通过。native实现尚未开始；产品仍是只读审查的旧Runtime，不能称问题已修复。正式实现和Windows目标平台复验完成后更新本计划状态及主验收报告；Goal仍未完成。
