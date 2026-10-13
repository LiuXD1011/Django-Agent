# Runtime 回归夹具初始化清理修订

Root 接受独立审查 [R-01](../20261013-asar-bootstrap-runtime-review/REPORT.md)：原夹具在 setup 和 ASAR 创建之后才注册 `t.after`，初始化异常可能遗留专用临时目录。

完整读取新增测试后，将清理注册移动到任何 setup 文件写入之前，预先声明 `child/runtime`；Runtime 尚未创建时使用可选检查，并通过 `finally` 保证停止失败也继续清理 ASAR cache 与自有目录。只改 `desktop/packaged-bootstrap.test.cjs`，生产 Runtime 一行路径修复和授权/IPC/NAPI/退出语义均未改。

修改前测试 SHA `184ca9c855368a7543b1f4cd0ba31dd72a03475410b9592332c59f8abb3dc813`，字节保存在 [before](before/packaged-bootstrap.test.cjs)；修改后 SHA `46cdd96a9b4b625d0478a209b627204dc7bb8845981645695130c945cf939272`。生产 Runtime SHA仍为 `fb2b569bbb94c4237608b515d97f78914cc996322116405c1d009244414b9112`。

Root 实际执行 `node --test packaged-bootstrap.test.cjs`，工具 chunk526d45、actual exit0，2/2 PASS、0FAIL/SKIP，TAP149.282871ms；当前 Node v22.23.2 由 a3ec91/actual0 核实。后续差异检查7ae759/actual0。这两项仍是实际 ASAR/外部 Node 加明确 Windows/NAPI/Core 替身，不是 Windows GUI 通过；没有因此重复前31项或完整Core/Frontend。

已交新 SHA 给独立 reviewer，待其仅核两项与初始化失败清理边界；原19输入/旧2项独立结果/原 R-01 发现保持。旧869安装包正式启动FAIL、新来源物理资源复制与packed Electron-Core门禁仍分别由对应负责人继续，Goal未完成。
