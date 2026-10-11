# 桌面运行

主业务是 `packages/core` 的 TypeScript 核心，桌面壳是 `desktop` 的 Electron。界面从随包资源加载，通过受控 preload/IPC 访问核心；Python仅承担解析和Ragas，不直接写业务数据库。正常桌面启动不需要Django、HTTP服务或Vite。

Windows x64是当前验收目标。macOS/Linux的桌面打包未验证。见[测试报告](desktop-refactor/TEST-REPORT.md)和[Windows构建与安装](windows-installer.md)。

## 安装版与数据

通过快捷方式或Marlin.exe启动。默认 `%LOCALAPPDATA%\Marlin` 保存数据库、媒体、任务、配置、凭据与 `desktop-profile`，程序保存在安装目录。

```powershell
& 'C:\安装位置\Marlin.exe' --data-dir 'C:\MarlinData'
```

首次在登录页注册或初始化，自行填写密码。源码工作区的数据与模型不会自动复制过来，迁移需显式执行[导入工具](desktop-refactor/MIGRATION.md)。API Key只在设置填写，核心加密保存，不向渲染进程回显。

## 窗口与退出

- 就绪后关闭窗口隐藏到托盘，任务可继续。
- 托盘“打开Marlin”恢复窗口，“退出”等待本应用核心与任务清理。
- 第二次启动恢复已有实例；启动失败保留数据并说明目录。

这是当前实现语义。窗口隐藏、单实例已有部分实际验证，最终包托盘退出与异常重开的完整GUI验收仍在进行，维护强制停止不算正常退出。

## 源码模式

原生Windows x64 Python3.13负责准备完整payload和Electron壳，开发机需要Node/npm，已验证Node22.23.2：

```powershell
python scripts/build_windows.py --prepare-only --work-dir 'C:\MarlinBuild'
npm run start:desktop -- --work-dir 'C:\MarlinBuild' --data-dir 'C:\MarlinDevData'
```

Node启动器核对构建目录和资源后直接启动Electron。缺少资源或校验失败需要重新准备；启动器不下载依赖、不初始化账号、不运行旧Django入口。源码在WSL时使用原生Windows工具，npm/NSIS工作目录使用本地Windows路径，详见[Windows说明](windows-installer.md)。

## 浏览器与检查

先 `npm run build`，再 `npm run start:local -- --data-root <独立目录>` 与 `npm run dev`。解析/评测参数和依赖见[README](../README.md)。Orca通过该HTTP适配测试同一核心，安装版不使用HTTP/Vite入口。

检查分为 `npm run test:core`、`npm run test:frontend`、`npm run test:desktop` 和 `npm run test:startup`。真实点击、厂商模型和安装验收独立记录，见[验收矩阵](desktop-refactor/TEST-MATRIX.md)。

退出后备份完整数据目录，包含媒体、`.secrets` 与 `.settings`。只备份数据库不能恢复全部凭据与源文件。import/backup/restore和实际核对见[迁移说明](desktop-refactor/MIGRATION.md)，不要生成新密钥覆盖缺失或损坏的原密钥。
