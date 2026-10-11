import { randomUUID } from 'node:crypto';
import type { AuthContext, ChatMessage, JsonObject, ModelCallOptions, ModelUsage } from '../contracts.js';
import { ModelRuntime, ModelRuntimeError, type ModelCompletion } from '../models/runtime.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import type { CoreDatabase } from '../storage/database.js';
import { currentObservation } from '../observability/context.js';
export const zeroUsage = (): ModelUsage => ({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cached_tokens: 0, reasoning_tokens: 0 });

/** One invocation sends one provider request. Audit survives cancellation or membership revocation. */
export class ModelCaller {
  constructor(readonly db: CoreDatabase, readonly models: ModelConfigurationService, readonly context: AuthContext,
    readonly metadata: JsonObject, readonly assert: () => void, readonly journal: (data: JsonObject) => void) {}
  async invoke<T>(model: string, scenario: string, work: (runtime: ModelRuntime, usage: (u: ModelUsage) => void) => Promise<T>, extra: JsonObject = {}): Promise<T> {
    this.assert();
    const configuration = this.models.configuration(this.context, model), runtime = new ModelRuntime(configuration);
    const id = randomUUID(), started = Date.now(), observation = currentObservation(this.context); let usage = zeroUsage(), success = false, code = '', unknown = false;
    try { const result = await work(runtime, value => { usage = { ...value }; }); success = true; return result; }
    catch (error) { code = error instanceof ModelRuntimeError ? error.code : 'model_call_failed'; unknown = error instanceof ModelRuntimeError && error.resultUnknown; throw error; }
    finally {
      const ended = Date.now(), duration = ended - started;
      const outcome = { invocationId: id, scenario, success, durationMs: duration, errorCode: code || undefined, metadata: { ...this.metadata, ...extra, model_call_id: id, result_unknown: unknown } };
      // Logging failure never causes a second paid request. Persist a credential-free audit for repair.
      try { this.models.recordUsage(this.context, configuration, usage, outcome); }
      catch { this.db.run('insert into desktop_meta(key,value) values(?,?) on conflict(key) do update set value=excluded.value', `chat.audit.pending:${id}`, JSON.stringify({ context: this.context, configuration: { ...configuration, parameters: {} }, usage, outcome })); }
      try { this.journal({ ...usage, success, model: configuration.name, provider: configuration.source, duration_ms: duration, ...extra }); } catch { /* A revoked or terminal turn cannot receive late projection events. */ }
      try { observation?.model({ invocationId: id, scenario, startedAt: started, endedAt: ended, success, usage, metadata: { ...this.metadata, ...extra } }); } catch { /* Optional telemetry cannot change the paid invocation or its audit. */ }
    }
  }
  complete(model: string, messages: ChatMessage[], options: ModelCallOptions, scenario = 'chat', extra: JsonObject = {}): Promise<ModelCompletion> {
    return this.invoke(model, scenario, async (runtime, usage) => { const result = await runtime.complete(messages, options); usage(result.usage); return result; }, extra);
  }
  vision(model: string, image: string, prompt: string, options: ModelCallOptions): Promise<ModelCompletion> {
    return this.invoke(model, 'chat_image', async (runtime, usage) => { const result = await runtime.vision(image, prompt, options); usage(result.usage); return result; }, { operation: 'vision' });
  }
}
