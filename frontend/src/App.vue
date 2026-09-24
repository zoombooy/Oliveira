<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound, Collection, Document as DocumentIcon, Fold, FullScreen, Grid, HomeFilled,
  Lock, Message, Operation, Plus, Search, Setting, Tickets, UserFilled, User as UserIcon,
} from '@element-plus/icons-vue'
import { api, clearToken, isLoggedIn, login, register, type Conversation, type Document, type Fact, type Memory, type Message as ChatMessage, type Project, type Provider, type ReviewItem, type Run, type User, type Workspace, type SearchResult } from './api'

type Panel = 'chat' | 'documents' | 'search' | 'facts' | 'timeline' | 'runs' | 'memories' | 'settings'

const loggedIn = ref(isLoggedIn())
const authMode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const displayName = ref('')
const authBusy = ref(false)
const authError = ref('')
const user = ref<User | null>(null)
const workspaces = ref<Workspace[]>([])
const workspaceId = ref('')
const projects = ref<Project[]>([])
const projectId = ref('')
const collapsed = ref(false)
const panel = ref<Panel>('chat')
const loading = ref(false)
const error = ref('')
const documents = ref<Document[]>([])
const conversations = ref<Conversation[]>([])
const conversationId = ref('')
const messages = ref<ChatMessage[]>([])
const composer = ref('')
const sending = ref(false)
const currentRun = ref<Run | null>(null)
const runs = ref<Run[]>([])
const searchQuery = ref('')
const searchResults = ref<SearchResult[]>([])
const facts = ref<Fact[]>([])
const reviewItems = ref<ReviewItem[]>([])
const memories = ref<Memory[]>([])
const providers = ref<Provider[]>([])
const selectedCitation = ref<SearchResult | null>(null)
const uploadInput = ref<HTMLInputElement | null>(null)
const newProjectName = ref('')
const newMemoryKey = ref('')
const newMemoryValue = ref('')
const providerName = ref('')
const providerBaseUrl = ref('http://host.docker.internal:11434/v1')
const providerChatModel = ref('')
const providerEmbeddingModel = ref('')
const providerApiKey = ref('')

const currentWorkspace = computed(() => workspaces.value.find(item => item.id === workspaceId.value))
const currentProject = computed(() => projects.value.find(item => item.id === projectId.value))
const currentConversation = computed(() => conversations.value.find(item => item.id === conversationId.value))
const runCitations = computed(() => (currentRun.value?.output?.citations as SearchResult[] | undefined) || [])
const panelTitle = computed(() => ({ chat: '对话', documents: '知识库', search: '检索', facts: '事实审核', timeline: '时间线', runs: '运行记录', memories: '用户记忆', settings: '工作空间设置' }[panel.value]))

async function boot() {
  if (!loggedIn.value) return
  try {
    user.value = await api<User>('/api/v1/auth/me')
    workspaces.value = await api<Workspace[]>('/api/v1/workspaces')
    workspaceId.value = workspaces.value[0]?.id || ''
    await loadWorkspace()
  } catch (caught) { handleError(caught) }
}

async function loadWorkspace() {
  if (!workspaceId.value) return
  projects.value = await api<Project[]>(`/api/v1/projects?workspace_id=${workspaceId.value}`)
  providers.value = await api<Provider[]>(`/api/v1/workspaces/${workspaceId.value}/providers`)
  projectId.value = projects.value[0]?.id || ''
  await loadProject()
}

async function loadProject() {
  if (!projectId.value) return
  loading.value = true
  try {
    const [docs, chats, factList, reviews, runList] = await Promise.all([
      api<Document[]>(`/api/v1/projects/${projectId.value}/documents`),
      api<Conversation[]>(`/api/v1/projects/${projectId.value}/conversations`),
      api<Fact[]>(`/api/v1/projects/${projectId.value}/facts`),
      api<ReviewItem[]>(`/api/v1/projects/${projectId.value}/review-items`),
      api<Run[]>(`/api/v1/runs?project_id=${projectId.value}`),
    ])
    documents.value = docs; conversations.value = chats; facts.value = factList; reviewItems.value = reviews; runs.value = runList
    conversationId.value = conversations.value[0]?.id || ''
    if (conversationId.value) messages.value = await api<ChatMessage[]>(`/api/v1/conversations/${conversationId.value}/messages`)
  } catch (caught) { handleError(caught) } finally { loading.value = false }
}

async function submitAuth() {
  authBusy.value = true; authError.value = ''
  try {
    user.value = authMode.value === 'login'
      ? await login({ username: username.value, password: password.value })
      : await register({ username: username.value, password: password.value, display_name: displayName.value })
    loggedIn.value = true
    await boot()
  } catch (caught) { authError.value = caught instanceof Error ? caught.message : '登录失败' } finally { authBusy.value = false }
}

function logout() { clearToken(); loggedIn.value = false; user.value = null; workspaces.value = []; projects.value = [] }
function handleError(caught: unknown) { error.value = caught instanceof Error ? caught.message : '操作失败'; ElMessage.error(error.value) }

async function createConversation() {
  if (!projectId.value) return
  try {
    const created = await api<Conversation>(`/api/v1/projects/${projectId.value}/conversations`, { method: 'POST', body: JSON.stringify({ title: '新对话' }) })
    conversations.value.unshift(created); conversationId.value = created.id; messages.value = []; panel.value = 'chat'
  } catch (caught) { handleError(caught) }
}

async function selectConversation(id: string) {
  conversationId.value = id
  panel.value = 'chat'
  try { messages.value = await api<ChatMessage[]>(`/api/v1/conversations/${id}/messages`) } catch (caught) { handleError(caught) }
}

async function sendMessage() {
  if (!conversationId.value || !composer.value.trim() || sending.value) return
  const content = composer.value.trim(); composer.value = ''; sending.value = true
  try {
    const accepted = await api<{ run_id: string; user_message_id: string; status: string }>(`/api/v1/conversations/${conversationId.value}/messages`, { method: 'POST', body: JSON.stringify({ content }) })
    messages.value.push({ id: accepted.user_message_id, role: 'user', content, created_at: new Date().toISOString() })
    currentRun.value = await pollRun(accepted.run_id)
    messages.value = await api<ChatMessage[]>(`/api/v1/conversations/${conversationId.value}/messages`)
    await loadProject()
  } catch (caught) { handleError(caught) } finally { sending.value = false }
}

async function pollRun(runId: string) {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const run = await api<Run>(`/api/v1/runs/${runId}`)
    currentRun.value = run
    if (['completed', 'failed', 'cancelled'].includes(run.status)) return run
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  throw new Error('Run 等待超时，请在运行记录中查看状态')
}

async function search() {
  if (!projectId.value || !searchQuery.value.trim()) return
  try { const result = await api<{ results: SearchResult[] }>(`/api/v1/projects/${projectId.value}/search`, { method: 'POST', body: JSON.stringify({ query: searchQuery.value, top_k: 8 }) }); searchResults.value = result.results } catch (caught) { handleError(caught) }
}

async function uploadDocument(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !projectId.value) return
  const form = new FormData(); form.append('file', file)
  try { await api<Document>(`/api/v1/projects/${projectId.value}/documents`, { method: 'POST', body: form }); ElMessage.success('文档已入库'); documents.value = await api<Document[]>(`/api/v1/projects/${projectId.value}/documents`) } catch (caught) { handleError(caught) } finally { if (uploadInput.value) uploadInput.value.value = '' }
}

async function createProject() {
  if (!newProjectName.value.trim() || !workspaceId.value) return
  try { await api<Project>('/api/v1/projects', { method: 'POST', body: JSON.stringify({ name: newProjectName.value, workspace_id: workspaceId.value }) }); newProjectName.value = ''; await loadWorkspace(); ElMessage.success('项目已创建') } catch (caught) { handleError(caught) }
}

async function loadFacts() { if (projectId.value) { facts.value = await api<Fact[]>(`/api/v1/projects/${projectId.value}/facts`); reviewItems.value = await api<ReviewItem[]>(`/api/v1/projects/${projectId.value}/review-items`) } }
async function review(item: ReviewItem, action: 'approve' | 'reject') { try { await api(`/api/v1/review-items/${item.id}/${action}`, { method: 'POST', body: JSON.stringify({ resolution: action === 'approve' ? 'Web 审核通过' : 'Web 审核拒绝' }) }); await loadFacts(); ElMessage.success('审核状态已更新') } catch (caught) { handleError(caught) } }
async function loadMemories() { memories.value = await api<Memory[]>('/api/v1/users/me/memories') }
async function createMemory() { if (!newMemoryKey.value.trim() || !newMemoryValue.value.trim()) return; try { await api('/api/v1/users/me/memories', { method: 'POST', body: JSON.stringify({ key: newMemoryKey.value, value: newMemoryValue.value }) }); newMemoryKey.value = ''; newMemoryValue.value = ''; await loadMemories() } catch (caught) { handleError(caught) } }
async function retractMemory(memory: Memory) { try { await api(`/api/v1/users/me/memories/${memory.id}`, { method: 'DELETE' }); await loadMemories() } catch (caught) { handleError(caught) } }
async function createProvider() { if (!workspaceId.value || !providerName.value.trim() || !providerBaseUrl.value.trim() || !providerChatModel.value.trim()) return; try { await api<Provider>(`/api/v1/workspaces/${workspaceId.value}/providers`, { method: 'POST', body: JSON.stringify({ name: providerName.value, base_url: providerBaseUrl.value, chat_model: providerChatModel.value, embedding_model: providerEmbeddingModel.value, api_key: providerApiKey.value }) }); providerName.value = ''; providerChatModel.value = ''; providerEmbeddingModel.value = ''; providerApiKey.value = ''; providers.value = await api<Provider[]>(`/api/v1/workspaces/${workspaceId.value}/providers`); ElMessage.success('Provider 已保存') } catch (caught) { handleError(caught) } }
async function deleteProjectDraft() { if (newProjectName.value) { await ElMessageBox.confirm('仅清空当前输入？', '提示').catch(() => undefined); newProjectName.value = '' } }

watch(workspaceId, () => { if (loggedIn.value) loadWorkspace() })
watch(projectId, () => { if (loggedIn.value) loadProject() })
watch(panel, (value) => { if (value === 'memories' && loggedIn.value) loadMemories() })
onMounted(boot)
</script>

<template>
  <div v-if="!loggedIn" class="auth-scene">
    <div class="auth-network" aria-hidden="true">
      <svg viewBox="0 0 1600 900" preserveAspectRatio="none">
        <g class="network-lines">
          <path d="M-40 140 C210 42 370 206 590 118 S1010 35 1660 166" />
          <path d="M-80 390 C190 250 410 470 710 350 S1190 250 1680 388" />
          <path d="M-50 700 C230 590 400 790 680 630 S1170 540 1650 700" />
          <path d="M160 940 C390 700 520 760 740 920 S1150 1010 1410 730" />
          <path d="M170 -40 C120 180 370 250 270 520 S220 780 370 940" />
          <path d="M610 -40 C520 180 790 240 650 480 S610 760 790 940" />
          <path d="M1010 -40 C900 180 1120 320 990 520 S1090 760 1190 940" />
          <path d="M1390 -40 C1250 150 1510 310 1350 510 S1410 750 1570 940" />
          <path d="M-80 235 C240 390 420 130 730 240 S1150 460 1670 240" />
          <path d="M-80 560 C260 420 480 650 720 510 S1160 380 1670 570" />
        </g>
        <g class="network-nodes">
          <circle cx="142" cy="141" r="3" /><circle cx="270" cy="520" r="3" /><circle cx="370" cy="206" r="3" />
          <circle cx="520" cy="238" r="3" /><circle cx="590" cy="118" r="3" /><circle cx="650" cy="480" r="3" />
          <circle cx="710" cy="350" r="3" /><circle cx="790" cy="240" r="3" /><circle cx="990" cy="520" r="3" />
          <circle cx="1010" cy="165" r="3" /><circle cx="1120" cy="320" r="3" /><circle cx="1190" cy="700" r="3" />
          <circle cx="1350" cy="510" r="3" /><circle cx="1410" cy="730" r="3" /><circle cx="1510" cy="310" r="3" />
          <circle cx="235" cy="390" r="3" /><circle cx="480" cy="650" r="3" /><circle cx="730" cy="240" r="3" />
        </g>
      </svg>
    </div>
    <div class="auth-ambient auth-ambient-left" />
    <div class="auth-ambient auth-ambient-right" />
    <main class="auth-center">
      <div class="auth-heading">
        <div class="auth-brand"><span class="brand-dot" /> Oliveira</div>
        <p class="auth-tagline">让知识有迹可循 · 让答案有据可依</p>
        <h1>让知识保留<br /><em>来龙去脉。</em></h1>
        <p>可追溯知识库与智能检索平台</p>
      </div>
      <section class="auth-card" aria-label="登录 Oliveira">
        <div class="auth-tabs" role="tablist" aria-label="账户操作">
          <button type="button" role="tab" :aria-selected="authMode === 'login'" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">登录</button>
          <button type="button" role="tab" :aria-selected="authMode === 'register'" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">注册</button>
        </div>
        <form class="auth-form" @submit.prevent="submitAuth">
          <label>邮箱或用户名<input v-model="username" autocomplete="username" placeholder="邮箱或用户名" required /></label>
          <label v-if="authMode === 'register'">显示名称<input v-model="displayName" autocomplete="name" placeholder="你的名字" required /></label>
          <label>密码<input v-model="password" type="password" autocomplete="current-password" placeholder="至少 8 位字符" minlength="8" required /></label>
          <p v-if="authError" class="form-error" role="alert">{{ authError }}</p>
          <button class="primary-button auth-submit" type="submit" :disabled="authBusy">{{ authBusy ? '正在进入…' : authMode === 'login' ? '登录' : '创建空间' }}<span>↗</span></button>
        </form>
        <p class="auth-footnote"><Lock :size="14" /> 你的资料只属于你的工作空间</p>
      </section>
      <p class="auth-consent">继续即表示你同意使用条款，并已知悉隐私政策。</p>
    </main>
    <div class="auth-footer"><span>OLIVEIRA / 2026</span><span>TRACEABLE INTELLIGENCE</span></div>
  </div>

  <div v-else class="app-shell" :class="{ 'is-collapsed': collapsed }">
    <aside class="sidebar">
      <div class="sidebar-top">
        <div class="brand-mark compact"><span class="brand-dot" /><span v-if="!collapsed">Oliveira</span></div>
        <button class="icon-button sidebar-toggle" aria-label="折叠侧栏" @click="collapsed = !collapsed"><Fold v-if="!collapsed" :size="17" /><FullScreen v-else :size="17" /></button>
      </div>
      <div class="workspace-picker" :title="currentWorkspace?.name">
        <div class="picker-label"><Grid :size="14" /><span v-if="!collapsed">工作空间</span></div>
        <div v-if="!collapsed" class="select-shell"><select v-model="workspaceId" aria-label="选择工作空间"><option v-for="workspace in workspaces" :key="workspace.id" :value="workspace.id">{{ workspace.name }}</option></select><span>⌄</span></div>
      </div>
      <div v-if="!collapsed" class="project-picker">
        <div class="project-picker-heading"><span>当前项目</span><button class="tiny-button" aria-label="新建项目" title="新建项目" @click="panel = 'settings'"><Plus :size="15" /></button></div>
        <div class="select-shell project-select"><select v-model="projectId" aria-label="选择项目"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select><span>⌄</span></div>
      </div>
      <nav class="primary-nav" aria-label="主导航">
        <div v-if="!collapsed" class="nav-section-title">工作台</div>
        <button :title="collapsed ? '对话' : undefined" :class="{ active: panel === 'chat' }" @click="panel = 'chat'"><span class="nav-icon"><ChatDotRound :size="17" /></span><span v-if="!collapsed">对话</span><b v-if="!collapsed && conversations.length">{{ conversations.length }}</b></button>
        <button :title="collapsed ? '知识库' : undefined" :class="{ active: panel === 'documents' }" @click="panel = 'documents'"><span class="nav-icon"><Collection :size="17" /></span><span v-if="!collapsed">知识库</span><b v-if="!collapsed">{{ documents.length }}</b></button>
        <button :title="collapsed ? '检索' : undefined" :class="{ active: panel === 'search' }" @click="panel = 'search'"><span class="nav-icon"><Search :size="17" /></span><span v-if="!collapsed">检索</span></button>
        <div v-if="!collapsed" class="nav-section-title secondary">知识治理</div>
        <button :title="collapsed ? '事实审核' : undefined" :class="{ active: panel === 'facts' }" @click="panel = 'facts'"><span class="nav-icon"><Tickets :size="17" /></span><span v-if="!collapsed">事实审核</span><b v-if="!collapsed && reviewItems.length" class="warning-count">{{ reviewItems.length }}</b></button>
        <button :title="collapsed ? '时间线' : undefined" :class="{ active: panel === 'timeline' }" @click="panel = 'timeline'"><span class="nav-icon"><Operation :size="17" /></span><span v-if="!collapsed">时间线</span></button>
        <button :title="collapsed ? '运行记录' : undefined" :class="{ active: panel === 'runs' }" @click="panel = 'runs'"><span class="nav-icon"><HomeFilled :size="17" /></span><span v-if="!collapsed">运行记录</span></button>
      </nav>
      <div v-if="!collapsed" class="recent-heading"><span>最近对话</span><button class="tiny-button" aria-label="新对话" title="新对话" @click="createConversation"><Plus :size="15" /></button></div>
      <div v-if="!collapsed" class="conversation-list"><button v-for="conversation in conversations.slice(0, 6)" :key="conversation.id" :class="{ active: conversation.id === conversationId }" @click="selectConversation(conversation.id)"><Message :size="14" /><span>{{ conversation.title }}</span></button><div v-if="!conversations.length" class="empty-side">还没有对话</div></div>
      <div class="sidebar-bottom">
        <button :title="collapsed ? '我的记忆' : undefined" :class="{ active: panel === 'memories' }" @click="panel = 'memories'"><span class="nav-icon"><UserFilled :size="17" /></span><span v-if="!collapsed">我的记忆</span></button>
        <button :title="collapsed ? '设置' : undefined" :class="{ active: panel === 'settings' }" @click="panel = 'settings'"><span class="nav-icon"><Setting :size="17" /></span><span v-if="!collapsed">设置</span></button>
        <div class="user-chip" v-if="!collapsed"><span class="user-avatar">{{ (user?.display_name || 'U').slice(0, 1).toUpperCase() }}</span><div><strong>{{ user?.display_name || 'Oliveira 用户' }}</strong><small>{{ user?.username }}</small></div><button aria-label="退出登录" title="退出登录" @click="logout">↗</button></div>
      </div>
    </aside>

    <main class="main-stage">
      <header class="topbar">
        <div class="topbar-heading"><div class="breadcrumbs"><span>{{ currentWorkspace?.name || '工作空间' }}</span><i>/</i><strong>{{ currentProject?.name || '未选择项目' }}</strong></div><div class="topbar-title-row"><h2>{{ panelTitle }}</h2><span v-if="currentProject" class="context-chip">项目空间</span></div></div>
        <div class="topbar-actions"><span class="sync-status"><i /> 数据源已同步</span><button class="quiet-action" aria-label="新建对话" @click="createConversation"><Plus :size="16" /><span>新对话</span></button></div>
      </header>
      <div v-if="error" class="error-banner">{{ error }}<button @click="error = ''">×</button></div>
      <section v-if="panel === 'chat'" class="content chat-content">
        <div v-if="!currentConversation" class="welcome-card"><span class="welcome-orbit"><span /></span><p class="eyebrow">YOUR KNOWLEDGE, IN CONTEXT</p><h1>从一个问题开始。</h1><p>上传资料，Oliveira 会在保留来源和时间的前提下，帮你整理、检索与回答。</p><button class="primary-button small" @click="panel = 'documents'">先添加知识 <span>↗</span></button></div>
        <template v-else><div class="message-stream"><div v-if="!messages.length" class="empty-state"><ChatDotRound :size="30" /><h3>这是一段新的对话</h3><p>向你的知识库提问，答案会带回可展开的证据。</p></div><article v-for="message in messages" :key="message.id" class="message-row" :class="message.role"><div class="avatar">{{ message.role === 'user' ? (user?.display_name || 'U').slice(0, 1) : 'O' }}</div><div class="message-body"><div class="message-meta">{{ message.role === 'user' ? '你' : 'Oliveira' }}<span>{{ new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</span></div><div class="message-text">{{ message.content }}</div><div v-if="message.role === 'assistant' && runCitations.length" class="citation-strip"><button v-for="(citation, index) in runCitations.slice(0, 3)" :key="index" @click="selectedCitation = citation">来源 {{ index + 1 }} · {{ citation.document_title }}</button></div></div></article><div v-if="sending" class="thinking"><span /><span /><span />正在检索并核对来源…</div></div><form class="composer" @submit.prevent="sendMessage"><textarea v-model="composer" :disabled="sending" placeholder="问问你的知识库…" rows="1" @keydown.enter.exact.prevent="sendMessage" /><button type="submit" class="send-button" :disabled="sending || !composer.trim()" aria-label="发送"><span>↗</span></button></form></template>
      </section>
      <section v-else-if="panel === 'documents'" class="content"><div class="section-heading"><div><p class="eyebrow">SOURCE LIBRARY</p><h1>知识库</h1><p>原始文档、版本和索引状态都保留在这里。</p></div><button class="primary-button small" @click="uploadInput?.click()"><Plus :size="16" /> 上传文档</button><input ref="uploadInput" hidden type="file" accept=".pdf,.docx,.md,.markdown,.txt" @change="uploadDocument" /></div><div class="metric-row"><div><span>文档</span><strong>{{ documents.length }}</strong></div><div><span>已索引</span><strong>{{ documents.filter(item => item.index_status === 'completed').length }}</strong></div><div><span>待处理</span><strong>{{ documents.filter(item => item.index_status !== 'completed').length }}</strong></div></div><div class="data-card"><div v-for="document in documents" :key="document.id" class="document-row"><div class="file-icon"><DocumentIcon :size="19" /></div><div class="row-main"><strong>{{ document.title }}</strong><span>版本 {{ document.version_no }} · {{ document.chunk_count }} 个知识块</span></div><span class="status-pill" :class="document.index_status">{{ document.index_status === 'completed' ? '已索引' : document.index_status === 'unavailable' ? '待 Embedding' : document.index_status }}</span><span class="row-date">{{ new Date(document.created_at).toLocaleDateString() }}</span></div><div v-if="!documents.length" class="empty-state compact"><DocumentIcon :size="25" /><p>上传第一份资料，开始建立可追溯知识库。</p></div></div></section>
      <section v-else-if="panel === 'search'" class="content"><div class="section-heading"><div><p class="eyebrow">HYBRID RETRIEVAL</p><h1>检索</h1><p>向量与关键词结果合并，并保留各自的评分。</p></div></div><form class="search-bar" @submit.prevent="search"><Search :size="18" /><input v-model="searchQuery" placeholder="搜索文档内容、项目名称或术语…" /><button type="submit">检索</button></form><div class="result-list"><button v-for="result in searchResults" :key="result.chunk_id" class="result-card" @click="selectedCitation = result"><div class="result-top"><span>{{ result.document_title }}</span><small>{{ result.methods.join(' + ') }} · {{ result.final_score.toFixed(2) }}</small></div><p>{{ result.snippet }}</p><div class="result-location">版本 {{ result.document_version_id.slice(0, 8) }} · {{ result.page_number ? `第 ${result.page_number} 页` : '段落定位' }}</div></button><div v-if="!searchResults.length" class="empty-state"><Search :size="30" /><h3>输入一个问题或关键词</h3><p>结果会显示来源、定位和混合分数。</p></div></div></section>
      <section v-else-if="panel === 'facts'" class="content"><div class="section-heading"><div><p class="eyebrow">REVIEW QUEUE</p><h1>事实审核</h1><p>自动抽取的事实默认保持 pending，确认后才会进入回答上下文。</p></div><el-button plain @click="loadFacts">刷新</el-button></div><div class="review-layout"><div class="data-card review-card"><div v-for="item in reviewItems" :key="item.id" class="review-row"><div class="review-mark">待</div><div class="row-main"><strong>{{ facts.find(fact => fact.id === item.ref_id)?.subject_text }} · {{ facts.find(fact => fact.id === item.ref_id)?.predicate }}</strong><span>{{ facts.find(fact => fact.id === item.ref_id)?.object_text }}</span><small>{{ item.reason }}</small></div><button class="approve" @click="review(item, 'approve')">通过</button><button class="reject" @click="review(item, 'reject')">拒绝</button></div><div v-if="!reviewItems.length" class="empty-state compact"><Tickets :size="25" /><p>审核队列为空。</p></div></div><aside class="side-note"><h3>审核原则</h3><p>每条事实都必须能回到至少一个文档块。Oliveira 不会用新事实覆盖旧事实，冲突会单独保留。</p><span>当前事实 {{ facts.length }} 条</span></aside></div></section>
      <section v-else-if="panel === 'timeline'" class="content"><div class="section-heading"><div><p class="eyebrow">BITEMPORAL MEMORY</p><h1>时间线</h1><p>同时查看事实的业务有效时间与系统记录时间。</p></div></div><div class="timeline"> <div v-for="fact in facts" :key="fact.id" class="timeline-item"><span class="timeline-dot" /><div><div class="timeline-date">{{ fact.valid_from ? new Date(fact.valid_from).toLocaleDateString() : '未声明业务时间' }} <span>记录于 {{ fact.recorded_at ? new Date(fact.recorded_at).toLocaleDateString() : '—' }}</span></div><h3>{{ fact.subject_text }} <em>{{ fact.predicate }}</em> {{ fact.object_text }}</h3><span class="status-pill" :class="fact.status">{{ fact.status }}</span></div></div><div v-if="!facts.length" class="empty-state"><Operation :size="30" /><h3>还没有可回放的事实</h3><p>完成一次事实抽取并审核后，时间线会在这里出现。</p></div></div></section>
      <section v-else-if="panel === 'runs'" class="content"><div class="section-heading"><div><p class="eyebrow">AUDITABLE EXECUTION</p><h1>运行记录</h1><p>每一次 Agent、索引和抽取任务都可以回放。</p></div></div><div class="data-card"><div v-for="run in runs" :key="run.id" class="document-row"><div class="run-status" :class="run.status" /><div class="row-main"><strong>{{ run.kind === 'chat' ? '知识对话' : run.kind }}</strong><span>{{ run.id.slice(0, 14) }} · {{ new Date(run.created_at).toLocaleString() }}</span></div><span class="status-pill" :class="run.status">{{ run.status }}</span><span v-if="run.error" class="row-error">{{ run.error }}</span></div><div v-if="!runs.length" class="empty-state compact"><Operation :size="25" /><p>完成一次对话后，这里会显示 Run 事件。</p></div></div></section>
      <section v-else-if="panel === 'memories'" class="content"><div class="section-heading"><div><p class="eyebrow">STRUCTURED MEMORY</p><h1>我的记忆</h1><p>只有你明确保存的内容才会进入长期记忆；删除采用撤回而不是抹除历史。</p></div></div><div class="memory-create"><input v-model="newMemoryKey" placeholder="键，例如：回答偏好" /><input v-model="newMemoryValue" placeholder="值，例如：请使用中文和简洁小节" /><button class="primary-button small" @click="createMemory">保存记忆</button></div><div class="data-card"><div v-for="memory in memories" :key="memory.id" class="document-row"><div class="file-icon"><UserIcon :size="18" /></div><div class="row-main"><strong>{{ memory.key }}</strong><span>{{ memory.value }}</span></div><span class="status-pill" :class="memory.status">{{ memory.status === 'active' ? '使用中' : '已撤回' }}</span><button v-if="memory.status === 'active'" class="text-button" @click="retractMemory(memory)">撤回</button></div><div v-if="!memories.length" class="empty-state compact"><UserIcon :size="25" /><p>你还没有保存任何长期记忆。</p></div></div></section>
      <section v-else class="content"><div class="section-heading"><div><p class="eyebrow">WORKSPACE CONTROL</p><h1>设置</h1><p>管理项目和模型 Provider。密钥只在服务端加密保存，前端不会读取明文。</p></div></div><div class="settings-grid"><div class="settings-card"><h3>新建项目</h3><p>将不同主题的文档、事实和对话隔离在独立项目中。</p><div class="inline-form"><input v-model="newProjectName" placeholder="项目名称" @keydown.enter="createProject" /><button class="primary-button small" @click="createProject">创建</button></div></div><div class="settings-card"><h3>Provider</h3><p>{{ providers.length ? `当前工作空间有 ${providers.length} 个 Provider 配置。` : '还没有配置 Provider。' }}</p><div v-for="provider in providers" :key="provider.id" class="provider-line"><span class="provider-dot" />{{ provider.name }}<small>{{ provider.chat_model }} · {{ provider.has_api_key ? '密钥已保护' : '本地模型' }}</small></div><div class="provider-form"><input v-model="providerName" placeholder="配置名称" /><input v-model="providerBaseUrl" placeholder="OpenAI-compatible Base URL" /><input v-model="providerChatModel" placeholder="聊天模型，例如 qwen2.5" /><input v-model="providerEmbeddingModel" placeholder="Embedding 模型（可选）" /><input v-model="providerApiKey" type="password" placeholder="API Key（本地模型可留空）" /><button class="primary-button small" @click="createProvider">保存 Provider</button></div><div class="provider-hint"><Lock :size="15" />支持 OpenAI-compatible、Ollama 与 vLLM</div></div></div></section>
    </main>
    <aside v-if="selectedCitation" class="citation-drawer"><div class="drawer-header"><div><p class="eyebrow">EVIDENCE DETAIL</p><h3>{{ selectedCitation.document_title }}</h3></div><button class="icon-button" @click="selectedCitation = null">×</button></div><div class="drawer-meta">{{ selectedCitation.document_version_id }}<span>{{ selectedCitation.page_number ? `第 ${selectedCitation.page_number} 页` : '段落定位' }}</span></div><blockquote>{{ selectedCitation.snippet }}</blockquote><div class="score-grid"><div><span>最终分数</span><strong>{{ selectedCitation.final_score.toFixed(3) }}</strong></div><div><span>检索方式</span><strong>{{ selectedCitation.methods.join(' + ') }}</strong></div></div></aside>
  </div>
</template>
