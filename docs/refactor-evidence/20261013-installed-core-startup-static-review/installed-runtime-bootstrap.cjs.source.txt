'use strict';
// Imported by the bundled Node only. Business modules remain behind the Job
// authorization gate; none of this protocol is exposed to the renderer.
const { pathToFileURL } = require('node:url');
const [entryPoint, generation, nativePath, ...args] = process.argv.slice(2);
if (!process.send || !entryPoint || !nativePath || !/^[a-f0-9-]{36}$/.test(generation || '')) {
  process.exitCode = 1;
} else {
  let starting = false;
  const close = () => process.exit(1);
  const send = process.send;
  function detach() {
    process.removeListener('message', authorize);
    process.removeListener('disconnect', close);
    process.send = send;
  }
  // desktop-process starts asynchronously. Keep early shutdown/disconnect
  // effective until its ready message proves that Core listeners are installed.
  process.send = function (message, ...rest) {
    if (message?.type === 'ready' && message.protocol === 1) detach();
    return Reflect.apply(send, this, [message, ...rest]);
  };
  function authorize(message) {
    if (message && Object.keys(message).length === 1 && message.type === 'shutdown') {
      process.exit(0);
    }
    if (starting || !message || Object.getPrototypeOf(message) !== Object.prototype
      || Object.keys(message).length !== 3 || message.type !== 'owned-start'
      || message.protocol !== 1 || message.generation !== generation) {
      close(); return;
    }
    starting = true;
    process.argv = [process.execPath, entryPoint, ...args];
    void import(pathToFileURL(entryPoint).href).catch(close);
  }
  process.on('message', authorize);
  process.once('disconnect', close);
  try {
    const identity = require(nativePath).currentIdentity();
    if (identity.pid !== process.pid || typeof identity.createdAt !== 'string' || !/^[1-9][0-9]{0,19}$/.test(identity.createdAt)) throw new Error('Invalid native identity');
    process.send({ type: 'owned-bootstrap', protocol: 1, generation, pid: identity.pid, createdAt: identity.createdAt }, error => { if (error) close(); });
  } catch { close(); }
}
