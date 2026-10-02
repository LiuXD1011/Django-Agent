## graphify

本项目在 graphify-out/ 中维护了一个知识图谱，其中包含核心节点（god nodes）、社区结构和跨文件关系。

当用户输入 `/graphify` 时，必须先使用已安装的 graphify 技能或相关说明，再执行其他操作。

规则：
- 对于代码库相关问题，如果 graphify-out/graph.json 存在，首先运行 `graphify query "<question>"`。查询关系时使用 `graphify path "<A>" "<B>"`，深入了解特定概念时使用 `graphify explain "<concept>"`。这些命令会返回限定范围的子图，通常比 GRAPH_REPORT.md 或原始 grep 输出小得多。
- 钩子或增量更新执行后，graphify-out/ 中的文件出现未提交的修改是正常现象；图谱文件有未提交的修改并不是跳过 graphify 的理由。只有当任务涉及过时或错误的图谱输出，或者用户明确要求不使用 graphify 时，才可以跳过。
- 如果 graphify-out/wiki/index.md 存在，应使用它进行整体导航，而不是直接浏览源代码。
- 仅在进行整体架构审查，或者 query/path/explain 未提供足够上下文时，才读取 graphify-out/GRAPH_REPORT.md。
- 修改代码后，运行 `graphify update .`，以保持图谱最新（仅使用 AST，不产生 API 费用）。
