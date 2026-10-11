import { createHash } from 'node:crypto';
import { CoreBinary, type CoreApplication } from '../application.js';
import type { JsonObject } from '../contracts.js';

export function registerEvaluationRoutes(app: CoreApplication): void {
  const base = '/api/v1/rag-eval', service = app.evaluation;
  const schedule = (result: JsonObject) => {
    const id = result.task_id ?? result.run_id;
    if (typeof id === 'string' && result.status === 'queued') void app.runTask(() => app.jobs.run(id)).catch(() => {});
    return result;
  };
  app.route('GET', base + '/datasets', c => service.listDatasets(c.auth));
  app.route('POST', base + '/datasets', c => service.createDataset(c.auth, c.body));
  app.route('GET', base + '/datasets/:id', c => service.getDataset(c.auth, c.params.id!));
  app.route('PATCH', base + '/datasets/:id/entries/:entry', c => service.editEntry(c.auth, c.params.id!, c.params.entry!, c.body));
  app.route('DELETE', base + '/datasets/:id/entries/:entry', c => service.deleteEntry(c.auth, c.params.id!, c.params.entry!));
  app.route('POST', base + '/datasets/:id/review', c => service.review(c.auth, c.params.id!, c.body));
  app.route('POST', base + '/datasets/:id/publish', c => service.publish(c.auth, c.params.id!));
  app.route('POST', base + '/datasets/:id/versions', c => service.newVersion(c.auth, c.params.id!));
  app.route('GET', base + '/testsets', c => service.listDatasets(c.auth, 'testsets'));
  app.route('GET', base + '/testsets/:id', c => service.getDataset(c.auth, c.params.id!));
  app.route('POST', base + '/testsets', c => service.generate(c.auth, c.body, 'testsets', { signal: c.signal }));
  app.route('POST', base + '/generate', c => service.generate(c.auth, c.body, 'datasets', { signal: c.signal }));
  app.route('GET', base + '/questions', c => service.questions(c.auth));
  app.route('POST', base + '/questions', c => service.addQuestion(c.auth, c.body));
  app.route('DELETE', base + '/questions/:id', c => service.deleteQuestion(c.auth, c.params.id!));
  app.route('GET', base + '/history', c => service.history(c.auth));
  app.route('GET', base + '/open-datasets', c => service.openDatasets(c.auth));
  app.route('GET', base + '/open-datasets/:id/status', c => service.openStatus(c.auth, c.params.id!));
  app.route('POST', base + '/open-datasets/:id/prepare', c => schedule(service.queuePrepareOpen(c.auth, c.params.id!, c.request.id)));
  for (const path of ['/runs', '/open-runs']) {
    app.route('POST', base + path, async c => schedule(await service.createRun(c.auth, c.body, c.request.id)));
    app.route('GET', base + path + '/:id', c => service.status(c.auth, c.params.id!));
    app.route('POST', base + path + '/:id/cancel', c => service.cancel(c.auth, c.params.id!));
    app.route('POST', base + path + '/:id/resume', c => schedule(service.resume(c.auth, c.params.id!, c.body)));
  }
  app.route('GET', base + '/runs', c => { const result = service.active(c.auth), runs = result.runs as JsonObject[]; return { ...result, active_run: runs[0] ?? null }; });
  app.route('POST', base + '/runs/estimate', c => service.estimate(c.auth, c.body));
  app.route('POST', base + '/run', async c => schedule(await service.createLegacyRun(c.auth, c.body, c.request.id)));
  for (const kind of ['retrieval', 'chunking'] as const) app.route('POST', `${base}/${kind}`, c => service.runDeterministic(c.auth, kind, c.body, c.request.id, { signal: c.signal }));
  app.route('GET', base + '/reports/:id', c => {
    const report = service.downloadReport(c.auth, c.params.id!);
    return new CoreBinary(report.bytes, report.filename, report.mimeType, createHash('sha256').update(report.bytes).digest('hex'));
  });
  app.route('DELETE', base + '/reports/:id', c => service.deleteReport(c.auth, c.params.id!));
}
