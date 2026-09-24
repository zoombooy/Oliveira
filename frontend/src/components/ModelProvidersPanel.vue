<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Check,
  ChevronRight,
  Plus,
  RefreshCw,
  Search,
  Server,
  Settings2,
  Trash2,
  X,
} from '@lucide/vue'
import ProviderIcon from './ProviderIcon.vue'
import { api, type Project, type Provider } from '../api'

type ProviderType = 'openai_compatible' | 'ollama' | 'vllm'

interface ProviderPreset {
  id: string
  name: string
  subtitle: string
  description: string
  provider_type: ProviderType
  base_url: string
  chat_model: string
  embedding_model: string
  local?: boolean
}

interface ProviderForm {
  name: string
  provider_type: ProviderType
  base_url: string
  chat_model: string
  embedding_model: string
  api_key: string
  is_default: boolean
}

const props = defineProps<{
  workspaceId: string
  providers: Provider[]
  projects: Project[]
  projectId: string
}>()

const emit = defineEmits<{
  (event: 'refresh'): void
  (event: 'project-changed'): void
}>()

const presets: ProviderPreset[] = [
  {
    id: 'ollama-local',
    name: 'Ollama',
    subtitle: '本地部署',
    description: '适合在本机运行 Qwen、Llama、DeepSeek 等模型。',
    provider_type: 'ollama',
    base_url: 'http://host.docker.internal:11434/v1',
    chat_model: 'qwen3:8b',
    embedding_model: '',
    local: true,
  },
  {
    id: 'vllm-local',
    name: 'vLLM',
    subtitle: '本地部署',
    description: '适合通过 OpenAI 兼容接口提供高吞吐推理。',
    provider_type: 'vllm',
    base_url: 'http://host.docker.internal:8000/v1',
    chat_model: 'Qwen/Qwen3-8B',
    embedding_model: '',
    local: true,
  },
  {
    id: 'openai',
    name: 'OpenAI 兼容',
    subtitle: '云端或自建网关',
    description: '只要提供 OpenAI 兼容协议，就可以接入云端或内网服务。',
    provider_type: 'openai_compatible',
    base_url: 'https://api.openai.com/v1',
    chat_model: 'gpt-4o-mini',
    embedding_model: 'text-embedding-3-small',
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    subtitle: '云端供应商',
    description: '使用 DeepSeek 的 OpenAI 兼容 API。',
    provider_type: 'openai_compatible',
    base_url: 'https://api.deepseek.com/v1',
    chat_model: 'deepseek-chat',
    embedding_model: '',
  },
  {
    id: 'qwen',
    name: '通义千问',
    subtitle: '云端供应商',
    description: '使用 DashScope 的 OpenAI 兼容 API。',
    provider_type: 'openai_compatible',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    chat_model: 'qwen-plus',
    embedding_model: 'text-embedding-v3',
  },
  {
    id: 'custom',
    name: '自定义供应商',
    subtitle: 'OpenAI-compatible',
    description: '填写你的网关地址和模型名称。',
    provider_type: 'openai_compatible',
    base_url: '',
    chat_model: '',
    embedding_model: '',
  },
]

const searchQuery = ref('')
const editorOpen = ref(false)
const editorId = ref<string | null>(null)
const saving = ref(false)
const testingId = ref<string | null>(null)
const testResults = ref<Record<string, { ok: boolean; error?: string }>>({})
const binding = ref(false)
const form = reactive<ProviderForm>({
  name: '',
  provider_type: 'openai_compatible',
  base_url: '',
  chat_model: '',
  embedding_model: '',
  api_key: '',
  is_default: false,
})

const currentProject = computed(() => props.projects.find(item => item.id === props.projectId))
const configuredProviders = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  if (!keyword) return props.providers
  return props.providers.filter(item =>
    [item.name, item.provider_type, item.base_url, item.chat_model]
      .join(' ')
      .toLowerCase()
      .includes(keyword),
  )
})
const localProviders = computed(() => props.providers.filter(isLocalProvider))
const defaultProvider = computed(() => props.providers.find(item => item.is_default))
const providerStats = computed(() => ({
  total: props.providers.length,
  local: localProviders.value.length,
  ready: props.providers.filter(item => item.chat_model && item.base_url).length,
}))

function isLocalProvider(provider: Pick<Provider, 'provider_type' | 'base_url' | 'name'>) {
  const value = [provider.provider_type, provider.base_url, provider.name].join(' ').toLowerCase()
  return provider.provider_type === 'ollama' || provider.provider_type === 'vllm'
    || value.includes('localhost')
    || value.includes('host.docker.internal')
    || value.includes('127.0.0.1')
    || value.includes('本地')
}

function providerTypeLabel(providerType: string) {
  return providerType === 'ollama' ? 'Ollama' : providerType === 'vllm' ? 'vLLM' : 'OpenAI-compatible'
}

function statusLabel(provider: Provider) {
  const result = testResults.value[provider.id]
  if (result?.ok) return '连接正常'
  if (result && !result.ok) return '连接失败'
  return provider.is_default ? '当前默认' : '已配置'
}

function emptyForm() {
  return {
    name: '',
    provider_type: 'openai_compatible' as ProviderType,
    base_url: '',
    chat_model: '',
    embedding_model: '',
    api_key: '',
    is_default: props.providers.length === 0,
  }
}

function openCreate(preset?: ProviderPreset) {
  editorId.value = null
  Object.assign(form, emptyForm())
  if (preset) {
    Object.assign(form, {
      name: preset.name + (preset.local ? ' · 本地' : ''),
      provider_type: preset.provider_type,
      base_url: preset.base_url,
      chat_model: preset.chat_model,
      embedding_model: preset.embedding_model,
    })
  }
  editorOpen.value = true
}

function openEdit(provider: Provider) {
  editorId.value = provider.id
  Object.assign(form, {
    name: provider.name,
    provider_type: provider.provider_type as ProviderType,
    base_url: provider.base_url,
    chat_model: provider.chat_model,
    embedding_model: provider.embedding_model,
    api_key: '',
    is_default: provider.is_default,
  })
  editorOpen.value = true
}

function applyPreset(preset: ProviderPreset) {
  Object.assign(form, {
    name: preset.name + (preset.local ? ' · 本地' : ''),
    provider_type: preset.provider_type,
    base_url: preset.base_url,
    chat_model: preset.chat_model,
    embedding_model: preset.embedding_model,
  })
}

function closeEditor() {
  if (!saving.value) editorOpen.value = false
}

async function saveProvider() {
  if (!form.name.trim() || !form.base_url.trim() || !form.chat_model.trim()) {
    ElMessage.warning('请填写名称、Base URL 和聊天模型')
    return
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      name: form.name.trim(),
      provider_type: form.provider_type,
      base_url: form.base_url.trim().replace(/\/+$/, ''),
      chat_model: form.chat_model.trim(),
      embedding_model: form.embedding_model.trim(),
      is_default: form.is_default,
    }
    if (!editorId.value || form.api_key.trim()) payload.api_key = form.api_key.trim()
    if (editorId.value) {
      await api<Provider>('/api/v1/providers/' + editorId.value, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      })
    } else {
      await api<Provider>('/api/v1/workspaces/' + props.workspaceId + '/providers', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    }
    editorOpen.value = false
    ElMessage.success(editorId.value ? '供应商已更新' : '供应商已添加')
    emit('refresh')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存供应商失败')
  } finally {
    saving.value = false
  }
}

async function testProvider(provider: Provider) {
  testingId.value = provider.id
  try {
    const result = await api<{ ok: boolean; error?: string }>('/api/v1/providers/' + provider.id + '/test', { method: 'POST' })
    testResults.value[provider.id] = result
    if (result.ok) ElMessage.success(provider.name + ' 连接正常')
    else ElMessage.warning(result.error || '供应商连接失败')
  } catch (error) {
    testResults.value[provider.id] = { ok: false, error: error instanceof Error ? error.message : '测试失败' }
    ElMessage.error(error instanceof Error ? error.message : '测试供应商失败')
  } finally {
    testingId.value = null
  }
}

async function setDefault(provider: Provider) {
  if (provider.is_default) return
  try {
    await api<Provider>('/api/v1/providers/' + provider.id, {
      method: 'PATCH',
      body: JSON.stringify({ is_default: true }),
    })
    ElMessage.success(provider.name + ' 已设为默认供应商')
    emit('refresh')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '设置默认供应商失败')
  }
}

async function deleteProvider(provider: Provider) {
  try {
    await ElMessageBox.confirm(
      '删除后不会再参与新的对话和索引任务，已保存的历史 Run 不会被删除。',
      '删除供应商',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await api<void>('/api/v1/providers/' + provider.id, { method: 'DELETE' })
    ElMessage.success('供应商已删除')
    emit('refresh')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error instanceof Error ? error.message : '删除供应商失败')
    }
  }
}

async function deleteEditingProvider() {
  const provider = props.providers.find(item => item.id === editorId.value)
  if (provider) await deleteProvider(provider)
}

async function bindProjectProvider(value: string) {
  if (!props.projectId || binding.value) return
  binding.value = true
  try {
    await api<Project>('/api/v1/projects/' + props.projectId, {
      method: 'PATCH',
      body: JSON.stringify({ provider_id: value || null }),
    })
    ElMessage.success(value ? '当前项目已切换模型供应商' : '当前项目将跟随工作空间默认供应商')
    emit('project-changed')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '切换项目供应商失败')
  } finally {
    binding.value = false
  }
}
</script>

<template>
  <div class="provider-management">
    <div class="provider-page-heading">
      <div>
        <p class="eyebrow">MODEL PROVIDERS</p>
        <h1>模型供应商</h1>
        <p>在工作空间里维护聊天模型和 Embedding 模型。供应商密钥只会在服务端加密保存。</p>
      </div>
      <div class="provider-page-actions">
        <button class="quiet-action" type="button" @click="emit('refresh')" aria-label="刷新供应商">
          <RefreshCw :size="15" />
          <span>刷新</span>
        </button>
        <button class="primary-button small provider-add-button" type="button" @click="openCreate()">
          <Plus :size="15" />
          新增供应商
        </button>
      </div>
    </div>

    <div class="provider-stat-row">
      <div><span>已配置</span><strong>{{ providerStats.total }}</strong><small>个供应商</small></div>
      <div><span>可用配置</span><strong>{{ providerStats.ready }}</strong><small>聊天接口</small></div>
      <div><span>本地服务</span><strong>{{ providerStats.local }}</strong><small>Ollama / vLLM</small></div>
      <div><span>工作空间默认</span><strong>{{ defaultProvider ? '1' : '0' }}</strong><small>{{ defaultProvider?.name || '尚未设置' }}</small></div>
    </div>

    <section class="project-model-card">
      <div class="project-model-icon"><Settings2 :size="18" /></div>
      <div class="project-model-copy">
        <strong>当前项目使用的供应商</strong>
        <span>项目级配置优先；选择“跟随工作空间默认”后，会使用下方的默认供应商。</span>
      </div>
      <select
        class="provider-select"
        :value="currentProject?.provider_id || ''"
        :disabled="binding || !props.projectId"
        aria-label="选择当前项目的模型供应商"
        @change="bindProjectProvider(($event.target as HTMLSelectElement).value)"
      >
        <option value="">跟随工作空间默认</option>
        <option v-for="provider in props.providers" :key="provider.id" :value="provider.id">
          {{ provider.name }}{{ provider.is_default ? '（默认）' : '' }}
        </option>
      </select>
    </section>

    <div class="provider-toolbar">
      <label class="provider-search">
        <Search :size="16" />
        <input v-model="searchQuery" placeholder="搜索供应商、模型或地址…" aria-label="搜索供应商" />
      </label>
      <span>{{ configuredProviders.length }} 个配置</span>
    </div>

    <section v-if="configuredProviders.length" class="provider-section">
      <div class="provider-section-heading">
        <div><span class="provider-section-kicker">WORKSPACE CONFIGURATION</span><h2>已配置供应商</h2></div>
        <span class="provider-section-count">{{ configuredProviders.length }}</span>
      </div>
      <div class="provider-card-grid">
        <article
          v-for="provider in configuredProviders"
          :key="provider.id"
          class="provider-card"
          tabindex="0"
          @click="openEdit(provider)"
          @keydown.enter="openEdit(provider)"
        >
          <div class="provider-card-head">
            <ProviderIcon :provider-type="provider.provider_type" :name="provider.name" :size="46" />
            <div class="provider-card-title"><strong>{{ provider.name }}</strong><span>{{ providerTypeLabel(provider.provider_type) }}</span></div>
            <i class="provider-health" :class="{ default: provider.is_default }" :title="statusLabel(provider)" />
          </div>
          <div class="provider-card-body">
            <div><span>Base URL</span><strong :title="provider.base_url">{{ provider.base_url }}</strong></div>
            <div><span>聊天模型</span><strong :title="provider.chat_model">{{ provider.chat_model }}</strong></div>
            <div><span>能力</span><strong>{{ provider.embedding_model ? 'chat · embedding' : 'chat' }}</strong></div>
          </div>
          <div class="provider-card-footer">
            <button type="button" @click.stop="setDefault(provider)" :disabled="provider.is_default">
              <Check v-if="provider.is_default" :size="14" />
              <span>{{ provider.is_default ? '当前默认' : '设为默认' }}</span>
            </button>
            <button type="button" @click.stop="testProvider(provider)" :disabled="testingId === provider.id">
              <span>{{ testingId === provider.id ? '测试中…' : (testResults[provider.id]?.ok ? '连接正常' : '测试连接') }}</span>
              <ChevronRight :size="14" />
            </button>
          </div>
          <div v-if="testResults[provider.id] && !testResults[provider.id].ok" class="provider-test-error">
            {{ testResults[provider.id].error || '连接失败，请检查地址和模型配置。' }}
          </div>
        </article>
      </div>
    </section>

    <section class="provider-section quick-connect">
      <div class="provider-section-heading">
        <div><span class="provider-section-kicker">QUICK CONNECT</span><h2>快速接入</h2></div>
        <span class="provider-section-note">选择模板后只需补充模型名称</span>
      </div>
      <div class="provider-preset-grid">
        <button v-for="preset in presets" :key="preset.id" class="provider-preset-card" type="button" @click="openCreate(preset)">
          <ProviderIcon :provider-type="preset.provider_type" :name="preset.name" :size="40" />
          <span class="provider-preset-copy"><strong>{{ preset.name }}</strong><small>{{ preset.subtitle }}</small><em>{{ preset.description }}</em></span>
          <ChevronRight :size="16" />
        </button>
      </div>
    </section>

    <div v-if="!props.providers.length" class="provider-empty-note">
      <Server :size="18" />
      <div><strong>还没有模型供应商</strong><span>先从 Ollama 或 vLLM 开始，Oliveira 可以直接连接本地部署的大模型。</span></div>
      <button class="text-button" type="button" @click="openCreate(presets[0])">配置本地模型</button>
    </div>

    <div v-if="editorOpen" class="provider-modal-backdrop" @click.self="closeEditor">
      <section class="provider-dialog" role="dialog" aria-modal="true" aria-labelledby="provider-dialog-title">
        <header class="provider-dialog-header">
          <div><p class="eyebrow">{{ editorId ? 'EDIT PROVIDER' : 'NEW PROVIDER' }}</p><h2 id="provider-dialog-title">{{ editorId ? '编辑供应商' : '新增供应商' }}</h2></div>
          <button class="icon-button" type="button" aria-label="关闭" @click="closeEditor"><X :size="17" /></button>
        </header>
        <form class="provider-dialog-form" @submit.prevent="saveProvider">
          <div v-if="!editorId" class="preset-picker">
            <span class="form-caption">选择接入方式</span>
            <div class="preset-picker-grid">
              <button v-for="preset in presets.slice(0, 3)" :key="preset.id" type="button" :class="{ selected: form.name === preset.name || form.name === preset.name + ' · 本地' }" @click="applyPreset(preset)">
                <ProviderIcon :provider-type="preset.provider_type" :name="preset.name" :size="30" /><span>{{ preset.name }}</span>
              </button>
            </div>
          </div>
          <div class="provider-form-grid">
            <label><span>显示名称</span><input v-model="form.name" placeholder="例如：办公室 Ollama" required /></label>
            <label><span>协议</span><select v-model="form.provider_type"><option value="openai_compatible">OpenAI-compatible</option><option value="ollama">Ollama</option><option value="vllm">vLLM</option></select></label>
            <label class="form-span-2"><span>Base URL</span><input v-model="form.base_url" placeholder="http://host.docker.internal:11434/v1" required /></label>
            <label><span>聊天模型</span><input v-model="form.chat_model" placeholder="qwen3:8b" required /></label>
            <label><span>Embedding 模型 <small>可选</small></span><input v-model="form.embedding_model" placeholder="nomic-embed-text" /></label>
            <label class="form-span-2"><span>API Key <small>本地模型可留空</small></span><input v-model="form.api_key" type="password" :placeholder="editorId ? '留空表示保留原密钥' : 'sk-…'" autocomplete="new-password" /></label>
          </div>
          <label class="default-check"><input v-model="form.is_default" type="checkbox" /><span>设为工作空间默认供应商</span><small>未单独指定项目时使用</small></label>
          <div class="provider-local-tip"><Server :size="16" /><span>本地 Docker 部署通常使用 <code>host.docker.internal</code> 访问宿主机上的 Ollama 或 vLLM。</span></div>
          <footer class="provider-dialog-footer">
            <button v-if="editorId" class="danger-button" type="button" @click="deleteEditingProvider"><Trash2 :size="14" />删除</button>
            <span v-else />
            <div><button class="quiet-action" type="button" @click="closeEditor">取消</button><button class="primary-button small" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存供应商' }}<ChevronRight :size="15" /></button></div>
          </footer>
        </form>
      </section>
    </div>
  </div>
</template>
