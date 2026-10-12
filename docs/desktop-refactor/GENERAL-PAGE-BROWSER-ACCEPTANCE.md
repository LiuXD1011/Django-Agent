# 不依赖模型的页面补充真实验收

2026-10-12，Goal仍active。根代理明确授权在五题Ragas暂缓时补A/B/D/F/I的安全GUI子项，当前只使用专用tenant2/QA账号、Orca独立page6 `22e0e212-30aa-4945-8a3d-7176cdfffdff`，全GUI由本代理持有。根代理并行负责CJK query修复和Windows构建，不编辑本次证据。原[评测复验](EVALUATION-REAL-RECHECK.md)已独立冻结，不再写入原H证据。

所有业务通过固定page GUID的Orca typed点击/输入；DOM/ResourceTiming与native readonly SQLite仅作后置断言，不用JS/fetch/直接API修改状态。禁止模型调用、Key/模型配置变化、改动原两库及gold文档/图片、三个已存评估集或原Wiki内容；不修改任何源码/测试/构建/主报告。

先建立自己的空库用于B-01/B-02：开启Wiki能力但不上传或生成，保存、编辑名称描述、搜索/范围/刷新与空库统计，随后只复制自己的空库并验证取消/确认删除。空库创建和手动Wiki校验均不启动解析/模型；若实际出现后台任务则暂停核查。因原Wiki全部在受保护gold库，F-01空标题验证安排到自建库：新建页面弹窗、将保存按钮滚到可见、空标题真实点击保存，核提示/弹窗保持/0页面写请求及0新行，再取消。不以视口外点击或disabled按钮回执冒充提交校验通过。

本段实际结果如下；未执行A/D/I并列行为，也不计完整B/F或安装版通过。根代理随后授权的唯一五题Ragas在[独立中文检索复验](EVALUATION-CHINESE-QUERY-BROWSER.md)中记录，本段无模型操作不与该45次调用混算。

## 已执行的安全子项

[02只读基线](../refactor-evidence/20261012-general-page-browser/002-general-before-protected-readonly.json)绑定原两个知识库、gold两文档/13块、13条原Wiki记录、三个评估集、四模型及vault，仅输出hash与非秘密字段，usage117/0活动任务。实际点击主导航知识库后[04列表](../refactor-evidence/20261012-general-page-browser/004-knowledge-list-current-snapshot.json)为两库、16条目、10027可检索摘录、0处理中。

在真实新建弹窗中输入自己的名称/描述并勾选Wiki，保留默认合法分块配置，[11运行前DOM](../refactor-evidence/20261012-general-page-browser/011-create-own-before-dom.json)确认创建按钮在视口内。[12单次真实创建](../refactor-evidence/20261012-general-page-browser/012-create-own-empty-library-click.json)保存空库`99218d30-8205-45bf-96ff-0a5d6c1c0a3f`（Orca 页面补验 空库 20261012），[13后置只读](../refactor-evidence/20261012-general-page-browser/013-after-own-empty-create-readonly.json)为0文档/块/Wiki/任务、0新增usage，全部保护摘要与基线一致。[14列表](../refactor-evidence/20261012-general-page-browser/014-after-own-empty-create-snapshot.json)变3库，自己的card正确RAG+Wiki、条目/摘录0。点击自己的卡片后[16详情](../refactor-evidence/20261012-general-page-browser/016-own-library-detail-snapshot.json)各统计0、图谱禁用，未上传或生成。

[17真实Wiki标签click](../refactor-evidence/20261012-general-page-browser/017-own-empty-wiki-tab-click.json)与[18内嵌空态](../refactor-evidence/20261012-general-page-browser/018-own-wiki-embedded-snapshot.json)为还没有Wiki页面，没有新建/编辑按钮，保留既有embedded只读行为。独立编辑入口通过[19正常浏览器深链goto](../refactor-evidence/20261012-general-page-browser/019-owned-wiki-normal-deeplink.json)访问真实router的ownKB/wiki?tab=pages，不是API或JS修改路由；此项不宣称产品存在一个未实际点击的独立入口链接。

[21真实新建页面click](../refactor-evidence/20261012-general-page-browser/021-owned-wiki-new-page-click.json)后标题与正文保持空。[24提交前DOM](../refactor-evidence/20261012-general-page-browser/024-empty-wiki-before-validation-dom.json)明确标题空、Save enabled、y463.8/高度32/viewport614，[25实际可见Save click](../refactor-evidence/20261012-general-page-browser/025-empty-wiki-actual-visible-save-click.json)后[26DOM](../refactor-evidence/20261012-general-page-browser/026-empty-wiki-after-validation-dom.json)弹窗仍开、标题空，Wiki ResourceTiming只有此前两条GET，集合完全相同，未发新页面写请求。[27只读](../refactor-evidence/20261012-general-page-browser/027-empty-wiki-validation-readonly.json)自有Wiki仍0、全部保护摘要与usage117相同；[28真实取消](../refactor-evidence/20261012-general-page-browser/028-empty-wiki-editor-cancel.json)关闭编辑。短warning未及时捕获，不称已核对“请输入标题”渲染文字；只将空标题阻止写入的真实子项记通过，不把整F组或安装链路填通过。

独立Wiki处于pages模式时breadcrumb仍写“文档 / Wiki / 图谱”，这是实际展示与当前视图不一致的轻微文案发现；没有擅自修改冻结产品。

## B空库编辑、搜索、复制与删除

[38真实保存设置](../refactor-evidence/20261012-general-page-browser/038-owned-library-edited-visible-save-click.json)与[39只读](../refactor-evidence/20261012-general-page-browser/039-owned-library-edited-after-readonly.json)确认名称改为“Orca 页面补验 空库 20261012 已编辑”、描述同步保存，分块和能力配置保持。保存后设置框仍开，符合现有`saveSettings()`不关闭的行为；实际取消关闭，再[43正常reload](../refactor-evidence/20261012-general-page-browser/043-owned-library-real-reload.json)后[44详情与最近访问](../refactor-evidence/20261012-general-page-browser/044-owned-library-after-reload-snapshot.json)均显示新名称、0统计。没有暗中解析或模型调用。

返回列表后实际填前缀并focus/Enter，[50搜索DOM](../refactor-evidence/20261012-general-page-browser/050-own-name-search-result-dom.json)恰好自己的1卡片、1库/0条目/摘录/处理中。[55真实刷新](../refactor-evidence/20261012-general-page-browser/055-own-filtered-actual-refresh-click.json)和[56刷新快照](../refactor-evidence/20261012-general-page-browser/056-own-filtered-actual-refresh-snapshot.json)保留关键词与单卡片。正常access过期的401经既有refresh后重试200，不输入密码或绕过认证。52/53是误加`browser`命令前缀的CLI参数错误，官方guide后纠正，原记录保留，不作为产品失败或通过。

[57复制自己的库](../refactor-evidence/20261012-general-page-browser/057-own-library-copy-click.json)得到空副本`f07d6f44-0abc-4b97-8481-9b102e106f7f`，[59只读](../refactor-evidence/20261012-general-page-browser/059-own-library-copied-readonly.json)明确描述、Wiki开关及所有分块配置一致，0文档/块/Wiki。最新副本最初排前；随后[60置顶原自建库](../refactor-evidence/20261012-general-page-browser/060-owned-original-pin-click.json)，[61顺序](../refactor-evidence/20261012-general-page-browser/061-own-pinned-sorted-snapshot.json)变原库在前，[63收藏](../refactor-evidence/20261012-general-page-browser/063-own-pinned-filter-click.json)后[64仅自己的置顶1库](../refactor-evidence/20261012-general-page-browser/064-own-pinned-filter-snapshot.json)，[65本空间](../refactor-evidence/20261012-general-page-browser/065-own-space-filter-click.json)后[66自己的两库](../refactor-evidence/20261012-general-page-browser/066-own-space-filter-snapshot.json)。最后取消置顶。这里验证实际默认更新顺序和置顶排序；页面没有显式排序选择器，不宣称执行了不存在的控件或“最近”范围/类型过滤。

副本删除先确认弹窗目标为准确copy名，再[71取消](../refactor-evidence/20261012-general-page-browser/071-own-copy-delete-cancel.json)，[72只读](../refactor-evidence/20261012-general-page-browser/072-own-copy-delete-cancel-readonly.json)副本仍活跃。重新打开相同目标并[76确认](../refactor-evidence/20261012-general-page-browser/076-own-copy-delete-confirm.json)，[77只读](../refactor-evidence/20261012-general-page-browser/077-own-copy-deleted-readonly.json)仅副本软删、0关联，[78清单](../refactor-evidence/20261012-general-page-browser/078-own-copy-deleted-snapshot.json)回自己的1库。

## F手动Wiki与清理

自己的原空库重新打开独立pages页，实际新建填标题与Markdown后滚到Save；[86可见DOM](../refactor-evidence/20261012-general-page-browser/086-own-manual-wiki-save-visible-dom.json)为enabled、y404.6/高度32/viewport518。[87单次保存](../refactor-evidence/20261012-general-page-browser/087-own-manual-wiki-save-once.json)后[88阅读页](../refactor-evidence/20261012-general-page-browser/088-own-manual-wiki-saved-snapshot.json)出现表格、两个目录和缺失双链，没有虚构来源。实际编辑为“已保存并编辑”及v2标记，[95保存](../refactor-evidence/20261012-general-page-browser/095-own-wiki-edited-save-once.json)后[97真实DOM](../refactor-evidence/20261012-general-page-browser/097-own-wiki-edited-network-render-dom.json)正文/表格同步；[103真实SQLite](../refactor-evidence/20261012-general-page-browser/103-own-wiki-version2-actual-readonly.json)为唯一自建页面`427ec585-aa8b-42e1-bfc1-85addf83a1d8`、version2、source_refs/chunk_refs均空。

[99按正文v2标记搜索](../refactor-evidence/20261012-general-page-browser/099-own-wiki-content-search-fill.json)后[100结果](../refactor-evidence/20261012-general-page-browser/100-own-wiki-search-result-snapshot.json)仍1目标；实际刷新后[102](../refactor-evidence/20261012-general-page-browser/102-own-wiki-refresh-selection-dom.json)搜索/正文/选择保持。[104目录click](../refactor-evidence/20261012-general-page-browser/104-own-wiki-outline-click.json)后[105焦点](../refactor-evidence/20261012-general-page-browser/105-own-wiki-outline-focus-dom.json)准确落在“缺失链接”heading。点击缺失双链保持原页面且不新增page请求；[107](../refactor-evidence/20261012-general-page-browser/107-own-wiki-missing-link-result-dom.json)短提示未捕获，不能作为提示文本的追加验证。

Wiki删除目标准确，[110取消](../refactor-evidence/20261012-general-page-browser/110-own-wiki-delete-cancel.json)后[111](../refactor-evidence/20261012-general-page-browser/111-own-wiki-delete-cancel-readonly.json)version2仍活跃；重开并[115确认](../refactor-evidence/20261012-general-page-browser/115-own-wiki-delete-confirm.json)，[116](../refactor-evidence/20261012-general-page-browser/116-own-wiki-deleted-readonly.json)准确该页version3/软删，[117](../refactor-evidence/20261012-general-page-browser/117-own-wiki-deleted-empty-snapshot.json)恢复空态。最后从清单确认删除自己的原KB，[123最终只读](../refactor-evidence/20261012-general-page-browser/123-general-final-protected-readonly.json)两自建KB均软删、关联0（包括此前已软删的自建Wiki物理行），[124清单](../refactor-evidence/20261012-general-page-browser/124-general-final-library-list-snapshot.json)恢复原两库、16条目/10027摘录/0处理中。最近访问此时仍有自己已删除库的旧按钮，记录为待独立核查的缓存展示边界，没有点击原库或改源码。

## 计量、诊断与范围

[62 ResourceTiming](../refactor-evidence/20261012-general-page-browser/062-own-pinned-readonly.json)本次刷新331ms、复制27.4ms、置顶23.3ms，各是一次应用请求；Orca动作回执约4–10秒包含工具/桌面桥耗时，不等同业务延迟。Wiki初次保存发生一次正常access refresh，之后编辑请求335.8ms、手动刷新351.8ms，见97/102。这些是n=1和Windows后台构建负载下观察，不报告P95或总体性能通过。

保护脚本初版`original_wiki`误选tenant全部Wiki，89新增自己的手动页使其变14；原记录不覆盖。[92范围纠正](../refactor-evidence/20261012-general-page-browser/092-original-wiki-guard-scope-corrected-readonly.json)仅原两KB、13行/hash精确等于02，最终123再次相等。另首次Wiki只读脚本误用不存在的`links`列，未写库，核实际schema后去掉该字段，103才是有效version断言；失败脚本归档，不能算产品缺陷。基线usage117与最终162差45全部属于独立已授权Ragas，本段B/F从29开始usage162一直不变。最终四模型、key、原两KB、gold两文档/13块、原13Wiki、三个评测集hash都等于02，0活动任务。

本段补通过UI-WIKI-001空标题阻止写入/embedded只读子项以及上述空库B操作，未覆盖重启保存配置（浏览器reload已测、core重启本段未做）、非空文档索引级联删除、KB配置变化重解析标记、真实图谱大节点/滚轮、来源文档变化/lint、原生新安装或A/D/I，不标整个Goal完成。
