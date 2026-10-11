# 知识库分块统计读取优化

日期：2026-10-11。授权范围：`knowledge/domain.ts`、`knowledge/index.ts` 的统计读取、独立真实 SQLite 回归测试及本设计/证据。完整应用 owner Worker 改造、GUI、实时数据、模型和大文件/profile不在本轮范围。

## 问题与最小设计

root实际空闲GET观察为约1.51–1.64秒，现有知识库含11,429块；本轮不重复该数据操作。已完整读取 [domain.ts](../../packages/core/src/knowledge/domain.ts)、[index.ts](../../packages/core/src/knowledge/index.ts)、[database.ts](../../packages/core/src/storage/database.ts)，并核对真实接口/现有测试和 `searchableTypes`。

`kbDto` 和 `stats` 为统计逐块调用 `chunks`，查ID后再读每条完整正文/metadata。新增同步域方法 `chunkCounts(ctx, kbId)`，先复用当前KB读权限/未删除校验，再用同一聚合SQL计算总数和可搜索类型数。SQL匹配chunk/doc/KB的tenant和KB，并排除三者soft delete。`searchable`集合从现有 `searchableTypes` 绑定参数，避免复制类型定义。

只替换kbDto的块水合及两个计数字段、stats的chunk_count；文档读取及其他DTO字段保留。不开新连接，不缓存，不删正文，不改变检索/向量或事务。真实 CoreDatabase `get` 返回规范化的 SQLite 行，safe integers仍按现有规则处理；使用现有同步连接API，不猜测异步接口。

| 现有字段 | 保留统计含义 |
| --- | --- |
| kbDto.chunk_count | 未删除且namespace一致的text/image_ocr/image_caption块，含disabled块与disabled文档 |
| kbDto.total_chunk_count | 同范围全部类型，包含parent及非可搜索类型 |
| stats.chunk_count | 同范围全部类型，与原 `chunks.length` 一致 |
| 空知识库 | 所有分块数为0 |

不能添加 `is_enabled`、文档 `enable_status` 或 `source_generation` 筛选。KB未删除、doc未删除与tenant/KB/knowledge_id关系必须保持。need_reindex、effective chunking、last_effective_strategy、processing和状态计数逻辑不调整。

## TDD 与验证计划

先建立小型、独立临时SQLite库，插入parent/text/OCR/caption/其他类型、禁用、软删、其他KB/tenant和不一致namespace。用旧 `domain.docs(...).flatMap(domain.chunks(...))` 作为行集合基线，并明确断言现有计数字段。真实方法观测记录统计调用是否读取 `chunks` 行；观测继续执行原DB方法，不伪造返回值。

第一轮必须由现有实现真实触发“统计仍水合正文/metadata”失败，然后实施最小SQL聚合。覆盖两入口、空集、统计新鲜性、soft delete、权限拒绝和其它DTO不变；不通过新增更窄过滤或放松断言变绿。随后运行新测试、相关knowledge/retrieval测试、core typecheck/build，检查设计链接/差异并清理临时脚本。

此回归证明读取工作减少和计数语义，不证明实时GET已达到某个预算，也不解决约6.7秒同步发布阻塞。root另负责真实GET复测与前端保存后刷新。

## 证据

已实施授权范围的最小聚合读取。两计数入口实际观察的 `chunks.read` 从各10次降为0次；真实SQLite计数及其它DTO语义断言保持。没有改动迁移、索引、检索或其它域写入。

| 检查 | 结果 | 命令总耗时 | 证据 |
| --- | --- | --- | --- |
| 原实现新回归 | 3 PASS / 2 FAIL；两个失败均为10次水合而非0 | 6,876.554 ms | [RED](../refactor-evidence/20261011-knowledge-counts-red.json) |
| 聚合实现新回归 | 5/5 PASS | 6,844.080 ms | [GREEN](../refactor-evidence/20261011-knowledge-counts-green.json) |
| 相关knowledge/application/status/retrieval | 95/95 PASS | 27,320.104 ms | [相关回归](../refactor-evidence/20261011-knowledge-counts-related.json) |
| `npm run typecheck` | exit 0 | 15,805.083 ms | [类型检查](../refactor-evidence/20261011-knowledge-counts-typecheck.json) |
| `npm run build` | exit 0 | 19,210.122 ms | [核心构建](../refactor-evidence/20261011-knowledge-counts-build.json) |

这些是测试/构建命令时间，包含fixture初始化和进程启动，不是页面延迟，也不是P95。没有运行40,000行入库/profile、实时库或GUI；既有检索测试的模型协议只使用本地fixture，未调用外部模型。

[真实小型查询计划](../refactor-evidence/20261011-knowledge-counts-query-plan.json) 捕获当前方法实际执行的聚合SQL，并在2块临时库执行 EXPLAIN：`chunks_space_library (tenant_id=? AND knowledge_base_id=?)`，doc/KB主键lookup。没有新增索引；这里证明现有范围索引使用，不证明任意数据量的时间上界。SQL仍访问chunks表计算类型/删除状态，只避免把正文/metadata水合到JavaScript，不能宣称SQLite完全不访问相关数据页。

命令JSON保存起止、耗时、原输出SHA及相关源文件前后SHA；新增测试覆盖旧计数集合、软删/禁用/父与图像类型、其它namespace、空集/新鲜性和persisted权限。最终清理/源码绑定保存在 [冻结与清理凭证](../refactor-evidence/20261011-knowledge-counts-final.json)。安装包和真实闲时/发布中页面仍由root后续验收，本轮结果不等同约6.7秒同步发布问题已修复。
