import { createServer } from '/home/liuxuedeng/Django-Agent/frontend/node_modules/vite/dist/node/index.js';

const [host, rawPort] = process.argv.slice(2);
const port = Number(rawPort);
if (!(host === '127.0.0.1' && port === 5184 || host === '::1' && port === 5185)) throw new Error('Only fixed authentication QA UI entries are allowed');
const target = 'http://127.0.0.1:8014';
const server = await createServer({
  root: '/home/liuxuedeng/Django-Agent/frontend',
  configFile: '/home/liuxuedeng/Django-Agent/frontend/vite.config.ts',
  configLoader: 'runner',
  envDir: false,
  cacheDir: `/tmp/marlin-auth-vite-cache-20261012-${port}`,
  clearScreen: false,
  server: { host, port, strictPort: true, open: false, proxy: Object.fromEntries(['/api', '/files', '/health'].map(path => [path, { target, changeOrigin: false }])) },
});
for (const path of ['/api', '/files', '/health']) {
  const proxy = server.config.server.proxy[path];
  if (typeof proxy !== 'object' || proxy.target !== target || proxy.changeOrigin !== false) { await server.close(); throw new Error('Isolated proxy not effective'); }
}
console.log(JSON.stringify({ event: 'auth.qa.proxy.resolved', host, port, paths: ['/api', '/files', '/health'], target, changeOrigin: false, cacheDir: server.config.cacheDir, configLoader: 'runner' }));
let closing;
const close = () => closing ??= server.close();
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { void close().catch(() => { process.exitCode = 1; }); });
try { await server.listen(); console.log(`AUTH-QA UI http://${host === '::1' ? '[::1]' : host}:${port}`); }
catch (error) { await close(); throw error; }
