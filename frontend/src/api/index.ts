import client from './client'

function authHeaders(extra: Record<string, string> = {}) {
  const token = localStorage.getItem('personal_kb_token') || localStorage.getItem('weknora_token')
  const tenant = localStorage.getItem('personal_kb_selected_tenant_id') || localStorage.getItem('weknora_selected_tenant_id')
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
  const maxRetries = 2

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ ...data, stream: true, channel: 'web' }),
        signal,
      })
      if (!response.ok || !response.body) throw new Error(`stream request failed: ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let gotCompleteEvent = false
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
            if (line.startsWith('data:')) dataLine += line.slice(5).trim()
          }
          if (!dataLine) continue
          try {
            const parsed = JSON.parse(dataLine)
            onEvent(event, parsed)
            if (event === 'done' || parsed.response_type === 'complete') gotCompleteEvent = true
          } catch {
            onEvent(event, dataLine)
          }
        }
      }
      // 成功完成，不需要重试
      return
    } catch (err: any) {
      if (err?.name === 'AbortError') throw err
      if (attempt < maxRetries) {
        // 等待后重试
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1)))
        continue
      }
      throw err
    }
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
  updateKnowledge: (id: string, data: any) => client.put(`/api/v1/knowledge/${id}`, data),
  reparseKnowledge: (id: string, data: any = {}) => client.post(`/api/v1/knowledge/${id}/reparse`, data),
  cancelKnowledge: (id: string) => client.post(`/api/v1/knowledge/${id}/cancel-parse`),
  batchDeleteKnowledge: (ids: string[], kbId = '') => client.post('/api/v1/knowledge/batch-delete', { ids, kb_id: kbId }),
  moveKnowledge: (ids: string[], targetKbId: string, sourceKbId = '') => client.post('/api/v1/knowledge/move', { ids, source_kb_id: sourceKbId, target_knowledge_base_id: targetKbId }),
  previewKnowledgeUrl: (id: string) => `/api/v1/knowledge/${id}/preview`,
  downloadKnowledgeUrl: (id: string) => `/api/v1/knowledge/${id}/download`,
  listChunks: (knowledgeId: string, params: any = {}) => client.get(`/api/v1/chunks/${knowledgeId}`, { params }),
  updateChunk: (knowledgeId: string, chunkId: string, data: any) => client.put(`/api/v1/chunks/${knowledgeId}/${chunkId}`, data),
  deleteChunk: (knowledgeId: string, chunkId: string) => client.delete(`/api/v1/chunks/${knowledgeId}/${chunkId}`),
  listTags: (kbId: string) => client.get(`/api/v1/knowledge-bases/${kbId}/tags`),
  createTag: (kbId: string, data: any) => client.post(`/api/v1/knowledge-bases/${kbId}/tags`, data),
  updateTag: (kbId: string, tagId: string, data: any) => client.put(`/api/v1/knowledge-bases/${kbId}/tags/${tagId}`, data),
  deleteTag: (kbId: string, tagId: string) => client.delete(`/api/v1/knowledge-bases/${kbId}/tags/${tagId}`),
  createSession: (data: any) => client.post('/api/v1/sessions', data),
  listSessions: (params: any = {}) => client.get('/api/v1/sessions', { params }),
  getSession: (sessionId: string) => client.get(`/api/v1/sessions/${sessionId}`),
  updateSession: (sessionId: string, data: any) => client.put(`/api/v1/sessions/${sessionId}`, data),
  deleteSession: (sessionId: string) => client.delete(`/api/v1/sessions/${sessionId}`),
  deleteSessions: (ids: string[]) => client.delete('/api/v1/sessions/batch', { data: { ids } }),
  deleteAllSessions: () => client.delete('/api/v1/sessions/batch', { data: { delete_all: true } }),
  pinSession: (sessionId: string) => client.post(`/api/v1/sessions/${sessionId}/pin`),
  unpinSession: (sessionId: string) => client.delete(`/api/v1/sessions/${sessionId}/pin`),
  clearSessionMessages: (sessionId: string) => client.delete(`/api/v1/sessions/${sessionId}/messages`),
  stopSession: (sessionId: string, messageId = '') => client.post(`/api/v1/sessions/${sessionId}/stop`, { message_id: messageId }),
  loadMessages: (sessionId: string, params: any = {}) => client.get(`/api/v1/messages/${sessionId}/load`, { params: { limit: 20, ...params } }),
  chat: (sessionId: string, data: any) => client.post(`/api/v1/knowledge-chat/${sessionId}`, data),
  agentChat: (sessionId: string, data: any) => client.post(`/api/v1/agent-chat/${sessionId}`, data),
  suggestedQuestions: () => client.get('/api/v1/agents/builtin-quick-answer/suggested-questions'),
  listModels: () => client.get('/api/v1/models'),
  modelUsage: (params: any = {}) => client.get('/api/v1/models/usage', { params }),
  createModel: (data: any) => client.post('/api/v1/models', data),
  updateModel: (id: string, data: any) => client.put(`/api/v1/models/${id}`, data),
  deleteModel: (id: string) => client.delete(`/api/v1/models/${id}`),
  updateModelCredentials: (id: string, data: any) => client.put(`/api/v1/models/${id}/credentials`, data),
  deleteModelCredential: (id: string, field: string) => client.delete(`/api/v1/models/${id}/credentials/${field}`),
  modelProviders: () => client.get('/api/v1/models/providers'),
  systemInfo: () => client.get('/api/v1/system/info'),
  parserEngines: () => client.get('/api/v1/system/parser-engines'),
  storageStatus: () => client.get('/api/v1/system/storage-engine-status'),
  vectorStoreTypes: () => client.get('/api/v1/vector-stores/types'),
  webSearchProviderTypes: () => client.get('/api/v1/web-search-providers/types'),
  checkParserEngine: (data: any = {}) => client.post('/api/v1/system/parser-engines/check', data),
  checkStorageEngine: (data: any = {}) => client.post('/api/v1/system/storage-engine-check', data),
  getTenantKv: (key: string) => client.get(`/api/v1/tenants/kv/${key}`),
  updateTenantKv: (key: string, value: any) => client.put(`/api/v1/tenants/kv/${key}`, { value }),
  listAgents: (params: any = {}) => client.get('/api/v1/agents', { params }),
  createAgent: (data: any) => client.post('/api/v1/agents', data),
  getAgent: (id: string) => client.get(`/api/v1/agents/${id}`),
  updateAgent: (id: string, data: any) => client.put(`/api/v1/agents/${id}`, data),
  deleteAgent: (id: string) => client.delete(`/api/v1/agents/${id}`),
  copyAgent: (id: string) => client.post(`/api/v1/agents/${id}/copy`),
  agentPlaceholders: () => client.get('/api/v1/agents/placeholders'),
  agentTypePresets: () => client.get('/api/v1/agents/type-presets'),
  agentSuggestedQuestions: (id: string) => client.get(`/api/v1/agents/${id}/suggested-questions`),
  listEmbedChannels: (agentId: string) => client.get(`/api/v1/agents/${agentId}/embed-channels`),
  createEmbedChannel: (agentId: string, data: any) => client.post(`/api/v1/agents/${agentId}/embed-channels`, data),
  rotateEmbedToken: (id: string) => client.post(`/api/v1/embed-channels/${id}/rotate-token`),
  previewEmbedSession: (id: string) => client.post(`/api/v1/embed-channels/${id}/preview-session`),
  listImChannels: (agentId: string) => client.get(`/api/v1/agents/${agentId}/im-channels`),
  createImChannel: (agentId: string, data: any) => client.post(`/api/v1/agents/${agentId}/im-channels`, data),
  toggleImChannel: (id: string) => client.post(`/api/v1/im-channels/${id}/toggle`),
  listMcpServices: () => client.get('/api/v1/mcp-services'),
  createMcpService: (data: any) => client.post('/api/v1/mcp-services', data),
  updateMcpService: (id: string, data: any) => client.put(`/api/v1/mcp-services/${id}`, data),
  deleteMcpService: (id: string) => client.delete(`/api/v1/mcp-services/${id}`),
  wikiPages: (kbId: string) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/pages`),
  getWikiPage: (kbId: string, slug: string) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/pages/${slug.split('/').map(encodeURIComponent).join('/')}`),
  createWikiPage: (kbId: string, data: any) => client.post(`/api/v1/knowledge-bases/${kbId}/wiki/pages`, data),
  wikiSearch: (kbId: string, params: any = {}) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/search`, { params }),
  wikiGraph: (kbId: string, params: any = {}) => client.get(`/api/v1/knowledge-bases/${kbId}/wiki/graph`, { params }),
}
