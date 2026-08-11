import test from 'node:test'
import assert from 'node:assert/strict'

import { safeParseStorage } from './auth-storage.mjs'

test('safeParseStorage returns null and clears malformed JSON', () => {
  const removed = []
  const storage = {
    removeItem(key) {
      removed.push(key)
    },
  }

  assert.equal(safeParseStorage('{broken', 'personal_kb_user', storage), null)
  assert.deepEqual(removed, ['personal_kb_user'])
})

test('safeParseStorage preserves valid JSON values', () => {
  const storage = { removeItem() {} }
  assert.deepEqual(safeParseStorage('{"id":"user-1"}', 'personal_kb_user', storage), { id: 'user-1' })
})
