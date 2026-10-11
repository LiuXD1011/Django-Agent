import type { CoreApplication } from '../application.js';

export function registerAgentRoutes(app: CoreApplication): void {
  app.route('GET', '/api/v1/agents/placeholders', () => app.agents.placeholders());
  app.route('GET', '/api/v1/agents/type-presets', () => app.agents.types());
  app.route('GET', '/api/v1/agents', c => app.agents.list(c.auth, Object.fromEntries(c.query)));
  app.route('POST', '/api/v1/agents', c => app.agents.create(c.auth, c.body));
  app.route('GET', '/api/v1/agents/:id', c => app.agents.get(c.auth, c.params.id!));
  app.route('PUT', '/api/v1/agents/:id', c => app.agents.update(c.auth, c.params.id!, c.body));
  app.route('PATCH', '/api/v1/agents/:id', c => app.agents.update(c.auth, c.params.id!, c.body));
  app.route('DELETE', '/api/v1/agents/:id', c => app.agents.delete(c.auth, c.params.id!));
  app.route('POST', '/api/v1/agents/:id/copy', c => app.agents.copy(c.auth, c.params.id!));
  app.route('GET', '/api/v1/agents/:id/suggested-questions', c => app.agents.suggestedQuestions(c.auth, c.params.id!));
}
