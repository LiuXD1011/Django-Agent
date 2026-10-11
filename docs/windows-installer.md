# Windows构建与安装

目标Windows10/11 x64。安装器包含Electron、Node22.23.2、Python3.13.16辅助环境、依赖及界面；主业务运行TypeScript，不携带Django、Waitress或Gunicorn。用户无需系统Python、Node.js、Vite、WSL或Docker。

目前已有基线安装器、中文空格路径安装与正式IPC smoke证据。最终源码包、升级和卸载保留数据验收仍在进行，[状态](desktop-refactor/STATUS.md)和[报告](desktop-refactor/TEST-REPORT.md)记录实际结果。

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

构建器按白名单和锁文件准备前端、核心及生产依赖，核对官方Node/Python包哈希并保留许可证。Python的110项依赖和Cairo原生文件由 `scripts/desktop` 与 `desktop/native-windows.lock.json` 管理，正常打包不使用旧根requirements/Django链路。

前端测试包含真实Chromium组件操作，浏览器下载到独立构建缓存。SQLite/FTS/vector、IPC与辅助进程检查使用独立数据。开发依赖只在构建目录，生产payload仅包含production node_modules，用户数据库、密钥、配置和上传文件不进入安装器。

整源码校验、Windows gate和打包后ASAR审计正在统一到构建入口。最终记录需要源码/锁哈希、完整payload清单、安装器SHA和实际检查，旧基线不能证明新包通过。

## 仅准备与启动

```powershell
python scripts/build_windows.py --prepare-only --work-dir 'C:\MarlinBuild'
npm run start:desktop -- --work-dir 'C:\MarlinBuild' --data-dir 'C:\MarlinDevData'
```

`--prepare-only`准备payload和Electron源码壳，跳过NSIS。启动器校验构建器标记及资源，不能直接启动没有payload的 `desktop/`。完整构建文件名由desktop/package.json配置决定，当前为 `Marlin-Setup-0.6.2-x64.exe`，旁边提供 `.sha256` 与无秘密清单。当前本地包未签名，本项目不自动发布。

## 安装、数据与smoke

安装后从快捷方式启动，首次在界面建账号再配置模型。Neo4j、Langfuse和联网服务需单独配置，安装器不提供服务或额度。默认数据 `%LOCALAPPDATA%\Marlin` 与安装目录分离，可用 `--data-dir` 改目录；就绪后关闭窗口隐藏到托盘，托盘“退出”停止自己的后台进程，不监听旧桌面HTTP8899端口。

卸载配置保留数据，升级用新安装包。基线中文空格路径安装与独立账号已验；最终升级/卸载保留、重开登录和模型配置仍需真实复核。

```powershell
& 'C:\安装位置\Marlin.exe' --smoke-test --data-dir 'C:\独立空验收目录'
```

smoke启动隐藏窗口和真实TS核心，输出smoke-result.json/smoke-window.png后正常退出。ok:true要求界面挂载、正式IPC、渲染进程没有Node暴露；不能代表模型/账户/全部页面通过，不得指向真实用户数据。安装、升级、卸载全部使用验收专用目录，见[验收矩阵](desktop-refactor/TEST-MATRIX.md)。
