# A组剩余认证真实浏览器验收准备计划

> **For agentic workers:** 执行前由Root确认隔离环境与GUI时段，按 executing-plans 逐项记录。当前仅只读准备，所有执行步骤未开始；不新增代理、产品入口或兼容层。

**Goal:** 只补跨页退出、自然过期后的当前验收设备撤销，以及可真实触发的权限边界；不重复已完成的首次登录/密码弹窗/撤销其他设备/退出全部设备。

**Architecture:** 使用全新空数据目录的现有 TypeScript CoreOwner/HTTP入口，Vue独立 `127.0.0.1` origin与独立Vite缓存。共享存储页签用同一origin；另一个设备必须有独立Cookie jar或不同安全loopback主机，单独换端口不能替代。

**Tech Stack:** 当前compiled Node TypeScript核心、现有Vue入口、已安装Vite7.3.5、Orca真实业务输入；无Django、真实模型、厂商服务或数据迁移。

## 当前仅完成读取

完整阅读两份 PENDING-A-J、auth service/reader、HTTP适配、dev-server、Vue API/auth transport/store/router/device页及Vite配置/相关安装类型；现有普通登录、设备与自然过期证据只取公开结果，没有打开私有验收口令文件、Cookie/token/header或实时数据库。

最新可用[剩余清单](../refactor-evidence/20261012-main-docs-web-search-mcp-checkpoint/PENDING-A-J.md)与[前一详细清单](../refactor-evidence/20261012-main-docs-post-prepare-checkpoint/PENDING-A-J.md)的A缺口一致。其他B/H/I/J描述是其当时checkpoint，不作为本轮当前状态。[自然过期既有证据](../refactor-evidence/20261010-root-sensitive-natural-expiry-real.json)已经验证改密、撤销其他设备、退出全部三项各一次：me401→refresh200→me200→业务200；没有改时钟/过期列或付费模型。

[旧设备证据](../refactor-evidence/20261010-root-orca-device-management-real.json)的旧自然过期401缺口由上述后续记录修复验证，不能重新当现有产品失败；其跨页签迟到refresh和正式安装验证明确false。已有源码/集成单测只说明回归覆盖，不能替代此轮浏览器实测。

本任务没有启动/停止项目进程、创建页面、GUI、API或业务写入。Root原browser QA PID2245508及localhost源空间保持不动，Windows升级由Root独占。

## 隔离必须成立的条件

1. [HTTP](../../packages/core/src/adapters/http.ts)设置的 `marlin_access`/`marlin_refresh` 为host-only、Path `/api/v1/`、HttpOnly、SameSite Strict；`csrftoken` 为host-only、Path `/`。Cookie不按端口区分。**禁止 `localhost:5184`，也不能把 `127.0.0.1:5185` 当独立设备。** 不读Cookie值或清除任何已有host的Cookie。
2. [EndpointResolver](../../frontend/src/api/endpoint.mjs)与[Axios](../../frontend/src/api/client.ts)固定当前页面同源，没有切换API地址的配置项。[现有Vite配置](../../frontend/vite.config.ts)的 `/api`、`/files`、`/health` 都固定8000，单改UI端口仍会误连源核心，不能这样启动。
3. 使用 `http://127.0.0.1:5184`，代理三路径全部改为同一个独立 `127.0.0.1:8014`。显式strictPort；占用即停止，不顺延或改动原5173/8000服务。候选三个端口经本轮只读 `ss` 未发现监听，但执行时必须再核，不能保证之后空闲。
4. 新数据路径固定 `/home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation`。首次执行前要求不存在；若已存在则保留并由Root另定唯一目录，禁止复用/清空源目录或导出副本。
5. Vite独立cacheDir，configLoader `runner`，避免共用原 `frontend/node_modules/.vite` 和默认config bundle临时目录。已安装类型/实现支持该接口；真正启动、Windows侧连通、有效代理与页面就绪仍未测试。[静态壳插件](../../frontend/src/pwa/static-shell-plugin.mjs)仅apply build，此处不执行build。
6. 新origin第一次验收前只检查是否存在既有认证缓存/会话的布尔事实。若该host/独立profile已被其他测试占用，停止，不清缓存或借用登录。只创建新的专有测试账户，不读取或复用源管理员、原QA口令。

## 准确启动命令（尚未运行）

[dev-server](../../packages/core/src/tools/dev-server.ts)严格接受 `--data-root`、`--port`、`--ui-origin` 等已列选项，没有host/TTL选项。HTTP默认listen127.0.0.1。先由Root记录新进程PID/startTicks/会话与端口的归属，不对原服务发信号。

```bash
cd /home/liuxuedeng/Django-Agent
test ! -e /home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation || exit 1
node packages/core/dist/tools/dev-server.js \
  --data-root /home/liuxuedeng/.local/share/marlin-refactor/20261012-auth-browser-isolation \
  --port 8014 \
  --ui-origin http://127.0.0.1:5184 \
  --ui-origin 'http://[::1]:5185'
```

第二行是首次启动的独立前置检查，失败不能继续第三行。compiled入口和Worker入口存在不等于启动成功；真正执行时要求原日志、health/capabilities、不同service_id和空业务数据证据。该最小命令不启用parser/Ragas：下载/图片路由会因 `app.documents` 不存在而503，不能把它当权限拒绝；有文件权限测试另按下方条件配置。

未来将以下独立辅助程序写到 `/tmp/marlin-auth-vite-20261012.mjs`，不用修改产品Vite文件，也不用安装依赖：

```js
import { createServer } from '/home/liuxuedeng/Django-Agent/frontend/node_modules/vite/dist/node/index.js';

const [host, rawPort] = process.argv.slice(2);
const port = Number(rawPort);
if (!(host === '127.0.0.1' && port === 5184 || host === '::1' && port === 5185)) {
  throw new Error('仅允许固定的隔离认证UI入口');
}
const target = 'http://127.0.0.1:8014';
const server = await createServer({
  root: '/home/liuxuedeng/Django-Agent/frontend',
  configFile: '/home/liuxuedeng/Django-Agent/frontend/vite.config.ts',
  configLoader: 'runner',
  envDir: false,
  cacheDir: `/tmp/marlin-auth-vite-cache-20261012-${port}`,
  clearScreen: false,
  server: {
    host, port, strictPort: true, open: false,
    proxy: Object.fromEntries(['/api', '/files', '/health'].map(path => [path, {
      target, changeOrigin: false,
    }])),
  },
});
for (const path of ['/api', '/files', '/health']) {
  const proxy = server.config.server.proxy[path];
  if (typeof proxy !== 'object' || proxy.target !== target || proxy.changeOrigin !== false) {
    await server.close();
    throw new Error('隔离API代理未生效');
  }
}
let closing;
const close = () => closing ??= server.close();
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => {
  void close().catch(() => { process.exitCode = 1; });
});
try {
  await server.listen();
  console.log(`AUTH-QA UI http://${host === '::1' ? '[::1]' : host}:${port}`);
} catch (error) {
  await close();
  throw error;
}
```

在另一个受控终端执行：

```bash
node /tmp/marlin-auth-vite-20261012.mjs 127.0.0.1 5184
```

三proxy覆盖优先级已核[已安装Vite实现](../../frontend/node_modules/vite/dist/node/chunks/config.js) `mergeConfig(loadResult.config, inlineConfig)`与递归覆盖逻辑；[真实类型](../../frontend/node_modules/vite/dist/node/index.d.ts)有createServer/InlineConfig/configLoader/envDir/cacheDir/host/strictPort/proxy。不声称已经执行这段辅助程序或类型构建。

需要第二个独立设备时，再启动同一程序的第二个受控实例：

```bash
node /tmp/marlin-auth-vite-20261012.mjs ::1 5185
```

`http://[::1]:5185`的Cookie主机和localStorage都与127及源localhost不同，同一个core8014负责认证。它仅listenIPv6loopback；Windows Orca→WSL IPv6是否可达未验证。若不通，不改成同127的另端口或localhost；改用Root另行审查的独立浏览器profile/上下文，或者明确留“跨设备未执行”。同origin两页用于共享存储测试，绝不能称两台设备。

## 最小执行批次与真实断言

账户构造仅为新空实例的前置：通过现有“创建个人账号”正常建立两个不同的专有普通账户，不把注册过程重复记为首次登录/初始化的新通过项。私有密码只临时生成/保存，按已审私有stdin输入流程操作；若该助手不能证明不落CLI参数、通用args日志或截图，则不输入，不复用源口令。页面证据仅保留公开user/tenant/device ID、到期UTC、状态和必要安全摘要。

- [ ] **A-REM-01：未授权深链与重开恢复。** 新origin尚未登录时，经真实地址导航到受保护知识库路径，核转login且没有私有数据/自动初始化。正常专有登录之后关闭仅owned页签再打开该origin深链，核服务端me及正确user/tenant恢复；不把source旧缓存当认证凭据。最终撤销后重开应持续login。
- [ ] **A-REM-02：真实同origin跨页退出。** 两个新owned页签均在127:5184、同user/tenant/device，先核另一页确已登录。A页账户菜单点击退出一次，B页不手动reload即因storage logout事件回login；随后正常深链/reload仍不能恢复。服务端只撤D1，不撤独立D2。没有独立D2时最后一项未执行，不从两页共享Cookie推断设备隔离。
- [ ] **A-REM-03：自然过期撤销当前设备。** 使用设备页明确标“当前”的专有D1。先记录其真实access_expires_at（仅公开身份/新隔离DB安全字段），保持页面无业务轮询至真实UTC超过该时间+1秒；默认TTL600000ms，无CLI缩短选项，不改时钟/数据库过期列。再实际确认“撤销当前”一次：me401→refresh200→me200→精确DELETE D1 200，返回login、另共享页也失效、D1 server revoked，pending0。若需要重登只建立新专有device，不重新提交原已完成删除。独立D2应可正常操作并保持自己的device ID。
- [ ] **A-REM-04：跨页迟到refresh不复活。** 普通跨页退出不能代替该竞态。先证明A页真实refresh已发出/响应在途，然后B页真实点logout，再观察迟到响应与两页最终状态、D1已撤销且后续保护请求拒绝。现有Web Locks会串行Cookie操作，工具4–7秒的交替点击很可能看不到真实重叠；没有实际pending/迟到证据就留未执行。可靠确定性版本需要Root另审只作用于新UI代理的响应屏障（不改核心、过期值、认证字段或JSON结果，私有Cookie只内存转发，状态日志不输出headers/body）。当前没有创建该屏障，不通过JS调用refresh/修改store制造GUI通过。
- [ ] **A-REM-05：不同个人用户的实际GUI隔离。** A、B在独立Cookie jar/不同host的origin，公开ID不同且各自个人空间。A经UI建自己的小空库；B清单不显示它，B真实地址打开其详情应拒绝/无A正文；切回A自己的资料仍在。只把这算个人空间读取/页面隔离，不能扩展为成员权限、越权写入、私有文件下载或持续订阅全部通过。

[auth-transport](../../frontend/src/api/auth-transport.mjs)的Web Locks按resolver.origin命名，storage事件只同origin传播；没有Web Locks的fallback只支持同页顺序。执行时只读确认navigator.locks能力，缺少时不假称跨页Cookie竞态保证。[设备页](../../frontend/src/views/settings/DeviceSessions.vue)当前撤销在authenticatedSessionOperation下先续期，mutation skipAuthRefresh，成功才invalidate/回login；[AuthService](../../packages/core/src/auth/index.ts)refresh保持同device family、重放只撤该family。

## 权限与条件项，不伪造GUI入口

[AuthReader](../../packages/core/src/auth/reader.ts)每次重新校验user/session/tenant/membership；个人空间只接受personal_owner_id对应的active成员，系统管理员也不因此获得别人的个人空间。legacy空间的owner/admin/editor/viewer确有不同read/write/admin权限，但新注册用户只形成自己的personal owner。

[legacy路由](../../packages/core/src/adapters/legacy-routes.ts)真实提供 `POST /api/v1/tenants`、`/tenants/:id/members`、`DELETE /tenants/:id/members/:user`、`POST /auth/switch-tenant`；[tenant service](../../packages/core/src/legacy/tenants.ts)明确个人空间不可共享。当前Vue router/Platform/API没有相应空间/成员管理或切换UI。没有这些实际前置，不能在浏览器localStorage注入tenant、伪造header/角色或直接SQL插成员，然后称正常GUI通过；成员CRUD/撤权后的持续订阅需另行授权隔离API/集成场景，证据明确归因而非补UI。

私有源下载实际路径为 `GET /api/v1/knowledge/:id/download`，图像为 `/knowledge/:id/images/:image`；[document routes](../../packages/core/src/adapters/document-routes.ts)依赖已配置parser。当前auth最小启动未配置parser，503不是权限断言。该子项需要Root确定现有有效Python/worker参数、新模型未配置的微型source，以及owner实际正常下载作为正向对照；不能凭错误/不存在ID的404证明越权拒绝。

聊天私有历史事件为 `GET /api/v1/sessions/:id/events`，持续流为 `GET /api/v1/sessions/continue-stream/:id`；[chat routes](../../packages/core/src/adapters/chat-routes.ts)要求实际会话/消息/请求ID。空会话的events拒绝不等于真实SSE订阅撤权测试，unknown request的404也不足。越权写入若产品没有可正常触发的按钮，应另用真实认证HTTP/核心集成验证，并注明非GUI；不得evaluate调用fetch/业务handler伪造点击。

30天idle/90天absolute自然过期、旧Bearer替换、换service_id/网络中断、所有role和最终安装IPC仍是独立条件，当前10分钟D1撤销不覆盖。需要已有真实请求的订阅/下载/越权写、late屏障和IPv6/profile条件由Root安排；没有条件就保留限制，不重复付费生成资料。

## 证据、保护与结束

- [ ] Root确认后才启动新owned进程与owned页签；逐条固定新的page GUID，禁止使用原page0/page6或安装窗口。正常cookies/CSRF保留，不读取或输出秘密值。
- [ ] 原始GUI步骤、公开DOM/ResourceTiming、精确user/tenant/device/到期、每次提交数、隔离DB后置只读摘要按独立目录保存；工具等待与产品HTTP/任务耗时分开，n=1不作P95。
- [ ] 最后只撤销/关闭自己的新账户设备和owned页签/新服务；记录自然退出及无新付费调用。原localhost账号、PID2245508、数据/Key/导出及Root Windows进程不动。新的隔离目录归Root决定保留或清理，不能因为失败就删除证据/业务库。

当前仅新增本文和[只读准备绑定](../refactor-evidence/20261012-auth-browser-isolation-preparation/freeze.json)。全部执行项仍未开始，Goal仍active；文档只做链接/差异/源码SHA核对，不重跑产品全套或build。
