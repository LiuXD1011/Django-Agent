import type { CoreApplication } from '../application.js';
import { AppError } from '../errors.js';

export function registerGraphRoutes(app: CoreApplication): void {
  const base = '/api/v1/knowledge-bases/:id/graph';
  app.route('GET', base, c => app.graph.overview(c.auth, c.params.id!, Object.fromEntries(c.query), { signal: c.signal }));
  app.route('GET', base + '/capabilities', c => app.graph.capabilities(c.auth, c.params.id!));
  app.route('GET', base + '/types', c => app.graph.types(c.auth, c.params.id!, { signal: c.signal }));
  app.route('GET', base + '/ego', c => {
    const center = c.query.get('center');
    if (!center) throw new AppError(400, 'graph_center_required', '请选择图谱节点。');
    return app.graph.ego(c.auth, c.params.id!, center, Object.fromEntries(c.query), { signal: c.signal });
  });
  app.route('POST', base + '/cleanup', c => app.graph.processPending(c.auth, c.params.id!, { signal: c.signal }));
}
