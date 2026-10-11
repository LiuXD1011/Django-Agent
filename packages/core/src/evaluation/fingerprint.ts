import type { AuthContext, JsonObject } from '../contracts.js';
import type { CoreDatabase } from '../storage/database.js';
import { digest, object } from './common.js';
/** Includes all searchable source documents and stored chunk content, rather than only judged evidence. */
export function corpusFingerprint(db: CoreDatabase, ctx: AuthContext, kbId: string): JsonObject {
  const kb = db.read('knowledge_bases', kbId);
  const documents = db.all("SELECT id FROM knowledges WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL AND enable_status='enabled' ORDER BY id", ctx.tenantId, kbId).map(value => {
    const doc = db.read('knowledges', String(value.id))!, metadata = object(doc.metadata);
    return { id: String(doc.id), file_hash: doc.file_hash!, source_generation: metadata.source_generation ?? null, canonical_hash: digest(metadata.content ?? null), parser_hash: digest([metadata.parser_blocks ?? null, metadata.parser_image_block_indices ?? null]) };
  });
  const chunks = db.all('SELECT id,knowledge_id,content,start_at,end_at,context_parent_id,is_enabled,chunk_type FROM chunks WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL ORDER BY id', ctx.tenantId, kbId);
  const index = db.all('SELECT model_signature,dimension,generation,status FROM search_index_meta WHERE tenant_id=? AND knowledge_base_id=? ORDER BY id', ctx.tenantId, kbId);
  return { knowledge_base_id: kbId, corpus_hash: digest([documents, chunks, kb?.chunking_config ?? null, index]), documents };
}
