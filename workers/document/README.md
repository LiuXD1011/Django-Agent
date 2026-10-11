# 独立文档解析 worker

从旧 `personal_knowledge_base/document_parsing` 的纯解析模块提取，保留项目 [MIT 许可证](LICENSE)。旧后端文件未修改。入口是 [worker.py](worker.py)，仅做文档解析与图片产物，未实现分块、模型调用、OCR/Caption、账户或业务数据库访问。

## 协议和调用

协议严格对应 [core contracts](../../packages/core/src/contracts.ts)：UTF-8 NDJSON，`protocol: 1`，`id`，`operation: capabilities | parse`；一次进程接收一条请求后退出。stdout 只输出 `result/error`，原生依赖诊断重定向到 stderr。TS 支持契约中的 progress 消息，当前 worker 只输出终态。

```json
{"protocol":1,"id":"job-1","operation":"parse","input":{"path":"/controlled/job/source.txt","name":"source.txt","sha256":"<64 lowercase hex characters>","size_bytes":123},"artifact_dir":"/controlled/job/artifacts","options":{"engine":"builtin"},"limits":{"max_input_bytes":67108864,"max_artifact_bytes":134217728,"max_pages":1000,"max_images":2000}}
```

输入须为绝对路径的常规文件，并核对大小与 SHA-256。产物目录须为当前 job 的新建空目录。仅接受旧上传白名单，不将未知二进制格式回退成文本。options 当前只有 `engine`（builtin/plain）；未知选项和不合法限额报错。worker 硬上限：请求 64 KiB、输入 64 MiB、图片产物合计 128 MiB、1000 页/幻灯片、2000 张图片；Office ZIP 展开总量 128 MiB、最多 100000 个条目。页数预检适用于 PDF/PPTX 及转换后的 PPT，不推测 DOCX 排版页数。

正文按有序 text blocks 以双换行拼接；`canonical_range` 是 0-based、end-exclusive 的 Unicode code point 范围，非 BMP 字符算一个。DOCX body 编号、PPTX slide、Excel row、PDF bbox 坐标在 `provenance`，不用于切片正文。表格 `rows/cells`、record `headers`、标题/字体/置信度保留在 metadata；页、段落、行、公式/单元格、shape_path 和合并范围保留在 provenance。契约未在 warnings 中定义的旧 `source_ref` 保留为 `diagnostics.warning_sources`，按 warning_index 对齐。

每个 image block 含 job 内相对 `artifact_path`、实际字节 SHA-256、实际输出 MIME、原始 MIME 和尺寸。SVG 实际写 PNG，原始 MIME 是 `image/svg+xml`；禁止 SVG 外部文件/网络/CSS 引用，内嵌 data image 可用。扫描 PDF 真正渲染为 150 dpi JPEG 页图，`ocr_performed: false`；没有识别文字或模型调用。

[DocumentParser](../../packages/core/src/documents/parser.ts) 的接口：

```ts
new DocumentParser({
  pythonExecutable: '/owned/runtime/python', // absolute path
  workerPath: '/owned/workers/document/worker.py',
  timeoutMs: 60_000,
  maxInputBytes: 64 * 1024 * 1024,
  maxOutputBytes: 16 * 1024 * 1024, // stdout + stderr
  maxArtifactBytes: 128 * 1024 * 1024,
  maxRequestBytes: 64 * 1024,
});
parser.capabilities({ signal, timeoutMs, onProgress }); // Promise<JsonObject>
parser.parse({ input, artifact_dir, options, limits }, { signal, timeoutMs, onProgress }); // Promise<ParsedDocument>
```

路径由宿主配置传入，无 Electron/Django import；spawn 不经过 shell。每次调用由同一 owned Python executable 启动一个 supervisor，再启动真实 worker；worker stdout/stderr 经过私有管道转发，后代不会继承 Node 的输出句柄。worker 已退出而后代仍持管道时，supervisor 保持存活，固定此次调用的 PID/PGID 身份。取消/超时只终止仍存活的 owned supervisor 及所属进程（POSIX 独立进程组；Windows 匿名、非继承句柄的 Job Object，KILL_ON_JOB_CLOSE 且禁止 breakaway）。不对已观察到退出的 PID 迟发 taskkill 或 group signal。正常结果等待 supervisor close；失败立即销毁父端管道、解除 timer/abort listener 并 reject，不依赖可能无限等待的 close，崩溃后可再次调用。stderr 有字节上限，不回传原生错误内容。协议版本、调用 ID、单终态、JSON、规范正文 hash/ranges、产物路径/符号链接/大小/hash/MIME 均在返回前检查。宿主应在失败后清理此 job scratch，在成功验证后自行持久化；桥接层不发布业务记录。

Windows supervisor 在创建 worker 前把自身加入独立 [Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)，子进程自动加入；主 worker 退出后成员仍属于该 job。创建或分配失败时不会继续启动不受控 worker。本机只有 Linux，Windows ctypes/Job Object 路径未执行，须在目标 Windows x64 中验证，不能把设计审查当成通过。

## 保留的格式与限制

TXT/LOG/PY（UTF-8 ignore）、JSON 美化、CSV 文字行、HTML 去标签、Markdown 图片与正文顺序；PDF 文本/嵌图/矢量裁剪/扫描页；DOCX 正文、行内图、表格/单元格图；PPTX text/table/picture/nested group；XLSX 双视图公式/缓存、sheet/row/cell/merged ranges；XLS 缓存单元格；PNG/JPEG/GIF/BMP/TIFF/WebP/SVG。

沿用最小图片 512 输入字节与 64×64 尺寸、首帧/EXIF/RGB/JPEG 的 VLM 归一化函数。PDF 页边/标题是启发式，不声称多栏重排或表格识别；DOCX 不声称完整提取页眉、脚注、批注和文本框；PPTX 不声称提取 SmartArt/讲者备注/图表数据；XLSX 不重新计算公式。

Markdown 相对图片保留原文字并 warning；HTTP/HTTPS 图片只允许公网 DNS，无 URL 用户密码，最多 3 次重定向、每次 10 秒、image MIME、每图最多 10 MiB。下载策略测试使用受控响应，未进行依赖外网的下载成功验收；沿用 requests 的 DNS 校验/连接方式，未新增 DNS 连接固定机制。

DOC/PPT 仍经真实 LibreOffice 转换，默认 30 秒；加密、缺 converter、timeout、转换失败/无产物/坏产物均保留分类。转换暂存与独立 profile 在当前 job 内。capabilities 实际尝试加载依赖，逐格式报告 availability；LibreOffice 缺失只使 DOC/PPT 不可用。OCR/Caption 的 capability 明确 false。

## 依赖与许可证

[requirements.txt](requirements.txt) 仅列解析必要依赖，沿用原项目 lower-bound 策略；不含 Django/DRF/Waitress/Neo4j/SQLite/Ragas。Cairo、Pillow、lxml、PyMuPDF 的原生运行时仍需在打包目标机器验证，不能假定目标有系统 Python/LibreOffice。Windows 打包应保留现有 [native lock](../../desktop/native-windows.lock.json) 与对应第三方声明；PyMuPDF 的 AGPL/commercial 许可安排仍须沿用项目选定方案，不由本目录的 MIT 许可替代。

[fixtures manifest](tests/fixtures/manifest.json) 记录原创新样本、预期语义与 SHA-256。新 TXT/MD/CSV/JSON/HTML、DOCX/PPTX/XLSX/XLS、文本/扫描 PDF、PNG/SVG 和坏/空/小图样本均为本项目创作，MIT，无真实用户数据。扫描 PDF 来自带可读收入文字的栅格图，不是噪声；只验证渲染。真实 DOC/PPT 样本复用 Apache POI，保留 [来源](tests/fixtures/legacy/README.md) 和 [Apache-2.0 许可证](tests/fixtures/legacy/LICENSE)。测试读取静态文件；[生成器](tests/generate_fixtures.py) 是维护工具，不在测试中生成样本，额外需要 xlwt 与 Linux DejaVu 字体。

## 验证证据（2026-10-10，Linux x64 / Python 3.12.2）

采用先失败再实现：初次 `python -B -m unittest discover -s workers/document/tests -v` 为 10 个 FAIL，因独立入口尚不存在；初次 `cd packages/core && node --import tsx --test test/parser.test.ts` 为 6 个 FAIL，断言独立桥接尚不存在。另观察可选依赖缺失、remote response 未关闭、converter scratch 参数缺失、SVG 外部引用未拒绝的失败回归，再实现修复。

最终相关命令：

```sh
python -B -m unittest discover -s workers/document/tests -v
cd packages/core
node --import tsx --test test/parser.test.ts
npm run typecheck
```

当前验证：22 个 Python 测试、10 个 TS 测试通过，core typecheck 通过。Python 测试包括 11 种真实格式在禁止导入 Django/项目业务/sqlite3 与禁止打开数据库后缀文件的进程内成功解析；TS 测试验证取消/timeout/crash/recovery、保留无关进程、坏协议/重复终态/限额、输入身份、产物遍历/符号链接/错 hash、真实 SVG 输出。

P1 继承管道回归先红：真实临时 worker 启动持 stdout/stderr 的 2 秒后代后立即退出，80ms timeout 实际 2033ms 才 settle，取消实际 2011ms。修复后两例测试运行约 92ms/47ms，均断言 settle 小于 600ms、worker 已退出、owned 后代在 1000ms 检查界限内停止、无关 Python 进程仍存活。Promise 失败收敛由 timer/abort 直接执行，既不等待 EOF，也不等待 close；无延迟针对旧 PID 的清理任务。Windows 尚未实际运行此回归。

还创建全新 venv，仅安装本目录 requirements，并断言 `find_spec('django') is None`，再运行全部 Python 测试和 TS 桥接测试（通过 `MARLIN_TEST_PYTHON` 指向该 venv）。该环境的主要实际版本：PyMuPDF 1.28.2、Pillow 12.3.0、python-docx 1.2.0、python-pptx 1.0.2、CairoSVG 2.9.1、openpyxl 3.1.5、xlrd 2.0.2、msoffcrypto-tool 6.0.0、requests 2.34.2。新版本 PyMuPDF `fitz` 导入会打印弃用提示，已改用安装包的正式 `pymupdf` API，并重新验证 stdout 协议。默认已有环境另验证 PyMuPDF 1.27.2.3/CairoSVG 2.9.0。

未验证：本机未装 LibreOffice，真实 DOC/PPT 只确认 `legacy_office_converter_unavailable` 和 capability false；受控 timeout/profile 测试不算真实转换成功。Windows x64 bundled Python/原生依赖、Windows 取消进程树、实际 LibreOffice 转换、真实 OCR/Caption、真实公网下载和大规模解析性能尚未验收。本次没有修改 Django/前端业务文件、提交/推送或调用付费模型；整项目 Django/UI 检查由重构主任务统一执行。
