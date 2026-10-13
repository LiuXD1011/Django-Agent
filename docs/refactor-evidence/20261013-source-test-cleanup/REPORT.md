# Source 专用验收设备与服务清理

2026-10-13。Root授权本轮必要清理，实际helper工具5050e0 exit0。原001–008界面尝试保留，未生效的菜单指针不计UI注销PASS；本轮是程序化合法API与原pidfd清理。[实际结果](cleanupresult.json)、[helper原文](cleanup-helper.source.py.txt)。未改production、主四文档、Git或Windows安装版数据。

完整读取实际AuthService/AuthReader、HTTP cookie/CSRF和应用auth路由、对应契约与查询入口。只从0600私有QA文件在内存读取既有口令，经普通CSRF＋cookie login，返回email匹配专用`orca-page-qa-20261010@example.invalid`且user UUID UTF8 SHA为cba6980f446f99647ab03db2c3da397b0d1cf26dfb703005a4fc3cd915b826aa。仅逐个DELETE该Root自建QA账号5个仍活跃的专用web设备，均HTTP200，再logout本轮新cleanup设备200，随后me401；QA未撤销设备为0。未使用logout-all、改密码、删账户/库/模型或触碰其他用户设备，口令/token仅内存，未写argv、日志或报告，没有读取API Key。

只读前后usage174、desktop_jobs/task_records active0；其他用户设备的撤销状态SHA相同，users/knowledge_bases/knowledges/models数量相同。私有QA口令文件0600和SHA保持，继续供最后Windows合法登录；SourceQA数据库、Key和媒体保留。不将合法认证会话变化误报为全库字节不变。

Core4156949/startTicks26982794、Vite3622392/startTicks26564747及唯一所属esbuild3622788/startTicks26564982在发信号前核exe/cwd/精确argv及原父子关系，通过Linux x64 pidfd_open syscall434保留原句柄，pidfd_send_signal syscall424发送SIGTERM，等待原fd终态，三个句柄均关闭。Core当时无process children；Vite唯一esbuild原fd也终态，没有名称/端口kill或向同端口新进程发信号。后置三个原PID均不存在，8000/5173只读connect为111。原session68767/52034由本agent读取均报Unknown process id，因此不写session exit0或推测OS退出码；Root可从其原工具另确认。

首助手在只读业务计数阶段误用表名knowledge，actual1、auth/API/stop动作均0；真实表是knowledges，仅修自有helper后实际0。保留[首失败](cleanup-initial.actual1.json)及[原helper](cleanup-helper.initial.source.py.txt)，没有重复登录或业务操作。执行过的自有临时helper在与归档逐字/SHA核对后精确删除；没有新freeze、全量证据审计或模型重跑。[执行与工具观测](cleanup-execution.json)、[助手消费](helper-cleanup.json)。
