<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { X, Plus } from 'lucide-vue-next'
import {
  MAX_KEYWORDS,
  MAX_KEYWORDS_CHARS,
  clampKeywordList,
  formatKeywords,
  parseKeywords,
} from '../keywords'

const props = defineProps<{
  keywords: string
  fileName?: string
  emoji?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', keywords: string): void
}>()

const words = ref<string[]>([])
const draft = ref('')
const errorMsg = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const charCount = computed(() => words.value.reduce((n, w) => n + w.length, 0))
const remainingChars = computed(() => Math.max(0, MAX_KEYWORDS_CHARS - charCount.value))
const atCountLimit = computed(() => words.value.length >= MAX_KEYWORDS)
const atCharLimit = computed(() => remainingChars.value <= 0)
const atLimit = computed(() => atCountLimit.value || atCharLimit.value)

watch(
  () => props.keywords,
  (value) => {
    words.value = clampKeywordList(parseKeywords(value))
    draft.value = ''
    errorMsg.value = ''
  },
  { immediate: true },
)

function focusInput() {
  nextTick(() => inputRef.value?.focus())
}

focusInput()

function addWords(raw: string) {
  errorMsg.value = ''
  const incoming = parseKeywords(raw)
  if (incoming.length === 0) return false

  let added = 0
  for (const word of incoming) {
    if (words.value.includes(word)) {
      errorMsg.value = `「${word}」已存在`
      continue
    }
    if (words.value.length >= MAX_KEYWORDS) {
      errorMsg.value = `最多 ${MAX_KEYWORDS} 个关键词`
      break
    }
    const used = words.value.reduce((n, w) => n + w.length, 0)
    const room = MAX_KEYWORDS_CHARS - used
    if (word.length > room) {
      errorMsg.value = room === 0
        ? `总长度已满 ${MAX_KEYWORDS_CHARS} 字符`
        : `「${word}」需要 ${word.length} 字符，还剩 ${room}`
      break
    }
    words.value.push(word)
    added += 1
  }
  if (added > 0) draft.value = ''
  return added > 0
}

function onAdd() {
  addWords(draft.value)
  focusInput()
}

function removeWord(index: number) {
  words.value.splice(index, 1)
  errorMsg.value = ''
  focusInput()
}

function onDraftKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    onAdd()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
  } else if (e.key === 'Backspace' && !draft.value && words.value.length > 0) {
    words.value.pop()
    errorMsg.value = ''
  }
}

function handleSave() {
  emit('save', formatKeywords(clampKeywordList(words.value)))
}
</script>

<template>
  <div
    data-skip-deselect
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    @click.self="$emit('close')"
  >
    <div class="w-full max-w-lg rounded-2xl bg-[#16181d] border border-[#282b35] shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
      <div class="flex items-center justify-between px-5 py-3.5 border-b border-[#252831] bg-[#12141a]">
        <div class="min-w-0">
          <h3 class="text-sm font-semibold text-white">编辑关键词</h3>
          <p class="text-[11px] text-gray-500 truncate mt-0.5">
            <span v-if="emoji" class="mr-1">{{ emoji }}</span>
            {{ fileName || '贴纸' }}
          </p>
        </div>
        <button
          type="button"
          class="rounded-lg p-1.5 text-gray-400 hover:text-white hover:bg-[#252831] transition cursor-pointer"
          @click="$emit('close')"
        >
          <X class="w-4 h-4" />
        </button>
      </div>

      <div class="p-5 flex flex-col gap-3 overflow-y-auto">
        <p class="text-[11px] text-gray-500">
          逐个添加搜索关键词，最多 {{ MAX_KEYWORDS }} 个，合计不超过 {{ MAX_KEYWORDS_CHARS }} 字符。仅写入压缩包内的 stickers.json。
        </p>

        <div
          class="min-h-[120px] rounded-xl bg-[#12141a] border border-[#2d323e] p-2.5 flex flex-wrap gap-1.5 content-start"
          @click="focusInput"
        >
          <span
            v-for="(word, idx) in words"
            :key="`${word}-${idx}`"
            class="inline-flex items-center gap-1 max-w-full pl-2 pr-1 py-0.5 rounded-full bg-[#24a1de]/15 border border-[#24a1de]/40 text-xs text-[#d7f0fb]"
          >
            <span class="truncate">{{ word }}</span>
            <button
              type="button"
              class="shrink-0 rounded-full p-0.5 text-gray-400 hover:text-white hover:bg-[#24a1de]/40 cursor-pointer"
              :title="`移除 ${word}`"
              @click.stop="removeWord(idx)"
            >
              <X class="w-3 h-3" />
            </button>
          </span>
          <span v-if="words.length === 0" class="text-[11px] text-gray-600 px-1 py-1">
            还没有关键词，在下方输入后回车添加
          </span>
        </div>

        <div class="flex items-center gap-2">
          <input
            ref="inputRef"
            v-model="draft"
            type="text"
            :disabled="atLimit"
            :placeholder="atCountLimit ? '已满 20 个' : atCharLimit ? '字符已满' : '输入关键词，回车添加'"
            class="flex-1 bg-[#12141a] border border-[#2d323e] focus:border-[#24a1de] rounded-lg px-3 py-2 text-xs text-white focus:outline-none disabled:opacity-50"
            @keydown="onDraftKeydown"
          />
          <button
            type="button"
            :disabled="atLimit || !draft.trim()"
            class="shrink-0 px-3 py-2 rounded-lg bg-[#24a1de] hover:bg-[#2eb5f7] text-white text-xs font-medium flex items-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            @click="onAdd"
          >
            <Plus class="w-3.5 h-3.5" />
            添加
          </button>
        </div>

        <div class="flex items-center justify-between gap-3">
          <p class="text-[11px] text-amber-400 min-h-[1rem]">{{ errorMsg }}</p>
          <p
            class="shrink-0 font-mono text-[11px] tabular-nums"
            :class="atLimit ? 'text-amber-400' : 'text-gray-500'"
          >
            {{ words.length }}/{{ MAX_KEYWORDS }} · {{ charCount }}/{{ MAX_KEYWORDS_CHARS }}
          </p>
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-[#252831] bg-[#12141a]">
        <button
          type="button"
          class="px-4 py-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-[#252831] text-xs font-medium cursor-pointer"
          @click="$emit('close')"
        >
          取消
        </button>
        <button
          type="button"
          class="px-5 py-1.5 rounded-lg bg-[#24a1de] hover:bg-[#2eb5f7] text-white text-xs font-semibold cursor-pointer"
          @click="handleSave"
        >
          保存
        </button>
      </div>
    </div>
  </div>
</template>
