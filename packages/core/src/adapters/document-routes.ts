import { CoreBinary, type CoreApplication } from '../application.js';
import type { JsonObject } from '../contracts.js';
import { AppError } from '../errors.js';

export function registerDocumentRoutes(app: CoreApplication): void {
  const workflow = () => {
    if (!app.documents) throw new AppError(503, 'parser_not_configured', '文档解析器尚未配置，请检查应用运行环境。');
    return app.documents;
  };
  app.route('POST', '/api/v1/knowledge-bases/:id/knowledge/file', async c => {
    if (!c.upload) throw new AppError(400, 'upload_required', '请选择要上传的文件。');
    const result = await workflow().upload(c.auth, c.params.id!, c.upload, c.request.id);
    return { ...result, deduplicated: result.repeated };
  });
  app.route('POST', '/api/v1/knowledge/:id/reparse', async c => {
    const raw = c.body.process_config ?? c.body;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new AppError(400, 'invalid_process_config', '解析配置必须是对象。');
    const result = await workflow().reparse(c.auth, c.params.id!, raw as JsonObject, c.request.id);
    return { ...result, deduplicated: result.repeated };
  });
  app.route('POST', '/api/v1/knowledge/:id/cancel-parse', c => workflow().cancel(c.auth, c.params.id!));
  app.route('GET', '/api/v1/knowledge/:id/stages', c => {
    const result = workflow().stages(c.auth, c.params.id!);
    return { knowledge_id: result.knowledge_id!, items: result.spans!, spans: result.spans! };
  });
  app.route('GET', '/api/v1/knowledge/:id/download', async c => {
    const file = await workflow().readOwnedSource(c.auth, c.params.id!);
    return new CoreBinary(file.bytes, file.name, file.mimeType, file.sha256);
  });
  app.route('GET', '/api/v1/knowledge/:id/images/:image', async c => {
    const file = await workflow().getMedia(c.auth, c.params.id!, c.params.image!);
    return new CoreBinary(file.bytes, file.name, file.mimeType, file.sha256);
  });
}
