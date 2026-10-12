# 根任务执行交接（final2；取代初版命令）

只针对已安装的取消 Worker 冻结包（桌面 0.6.2 / 核心 0.7.0）。在根任务完整读 [脚本](reviewed-harness-final2.source.txt)、[设计](README-final2.md)、[非执行检查](linux-final2-guard-results.json) / [Windows guards](windows-final2-guard-results.json) 和 [当前只读调查](readonly-readiness-final2.json) 后执行。准备代理没有启动 Marlin 或产品 core；原四模型 PID 25268 仍保持。

脚本 `/tmp/marlin-agent-cancel-installed-launch-20261012.py` 已保留，SHA：

```text
8cf04e7bebb3cb77566507acb6ee6035a34d65c48e8feab5d54d846d06c94a4f
```

无参数或仅 `--phase hidden-smoke` / `--phase visible-retained` 只输出 review_only，既不调查 Windows 也不写数据。

## 第一步：真实隐藏检查

以下是根任务明确启动第一步的精确命令；以 exec session 异步运行，读取进度和最终退出码，不提前重试。

```bash
/mnt/c/Python313/python.exe -I -B \
  '\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-cancel-installed-launch-20261012.py' \
  --phase hidden-smoke \
  --execute-reviewed-launch \
  --reviewed-script-sha256 8cf04e7bebb3cb77566507acb6ee6035a34d65c48e8feab5d54d846d06c94a4f \
  --upgrade-receipt-sha256 6f5d202d3d9ff0771858c41405e9aae4d161cdd7aa6e4b3d28e741221c65e5b8
```

预期后置断言：`executed-hidden-smoke.json` 真实生成且 state verified、该 script SHA/安装 identity 对齐、真实窗口/preload/IPC/实际窗口 DB schema 通过、bundled Node 原生 FTS/vec/真实私有 Owner+Query fork/正常 shutdown 通过、bundled Python 无 Django、各 Job 活动数 0、原 retained 90 文件/12 表/密钥完全相同、PID 25268 原创建身份仍活动。报告 startup_ms 的具体单次测量，不声称 P95、四模型或人工 GUI 通过。异常 receipt 写 failed_manual_review_required，禁止通过删除 WORK 自动重试。

## 第二步：可见保留数据启动

根任务必须先完整审阅实际第一步 receipt。该 receipt 尚未执行生成，不能提前填入一个假 SHA。以下 Bash 调用将其**实际文件字节哈希**作为唯一的动态参数，所有 exe / 数据路径 / 其余 SHA 仍固定；仅在已完成第一步审阅后由根任务执行。

```bash
python3 -I -B - <<'PY'
from pathlib import Path
import hashlib
import json
import subprocess

receipt = Path('/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261012-root-cancel-installed-launch-preparation/executed-hidden-smoke.json')
raw = receipt.read_bytes()
value = json.loads(raw)
assert value['state'] == 'verified' and value['phase'] == 'hidden-smoke'
assert value['reviewed_script_sha256'] == '8cf04e7bebb3cb77566507acb6ee6035a34d65c48e8feab5d54d846d06c94a4f'
command = [
    '/mnt/c/Python313/python.exe', '-I', '-B',
    r'\\wsl.localhost\Ubuntu-20.04\tmp\marlin-agent-cancel-installed-launch-20261012.py',
    '--phase', 'visible-retained', '--execute-reviewed-launch',
    '--reviewed-script-sha256', '8cf04e7bebb3cb77566507acb6ee6035a34d65c48e8feab5d54d846d06c94a4f',
    '--upgrade-receipt-sha256', '6f5d202d3d9ff0771858c41405e9aae4d161cdd7aa6e4b3d28e741221c65e5b8',
    '--hidden-receipt-sha256', hashlib.sha256(raw).hexdigest(),
]
raise SystemExit(subprocess.run(command, check=False).returncode)
PY
```

保持该 exec session 存活；可见阶段每 5 秒输出 owned alive / Job 子进程数，timeout 7200 秒，工具 yield 150 秒不会结束 loop。出现 `visible_owned_process_alive` 后从 `visible-launched.json` 取新 PID / exe / 创建时间，根任务只针对这个新窗口测试；这条事件并不证明窗口已登录或功能通过。原 PID 25268 不得关闭。新窗口点关闭会进托盘；根任务验收完通过新窗口自己的托盘“退出”，harness 才完成 Job 全树退出和安装后校验并生成 `executed-visible-retained.json`。7200 秒超时或宿主结束会只清理本 harness 自己的 Job，并作为异常处理。

准备阶段所有 Node/Python 临时语法和调查 helper 已精确消费删除，源码/hash 归档于 [清理记录](temporary-helpers-final2-consumed.json)。唯一未消费的主启动脚本供根任务使用；两阶段终态均记录后再精确删除这个路径，根任务记录实际清理，不由准备代理提前销毁。将前序已完成安装脚本、旧证据及可变工作区源码作为只读或不依赖的来源。

本轮保留目录的模型数为 0；没有将原四模型导入这个目录。凭据预检查只验证文件/hash/加密 envelope 存在，真实会话过期或刷新行为需要根任务 UI/IPC 证据。隐藏 mount/native 检查与人工 GUI 功能覆盖分别记载，安装器本身的桌面版本与 core 系统版本分别报告。
