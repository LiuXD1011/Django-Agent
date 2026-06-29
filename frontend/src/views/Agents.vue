<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const router = useRouter()
const agents = ref<any[]>([])
const knowledgeBases = ref<any[]>([])
const presets = ref<any[]>([])
const mcpServices = ref<any[]>([])
const visible = ref(false)
const activeAgent = ref<any>(null)
const keyword = ref('')
const form = ref<any>({})
const editorTab = ref('basic')

// 可用工具列表
const availableTools = [
  { id: 'thinking', name: '思考推理', group: '基础', desc: '结构化推理过程' },
  { id: 'todo_write', name: '任务规划', group: '基础', desc: '多步骤任务规划' },
  { id: 'knowledge_search', name: '知识库检索', group: 'RAG', desc: '向量+关键词混合检索' },
  { id: 'grep_chunks', name: '内容搜索', group: 'RAG', desc: '在已检索内容中搜索' },
  { id: 'list_knowledge_docs', name: '列出文档', group: 'RAG', desc: '列出知识库文档' },
  { id: 'get_document_info', name: '文档信息', group: 'RAG', desc: '获取文档元信息' },
  { id: 'database_query', name: '数据库查询', group: '数据', desc: '统计查询' },
  { id: 'web_search', name: '网络搜索', group: '网络', desc: 'DuckDuckGo 搜索' },
  { id: 'web_fetch', name: '网页获取', group: '网络', desc: '获取网页内容' },
  { id: 'read_skill', name: '读取技能', group: '技能', desc: '加载 Skill 指令' },
]

const toolGroups = computed(() => {
  const groups: Record<string, typeof availableTools> = {}
  for (const tool of availableTools) {
    if (!groups[tool.group]) groups[tool.group] = []
    groups[tool.group].push(tool)
  }
  return groups
})

const activeStats = computed(() => ({
  total: agents.value.length,
  enabled: agents.value.filter((a) => a.status !== 'disabled').length,
}))

function defaultAgent() {
  return {
    id: '',
    name: '',
    description: '',
    type: 'quick-answer',
    agent_type: 'quick-answer',
    agent_mode: 'quick-answer',
    system_prompt: '你是一个严谨的知识库问答助手。请优先基于知识库上下文回答用户问题。',
    opening_statement: '你好，我可以帮你检索知识库并整理答案。',
    suggested_questions: ['请总结这个知识库', '有哪些关键内容？'],
    kb_selection_mode: 'all',
    knowledge_base_ids: [],
    model_id: '',
    allowed_tools: ['thinking', 'knowledge_search', 'grep_chunks', 'list_knowledge_docs', 'get_document_info'],
    mcp_selection_mode: 'none',
    mcp_services: [],
    web_search_enabled: false,
    memory_enabled: true,
    rerank_enabled: true,
    temperature: 0.7,
    max_rounds: 5,
    status: 'active',
  }
}

// Agent 类型预设（只保留三个内置 Agent）
const typePresets: Record<string, Partial<ReturnType<typeof defaultAgent>>> = {
  'quick-answer': {
    agent_mode: 'quick-answer',
    system_prompt: '你是一个严谨的知识库问答助手。请优先基于知识库上下文回答用户问题。\n\n要求：\n- 优先使用上下文中的信息回答\n- 引用具体来源时注明文档标题\n- 如果上下文中没有相关信息，如实说明\n- 不要编造信息',
    allowed_tools: [],
    temperature: 0.7,
    max_rounds: 1,
  },
  'smart-reasoning': {
    agent_mode: 'smart-reasoning',
    system_prompt: `你是一个智能推理助手，能够使用工具来帮助回答问题。

## 工作流程
1. 先理解用户问题，判断是否需要检索知识库
2. 使用 knowledge_search 工具搜索相关内容
3. 使用 grep_chunks 在已检索内容中搜索特定信息
4. 使用 thinking 工具进行推理分析
5. 基于检索到的信息给出准确、有组织的回答

## 重要规则
- 优先使用知识库中的信息回答，不要依赖预训练知识
- 引用具体来源时注明文档标题
- 可以同时调用多个工具
- 如果知识库中没有相关信息，如实说明`,
    allowed_tools: ['thinking', 'knowledge_search', 'grep_chunks', 'list_knowledge_docs', 'get_document_info'],
    temperature: 0.7,
    max_rounds: 5,
  },
  'wiki-researcher': {
    agent_mode: 'smart-reasoning',
    system_prompt: `你是一个 Wiki 知识库研究员，擅长通过 Wiki 页面导航和结构化信息回答问题。

## 工作流程
1. 使用 wiki_search 搜索相关的 Wiki 页面
2. 使用 wiki_read_page 读取 Wiki 页面的完整内容
3. 使用 wiki_list_pages 列出所有可用的 Wiki 页面
4. 如果 Wiki 页面信息不够详细，使用 wiki_read_source_doc 回溯到原始文档
5. 使用 thinking 工具分析和推理
6. 综合所有信息给出结构化的回答

## 重要规则
- 优先使用 Wiki 页面中的结构化信息
- Wiki 搜索只返回摘要，必须用 wiki_read_page 读取完整内容
- 引用来源时注明 Wiki 页面标题
- 如果 Wiki 页面没有相关信息，可以回退到 knowledge_search 搜索原始文档
- 对比不同页面的信息，给出全面的回答`,
    allowed_tools: ['thinking', 'wiki_search', 'wiki_read_page', 'wiki_list_pages', 'wiki_read_source_doc', 'knowledge_search'],
    temperature: 0.7,
    max_rounds: 5,
  },
  'custom': {
    agent_mode: 'smart-reasoning',
    system_prompt: '',
    allowed_tools: ['thinking', 'knowledge_search', 'grep_chunks', 'list_knowledge_docs', 'get_document_info'],
    temperature: 0.7,
    max_rounds: 5,
  },
}

function normalizeAgent(raw: any) {
  return { ...defaultAgent(), ...(raw || {}), ...(raw?.data || {}) }
}

function openEditor(agent?: any) {
  form.value = normalizeAgent(agent)
  editorTab.value = 'basic'
  visible.value = true
}

function applyTypePreset(type: string) {
  const preset = typePresets[type]
  if (!preset) return
  form.value = { ...form.value, ...preset, type, agent_type: type }
}

async function load() {
  const [agentRes, kbRes, presetRes, mcpRes]: any[] = await Promise.all([
    api.listAgents(keyword.value ? { keyword: keyword.value } : {}),
    api.listKbs(),
    api.agentTypePresets(),
    api.listMcpServices(),
  ])
  agents.value = (agentRes.data?.items || []).map(normalizeAgent)
  knowledgeBases.value = kbRes.data?.items || []
  presets.value = presetRes.data?.items || []
  mcpServices.value = mcpRes.data?.items || []
  if (!activeAgent.value && agents.value.length) await selectAgent(agents.value[0])
}

async function selectAgent(agent: any) {
  activeAgent.value = normalizeAgent(agent)
}

async function saveAgent() {
  if (!form.value.name.trim()) {
    MessagePlugin.warning('请输入 Agent 名称')
    return
  }
  const payload = {
    ...form.value,
    suggested_questions: (form.value.suggested_questions || []).filter(Boolean),
    agent_type: form.value.type,
    knowledge_base_ids: form.value.knowledge_base_ids || [],
    knowledge_bases: form.value.knowledge_base_ids || [],
    allowed_tools: form.value.allowed_tools || [],
    mcp_selection_mode: form.value.mcp_services?.length ? 'selected' : 'none',
  }
  try {
    if (payload.id) await api.updateAgent(payload.id, payload)
    else await api.createAgent(payload)
    visible.value = false
    await load()
    MessagePlugin.success('Agent 已保存')
  } catch (e: any) {
    MessagePlugin.error(e?.response?.data?.message || '保存失败')
  }
}

async function removeAgent(agent: any) {
  if (String(agent.id).startsWith('builtin-')) {
    MessagePlugin.warning('内置 Agent 不可删除')
    return
  }
  if (!confirm(`删除 Agent"${agent.name}"？`)) return
  await api.deleteAgent(agent.id)
  if (activeAgent.value?.id === agent.id) activeAgent.value = null
  await load()
}

async function copyAgent(agent: any) {
  await api.copyAgent(agent.id)
  await load()
  MessagePlugin.success('已复制 Agent')
}

async function startChat(agent: any) {
  const kbId = agent.knowledge_base_ids?.[0] || ''
  const res: any = await api.createSession({
    title: `${agent.name} 会话`,
    agent_id: agent.id,
    knowledge_base_id: kbId,
    agent_config: agent,
  })
  router.push(`/platform/chat/${res.data.id}`)
}

function toggleTool(toolId: string) {
  const tools = form.value.allowed_tools || []
  const idx = tools.indexOf(toolId)
  if (idx >= 0) tools.splice(idx, 1)
  else tools.push(toolId)
  form.value.allowed_tools = [...tools]
}

function presetName(type: string) {
  const names: Record<string, string> = {
    'quick-answer': '快速问答',
    'smart-reasoning': '智能推理',
    'wiki-researcher': 'Wiki 问答',
    'custom': '自定义',
  }
  return names[type] || type
}

function modeLabel(mode: string) {
  return mode === 'smart-reasoning' ? '智能推理' : '快速问答'
}

onMounted(load)
</script>

<template>
  <main class="content agents-page">
    <!-- 顶部统计 -->
    <section class="archive-hero agent-hero">
      <div>
        <div class="paper-kicker">Agents</div>
        <h2>智能体编排</h2>
        <p>配置提示词、知识库范围、工具和模型，创建专业化的智能体。</p>
      </div>
      <div class="archive-stats">
        <span><strong>{{ activeStats.total }}</strong> Agent</span>
        <span><strong>{{ activeStats.enabled }}</strong> 启用</span>
      </div>
    </section>

    <!-- 工具栏 -->
    <div class="workbench-bar">
      <t-input v-model="keyword" clearable placeholder="搜索 Agent" @enter="load" />
      <t-button variant="outline" @click="load">刷新</t-button>
      <t-button theme="primary" @click="openEditor()">+ 新建 Agent</t-button>
    </div>

    <!-- 主体：列表 + 详情 -->
    <section class="agent-workbench">
      <!-- Agent 列表 -->
      <aside class="agent-list">
        <article
          v-for="agent in agents"
          :key="agent.id"
          class="agent-card"
          :class="{ active: activeAgent?.id === agent.id }"
          @click="selectAgent(agent)"
        >
          <div class="agent-avatar" :class="agent.agent_mode">{{ (agent.name || 'A').slice(0, 1) }}</div>
          <div class="agent-card-body">
            <h3>{{ agent.name }}</h3>
            <p>{{ agent.description || presetName(agent.type) }}</p>
            <div class="tag-row">
              <span class="agent-badge" :class="agent.agent_mode">{{ modeLabel(agent.agent_mode) }}</span>
              <span v-if="agent.web_search_enabled" class="agent-badge web">联网</span>
              <span v-if="agent.allowed_tools?.length" class="agent-badge tools">{{ agent.allowed_tools.length }} 工具</span>
            </div>
          </div>
        </article>
        <div v-if="!agents.length" class="empty-state">还没有 Agent</div>
      </aside>

      <!-- Agent 详情 -->
      <section v-if="activeAgent" class="agent-detail">
        <div class="panel-head">
          <div>
            <h3>{{ activeAgent.name }}</h3>
            <span>{{ activeAgent.description || '自定义智能体' }}</span>
          </div>
          <div class="card-actions inline">
            <button @click="startChat(activeAgent)">预览对话</button>
            <button @click="openEditor(activeAgent)">编辑</button>
            <button @click="copyAgent(activeAgent)">复制</button>
            <button class="danger" @click="removeAgent(activeAgent)">删除</button>
          </div>
        </div>

        <!-- 配置概览 -->
        <div class="agent-config-grid">
          <article class="setting-tile">
            <span>模式</span>
            <strong>{{ modeLabel(activeAgent.agent_mode) }}</strong>
            <p>{{ activeAgent.agent_mode === 'smart-reasoning' ? '多步推理，支持工具调用' : '直接检索并回答' }}</p>
          </article>
          <article class="setting-tile">
            <span>类型</span>
            <strong>{{ presetName(activeAgent.type) }}</strong>
          </article>
          <article class="setting-tile">
            <span>模型</span>
            <strong>{{ activeAgent.model_id || '默认模型' }}</strong>
            <p>温度 {{ activeAgent.temperature }} · 最大 {{ activeAgent.max_rounds }} 轮</p>
          </article>
          <article class="setting-tile">
            <span>知识库</span>
            <strong>{{ activeAgent.knowledge_base_ids?.length ? activeAgent.knowledge_base_ids.length + ' 个' : '全部' }}</strong>
            <p>{{ activeAgent.knowledge_base_ids?.length ? '指定知识库检索' : '检索所有知识库' }}</p>
          </article>
        </div>

        <!-- 系统提示词 -->
        <div class="agent-prompt-preview">
          <h4>系统提示词</h4>
          <pre>{{ activeAgent.system_prompt || '未配置' }}</pre>
        </div>

        <!-- 工具列表 -->
        <div class="agent-tools-preview">
          <h4>启用工具 ({{ activeAgent.allowed_tools?.length || 0 }})</h4>
          <div class="tool-tags">
            <span v-for="toolId in (activeAgent.allowed_tools || [])" :key="toolId" class="tool-tag">
              {{ availableTools.find(t => t.id === toolId)?.name || toolId }}
            </span>
            <span v-if="!activeAgent.allowed_tools?.length" class="muted">无工具</span>
          </div>
        </div>
      </section>
    </section>

    <!-- Agent 编辑器对话框 -->
    <t-dialog v-model:visible="visible" header="Agent 编排" :confirm-btn="null" width="900px">
      <div class="agent-editor">
        <!-- 编辑器标签页 -->
        <div class="editor-tabs">
          <button :class="{ active: editorTab === 'basic' }" @click="editorTab = 'basic'">基本信息</button>
          <button :class="{ active: editorTab === 'prompt' }" @click="editorTab = 'prompt'">提示词</button>
          <button :class="{ active: editorTab === 'tools' }" @click="editorTab = 'tools'">工具</button>
          <button :class="{ active: editorTab === 'retrieval' }" @click="editorTab = 'retrieval'">检索</button>
        </div>

        <!-- 基本信息 -->
        <div v-show="editorTab === 'basic'" class="editor-section">
          <div class="form-row">
            <label>名称</label>
            <input v-model="form.name" placeholder="Agent 名称" />
          </div>
          <div class="form-row">
            <label>描述</label>
            <textarea v-model="form.description" placeholder="Agent 描述" rows="2"></textarea>
          </div>
          <div class="form-row">
            <label>Agent 类型</label>
            <div class="type-presets">
              <button v-for="(preset, type) in typePresets" :key="type" class="type-preset-btn" :class="{ active: form.type === type }" @click="applyTypePreset(type as string)">
                <strong>{{ presetName(type as string) }}</strong>
                <span>{{ type === 'quick-answer' ? '单轮检索' : type === 'smart-reasoning' ? '多步推理' : type === 'wiki-researcher' ? 'Wiki 导航' : '手动配置' }}</span>
              </button>
            </div>
          </div>
          <div class="form-row">
            <label>模式</label>
            <div class="radio-group">
              <label :class="{ active: form.agent_mode === 'quick-answer' }"><input v-model="form.agent_mode" type="radio" value="quick-answer" /> 快速问答</label>
              <label :class="{ active: form.agent_mode === 'smart-reasoning' }"><input v-model="form.agent_mode" type="radio" value="smart-reasoning" /> 智能推理</label>
            </div>
          </div>
          <div class="form-row">
            <label>开场白</label>
            <input v-model="form.opening_statement" placeholder="用户进入对话时的欢迎语" />
          </div>
          <div class="form-row">
            <label>推荐问题</label>
            <div v-for="(_, idx) in form.suggested_questions" :key="idx" class="question-row">
              <input v-model="form.suggested_questions[idx]" placeholder="推荐问题" />
              <button class="icon-btn danger" @click="form.suggested_questions.splice(idx, 1)">×</button>
            </div>
            <button class="add-btn" @click="form.suggested_questions.push('')">+ 添加问题</button>
          </div>
        </div>

        <!-- 提示词 -->
        <div v-show="editorTab === 'prompt'" class="editor-section">
          <div class="form-row">
            <label>系统提示词</label>
            <p class="form-hint">定义 Agent 的角色、行为和回答风格</p>
            <textarea v-model="form.system_prompt" rows="10" placeholder="你是一个..."></textarea>
          </div>
        </div>

        <!-- 工具 -->
        <div v-show="editorTab === 'tools'" class="editor-section">
          <div class="form-row">
            <label>启用工具</label>
            <p class="form-hint">选择 Agent 可以使用的工具（智能推理模式下生效）</p>
            <div v-for="(tools, group) in toolGroups" :key="group" class="tool-group">
              <h5>{{ group }}</h5>
              <div class="tool-grid">
                <label v-for="tool in tools" :key="tool.id" class="tool-option" :class="{ active: form.allowed_tools?.includes(tool.id) }" @click="toggleTool(tool.id)">
                  <strong>{{ tool.name }}</strong>
                  <span>{{ tool.desc }}</span>
                </label>
              </div>
            </div>
          </div>
          <div class="form-row">
            <label>MCP 服务</label>
            <select v-model="form.mcp_selection_mode" class="setting-select">
              <option value="none">不使用</option>
              <option value="all">全部启用</option>
            </select>
          </div>
        </div>

        <!-- 检索配置 -->
        <div v-show="editorTab === 'retrieval'" class="editor-section">
          <div class="form-row">
            <label>知识库范围</label>
            <select v-model="form.kb_selection_mode" class="setting-select">
              <option value="all">全部知识库</option>
              <option value="selected">指定知识库</option>
            </select>
          </div>
          <div v-if="form.kb_selection_mode === 'selected'" class="form-row">
            <label>选择知识库</label>
            <div class="kb-checkbox-list">
              <label v-for="kb in knowledgeBases" :key="kb.id" class="kb-option">
                <input v-model="form.knowledge_base_ids" type="checkbox" :value="kb.id" />
                <span>{{ kb.name }}</span>
              </label>
            </div>
          </div>
          <div class="form-row">
            <label>模型</label>
            <select v-model="form.model_id" class="setting-select">
              <option value="">默认模型</option>
            </select>
          </div>
          <div class="form-row-inline">
            <label>温度 <input v-model.number="form.temperature" type="number" min="0" max="2" step="0.1" /></label>
            <label>最大轮数 <input v-model.number="form.max_rounds" type="number" min="1" max="30" /></label>
          </div>
          <div class="form-row-inline">
            <label><input v-model="form.web_search_enabled" type="checkbox" /> 联网搜索</label>
            <label><input v-model="form.rerank_enabled" type="checkbox" /> Rerank 重排序</label>
          </div>
        </div>

        <!-- 底部按钮 -->
        <div class="editor-footer">
          <button class="btn-secondary" @click="visible = false">取消</button>
          <button class="btn-primary" @click="saveAgent">保存 Agent</button>
        </div>
      </div>
    </t-dialog>
  </main>
</template>

<style scoped>
/* ── Agent 列表 ──────────────────────────────────────────────────── */
.agent-workbench {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  min-height: 500px;
}

.agent-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  max-height: 600px;
}

.agent-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.agent-card:hover { background: #f2f3f5; }
.agent-card.active { background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }

.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  color: #fff;
  background: #4f46e5;
  flex-shrink: 0;
}

.agent-avatar.smart-reasoning { background: #7c3aed; }

.agent-card-body { flex: 1; min-width: 0; }
.agent-card-body h3 { font-size: 13px; font-weight: 600; margin: 0; }
.agent-card-body p { font-size: 12px; color: #86909c; margin: 2px 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.tag-row { display: flex; gap: 4px; margin-top: 6px; }

.agent-badge {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
}

.agent-badge.quick-answer { background: #e8f5e9; color: #2e7d32; }
.agent-badge.smart-reasoning { background: #ede7f6; color: #7c3aed; }
.agent-badge.web { background: #e3f2fd; color: #1565c0; }
.agent-badge.tools { background: #f3e5f5; color: #9c27b0; }

/* ── Agent 详情 ──────────────────────────────────────────────────── */
.agent-detail {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #e8e8e8;
  padding: 20px;
  overflow-y: auto;
  max-height: 600px;
}

.agent-config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin: 16px 0;
}

.agent-prompt-preview {
  margin: 16px 0;
}

.agent-prompt-preview h4 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.agent-prompt-preview pre {
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 150px;
  overflow-y: auto;
}

.agent-tools-preview {
  margin: 16px 0;
}

.agent-tools-preview h4 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.tool-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tool-tag {
  padding: 3px 10px;
  border-radius: 6px;
  background: #f2f3f5;
  font-size: 12px;
  color: #4e5969;
}

.muted { color: #c9cdd4; font-size: 12px; }

/* ── 编辑器 ──────────────────────────────────────────────────────── */
.agent-editor {
  display: flex;
  flex-direction: column;
  gap: 0;
  max-height: 70vh;
}

.editor-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid #e8e8e8;
  margin-bottom: 16px;
}

.editor-tabs button {
  padding: 10px 20px;
  border: none;
  background: none;
  font-size: 13px;
  font-weight: 500;
  color: #86909c;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}

.editor-tabs button.active {
  color: #4f46e5;
  border-bottom-color: #4f46e5;
}

.editor-section {
  flex: 1;
  overflow-y: auto;
  padding: 0 4px;
  max-height: 50vh;
}

.form-row {
  margin-bottom: 16px;
}

.form-row label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
  margin-bottom: 6px;
}

.form-hint {
  font-size: 12px;
  color: #86909c;
  margin: 0 0 8px;
}

.form-row input,
.form-row textarea,
.form-row select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
}

.form-row textarea {
  resize: vertical;
  line-height: 1.5;
}

.form-row-inline {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.form-row-inline label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.form-row-inline input[type="number"] {
  width: 80px;
  padding: 6px 8px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
}

/* 类型预设 */
.type-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.type-preset-btn {
  padding: 8px 14px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}

.type-preset-btn:hover { border-color: #4f46e5; }
.type-preset-btn.active { border-color: #4f46e5; background: #f5f3ff; }

.type-preset-btn strong {
  display: block;
  font-size: 13px;
  color: #1d2129;
}

.type-preset-btn span {
  font-size: 11px;
  color: #86909c;
}

/* 工具选择 */
.tool-group {
  margin-bottom: 16px;
}

.tool-group h5 {
  font-size: 12px;
  font-weight: 600;
  color: #86909c;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}

.tool-option {
  padding: 8px 10px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.tool-option:hover { border-color: #4f46e5; }
.tool-option.active { border-color: #4f46e5; background: #f5f3ff; }

.tool-option strong {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #1d2129;
}

.tool-option span {
  font-size: 11px;
  color: #86909c;
}

/* 知识库选择 */
.kb-checkbox-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.kb-option {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  cursor: pointer;
}

/* 问题编辑 */
.question-row {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}

.question-row input { flex: 1; }

.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
}

.icon-btn.danger:hover { background: #fff2f0; color: #f53f3f; }

.add-btn {
  padding: 6px 12px;
  border: 1px dashed #c9cdd4;
  border-radius: 6px;
  background: transparent;
  color: #4f46e5;
  font-size: 12px;
  cursor: pointer;
}

/* 编辑器底部 */
.editor-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid #e8e8e8;
  margin-top: 16px;
}

.btn-primary {
  padding: 8px 20px;
  border: none;
  border-radius: 8px;
  background: #4f46e5;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.btn-primary:hover { background: #4338ca; }

.btn-secondary {
  padding: 8px 20px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fff;
  color: #4e5969;
  font-size: 13px;
  cursor: pointer;
}

/* 设置选择框 */
.setting-select {
  padding: 6px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  font-size: 13px;
  min-width: 180px;
}

/* Radio group */
.radio-group {
  display: flex;
  gap: 0;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  overflow: hidden;
}

.radio-group label {
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  border-right: 1px solid #e0e0e0;
}

.radio-group label:last-child { border-right: none; }
.radio-group label.active { background: #4f46e5; color: #fff; }
.radio-group input { display: none; }
</style>
