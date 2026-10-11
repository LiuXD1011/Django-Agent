# 最终交付报告

状态：实施中，Goal active；已有真实桌面运行、基线安装和四模型业务证据，尚未达到最终交付标准。未提交、未推送、未发布。

## 当前可核对结果

- 主业务使用 `packages/core` 的 TypeScript核心、SQLite、FTS5/sqlite-vec；Electron通过正式preload/IPC访问核心，随包Python只用于解析与Ragas辅助工作。已运行的Windows正式smoke无需系统Node/Python或Vite，不监听旧桌面HTTP端口。
- 旧数据完整副本31表、2445文件已导入，重复导入通过；44表、2446文件备份和独立恢复核对记录、文件hash与FK。没有对原库重放旧Django迁移。[迁移与恢复](MIGRATION.md)。
- 用户重新配置的对话、Embedding、ReRank、视觉四角色均已有实际厂商调用；自编五份资料完成入库及摘要。相似实体与图片问题经事实、计算及机器引用核对，并实际打开图片OCR的准确来源。[厂商与来源记录](../refactor-evidence/20261010-windows-model-vendor-regression.json)。
- 基线NSIS已在专用中文空格路径安装并通过正式smoke；验收专用账户完成密码修改，真实管理员密码、模型Key及其他用户设备未修改。升级、卸载保留数据和最终包完整窗口生命周期尚未执行。

## 基线安装器与版本

当前已验的是第二个基线包，不包含后续全部修复，不能作为最终包交付：

```text
C:\Users\lxd\AppData\Local\Temp\Marlin TS Installers 20261010\Marlin-Setup-0.6.2-x64.exe
SHA256: 1d431f64f9d9de54a2e3c169fc12d774ef2a439786ecec852e5ba84052b52ee7
401698923 bytes
```

Electron44.7.0，携带Node22.23.2、Python3.13.16；桌面包版本0.6.2、核心0.7.0。原生Windows x64是本次必须交付的平台，macOS/Linux桌面包尚未验收。[实际构建](../evidence/20261010-windows-nsis-build.json)、[安装](../refactor-evidence/20261010-windows-nsis-installation.json)、[安装版smoke](../refactor-evidence/20261010-windows-installed-smoke.json)。

默认用户数据位于 `%LOCALAPPDATA%\Marlin`，与安装位置分离。验收使用专用目录；默认真实数据没有被安装或卸载测试覆盖。

## 运行与检查

开发前构建核心与界面，然后分别启动同一核心的HTTP适配和Vue：

```bash
npm run build
npm run start:local -- --data-root /path/to/isolated-marlin-data
npm run dev
npm run typecheck
npm run test:core
npm run test:frontend
npm run test:desktop
npm run test:startup
```

源码桌面需要原生Windows构建器准备完整资源，不能直接运行缺payload的desktop目录。运行和辅助进程参数见[README](../../README.md)、[桌面说明](../desktop.md)及[Windows构建](../windows-installer.md)。启动入口与正式构建门槛仍在独立复核，最终报告会记录最终源码、完整资源与安装器hash。

## 尚需完成的必做验收

- Orca所有核心页面真实操作、正式Electron复核与其余标准问答；工具送达但没有业务变化的操作没有计通过。
- 至少五条审核通过、有证据的题目的真实厂商Ragas评测，以及实际报告下载、样本和指标核对。
- 最终NSIS、升级/卸载保留数据、托盘真正退出和异常重开、窗口尺寸与缩放检查。
- 最终代码清理、秘密材料与临时认证文件清理、最后的源码/资源一致性检查。

Windows锁屏和Orca页面输入/连接异常目前阻止部分真实操作，已请求解锁，继续独立修复与构建。Neo4j旧配置的真实只读连接失败，原图数量未知；不能写成空图或已迁移。可选外部Langfuse、搜索等真实服务尚未全部验收，受控协议测试与厂商结果分开记录。

具体进度与修复结果见[STATUS](STATUS.md)和[TEST-REPORT](TEST-REPORT.md)，完整完成门槛见[SPEC](SPEC.md)和[TEST-MATRIX](TEST-MATRIX.md)。上述缺失的核心条件没有用“未验证”替代或计为通过。
