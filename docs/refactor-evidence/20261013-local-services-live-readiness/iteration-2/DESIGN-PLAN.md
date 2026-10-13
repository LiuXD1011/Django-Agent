# 独立真实 Linux autostart fixture 准备方案

Root 已明确授权本轮只准备可审核输入，不执行 Docker up/down、Core、Vite 或 GUI。此方案继承已接受的独立 project/source/env/data 设计；真实执行与 Orca 保存仍交给 Root。

- [x] 完整读当前 dev CLI、Owner client/host/contracts 及实际 dist 类型；可信入口准确为绝对 `sourceRoot` / `--source-root`，不向 HTTP/renderer 传 project/env/argv。
- [x] 当前工作区 compose 与公开 HEAD SHA 均为 `34b365a66ca7f97867547fcb956dfe148f4d783f33499b87f8a0e27664404062`，字节相同；实际工作区为复制基线。
- [x] 核六服务全部端口/卷/名称：仅 web 的 127.0.0.1:3000；五 local named volumes，无固定 container/project name、外部卷或网络。
- [x] 只读采现有六容器 ID/created/image/status/health 与资源样本；宿主约 15.4 GiB MemAvailable，既有栈约 3.4 GiB。无 healthcheck 是 null，不冒充 unhealthy。
- [x] 建专属 0700 中文空格临时根，source/data/cache/receipts 子目录；合成 .env 0600，仅记录路径、SHA 和变量名，不归档秘密字节。
- [x] 唯一 Compose project；只改变 fixture web host 端口，其余真实 pinned 六服务/depends_on/卷语义保留。六服务是公开真实 Langfuse 栈，不能缩为 mock health 或借用既有数据库凭据。
- [x] 准备当前 compiled Core 与独立 Vite 的启动控制器和 UI server 程序；均默认 plan/no-start，实际 run/stop/cleanup 需 Root 明确执行旗标。运行前需至少 14 GiB MemAvailable（6 GiB 新栈工作预算 + 8 GiB 给既有测试的保守保留；这是操作门槛，不是镜像官方内存保证）、10 GiB disk free、原基线仍 healthy/running、无端口/project冲突。启动后 Root 持续观察，任何资源压力均记录并暂停，不扩大栈规模。
- [x] 真实 UI 使用独立 Vite 端口与 proxy 指向自有 Core；不得用既有5173 proxy到8000。Vite cache/env/config全独立，真实 Vue组件仍取当前源码。Root 使用全新独立 Orca profile，Cookie 不按端口隔离，不复用 Root QA profile。
- [ ] Root 后续先 initial/default-off 启动与初始化，在自己的 UI 保存 API base为fixture IPv4端口、timeout和autostart=true；正常精确退出/restart后验真实 CLI/health/state，再保存false、精确restart、验零启动。业务 LANGFUSE_AUTOSTART/TIMEOUT/BASE_URL/HOST 全 unset，不用env true掩盖保存值。
- [x] 语法和静态来源/权限/隔离检查；不执行 prepared helper，不执行 suite/build。自有 preparation helper用完归档精确删；未消费运行程序保留在私有根，说明等待Root review与UI保存的原因。

取消与清理：controller捕获每个实际Popen、PID/startTicks及pidfd，SIGTERM只发给同一自有句柄，并等待子进程终态；取消先触发dev CLI原AbortSignal/Owner.close/registry清理。超时或终态未证实不推测成功，不按端口/名称kill。长期container不会随Core.close自动down；如Root后续决定清理，只按该唯一project、匹配标签/created/ID、保护原六IDs，并执行自有fixture compose down/volumes。第一次cold startup预算失败与后续retry分别保存，不改原失败。

两种替代均未采用：复用既有服务/凭据缺少隔离且不能证明创建链；mock CLI/health不能算真实Docker/Langfuse。全栈配置可准备，但本轮不启动，不把配置有效/镜像已缓存/语法通过写成autostart PASS。
