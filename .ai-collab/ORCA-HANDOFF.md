## 本地预览服务保留（2026-10-01T06:19:30.811772+00:00）

用户反馈 http://127.0.0.1:18764/login 点击自动初始化失败。根因证据：此端口原属/tmp/marlin-codex-ui-vite.mjs临时验收服务；Linux curl连接拒绝、ss无监听，Windows连接亦失败，浏览器保留旧页面。无业务代码缺陷证据，未派发代码修改。
已通过Orca新建专用可见终端 term_ed3dbd77-b8c2-462e-97b8-f9bb78b66842（Marlin 本地预览 :18764（保留运行）），运行/tmp/marlin-codex-desktop-venv/bin/python scripts/start_desktop.py --data-dir /home/liuxuedeng/.local/share/marlin-orca-preview/marlin --port 18764 --no-browser。
Linux和Windows health均HTTP200，当前独立用户数据目录初始化前users计数0；未代用户创建账号、未读取密钥或密码。该终端/服务/数据目录是给用户继续操作的持久预览，**不要作为临时验收资源自动清理或删除数据**。停止方法：在该专用终端Ctrl+C；原ZCode/Codex终端不动。此服务不等于会话退出后Codex仍后台监督。
下文“测试服务均已停止”为上一轮结束状态，本条保留的预览服务是后续新建，优先于下文旧状态。

# 当前交接状态（2026-10-01T04:40:57.763510+00:00）

当前批准批次8项全部由Codex验收passed：cleanup-r2、P02A-r2、D1用户数据目录、D2桌面运行入口、D3首次登录、R2A属主围栏、R2B持续恢复、SEC1前端依赖安全。它是桌面源码运行交付基础，不等于签名安装包或整体商业化完成。

## 当前资源/职责
- worktree: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin
- Windows实际目录: \\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\orca\workspaces\Django-Agent\marlin
- branch: prep-desktop-commercial-release；HEAD afa7e0138f9fbad80e80aa4ead6f1d80af0145da；所有改动未提交。
- 唯一CLI: /home/liuxuedeng/.local/bin/orca-ide；Run run_c0d51a93432f
- Codex term_60dee0e3-814d-4700-949f-10d6f21542ef
- 桌面/SEC1 ZCode term_0740ef7f-610c-4f37-966f-45a74fb8890c
- 恢复 ZCode term_f8c9c557-bdc5-4749-bddb-0f9f0820bc28
- 两个ZCode最新Dispatch均正式succeeded并worker-retain，所有Delivery已处理ack，无活动Dispatch、无reclaimable资源。保留所有手动终端，不关闭。
- Codex协调/只读审查与隔离测试；ZCode业务修改；Orca编排，不用Codex内置子代理。Windows优先。无提交/推送/合并/发布。

## 最新验收
D2 task_7c898801f949 / ctx_bff176173eda：Windows完整30/36.196s exit0，6独立probe exit0；执行者Linux30 exit0。上轮Windows连接清理/路径/端口失败已消除。
SEC1 task_a8da76839ae3 / ctx_35705b9eeaf5：Codex audit各级漏洞0 exit0，Windows npm ci和unit45/45 exit0，Node20.19 unit45/45 exit0；执行者Linuxunit45、build、E2E38 exit0。最终锁文件哈希一致。D2历史报告两处措辞已依授权修正。
R2B task_a225951b0d82 / ctx_7202552dc69a：Codex独立Linux142/16.419s、Windows142/22.979s全部exit0，4probe/0.226s exit0；测试文件哈希一致。报告lifecycle25为计数笔误，实际24，合并142。
最后真实桌面HTTP/Chromium登录/workbench/退出清理exit0：/tmp/marlin-codex-final-integration.log。graphify update . exit0，AST-only；git diff --check exit0。
详细证据见ORCA-COORDINATOR-REVIEW.md、各RESULT和ORCA-FILE-MANIFEST.md。

## 后续未完成及下一负责人
当前批次没有返工。下一阶段由Codex先检查交付缺口并制定小批次，再派发已核实Ready的ZCode；已完成Task不能retry。可复用现有Run，新Task/Dispatch，先核实终端无其他工作。用户已允许总体范围内自主技术决策及自动创建ZCode；不需要重问已批准方向。
1. Windows干净环境完整运行依赖安装与体积/许可证梳理；当前native测试环境只有测试所需依赖，不是完整requirements验证。
2. 真正可安装/可分发的桌面产物和升级/卸载数据保留策略；现有仅源码运行入口，不宣称有安装器、签名或自动更新。
3. 商业许可证和数据集使用边界核验（尤其PyMuPDF与评测数据集），未取得商业授权，不猜测已清除法律限制。
4. 在明确部署形态/负载目标后再决定服务端扩展与HA；当前SQLite单机恢复不等于多机HA/highQPS/exactly-once。
付费、凭据使用、生产环境变更、不可逆删除、对外发布仍需用户明确授权；禁止提交推送合并发布。

## 恢复方法与保留资源
本轮会话结束后不会继续后台监督。用户发“继续读取协作文件”可让Codex恢复；新任务前读取当前orchestration指南和Run/Task/Dispatch及终端状态，不重复旧任务。配额旧失败已成功恢复，不再按旧重置时间阻塞。
Linux测试runner /tmp/marlin-codex-review-runner.py；Windows临时venv C:\Users\lxd\AppData\Local\Temp\marlin-native-review-20260930。测试使用隔离临时DB/数据目录，无真实模型凭据。最终Codex smoke服务已停止，临时测试数据已由harness清理；原浏览器tab保留但其测试URL服务已停止。
六个项目Langfuse容器仍停止，数据卷保留；无自动恢复重容器。历史敏感脚本已批准删除；不得读取/打印/验证git历史凭据。
