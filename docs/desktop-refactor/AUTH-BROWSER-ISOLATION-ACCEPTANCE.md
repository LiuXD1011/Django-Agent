# A组隔离认证浏览器验收

本轮仅补A-REM01/02/03：受保护深链与重开身份恢复、真实同源双页退出、默认600秒自然过期后的当前设备撤销。迟到refresh屏障、成员角色、下载、订阅和安装版认证不在本批执行范围，Goal仍active。

## 隔离与边界

依[冻结准备计划](AUTH-BROWSER-ISOLATION-PREPARE.md)启动全新空数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation`，Core8014/Vue127.0.0.1:5184，未设置parser/Ragas/模型。开始前目录不存在，8014/5184/5185均无监听，原browser核心2245508仍存活，[12个源码/compiled绑定与前置](../refactor-evidence/20261012-auth-browser-isolation-real/000-preflight.json)保留。

实际发现default profile已有127旧QA页，换端口不能隔离Cookie。因此Root批准采用Orca正式 `tab profile create --scope isolated`，只创建自己的新profile。D1为 `f97e4ab1-3837-49fd-881a-45ebecd5d211`，partition为独立persist namespace；[创建回执](../refactor-evidence/20261012-auth-browser-isolation-real/001-profile-create.json)。不清除default或NextBit配置，不读旧口令/Cookie/token，不复用源管理员。

Root核查后纠正旧“stdin填密码”的描述：浏览器fill没有value-stdin。本批实际使用新随机专用QA口令、0600私有文件、短助手内存加载、仅瞬时child argv并全面redact stdout/stderr；证据不写口令参数或截图明文。这不是stdin，也没有使用用户真实密码/API Key。原生Windows安装窗口保持Root归属，不用native输入。

## 启动绑定及早期工具失败

启动时新核心PID2574115/start17993636/session70671；VitePID2574880/start17994341/session7836。结束正常SIGTERM与真实exec终态见末节。实际resolved三proxy都指向8014、changeOrigin=false、独立cacheDir。直接/代理health均200且service_id同为 `39eda7f1-854f-4c8c-940c-8ad092434140`，[启动绑定](../refactor-evidence/20261012-auth-browser-isolation-real/002-startup.json)。启动日志中5173字样是现dev-server的固定文案，实际UI5184由resolved配置和代理health证明。

初始受保护深链新页创建收到 [Tab creation timed out](../refactor-evidence/20261012-auth-browser-isolation-real/003-owned-page-create.json)；后置 [tab list](../refactor-evidence/20261012-auth-browser-isolation-real/004-tabs-after-timeout.json)没有5184owned页，[profile仍存在](../refactor-evidence/20261012-auth-browser-isolation-real/006-profile-after-timeout.json)。此为Orca创建环境限制，尚不能判断项目页面行为。没有向旧页输入、没有注册或登录提交。

按Root批准的安全诊断，独立profile下[about:blank创建](../refactor-evidence/20261012-auth-browser-isolation-real/007-owned-blank-page-create.json)与[无profile的新空白页创建](../refactor-evidence/20261012-auth-browser-isolation-real/008-owned-blank-without-profile.json)也都超时，[后置列表](../refactor-evidence/20261012-auth-browser-isolation-real/009-final-owned-tab-check.json)仍只有原3页，没有新owned页面。因此不能归因于项目路由、Vite代理或独立profile，也不把CLI ready当页面操作成功。[实际runtime status](../refactor-evidence/20261012-auth-browser-isolation-real/010-runtime-status.json)为ready/connected、Orca1.4.224，仍不消除这些实际失败。

Root先授权的旧QA登录页4fc已不存在，[精确GUID全worktree查询](../refactor-evidence/20261012-auth-browser-isolation-real/015-reassigned-page-show-all.json)仍browser_tab_not_found，没有猜索引或替换Root页面。Root再授权早期QA页9189作为唯一临时备用：[tabshow](../refactor-evidence/20261012-auth-browser-isolation-real/016-backup-page-show.json)和[profile前置](../refactor-evidence/20261012-auth-browser-isolation-real/017-backup-profile-before.json)确认原URL/default。唯一[typed profile set](../refactor-evidence/20261012-auth-browser-isolation-real/018-backup-profile-set-isolated.json)返回Tab profile update timed out；[后置metadata](../refactor-evidence/20261012-auth-browser-isolation-real/019-backup-profile-after.json)仍default，停止该GUI路径，没有导航5184或填认证字段。

三次create工具耗时17.855/16.510/16.239秒，profile-set11.796秒，均为Orca工具等待，**不是项目认证延迟**。截至[012安全状态](../refactor-evidence/20261012-auth-browser-isolation-real/012-after-three-timeouts.json)还没有生成私有口令/注册/登录/模型调用；后续实际落地和账户构造见下节，不把这个早期状态当全批终态。截至019后置时备用页仍default；后续迟到切换与恢复见下节。没有登出原设备或清除原Cookie。

[隔离数据库只读前置](../refactor-evidence/20261012-auth-browser-isolation-real/005-empty-data.json)确认users/device/KB/docs/chunks/model_usage/desktop_jobs均0。两次独立助手准备失误保留：首次证据目录不存在导致保存失败、首次只读计数猜jobs表被SQLite拒绝；都在任何业务操作前，没有产品写入，不计产品失败。

## 迟到页签落地与独占输入

[024后续实际tab list](../refactor-evidence/20261012-auth-browser-isolation-real/024-all-worktree-task-tab-metadata.json)出现新owned页 `e4fa4cd8-169e-4b52-9584-8782c73189a7`，URL5184/login、profilef97；[025精确profile](../refactor-evidence/20261012-auth-browser-isolation-real/025-owned-profile-recovered.json)和[026只读DOM/请求](../refactor-evidence/20261012-auth-browser-isolation-real/026-owned-new-origin-empty.json)核实：输入为空、me401/10.4ms、capabilities200/10.8ms、有Web Locks。此为先前超时操作的迟到实际落地，不覆盖原失败回执，不凭回执超时重放创建/业务操作。

点击创建个人账号、填写新的专用邮箱与两次合成口令后，**没有发送“注册并进入”的计划click/Enter**。[033经过安全助手的表单快照](../refactor-evidence/20261012-auth-browser-isolation-real/033-registration-redacted-form.json)意外显示loading；[034只读ResourceTiming](../refactor-evidence/20261012-auth-browser-isolation-real/034-registration-inflight-public-network.json)确认唯一register200/446.6ms，[035隔离SQLite](../refactor-evidence/20261012-auth-browser-isolation-real/035-unexpected-inflight-new-db.json)确认只创建一名普通个人用户与一台设备。Root报告自己另一source page的Enter回执9c46aafa可能与输入重叠，因此保留工具焦点交叉，不称计划提交点击通过。GUID保障数据查询目标，不能据此假定物理键盘隔离。Root此后暂停全部GUI输入，双方按串行租约操作；现有专用账户只作为后续测试夹具，不重新提交注册。

普通用户 `8d5f267d-b144-40bd-847e-a2a82a107d4e`、个人tenant1；device `fbc66ba1-50c7-4df2-94d4-59bd0224628f`，创建04:29:25.138Z、原access到期04:39:25.138Z。没有自动初始化管理员/注册其他用户。实际[036知识库页](../refactor-evidence/20261012-auth-browser-isolation-real/036-d1-authenticated-snapshot.json)显示专用账户、空库；进入账户设置与管理设备真实click后，038 snapshot有一次runtime_unavailable，039status恢复ready，保留原工具错误且没有重放click。后续[043设备页](../refactor-evidence/20261012-auth-browser-isolation-real/043-d1-device-list-settled.json)正确显示当前设备。[044请求基线](../refactor-evidence/20261012-auth-browser-isolation-real/044-d1-network-baseline.json)devices200/13.9ms、auth/me200/11.9ms，尚无refresh；Settings并行请求另有约2.56秒浏览器观测，不能当P95或仅由后端业务耗时解释。

## 自然600秒条件与第一段租约交接

保持设备页不刷新、不改时钟/过期列。只读[046到期前观察](../refactor-evidence/20261012-auth-browser-isolation-real/046-natural-expiry-readonly-observation.json)、[047到期后观察](../refactor-evidence/20261012-auth-browser-isolation-real/047-natural-access-expired-before-revoke.json)证明原600秒期限未变，实际UTC04:39:59.528Z已过期。[048当前页面](../refactor-evidence/20261012-auth-browser-isolation-real/048-expired-device-dialog-preflight.json)仍标当前设备；未点击撤销。按Root要求此时交还全GUI租约，Root继续其native/source验收，后续串行段再执行确认。

必要共享页[045创建回执](../refactor-evidence/20261012-auth-browser-isolation-real/045-d1-shared-tab-create.json)再次超时，没有重放。[049晚到metadata](../refactor-evidence/20261012-auth-browser-isolation-real/049-shared-page-late-outcome-readonly.json)出现新同profile页c238，但仅 `data:text/html,`，尚未认证/导航，不算第二已登录页。[050无GUI审计](../refactor-evidence/20261012-auth-browser-isolation-real/050-post-lease-new-device-audit.json)在04:42:07仍只有原expired device、revoked=null、users1/KB0/docs0/chunks0/usage0/jobs0，原source PID仍存活；授权备用9189已不在实际list，未由本代理关闭，不沿用旧元信息恢复/操作不存在页。

## A-REM03：自然过期后的当前设备真实撤销

后续串行租约恢复时，[054隔离数据库](../refactor-evidence/20261012-auth-browser-isolation-real/054-resumed-expired-device-preflight.json)发现同一设备在05:09:41.232Z续期、期限变为05:19:41.232Z。没有修改过期列或时钟；该续期的具体触发页面未证实，不把它归到原04:39期限后的计划操作。到本次唯一有效提交前，[070只读前置](../refactor-evidence/20261012-auth-browser-isolation-real/070-visible-confirm-expiry.json)在06:05:58.613Z再次确认该默认600秒期限自然经过，设备仍未撤销。

精确GUID切换并focus后，058真实点击撤销打开确认框。061确认点击虽然返回clicked，062请求记录与063数据库均没有撤销，064确认仍在且按钮未busy。只读[065几何](../refactor-evidence/20261012-auth-browser-isolation-real/065-dom-confirm-control-preflight.json)显示按钮在1289像素视口外、缩为0.60×0.32像素；入口动画帧没有正常推进。这是Orca交付限制，不计产品成功或失败。一次普通浏览器截图采集之后，[068几何](../refactor-evidence/20261012-auth-browser-isolation-real/068-confirm-geometry-after-screenshot.json)恢复为视口内60×32像素、动画已结束，重新读取唯一确认引用，再执行[071真实mouse点击](../refactor-evidence/20261012-auth-browser-isolation-real/071-visible-confirm-real-mouse.json)。067截图工具成功，但助手当时只支持data URL/路径，未保存实际纯base64载荷，因此只保留其metadata，不称已经查看截图。

[076真实请求终态](../refactor-evidence/20261012-auth-browser-isolation-real/076-current-device-final-network.json)记录auth/me401→auth/refresh200→auth/me200→唯一DELETE当前设备200；请求分别23.6/17.1/21.5/12.3ms。DELETE精确指向fbc66ba1…，没有重放实际提交；这里未使用DOM button.click或业务函数/API注入。[075只读数据库](../refactor-evidence/20261012-auth-browser-isolation-real/075-current-device-final-audit.json)对应最后续期06:06:46.325Z、user_revoked06:06:50.954Z，[074页面](../refactor-evidence/20261012-auth-browser-isolation-real/074-inflight-observation-buffer.json)已返回login。页面、请求与持久设备三重终态一致。

本子项证明默认自然过期后自动续期并撤销当前设备的实际mouse链路。第二独立设备当时不存在，同源空页尚未认证，因此不包含其他设备保持、跨页退出或整组A通过。单次请求时间不是P95；工具等待、暂停动画以及整条浏览器链路时间不等于HTTP处理时间。

## D2迟到落地与同源共享页退出

[055实际metadata](../refactor-evidence/20261012-auth-browser-isolation-real/055-resumed-own-pages.json)显示授权备用9189的迟到profile切换已落地到f97，URL为127:5173/login。这改变了先前019的后置事实，保留两时点，未把旧default状态当终态。仅发送一次[086恢复default](../refactor-evidence/20261012-auth-browser-isolation-real/086-authorized-backup-single-default-restore.json)，也返回超时；[104后置](../refactor-evidence/20261012-auth-browser-isolation-real/104-sibling-profile-after-single-set.json)终于确认default、仍127:5173/login。本代理没有登录源账号、清Cookie或提交源业务；GUI交还后不再导航原URL。原URL在016保留，后续是否恢复归Root处理。

[077第二独立profile](../refactor-evidence/20261012-auth-browser-isolation-real/077-d2-isolated-profile-create.json)为a372a0fd…，partition不同于f97。唯一[078新页创建](../refactor-evidence/20261012-auth-browser-isolation-real/078-d2-owned-login-page-create.json)超时，[079列表](../refactor-evidence/20261012-auth-browser-isolation-real/079-d2-create-timeout-metadata.json)与080精确查询发现e87a76af…仍D1。只对这个自有新空登录页发送一次[082改D2](../refactor-evidence/20261012-auth-browser-isolation-real/082-owned-late-page-to-d2-profile.json)：083仍旧profile，084截图报tab closed，088却出现正确D2的9196f757…。随后104显示e87也迟到重建为D2。各时点和工具失败均保留，没有重放创建或把早期错误绑定当独立设备。

[091实际空登录截图](../refactor-evidence/20261012-auth-browser-isolation-real/091-d2-empty-login-frame.png)已打开查看。正常输入自己的专用邮箱/合成QA口令，仅[096一次真实mouse登录](../refactor-evidence/20261012-auth-browser-isolation-real/096-d2-unique-login-mouse.json)。097早期数据库尚无新设备、098快照报runtime_unavailable；没有重放。其后[100实际页面与请求](../refactor-evidence/20261012-auth-browser-isolation-real/100-d2-readonly-after-runtime-recovered.json)已是KB页、login200/418.3ms；[101持久记录](../refactor-evidence/20261012-auth-browser-isolation-real/101-d2-late-login-db-audit.json)新增D2 `f925c705-87f7-4ce9-9d8b-e88513ccbcbe`，原D1仍已撤销。该工具断连不能当认证失败，也不能仅凭clicked回执提前算成功。

[104两个D2页](../refactor-evidence/20261012-auth-browser-isolation-real/104-sibling-profile-after-single-set.json)和[105共享页](../refactor-evidence/20261012-auth-browser-isolation-real/105-d2-late-sibling-readonly.json)确认9196/e87同origin、同a372 profile，e87有同专用用户与me200/11.2ms，Web Locks可用。只有一个有效D2设备。109真实点击账户菜单且110确实展开，再[111一次真实mouse退出](../refactor-evidence/20261012-auth-browser-isolation-real/111-d2-unique-logout-mouse.json)。[112另一页](../refactor-evidence/20261012-auth-browser-isolation-real/112-shared-sibling-after-logout-no-reload.json)在没有手动reload/导航的情况下自动navigate login，侧栏消失；[114主页面](../refactor-evidence/20261012-auth-browser-isolation-real/114-d2-single-logout-final-network.json)唯一logout200/8.2ms；[113 SQLite](../refactor-evidence/20261012-auth-browser-isolation-real/113-shared-logout-db-outcome.json)D2为logout06:36:35.862Z。随后正常[115受保护深链](../refactor-evidence/20261012-auth-browser-isolation-real/115-loggedout-sibling-protected-deeplink.json)仍由[116 me401](../refactor-evidence/20261012-auth-browser-isolation-real/116-loggedout-deeplink-auth-rejected.json)回login，没有身份复活。

这个退出案例当时没有另一有效独立设备，独立保持由下面不同代次单独补验，不能称本次logout已同步验证其他设备保持或迟到refresh竞态。

## 新代次设备撤销、独立保持与新document恢复

Root明确允许正常GUI重新登录构造新代次，避免重放原撤销。f97上仅121一次mouse登录建立D3 `c62fff52-25f7-4527-b5f8-2ac3aea6f305`；a372上仅127一次mouse登录建立D4 `089e7176-f7bd-48cf-a8ed-a3eb6e16ca98`。[128精确记录](../refactor-evidence/20261012-auth-browser-isolation-real/128-two-partitions-new-devices.json)显示两个不同有效设备，旧D1/D2撤销保持，没有新用户或模型调用。

[137真实设备页](../refactor-evidence/20261012-auth-browser-isolation-real/137-d3-two-device-page-fresh.json)明确D3是当前设备，另有D4。正常点击当前设备打开确认，[139截图](../refactor-evidence/20261012-auth-browser-isolation-real/139-d3-confirm-real-frame.png)已实际查看，当前设备也将退出的提示正确；140重新取唯一撤销引用，[142一次真实mouse确认](../refactor-evidence/20261012-auth-browser-isolation-real/142-d3-unique-visible-confirm-mouse.json)。[143持久终态](../refactor-evidence/20261012-auth-browser-isolation-real/143-current-d3-single-revoke-durable.json)D3 user_revoked06:49:46.626Z、D4完整公开设备字段未改变；[144页面/请求](../refactor-evidence/20261012-auth-browser-isolation-real/144-d3-revoke-final-network.json)精确DELETE D3 200/9.7ms并回login。141前置时D3 access仍有效，**本例不是第二次自然过期案例**；自然600秒链路由原D1证明。

A-REM01重开部分只关闭自己的已登录D4页。唯一[130 close](../refactor-evidence/20261012-auth-browser-isolation-real/130-d4-own-authenticated-tab-close.json)工具超时、131仍存在；没有重发，[145后置列表](../refactor-evidence/20261012-auth-browser-isolation-real/145-d4-close-late-final-state.json)确认9196真正消失。同profile自建c238原先一直是空document，103一次profile切换亦有超时，129后置才确认已变a372。关闭后，经正常[146 goto](../refactor-evidence/20261012-auth-browser-isolation-real/146-d4-fresh-owned-blank-protected-open.json)在这个自有空页打开受保护设备深链，不填写口令或注入缓存。147只读断连原样保留，[149真实截图](../refactor-evidence/20261012-auth-browser-isolation-real/149-d4-restored-owned-page-frame.png)已打开查看，[150新document](../refactor-evidence/20261012-auth-browser-isolation-real/150-d4-restored-page-final-public-read.json)正确专用用户、当前D4、D3已撤销，capabilities200/8.9ms、me200/9ms、devices200/10.3ms；[148数据库](../refactor-evidence/20261012-auth-browser-isolation-real/148-d4-preserved-device-after-new-document.json)无新增设备、D4未撤销。它同时证明新document正常恢复和不同Cookie partition的D4仍可读。

这不是整个Orca进程关闭/重启或整个浏览器所有页签关闭测试；同D2的另一个登录页仍在。也没有在本轮清理后重新打开已撤销D4页。仅已实际完成的owned页关闭、空页打开新document、恢复身份和独立设备读取计为通过。

Root唯一产品修改Platform.vue加入侧栏可访问属性。该独立UI的[102只读DOM](../refactor-evidence/20261012-auth-browser-isolation-real/102-d2-platform-sidebar-accessibility.json)已核对话/知识库type=button、aria-label/title与知识库aria-current=page，账户label/title为账户与设置。这是当前源码DOM子项，不代替1024安装版或触控/窄屏真实验收；160的Vite输出记录了实际HMR，认证核心和本批绑定的12个文件仍另核SHA。

## 最终范围与清理

| 用例 | 本轮真实覆盖与限制 |
| --- | --- |
| A-REM01 | 初始未认证深链→login401、logout后保护深链仍401，以及owned已登录页真正关闭后新document Cookie恢复通过；完整浏览器退出/重启、最终撤销后再次重开未执行。 |
| A-REM02 | 同origin两个已登录页、一次真实mouse logout、另一页无手动reload自动login、后续深链拒绝通过；该logout案例没有另一有效独立设备，迟到refresh竞态未执行。 |
| A-REM03 | 原D1默认600秒自然expiry→refresh→唯一真实mouse撤销→login通过；另一个新代次D3撤销/D4保持正常读取通过。两者是独立案例，不合并成同一自然过期且多设备案例。 |
| A-REM04/05 | 迟到refresh屏障、角色/越权/持续订阅、两个不同用户的空间隔离仍未执行。 |

完成断言后，正常[155一次GUI logout](../refactor-evidence/20261012-auth-browser-isolation-real/155-last-owned-device-cleanup-logout-once.json)清理最后D4；[157实际logout200/7.5ms](../refactor-evidence/20261012-auth-browser-isolation-real/157-cleanup-logout-final-network.json)回login，[156终态SQLite](../refactor-evidence/20261012-auth-browser-isolation-real/156-own-devices-all-revoked-cleanup.json)四个自建设备全部revoked。users1、tenant1；KB/docs/chunks/model_usage/jobs始终0。没有修改原管理员、模型配置或厂商密钥，也未使用模型/解析/评测服务。

已显式交还全部GUI租约，不再发浏览器/native/键鼠命令。[158精确停止](../refactor-evidence/20261012-auth-browser-isolation-real/158-owned-services-normal-stop.json)通过PID/startTicks/argv/cwd与pidfd，仅SIGTERM自己的Vite/core，kernel退出分别35.086/98.429ms；原source2245508身份前后相同、公开auth/counts前后相同。第一次助手错误为Python虽3.12但缺pidfd导出，[159原失败](../refactor-evidence/20261012-auth-browser-isolation-real/159-stop-helper-api-preflight-failure.json)发生在任何signal前，核真实Linux x86_64系统header后用native libc syscall修正。[160原exec终态](../refactor-evidence/20261012-auth-browser-isolation-real/160-owned-exec-final-receipts.json)为Core exit0、Vite exit143；不称两个exec均自然exit0，也未升级为SIGKILL。QA数据目录保留，停止后仍有WAL/SHM文件名，不称sidecar全移除；自有页/profile保留在login，由Root后续决定处理，备用页已default但原URL未恢复。

[161临时清理凭证](../refactor-evidence/20261012-auth-browser-isolation-real/161-temporary-cleanup.json)核定12个助手已归档SHA并删除、0600合成口令文件未归档且已删除、独立Vite cache已删除；自有口令仅对本批文档/证据/归档助手扫描，没有明文匹配，不扩大为全系统秘密审计。[162最终只读检查](../refactor-evidence/20261012-auth-browser-isolation-real/162-final-readonly-check.json)绑定原始结果、链接/差异和12个既有源码SHA，独立freeze.json位于同证据目录。本批没有修改产品源码、运行产品测试/build或重写旧失败证据。Goal仍active，全项目与正式安装验收不由这些认证子项代替。
