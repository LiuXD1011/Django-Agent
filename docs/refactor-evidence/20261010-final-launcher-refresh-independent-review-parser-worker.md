# 本轮 Final launcher refresh 独立只读核对

日期：2026-10-10；审查者：parser_worker。

结论：本轮正式 prepare 的归档、实际 stage 报告、当前来源及 Electron 分发哈希一致，未发现证据绑定漂移。Root 的实际 Windows source CLI smoke 已退出 0；这项证据不证明 GUI 页面就绪。没有执行 GUI、测试、安装或付费请求，没有修改 source/stage。

已全文读取 [本轮 proof](20261010-windows-repository-final-launcher-refresh-proof.json)、[上轮 proof](20261010-windows-repository-final-refresh-proof.json)、本轮 summary/exit 及 [root smoke](20261010-root-source-desktop-smoke.json)。大映射由只读 Python 解析全部内容并逐项比较，未截取采样。

## 实际复算

| 检查 | 结果 |
| --- | --- |
| 本轮 `repository_evidence` | 14/14 仓库归档的实际 size/SHA 均匹配；14/14 其实际 Final stage 来源文件的 size/SHA 也匹配。 |
| 实际 prepared / gates / payload manifest | 三份实际 stage 字节均与仓库归档完全相同，SHA 与 proof 相同，见下表。 |
| 全部来源 | 按当前 builder 的七个 source folders、public 排除规则和固定 build/desktop/package 输入名单重算，共 361；文件名与 SHA map 和 prepared/gates/manifest 完全一致，当前 workspace 差异为 0。 |
| 相对上轮来源 | 恰好 `scripts/desktop/start-desktop.cjs`、`scripts/desktop/startup.test.cjs` 两项 SHA 变化，没有新增、缺失或其他来源漂移。 |
| payload | 两轮 `files` 映射逐项完全相同，共 25,279；这里验证的是完整映射及其实际 manifest 字节绑定，没有重新哈希 25,279 个 payload 实体。 |
| Electron | 两轮完整 `electron_distribution` 相同，共 73 文件；另实际读取 Final stage 的全部 73 个 dist 文件复算，名称/SHA 完全匹配，package.json/path.txt SHA 也匹配。 |
| desktop | prepared/gates 的完整 10 项 desktop map 一致；实际 app 下 10 文件 SHA 全匹配。 |
| gates | `verified`、`scope:frozen_source`、before/after equal、paid calls 0；core 24/24、runtime 6/6，失败/跳过为 0；native/python/Langfuse 三份归档报告实际 SHA 与 gates 绑定一致；manifest Django=false。这是既有门禁的证据核验，没有重跑测试。 |

| 标识 | 独立复算 SHA-256 |
| --- | --- |
| prepared-build.json | `44272b04f54ff0a03f56bbe5ebca502f6267086ac1b862f0e413ff6b45cc1629` |
| windows-gates.json | `860dba721dd62e74ad76a236c5db5585b43b8d5d89e1de168a52efac7832b8aa` |
| source-manifest.json | `0082290f3a4dcd9b6c0d8c067914a05e7b853b26f4f81464198eec24a656d559` |
| 361 来源 canonical map | `d6b1e96898c25953b3b7449ea4daed72bc003b44e7b5c54019d51945ae743c03` |
| Electron canonical distribution | `6f7130c0a9845676199bc4013611a2c20b59f06c62f0e9fe5ff37678f370c3c9` |

两组只读断言命令均退出 0。没有创建临时脚本，命令使用 `python -B` stdin；仅新增本报告。

## Source CLI smoke 与适用边界

Root 的 [实际 Windows smoke](20261010-root-source-desktop-smoke.json) 绑定上述 prepared/gates 和当前 launcher SHA，exit 0；报告的 `ok`、Vue mounted、native IPC 与 TypeScript core ready 均为 true，HTTP listener=false、nodeExposed=false。

- `startup_ms = 1604.8697` 是该次内部启动测量。
- `command_wall_duration_ms = 107553.7582` 是整条命令耗时，包含 source/runtime 哈希核验。
- 测量仅单样本，不是干净机器冷启动或性能承诺。
- Root 观察 PNG 仅有背景，本审查没有打开/操作窗口。`manual_gui_verified:false`、`installer_verified:false`、paid calls 0 原样保留；不能把 mounted 或 exit 0 当成登录页可见/可交互验收。

本轮 proof 的 `formal_prepare_verified_source_cli_smoke_pending` 是 prepare 归档时的历史状态；之后的 root smoke 独立补上 CLI 结果，未改写历史报告。本次也不宣称尚在另一路执行的 NSIS 打包、安装或厂商评测已通过。
