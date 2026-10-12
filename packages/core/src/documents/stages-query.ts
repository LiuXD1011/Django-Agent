import type { JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';
import type { DatabaseReader } from '../storage/read-database.js';
import type { KnowledgeReadDomain } from '../knowledge/read-domain.js';
import type { ReadRouteRegistrar } from '../knowledge/read-routes.js';

/** Caller must authorize this document in the same snapshot before projecting spans. */
export function readDocumentStages(db: DatabaseReader, knowledgeId: string): JsonObject {
  const spans = db.all('SELECT id FROM knowledge_processing_spans WHERE knowledge_id=? ORDER BY attempt,started_at,id', knowledgeId).map(r => db.read('knowledge_processing_spans', String(r.id))!).map(r => ({ id: r.span_id!, parent_id: r.parent_span_id!, name: r.name!, kind: r.kind!, status: r.status!, attempt: r.attempt!, input: r.input_data!, output: r.output_data!, metadata: r.metadata!, error_code: r.error_code!, error_message: r.error_message!, started_at: r.started_at!, finished_at: r.finished_at!, duration_ms: r.duration_ms! }));
  return { knowledge_id: knowledgeId, spans };
}

export function registerDocumentReadRoutes(registrar: ReadRouteRegistrar, domain: KnowledgeReadDomain,
  options: { parserEnabled: boolean }): void {
  registrar.route('GET', '/api/v1/knowledge/:id/stages', c => {
    if (!options.parserEnabled) throw new AppError(503, 'parser_not_configured', '文档解析器尚未配置，请检查应用运行环境。');
    domain.doc(c.auth, c.params.id!);
    const result = readDocumentStages(domain.db, c.params.id!);
    return { knowledge_id: result.knowledge_id!, items: result.spans!, spans: result.spans! };
  });
}
