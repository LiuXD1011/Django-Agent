import type { CoreApplication } from '../application.js';
import type { AuthContext, JsonObject } from '../contracts.js';
import { ModelCaller } from '../chat/index.js';
import { embeddingBinding } from '../documents/pipeline.js';
import { AppError } from '../errors.js';
import type { SearchOptions, SearchScope } from '../retrieval/types.js';

export function retrievalOptions(app: CoreApplication, ctx: AuthContext, scope: SearchScope): SearchOptions {
  const config = app.settings.getKV(ctx, 'retrieval').value as JsonObject;
  const assert = () => { app.auth.assertCan(ctx, 'read'); for (const id of scope.knowledgeBaseIds ?? []) app.knowledge.knowledgeBases.get(ctx, id); };
  const caller = new ModelCaller(app.database, app.models, ctx, { operation: 'retrieval', knowledge_base_ids: scope.knowledgeBaseIds ?? [] }, assert, () => {});
  const options: SearchOptions = {
    ...(typeof config.keyword_top_k === 'number' ? { keywordTopK: config.keyword_top_k } : {}),
    vectorTopK: typeof config.embedding_top_k === 'number' ? config.embedding_top_k : 10,
    rerankTopK: typeof config.rerank_top_k === 'number' ? config.rerank_top_k : 5,
    keywordThreshold: typeof config.keyword_threshold === 'number' ? config.keyword_threshold : 0.3,
    vectorThreshold: typeof config.vector_threshold === 'number' ? config.vector_threshold : 0.15,
    rerankThreshold: typeof config.rerank_threshold === 'number' ? config.rerank_threshold : 0.3,
    ...(['keyword', 'vector', 'hybrid'].includes(String(config.strategy)) ? { strategy: config.strategy as SearchOptions['strategy'] } : {}),
  };
  try {
    const pinned = app.searchIndex.embeddingModelIds(scope), model = app.models.configuration(ctx, pinned[0] || 'Embedding');
    const binding = embeddingBinding(model);
    binding.runtime = { embed: (texts, callOptions) => caller.invoke(model.id, 'query_embedding', async (runtime, usage) => {
      if (embeddingBinding(app.models.configuration(ctx, model.id)).signature !== binding.signature) throw new AppError(409, 'embedding_configuration_changed', 'Embedding 配置已改变，请重建索引后重试。');
      const result = await runtime.embed(texts, callOptions); usage(result.usage); assert(); return result;
    }) };
    options.embedding = binding;
  } catch (error) { if (!(error instanceof AppError) || error.status !== 404) throw error; }
  if (config.rerank_enabled === false) options.rerankTopK = 0;
  else try {
    const model = app.models.configuration(ctx, typeof config.rerank_model_id === 'string' && config.rerank_model_id ? config.rerank_model_id : 'Rerank');
    options.reranker = { rerank: (query, documents, callOptions) => caller.invoke(model.id, 'query_rerank', async (runtime, usage) => { const result = await runtime.rerank(query, documents, callOptions); usage(result.usage); assert(); return result; }) };
  } catch (error) { if (!(error instanceof AppError) || error.status !== 404) throw error; }
  return options;
}
