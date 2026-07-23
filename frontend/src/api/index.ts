import client from './client'

export type ChunkingStrategy = 'auto' | 'heading' | 'layout' | 'record' | 'recursive' | 'semantic'

export interface ChunkingConfig {
  strategy: ChunkingStrategy
  chunk_size: number
  chunk_overlap: number
  enable_parent_child: boolean
  parent_chunk_size: number
  child_chunk_size: number
  child_chunk_overlap: number
  token_limit: number
  semantic_window_size: number
  semantic_breakpoint_percentile: number
}

export const chunkingStrategyOptions: Array<{ value: ChunkingStrategy; label: string }> = [
  { value: 'auto', label: 'Auto' },
  { value: 'heading', label: 'Heading' },
  { value: 'layout', label: 'Layout' },
  { value: 'record', label: 'Record' },
  { value: 'recursive', label: 'Recursive' },
  { value: 'semantic', label: 'Semantic (Experimental)' },
]

const defaultChunkingConfig: ChunkingConfig = {
  strategy: 'auto',
  chunk_size: 512,
  chunk_overlap: 80,
  enable_parent_child: true,
  parent_chunk_size: 2048,
  child_chunk_size: 384,
  child_chunk_overlap: 64,
  token_limit: 0,
  semantic_window_size: 3,
  semantic_breakpoint_percentile: 90,
}

export function normalizeChunkingConfig(raw?: Partial<ChunkingConfig> | null): ChunkingConfig {
  return {
    strategy: raw?.strategy ?? defaultChunkingConfig.strategy,
    chunk_size: Number(raw?.chunk_size ?? defaultChunkingConfig.chunk_size),
    chunk_overlap: Number(raw?.chunk_overlap ?? defaultChunkingConfig.chunk_overlap),
    enable_parent_child: raw?.enable_parent_child ?? defaultChunkingConfig.enable_parent_child,
    parent_chunk_size: Number(raw?.parent_chunk_size ?? defaultChunkingConfig.parent_chunk_size),
    child_chunk_size: Number(raw?.child_chunk_size ?? defaultChunkingConfig.child_chunk_size),
    child_chunk_overlap: Number(raw?.child_chunk_overlap ?? defaultChunkingConfig.child_chunk_overlap),
    token_limit: Number(raw?.token_limit ?? defaultChunkingConfig.token_limit),
    semantic_window_size: Number(raw?.semantic_window_size ?? defaultChunkingConfig.semantic_window_size),
    semantic_breakpoint_percentile: Number(raw?.semantic_breakpoint_percentile ?? defaultChunkingConfig.semantic_breakpoint_percentile),
  }
}

export function chunkingConfigError(config: ChunkingConfig): string {
  const integerRanges: Array<[keyof ChunkingConfig, number, number, string]> = [
    ['chunk_size', 128, 4096, '分块长度'],
    ['parent_chunk_size', 512, 8192, '父块长度'],
    ['child_chunk_size', 128, 2048, '子块长度'],
    ['token_limit', 0, 32768, 'Token 上限'],
    ['semantic_window_size', 1, 32, '语义窗口'],
  ]
  for (const [key, minimum, maximum, label] of integerRanges) {
    const value = Number(config[key])
    if (!Number.isInteger(value) || value < minimum || value > maximum) return `${label}需在 ${minimum} 到 ${maximum} 之间`
  }
  if (!Number.isInteger(config.chunk_overlap) || config.chunk_overlap < 0 || config.chunk_overlap > Math.floor(config.chunk_size / 2)) {
    return '重叠字符不能超过分块长度的一半'
  }
  if (!Number.isInteger(config.child_chunk_overlap) || config.child_chunk_overlap < 0 || config.child_chunk_overlap > Math.floor(config.child_chunk_size / 2)) {
    return '子块重叠不能超过子块长度的一半'
  }
  if (config.parent_chunk_size < config.child_chunk_size) return '父块长度不能小于子块长度'
  if (!Number.isFinite(config.semantic_breakpoint_percentile) || config.semantic_breakpoint_percentile < 0 || config.semantic_breakpoint_percentile > 100) {
    return '语义断点百分位需在 0 到 100 之间'
  }
  return ''
}

export function chunkingStrategyLabel(strategy?: string | null): string {
  return chunkingStrategyOptions.find((item) => item.value === strategy)?.label || '-'
}

function authHeaders(extra: Record<string, string> = {}) {
  const token = localStorage.getItem('personal_kb_token')
  const tenant = localStorage.getItem('personal_kb_selected_tenant_id')
  return {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(tenant ? { 'X-Tenant-ID': tenant } : {}),
    'X-Request-ID': Math.random().toString(36).slice(2),
    ...extra,
  }
}

export async function streamChat(
  sessionId: string,
  data: any,
  agent = false,
  onEvent: (event: string, payload: any) => void,
  signal?: AbortSignal,
) {
  const url = `${agent ? '/api/v1/agent-chat' : '/api/v1/knowledge-chat'}/${sessionId}`

  const response = await fetch(url, {
    method: 'POST',
    headers: authHeaders(data?.request_id ? { 'X-Request-ID': String(data.request_id) } : {}),
    body: JSON.stringify({ ...data, stream: true, channel: 'web' }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`stream request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      for (const frame of frames) {
        let event = 'message'
        let dataLine = ''
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          // SSE 规范：多行 data 字段用换行符连接
          if (line.startsWith('data:')) dataLine += (dataLine ? '\n' : '') + line.slice(5).trim()
        }
        if (!dataLine) continue
        try {
          const parsed = JSON.parse(dataLine)
          onEvent(event, parsed)
        } catch {
          onEvent(event, dataLine)
        }
      }
    }
  } finally {
    reader.cancel()
  }
}

/**
 * Continue-stream: 断线重连。
 * 当页面刷新或重新打开有未完成消息的会话时，调用此函数恢复流式输出。
 * 参考同类知识库系统的 continue-stream 实现。
 */
export async function continueStream(
  sessionId: string,
  messageId: string,
  onEvent: (event: string, payload: any) => void,
  signal?: AbortSignal,
) {
  const url = `/api/v1/sessions/continue-stream/${sessionId}?message_id=${encodeURIComponent(messageId)}`

  const response = await fetch(url, {
    method: 'GET',
    headers: authHeaders(),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`continue-stream failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      for (const frame of frames) {
        let event = 'message'
        let dataLine = ''
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          if (line.startsWith('data:')) dataLine += (dataLine ? '\n' : '') + line.slice(5).trim()
        }
        if (!dataLine) continue
        try {
          const parsed = JSON.parse(dataLine)
          onEvent(event, parsed)
        } catch {
          onEvent(event, dataLine)
        }
      }
    }
  } finally {
    reader.cancel()
  }
}

export const api = {
  autoSetup: () => client.post('/api/v1/auth/auto-setup'),
  login: (data: any) => client.post('/api/v1/auth/login', data),
  me: () => client.get('/api/v1/auth/me'),
  updatePreferences: (data: any) => client.put('/api/v1/auth/me/preferences', data),
  changePassword: (data: any) => client.post('/api/v1/auth/change-password', data),
  listKbs: () => client.get('/api/v1/knowledge-bases'),
  searchKbs: (params: any = {}) => client.get('/api/v1/knowledge-bases', { params }),
  createKb: (data: any) => client.post('/api/v1/knowledge-bases', data),
  getKb: (id: string) => client.get(`/api/v1/knowledge-bases/${id}`),
  updateKb: (id: string, data: any) => client.put(`/api/v1/knowledge-bases/${id}`, data),
  deleteKb: (id: string) => client.delete(`/api/v1/knowledge-bases/${id}`),
  pinKb: (id: string, isPinned?: boolean) => client.put(`/api/v1/knowledge-bases/${id}/pin`, { is_pinned: isPinned }),
  copyKb: (sourceId: string) => client.post('/api/v1/knowledge-bases/copy', { source_id: sourceId }),
  moveTargets: (kbId: string) => client.get(`/api/v1/knowledge-bases/${kbId}/move-targets`),
  listKnowledge: (kbId: string, params: any = {}) => client.get(`/api/v1/knowledge-bases/${kbId}/knowledge`, { params }),
  getKnowledgeSpans: (knowledgeId: string) => client.get(`/api/v1/knowledge/${knowledgeId}/stages`),
  uploadFile: (kbId: string, file: File, options: { tag_id?: string; process_config?: any } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (options.tag_id) fd.append('tag_id', options.tag_id)
    if (options.process_config) fd.append('process_config', JSON.stringify(options.process_config))
    return client.post(`/api/v1/knowledge-bases/${kbId}/knowledge/file`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  },
  deleteKnowledge: (id: string) => client.delete(`/api/v1/knowledge/${id}`),
  reparseKnowledge: (id: string, data: any = {}) => client.post(`/api/v1/knowledge/${id}/reparse`, data),
  cancelKnowledge: (id: string) => client.post(`/api/v1/knowledge/${id}/cancel-parse`),
  batchDeleteKnowledge: (ids: string[], kbId = '') => client.post('/api/v1/knowledge/batch-delete', { ids, kb_id: kbId }),
  moveKnowledge: (ids: string[], targetKbId: string, sourceKbId = '') => client.post('/api/v1/knowledge/move', { ids, source_kb_id: sourceKbId, target_knowledge_base_id: targetKbId }),
  listChunks: (knowledgeId: string, params: any = {}) => client.get(`/api/v1/chunks/${knowledgeId}`, { params }),
  knowledgeImage: (knowledgeId: string, imageId: string) => client.get(`/api/v1/knowledge/${knowledgeId}/images/${imageId}`, { responseType: 'blob' }),
  updateChunk: (knowledgeId: string, chunkId: string, data: any) => client.put(`/api/v1/chunks/${knowledgeId}/${chunkId}`, data),
  deleteChunk: (knowledgeId: string, chunkId: string) => client.delete(`/api/v1/chunks/${knowledgeId}/${chunkId}`),
  listTags: (kbId: string) => client.get(`/api/v1/knowledge-bases/${kbId}/tags`),
  createTag: (kbId: string, data: any) => client.post(`/api/v1/knowledge-bases/${kbId}/tags`, data),
  createSession: (data: any) => client.post('/api/v1/sessions', data),
  listSessions: (params: any = {}) => client.get('/api/v1/sessions', { params }),
  getSession: (sessionId: string) => client.get(`/api/v1/sessions/${sessionId}`),
  deleteSession: (sessionId: string) => client.delete(`/api/v1/sessions/${sessionId}`),
  deleteSessions: (ids: string[]) => client.delete('/api/v1/sessions/batch', { data: { ids } }),
  deleteAllSessions: () => client.delete('/api/v1/sessions/batch', { data: { delete_all: true } }),
  pinSession: (sessionId: string) => client.post(`/api/v1/sessions/${sessionId}/pin`),
  unpinSession: (sessionId: string) => client.delete(`/api/v1/sessions/${sessionId}/pin`),
  clearSessionMessages: (sessionId: string) => client.delete(`/api/v1/sessions/${sessionId}/messages`),
  stopSession: (sessionId: string, messageId = '') => client.post(`/api/v1/sessions/${sessionId}/stop`, { message_id: messageId }),
  loadMessages: (sessionId: string, params: any = {}) => client.get(`/api/v1/messages/${sessionId}/load`, { params: { limit: 20, ...params } }),
  chat: (sessionId: string, data: any) => client.post(`/api/v1/knowledge-chat/${sessionId}`, data, { headers: data?.request_id ? { 'X-Request-ID': String(data.request_id) } : {} }),
  agentChat: (sessionId: string, data: any) => client.post(`/api/v1/agent-chat/${sessionId}`, data, { headers: data?.request_id ? { 'X-Request-ID': String(data.request_id) } : {} }),
  listModels: () => client.get('/api/v1/models'),
  modelUsage: (params: any = {}) => client.get('/api/v1/models/usage', { params }),
  createModel: (data: any) => client.post('/api/v1/models', data),
  updateModel: (id: string, data: any) => client.put(`/api/v1/models/${id}`, data),
  deleteModel: (id: string) => client.delete(`/api/v1/models/${id}`),
  updateModelCredentials: (id: string, data: any) => client.put(`/api/v1/models/${id}/credentials`, data),
  deleteModelCredential: (id: string, field: string) => client.delete(`/api/v1/models/${id}/credentials/${field}`),
  systemInfo: () => client.get('/api/v1/system/info'),
  parserEngines: () => client.get('/api/v1/system/parser-engines'),
  storageStatus: () => client.get('/api/v1/system/storage-engine-status'),
  vectorStoreTypes: () => client.get('/api/v1/vector-stores/types'),
  webSearchProviderTypes: () => client.get('/api/v1/web-search-providers/types'),
  checkParserEngine: (data: any = {}) => client.post('/api/v1/system/parser-engines/check', data),
  checkStorageEngine: (data: any = {}) => client.post('/api/v1/system/storage-engine-check', data),
  getTenantKv: (key: string) => client.get(`/api/v1/tenants/kv/${key}`),
  updateTenantKv: (key: string, value: any) => client.put(`/api/v1/tenants/kv/${key}`, { value }),
  listMcpServices: () => client.get('/api/v1/mcp-services'),
  createMcpService: (data: any) => client.post('/api/v1/mcp-services', data),
  updateMcpService: (id: string, data: any) => client.put(`/api/v1/mcp-services/${id}`, data),
  deleteMcpService: (id: string) => client.delete(`/api/v1/mcp-services/${id}`),
  wikiPages: (kbId: string) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/pages`),
  getWikiPage: (kbId: string, slug: string) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/pages/${slug.split('/').map(encodeURIComponent).join('/')}`),
  createWikiPage: (kbId: string, data: any) => client.post(`/api/v1/knowledge-bases/${kbId}/wiki/pages`, data),
  wikiSearch: (kbId: string, params: any = {}) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/search`, { params }),
  wikiGraph: (kbId: string, params: any = {}) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/graph`, { params }),

  // RAG 评估
  ragEvalRun: (data: any = {}) => client.post('/api/v1/rag-eval/run', data),
  ragEvalQuestions: () => client.get('/api/v1/rag-eval/questions'),
  ragEvalAddQuestion: (data: any) => client.post('/api/v1/rag-eval/questions', data),
  ragEvalGenerate: (data: any = {}) => client.post('/api/v1/rag-eval/generate', data),
  ragEvalHistory: () => client.get('/api/v1/rag-eval/history'),
}
