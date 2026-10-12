# 非空知识库与微型 HTML 真实浏览器补验

2026-10-12 03:07:48–03:24:05 UTC，通过 Orca 真实操作完成一个新知识库的 HTML 入库、正文检查、库名称与描述编辑、搜索、刷新、删除取消及确认删除。唯一入库任务耗时 **8.688 秒**，新增 **4 次成功模型调用、605 tokens**；关联正文块、FTS、实际 vec0 行和源文件均清除。仅此组合场景通过，JSON/SVG、非空 Wiki/远端图谱清理、Windows 安装版及全部 B/C 组没有据此通过。

## 环境与范围

- 固定自有 page6：`22e0e212-30aa-4945-8a3d-7176cdfffdff`，`localhost:5173`，实际界面为 TypeScript 应用；Root 提供核心 PID2245508/startTicks17581590/session7456。此报告没有独立重启或操作该进程。
- 数据目录：`/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`，tenant2 的专用 QA 账户。未注销、修改密码、管理设备、改变原模型/Key/global 配置或触碰离线导出与 Windows 安装目录。
- [矩阵](TEST-MATRIX.md)中的 B-01/B-02、UI-KB-004/005、C-01 的 HTML 和部分 C-03 子项；其余并列行为分别保留原状态。此次编辑对象是知识库名称/描述，正文块只打开核对，未编辑正文块或触发重解析。
- 全部业务写入经 Orca typed CLI 的页面点击、正常输入/键盘、文件输入选择完成；`eval` 仅读取 DOM/ResourceTiming。SQLite 后置断言使用 native readonly 或 `mode=ro`/`query_only`/同步快照，没有 API/SQL 造业务数据。
- [源绑定](../refactor-evidence/20261012-browser-nonempty-format-followup/075-readonly-source-binding.json)记录 10 个相关源码 SHA；本任务未改源码、测试、构建、依赖或主进度文档。

## 先核查零模型路径

[实际新建弹窗](../refactor-evidence/20261012-browser-nonempty-format-followup/006-new-library-controls.json)只有混合检索、Wiki、图谱三种索引选择；混合检索明确说明同时启用向量和关键词。没有分别控制 keyword/vector 或摘要的选项。[关闭索引后](../refactor-evidence/20261012-browser-nonempty-format-followup/009-disabled-index-controls.json)的三个索引均为 false；[DOM](../refactor-evidence/20261012-browser-nonempty-format-followup/010-disabled-controls-readonly.json)证明 Create 位于可见视口 y405/height32。

[实际点 Create](../refactor-evidence/20261012-browser-nonempty-format-followup/011-all-index-off-create-attempt.json)后，[弹窗仍在且无新增 KB 请求](../refactor-evidence/20261012-browser-nonempty-format-followup/012-create-validation-readonly.json)，[后置数据库](../refactor-evidence/20261012-browser-nonempty-format-followup/013-after-no-index-attempt.json)仍为 ownKB0/usage170/0active。短提示已消失，未宣称核对其文字。[KnowledgeBases.vue](../../frontend/src/views/KnowledgeBases.vue)第49–53行将 vector/keyword 绑在同一 setter，第127行拒绝所有索引关闭；这是源码解释，不替代页面证据。

[实际上传弹窗](../refactor-evidence/20261012-browser-nonempty-format-followup/029-upload-controls-single-file.json)仅有分块设置及本次图谱开关，没有 vector/wiki/summary-off 控件。[KnowledgeDetail.vue](../../frontend/src/views/KnowledgeDetail.vue)第328–335行仅发送 chunking/graph/extract 配置；[pipeline](../../packages/core/src/documents/pipeline.ts)非空正文 postprocess 第325行列出 summary/questions/metadata 三项调用。故不将当前四模型配置下的普通上传当作无付费操作，也未为验收新增控制入口。

Root 在确认上述限制后，明确授权仅一个微型 HTML、最多6新增用量行/10分钟、不重试；JSON/SVG 不得混入。本报告后续按该有界授权执行。

## 唯一输入、选择与提交

新自有 KB：`51fcf8ab-6c68-4ac1-ae8d-2fbcffcfe00d`，初始名 `Orca 非空 HTML 补验 20261012`。[真实配置](../refactor-evidence/20261012-browser-nonempty-format-followup/024-own-library-created-proof.json)：hybrid(vector/keyword true)、Wiki/graph false、recursive512/overlap80、parent-child false、token_limit0。首次普通点击父子开关未改变状态，原[016](../refactor-evidence/20261012-browser-nonempty-format-followup/016-disable-parent-child.json)/[017](../refactor-evidence/20261012-browser-nonempty-format-followup/017-safe-empty-library-form.json)保留；随后 [focus](../refactor-evidence/20261012-browser-nonempty-format-followup/018-focus-parent-toggle.json)+[Space](../refactor-evidence/20261012-browser-nonempty-format-followup/019-keyboard-disable-parent.json)，[020](../refactor-evidence/20261012-browser-nonempty-format-followup/020-create-form-final.json)才实际为 false，未把无效点击算通过。

唯一文件 [01 中文 HTML 小表.html](<../refactor-evidence/20261012-browser-nonempty-format-followup/fixtures/01 中文 HTML 小表.html>)，480B，SHA256 `41f79e2e5678819e95df868851e41755dd4d18f2b1a5dd7ab840eaa4828bd7ba`；标题/小表含验收标识 `HTML-QA-51FC`、维护人许清、14天保留期、7台×23元=161元，无图片、脚本或外链。[输入清单](../refactor-evidence/20261012-browser-nonempty-format-followup/027-html-fixture.json)记录中文空格临时路径及事实。

[实际文件输入选择](../refactor-evidence/20261012-browser-nonempty-format-followup/028-queue-only-html.json)后，[029弹窗](../refactor-evidence/20261012-browser-nonempty-format-followup/029-upload-controls-single-file.json)/[030 DOM](../refactor-evidence/20261012-browser-nonempty-format-followup/030-upload-preflight-dom.json)确认唯一480B HTML、recursive、parent false、graph false、Start y405 可见。[031](../refactor-evidence/20261012-browser-nonempty-format-followup/031-before-single-html-start.json)确认仅选择阶段 ownDocs0/ownChunks0/usage170，未先入库。前端选择后清空原 file input，所以030的 files 数组为空；队列文件以029的实际弹窗为证，未把该空数组误判为没有选择。

[032](../refactor-evidence/20261012-browser-nonempty-format-followup/032-start-single-html-once.json)唯一点击开始解析，之后没有再点击开始/重解析/重试；[033](../refactor-evidence/20261012-browser-nonempty-format-followup/033-html-processing.json)实际处理中，未 reload 的[035](../refactor-evidence/20261012-browser-nonempty-format-followup/035-html-completed-ui.json)已自动显示完成/0处理中，[截图](../refactor-evidence/20261012-browser-nonempty-format-followup/036-html-completed-screenshot.png)已实际查看。

## 正文、阶段和用量

[037完整数据库断言](../refactor-evidence/20261012-browser-nonempty-format-followup/037-html-business-terminal.json)：doc `c73a1583-80d8-4cd6-adac-d9c09d09621c`，job `d625c757-200d-495c-9f18-2ff57dc75786`，request `kohauwkw3pc`，attempt1/manual/completed/progress1/0pending/0warnings；parse与summary completed、workflow completed、vector ready1024。实际受控源文件 SHA 与480B输入一致。

Canonical 正文142 Unicode code points，HTML标签被解析为文本，标题、许清、14天、小表的数量/单价/总额均完整；1个可检索正文块，start0/end142、0父块/0图片、recursive无fallback。[实际打开 Chunk](../refactor-evidence/20261012-browser-nonempty-format-followup/038-open-html-chunks.json)及[039正文/时间轴](../refactor-evidence/20261012-browser-nonempty-format-followup/039-html-chunk-content.json)显示相同内容，未据此宣称保留 HTML 表格视觉布局。

| 阶段 | 实际终态 | 持久化耗时 |
| --- | --- | ---: |
| docreader | done，142字符/0图 | 332ms |
| chunking | done，1正文/0父块 | 512ms（诊断纯计算2ms，含 Worker 路径开销） |
| publish_local | done | 16ms |
| multimodal | done，0图/0图像块，未执行OCR调用 | 2ms |
| embedding | done，indexed1 | 500ms |
| postprocess | done，106字符摘要/5问题/元数据 | 7236ms |
| graph / Wiki | skipped / skipped | 15ms / 12ms |

Root span 8669ms，job 03:15:21.680–03:15:30.368 UTC，共8688ms；实际 UI 轨迹显示8.7s。未混入 Orca 每命令4–7秒的工具等待，也未用一次观察推断P95。

| 模型场景 | 成功/请求数 | prompt / completion / total | 实际调用耗时 |
| --- | --- | --- | ---: |
| Embedding | 1 / 1 | 80 / 0 / 80 | 311ms |
| summary（原GLM） | 1 / 1 | 117 / 66 / 183 | 3888ms |
| questions（原GLM） | 1 / 1 | 109 / 56 / 165 | 1590ms |
| metadata（原GLM） | 1 / 1 | 109 / 68 / 177 | 1734ms |

四用量行均关联上述 request/job/doc/attempt，独立ID、success1、result_unknown0；415prompt+190completion=605tokens，cache/reasoning0。全局170→174，后续编辑/搜索/删除仍174。摘要/问题/提取字段实际准确对应输入，未发额外问答以制造检索通过。

## 非空库编辑、搜索与删除

仅编辑新库：[045名称](../refactor-evidence/20261012-browser-nonempty-format-followup/045-edit-own-library-name.json)增加“已编辑”，[046描述](../refactor-evidence/20261012-browser-nonempty-format-followup/046-edit-own-library-description.json)填验收标识与资料范围，[047保存](../refactor-evidence/20261012-browser-nonempty-format-followup/047-save-own-library-settings.json)后[048](../refactor-evidence/20261012-browser-nonempty-format-followup/048-own-library-settings-saved.json)标题已更新。设置弹窗按现有实现仍在，随后仅[049关闭](../refactor-evidence/20261012-browser-nonempty-format-followup/049-close-saved-settings.json)，没有假称保存自动关闭。

[050真实reload](../refactor-evidence/20261012-browser-nonempty-format-followup/050-reload-own-library.json)→[051](../refactor-evidence/20261012-browser-nonempty-format-followup/051-own-library-edited-refresh.json)保持新名称/1文档/1摘录/0处理中；[052 SQL](../refactor-evidence/20261012-browser-nonempty-format-followup/052-own-library-edited-proof.json)文档和块 SHA 与037相同，原keyword/vec/meta/source仍在，未悄悄重解析或调用模型。

[055输入描述标识](../refactor-evidence/20261012-browser-nonempty-format-followup/055-search-own-library-description.json)+[056 Enter](../refactor-evidence/20261012-browser-nonempty-format-followup/056-submit-library-search.json)，[057](../refactor-evidence/20261012-browser-nonempty-format-followup/057-search-one-nonempty-library.json)恰好一个自有非空库；[058真实刷新](../refactor-evidence/20261012-browser-nonempty-format-followup/058-refresh-filtered-library-list.json)后[059](../refactor-evidence/20261012-browser-nonempty-format-followup/059-filtered-list-refresh-proof.json)仍1库/1条目/1摘录。这是知识库描述搜索，未宣称执行内容召回/模型问答。

[060删除](../refactor-evidence/20261012-browser-nonempty-format-followup/060-open-delete-own-nonempty-library.json)→[061确认对象](../refactor-evidence/20261012-browser-nonempty-format-followup/061-delete-nonempty-confirmation.json)→[062取消](../refactor-evidence/20261012-browser-nonempty-format-followup/062-cancel-own-nonempty-library-delete.json)，[063](../refactor-evidence/20261012-browser-nonempty-format-followup/063-cancel-nonempty-delete-proof.json)KB/doc/chunk/FTS/vec/meta/source/job等与052一致。随后[064重新打开](../refactor-evidence/20261012-browser-nonempty-format-followup/064-reopen-own-nonempty-delete.json)/[065对象核对](../refactor-evidence/20261012-browser-nonempty-format-followup/065-own-nonempty-delete-confirm-preflight.json)，[066](../refactor-evidence/20261012-browser-nonempty-format-followup/066-confirm-delete-own-nonempty-library.json)才确认一次；[067](../refactor-evidence/20261012-browser-nonempty-format-followup/067-after-nonempty-delete-ui.json)筛选结果0。

[068数据库与文件](../refactor-evidence/20261012-browser-nonempty-format-followup/068-after-nonempty-delete-business.json)证明 KB/doc 于03:22:52.540UTC软删，activeDoc0、chunks0、旧FTS rowid `675847552571479314` 0、注册0、vector_entries0、index_meta0、源文件不存在。[044 native readonly vec0](../refactor-evidence/20261012-browser-nonempty-format-followup/044-vector-before-delete.json)与[069删除后](../refactor-evidence/20261012-browser-nonempty-format-followup/069-vector-after-delete.json)对精确 table/64bit rowid读取实际向量行 **1→0**；不是仅以注册表消失推断向量清除。连接明确 readonly/fileMustExist/query_only，既有 sqlite-vec 扩展只加载到该只读连接，没有另开写者或DDL。

任务/远端边界：[074](../refactor-evidence/20261012-browser-nonempty-format-followup/074-association-boundaries.json)完成job1/task1/spans9/事件21留作审计，没有active job/task；artifact cleanup pending0/Wiki pending0。仍有2个既有设计的远端图清理 pending（doc delete、delete_knowledge_base，generation null），不宣称远端图清理完成或所有关联行物理归零。Wiki/graph未开启，所以未验证非空 Wiki/图谱删除。

[071实际ResourceTiming](../refactor-evidence/20261012-browser-nonempty-format-followup/071-nonempty-delete-latency-dom.json)：新库GET200/23.9ms、描述搜索200/330.9ms、刷新200/13.3ms、非空DELETE200/387.5ms、后续清单200/193ms。均为各次n=1、Root Windows后台封装负载条件；此前上传/保存的 ResourceTiming已随reload清空，不补造HTTP耗时。最后[072正常reload](../refactor-evidence/20261012-browser-nonempty-format-followup/072-final-reload-unfiltered-list.json)/[073](../refactor-evidence/20261012-browser-nonempty-format-followup/073-final-unfiltered-original-libraries.json)还原原两库清单16文档/10027摘录/0处理中，删除的最近访问项消失；已向Root释放GUI。

## 保护与验证限制

[001前置](../refactor-evidence/20261012-browser-nonempty-format-followup/001-before-protected.json)与[070终态](../refactor-evidence/20261012-browser-nonempty-format-followup/070-after-nonempty-delete-protected.json)原4models全行SHA、vault文件SHA、原2KB/gold2docs/13chunks/13Wiki/3testsets及既有MCP/Web行摘要完全一致，tenant2 Web KV仍NULL。没有输出明文Key/密码/token/header，也没有把hash相同扩展为调用费用或厂商账单核对。

只更新本文与新证据目录；按AGENTS进行链接/差异、原始断言和哈希检查，不因文档工作重跑产品全套。临时辅助脚本及原Windows输入副本按精确路径归档/删除，证据fixture保留。JSON/SVG未选择或提交，原冻结报告/失败记录保持，整个Goal仍active。
