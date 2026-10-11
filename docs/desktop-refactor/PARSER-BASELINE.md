# 文档解析、OCR 与 Ragas 迁移基线

本报告以 2026-10-10 的实际工作区为准。HEAD 为 `222383803cf2c6586605b9c5b793afbe3a27b14d`，工作区已有大量修改；不能把 HEAD 内容代替此次检查到的代码。此次只增加本文件，未改业务代码、依赖或 fixtures，未提交。

目标边界：Electron + TypeScript 拥有业务数据、分块、检索、模型配置、任务状态和报告持久化；Python 只提供独立的文档解析、可选 OCR 和 Ragas 运算。Python 不导入 Django，不读取或写入业务数据库。本文件中的协议及目录划分是建议，尚未实施。

## 1. 实际代码位置与可提取范围

仓库没有名为 `document_extractors` 的源码模块。实际提取函数位于 [registry.py](../../personal_knowledge_base/document_parsing/registry.py) 和 [spreadsheet.py](../../personal_knowledge_base/document_parsing/spreadsheet.py)。旧的 `extract_text_from_bytes` 位于 [document_processing.py](../../personal_knowledge_base/document_processing.py)，只是调用解析器后拼接正文，并不是独立提取器。

| 模块 | 实际职责与依赖 | 独立化结论 |
| --- | --- | --- |
| [document_parsing/types.py](../../personal_knowledge_base/document_parsing/types.py) | `ParsedDocument`、`TextBlock`、`ImageBlock`、`ParseWarning` 数据类；标准库 | 可直接提取；`ImageBlock.data: bytes` 需要产物文件或明确的二进制编码协议 |
| [document_parsing/registry.py](../../personal_knowledge_base/document_parsing/registry.py) | 按扩展名分派，PDF/Office/Markdown/图片读取；局部导入 fitz/docx/pptx | 实际解析函数无 Django/ORM；保留现有行为后可提取 |
| [document_parsing/spreadsheet.py](../../personal_knowledge_base/document_parsing/spreadsheet.py) | XLSX 公式/缓存双视图、OOXML 合并信息；XLS 单元格；openpyxl/xlrd | 无 Django/ORM，可提取 |
| [document_parsing/images.py](../../personal_knowledge_base/document_parsing/images.py) | Pillow 检查、EXIF 校正、第一帧、RGB/JPEG 归一化；SVG 经 CairoSVG | 无 Django/ORM；先补 SVG 数据与 MIME 一致性回归 |
| [document_parsing/legacy_office.py](../../personal_knowledge_base/document_parsing/legacy_office.py) | msoffcrypto 预检；subprocess 调 LibreOffice；临时目录 | 无 Django/业务 DB，但不是仅依靠 Python wheel 的能力 |
| [document_parsing/remote_images.py](../../personal_knowledge_base/document_parsing/remote_images.py) | requests 下载公网图片，校验 DNS/协议/重定向/大小 | 无 Django/ORM；包含网络副作用，需保留约束并明确网络策略 |
| [document_parsing/__init__.py](../../personal_knowledge_base/document_parsing/__init__.py) | 公共导出；`parser_capabilities(tenant)` 查询 settings/ModelConfig/VLM 状态 | `parse_document` 导入已证明无 Django；不能照搬能力探测函数 |
| [chunking/config.py](../../personal_knowledge_base/chunking/config.py)、[types.py](../../personal_knowledge_base/chunking/types.py)、[recursive.py](../../personal_knowledge_base/chunking/recursive.py)、[validator.py](../../personal_knowledge_base/chunking/validator.py) | 配置校验、数据类、保护区间、覆盖与父子约束；标准库 | 算法主体纯 Python，适合移植 TS；当前 package 初始化会拉入 service/semantic |
| [chunking/structural.py](../../personal_knowledge_base/chunking/structural.py) | 规范正文、原子单元、heading/layout/record、微块合并；解析类型 | 算法可移植 TS；需保留来源坐标和图片边界 |
| [chunking/service.py](../../personal_knowledge_base/chunking/service.py) | 策略选择、降级、父子块、token 回调、诊断 | 主体不写 DB；顶层导入 semantic 使整个入口耦合 Django |
| [chunking/semantic.py](../../personal_knowledge_base/chunking/semantic.py) | 窗口 embedding、余弦距离、百分位、边界合并、缓存 | 顶层导入 `SemanticChunkCache`，默认直接 ORM 读写；数学算法可移植 TS，缓存归 TS 管理 |
| [document_processing.py](../../personal_knowledge_base/document_processing.py) | Storage、Knowledge/Chunk 事务、索引、任务所有权、摘要/问题/图谱/Wiki | 业务编排归 TS，不能作为 Python worker 入口 |
| [multimodal.py](../../personal_knowledge_base/multimodal.py) | VLM OCR/Caption 请求、KnowledgeImage/Chunk 写入、Storage 清理 | 提取 prompt/图片归一化运算；配置、模型调用编排和持久化归 TS |
| [ragas_adapter.py](../../personal_knowledge_base/ragas_adapter.py) | Ragas API、分组批量评分、生成 testset；`_clients` 读取 Django/模型配置 | 可保留纯运算适配，必须改为显式传入客户端配置/客户端，不传 tenant ORM 对象 |
| [evaluation_examples.py](../../personal_knowledge_base/evaluation_examples.py) | 样本身份、评分对齐、覆盖统计；调用纯评分可用性检查 | 可作为 TS 移植参考；业务样本及 checkpoint 管理归 TS |

已执行的无 Django 导入探测：

```text
env -u DJANGO_SETTINGS_MODULE python -B -c '<导入 parse_document 并解析 notes.txt>'
text_blocks 1
django_loaded False

env -u DJANGO_SETTINGS_MODULE python -B -c '<导入 split_document>'
ImproperlyConfigured: Requested setting INSTALLED_APPS, but settings are not configured.
```

后一结果来自 `chunking/__init__ → service → semantic → models`。即便只希望使用 recursive、只提供内存 `semantic_cache={}`，顶层导入仍发生；仅传参数无法解除耦合。

## 2. 各格式、结构与图像能力

下表区分代码路径与质量证明。现有测试多数在内存生成样本，不能据此声称真实用户文件已全覆盖。

| 输入 | 当前解析结果 | 明确限制 / 证据范围 |
| --- | --- | --- |
| TXT/LOG/PY | UTF-8 `errors="ignore"` 解码，非空时一个 text block | 非 UTF-8 字节可能丢失；不探测编码 |
| JSON | 成功解 JSON 后美化，否则保留解码文字 | 非 schema 解析，无结构化记录坐标 |
| CSV | csv.reader 后以 ` | ` 拼列、换行拼行 | 无 sheet/record/cell provenance；现有 auto 不因此选 record |
| HTML/HTM | 正则移除 script/style、剥标签 | 无 DOM 语义/内嵌图片提取；不是浏览器渲染或完整 HTML 转换 |
| MD/MARKDOWN | 图片前后正文保持顺序；data URI、公网 HTTP/HTTPS 图片提取 | 图片使用简单正则；相对图片保留 Markdown 并输出 `relative_image_unavailable`；没有上传目录解析 |
| 文本 PDF | PyMuPDF dict 文本/内嵌位图；坐标、字体、标题置信度、页码；重复页边文字过滤 | 按 `(page,y,x)` 排序，未实现多栏阅读顺序分析；标题/页边识别为启发式；没有原生 PDF 表格结构输出 |
| PDF 矢量图 | 大于等于 64×64 的 drawing rect 裁剪为 150dpi PNG | 每个 drawing 独立截图；不能当作完整图表重建或表格识别 |
| 扫描 PDF | 单页文字少于 20 字符且有图/绘图时，整页 150dpi JPEG，`source_type=scanned_pdf` | 此分支直接跳过该页正文/局部图片提取；仅输出图片，不识别文字；短文字+图的页面也可能走此分支 |
| DOCX | body 段落、Heading/outline 层级、行内文本/图片顺序、表格 text/rows/cells；表格图片带 cell 坐标 | 未见页眉/页脚、批注、修订、脚注、文本框完整遍历；单元格合并跨度未显式输出；表格图片排在整个表格块之后 |
| PPTX | slide text box、table rows/cells、picture；group 递归；slide/shape_path | shape 遍历顺序不是按几何位置重排；WMF/EMF 输出 warning；未见图表数据、SmartArt、讲者备注提取 |
| DOC/PPT | LibreOffice headless 转 DOCX/PPTX 后复用上述解析；默认 30 秒 timeout | 本机无 `soffice/libreoffice`，真实转换未运行；现有 converter mocked 测试证明路由/错误分类，不证明转换质量 |
| XLSX | 每个非空行一个 record；sheet、headers、行列范围、公式来源、每 cell provenance、merged ranges | 第一非空行当 headers；只读双 workbook；有缓存则用值，无缓存保留公式；不重新计算公式；未提取图片/图表 |
| XLS | xlrd 每个非空行 record；sheet、行列、合并范围、缓存值来源 | 不恢复公式表达式或图片/图表；时间/数字显示格式未见按 Excel 格式完整还原 |
| JPG/JPEG/PNG/GIF/BMP/TIF/TIFF/WEBP/SVG | 独立 ImageBlock；后续 VLM 可产生 OCR/Caption | 原始文件小于 512 字节，或任一尺寸小于 64 时跳过；归一化只取动画/多帧首帧；SVG 端到端有下述复现缺陷 |

上传白名单来自 [chunking/config.py](../../personal_knowledge_base/chunking/config.py)：显式不支持宏 Office、RTF、EPUB、音频/视频。`parse_document` 对未知扩展名本身会回落到文本；独立 worker 应承接现有上传扩展校验，不能绕过白名单把二进制当正文。`engine="plain"` 是 builtin 的别名，不是关闭图片或格式处理的另一解析引擎。

远程 Markdown 图片现有约束：HTTP/HTTPS、公网 DNS 地址，无 URL 用户密码，最多 3 次重定向，每次请求 10 秒，响应必须 `image/*`，累计最多 10 MiB。移植时应保留这些行为及失败 warning。

### OCR 的实际状态

[multimodal.analyze_image](../../personal_knowledge_base/multimodal.py) 将图归一化为最长边 2048、JPEG quality 88，再分别请求 `vision_completion(..., OCR_PROMPT, "image_ocr")` 与 caption。该路径存在，OCR 与 caption 可以部分成功；缺模型/无权限会熔断后续图片，同文档相同 hash 只分析一次。

这证明当前有 **VLM 文字识别调用路径**，不证明有独立本地 OCR 或真实识别准确度。仓库源码/requirements 未出现 rapidocr、paddleocr、pytesseract、easyocr、tesseract 集成。宿主环境恰好安装某 OCR 依赖也不能算项目能力。扫描 PDF 测试的图是随机噪声，没有可识别文字、CER/WER 或期望表格。

`process_document_images` 还会创建业务图片记录、disabled `image_container`、可检索的 `image_ocr/image_caption`、媒体父关系和邻近正文锚点。这部分必须由 TS 保存。若继续 VLM OCR，TS 可直接使用统一模型调用；Python 负责图片归一化/页面渲染。若增加本地 OCR，应作为新能力单独选型、打包和验证，不能宣称此次提取已具备。

### 已复现的 SVG 问题

有效 96×96、超过 512 字节的 SVG，经 `inspect_image` 栅格化检查后返回 `image/png`；`_image_block` 却保留原 SVG bytes。无 Django 探测结果：

```text
ImageBlock.mime_type = image/png
ImageBlock.data 前四字节 = <svg
normalize_for_vlm(ImageBlock.data, ImageBlock.mime_type)
→ InvalidImageError: invalid image data
```

原因见 [images.py](../../personal_knowledge_base/document_parsing/images.py) 与 [registry.py](../../personal_knowledge_base/document_parsing/registry.py)。提取时应使 bytes/MIME/文件扩展一致，分别保存原始来源 MIME 与归一化产物 MIME；这不是可以把 SVG 从支持列表删除的依据。当前没有关联 issue 编号，后续回归测试只在存在对应 issue 后标号。

## 3. 分块必须保留的行为与坐标

现有结构分块不是简单的固定窗口。移植参考 [service.py](../../personal_knowledge_base/chunking/service.py)、[structural.py](../../personal_knowledge_base/chunking/structural.py)、[recursive.py](../../personal_knowledge_base/chunking/recursive.py) 及 [test_adaptive_chunking.py](../../personal_knowledge_base/test_adaptive_chunking.py)。

- 规范正文按 `block_index` 排序，只排除空字符串块，以两个换行拼接。正文不插入图片，但图片在前后正文之间构成硬边界。
- `auto` 优先 heading，其次 record，再 layout，最后 recursive。heading 维护标题路径；layout 按 page/slide；record 按 sheet/headers。
- 代码围栏、公式、链接及 table 等受保护；token_limit 无法容纳受保护内容时报告失败，而非静默截断。chunk_size 是目标，不是任何情况下都严格不超出的字符上限。
- 默认父子块开启：parent 2048、child 384、child overlap 64；一般 chunk_size 512、overlap 80。仅 child 用于检索；parent 供上下文展开。
- 微块合并、非空正文覆盖、源区间对应、父子包含关系、token 上限均有校验；降级链、所选策略、统计与耗时会输出诊断。
- semantic 窗口默认 3、百分位 90；验证向量数量/维数/有限值/非零范数，尊重媒体硬边界。失败可降级结构策略及 recursive，并保留理由。持久缓存与模型签名应交给 TS。

**坐标不能混用：** Python `len`/slice 当前使用 Unicode code points；JS 默认字符串索引是 UTF-16 code units。含非 BMP 字符的文件会发生坐标偏移。建议 v1 协议显式声明 `offset_unit="unicode_code_point"`，TS 用专用转换/切片方法，fixture 至少包含一个非 BMP 字符。不要以语言原生 `.length` 隐式定义协议。

`TextBlock.source_start/source_end` 当前语义也不统一：PDF 为规范正文字符范围（结束不含），DOCX 为 body 编号（start=end），PPTX 为 slide 编号，Excel 为 row 编号。协议应分开 `canonical_range` 与 `provenance`，后者带单位、页/段落/slide/row/cell/bbox。不能把这些字段统一视为可切片的字符坐标。

## 4. 评测运行器的耦合与保留范围

| 路径 | 当前依赖 | 迁移归属 |
| --- | --- | --- |
| [rag_eval.py](../../personal_knowledge_base/rag_eval.py) | KnowledgeBase 查询、hybrid_search、chat_completion，然后调用 Ragas | 检索与答案生成归 TS；Python 只评分明确传入的完整 rows |
| [ragas_adapter.py](../../personal_knowledge_base/ragas_adapter.py) | `_clients` 从 settings/ModelConfig/active_embedding_config 构建 LangChain 客户端 | Python 接收已解析的 judge/embedding 配置，不再查询 tenant 或默认模型 |
| [chunking_eval.py](../../personal_knowledge_base/chunking_eval.py) | Django Storage、Knowledge 查询、版本 hash、document_processing、model_providers、search | 数据加载、策略比对、隔离索引与门禁归 TS；不得因“不写生产索引”就视为无 Django |
| [retrieval_eval.py](../../personal_knowledge_base/retrieval_eval.py) | Chunk/Knowledge、生产检索、evidence 校验 | TS；hit/MRR/recall 公式可直接移植 |
| [tasks.py](../../personal_knowledge_base/tasks.py) | TaskRecord、tenant/dataset 读取、worker claim、checkpoint、答案生成、报告保存 | 所有业务队列、取消、恢复和 checkpoint 归 TS |
| [open_rag_benchmark.py](../../personal_knowledge_base/open_rag_benchmark.py) | Django settings/cache、TaskRecord 间接使用、sqlite3/sqlite-vec benchmark index、模型调用、下载/状态文件 | 公共语料下载、索引与策略评测归 TS；隔离 benchmark SQLite 也不能照搬进受限 Python 运算 worker |
| [eval_views.py](../../personal_knowledge_base/eval_views.py)、[eval_reports.py](../../personal_knowledge_base/eval_reports.py) | HTTP/权限、GenericResource 发布与报告持久化 | TS 业务层 |
| [eval_generator.py](../../personal_knowledge_base/eval_generator.py) | 随机抽取 ORM chunks、普通 LLM 生成、GenericResource 保存 | 与 Ragas TestsetGenerator 不同；归 TS |

Ragas 实际正式指标是 `faithfulness`、`answer_relevancy`、`context_precision`。有 reference 用 `ContextPrecision`，无 reference 用 `LLMContextPrecisionWithoutReference` 并重命名输出。虽然 `rag_eval.py` 数据类/文档含 context_recall、answer_correctness，当前正式 adapter 没计算它们；不能将默认 0 当已评测的真实分数。

当前 adapter 按有无 reference 分组，每批 10 行，RunConfig 最大 2 workers；空 question/answer/context 标 invalid，NaN/非有限指标标 invalid，结果数量不符报错。支持 existing_scores、进度和批间取消。正式评测失败不使用 `_simple_evaluation` 伪造 Ragas 分数。独立运行器应保留这些约定。

已检查本机安装的 Ragas 0.4.3 源码类型/签名：`SingleTurnSample(user_input, response, retrieved_contexts, reference)`、`EvaluationDataset(samples)`、`evaluate(..., metrics, llm, embeddings, run_config, raise_exceptions, show_progress)`、`TestsetGenerator.from_langchain(..., llm_context)` 及 `generate_with_langchain_docs`。这里未进行付费模型请求或真实 Ragas 评分，现有 [test_ragas_evaluation_loop.py](../../personal_knowledge_base/test_ragas_evaluation_loop.py) 主要通过替身验证契约。

Ragas 0.4.3 的 legacy Vertex 兼容逻辑已存在于 adapter；提取应先使用现有 pin 组合验证真实导入，不扩大兼容层或在本轮删掉现有逻辑。LangChain client 对 qwen/qwq 才加 thinking controls 的行为也应保留。

## 5. 建议的版本化 JSON 运算协议

建议统一使用 Electron main 启动独立 worker 的 stdin/stdout UTF-8 NDJSON。stdout 仅协议事件，诊断写 stderr；每个请求以 `request_id` 关联，一个终态 `result/error/cancelled`。TS 控制任务所有权、取消、重试及持久化；Python 只操作当前 job 的输入和产物目录。

### 外层消息

| 字段 | 约定 |
| --- | --- |
| `protocol_version` | `"1.0"`；不支持的主版本明确报 `protocol_version_unsupported` |
| `request_id` / `operation` | 调用关联串；操作 `capabilities`、`parse`、`ocr`、`evaluate`、`generate_testset`、`cancel`，仅已实施操作进入 capabilities |
| `type` | 输出 `progress/result/error/cancelled`；请求通过 operation 区分 |
| `input` | `path`、`name`、`sha256`、`size_bytes`、可选 MIME hint；输入由 TS 放入 job 目录，worker核验内容 hash |
| `artifact_dir` | TS 创建的本 job scratch 目录；Python 允许写解析图片、规范正文等产物，不写业务 DB/用户长期文件 |
| `options` | 格式/engine、远程图策略、render dpi、OCR 选择及限额；实际支持项须单独声明，不伪装全部已实现 |
| `limits` | 明确最大输入/产物字节、页数/图数、超时；到限输出稳定错误/partial，避免静默遗漏 |
| `error` | `code`、可供展示的 message、`stage`、`retryable`、来源 block；保留现有 legacy_office/xls/xlsx 错误分类，不回传凭据 |
| `diagnostics` | worker/parser/engine 版本、依赖版本、耗时、warning、有效配置；不混入 ORM 对象或模型凭据 |

### parse 结果

建议单一 `blocks` 有序数组，而不是仅传纯文字：

```json
{
  "protocol_version": "1.0",
  "request_id": "parse-example",
  "type": "result",
  "operation": "parse",
  "status": "completed",
  "result": {
    "document": {
      "input_sha256": "<输入文件 hash>",
      "parser_version": "<实现版本>",
      "canonicalization_version": "blocks-double-newline-v1",
      "offset_unit": "unicode_code_point",
      "canonical_text": "季度收入\n\nQ1 | 100",
      "canonical_sha256": "<规范正文 UTF-8 hash>"
    },
    "blocks": [
      {
        "id": "b0",
        "block_index": 0,
        "kind": "text",
        "block_type": "heading",
        "text": "季度收入",
        "canonical_range": {"start": 0, "end": 4},
        "provenance": {"page_index": 0, "unit": "pdf_point", "bbox": [54, 60, 180, 90]},
        "metadata": {"heading_level": 1, "structure_confidence": 0.85}
      },
      {
        "id": "b1",
        "block_index": 1,
        "kind": "text",
        "block_type": "paragraph",
        "text": "Q1 | 100",
        "canonical_range": {"start": 6, "end": 14},
        "provenance": {"page_index": 0, "unit": "pdf_point", "bbox": [54, 110, 180, 130]},
        "metadata": {"structure_confidence": 0.5}
      }
    ],
    "assets": [],
    "warnings": []
  }
}
```

示例仅展示字段，不是已运行的返回值。`canonical_range` 为 0-based、end-exclusive；page_index 为 0-based，用户显示页码单独转换。正文大时可用带 hash/bytes/encoding 的 `canonical_text_artifact` 代替 inline 字符串，协议应固定一种明确的互斥规则。

image block 应包含 `asset_id`、source_type/ref、page/block 顺序、bbox/原文件位置；asset manifest 包含相对 job 路径、hash、字节大小、实际 MIME、宽高、原始 MIME、归一化信息。TS 检查产物后决定永久保存路径和业务图片 ID。严禁把现有 API preview_url/tenant storage path 当解析协议。

table/record 保留 `rows/cells`、row/column_count、table_index、sheet_name、headers、row/column范围、cell coordinate/formula/value/source、merged_ranges；以格式 provenance 表达，不丢成单个 Markdown 字符串。warning 保留 code/message/block_index/source_ref。建议按实际依赖逐格式报告 availability，避免沿用 `all(dependencies.values())` 将 LibreOffice 缺失扩大成整个解析器不可用。

### OCR 与 Ragas 的独立结果

- OCR 输入引用某 asset，输出同一 asset_id 的 text/结构化表格（仅实际引擎支持时）/confidence（可空）、engine/version、状态与错误。VLM OCR 和本地 OCR 的 engine 必须区分；caption 是独立结果，不能充当识别文本的替代证明。
- Ragas 输入是 TS 已完成检索/答案生成的 rows：`example_id`、question、answer、contexts、ground_truth、可选 evidence。judge/embedding 配置作为当前请求参数传入独立进程，不来自业务 DB，不放命令行参数或结果中。
- Ragas 输出保留 example_id、逐指标数值或 null、valid/error、指标实现版本、reference 与 no-reference 的区别、coverage 和耗时。失效项不填 0；TS 负责汇总/保存、样本对齐和 checkpoint。
- generate_testset 输入普通 documents（content + provenance）与规模/类型，输出 candidates/reference_contexts；候选审批/发布仍是 TS 业务。model config、dataset/hash/版本由 TS 冻结。
- TS 分块结果建议保留 parents/children 的临时索引关系、content/context_header、规范坐标、source_refs、diagnostics；TS 分配业务 ID。协议核心不要求 Python 继续承担分块。

## 6. 依赖、版本和运行时打包

版本事实来自 [requirements.txt](../../requirements.txt)、[Windows 锁文件](../../desktop/requirements-windows.lock) 与本机 pip metadata。下表的“本机”不能替代目标平台实际打包验证。

| 组件 | requirements 策略 | 本机 Python 3.12.2 | Windows x64/Python 3.13 锁 |
| --- | --- | --- | --- |
| PyMuPDF | >=1.24.0 | 1.27.2.3 | 1.28.2 |
| Pillow | >=10.4.0 | 12.3.0 | 12.3.0 |
| python-docx | >=1.1.0 | 1.2.0 | 1.2.0 |
| python-pptx | >=1.0.0 | 1.0.2（来自用户 site-packages） | 1.0.2 |
| CairoSVG | >=2.7.0 | 2.9.0 | 2.9.1 |
| openpyxl | >=3.1.5 | 3.1.5 | 3.1.5 |
| xlrd | >=2.0.1 | 2.0.2 | 2.0.2 |
| msoffcrypto-tool | >=5.4.2 | 6.0.0 | 6.0.0 |
| requests | >=2.32.0 | 2.34.2 | 2.34.2 |
| ragas | ==0.4.3 | 0.4.3 | 0.4.3 |
| datasets | ==4.8.4 | 4.8.4 | 4.8.4 |
| langchain-community | ==0.3.31 | 0.3.31 | 0.3.31 |
| langchain-openai | ==0.3.35 | 0.3.35 | 0.3.35 |

纯解析所需依赖图：Pillow；PyMuPDF 原生 wheel；python-docx/python-pptx + lxml（pptx 另含 XlsxWriter 等已安装依赖）；openpyxl + et-xmlfile；xlrd；msoffcrypto + cryptography/olefile；CairoSVG + cairocffi/cffi 与 Cairo 原生库；requests。不能只拷 Python 文件假定机器已有解析器。

Ragas 还引入 datasets/pandas/pyarrow/numpy、LangChain/OpenAI、networkx/scikit-network/scipy、tiktoken 等运行时依赖。应为解析与 Ragas 分组建立目标平台锁/打包入口，遵守现有 lower-bound 与精确 pin 策略；独立 worker 的锁不应包含 Django、DRF、Waitress、WhiteNoise、sqlite-vec、Neo4j 等业务服务。当前 requirements 仍保留不变。`pypdf` 虽在 requirements，但此次仓库检索只发现声明，没有实际 parser 调用；不是该 PDF 解析实现的直接依赖。

[build_windows.py](../../scripts/build_windows.py) 当前打包 Python 3.13.16 embedded 和整套 Django backend，pip 全 requirements，并预热 cl100k_base；不能直接作为独立运算包产物。[bundle_windows_native.py](../../scripts/bundle_windows_native.py) 与 [native-windows.lock.json](../../desktop/native-windows.lock.json) 已提供 hash 固定的 Cairo DLL/字体及 license/source notices，是可复用的打包基础。

当前脚本未提供 LibreOffice 产物；因此旧 DOC/PPT 离线可用性仍需明确打包 converter、可执行路径发现和实际转换测试。不得仅因 Python dependency_status 为真就宣称这两个格式可用。Cairo、PyMuPDF、Pillow/图像 codec、lxml、Ragas 的原生依赖应在无系统 Python/Node/LibreOffice 的干净目标机器验证。保留项目许可证与已有 native-notices；PyMuPDF metadata 标明 AGPL/commercial 双许可，打包应沿用项目选定的许可证安排，不能遗漏声明。

## 7. fixtures 与必要的真实验证

当前已入库的二进制 fixtures 仅有以下三项；[README](../../personal_knowledge_base/testdata/legacy/README.md) 记录 DOC/PPT 的 Apache POI 来源和 Apache-2.0，未记录 sample.xls 来源。

| 文件 | SHA-256 | 当前证明 |
| --- | --- | --- |
| [sample.doc](../../personal_knowledge_base/testdata/legacy/sample.doc) | `39170c5a103bb0961b269be04da00ae2ae961da6a26f1624f462ac915adaf13e` | CDF Office 文件；真实测试仅断言任一 text/image 非空，本机无 converter 未运行 |
| [sample.ppt](../../personal_knowledge_base/testdata/legacy/sample.ppt) | `7eed4b72a235b4122b07b371fb02fbb5ae95d47dc70592ce37bb6bf4a6e94de4` | 同上 |
| [sample.xls](../../personal_knowledge_base/testdata/legacy/sample.xls) | `3f8cde41d289b9af1debd9b1bcd8c63e93fd82d7d08eddeb2684d16bd9912ae2` | 本次无 Django 真实探测输出 3 blocks、sheet Revenue、merge A3:B3 |

[test_document_parsing.py](../../personal_knowledge_base/test_document_parsing.py) 内存生成 PDF/XLSX/DOCX/PPTX/随机图片，覆盖标题、页边过滤、表格、公式 fallback、行内图顺序、shape 顺序、扫描页渲染及 legacy 错误；[test_multimodal_processing.py](../../personal_knowledge_base/test_multimodal_processing.py) 主要替身验证 VLM 调用与 ORM 行为；[test_pdf_line_join.py](../../tests/test_pdf_line_join.py) 覆盖断词、复合词和中英文合行。它们是迁移回归参考，尚不是独立 Python/TS 测试包。

下一阶段需要提供真实静态文件及人工可读的 expected JSON/文字，而非只在测试里生成容器：

| fixture 组 | 必须包含 | 断言 |
| --- | --- | --- |
| text/Markdown/HTML/CSV/JSON | 中英混排、非 BMP 字符、空白、代码/公式/链接、data URI、相对图与远程图失败 | 规范正文、offset、block 顺序、warning、保留上传白名单 |
| DOCX/DOC | 标题、段落行内图、表格单元格图、合并单元格；真实 legacy 转换 | 内容关键字、rows/cells、来源、顺序；converter 缺失/timeout/加密分类 |
| PPTX/PPT | 两页、nested group、text/table/picture、WMF/EMF、不支持对象 | slide/shape path、table、图片来源与 warning，真实 converter 内容 |
| XLSX/XLS | 多 sheet、空 sheet、合并格、日期、cached formula、无缓存 formula、宽/长 sheet | value/formula/source 三者、row/cell 坐标、merge，不声称重新计算 |
| 文本/混合 PDF | 中英、双栏、重复页眉页脚、标题、表格、内嵌图、矢量图、旋转页、短文字+图 | 正文/页/框/顺序，表格仅在能力实际实施后断言结构 |
| 真扫描 PDF/图像 | 清晰中英文、低质量/旋转扫描、数字表格、无字图、多页扫描、扫描与文本混合 | 先验证渲染；选定 OCR 引擎后再验证文字/数字/表格并记录 CER/WER 和失败覆盖 |
| SVG/多帧/异常图像 | 当前 SVG 复现样本、小图、坏图、EXIF、GIF/TIFF 多帧 | bytes/MIME 一致、首帧策略、归一化、warning |
| 独立 Ragas | 确定的 question/answer/context/reference rows，reference/no-reference、空输入、NaN、checkpoint 对齐 | 本地契约与失败处理；真实模型 smoke 单独显式记录配置版本和结果，不用 mock 充当真实评分 |

fixtures 需要记录来源/许可证、输入 hash、预期输出版本。外部图片失败用受控服务验证下载策略；核心离线 parse 不依赖随时变化的公网 URL。性能样本用于超时/取消/限额，不要求在此次文档任务运行完整套件。

## 8. TS 与 Python 的建议分工及下一独立任务

可纯 TS 实现的范围：文本/JSON/CSV/HTML/Markdown 文本部分、block 规范化与来源协议、全部结构分块与 semantic 数学、embedding/缓存编排、VLM OCR/Caption 模型调用、图片/Chunk 持久化、检索评测公式、dataset 审核、checkpoint、任务与报告。保持现有规则/降级/父子关系，避免借迁移删功能。

继续 Python 的范围：先复用成熟 PDF/Office/Excel/图像解析依赖与 renderer，以及精确 pin 的 Ragas 评分/测试集生成。Office/Excel/PDF 在技术上也可另选 JS 实现，但仓库没有等价 TS 实现或已验证 fixtures；不应为了语言统一在第一阶段重写并声称能力等价。LibreOffice 始终是外部 converter，不应归类为纯 Python。

建议下一可独立实施任务是 **“提取无 Django 的 parser worker 与 v1 parse 协议”**：新建独立 Python 包，只移动/复用 document_parsing 的纯函数、显式运行配置及能力探测，不导入 document_processing/multimodal/chunking/models；实现 parse/capabilities NDJSON 和 job 产物 manifest，修复 SVG 一致性并添加真实 fixture。该任务不依赖业务数据库迁移，可由 TS 用 fake worker 并行开发 caller。

该任务验收应直接证明：不设置 `DJANGO_SETTINGS_MODULE`、不安装 Django 即可解析；运行进程未加载 django/project models、未创建或访问业务数据库；stdout 完整可解 JSON、warnings/MIME/hash/provenance 保真；至少 TXT、DOCX、PPTX、XLSX、XLS、文本/扫描 PDF、SVG 有静态文件断言；DOC/PPT 的成功与缺 converter 均有明确结果；进程取消/崩溃只留下 job scratch，TS 不发布半成品。

Ragas 可作为第二个独立包随后提取，显式配置取代 `_clients(tenant)`，TS 提供答案和 contexts。chunking 的 TS 移植可利用现有算法 fixtures 独立进行，不让 Python worker 继续承担业务缓存与分块落库。

此次验证限于源码/依赖检查及无 Django 的入口/XLS/SVG probes；未运行 Django/前端/完整测试、真实 LibreOffice 转换、真实 OCR 或付费 Ragas 评分。文档检查：51 个本地链接均存在，JSON 示例可解码，新增文件 `git diff --no-index --check` 无空白错误。
