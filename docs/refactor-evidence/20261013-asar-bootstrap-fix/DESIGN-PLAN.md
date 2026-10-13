# WIN-ASAR-BOOTSTRAP-001：安装版核心启动修复设计

2026-10-13。Goal 的普通修复、细化设计后继续实施及隔离安装已获第二节第3–4项授权；不重复请求确认，不执行提交或发布。

## 已确认的问题与范围

869a安装器的真实正常启动显示 loading 后提示本地核心代码1退出，登录及业务未就绪。原工具98461最终0是所属树收尾，与产品启动FAIL分别记录。独立 Windows probe48236实际0，bundledNode的原HANDLE身份与 addon.currentIdentity相等；同一实际安装路径 `resources/app.asar/runtime-bootstrap.cjs` 的 Node resolve及require都报MODULE_NOT_FOUND。原Runtime在canonical ASAR文件名下的fork参数捕获也是该路径；此探针未启动Core或读取DB/Key。

前置准备和Runtime tests通过普通物理app目录加载runtime；已安装ASAR内bootstrap是packed条目，外部独立Node22不能从该虚拟目录加载。此差异解释当前加载边界，进一步单变量真实fork/physical bootstrap→ready/stop对照由Windows worker记录，原失败及installed字节保持。

## 方案

采用已有payload的 `owned-runtime/runtime-bootstrap.cjs` 物理资源：Windows Runtime由其root解析启动脚本，保留bundled Node22、Core编译入口、原generation/IPC/NAPI8 Job授权、现有数据目录与退出语义。构建阶段复制原脚本字节，清单及安装资源审核同时验证存在与SHA，避免只在普通staging通过。现有12项ASAR资产暂保留，新增物理副本与归档中的原bootstrap必须逐字一致；不借本修复移除功能或调整版本/依赖。

另两种方案是为脚本增加asarUnpack规则，或者用Electron RunAsNode执行Core。前者引入另一套安装资源定位和审核配置；后者改变Core Node/原生依赖ABI及环境边界。已有owned-runtime目录可直接容纳这项资源，变动更集中。

## 验证与实施顺序

1. 在改生产前补回归，复现Runtime来自真实ASAR目录、其外部Node加载bootstrap失败。使用实际锁定ASAR与真实Node文件加载链；Native API/Core若必须使用替身，要明确标注，不将其计Windows实际通过。
2. Runtime路径与构建资源清单分别由明确文件负责人修改，接口固定为上述物理路径；先完整阅读文件和已安装API/types，再最小改动。缺失/变更bootstrap的门禁必须拒绝，实际打包字节须匹配source。
3. 执行相关desktop、startup、Windows构建脚本检查和实际目标平台检查。补实际Electron从真实ASAR加载Runtime、bundled Node启动真实Core并ready/stop的打包门禁，合成独立数据、0模型调用；普通staging probe继续保留其边界。
4. 当前完整来源冻结后生成新Windows包，隔离安装并重新正常打开独立业务副本。Root通过真实窗口正常登录/页面/单实例/托盘验收；单元、instrumented对照或helper0不能替代安装版。

## 分工与保护

Root协调共享路径、最终集成、原FAIL与新结果边界、正式Orca/native UI。Runtime负责人只改desktop/runtime.cjs及其desktop回归文件；packaging负责人只改构建/资源门禁与对应测试。Windows worker在独占diagnosis目录做受控动态取证，不改生产。未经Root协调不得跨文件归属。

不修改原installer/安装目录字节来冒充新包，不重置密码、不清Key/设备、不读取真实.env；测试使用自有副本及无活动工作。所有控制/清理继续使用自有原HANDLE/Job，不按名称/端口泛化终止。已完成的current324 Core728与前端422来源没有被本问题推翻，不能外推为Windows启动通过；相关源未变时不重复全套检查。
