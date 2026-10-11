import assert from 'node:assert/strict';
import { test } from 'node:test';

test('stored JSON preserves legacy numeric IDs beyond 2^53 as exact decimal wire strings', async () => {
  const module = await import('../src/storage/json.js').catch(() => null);
  assert.ok(module, 'Lossless stored JSON parser must exist');
  assert.deepEqual(module.parseStoredJson('{"seq_id":1152921504606846975,"negative":-1152921504606846975,"quoted":"1152921504606846975","normal":46.8,"safe":9007199254740991}'), { seq_id: '1152921504606846975', negative: '-1152921504606846975', quoted: '1152921504606846975', normal: 46.8, safe: Number.MAX_SAFE_INTEGER });
  assert.deepEqual(module.parseStoredJson('[null,true,{"id":1152921504606846975}]'), [null, true, { id: '1152921504606846975' }]);
  assert.throws(() => module.parseStoredJson('{"value":1e400}'), /JSON|范围/);
});
