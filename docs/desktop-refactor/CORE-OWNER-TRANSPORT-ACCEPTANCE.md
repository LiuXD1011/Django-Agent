# Owner 传输接入与真实页面回归

日期：2026-10-12 01:30，北京时间。阶段1已接入开发HTTP与正式桌面fork；只读查询、同步发布取消及最终Windows安装仍未完成。[综合收据](../refactor-evidence/20261012-root-owner-move-real.json)绑定154份原始证据和来源哈希。未提交、发布或修改真实管理员凭据。

唯一 `CoreApplication/CoreIpcAdapter` 已在Node22 Worker中构造。HTTP可信facade仍先认证及检查范围再读取multipart，最终写入重新授权；fork保留私有JSON字节协议、请求界限、ACK、取消和正常关闭。原直接实例化真实核心的测试继续保留。[计划](CORE-OWNER-WORKER-PLAN.md)、[owner实现](CORE-OWNER-WORKER-IMPLEMENTATION.md)。

| 实际检查 | 结果 | 耗时与范围 |
| --- | --- | --- |
| 新HTTP认证、跨空间预检、Python上传/下载和重开 | 2项预期RED → 2/2 GREEN | GREEN TAP13641.690ms，真实SQLite/Worker/文件 |
| HTTP/IPC/桌面进程/诊断及新传输组合 | 29/29，0失败/取消/跳过 | TAP32212.627ms；命令32308.252ms |
| 类型检查 / 核心构建 | exit0 / exit0 | 命令17453.047 / 21470.628ms |
| Plain Node编译后owner与嵌套分块Worker | 2/2，0失败/跳过 | TAP10156.019ms |
| 桌面消费者IPC/runtime | 9/9，0失败/跳过 | TAP18438.066ms |
| 独立owner源码、私有边界、流及真实子进程生命周期 | 16/16，0失败/跳过 | 命令29284.533ms；核冻结10文件与22份命令证据 |

首次编译检查遗漏opt-in，两项实际跳过，日志原样保留；只有后续 `MARLIN_CORE_OWNER_COMPILED_TEST=1 node --test test/core-owner-compiled.test.ts` 的2/2计作编译验收。root检查的157项来源前后未变，编译产物和实时源码已核哈希。上述时长是检查命令时长。[命令](../refactor-evidence/20261012-root-owner-transports-checks/result.json)、[纠正后的编译检查](../refactor-evidence/20261012-root-owner-transports-checks/compiled-owner-real.json)。

## 真实页面结果

专用tenant3无模型，数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`。以下先操作Orca控件，再只读核对SQLite；没有绕过登录。

- MD类型实际只显示对应资料，清空恢复全部。抽屉关闭动画曾停在未呈现帧，正常截图触发呈现后恢复，未改DOM/CSS/动画强制结果，暂不认定产品缺陷。
- 两份自建短资料移动先取消再确认，文档名/哈希和分块序列ID保持，分块/FTS移入目标命名空间，标签正确映射；原大文件未移动。实际请求200、51.3ms。
- 批删先取消，文档/分块/标签/索引完全保留；再确认后两文档软删、分块/FTS清除、目标计数归零。请求200、57.7ms。源大文件仍1文档/11429分块。
- 新owner服务PID3714636使用同一隔离目录。新专用页正常cookie恢复身份，access自然过期时401→refresh200→me200，再正常打开知识库。
- 选择并提交198字节中文MD，请求73.8ms。打开Chunk，预算12345元/负责人李小川正确；源文件与存储哈希一致，1父块/1有效子块及FTS正确。root850ms、读取259ms、分块506ms、发布13ms，全部轨迹和任务结束。[上传只读断言](../refactor-evidence/20261012-root-owner-gui-upload-readonly.json)。

各请求只有一次ResourceTiming观测，不计完整交互、P95或并发能力。移动后的模型问答、跨权限目标界面、末页分块删除及最终安装版仍待执行，整组未完成。本轮模型SHA保持、global usage101/tenant3 usage0，零新增调用。此前另一账户的大文件重解析实际3次成功辅助请求/7571 tokens（4512/2948/2884ms），单列保留；随后取消点击没有实际cancel HTTP，不能计取消成功。

Windows PID25268真实导航并打开原验收库，显示5资料/10有效摘录。旧控件索引一次失败保留，立即读新快照再点击成功；该窗口仍为旧候选，不计最新owner安装通过。388来源安装包已构建未安装且早于本轮改造，须重新绑定来源构建。历史6.676秒同步发布中的业务读页与取消仍待修复；强制owner崩溃时的在途Python后代清理也未证明。

8份已消费临时脚本按哈希核对后删除；活动browser driver、精确停止脚本与私有认证文件保留供后续。[清理收据](../refactor-evidence/20261012-root-owner-consumed-helper-cleanup.json)。
