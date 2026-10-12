# 已安装包后验证继续交接

[原 hidden receipt](../20261012-root-cancel-installed-launch-preparation/executed-hidden-smoke.json) 状态仍为 failed_manual_review_required，SHA `d7cc7d772cc3abb17b4c9fe3baa6fe905aba6ae69bc7b56e55f02246f6586ea5`。真实窗口挂载/preload IPC、schema、bundled Node 原生 FTS/vec/Owner+Query、bundled Python 无 Django、三个 Job 全退出、原保留数据未变已有原始结果；末尾进程 guard 未通过，原记录不改、不删 WORK、不重放 hidden。

[本次只读调查](readonly-process-survey.json) 在 2026-10-11 22:14:09 UTC 使用原过滤的 CIM 投影查到候选 0。Win32 只读句柄核验原 PID25268：exe/创建 FILETIME134361236166333286完全相同，Wait258、Exit259、仍活动。未读 CommandLine、未启动或结束产品。失败当时没有记录候选 PID，原因无法还原，不能将 WMI缓存或用户额外启动当成已证实根因。

[新脚本](postvalidation-continuation.source.txt) 共121行，默认 review_only，只复用原已审核 688 行归档 module 的函数（固定 SHA）。其两个明确 phase 为 postvalidate 和 visible-retained；只有 root 全读后显式执行。原 main、188 文件、failed receipt 均不修改。新证据与实际结果均写本目录。

postvalidate 只核原 failed 与 WORK 副本 SHA、原 smoke 截图/result SHA、实际 hidden DB只读schema、原 native/Python JSON与三项 Job/log事实、helper确已删除，然后执行原精确 process_preflight（仍必须候选0）、registry guard、同固定17+274安装关键文件、原90文件/12表/vault key、保护25268。独立写 executed-postvalidation-continuation.json，状态 verified_postvalidation_continuation，只称新后验证通过。原failed状态保持，原因未还原，不重跑模型/IPC/Marlin。

root已看到 hidden 截图只有背景；mounted仅证明 app 子节点存在。新receipt明确 mount_only=true、page_ready_not_verified=true、interactive_cold_start_not_verified=true，3231.9168ms仅原mounted测量，不能称登录页已就绪或可交互冷启动。

visible-retained 必须引用实际成功恢复receipt的SHA，同script/failed原件/安装身份。仍固定已安装Marlin.exe和原‘验收数据 二次’，启动前原离线数据/auth envelope/0活动任务保护不变。使用原专有Job、7200秒、每5秒状态输出、新PID/exe/创建时间receipt；root真实GUI验证后该新窗口托盘退出，helper等待完整Job0/exit0再核表完整性/原密钥/安装关键文件/注册表/保护25268。真实GUI注销后ipc.session可缺席；不推断模型次数，不称人工GUI通过。原四模型PID25268保持独立，本保留目录模型0。唯一主脚本留给root消费，异常不自动重试。

[非执行检查](nonexecuting-checks.json)：Linux默认exit0、Windows两phase仅review均exit0、Windows缺hash的visible执行被argparse拒绝exit2；没有提供完整执行授权。新postvalidate和visible尚未执行。原mounted/native检查由root原实际执行所得，不由本次守卫冒充。

## 1. root执行独立后验证

```bash
/mnt/c/Python313/python.exe -I -B \
  '\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-installed-postvalidation-20261012.py' \
  --phase postvalidate --execute-reviewed-continuation \
  --reviewed-script-sha256 6a9546e0ae17b41f2c5846bbdd96d5cfd8fa6269d2231627c377365dd9b5ccf4 \
  --failed-receipt-sha256 d7cc7d772cc3abb17b4c9fe3baa6fe905aba6ae69bc7b56e55f02246f6586ea5
```

## 2. root审阅成功receipt后启动可见窗口

```bash
python3 -I -B - <<'PYROOT'
from pathlib import Path
import hashlib,json,subprocess
receipt=Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-installed-postvalidation-review/executed-postvalidation-continuation.json')
raw=receipt.read_bytes();value=json.loads(raw)
assert value['state']=='verified_postvalidation_continuation'
assert value['reviewed_script_sha256']=='6a9546e0ae17b41f2c5846bbdd96d5cfd8fa6269d2231627c377365dd9b5ccf4'
command=['/mnt/c/Python313/python.exe','-I','-B',r'\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-installed-postvalidation-20261012.py','--phase','visible-retained','--execute-reviewed-continuation','--reviewed-script-sha256','6a9546e0ae17b41f2c5846bbdd96d5cfd8fa6269d2231627c377365dd9b5ccf4','--failed-receipt-sha256','d7cc7d772cc3abb17b4c9fe3baa6fe905aba6ae69bc7b56e55f02246f6586ea5','--recovery-receipt-sha256',hashlib.sha256(raw).hexdigest()]
raise SystemExit(subprocess.run(command,check=False).returncode)
PYROOT
```

保持这个exec session至真实托盘退出。用本目录visible-launched.json的新PID选择目标，不动原25268。退出后执行结果在本目录executed-visible-retained.json，原failed文件和原main始终保留不改。两个步骤实际完成后root才按准确SHA消费新主脚本。
