# Windows构建与安装

目标Windows10/11 x64。安装器包含Electron、Node22.23.2、Python3.13.16辅助环境、依赖及界面；主业务运行TypeScript，不携带Django、Waitress或Gunicorn。用户无需系统Python、Node.js、Vite、WSL或Docker。

最终v2安装器已完成中文空格路径的隔离升级、实际打包Electron到TS核心门禁，以及正常登录、问答引用、托盘退出和重启恢复。最新包卸载保留数据等长尾项未验证；安装器路径与SHA见[最终报告](desktop-refactor/FINAL-REPORT.md)，各阶段失败和实际范围见[测试报告](desktop-refactor/TEST-REPORT.md)。旧Django源码的退役范围见[清理说明](desktop-refactor/LEGACY-CLEANUP.md)。

## 构建机与命令

需要原生Windows x64 Python3.13、Node/npm、网络和本地构建目录。已验Node22.23.2；锁定工具要求 `^22.22.2 || ^24.15.0 || >=26`，不能仅按版本大于22判断。所选node.exe同目录需有 `node_modules/npm/bin/npm-cli.js`。

```powershell
python scripts/build_windows.py --work-dir 'C:\MarlinBuild'
```

源码位于WSL也可用PowerShell调用原生工具；示例工具路径替换为本机实际位置：

```powershell
& 'C:\Python313\python.exe' '\\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\scripts\build_windows.py' `
  --work-dir 'C:\MarlinBuild' `
  --build-node 'C:\Tools\node-v22.23.2-win-x64\node.exe' `
  --node-cache 'C:\MarlinNodeCache' `
  --output-dir 'C:\MarlinInstallers'
```

`--work-dir`使用空目录或构建器有标记的专用目录，不能指向用户数据或其他项目。npm/NSIS不在UNC工作目录运行。默认输出项目根 `dist/windows`。

## 资源与检查

构建器按白名单和锁文件准备前端、核心及生产依赖，核对官方Node/Python包哈希并保留许可证。Python的110项依赖和Cairo原生文件由 `scripts/desktop` 与 `desktop/native-windows.lock.json` 管理；解析与评测使用各自worker依赖，正常打包不使用旧根requirements/Django链路。

前端测试包含真实Chromium组件操作，浏览器下载到独立构建缓存。SQLite/FTS/vector、IPC与辅助进程检查使用独立数据。开发依赖只在构建目录，生产payload仅包含production node_modules，用户数据库、密钥、配置和上传文件不进入安装器。

构建入口已执行源码与锁哈希核对、Windows gate、完整payload清单和打包后ASAR审计；正式打包还检查实际Electron通过物理bootstrap启动随包Node及TS核心。最终v2结果绑定安装器SHA和实际检查，旧基线不能证明新包通过。此次旧源码清理不修改这些构建输入或重打安装器。

## 仅准备与启动

```powershell
python scripts/build_windows.py --prepare-only --work-dir 'C:\MarlinBuild'
npm run start:desktop -- --work-dir 'C:\MarlinBuild' --data-dir 'C:\MarlinDevData'
```

`--prepare-only`准备payload和Electron源码壳，跳过NSIS。启动器校验构建器标记及资源，不能直接启动没有payload的 `desktop/`。完整构建文件名由desktop/package.json配置决定，当前为 `Marlin-Setup-0.6.2-x64.exe`，旁边提供 `.sha256` 与无秘密清单。当前本地包未签名，本项目不自动发布。

## 安装、数据与smoke

安装后从快捷方式启动，首次在界面建账号再配置模型。Neo4j、Langfuse和联网服务需单独配置，安装器不提供服务或额度。默认数据 `%LOCALAPPDATA%\Marlin` 与安装目录分离，可用 `--data-dir` 改目录；就绪后关闭窗口隐藏到托盘，托盘“退出”停止自己的后台进程，不监听旧桌面HTTP8899端口。

卸载配置保留数据，升级用新安装包。最终v2隔离升级后数据库及密钥哈希保持，正常重开恢复验收身份、知识库和已有问答引用；模型配置保留。最新包卸载保留数据尚未实测。

```powershell
& 'C:\安装位置\Marlin.exe' --smoke-test --data-dir 'C:\独立空验收目录'
```

smoke启动隐藏窗口和真实TS核心，输出smoke-result.json/smoke-window.png后正常退出。ok:true要求界面挂载、正式IPC、渲染进程没有Node暴露；不能代表模型/账户/全部页面通过，不得指向真实用户数据。安装、升级、卸载全部使用验收专用目录，见[验收矩阵](desktop-refactor/TEST-MATRIX.md)。
