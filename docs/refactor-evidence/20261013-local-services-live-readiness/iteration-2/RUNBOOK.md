# Root 待执行步骤：尚未消费

本轮只准备。以下命令仅供 Root 审阅；准备者没有执行任何 fixture-control action，甚至没有运行 plan。业务 LANGFUSE_AUTOSTART/TIMEOUT/BASE_URL/HOST 均不继承；不要额外 env=true/false 掩盖正常 UI 保存。`--execute-approved-linux` 是防止把准备材料误当执行授权的门禁，只有 Root 明确安排下一真实阶段才使用。

实际输入：私有根 `/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93`，project `marlin-autostart-live-20261013-3d90135bf46d`；Langfuse `127.0.0.1:3300`，Core `18080`，独立 UI `18173`。Root 使用全新独立 Orca profile：Cookie 不按端口隔离，不能复用 Root QA profile。Core 使用当前已验证 compiled dev CLI，参数名为 `--source-root`，绝对sourceRoot经过可信 `CoreOwner.startDevelopmentLocalServices({sourceRoot}, signal)`；没有 projectRoot 字段或普通 HTTP 命令入口。

1. 审阅 [控制器](fixture-control.source.py.txt)、[独立 UI](fixture-ui.source.mjs.txt)、[私有输入 hash/mode](prepared-fixture.json)及[设计](DESIGN-PLAN.md)。可在未来用下面的无启动 plan 看精确 argv/env names；本轮未运行：

```bash
/home/liuxuedeng/anaconda3/bin/python -B '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/fixture-control.py' plan
```

2. 执行前重新核 protected六IDs/created/image/status/health、project label零碰撞、端口空闲、MemAvailable≥14GiB、disk free≥10GiB。该 14GiB=6GiB新栈工作预算+8GiB既有工作保留，是保守操作门槛，不是镜像官方最低内存保证。程序在启动与运行期间也检查8GiB保留；降低后会取消自有Core/UI并报失败。长期容器按产品行为不会自动down，Root随后需明确执行本project cleanup，因此仍须主动监控资源；门槛不能替代运行中压力监控。

3. Root 首次 default-off 开独立Core/UI。为准确记录真实 CLI exec/exit，使用已存在的 `/usr/bin/strace`，只跟踪自己的 controller/Node 后代 process syscalls。私有 trace/log 0600，不归档原始值，禁止加 `-v` 展开环境；公开回执只提取固定 compose argv/PID及对应exit，区分controller前置只读Docker probes和Core实际startup子树。若 ptrace 不可用，记录环境失败，不把未捕获事件视为zero。

```bash
umask 077
/usr/bin/strace -f -e trace=%process -s 256 -o '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/receipts/initial.exec.trace' /home/liuxuedeng/anaconda3/bin/python -B '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/fixture-control.py' run --phase initial --execute-approved-linux
```

这是长期运行命令，Root记录真实工具session与controller/Core/UI PID/startTicks。Node ready 后独立UI `http://127.0.0.1:18173` 才可用。Orca在这个新实例实际初始化自己的管理员；口令由Root在新UI输入，不写报告/代码。去Langfuse设置保存API base `http://127.0.0.1:3300`，保持tracing/auto_login关闭，不需要任何真实Key；保存timeout=120与autostart=true，记录实际UI回填及非秘密配置。初次default-off应显示disabled，Core实际startup子树零compose config/up，fixture project零容器。

4. 在另一工具调用用精确pidfd停止自有controller。它给捕获的Core/UI pidfd发送SIGTERM，dev CLI原AbortSignal/Owner.close/registry负责自己的CLI后代；等待原strace工具和current-run/terminal receipt全部终态，children exit均0后才重启。stop命令exit0只说明信号已送达，不等于原session已退出。超过30秒会保留unreaped_owned_pids且原run exit1，没有按名称/端口kill、没有盲强杀；Root须据PID/startTicks另处理，不能重开覆盖未终态旧实例。

```bash
/home/liuxuedeng/anaconda3/bin/python -B '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/fixture-control.py' stop --execute-approved-linux
```

5. 当前dataRoot与UI保存值不变，重启saved-true阶段，四个业务environment override全unset。必须观察Core子树实际固定config --quiet exit0，再up -d exit0；private startup.json=healthy、本fixture独立端口的真实health HTTP200、Core HTTP正常、六个新container/volumes/network project归属和原六容器身份/health保留。用下述精确端口，不使用既有3000 health。

```bash
umask 077
/usr/bin/strace -f -e trace=%process -s 256 -o '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/receipts/saved-true.exec.trace' /home/liuxuedeng/anaconda3/bin/python -B '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/fixture-control.py' run --phase saved-true --execute-approved-linux
```

程序外部startup watchdog180秒包含Core Owner30秒等等待，不能更改生产服务单一1–120秒工作预算。cold start若超过120则保存startup_timeout，并核Core HTTP仍正常；再次尝试单列phase/新trace/terminal receipt，不覆盖原失败。原始private日志保留，公开证据只能提取非秘密状态、argv、exit及SHA，不能输出compose config/env或container env/log。

6. 同一独立Orca UI实际保存autostart=false，确认回填，然后重复stop并等待终态，再运行saved-false：

```bash
umask 077
/usr/bin/strace -f -e trace=%process -s 256 -o '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/receipts/saved-false.exec.trace' /home/liuxuedeng/anaconda3/bin/python -B '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/fixture-control.py' run --phase saved-false --execute-approved-linux
```

应为disabled与Core startup子树零compose config/up；此前本project长期containers仍保留，不能要求false或Core.close把它们down。保存true/false步骤由Root UI完成，准备者没有代写DB、接口或配置。实际trace/GUI/状态/终态观察均为待执行，不由语法/config0替代。

7. 测试完成后stop并等真实终态。若Root决定移除本fixture stack，用以下显式project cleanup；它先核原六protectedIDs/created/image仍在，核project当前容器ID/created/image与自己的资源receipt相符，拒绝未知project资源；只对唯一project运行down --volumes，不删除本dataRoot，也不碰既有3000服务/卷：

```bash
/home/liuxuedeng/anaconda3/bin/python -B '/tmp/Marlin autostart 20261013 3d90135bf46d mpuaue93/fixture-control.py' cleanup-project --execute-approved-linux
```

cleanup root exit0仍须核project剩余容器/volumes/network零、原六与3000 health继续正常。最初project容器/网络/卷零碰撞事实见 [project检查](project-no-collision.json)。程序down只核容器receipt；Root须在cleanup前额外核该project网络/五卷label与本轮创建记录，任何未知资源不执行down。无project的compose down、prune、按端口/名称kill和读取RootQA/private-auth/Keys均不属于此计划。

运行程序尚未实际验收，只做Python/Node语法与fixture config --quiet检查。Root应先审程序及这些明确限制；若源码/依赖/目录/端口有变化，按具体变化重新绑定，不重跑已稳定current324整套或借旧Django。
