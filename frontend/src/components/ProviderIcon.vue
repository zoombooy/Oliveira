<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  providerType?: string
  name?: string
  size?: number
}>(), {
  providerType: 'openai_compatible',
  name: 'Provider',
  size: 42,
})

const normalized = computed(() => [props.providerType, props.name].join(' ').toLowerCase())
const kind = computed(() => {
  if (normalized.value.includes('ollama')) return 'ollama'
  if (normalized.value.includes('vllm')) return 'vllm'
  if (normalized.value.includes('deepseek')) return 'deepseek'
  if (normalized.value.includes('qwen') || normalized.value.includes('通义')) return 'qwen'
  if (normalized.value.includes('openai')) return 'openai'
  if (normalized.value.includes('local') || normalized.value.includes('本地')) return 'local'
  return props.providerType === 'openai_compatible' ? 'compatible' : 'custom'
})

const label = computed(() => {
  const map: Record<string, string> = {
    ollama: 'O',
    vllm: 'V',
    deepseek: 'D',
    qwen: 'Q',
    openai: '◎',
    local: '⌘',
    compatible: '↔',
    custom: '·',
  }
  return map[kind.value] || '·'
})
</script>

<template>
  <span
    class="provider-icon"
    :class="'provider-icon-' + kind"
    :style="{ width: size + 'px', height: size + 'px' }"
    role="img"
    :aria-label="(name || '模型供应商') + '图标'"
  >
    <svg viewBox="0 0 42 42" aria-hidden="true">
      <g v-if="kind === 'openai'" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path d="M21 7.2c3.2-2.1 7.5-1.3 9.6 1.9l1 1.5c3.8-.3 7.2 2.5 7.5 6.3l.2 1.8c2.9 2.4 3.3 6.7.9 9.6l-1.1 1.4c1.4 3.6-.4 7.6-4 9l-1.7.7c-1 3.7-4.9 5.9-8.6 4.9l-1.8-.5c-2.8 2.6-7.1 2.4-9.7-.4l-1.1-1.4c-3.7.5-7.1-2-7.6-5.7l-.3-1.8c-3.2-2-4.2-6.1-2.2-9.3l1-1.5c-1-3.7 1.2-7.5 4.9-8.5l1.8-.5c1.4-3.6 5.5-5.3 9.1-3.9Z" transform="translate(0 -1) scale(.98)" />
        <path d="m13 15 15 8.7v9.4M28 15l-15 8.7v9.4M9 23.7l15-8.6 8.1 4.7M33 23.7l-15 8.6-8.1-4.7" />
      </g>
      <g v-else-if="kind === 'ollama'" fill="none" stroke="currentColor" stroke-width="2.5">
        <circle cx="21" cy="21" r="13" />
        <circle cx="21" cy="21" r="5" />
        <path d="M8 21h26M21 8v26" opacity=".55" />
      </g>
      <g v-else-if="kind === 'vllm'" fill="currentColor">
        <rect x="7" y="8" width="10" height="10" rx="2" opacity=".55" />
        <rect x="25" y="8" width="10" height="10" rx="2" />
        <rect x="7" y="24" width="10" height="10" rx="2" />
        <rect x="25" y="24" width="10" height="10" rx="2" opacity=".55" />
      </g>
      <g v-else-if="kind === 'deepseek'" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 27c4.5 2.8 8.9 2.5 12.2-1.2 2.2-2.4 2.2-6.9-.1-9.4-1.4-1.5-3.3-2.3-5.4-2.2" />
        <path d="M16 12.8c2.1-2.7 5.8-3.2 8.3-1.3 1.7 1.3 2.5 3.2 2.3 5.2 3.5.6 5.1 3.3 5 5.6-.1 3.5-3.3 5.3-6.5 4.9" />
        <circle cx="15" cy="20" r="1.4" fill="currentColor" stroke="none" />
      </g>
      <g v-else-if="kind === 'qwen'" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round">
        <circle cx="20" cy="20" r="11.5" />
        <path d="M27 27l6.5 6.5M14.5 19.8h6.2a3.7 3.7 0 0 1 0 7.4h-1.4" />
      </g>
      <g v-else-if="kind === 'local'" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="7" y="9" width="28" height="22" rx="3" />
        <path d="M12 15h18M12 21h4M12 26h9M29 25.5h.1" />
      </g>
      <g v-else fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
        <path d="M10 14h22M10 21h22M10 28h22" />
        <circle cx="15" cy="14" r="2.5" fill="currentColor" stroke="none" />
        <circle cx="27" cy="21" r="2.5" fill="currentColor" stroke="none" />
        <circle cx="19" cy="28" r="2.5" fill="currentColor" stroke="none" />
      </g>
      <text v-if="['compatible', 'custom'].includes(kind)" x="21" y="26" text-anchor="middle" font-size="18" font-weight="700" fill="currentColor">{{ label }}</text>
    </svg>
  </span>
</template>
