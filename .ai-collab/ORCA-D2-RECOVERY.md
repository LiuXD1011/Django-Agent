# D2 同Task恢复清单

Task task_3eaaedeb24fd；旧Dispatch ctx_01684d22edc2已失败。2026-10-01：终端显示Killed并回bash，原PID1553995消失而bash1553695仍在；Codex据正面退出证据worker-abandon保留窗口，再重开默认ZCode。不是基于超时重复派发。原业务文件已保留，勿重做/回滚。

本清单为当前Task已批准范围内的验收要求。先处理以下具体问题，再定向测试，按preamble在每次测试后和新文件前check/ack全部协调消息。旧worker长时间未check的意见已合并到这里，不能沿用旧Dispatch capability。

1. /tmp/marlin_codex_d2_probes.py 当前5项全失败，实际日志/tmp/marlin-codex-d2-probes-before.log。修复：migration KeyboardInterrupt/SystemExit等finally回收持有的child；stop_group一项异常仍逐一回收其余child；web/worker早退立即失败而非等60秒deadline；HTTP/sleep只用真实剩余预算、不设延长deadline的最低值；secret必须从初始创建即0600（mkstemp/os.open），不能open0644写完再chmod。
2. run_desktop data_dir expanduser后resolve为绝对路径，所有子进程env/锁/secret/DB一致。子进程cwd源码目录不能使相对路径指向另一个位置。
3. _run_migrate_mode在django.setup之前设置sys.argv为manage.py migrate，避免启动recovery timer误进入迁移。先记录既有DB存在性，再初始化MigrationExecutor（后者会创建空DB）；仅既有DB且有pending migration时备份，fresh不备空库。迁移失败不得启动web/worker；备份内容与恢复路径测试要真实。
4. config.desktop_wsgi _same_origin有效端口正规化，http隐式80与显式80语义等价且仍与绑定端口相符；保持null/external/wrong-port拒绝。
5. test_desktop_runtime垃圾库测试此前使用env DJANGO_DB_PATH，但build_desktop_env覆盖它，结果正常启动并卡住：在实际data_dir/db.sqlite3写垃圾字节，assert非零且未启动web/worker。不是内存导致垃圾库测试正常开服务。
6. 所有stdout.readline即使外层while有deadline仍无界。用reader Queue+timeout或HTTP polling；临时FileLock.acquire必须保留对象或with，不可临时引用被GC立刻释放。双实例真实屏障、无sleep猜时序。
7. 真实进程测试finally首先stdin关闭并bounded wait优雅退出（Windows terminate为强杀，不执行launcher finally），随后才fallback terminate/kill，并回收本次全部owned children，禁止按端口/名字泛杀。任何失败路径不可泄漏测试服务。
8. 命令... | tail ; echo $?得到tail状态不等于测试实际exitcode。使用subprocess.returncode或无pipe保存log再读取，报告真实退出码和未执行项。勿反复420秒全套掩盖已定位卡点。

已有证据仅供避免重复：Codex Linux与Windows原生真实源码启动、静态资源/深链、首次初始化/登录、异站拒绝、第二实例拒绝、优雅停止均已通过，/tmp/marlin-codex-d2-smoke-linux.log、...-windows.log；真实生产WSGI+Chromium登录工作台通过，/tmp/marlin-codex-d2-browser.log。这是草稿阶段主路径证据，不替代以上失败项修复后的最终验收。Windows临时venv已备，不可宣称worker实际运行过。Codex会重验最终版本。

依赖waitress/whitenoise和package start:desktop、README、docs/desktop.md已写入；核对git diff，不要重做已正确内容。D2只改原Task文件，不碰R2A tasks.py/test_task_ownership.py等。源代码运行基础不是安装包，不引入Electron/Tauri/自动更新。graphify由Codex整波运行。报告.ai-collab/ORCA-D2-RESULT.md原子写入，worker_done正式全文件/真实命令exit/未解决项后停；不提交推送合并，不关闭手动终端。
