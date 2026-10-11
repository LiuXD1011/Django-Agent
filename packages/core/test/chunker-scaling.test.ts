import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import type { ParsedDocument } from '../src/contracts.js';
import { splitDocument } from '../src/documents/chunker.js';

function document(content: string): ParsedDocument {
  const hash = createHash('sha256').update(content).digest('hex');
  return {
    document: {
      name: 'large-text.txt', input_sha256: hash, parser_version: 'unit-fixture',
      canonicalization_version: 'blocks-double-newline-v1', offset_unit: 'unicode_code_point',
      canonical_text: content, canonical_sha256: hash,
    },
    blocks: [{
      id: 'b0', kind: 'text', block_index: 0, block_type: 'text', text: content,
      canonical_range: { start: 0, end: Array.from(content).length }, provenance: {}, metadata: {},
    }],
    warnings: [], diagnostics: {},
  };
}

test('large parent-child documents keep regular-expression scanning proportional to input size', async () => {
  const content = Array.from({ length: 40000 }, (_, i) => `${String(i).padStart(6, '0')} fixture revenue Q1=100; repeated line for document ingestion.\n`).join('');
  const parsed = document(content), original = String.prototype.matchAll;
  let scannedCharacters = 0;
  // Observe work on real inputs rather than asserting an elapsed-time budget.
  // A guard stops the regression early instead of spending minutes scanning.
  String.prototype.matchAll = function (this: string, regexp: RegExp) {
    scannedCharacters += this.length;
    if (scannedCharacters > content.length * 24)
      throw new Error('repeated_full_document_scanning');
    return original.call(this, regexp);
  };
  let result;
  try {
    result = await splitDocument(parsed, {}, { title: 'Large text' });
  } finally {
    String.prototype.matchAll = original;
  }
  assert.ok(result.parents.length > 1000);
  assert.ok(result.children.length > result.parents.length);
  assert.deepEqual(result.diagnostics.fallback_chain, []);
  assert.ok(scannedCharacters <= content.length * 24);
  assert.equal(result.parents.map(chunk => chunk.content).join(''), content);
  for (const chunk of result.children) {
    const parent = result.parents[chunk.context_parent_index!];
    assert.ok(parent && parent.start_at <= chunk.start_at && chunk.end_at <= parent.end_at);
    assert.equal(chunk.content, content.slice(chunk.start_at, chunk.end_at));
  }
});
