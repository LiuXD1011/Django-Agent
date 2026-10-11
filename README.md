# Marlin · 个人轻量知识库

基于 TypeScript、Electron 和 Vue 3 的个人知识工作台。独立 TypeScript 核心承担主业务，SQLite 保存本地数据；Python 辅助进程负责文档解析和 Ragas 评测。正常桌面链路不运行 Django、Waitress 或 Gunicorn。

本次交付目标是 Windows x64。基线安装和部分真实业务已验证，最终包、全部页面操作和升级/卸载验收仍在进行。实际进度见[重构状态](docs/desktop-refactor/STATUS.md)和[测试报告](docs/desktop-refactor/TEST-REPORT.md)。

## 功能

- 文档工作台：上传、解析、分块、标签、筛选、重解析、取消和来源定位。
- 混合检索：FTS5、sqlite-vec、权限与知识库过滤、Rerank、父子分块。
- 对话与 Agent：流式回答、停止与恢复、工具、子任务、附件、引用和可配置记忆。
- Wiki：生成、双链、编辑、删除、目录、来源及 Markdown/表格/代码/公式/图片渲染。
- 图谱：实体、关系、来源、可选 Neo4j，以及旧图只读迁移工具。
- 模型：对话、Embedding、ReRank、视觉四角色，思考参数和用量记录。
- 评测：题目审核、数据集版本、后台运行、取消/恢复、历史和报告。
- 可选集成：MCP、联网搜索和 Langfuse，基础桌面使用无需 Docker。

## Windows 使用

安装包包含 Electron、Node.js、Python 辅助环境、依赖和界面，用户无需系统 Node.js、Python、Vite 或 WSL。首次在界面建立账号，在模型管理配置模型；安装器不附带 API Key 或模型额度。

数据默认在 `%LOCALAPPDATA%\Marlin`，与安装目录分离。就绪后关闭窗口隐藏到托盘，托盘“退出”结束程序及其自身后台进程。卸载配置保留数据，最终实际验收状态以报告为准。

见[桌面运行](docs/desktop.md)和[Windows 构建](docs/windows-installer.md)。macOS/Linux 的桌面打包与交付尚未验证。

## 浏览器开发与 Orca 测试

已验证 Node22.23.2。安装锁定依赖并构建：

```bash
git clone https://github.com/LiuXD1011/Django-Agent.git
cd Django-Agent
npm --prefix packages/core ci
npm --prefix frontend ci
npm run build
```

两个终端分别启动 TypeScript 核心和 Vue，明确使用独立开发数据目录：

```bash
npm run start:local -- --data-root /path/to/marlin-dev-data
npm run dev
```

页面为 `http://localhost:5173`，核心默认仅监听本机8000端口。该入口让 Orca 连接同一业务核心；正式 Electron 使用 preload/IPC 和随包界面。

实际解析和评测需要独立 Python 环境中的[解析依赖](workers/document/requirements.txt)和[评测依赖](workers/evaluation/requirements.txt)，以及配对参数：

```bash
npm run start:local -- --data-root /path/to/marlin-dev-data \
  --python /path/to/python --parser-worker workers/document/worker.py \
  --ragas-python /path/to/python --ragas-worker workers/evaluation/worker.py
```

安装版已携带辅助环境，无需上述开发配置。密钥只在应用设置填写，不放入启动参数、根环境文件或源码。

## 源码桌面与检查

在原生 Windows x64 Python3.13、Node/npm 的构建机准备完整运行目录，再用 Node 启动该目录的 Electron：

```powershell
python scripts/build_windows.py --prepare-only --work-dir 'C:\MarlinBuild'
npm run start:desktop -- --work-dir 'C:\MarlinBuild' --data-dir 'C:\MarlinDevData'
```

`--work-dir` 必须属于构建器。缺少payload的 `desktop/` 不能独立启动；省略 `--prepare-only` 生成NSIS。参数和构建边界见[Windows说明](docs/windows-installer.md)。

```bash
npm run typecheck       # TypeScript核心类型检查
npm run test:core
npm run test:frontend   # 包含真实浏览器组件测试
npm run test:desktop
npm run test:startup
npm run build          # 核心与界面生产构建
```

`npm test` 顺序运行上述测试；真实 Orca 点击、正式 Electron 与安装验收另行记录。旧数据导入前先完整备份，不对原库重放旧 Django migrations，详见[迁移说明](docs/desktop-refactor/MIGRATION.md)。

## 贡献与许可证

欢迎通过 Issue 和 Pull Request 参与。开发规则见[AGENTS.md](AGENTS.md)，范围与验收见[重构规范](docs/desktop-refactor/SPEC.md)。本项目采用[MIT许可证](LICENSE)；随包运行环境、原生库与算法保留各自许可证和来源说明。

感谢 [Tencent/WeKnora](https://github.com/Tencent/WeKnora)、[XiaomiMiMo/MiMo-Code](https://github.com/XiaomiMiMo/MiMo-Code)、[Ragas](https://github.com/explodinggradients/ragas)、[Vue](https://vuejs.org/)和 [Electron](https://www.electronjs.org/)。
