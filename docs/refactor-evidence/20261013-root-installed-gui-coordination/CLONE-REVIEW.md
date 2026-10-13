# Root 对安装版业务副本的具体审核

2026-10-13。依据 Goal 第二节第 3 项与第五节，批准恰一次固定新目录的数据复制；这项工作属于已授权的隔离安装验收。

Root 已完整阅读 [复制代码](../20261013-owned-runtime-installed-gui-preparation/clone-helper.source.txt)及[复制阶段说明](../20261013-owned-runtime-installed-gui-preparation/CLONE-REVIEW.md)，并重新核验 live helper、归档代码和 Python 的 SHA。Windows worker 的只读 preparation session14376 已 actual exit0，同原 HANDLE 的 PID21948/FILETIME134363465628563183、conhost13584/FILETIME134363465628629601 均 Wait0/Exit0/Jobactive0，且新 DATA/CONTROL 尚不存在。上述过程未启动产品、sentinel 或复制数据。

批准范围：固定源 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`，固定目标 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\业务验收 20261013`。使用只读 SQLite 事务与 backup 保留 WAL 中的有效记录；复制 25 项已绑定材料，并核对所有表、关联、schemaVersion1、无活动任务及专用 QA 身份哈希。不得覆盖已有目标，失败保留原收据和新目录，不自动重试。

审核绑定 SHA `1fee18414a69424b5f91c26d140fe2565ac76aa491221da66463904129768e61`；代码 SHA `d0f79323fddb2a3d26e8477379cbc0076987aff2b3fed743005ae809ea8ba6fe`；固定 Python SHA `9efaae159cb926dc4416a1ba8e07e02837ea87f773f18224b9910305e3e9b683`。绑定继续区分旧 468 来源的 869a 安装包、已完成升级的 inner exit0 与原 outer 工具 exit1，当前后续源码不进入该安装包的身份。

具体命令：

```sh
/home/liuxuedeng/anaconda3/bin/python -B /tmp/marlin-installed-gui-clone-20261013.py --execute-reviewed-clone --binding-sha 1fee18414a69424b5f91c26d140fe2565ac76aa491221da66463904129768e61
```

本次批准仅覆盖复制。正常 Electron 启动、有限控制协议与 sentinel 将另行读取完整代码后审核。复制结果只能据实际 terminal 与收据记录，不能据本批准文件称为通过。
