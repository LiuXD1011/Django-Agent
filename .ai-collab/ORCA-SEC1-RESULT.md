# ORCA-SEC1-RESULT — MARLIN-SEC1 前端依赖审计修复（round1）

- Task: `task_a8da76839ae3` / Dispatch: `ctx_35705b9eeaf5`
- 日期: 2026-10-01
- 执行环境: Linux (WSL2)，Node v22.23.2 / npm 10.9.8；npm 缓存 `npm_config_cache=/tmp/marlin-sec1-npm-cache`
- 范围遵守: 仅改 `frontend/package.json`、`frontend/package-lock.json`、新增本报告；另按当前 Task 明确授权对 `.ai-collab/ORCA-D2-RESULT.md` 做了两处历史措辞原子修正（见文末）。未触碰业务源码/根 package/Python 依赖/桌面入口/文档。

## 改动前 audit 基线（本机实测，非推断）

`npm audit --json` → **exit 1**（/tmp/marlin-sec1-audit-before.json）：3 high + 1 low，共 4 项，与 Codex 证据 /tmp/marlin-codex-npm-audit.json 一致：

| 包 | 锁定版本 | 严重度 | 修复版本（advisory） |
| --- | --- | --- | --- |
| axios（直接依赖） | 1.18.1 | high（12 条 advisory） | ≥1.20.0 |
| nanoid（传递，经 postcss `^3.3.12`） | 3.3.15 | high | ≥3.3.18 |
| postcss（传递，经 vite `^8.5.6` / @vue/compiler-sfc `^8.5.15`） | 8.5.15 | high | ≥8.5.23 |
| esbuild（直接 + vite 传递 `^0.27.0`） | 0.27.7 | low | ≥0.28.1（audit 建议 0.28.2；漏洞区间 0.27.3–0.28.0，**无 0.27.x 补丁版**） |

## 实际改动与解析版本

1. `frontend/package.json`：
   - `axios` `^1.16.0` → `^1.20.0`（同主版本，advisory 修复线）；
   - devDependencies `esbuild` `0.27.7` → `0.28.2`；
   - 新增 `"overrides": { "esbuild": "0.28.2" }` —— 最小 override，理由：vite 7.3.5 声明 `esbuild: ^0.27.0`，而补丁只存在于 0.28.1+（0.27.x 无修复版），不 override 则 vite 会嵌套自留 0.27.7、low 漏洞残留（中期实测复现：仅剩 esbuild low，/tmp/marlin-sec1-audit-mid.json）。未跨 Vite 主版本、未动 Vue/Vite 生态其余部分、未用 `audit fix --force`。
2. `frontend/package-lock.json`：经 `npm install`（axios/esbuild 变更）+ `npm update nanoid postcss`（范围内补丁提升，**未使用任何 nanoid/postcss override**）重新生成；实测解析：axios **1.20.0**、nanoid **3.3.19**、postcss **8.5.28**、esbuild **0.28.2**（全树单副本，vite 嵌套副本消失）。lock diff 逐项核对仅触及这四个包及其平台二进制/integrity，无无关包变更。

## 改动后 audit 与验收（全部真实退出码，日志无管道）

| 命令 | exit | 结果 |
| --- | --- | --- |
| `npm audit --json`（改前） | **1** | 3 high + 1 low（基线复现） |
| `npm install` / `npm update nanoid postcss` | 0 / 0 | lock 重建 |
| `npm audit --json`（中期） | 1 | 0 high，仅剩 esbuild low（vite 嵌套 0.27.7）→ 触发 override 决策 |
| `npm audit --json`（改后） | **0** | **0 漏洞**（info/low/moderate/high/critical 全 0；/tmp/marlin-sec1-audit-after.json）——本次可如实称 audit 全绿 |
| `npm ci`（从最终 lock 全新安装） | **0** | 安装成功，"found 0 vulnerabilities" |
| `npm run test:unit` | **0** | **45/45 pass**，0 fail 0 skip（node --test；esbuild 0.28.2 被单测直接 import，兼容实测） |
| `npm run build` | **0** | vite 7.3.5 + esbuild 0.28.2 构建成功（17.53s；chunk 体积提示为既有状态，非本次引入） |
| `npm run test:e2e` | **0** | **38/38 passed**（1.3m，desktop + mobile-390 两个 chromium 项目；axios 运行时 1.18.1→1.20.0 的登录/知识库选择/聊天/轨迹等既有 mock 协议回归通过） |

## 兼容性与边界

- Node engines 未改，`test:unit`（`cd src && node --test`）与 `test:e2e`（playwright）脚本原样保留；axios 1.20.0 / esbuild 0.28.2 / nanoid 3.3.19 / postcss 8.5.28 均在 Node 20.19+/22 可用范围（本机 Node 22 实测通过；Node 20 未由本 worker 实测）。
- override `esbuild 0.28.2` 的真实适用边界：仅覆盖 esbuild 工具链副本（构建期/测试期使用，不进运行时产物）；兼容性由 unit/build/e2e 三组真实运行背书，若未来 vite 升级到声明支持 0.28+ 的版本，可移除 override。
- `npm run build` 按验收要求真实执行，重建了 `frontend/dist/`（git 忽略的构建产物，属验收命令的预期副作用；未手改其中内容）。

## 未运行 / 未做

- **Windows npm unit 未由本 worker 运行**。以下为 **Codex 独立验证**结果（本 worker 未实跑，据协调者消息转述）：当前 package/lock 快照 `npm audit --json` exit 0、各级漏洞 0（/tmp/marlin-codex-sec1-audit.json）；Windows native 隔离 frontend 目录 `npm ci` exit 0、unit 45/45 exit 0、无 skip，源 package/lock 哈希测试前后相同（/tmp/marlin-codex-sec1-windows.log）。
- 未用真实模型/账号/用户 DB/外部业务服务；e2e 为既有 mock 协议套件。
- 未提交/推送/合并；未删除 node_modules 以外数据；未改 git 历史。

## 附带授权修正（同一 Task 内，原子）

- `.ai-collab/ORCA-D2-RESULT.md` 两处历史措辞：Round1 内联勘误后的"现 diff 仅剩 start:desktop 一行新增"标注为当时历史状态（当前 diff 含已批准 CLEANUP 删除）；"dsh-recon 令牌核验"改为"历史敏感材料清理事项，本轮未操作"，未读取/打印/验证任何历史凭据。不涉及 D2 测试重跑。
