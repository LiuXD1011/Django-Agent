# 6e 历史安装包：正常副本可见启动准备

本目录已完成准备检查及唯一实际只读 fresh 基线，尚未启动应用。固定 installed 身份来自升级 718bd256 / binding 3a21d960 / source 6e37；Root 的新源码迭代不在本历史包中。95a8 原脚本和旧失败收据全部保留。

完整候选为 [reviewed-harness.source.txt](reviewed-harness.source.txt)，117 行，SHA256 `f2641b60539c55d58ee75f853e294479d03cc45c10a9490b17acd4ae27e8fa18`；临时执行入口 `/tmp/marlin-agent-sidebar-clone-visible-20261013.py`。纯 snapshot 审计 [snapshot-audit.mjs](snapshot-audit.mjs) 为 80 行，SHA256 `85a9c77585afa2e82e760490027e53bcac1e6918d3c302a02d3552597f9416d9`。范围及旧 audit 构造写入边界见 [设计](../../desktop-refactor/SIDEBAR-INSTALLED-CLONE-LAUNCH-PLAN.md)。

[准备检查](preparation-checks.json)：Linux 与原生 Windows Python 默认 review_only 实际退出 0，无 Win32 SDK/产品调用或资料读取。六项 BigInt/Buffer/键顺序/REAL 特殊值摘要检查通过，只属于纯函数夹具；源已归档、临时 guard 已删除。最后实际 Node 语法检查 0 / fe0eec，Python AST 与 archive/hash/95a8 不变检查 0 / 8d1a9f，均绑定最终上述 SHA。

实际 fresh 基线会话 97709 / exit 0 / ae0c48，收据 [fresh-clone-baseline.json](fresh-clone-baseline.json) SHA256 `5b5ef889ed5503f90d4d259e04d040e27cfa6f59ccac7e96b4294a991b051848`。全部 72 张当前表 native typed 摘要、68 张保护表、79 个加密字段认证、24 个本地媒体通过。原副本 116 文件 / 79 目录条目、25 managed 文件原始摘要前后完全相同；legacy 保护投影匹配 b357 后记录。当前用户 3 / device_sessions 26 / refresh_tokens 130 / desktop_meta 54，未强行匹配旧 ca9 认证计数。审计 Node 8808.104 ms，private Job/Bootstrap 0，正常收尾 0.028 ms，零终止；不是应用启动或产品延迟。

安装 prefix 活动进程前置已实际通过，原 25268 的固定 FILETIME/路径保护及持有句柄退出检查通过，竞态观察为空。Root 协调线程中断的实际观察已单列在启动回执；没有把等候当作新的权限，执行严格限于本任务已授权的只读基线，候选进程存在则会在副本读取前拒绝。原副本数据库没有 SQLite 连接，只有字节/哈希读取；凭据解密仅发生于自有 snapshot，0 Auth/HTTP/IPC/模型请求。

实际执行过的只读基线参数为下列命令，现已消费，不重放：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-sidebar-clone-visible-20261013.py --phase fresh-baseline --execute-reviewed --reviewed-script-sha256 f2641b60539c55d58ee75f853e294479d03cc45c10a9490b17acd4ae27e8fa18
```

该阶段只读取固定已恢复副本的字节与摘要，在新的自有 snapshot 上通过 installed native API 验证当前全部表、加密字段和媒体；原副本前后文件/目录必须全部相同。旧 b357 后的 protected 业务/meta/media/key 摘要仍须相同，认证计数不要求等于旧 ca9。解密值与密钥内容不输出，不发认证/HTTP/IPC/厂商请求。

Root 完整审阅 fresh 回执后，才可运行同一脚本 `--phase visible --execute-reviewed --reviewed-script-sha256 f2641b60539c55d58ee75f853e294479d03cc45c10a9490b17acd4ae27e8fa18 --baseline-sha256 5b5ef889ed5503f90d4d259e04d040e27cfa6f59ccac7e96b4294a991b051848`。visible 尚未调用；它仅正常 `Marlin.exe --data-dir`，Root 独占实际 GUI；私有 Job 持有到托盘退出，随后独立后置审计。没有依赖旧隐藏失败被改成成功，不替代新 hidden 或实际侧栏验证。
