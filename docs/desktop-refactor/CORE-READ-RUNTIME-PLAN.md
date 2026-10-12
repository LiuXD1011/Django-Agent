# 只读运行时集成计划

依据已冻结[第二阶段设计](CORE-READ-WORKER-DESIGN.md)。Goal II.3–5已授权继续实施，不提交。首批16条GET；设置、下载、流、模型和取消终态仍owner，阶段3新增私有只读取消预检和可信coordinator精确CAS。root协调共享接口与最终集成。

- [x] root统一URL规范化、route matcher/body规则；实际带query IPC路径/保存前后epoch RED→GREEN并撤销未公开设备。HTTP及IPC迟到reply另有真实RED→GREEN，不以丢回复代替恢复原会话。
- [x] image_parse_review已冻结storage/database、row-codec、read-database及auth/index、reader。`DatabaseReader`仅path/dataRoot/get/all/read；真正native只读及同步deferred snapshot，AuthService extends AuthReader；定向17/17及相关36/36。
- [x] large_document_review已冻结knowledge/read模块及原路由、SearchIndex state、Workflow stages。共享13知识GET+stages投影；实际native RO6/6、相关73/73、stages6/6。
- [x] owner消息泵提为内部host、正式worker单独构造完整Application/IPC；原相关12/12等价。测试专用fixture复用host，普通config不接受任意worker URL/SQL/函数。
- [x] 私有HTTP facade及IPC实际写事务barrier两case RED→GREEN：释放前旧完整正文/分块，COMMIT后新版本、rollback仍旧。查询认证/hydration同snapshot。外层fork及Orca实际发布中读页另验，不将本集成代替页面通过。
- [x] 私有bootstrap返回owner实际路径、serviceId、parserEnabled/startup active；镜像仅access。有效authority intent先立epoch/pending，IPC失败登录恢复已确认device，保持每请求selectedTenant语义。receipt正常关闭/重启已有定向通过。
- [x] Query仅16条精确GET与窄化binding；16×2真实DTO等价、完整Unicode正文/高整数保留。1执行+32等待、429准入、409 pending认证、503故障/关闭；禁止静默fallback/任意SQL。
- [x] generation/epoch reply fence、abort迟到拒绝、owner死亡封闭Query及health503；取消owner slot持有到终态ACK，header前取消真实通过。15秒Query期限及只读Worker实际退出验证通过；不声称能interrupt同步SQL。
- [x] image_parse_review已冻结IPC与receipt测试：加密journal同session事务落库；真实强杀恢复、refresh代次及已接受后代保护、损坏journal显式失败。定向20/20、相关19/19，原Auth issue到journal的早期窗口仍见报告边界。
- [x] 阶段2冻结270输入/423编译产物；相关domain174/174、runtime33/33、typecheck/build、plain Node编译2/2和桌面12/12通过。同隔离目录正常重启，Orca真实点击重解析/Chunk及228条HTTP采样已执行。
- [x] 阶段3分页改为仅hydrate当前页；当前PID245516来源逐项匹配，Orca实际显示抽屉/点击第2页并核对#50–52、请求200/88ms。真实重解析168次观察及发布期间56次均200，health无超时；保留阶段2慢读取/2超时历史，不从少量样本宣称P95。
- [x] 按文档取消与提交设计实现私有只读授权预检、精确attempt共享槽、实际SQL批次checkpoint及耐久终态；真实HTTP/IPC提交屏障、双重终态故障、无任务后续claim竞争与桌面abort槽保留回归通过。统一350输入/435编译产物冻结，相关265/46、plain Node2、桌面14均无失败、取消或skip，类型/构建退出0。
- [x] 当前来源Orca实际键盘发布取消：请求200/866.1ms、job/root/stage均cancelled、running0；旧正文/11429完整分块行/10000 FTS行SHA不变，250条观察全部200。此前2次裁切click未发API不计通过，见真实取消分析。
- [ ] 另轮1次正文409响应体缺失，原因待核实；Windows最新NSIS正在构建，正式隔离安装及其他页面另验，不能用健康200宣布全部响应性完成。

原文档与154份证据为阶段1冻结历史；阶段2修改来源后重新冻结，不改写既有日志或伪装为同一来源。
