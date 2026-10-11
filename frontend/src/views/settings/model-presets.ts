export type ModelType = 'KnowledgeQA' | 'Embedding' | 'Rerank' | 'VLLM'

interface ModelDefaults {
  model: string
  dimension?: number
}

export interface ModelPreset {
  id: string
  label: string
  source: string
  baseUrl: string
  requiresKey: boolean
  models: Partial<Record<ModelType, ModelDefaults>>
}

// 参考 WeKnora ModelEditorDialog 的厂商预设和类型筛选；仅列出当前调用链支持的协议。
export const modelPresets: ModelPreset[] = [
  {
    id: 'aliyun-bailian', label: '阿里云百炼 / 通义千问', source: 'aliyun-bailian',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', requiresKey: true,
    models: { KnowledgeQA: { model: 'qwen-plus' }, Embedding: { model: 'text-embedding-v4', dimension: 1024 }, VLLM: { model: 'qwen-vl-plus' } },
  },
  {
    id: 'deepseek', label: 'DeepSeek', source: 'deepseek',
    baseUrl: 'https://api.deepseek.com/v1', requiresKey: true,
    models: { KnowledgeQA: { model: 'deepseek-chat' } },
  },
  {
    id: 'openai', label: 'OpenAI', source: 'openai',
    baseUrl: 'https://api.openai.com/v1', requiresKey: true,
    models: { KnowledgeQA: { model: 'gpt-4o-mini' }, Embedding: { model: 'text-embedding-3-small', dimension: 1536 }, VLLM: { model: 'gpt-4o-mini' } },
  },
  {
    id: 'siliconflow', label: '硅基流动 / SiliconFlow', source: 'siliconflow',
    baseUrl: 'https://api.siliconflow.cn/v1', requiresKey: true,
    models: { KnowledgeQA: { model: 'Qwen/Qwen3-32B' }, Embedding: { model: 'BAAI/bge-m3', dimension: 1024 }, Rerank: { model: 'BAAI/bge-reranker-v2-m3' } },
  },
  {
    id: 'zhipu', label: '智谱 / GLM', source: 'zhipu',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4', requiresKey: true,
    models: { KnowledgeQA: { model: 'glm-5.3-flash' }, VLLM: { model: 'glm-5.3-flash' } },
  },
  {
    id: 'gemini', label: 'Google Gemini', source: 'gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', requiresKey: true,
    models: { KnowledgeQA: { model: 'gemini-3.8-flash' }, VLLM: { model: 'gemini-3.8-flash' } },
  },
  {
    id: 'local', label: 'Ollama / 本地模型', source: 'local',
    baseUrl: 'http://localhost:11434/v1', requiresKey: false,
    models: { KnowledgeQA: { model: 'qwen3:8b' }, Embedding: { model: 'bge-m3', dimension: 1024 }, VLLM: { model: 'qwen2.5vl:7b' } },
  },
  {
    id: 'custom', label: '自定义 / OpenAI 兼容', source: 'openai',
    baseUrl: '', requiresKey: false,
    models: { KnowledgeQA: { model: '' }, Embedding: { model: '' }, Rerank: { model: '' }, VLLM: { model: '' } },
  },
]

export function presetsForType(type: string) {
  return modelPresets.filter((preset) => preset.models[type as ModelType])
}

export function inferPreset(model: { source?: string; type?: string; parameters?: { base_url?: string } }) {
  const url = String(model.parameters?.base_url || '').replace(/\/+$/, '')
  return modelPresets.find((preset) => preset.id !== 'custom' && preset.baseUrl === url
    && preset.models[model.type as ModelType])?.id || 'custom'
}

export function presetFields(id: string, type: string) {
  const preset = presetsForType(type).find((item) => item.id === id)
  if (!preset || preset.id === 'custom') return null
  const defaults = preset.models[type as ModelType]!
  return {
    source: preset.source,
    name: defaults.model,
    display_name: `${preset.label} · ${defaults.model}`,
    parameters: { base_url: preset.baseUrl, api_key: '', model: defaults.model, dimension: defaults.dimension || 1024 },
  }
}
