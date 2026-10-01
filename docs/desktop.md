# 本地桌面运行（MARLIN-D2 最小运行入口）

本文档描述把本项目当作**本地桌面应用**运行的源码级入口：`scripts/start_desktop.py`。
它面向"在本机跑起来、数据放在用户目录"的交付基础，**不是**已签名/已打包的桌面安装
程序——没有 Electron/Tauri、没有安装器、没有自动更新与代码签名。通用部署
（gunicorn + `config.wsgi`）和开发入口（`manage.py runserver`、`npm run dev`）
均不受影响，照常使用。

## 前置条件

- Python 3.10+，并安装依赖：`pip install -r requirements.txt`
  （桌面运行额外需要其中的 `waitress>=3.0,<4` 与 `whitenoise>=6.12,<7`）。
- 已构建的前端产物：`frontend/dist/index.html` 与 `frontend/dist/assets/`。
  缺失时入口会直接报错退出，并提示先在 `frontend/` 执行 `npm run build`；
  **桌面入口永远不会自动执行 `npm install` / `npm run build`**。

## 启动

```bash
# 推荐入口（等价于 python scripts/start_desktop.py）
npm run start:desktop

# 指定数据目录 / 端口 / 不开浏览器
python scripts/start_desktop.py --data-dir "D:\MarlinData" --port 8899 --no-browser
```

参数说明：

- `--data-dir`：数据目录，缺省 Windows 为 `%LOCALAPPDATA%\Marlin`，其他平台为
  `$XDG_DATA_HOME/marlin`（未设 XDG 时 `~/.local/share/marlin`）。路径含空格安全。
- `--port`：TCP 端口，缺省 8899，合法范围 1..65535，始终只绑定 `127.0.0.1`。
- `--no-browser`：不自动打开系统浏览器（无人值守验收用）。

启动流程（全部由该入口编排，失败即整组退出并清理）：

1. 在数据目录获取非阻塞实例锁（`instance.lock`）——同一数据目录重复启动会被
   清楚拒绝；入口从不删除数据或锁文件来绕过冲突。
2. 持锁期间创建/读取持久应用密钥 `secret.key`（原子写入、POSIX 0600 权限）。
   已存在非空密钥则复用；存在但为空的密钥文件会报错拒绝，绝不静默替换。
   密钥内容不会被打印或写进日志。
3. 执行数据库迁移；若已存在数据库且仍有待迁移项，先经 SQLite backup API 在
   `data/backups/` 生成 `pre-migrate-*.sqlite3` 备份（无待迁移项时不重复备份）。
   迁移失败则 web 与 worker 都不会启动。不复制/移动旧项目数据库。
4. 启动两个子进程（均为 `sys.executable` 直连 `Popen`，列表参数，不经 shell，
   路径含空格安全）：
   - web：Waitress 服务器，**仅监听 `127.0.0.1`**，由 `config/desktop_wsgi.py`
     提供生产形态的静态资产服务（见下）；
   - worker：`manage.py run_task_worker --queue evaluation`（文档队列任务由 web
     进程内现有机制执行，桌面不重复开 documents worker）。
5. 健康检查：探测 `http://127.0.0.1:<port>/health`，除 HTTP 200 外还必须命中本次
   启动随机生成的 `X-Marlin-Desktop-Instance` 响应头——端口被其他健康服务占用时
   不会误判成功。所有等待/探测都有超时且禁用系统代理。
6. 健康通过后才（可选）打开系统浏览器。

退出与清理：Ctrl+C、关闭管道（stdin EOF）或 SIGTERM 都会优雅停止；任何退出路径只
对**本入口自己拉起的子进程**做 terminate → 有限等待 → kill，绝不按端口或进程名泛化
杀掉其他服务；`finally` 中释放实例锁，不会遗留后台服务。

## 桌面 WSGI 边界（config/desktop_wsgi.py）

- WhiteNoise 只从**源码根**的 `frontend/dist/assets` 提供 `/assets/`（自带跨平台
  MIME 表，JS/CSS 类型不依赖 Windows 注册表）；SPA 深链、`/health`、API 与经鉴权的
  `/files` 全部仍由 Django 处理。不使用 Django 开发 static 视图，不暴露整个用户目录。
- 带 `Origin` 的 API 写请求只接受本机同源（loopback 主机 + 实际端口完全一致）；
  `Origin: null` 与外部站点一律 403。本机 CLI 无 Origin 请求照常放行，Django 的
  Host 白名单（`DJANGO_ALLOWED_HOSTS`）继续生效。
- `/api/v1/auth/auto-setup` 仅接受 POST（GET 无法建号）；token/初次密码相关响应
  `Cache-Control: no-store`，密钥与密码不落日志。

## 子进程环境（由桌面入口强制设置）

`DJANGO_DEBUG=false`、`DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost`、
`APP_DATA_DIR` 与 `DJANGO_DB_PATH` 指向所选数据目录、`LANGFUSE_AUTOSTART=false`、
`NEO4J_ENABLE=false`、`LANGFUSE_ENABLED=false`（后两项仅在用户进程未显式 opt-in 时
强制为 false；仓库 `.env` 无法重新启用，因为 settings 的 dotenv 只填充缺失键）。
`ALLOW_AUTO_SETUP=true` 只由本桌面入口设置；全局 `.env` 与通用部署保持默认关闭。

通用生产设置（`DJANGO_DEBUG=false` 且无 `DJANGO_SECRET_KEY` 环境变量）仍然会因
缺少密钥而拒绝启动——桌面密钥文件不会被 settings 自动读取。

## 首次初始化

桌面模式允许首次管理员初始化（前端登录页点击初始化），后端生成 `admin` 账号并
在响应中返回**临时密码**，由用户自行保存并按要求修改；默认不启用 Neo4j 与
Langfuse。涉及模型对话、Embedding、Rerank、VLM 等功能需要另行配置模型 API，
未配置时相应功能不可用，界面与文档如实提示。

## 测试

```bash
python manage.py test personal_knowledge_base.test_desktop_runtime
```

覆盖：真实临时目录的密钥生成/重启保持/空文件拒绝、跨进程双实例拒绝、缺 dist
失败、真实迁移（含一次性备份与垃圾库失败）、端口占用、健康实例头不匹配、
worker 提前退出、启动超时、停止清理、WSGI 资产/深链/边界（异站 Origin 拒绝且
数据库零残留、合法 POST 可初始化）、settings 契约（生产缺密钥仍报错、
auto-setup 默认关闭）。测试全部使用白名单环境与临时 DB/数据路径，不读写真实
工作数据、凭据或外部服务。

## 明确不包含

安装包/签名/自动更新、真实用户数据演练、任务恢复语义变更（R2 另行处理）、
以及任何对通用部署路径的修改。本文档描述的是**本地源码运行交付基础**。
