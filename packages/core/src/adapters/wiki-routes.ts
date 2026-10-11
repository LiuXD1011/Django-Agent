import type { CoreApplication } from '../application.js';
import { AppError } from '../errors.js';

export function registerWikiRoutes(app: CoreApplication): void {
  const base = '/api/v1/knowledge-bases/:id/wiki';
  app.route('GET', base + '/pages', c => app.wiki.list(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('POST', base + '/pages', c => app.wiki.create(c.auth, c.params.id!, c.body));
  app.route('GET', base + '/pages/:slug*', c => app.wiki.get(c.auth, c.params.id!, c.params.slug!));
  app.route('PUT', base + '/pages/:slug*', c => app.wiki.update(c.auth, c.params.id!, c.params.slug!, c.body));
  app.route('PATCH', base + '/pages/:slug*', c => app.wiki.update(c.auth, c.params.id!, c.params.slug!, c.body));
  app.route('DELETE', base + '/pages/:slug*', c => app.wiki.delete(c.auth, c.params.id!, c.params.slug!));
  app.route('GET', base + '/folders', c => app.wiki.folders(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('POST', base + '/folders', c => app.wiki.createFolder(c.auth, c.params.id!, c.body));
  app.route('GET', base + '/folders/:folder', c => app.wiki.getFolder(c.auth, c.params.id!, c.params.folder!));
  app.route('PUT', base + '/folders/:folder', c => app.wiki.updateFolder(c.auth, c.params.id!, c.params.folder!, c.body));
  app.route('DELETE', base + '/folders/:folder', c => app.wiki.deleteFolder(c.auth, c.params.id!, c.params.folder!));
  app.route('GET', base + '/index', c => app.wiki.index(c.auth, c.params.id!));
  app.route('GET', base + '/search', c => app.wiki.search(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('GET', base + '/graph', c => app.wiki.graph(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('GET', base + '/stats', c => app.wiki.stats(c.auth, c.params.id!));
  app.route('GET', base + '/log', c => app.wiki.log(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('GET', base + '/lint', c => app.wiki.lint(c.auth, c.params.id!));
  app.route('GET', base + '/issues', c => app.wiki.issues(c.auth, c.params.id!, Object.fromEntries(c.query)));
  app.route('PUT', base + '/issues/:issue/status', c => {
    if (typeof c.body.status !== 'string') throw new AppError(400, 'invalid_issue_status', '请选择检查项状态。');
    return app.wiki.updateIssueStatus(c.auth, c.params.id!, c.params.issue!, c.body.status);
  });
}
