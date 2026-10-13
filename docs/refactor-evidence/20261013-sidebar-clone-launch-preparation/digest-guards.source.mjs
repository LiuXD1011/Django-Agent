import assert from 'node:assert/strict';
import {digest} from '/home/liuxuedeng/Django-Agent/docs/refactor-evidence/20261013-sidebar-clone-launch-preparation/snapshot-audit.mjs';
assert.notEqual(digest({seq:(1n<<60n)+321n}),digest({seq:Number((1n<<60n)+321n)}));
assert.notEqual(digest({body:Buffer.from([0,255])}),digest({body:Buffer.from([0,254])}));
assert.equal(digest({a:1n,b:'x'}),digest({b:'x',a:1n}));
assert.notEqual(digest(Infinity),digest(-Infinity));
assert.notEqual(digest(-0),digest(0));
assert.notEqual(digest(Buffer.from('1')),digest('1'));
console.log(JSON.stringify({state:'prepared_digest_guards_passed',assertions:6,nativeOrProductCalls:0}));
