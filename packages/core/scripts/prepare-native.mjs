import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';

const require = createRequire(import.meta.url);
const SQLite = require('better-sqlite3');
const packageRoot = dirname(require.resolve('better-sqlite3/package.json'));
const binding = join(packageRoot, 'build', 'Release', 'better_sqlite3.node');

function probe() {
  new SQLite(':memory:', existsSync(binding) ? { nativeBinding: binding } : {}).close();
}

try {
  probe();
} catch (error) {
  if (process.platform !== 'linux' || !String(error.message).includes('GLIBC_')) throw error;
  // Old Linux build hosts need a local N-API binary. Windows packages retain their published binary.
  console.log('SQLite prebuild requires a newer GLIBC; compiling against this Linux build host.');
  const build = spawnSync(process.execPath, [require.resolve('node-gyp/bin/node-gyp.js'), 'rebuild', '--release', '--force_build=1'], {
    cwd: packageRoot,
    stdio: 'inherit',
    env: { ...process.env, ...(!process.env.CXX && existsSync('/usr/bin/g++-10') ? { CXX: '/usr/bin/g++-10' } : {}) },
  });
  if (build.status !== 0) throw new Error('SQLite native build failed; a C++20 compiler and Python are required on this build host.');
  probe();
}
