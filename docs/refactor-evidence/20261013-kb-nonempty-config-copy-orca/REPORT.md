# 非空知识库配置复制实际验收

2026-10-13，Orca 专属已登录 QA 页 `d33064fa-a31e-416d-82c6-80339b47543c`，Vue5173→同一真实TS Core8000，数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`。本轮没有生产修改、接口注入、认证绕过或模型调用。

实际指针点击原库「复制」→刷新→打开副本→返回列表→仅删除副本→确认删除。原库为「Orca 全流程验收 20261010」，含2份文档。结果：副本名称正确，配置全部对应字段逐字一致，副本0文档、0分块与相关索引；刷新后保留，打开正常显示空状态。这符合既有只复制配置的语义。[复制后的页面](011-copy-state.json)、[副本详情](021-copy-detail.json)、[只读配置核对](copied-audit.json)。

本轮副本ID `d07e8eb4-b64c-44c8-a5fc-9eb2e08c0b6f` 已通过页面确认删除，软删除记录保留、相关索引零残留。原15条含历史软删除的库记录、11张受保护业务表和25个管理文件均保持；模型用量仍174、活动任务0。[删除核对](deleted-audit.json)、[最终页面](040-final-visible.json)、[最终截图](041-final-list-screen.png)。未将这一子用例计为整个知识库验收组完成。

真实浏览器 ResourceTiming，单次本地样本：复制请求200，46.9ms；随后列表与侧栏请求200，145.2/196.5ms；删除请求200，63.4ms，随后列表与侧栏80.3/132.3ms。这些是请求区间，不代表点击到最终绘制的完整耗时，也不推算P95。[复制请求计时](012-copy-performance.json)、[删除请求计时](039-delete-performance.json)。命令调用耗时另存，未冒充产品延迟。

工具问题如实保留：最初只读audit因当前Python缺少os.pidfd_open退出1，改用已验证Linux x64 syscall434获取实际原PID句柄，断言未放宽，随后before/copied/deleted均0。期间一次截图恰在页面隐藏时捕捉到尚未结束的渐入效果，仅作原始记录；恢复Orca窗口和专属页后重新核对visible状态，最终截图正常。未修改DOM或强制动画。[原audit失败](first-audit-failure.json)、[修订前脚本](audit-helper.initial.source.py.txt)。

临时执行脚本归档后精确删除，QA认证文件暂为后续安装版合法登录保留；未读取密码或解密Key。[清理回执](helper-cleanup.json)。按照用户「选择性跳过一些步骤，快速收尾」的要求，不追加重复全量测试或独立冻结审计。
