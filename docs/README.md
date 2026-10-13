# 项目文档

## 使用与运维

- [项目说明](../README.md)
- [本地桌面运行](desktop.md)
- [Windows 构建与安装](windows-installer.md)
- [旧实现清理与保留范围](desktop-refactor/LEGACY-CLEANUP.md)

## 当前设计与待办

- [TypeScript 桌面重构进度](desktop-refactor/STATUS.md)：当前实施主线，Electron、Vue、SQLite及独立解析/评测辅助进程。
- [真实测试报告](desktop-refactor/TEST-REPORT.md)与[完整验收矩阵](desktop-refactor/TEST-MATRIX.md)：区分自动化、页面、厂商模型与安装版结果。
- [个人知识库跨设备架构方案](个人知识库跨设备架构方案.md)：保留个人隔离与远程、多设备访问设计；新桌面核心不依赖旧Django服务器。
- [跨设备第一批实施报告](cross-device-evidence/README.md)：旧Django阶段的个人空间、Cookie设备会话、移动网页/PWA验证记录，不替代当前TS核心验收。
- [历史团队商用重构方案](重构方案.md)：保留审计与扩容参考；团队协作、千人容量不作为当前主方案的默认目标。
- [最新代码复核与收尾](refactor-evidence/CLOSEOUT.md)：已修复项、实际验证和剩余阶段。
- [评测工作台业务逻辑修复方案](evaluation-workbench-business-logic-fix-plan.md)
- [会话条目树设计](session-tree-refactor-plan.md)：待排期，不代表已上线。
- [轨迹事件与投影设计](trajectory-event-sourcing.md)
- [工具调用失败处理](tool-error-handling.md)

## 评测资料与历史复核

- [旧Django Langfuse运维记录](langfuse-operations.md)：保留当时的配置和诊断命令；当前应用入口见[桌面运行](desktop.md)，TS迁移及实际验证边界见[测试报告](desktop-refactor/TEST-REPORT.md)。
- [Open RAG Benchmark 180 题关联文档说明](open-rag-benchmark-180-documents.md)
- [关联文档清单](open-rag-benchmark-180-documents.csv)
- [Langfuse 实施复核报告](langfuse-implementation-report.md)：历史验证与未完成验收范围。
- [重构阶段记录](refactor-evidence/README.md)：历史测试口径，不替代最新收尾报告。

旧Django设计、运维和报告中的 `manage.py`、旧启动器及业务源码路径均是历史引用，不作为当前启动或检查入口。DATA/PARSER基线的174条源码引用由[历史来源映射](refactor-evidence/20261013-legacy-retirement-prepare/HISTORICAL-SOURCE-MAP.md)指向精确`.txt`快照；其他旧源码可按[301项归档清单](refactor-evidence/20261013-legacy-retirement-prepare/RETIREMENT-FILES.md)查阅。原失败、条件跳过、样本来源与许可证保留。

## 文档清理

已移除重复的旧 Langfuse 执行方案、过时的设置实施记录、旧公开数据集临时计划及
阶段测试日志。有效操作说明归入运维手册；未完成设计和验收边界继续保留。
本机原文件与 SHA256 位于 `.cache/docs-cleanup/`，不随仓库分发。

`media/` 是知识库运行文件目录，包含按租户、知识库分隔的上传原文与图片等产物；
它不是文档目录或前端构建缓存。本次清理不修改该目录。
