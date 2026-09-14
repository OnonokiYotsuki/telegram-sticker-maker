<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { X, Save, Check } from 'lucide-vue-next'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved'): void
}>()

const settings = ref({
  ai_base_url: 'https://api.openai.com/v1',
  ai_model: 'gpt-4o-mini',
  ai_api_key: '',
})

const isSaving = ref(false)
const saveSuccess = ref(false)

async function loadSettings() {
  if (window.pywebview?.api?.get_settings) {
    try {
      const data = await window.pywebview.api.get_settings()
      if (data) {
        settings.value.ai_base_url = data.ai_base_url || 'https://api.openai.com/v1'
        settings.value.ai_model = data.ai_model || 'gpt-4o-mini'
        settings.value.ai_api_key = data.ai_api_key || ''
      }
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      loadSettings()
    }
  }
)

async function handleSave() {
  isSaving.value = true
  saveSuccess.value = false
  if (window.pywebview?.api?.save_settings) {
    try {
      const current = (await window.pywebview.api.get_settings()) || {}
      await window.pywebview.api.save_settings({
        ...current,
        ai_base_url: settings.value.ai_base_url,
        ai_model: settings.value.ai_model,
        ai_api_key: settings.value.ai_api_key,
      })
      saveSuccess.value = true
      emit('saved')
      setTimeout(() => {
        saveSuccess.value = false
        emit('update:modelValue', false)
      }, 600)
    } catch (e) {
      console.error('Failed to save settings:', e)
    } finally {
      isSaving.value = false
    }
  } else {
    isSaving.value = false
    emit('update:modelValue', false)
  }
}

function handleClose() {
  emit('update:modelValue', false)
}

onMounted(() => {
  loadSettings()
})
</script>

<template>
  <div
    v-if="modelValue"
    data-skip-deselect
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    @click.self="handleClose"
  >
    <div class="w-full max-w-lg rounded-2xl bg-zinc-900 border border-zinc-700/70 shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
      <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-zinc-950/60">
        <h3 class="text-lg font-semibold text-zinc-100 flex items-center gap-2">
          ⚙️ AI 设置
        </h3>
        <button
          @click="handleClose"
          class="rounded-lg p-1.5 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <div class="p-6 space-y-4 overflow-y-auto text-sm text-zinc-300">
        <h4 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider">✨ AI 智能匹配 Emoji</h4>

        <div class="space-y-3">
          <div class="space-y-1">
            <label class="text-xs text-zinc-400">API Key</label>
            <input
              v-model="settings.ai_api_key"
              type="password"
              placeholder="sk-..."
              class="w-full rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-1">
              <label class="text-xs text-zinc-400">Base URL</label>
              <input
                v-model="settings.ai_base_url"
                type="text"
                placeholder="https://api.openai.com/v1"
                class="w-full rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div class="space-y-1">
              <label class="text-xs text-zinc-400">模型名称</label>
              <input
                v-model="settings.ai_model"
                type="text"
                placeholder="gpt-4o-mini"
                class="w-full rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-xs text-zinc-100 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
          <p class="text-[11px] text-zinc-500">支持任何兼容 OpenAI 格式的接口 (如 DeepSeek, Moonshot, OneAPI 等)。</p>
        </div>
      </div>

      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-zinc-800 bg-zinc-950/60">
        <button
          @click="handleClose"
          class="px-4 py-2 rounded-xl text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 text-xs font-medium transition"
        >
          取消
        </button>
        <button
          @click="handleSave"
          :disabled="isSaving"
          class="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 active:scale-95 text-white text-xs font-medium flex items-center gap-1.5 transition shadow-lg shadow-blue-500/20 disabled:opacity-50"
        >
          <Check v-if="saveSuccess" class="w-4 h-4 text-white" />
          <Save v-else class="w-4 h-4" />
          {{ saveSuccess ? '已保存' : '保存设置' }}
        </button>
      </div>
    </div>
  </div>
</template>
