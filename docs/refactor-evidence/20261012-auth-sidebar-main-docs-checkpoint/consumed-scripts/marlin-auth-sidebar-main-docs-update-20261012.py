from pathlib import Path
import datetime,hashlib,json,shutil
ROOT=Path('/home/liuxuedeng/Django-Agent');OUT=ROOT/'docs/refactor-evidence/20261012-auth-sidebar-main-docs-checkpoint'
if OUT.exists():raise RuntimeError('New checkpoint already exists')
OUT.mkdir();(OUT/'before').mkdir()
files=[ROOT/'docs/desktop-refactor'/name for name in ['STATUS.md','TEST-REPORT.md','TEST-MATRIX.md']]
records=[]
for p in files:
    target=OUT/'before'/p.name;shutil.copyfile(p,target)
    records.append({'path':str(p.relative_to(ROOT)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'lines':len(p.read_text().splitlines())})
(OUT/'before.json').write_text(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'documents':records,'full_read_completed':True,'only_three_existing_document_paths_authorized':True},ensure_ascii=False,indent=2)+'\n')

def para(s,prefix,new):
    lines=s.splitlines(keepends=True)
    hits=[i for i,line in enumerate(lines) if line.startswith(prefix)]
    if not hits:raise RuntimeError('Missing paragraph anchor '+prefix)
    lines[hits[0]]=new+'\n';return ''.join(lines)

def row(s,ident,content):
    lines=s.splitlines(keepends=True);hits=[i for i,line in enumerate(lines) if line.startswith('| '+ident+' |')]
    if len(hits)!=1:raise RuntimeError('Row anchor not unique '+ident)
    columns=lines[hits[0]].rstrip('\n').split(' | ')
    columns[-1]=content+' |';lines[hits[0]]=' | '.join(columns)+'\n';return ''.join(lines)
B='B浏览器续验已清理两个自有空库，页面恢复原2库/16条目/10027摘录，protected表与managedfiles摘要相同、usage174。完整名称搜索、取消/确认删除、取消置顶和空收藏经标准DOM button.click进入正常前端流程；普通CLI click/keypress虽报送达却没有相应请求，不计真实鼠标通过，也未直接调用Vue业务函数/API。原025未生效、076未稳定断言失败和旧空页面观察保留；其他筛选、编辑、相似名称、重启和非空关联边界及安装版B仍待验。[实际续验及边界](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)、[最终保护核对](../refactor-evidence/20261012-root-kb-list-followup/cleaned-readonly-db.json)。'
A='A隔离浏览器补验已终态：专用127:5184与两个独立persist profile，原D1默认600秒自然expiry→refresh→唯一真实mouse撤销→login；共享D2两页真实mouse logout后另一页无手动reload自动login；另新代次D3撤销而D4仍正常读取，owned已登录页实际关闭后从自有blank打开新document恢复身份。自然过期与独立保持为两个案例，不合并成同一次多设备过期测试；整Orca重启、最终撤销后再重开、该logout时另一active设备保持、late refresh和权限仍未验。4个自建设备已全部退出、0模型/任务；自有core exit0/Vite exit143，12助手/临时QA口令/cache已清理，数据/profile留给Root。注册夹具提交者不确定与工具迟到/断连原样保留，不计计划注册点击通过。[完整边界](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)、[178证据/41断言/81链接冻结db5b33](../refactor-evidence/20261012-auth-browser-isolation-real/freeze.json)。'
S='旧99ba安装版1024收起侧栏的三入口无正确名称仍保留失败。源码Platform.vue仅补type/aria-label/title/aria-current，Linux当前前端361/361与Vite build退出0；独立正常登录页102只读DOM核三名称、提示及知识库当前页正确，未改viewport，不能替代新安装版1024 UIA/实际导航。新[来源6e37](../refactor-evidence/20261012-sidebar-a11y-integrated-source-freeze.json)为457输入/5额外测试，438 core产物保持、85前端产物绑定新Vite，共523；旧5cab与99ba产物身份不重写。[修复与原始收据](SIDEBAR-ACCESSIBLE-NAMES.md)。'
W='Windows新Sidebar stage仅copy已实际exit0/owned tree closed，81263文件/2146851880字节（约2.15GB）、809.733秒，收据[f601](../refactor-evidence/20261012-sidebar-a11y-windows-build/copy-execution.json)与[原生终态](../refactor-evidence/20261012-sidebar-a11y-windows-build/copy-native-terminal.json)一致。这是经验证旧依赖复制到独立stage，不是新门禁、package或安装。正式--refresh --prepare-only已[开始](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-attempt.json)，native session30038/GUI租约释放见[启动回执](../refactor-evidence/20261012-sidebar-a11y-windows-build/prepare-native-session-start.json)；本checkpoint尚未收到prepare终态，新NSIS/升级/1024复验均不预填成功。'
G='Goal保持active，38组整体通过仍仅M-01/M-02。A新增仅上述有界子项，B DOM续验不冒充真实鼠标；1024侧栏源码已修但新版安装复验未完成。hidden UnknownVizError和45ef整体exit1保持；新prepare等待实际终态，崩溃恢复/最新包卸载保留、全页面与外部条件继续，原四模型QA与既有资料保护。'
p=files[0];s=p.read_text();s=para(s,'更新时间：','更新时间：2026-10-12，纳入A隔离认证终态、B DOM续验与自有空库清理、侧栏属性修复及Windows新stage copy/prepare开始（北京时间）。Goal active，无显式token预算；未提交、未推送、未发布。旧846 checkpoint和全部历史失败/旧安装身份继续保留。');s=para(s,'B浏览器HTTP续验',B);s=para(s,'A代理当前零GUI',A+'\n\n'+S+'\n\n'+W);s=para(s,'Goal保持active：仅补当前图片引用',G)
s=s.replace('- 根代理：5cab最新prepare/package/升级/restore及正常clone退出/限定后置完成；D02图片引用、H报告另存已实际，整组仍未完成。当前B搜索/两空库清理继续、A等待Root租约；hidden d40b、45ef整体失败与1024侧栏名称缺陷保留，后续产品修复/最新版复验与最终清理仍待完成。','- 根代理：旧5cab prepare/package/升级/restore及正常clone退出/限定后置保持。A有界补验和B DOM清理已终态；侧栏属性新6e37来源copy完成，Windows prepare正在执行，未计终态/新安装1024复验。hidden d40b/45ef失败、其余页面与最终清理保留。')
s=para(s,'继续D/H/J和A–J余项；','继续D/H/J和A–J余项。A有界认证与B DOM清理已终态，不重放已消费操作；先等待6e37 Windows prepare实际终态，再正式package/新来源安装及1024侧栏真实UIA/导航，随后按授权补崩溃恢复和最新包卸载保数据。B真实鼠标、其他筛选/编辑/重启，A晚refresh/权限/整浏览器重开，以及文档、聊天、外部服务和hidden缺陷继续按[矩阵](TEST-MATRIX.md)，Goal未完成。')
p.write_text(s)
p=files[1];s=p.read_text();s=para(s,'本报告保留构建和失败历史。','本报告保留构建和失败历史。原核心693PASS/0FAIL/2条件skip另plain compiled2/2因核心身份不变继续保留；侧栏属性新6e37来源Linux前端361/361与Vite build退出0。A有界隔离认证、B标准DOM续验及自有空库清理已终态，整组不扩大；Windows新stage copy实际0/81263文件/约2.15GB，prepare已开始但本checkpoint无终态。最近已安装99ba/5cab的升级、restore、normal clone退出及D/H具体子项保持；hidden d40b与45ef整体exit1及新版1024/其他页面仍待验。具体最新边界见本报告末节，38组整组通过仍仅M-01/M-02，Goal active。')
s=s.replace('## 正式安装副本正常退出与报告另存：2026-10-12阶段checkpoint','## 正式安装副本正常退出与报告另存：2026-10-12此前阶段checkpoint')
s+='''\n## A认证终态、B DOM清理与侧栏新来源：2026-10-12当前checkpoint\n\n本次只完整阅读原文档、公有专项和原生收据后维护三份主文档，不操作GUI、产品、数据、模型、端口或Windows生命周期；FINAL及各专项/旧证据不改。此前“A等待租约、B两空库未清、1024源码待修”不覆盖下述新事实。\n\n'''+A+'\n\n'+B+'\n\n'+S+'\n\n'+W+'\n\n'+G+'\n'
p.write_text(s)
p=files[2];s=p.read_text();s=para(s,'B浏览器HTTP续验',B);s=para(s,'A代理当前零GUI',A+'\n\n'+S+'\n\n'+W);s=para(s,'Goal保持active：仅补当前图片引用',G)
s=para(s,'最新[集成来源]',s.splitlines()[12].replace('最新[集成来源]','前一5cab[集成来源]')) if s.splitlines()[12].startswith('最新[集成来源]') else s
s=row(s,'A-01','未完成（原注册/坏密码/安装clone口令登录证据保持；新隔离未认证深链401、共享退出后深链仍401、owned已登录页实际关闭后新document正常Cookie恢复已验证。两个不同partition的同专用账号可正常登录/读取；整Orca退出重启、最终撤销后再重开及最新版IPC认证待验，见[有界A验收](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)）')
s=row(s,'A-02','未完成（原改密/撤销其他/全体自然续期与中文错误证据保持；新隔离原D1默认600秒自然过期→refresh→唯一真实mouse撤销当前→login通过，另新代次D3撤销/D4保持正常读取通过，不能合并成同一次多设备过期。late refresh/额外权限与最终安装版待验，见[A终态](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)）')
s=row(s,'B-01','未完成（自有空库新建/置顶/收藏/配置复制/刷新已有实际；后续完整名称搜索、取消/确认删除、取消置顶及空收藏经标准DOM button.click验证前端路径，普通鼠标未确认送达，不计点击通过。两个自有库已soft-delete、恢复2库/16/10027且保护相同/usage174；其他筛选/编辑/相似名/重启与新版B待验，见[B边界](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)）')
s=row(s,'J-04','未完成（旧正式安装1440/1024及恢复1280/DPI96表格可读；旧99ba1024导航名称缺陷保留。源码仅加可访问属性、Linux361/build0与102只读DOM名称/当前页通过；6e37新来源copy0/prepare开始，新安装1024 UIA及实际导航尚未验。125/150%、其他页面/IME余项待验，见[侧栏修复](SIDEBAR-ACCESSIBLE-NAMES.md)）')
s=row(s,'UI-AUTH-001','未完成（新隔离初始保护深链me401回login、正常专用QA登录、已登录owned页真关闭后从自有blank打开保护页恢复me200/正确用户及D4当前设备，退出后深链401已验证。非整个Orca退出/重启、非最终撤销后再重开；原安装005登录保留，新版完整IPC余项待验，见[A专项](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)）')
s=row(s,'UI-AUTH-002','未完成（历史密码不一致/正常注册与个人空间关联保持；新隔离同一QA通过两个独立persist profile正常登录并可读空个人空间。新注册夹具唯一register200的提交者因跨页Enter焦点重叠不确定，不计计划注册鼠标通过，不把不同用户/数据夹具混成完整单条用例，见[A边界](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)）')
s=row(s,'UI-AUTH-005','未完成（同origin同profile两已登录页，一次真实mouse logout后另一页无手动reload自动login，之后保护深链401；该logout时无其他active独立设备。另新代次D3撤销/D4读取保持单列，不能替代logout独立保持或后到旧refresh竞态，见[A共享页终态](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)）')
s=row(s,'UI-KB-002','未完成（完整名称搜索仅经标准DOM button.click进入正常前端流程、结果唯一copy；取消置顶后收藏为空也有DOM后置。普通CLI鼠标/Enter未确认请求，不计真实点击通过；类型/最近/本空间及其他条件未补齐，见[B续验](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)）')
s=row(s,'UI-KB-003','未完成（新建自有空库置顶/收藏仅1/配置复制/刷新保持已实际；后续取消置顶与空收藏以标准DOM按钮触发验证，不计普通鼠标通过。两自建库已清理，重启/新安装与并列剩余项待验，见[B边界](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)）')
s=row(s,'UI-KB-004','未完成（历史空副本删除取消/确认实际鼠标结果保持；本轮两个自有空库再次以标准DOM按钮取消/确认soft-delete，恢复2/16/10027/usage174及保护摘要相同，不冒充本轮mouse。其他详情/非空关联与安装条件仍按实际专项范围，见[B清理](KNOWLEDGE-LIST-FOLLOWUP-20261012.md)）')
s=row(s,'UI-SET-010','未完成（原改密/撤销其他/全体续期与独立拒绝保持；补充原D1自然600秒过期当前撤销真实mouse与refresh200→DELETE200→login，另D3有效代次当前撤销/D4独立读取保持。两案例不合并；迟到refresh不复活和最终安装仍待验，见[A专项](AUTH-BROWSER-ISOLATION-ACCEPTANCE.md)）')
s=para(s,'本checkpoint补充：正常clone已退出','本checkpoint补充：原normal clone退出/限定保护、D/H安装具体子项保持；A有界认证终态、B标准DOM清理和侧栏源码属性修复已补入对应子项。6e37 copy0/prepare开始，未收到终态；hidden/45ef失败、新版1024/late refresh/权限/余页仍待验。38稳定组不扩充，整组通过仍仅M-01/M-02，Goal active，不动旧H/846冻结与原失败。')
p.write_text(s)
print(json.dumps({'updated_existing_documents':[str(p.relative_to(ROOT)) for p in files],'prepare_status':'started; terminal receipt not supplied','gui_product_model_database_port_actions':0,'before_manifest':str((OUT/'before.json').relative_to(ROOT))},ensure_ascii=False,indent=2))
