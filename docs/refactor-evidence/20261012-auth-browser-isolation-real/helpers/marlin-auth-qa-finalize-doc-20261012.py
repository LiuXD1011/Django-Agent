from pathlib import Path
p=Path('/home/liuxuedeng/Django-Agent/docs/desktop-refactor/AUTH-BROWSER-ISOLATION-ACCEPTANCE.md')
s=p.read_text().replace('## 当前执行状态','## 启动绑定及早期工具失败').replace('新核心PID2574115/start17993636/session70671；VitePID2574880/start17994341/session7836。','启动时新核心PID2574115/start17993636/session70671；VitePID2574880/start17994341/session7836。结束正常SIGTERM与真实exec终态见末节。').replace('授权备用页后置默认profile元信息未变，没有登出原设备或清除原Cookie。','截至019后置时备用页仍default；后续迟到切换与恢复见下节。没有登出原设备或清除原Cookie。')
start=s.index('## 尚在补验的第二设备与跨页状态')
s=s[:start]+'''## D2迟到落地与同源共享页退出

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

临时私有QA口令、助手与独立Vite cache的清理，以及最终链接/差异/源码绑定与独立freeze见后置凭证。本批没有修改产品源码、运行产品测试/build或重写旧失败证据。Goal仍active，全项目与正式安装验收不由这些认证子项代替。
'''
p.write_text(s)
