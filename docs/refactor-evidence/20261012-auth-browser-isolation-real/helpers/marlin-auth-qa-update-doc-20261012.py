from pathlib import Path
p=Path('/home/liuxuedeng/Django-Agent/docs/desktop-refactor/AUTH-BROWSER-ISOLATION-ACCEPTANCE.md')
s=p.read_text()
s=s.replace('## 自然600秒条件已达到，撤销尚未提交','## 自然600秒条件与第一段租约交接')
start=s.index('| 用例 | 当前真实范围 |')
s=s[:start]+'''## A-REM03：自然过期后的当前设备真实撤销

后续串行租约恢复时，[054隔离数据库](../refactor-evidence/20261012-auth-browser-isolation-real/054-resumed-expired-device-preflight.json)发现同一设备在05:09:41.232Z续期、期限变为05:19:41.232Z。没有修改过期列或时钟；该续期的具体触发页面未证实，不把它归到原04:39期限后的计划操作。到本次唯一有效提交前，[070只读前置](../refactor-evidence/20261012-auth-browser-isolation-real/070-visible-confirm-expiry.json)在06:05:58.613Z再次确认该默认600秒期限自然经过，设备仍未撤销。

精确GUID切换并focus后，058真实点击撤销打开确认框。061确认点击虽然返回clicked，062请求记录与063数据库均没有撤销，064确认仍在且按钮未busy。只读[065几何](../refactor-evidence/20261012-auth-browser-isolation-real/065-dom-confirm-control-preflight.json)显示按钮在1289像素视口外、缩为0.60×0.32像素；入口动画帧没有正常推进。这是Orca交付限制，不计产品成功或失败。一次普通浏览器截图采集之后，[068几何](../refactor-evidence/20261012-auth-browser-isolation-real/068-confirm-geometry-after-screenshot.json)恢复为视口内60×32像素、动画已结束，重新读取唯一确认引用，再执行[071真实mouse点击](../refactor-evidence/20261012-auth-browser-isolation-real/071-visible-confirm-real-mouse.json)。067截图工具成功，但助手当时只支持data URL/路径，未保存实际纯base64载荷，因此只保留其metadata，不称已经查看截图。

[076真实请求终态](../refactor-evidence/20261012-auth-browser-isolation-real/076-current-device-final-network.json)记录auth/me401→auth/refresh200→auth/me200→唯一DELETE当前设备200；请求分别23.6/17.1/21.5/12.3ms。DELETE精确指向fbc66ba1…，没有重放实际提交；这里未使用DOM button.click或业务函数/API注入。[075只读数据库](../refactor-evidence/20261012-auth-browser-isolation-real/075-current-device-final-audit.json)对应最后续期06:06:46.325Z、user_revoked06:06:50.954Z，[074页面](../refactor-evidence/20261012-auth-browser-isolation-real/074-inflight-observation-buffer.json)已返回login。页面、请求与持久设备三重终态一致。

本子项证明默认自然过期后自动续期并撤销当前设备的实际mouse链路。第二独立设备当时不存在，同源空页尚未认证，因此不包含其他设备保持、跨页退出或整组A通过。单次请求时间不是P95；工具等待、暂停动画以及整条浏览器链路时间不等于HTTP处理时间。

## 尚在补验的第二设备与跨页状态

[055实际metadata](../refactor-evidence/20261012-auth-browser-isolation-real/055-resumed-own-pages.json)另显示授权备用9189的迟到profile切换已落地到f97，URL为127:5173/login。这改变了先前019的后置事实，保留两时点，未把旧default状态当终态；该页没有被本代理登录源账号、清Cookie或提交源业务，后续按Root授权恢复单页profile/原URL。

[077第二独立profile](../refactor-evidence/20261012-auth-browser-isolation-real/077-d2-isolated-profile-create.json)为a372a0fd…，具有不同persist partition。唯一[078新页创建](../refactor-evidence/20261012-auth-browser-isolation-real/078-d2-owned-login-page-create.json)再次超时；[079后置列表](../refactor-evidence/20261012-auth-browser-isolation-real/079-d2-create-timeout-metadata.json)出现e87a76af…但属于D1/f97，[080精确profile](../refactor-evidence/20261012-auth-browser-isolation-real/080-late-new-page-profile.json)亦如此，不能当独立D2。后续仅对该新owned登录页采用typed profile set，一次操作与后置核查单列，不重放创建。

| 用例 | 当前真实范围 |
| --- | --- |
| A-REM01 | 初始未认证深链→login401已观察；已登录重开恢复与撤销后重开待执行。 |
| A-REM02 | 同源第二页只有未导航的迟到空页；跨页退出待执行。 |
| A-REM03 | 当前设备自然600秒过期→自动refresh→唯一真实mouse撤销→login已通过；独立D2保持未执行。 |
| A-REM04/05 | 本批没有迟到refresh屏障、额外权限夹具或真实请求。 |

本文件为执行中记录，临时助手清理与独立证据freeze尚待追加；不得据核心启动、profile创建或单个子项宣称A组通过。
'''
p.write_text(s)
