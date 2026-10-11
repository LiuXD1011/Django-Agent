# 独立损坏图片解析失败修复计划

**Goal:** 上传损坏的独立图片时返回已有 `parse_failed` 错误；保留正常空文本、扫描 PDF、有效无文字图片、小图和文档内图片的既有语义。

**Architecture:** 仅缩窄 `workers/document/parser/registry.py` 的 `parse_image` 异常捕获范围。`ImageTooSmallError` 继续生成原有警告；真正的 `InvalidImageError` 由现有 worker 的公共错误路径处理，不向用户暴露原生解析器异常。TS 协议及发布流程保持原契约。

**Tech Stack:** Python 3.12、现有 unittest、Pillow/CairoSVG、真实独立 Python worker、TypeScript `DocumentParser`。

## 根因与选择

`parse_image` 捕获所有 `InvalidImageError`，返回零块及 `invalid_or_small_image` 警告。协议适配器把此结果作为成功返回；TS 校验允许合法空正文，发布流程因此标记解析完成。现有 `test_bad_empty_and_unsupported` 甚至要求坏 PNG 是警告成功。

选择只捕获 `ImageTooSmallError`，让损坏图走 worker 既有 `parse_failed`。在 TS 层统一拒绝空正文会误伤扫描 PDF 和有效无文字图片；统一把所有图片警告视为失败会误伤 DOCX/PDF/Markdown 的局部图片失败。两种替代方案均不采用。

保留最小图片 512 输入字节与 64×64 尺寸。纯色 PNG 可能因压缩结果低于 512 字节而被跳过，这属于现有小图策略，不应误报为解码失败。有效纯色 BMP 用来证明无文字图片仍能保留图片块。没有对应 issue 编号。

已完整阅读 registry、worker/protocol、图片类型与检查函数及 Python 测试；TS 桥接及下游发布路径已追踪。安装的 Pillow `Image.open` 明确为惰性读取；本次修复已证实的异常吞没问题，不在无回归证据时扩大到像素校验行为。

## 执行与验证

- [x] 修改真实静态坏 PNG 用例，要求 `type=error`、`code=parse_failed`、`retryable=false`；运行观察预期 RED。
- [x] 加入临时真实 malformed SVG、有效纯色 BMP/PNG、带坏嵌图的 Markdown 用例；保留现有小图及扫描 PDF 断言。
- [x] 仅将 `parse_image` 的 `except InvalidImageError` 改为 `except ImageTooSmallError`。
- [x] 运行相关 Python worker/boundary 测试；运行真实 TS 桥接定向回归及现有 parser 测试、核心 typecheck。
- [x] 保存独立命令、退出码、耗时、源码哈希和测试输出证据；检查文档链接与差异；删除已消费临时脚本。

代码范围：`workers/document/parser/registry.py`、`workers/document/tests/test_worker.py` 以及本文；动态样本使用 `TemporaryDirectory`，不改静态 fixture manifest、依赖或核心源代码。执行主任务已通过 Goal II.3/II.4 授权设计记录后继续，不另起批准流程；不提交、访问真实数据、GUI、API、模型或凭据。最终 Workflow/UI 验证由主任务执行。

## 结果

2026-10-11，Linux x64 / Python 3.12 / Node 22.23.2：

| 检查 | 实际结果 | 命令总耗时 | 证据 |
| --- | --- | --- | --- |
| Python 定向 RED | 4 项中 2 FAIL：坏 PNG、坏 SVG 返回成功；纯色图、嵌图 2 PASS | 5304.709 ms | [命令与哈希](../refactor-evidence/20261011-image-parse-python-red.json)、[输出](../refactor-evidence/20261011-image-parse-python-red.log) |
| 真实 TS 桥接 RED | 4 项中 2 FAIL，均 Missing expected rejection；原有空正文/嵌图语义 2 PASS | 4188.258 ms | [命令与哈希](../refactor-evidence/20261011-image-parse-bridge-red.json)、[输出](../refactor-evidence/20261011-image-parse-bridge-red.log) |
| Python worker/boundary GREEN | 25/25 PASS，无跳过；包含 11 格式隔离解析 | 48325.946 ms | [命令与哈希](../refactor-evidence/20261011-image-parse-python-green.json)、[输出](../refactor-evidence/20261011-image-parse-python-green.log) |
| 真实 TS 桥接 GREEN | 4/4 PASS，无跳过 | 4736.346 ms | [命令与哈希](../refactor-evidence/20261011-image-parse-bridge-green.json)、[输出](../refactor-evidence/20261011-image-parse-bridge-green.log) |
| 现有 TS parser 回归 | 12/12 PASS，无跳过 | 7212.114 ms | [命令与哈希](../refactor-evidence/20261011-image-parse-parser-related.json)、[输出](../refactor-evidence/20261011-image-parse-parser-related.log) |
| 核心 typecheck | exit 0 | 17736.122 ms | [命令与哈希](../refactor-evidence/20261011-image-parse-typecheck.json)、[输出](../refactor-evidence/20261011-image-parse-typecheck.log) |

生产 registry SHA-256：`f5a66ef8895929eb51729bcdcefdcaa81c1d9452f9bc508f4e068ea67f34cfbd`。Python 新测试使用真实文件/进程，无解析器成功替身；TS 定向验证直接调用真实 `DocumentParser`。测试总耗时包含启动及验证，不能作为业务页面延迟。现有 TS parser 回归只有 Node MockTimers API 的实验性提示，无失败。

真实 UI 仍需由主任务重新解析损坏图片并确认失败状态；更新后的 worker 也须进入下一次 Windows 构建。此处未操作 GUI、实际数据、账户、API 或模型，不把单元/桥接通过写成 UI 或安装包通过。
