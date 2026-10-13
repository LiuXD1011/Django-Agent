# 已安装侧栏阶段包：独立副本可见启动准备

本任务仅准备脚本与当前副本只读基线。应用固定为已实际升级的历史 6e37 工件：升级回执 718bd256、artifact binding 3a21d960、安装器 aabd44bc。Root 后续类型筛选修复独立进行，不把 6e37 称为最新全部修复版本。95a8 原脚本不修改、不删除。

选择“原副本只读字节采集 → 自有 snapshot 原生审计 → 独立正常可见启动”。直接沿用旧 clone-audit 的 CoreDatabase 构造会写 WAL/schema，不能用于本轮零写基线；直接 readonly native 连接原文件也不能证明不创建 WAL/SHM。新脚本在原数据库持有 Win32 deny-write/delete 句柄，拒绝非零 WAL，完整采集文件与目录条目，复制数据库与凭据材料到新的专有 snapshot。仅 snapshot 通过安装内 Node/openNativeDatabase readonly/sqlite-vec/CredentialVault 认证全部当前表和加密字段；不会输出行值、明文或密钥内容。原副本完整清单前后必须精确相同。

新审计把 native bigint 与 Buffer 显式编码，逐行产生摘要并排序汇总所有 72 表；算法命名 typed-native-v1。它独立于旧正式备份的 canonical 摘要，不把不同算法强行判等。媒体/配置/密钥仍按原始文件 SHA 核验，保留 24 个本地引用；当前认证表从本轮 fresh 基线采集，允许它们相较旧 ca9 发生正常登录变化。没有认证、HTTP、IPC 或模型请求，没有原始 Linux QA 数据库打开。

候选 normal launcher 默认 review_only，只有 Root 在完整审阅后可执行 visible。入口直接为固定安装目录 Marlin.exe `--data-dir` 固定“浏览器资料副本 20261012 第1轮”，无 smoke/GPU/认证参数。沿用已审 95a8 同句柄退出竞态判断、b12/final2 私有 Job、30 秒 bootstrap reap 和每五秒进程状态；7200 秒上限且持有到 Root 实际托盘退出。安装单实例和 WAL/活动任务前置拒绝保留；25268 的原 FILETIME/路径必须存活，33404 已退出事实只绑定 b357 历史回执。

启动前先重新采集基线并要求等于已审 fresh 基线，拒绝副本在等待期间发生变化。退出后比较本轮 protected_tables、managed_files、protected_desktop_meta（排除 ipc.session/ipc.receipts）、verified_media；允许正常会话/profile增量，仍要求无活跃任务和未结算 auth receipt。它不依赖旧隐藏 smoke/可见诊断被改为 PASS，也不替代真实 GUI 或新正常 hidden 验收。现有失败收据全部保留。

步骤：

- [x] 完整读取 95a8、76e11、d79、b12/final2、实际 native API 类型和凭据 API，绑定 718/3a21/b357 等实际 SHA。
- [x] 在新证据目录保存最小 native snapshot 审计及候选 launcher；检查默认 review_only、语法、BigInt/Buffer 摘要行为，零应用启动。
- [x] 只执行 fresh-baseline：97709 实际 exit 0 / ae0c48，72 表全部当前摘要、79 加密字段认证、24 媒体、116 文件 / 79 目录前后相同；新收据 SHA5b5ef889。原进程/数据库保护通过，0 Auth/模型请求。旧 b357 后 protected 投影通过复用旧 canonical 函数核对；允许认证表变化。
- [ ] Root 阅读全部源码、fresh 回执和 SHA 后再执行唯一 visible；本任务不执行该阶段或 GUI。

唯一归属为 docs/refactor-evidence/20261013-sidebar-clone-launch-preparation、该计划与 /tmp/marlin-agent-sidebar-clone-visible-20261013.py；不改产品、主报告、旧证据或依赖，不提交。
