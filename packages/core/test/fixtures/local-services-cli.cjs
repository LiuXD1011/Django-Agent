// Controlled CLI protocol fixture. This never invokes Docker or creates containers.
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const args = process.argv.slice(2);
const record = process.env.MARLIN_LOCAL_FIXTURE_RECORD;
fs.appendFileSync(record, JSON.stringify({ args, cwd: process.cwd(), pid: process.pid }) + '\n');
if (process.env.MARLIN_LOCAL_FIXTURE_MODE === 'fail-config' && args.includes('config')) {
  process.stderr.write('synthetic-private-fixture-secret'); process.exit(7);
}
if (process.env.MARLIN_LOCAL_FIXTURE_MODE === 'hold-config' && args.includes('config')) {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
  fs.writeFileSync(record + '.child', String(child.pid));
  setInterval(() => {}, 1000);
}
if (process.env.MARLIN_LOCAL_FIXTURE_MODE === 'noisy') {
  process.stdout.write('synthetic-output-'.repeat(150000));
  process.stderr.write('synthetic-private-error-'.repeat(150000));
}
if (process.env.MARLIN_LOCAL_FIXTURE_MODE === 'echo') {
  process.stdout.write('fixture-output'); process.stderr.write('fixture-error');
}
