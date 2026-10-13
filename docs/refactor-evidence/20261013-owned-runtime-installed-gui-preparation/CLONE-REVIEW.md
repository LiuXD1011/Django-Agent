# 独立复制阶段待审核

本文件只交付可审准备；尚未复制或启动产品。固定新DATA/CONTROL目前不存在。

数据库不使用旧观测的全表hash/count作为静态门禁：在未来复制的只读事务第一次schema查询建立当前快照，再backup，并比较源快照与目标所有实际表的hash/count。schema必须与已读实际schema完全相等，version1/FK0/queued-running0；专用QA UUID的SHA256匹配active且nondeleted账号恰好1，密码/邮件/UUID不输出，不读取private-auth或解密。

25材料的path/size/SHA保持静态门禁（1个credentials.key、24个media，.settings原缺失）；任何正常新媒体变动也会拒绝，需要新观测和Root复审，不能把变化伪装为旧green。copy前后源/目标逐文件SHA比较，数据库物理路径/文档图片关联严格验证，不改auth/models/路径。

helper仅Linux SQLite只读backup与文件复制，不启动native/Core/GUI/模型/服务/安装器。每次输入固定SHA，目标存在、已attempt/receipt均拒绝自动重试；创建后的失败目录与原失败回执保留。

绑定与源归档：[clone-reviewed-binding.json](clone-reviewed-binding.json)、[clone-helper.source.txt](clone-helper.source.txt)、[clone-review-validation.json](clone-review-validation.json)。原869/旧468源码及原upgrade工具overall1均在绑定分别保留；当前源码变化不进入旧artifact binding。

未来精确命令（仍须Root读源码后的具体授权）：

```sh
/home/liuxuedeng/anaconda3/bin/python -B /tmp/marlin-installed-gui-clone-20261013.py --execute-reviewed-clone --binding-sha 1fee18414a69424b5f91c26d140fe2565ac76aa491221da66463904129768e61
```
