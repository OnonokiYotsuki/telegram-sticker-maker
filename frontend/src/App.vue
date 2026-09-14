<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import {
  FolderOpen,
  Trash2,
  Plus,
  Scissors,
  ChevronDown,
  ChevronUp,
  Film,
  Image as ImageIcon,
} from 'lucide-vue-next'
import type { TaskItem, GlobalOptions, ClipItem } from './types'
import { clampCropRadius, cropRadiusLabel } from './types'
import { defaultClipEnd, formatOutputName } from './naming'
import VideoClipModal from './components/VideoClipModal.vue'
import SettingsModal from './components/SettingsModal.vue'

// --- State ---
const tasks = ref<TaskItem[]>([])
const selectedTaskIds = ref<Set<number>>(new Set())
const lastSelectedTaskId = ref<number | null>(null)
const selectedTaskId = computed(() => {
  if (selectedTaskIds.value.size === 1) {
    return Array.from(selectedTaskIds.value)[0]
  }
  return lastSelectedTaskId.value
})

const globalOptions = ref<GlobalOptions>({
  preset_style: 'anime',
  is_custom_emoji: false,
  same_dir: false,
  custom_output_dir: '',
})

const isConverting = ref(false)
const isAiTagging = ref(false)
const isDraggingOver = ref(false)
const showSettings = ref(false)
const isLogOpen = ref(false)
const logs = ref<string[]>([])
const logContainer = ref<HTMLElement | null>(null)
const streamBaseUrl = ref('')
const activeClipTask = ref<TaskItem | null>(null)

let nextTaskId = 1

const editingEmojiTaskId = ref<number | null>(null)
const emojiInputRef = ref<HTMLInputElement | null>(null)

function startEmojiEdit(task: TaskItem) {
  editingEmojiTaskId.value = task.taskId
  if (!selectedTaskIds.value.has(task.taskId)) {
    selectedTaskIds.value = new Set([task.taskId])
    lastSelectedTaskId.value = task.taskId
  }
  nextTick(() => {
    emojiInputRef.value?.focus()
    emojiInputRef.value?.select()
  })
}

function commitEmojiEdit(task: TaskItem) {
  if (editingEmojiTaskId.value !== task.taskId) return
  task.emoji = (task.emoji || '').trim()
  updateTaskOutputPath(task)
  editingEmojiTaskId.value = null
}

// Context Menu State
const contextMenu = ref<{
  visible: boolean
  x: number
  y: number
  task: TaskItem | null
}>({
  visible: false,
  x: 0,
  y: 0,
  task: null,
})

// Supported formats chips for EmptyDropzone
const formatChips = ['MP4', 'MKV', 'WebM', 'MOV', 'PNG', 'JPG', 'WebP', 'GIF', 'HEIC', 'APNG']

// --- Computed ---
const taskCounts = computed(() => {
  const total = tasks.value.length
  const waiting = tasks.value.filter((t) => t.status === 'waiting').length
  const converting = tasks.value.filter((t) => t.status === 'converting').length
  const success = tasks.value.filter((t) => t.status === 'success').length
  const failed = tasks.value.filter((t) => t.status === 'failed').length
  return { total, waiting, converting, success, failed }
})

const statusSummaryText = computed(() => {
  if (isConverting.value) {
    return `正在转码: ${taskCounts.value.converting} 进行中, ${taskCounts.value.success} 完成 / 共 ${taskCounts.value.total} 项`
  }
  if (taskCounts.value.total === 0) return '就绪'
  return `就绪: 共 ${taskCounts.value.total} 项 (${taskCounts.value.success} 完成, ${taskCounts.value.failed} 失败)`
})

// --- Naming & Output Path Logic (Matched to PySide6 AIEmojiTagger.format_output_name) ---
function computeTargetFilename(task: TaskItem): string {
  const ext = task.mediaInfo.is_video ? '.webm' : '.webp'
  return formatOutputName(task.index, task.emoji || '', ext)
}

function updateTaskOutputPath(task: TaskItem) {
  const targetName = computeTargetFilename(task)
  let dir = ''
  if (globalOptions.value.same_dir || !globalOptions.value.custom_output_dir) {
    const lastSlash = Math.max(task.inputPath.lastIndexOf('/'), task.inputPath.lastIndexOf('\\'))
    dir = lastSlash > 0 ? task.inputPath.substring(0, lastSlash) : task.inputPath
  } else {
    dir = globalOptions.value.custom_output_dir.trim().replace(/[/\\]+$/, '')
  }

  task.outputPath = `${dir}/${targetName}`.replace(/\\/g, '/')
}

function updateAllTasksOutputPaths() {
  tasks.value.forEach((t) => updateTaskOutputPath(t))
}

watch(
  () => [
    globalOptions.value.same_dir,
    globalOptions.value.custom_output_dir,
    globalOptions.value.is_custom_emoji,
  ],
  () => {
    updateAllTasksOutputPaths()
  }
)

// --- API & IPC Setup ---
function onKeyDown(e: KeyboardEvent) {
  const target = e.target as HTMLElement
  const isEditing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
  if (isEditing) return

  if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) {
    if (tasks.value.length > 0) {
      e.preventDefault()
      selectAll()
    }
  } else if (e.key === 'Delete') {
    if (selectedTaskIds.value.size > 0 && !isConverting.value) {
      e.preventDefault()
      removeSelectedTasks()
    }
  } else if (e.key === 'Escape') {
    clearSelection()
    contextMenu.value.visible = false
  }
}

onMounted(async () => {
  setupIpcListeners()
  await initPywebview()

  // Close context menu on window click
  window.addEventListener('click', () => {
    contextMenu.value.visible = false
  })
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})

function appendLog(msg: string) {
  const time = new Date().toLocaleTimeString()
  logs.value.push(`[${time}] ${msg}`)
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

function setupIpcListeners() {
  window.onLog = (msg: string) => appendLog(msg)

  window.onTaskStarted = (taskId: number) => {
    const t = tasks.value.find((item) => item.taskId === taskId)
    if (t) {
      t.status = 'converting'
      t.progress = 0
      t.statusMsg = '正在转码...'
    }
  }

  window.onTaskProgress = (taskId: number, p: number, msg: string) => {
    const t = tasks.value.find((item) => item.taskId === taskId)
    if (t) {
      t.progress = Math.round(p * 100)
      t.statusMsg = msg
    }
  }

  window.onTaskFinished = (taskId: number, success: boolean, msg: string, outPath: string, size: number) => {
    const t = tasks.value.find((item) => item.taskId === taskId)
    if (t) {
      t.status = success ? 'success' : 'failed'
      t.progress = success ? 100 : 0
      t.statusMsg = msg
      t.outputSize = size
      if (outPath) t.outputPath = outPath
    }
  }

  window.onAllCompleted = () => {
    isConverting.value = false
    appendLog('🎉 批量转换已全部完成！')
  }

  window.onAiItemStarted = (_taskId: number, fileName: string) => {
    appendLog(`[AI] 正在分析表情: ${fileName}...`)
  }

  window.onAiItemFinished = (taskId: number, emoji: string) => {
    const t = tasks.value.find((item) => item.taskId === taskId)
    if (t) {
      t.emoji = emoji
      updateTaskOutputPath(t)
    }
  }

  window.onAiItemError = (_taskId: number, err: string) => {
    appendLog(`[AI 异常] ${err}`)
  }

  window.onAiAllCompleted = () => {
    isAiTagging.value = false
    appendLog('✨ AI Emoji 智能匹配已完成！')
  }
}

async function bootApi() {
  const api = window.pywebview?.api
  if (!api) return
  try {
    const info = await api.get_info()
    if (info.stream_base_url) {
      streamBaseUrl.value = info.stream_base_url
    }
    const settings = await api.get_settings()
    if (settings) {
      globalOptions.value.preset_style = settings.preset_style || 'anime'
      globalOptions.value.is_custom_emoji = settings.is_custom_emoji ?? false
      globalOptions.value.same_dir = settings.same_dir ?? false
      globalOptions.value.custom_output_dir = settings.custom_output_dir || ''
    }
    appendLog('🚀 Telegram Sticker Maker 已准备就绪')
  } catch (e) {
    console.error('Error initializing API:', e)
  }
}

function initPywebview() {
  if (window.pywebview?.api) {
    void bootApi()
    return
  }
  window.addEventListener('pywebviewready', () => {
    void bootApi()
  }, { once: true })
  const poll = window.setInterval(() => {
    if (window.pywebview?.api) {
      window.clearInterval(poll)
      void bootApi()
    }
  }, 100)
  window.setTimeout(() => window.clearInterval(poll), 15000)
}

// --- Add Files ---
async function addFilesFromPaths(paths: string[]) {
  if (!paths || paths.length === 0) return
  appendLog(`正在解析 ${paths.length} 个文件...`)

  for (const p of paths) {
    try {
      const info = await window.pywebview?.api?.analyze_file(p)
      if (!info || info.error) {
        appendLog(`❌ 解析失败: ${p} (${info?.error || '未知错误'})`)
        continue
      }
      const idx = tasks.value.length + 1
      const task: TaskItem = {
        taskId: nextTaskId++,
        inputPath: p,
        outputPath: '',
        mediaInfo: info,
        emoji: '',
        index: idx,
        status: 'waiting',
        progress: 0,
        statusMsg: '等待转换',
        outputSize: 0,
        startTime: info.is_video ? 0 : undefined,
        endTime: info.is_video ? defaultClipEnd(info.duration) : undefined,
      }
      updateTaskOutputPath(task)
      tasks.value.push(task)
    } catch (e) {
      appendLog(`❌ 解析异常: ${p}`)
    }
  }
  appendLog(`✅ 已添加完成，当前任务数: ${tasks.value.length}`)
}

async function handleSelectFiles() {
  if (window.pywebview?.api?.select_files) {
    const files = await window.pywebview.api.select_files()
    if (files && files.length > 0) {
      await addFilesFromPaths(files)
    }
  }
}

async function handleSelectDirectory() {
  if (window.pywebview?.api?.select_directory) {
    const dir = await window.pywebview.api.select_directory()
    if (dir) {
      appendLog(`扫描文件夹: ${dir}`)
      const files = await window.pywebview.api.scan_directory(dir)
      if (files && files.length > 0) {
        await addFilesFromPaths(files)
      } else {
        appendLog('⚠️ 所选文件夹下未发现支持的媒体文件')
      }
    }
  }
}

async function handleToolbarClipVideo() {
  // 1. If currently selected row is a video, open clip modal directly
  if (selectedTaskId.value) {
    const t = tasks.value.find((item) => item.taskId === selectedTaskId.value)
    if (t && t.mediaInfo.is_video) {
      openTaskClipModal(t)
      return
    }
  }

  // 2. Otherwise open file selector to choose a video to clip
  if (window.pywebview?.api?.select_files) {
    const files = await window.pywebview.api.select_files()
    if (files && files.length > 0) {
      const p = files[0]
      const info = await window.pywebview?.api?.analyze_file(p)
      if (info && !info.error) {
        if (!info.is_video) {
          alert('所选文件不是视频格式！')
          return
        }
        const tempTask: TaskItem = {
          taskId: nextTaskId++,
          inputPath: p,
          outputPath: '',
          mediaInfo: info,
          emoji: '',
          index: tasks.value.length + 1,
          status: 'waiting',
          progress: 0,
          statusMsg: '等待转换',
          outputSize: 0,
          startTime: 0,
          endTime: defaultClipEnd(info.duration),
        }
        updateTaskOutputPath(tempTask)
        tasks.value.push(tempTask)
        openTaskClipModal(tempTask)
      }
    }
  }
}

// --- Drag & Drop ---
function handleDragOver(e: DragEvent) {
  e.preventDefault()
  e.stopPropagation()
  isDraggingOver.value = true
}

function handleDragLeave(e: DragEvent) {
  e.preventDefault()
  e.stopPropagation()
  isDraggingOver.value = false
}

async function handleDrop(e: DragEvent) {
  e.preventDefault()
  e.stopPropagation()
  isDraggingOver.value = false

  if (window.chrome?.webview?.postMessageWithAdditionalObjects && e.dataTransfer?.files) {
    window.chrome.webview.postMessageWithAdditionalObjects('FilesDropped', e.dataTransfer.files)
    await new Promise((r) => setTimeout(r, 60))
    if (window.pywebview?.api?.get_dropped_files) {
      const paths = await window.pywebview.api.get_dropped_files()
      if (paths && paths.length > 0) {
        await addFilesFromPaths(paths)
        return
      }
    }
  }

  if (e.dataTransfer?.files) {
    const paths: string[] = []
    for (let i = 0; i < e.dataTransfer.files.length; i++) {
      const f = e.dataTransfer.files[i] as any
      if (f.path) paths.push(f.path)
    }
    if (paths.length > 0) {
      await addFilesFromPaths(paths)
    }
  }
}

// --- Task Actions & Selection ---
function selectAll() {
  selectedTaskIds.value = new Set(tasks.value.map((t) => t.taskId))
}

function clearSelection() {
  selectedTaskIds.value = new Set()
  lastSelectedTaskId.value = null
}

function invertSelection() {
  const newSet = new Set<number>()
  for (const t of tasks.value) {
    if (!selectedTaskIds.value.has(t.taskId)) {
      newSet.add(t.taskId)
    }
  }
  selectedTaskIds.value = newSet
}

function isSelectionSafeTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return Boolean(
    target.closest(
      'button, input, textarea, select, a, label, [role="dialog"], [data-skip-deselect]'
    )
  )
}

function handleBlankClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  if (!target) return
  // Keep selection when clicking rows or interactive controls
  if (isSelectionSafeTarget(target) || target.closest('tbody tr')) return
  clearSelection()
}

function handleRowClick(e: MouseEvent, task: TaskItem) {
  const target = e.target as HTMLElement
  if (target.closest('button, input, [contenteditable="true"]')) {
    return
  }
  // 双击用于编辑关联 Emoji，忽略后续 click，避免把已选项点掉
  if (e.detail > 1) return
  if (target.closest('[data-emoji-edit]') && selectedTaskIds.value.has(task.taskId)) {
    return
  }

  const currentId = task.taskId
  const currentIndex = tasks.value.findIndex((t) => t.taskId === currentId)

  if (e.shiftKey && lastSelectedTaskId.value !== null) {
    const lastIndex = tasks.value.findIndex((t) => t.taskId === lastSelectedTaskId.value)
    if (lastIndex !== -1 && currentIndex !== -1) {
      const start = Math.min(lastIndex, currentIndex)
      const end = Math.max(lastIndex, currentIndex)
      const newSet = new Set(selectedTaskIds.value)
      for (let i = start; i <= end; i++) {
        newSet.add(tasks.value[i].taskId)
      }
      selectedTaskIds.value = newSet
    }
  } else if (e.ctrlKey || e.metaKey) {
    const newSet = new Set(selectedTaskIds.value)
    if (newSet.has(currentId)) {
      newSet.delete(currentId)
      if (lastSelectedTaskId.value === currentId) {
        lastSelectedTaskId.value = newSet.size ? [...newSet][newSet.size - 1] : null
      }
    } else {
      newSet.add(currentId)
      lastSelectedTaskId.value = currentId
    }
    selectedTaskIds.value = newSet
  } else if (selectedTaskIds.value.has(currentId)) {
    // 再次点击已选项：取消该项选中
    const newSet = new Set(selectedTaskIds.value)
    newSet.delete(currentId)
    selectedTaskIds.value = newSet
    if (lastSelectedTaskId.value === currentId) {
      lastSelectedTaskId.value = newSet.size ? [...newSet][newSet.size - 1] : null
    }
  } else {
    selectedTaskIds.value = new Set([currentId])
    lastSelectedTaskId.value = currentId
  }
}

function removeSelectedTasks() {
  if (selectedTaskIds.value.size === 0) return
  const count = selectedTaskIds.value.size
  tasks.value = tasks.value.filter((t) => !selectedTaskIds.value.has(t.taskId))
  selectedTaskIds.value = new Set()
  lastSelectedTaskId.value = null
  tasks.value.forEach((t, i) => {
    t.index = i + 1
    updateTaskOutputPath(t)
  })
  appendLog(`已移除选中的 ${count} 个任务。`)
}

function removeTask(taskId: number) {
  tasks.value = tasks.value.filter((t) => t.taskId !== taskId)
  const newSet = new Set(selectedTaskIds.value)
  newSet.delete(taskId)
  selectedTaskIds.value = newSet
  if (lastSelectedTaskId.value === taskId) lastSelectedTaskId.value = null
  tasks.value.forEach((t, i) => {
    t.index = i + 1
    updateTaskOutputPath(t)
  })
}

function clearAllTasks() {
  if (isConverting.value) {
    alert('转换正在进行中，请先停止！')
    return
  }
  tasks.value = []
  selectedTaskIds.value = new Set()
  lastSelectedTaskId.value = null
  appendLog('已清空所有任务。')
}

function openTaskClipModal(task: TaskItem) {
  activeClipTask.value = task
}

function handleClipsGenerated(clips: ClipItem[]) {
  if (!activeClipTask.value || clips.length === 0) {
    activeClipTask.value = null
    return
  }

  const baseTask = activeClipTask.value
  if (clips.length === 1) {
    const c = clips[0]
    if (baseTask.mediaInfo.is_video) {
      baseTask.startTime = c.startTime
      baseTask.endTime = c.endTime
      baseTask.clipLabel = `[${c.startTime.toFixed(3)}s - ${c.endTime.toFixed(3)}s]`
    }
    baseTask.crop = c.crop
    baseTask.cropRadius = c.cropRadius
    baseTask.emoji = c.emoji || baseTask.emoji
    updateTaskOutputPath(baseTask)
    appendLog(`[${baseTask.mediaInfo.file_name}] 已更新截取与裁切参数`)
  } else {
    const baseIdx = tasks.value.findIndex((t) => t.taskId === baseTask.taskId)
    const newTasks: TaskItem[] = []

    clips.forEach((c, i) => {
      const task: TaskItem = {
        taskId: nextTaskId++,
        inputPath: baseTask.inputPath,
        outputPath: '',
        mediaInfo: baseTask.mediaInfo,
        emoji: c.emoji || baseTask.emoji,
        index: baseTask.index + i,
        clipLabel: `[${c.startTime.toFixed(3)}s - ${c.endTime.toFixed(3)}s]`,
        startTime: c.startTime,
        endTime: c.endTime,
        crop: c.crop,
        cropRadius: c.cropRadius,
        status: 'waiting',
        progress: 0,
        statusMsg: '等待转换',
        outputSize: 0,
      }
      updateTaskOutputPath(task)
      newTasks.push(task)
    })

    tasks.value.splice(baseIdx, 1, ...newTasks)
    tasks.value.forEach((t, i) => {
      t.index = i + 1
      updateTaskOutputPath(t)
    })
    appendLog(`[${baseTask.mediaInfo.file_name}] 已生成 ${clips.length} 个截取片段`)
  }

  activeClipTask.value = null
}

function getThumbnailUrl(task: TaskItem): string {
  if (!streamBaseUrl.value) return ''
  const p = encodeURIComponent(task.inputPath)
  const t = task.startTime || 0
  let url = `${streamBaseUrl.value}/thumbnail?path=${p}&t=${t.toFixed(3)}&size=88`
  if (task.crop && task.crop.length === 4) {
    url += `&crop=${task.crop.join(',')}`
  }
  if (task.cropRadius && task.cropRadius > 0.001) {
    url += `&radius=${task.cropRadius}`
  }
  return url
}

function openFolder(filePath: string) {
  if (!filePath) return
  if (window.pywebview?.api?.open_folder) {
    window.pywebview.api.open_folder(filePath)
  }
}

function handleOpenOutputFolder() {
  let target = ''
  if (globalOptions.value.same_dir) {
    if (tasks.value.length > 0 && tasks.value[0].outputPath) {
      target = tasks.value[0].outputPath
    } else if (tasks.value.length > 0 && tasks.value[0].inputPath) {
      target = tasks.value[0].inputPath
    } else {
      target = globalOptions.value.custom_output_dir
    }
  } else {
    target = globalOptions.value.custom_output_dir
  }
  if (target && window.pywebview?.api?.open_folder) {
    window.pywebview.api.open_folder(target)
  }
}

async function saveCurrentSettings() {
  if (window.pywebview?.api?.save_settings) {
    try {
      await window.pywebview.api.save_settings({
        preset_style: globalOptions.value.preset_style,
        spoof_duration: true,
        optimize_fps: true,
        is_custom_emoji: globalOptions.value.is_custom_emoji,
        same_dir: globalOptions.value.same_dir,
        custom_output_dir: globalOptions.value.custom_output_dir,
        use_emoji_naming: true,
        zero_pad: true,
      })
    } catch (e) {
      console.error('Failed to auto-save settings:', e)
    }
  }
}

async function selectCustomOutputDir() {
  if (window.pywebview?.api?.select_directory) {
    const dir = await window.pywebview.api.select_directory()
    if (dir) {
      globalOptions.value.custom_output_dir = dir
      globalOptions.value.same_dir = false
      updateAllTasksOutputPaths()
      saveCurrentSettings()
    }
  }
}

// --- Right Click Context Menu ---
function onRowContextMenu(e: MouseEvent, task: TaskItem) {
  e.preventDefault()
  if (!selectedTaskIds.value.has(task.taskId)) {
    selectedTaskIds.value = new Set([task.taskId])
    lastSelectedTaskId.value = task.taskId
  }
  contextMenu.value = {
    visible: true,
    x: e.clientX,
    y: e.clientY,
    task,
  }
}

async function aiTagSingle(task: TaskItem) {
  if (window.pywebview?.api?.ai_tag_single) {
    appendLog(`[AI] 开始识别: ${task.mediaInfo.file_name}`)
    await window.pywebview.api.ai_tag_single(
      task.taskId,
      task.inputPath,
      task.startTime,
      task.endTime
    )
  }
}

// --- Conversion Controls ---
async function startConversion() {
  if (tasks.value.length === 0) return
  updateAllTasksOutputPaths()
  isConverting.value = true

  const payload = tasks.value.map((t) => ({
    task_id: t.taskId,
    input_path: t.inputPath,
    output_path: t.outputPath,
    start_time: t.startTime,
    end_time: t.endTime,
    crop: t.crop,
    crop_radius: t.cropRadius || 0,
  }))

  try {
    if (window.pywebview?.api?.start_conversion) {
      await window.pywebview.api.start_conversion(payload, {
        ...globalOptions.value,
        spoof_duration: true,
        optimize_fps: true,
        use_emoji_naming: true,
        zero_pad: true,
      })
    }
  } catch (e) {
    appendLog(`❌ 启动转换失败: ${e}`)
    isConverting.value = false
  }
}

async function cancelConversion() {
  if (window.pywebview?.api?.cancel_conversion) {
    await window.pywebview.api.cancel_conversion()
  }
}

async function triggerAiTagAll() {
  if (tasks.value.length === 0) return
  const targets = selectedTaskIds.value.size > 0
    ? tasks.value.filter((t) => selectedTaskIds.value.has(t.taskId))
    : tasks.value

  isAiTagging.value = true
  const payload = targets.map((t) => ({
    task_id: t.taskId,
    input_path: t.inputPath,
    start_time: t.startTime,
    end_time: t.endTime,
  }))
  try {
    if (window.pywebview?.api?.ai_tag_all) {
      await window.pywebview.api.ai_tag_all(payload)
    }
  } catch (e) {
    appendLog(`❌ AI 打标失败: ${e}`)
    isAiTagging.value = false
  }
}
</script>

<template>
  <div
    class="flex flex-col h-screen w-screen overflow-hidden bg-[#121316] text-[#f3f4f6] font-sans select-none p-[16px_18px_14px_18px] gap-3"
    @click="handleBlankClick"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <!-- 1. Header Title & Subtitle (Faithful to PySide6 MainWindow) -->
    <header class="flex items-center justify-between shrink-0 px-1">
      <div class="flex items-center gap-3">
        <span class="text-2xl leading-none">✨</span>
        <div class="flex flex-col gap-0.5">
          <h1 class="text-lg font-bold text-white tracking-wide">
            Telegram Sticker Maker
          </h1>
          <p class="text-xs text-[#9ca3af]">
            Telegram 贴纸批量转换工具 | 支持 WebM 视频贴纸与 WebP 静态贴纸
          </p>
        </div>
      </div>

      <!-- Top Right Status Badge -->
      <div
        :class="[
          'rounded-md px-2.5 py-1 text-xs font-semibold border transition-all duration-200',
          tasks.length === 0
            ? 'bg-[#1e222b] text-[#9ca3af] border-[#2d323e]'
            : 'bg-[#24a1de]/15 text-[#2eb5f7] border-[#24a1de]'
        ]"
      >
        <span v-if="selectedTaskIds.size > 0">已选 {{ selectedTaskIds.size }} / {{ tasks.length }} 项</span>
        <span v-else>已添加 {{ tasks.length }} 项</span>
      </div>
    </header>

    <!-- 2. Main Splitter Area: Left (Table + Dropzone) | Right (Settings Controls) -->
    <div class="flex-1 flex min-h-0 gap-3">
      
      <!-- ================= LEFT CARD (Table & Dropzone) ================= -->
      <div class="flex-1 bg-[#1a1c22] border border-[#282b35] rounded-xl flex flex-col p-3.5 gap-2.5 overflow-hidden min-w-[420px]">
        
        <!-- Action Buttons Toolbar (Identical to PySide6) -->
        <div class="flex items-center gap-2 shrink-0 flex-wrap">
          <button
            @click="handleSelectFiles"
            class="px-3 py-1.5 rounded-lg bg-[#242730] hover:bg-[#2e333e] border border-[#333844] text-[#e5e7eb] text-xs font-medium flex items-center gap-1.5 transition active:scale-95 cursor-pointer"
          >
            ➕ 添加文件
          </button>

          <button
            @click="handleToolbarClipVideo"
            class="px-3 py-1.5 rounded-lg bg-[#242730] hover:bg-[#2e333e] border border-[#333844] text-[#e5e7eb] text-xs font-medium flex items-center gap-1.5 transition active:scale-95 cursor-pointer"
            title="选择视频文件并指定起止时间，支持在一个视频中截取出多个贴纸"
          >
            ✂️ 截取视频片段
          </button>

          <button
            @click="handleSelectDirectory"
            class="px-3 py-1.5 rounded-lg bg-[#242730] hover:bg-[#2e333e] border border-[#333844] text-[#e5e7eb] text-xs font-medium flex items-center gap-1.5 transition active:scale-95 cursor-pointer"
          >
            📁 添加文件夹
          </button>

          <button
            @click="triggerAiTagAll"
            :disabled="isAiTagging || isConverting || tasks.length === 0"
            class="px-3 py-1.5 rounded-lg bg-[#10b981]/15 hover:bg-[#10b981]/25 border border-[#10b981]/40 text-[#10b981] text-xs font-semibold flex items-center gap-1.5 transition active:scale-95 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            :title="selectedTaskIds.size > 0 ? '使用视觉模型识别所选贴纸画面并推荐 Emoji' : '使用视觉模型识别全部贴纸画面并推荐 Emoji'"
          >
            {{ isAiTagging ? '正在 AI 匹配...' : (selectedTaskIds.size > 0 ? `✨ AI 匹配 (${selectedTaskIds.size}项)` : '✨ AI 匹配 Emoji') }}
          </button>

          <button
            @click="showSettings = true"
            class="px-3 py-1.5 rounded-lg bg-[#242730] hover:bg-[#2e333e] border border-[#333844] text-[#e5e7eb] text-xs font-medium flex items-center gap-1.5 transition active:scale-95 cursor-pointer"
            title="配置视觉大模型接口与 API Key"
          >
            ⚙️ AI 设置
          </button>

          <button
            @click="clearAllTasks"
            :disabled="isConverting || tasks.length === 0"
            class="px-3 py-1.5 rounded-lg bg-[#242730] hover:bg-red-500/20 hover:text-red-400 border border-[#333844] text-[#e5e7eb] text-xs font-medium flex items-center gap-1.5 transition active:scale-95 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ml-auto"
          >
            🗑️ 清空列表
          </button>
        </div>

        <!-- Stack Container: EmptyDropzone (tasks.length === 0) vs Table (tasks.length > 0) -->
        <div class="flex-1 flex flex-col min-h-0 overflow-hidden relative">
          
          <!-- Dragging Over Full Overlay -->
          <div
            v-if="isDraggingOver"
            class="absolute inset-0 z-40 bg-[#24a1de]/20 backdrop-blur-sm border-2 border-dashed border-[#24a1de] rounded-xl flex flex-col items-center justify-center pointer-events-none transition-all"
          >
            <div class="p-6 rounded-2xl bg-[#16181d]/90 border border-[#24a1de]/50 shadow-2xl flex flex-col items-center gap-2 animate-pulse">
              <Plus class="w-10 h-10 text-[#24a1de]" />
              <p class="text-sm font-semibold text-white">松开鼠标立即导入文件</p>
            </div>
          </div>

          <!-- Empty Dropzone Widget (Faithful to EmptyDropzoneWidget in Python) -->
          <div
            v-if="tasks.length === 0"
            class="flex-1 border-2 border-dashed border-[#282b35] hover:border-[#24a1de]/60 rounded-xl flex flex-col items-center justify-center p-8 gap-3 bg-[#16181d]/40 hover:bg-[#24a1de]/5 transition group"
          >
            <div class="text-5xl leading-none select-none">📥</div>
            <h3 class="text-base font-bold text-white">拖拽图片或视频到这里</h3>
            <p class="text-xs text-[#9ca3af]">支持多文件与文件夹拖拽，自动适配 Telegram 规范</p>

            <div class="flex items-center gap-3 mt-2">
              <button
                @click="handleSelectFiles"
                class="px-4 py-2 rounded-lg bg-[#24a1de] hover:bg-[#2eb5f7] active:bg-[#1d89be] text-white text-xs font-semibold flex items-center gap-1.5 shadow-sm transition cursor-pointer"
              >
                ➕ 添加文件
              </button>
              <button
                @click="handleSelectDirectory"
                class="px-4 py-2 rounded-lg bg-[#252831] hover:bg-[#2e333e] active:bg-[#1c1e25] border border-[#363b47] text-[#e5e7eb] text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer"
              >
                📁 添加文件夹
              </button>
            </div>

            <!-- Format Capsules -->
            <div class="flex items-center gap-1.5 flex-wrap justify-center mt-3 max-w-sm">
              <span
                v-for="fmt in formatChips"
                :key="fmt"
                class="px-2 py-0.5 rounded-full bg-[#1f2229] border border-[#2d313c] text-[10px] text-gray-400 font-mono"
              >
                {{ fmt }}
              </span>
            </div>
          </div>

          <!-- Task Table (Faithful to QTableWidget in Python) -->
          <div v-else class="flex-1 flex flex-col min-h-0 bg-[#15171c] border border-[#252831] rounded-lg overflow-hidden">
            <div class="flex-1 overflow-y-auto" @click="handleBlankClick">
              <table class="w-full text-left text-xs border-collapse">
                <thead class="sticky top-0 bg-[#16181d] z-10 border-b border-[#252831] text-[#9ca3af] font-semibold select-none">
                  <tr>
                    <th class="py-2.5 px-3 w-14 text-center">预览</th>
                    <th class="py-2.5 px-3">原文件名</th>
                    <th class="py-2.5 px-3 w-48 text-center">原规格</th>
                    <th class="py-2.5 px-3 w-56">目标文件名</th>
                    <th class="py-2.5 px-3 w-44">进度与状态</th>
                    <th class="py-2.5 px-3 w-20 text-center">体积</th>
                    <th class="py-2.5 px-3 w-24 text-right">操作</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[#20232b]">
                  <tr
                    v-for="task in tasks"
                    :key="task.taskId"
                    @click.stop="handleRowClick($event, task)"
                    @contextmenu="onRowContextMenu($event, task)"
                    :class="[
                      'transition-colors cursor-pointer select-none group',
                      selectedTaskIds.has(task.taskId) ? 'bg-[#24a1de]/20' : 'hover:bg-[#1f2229]/60'
                    ]"
                  >
                    <!-- 1. 预览 (Thumbnail) -->
                    <td class="py-2 px-3 text-center">
                      <div
                        class="w-11 h-11 mx-auto bg-[#1a1c22] border border-[#2d323e] overflow-hidden relative flex items-center justify-center shrink-0"
                        :class="clampCropRadius(task.cropRadius) > 0.001 ? '' : 'rounded-md'"
                        :style="clampCropRadius(task.cropRadius) > 0.001 ? { borderRadius: `${Math.round(clampCropRadius(task.cropRadius) * 50)}%` } : {}"
                      >
                        <img
                          v-if="streamBaseUrl"
                          :src="getThumbnailUrl(task)"
                          class="w-full h-full object-cover"
                          loading="lazy"
                        />
                        <div v-else class="text-gray-500">
                          <Film v-if="task.mediaInfo.is_video" class="w-4 h-4" />
                          <ImageIcon v-else class="w-4 h-4" />
                        </div>
                        <span
                          v-if="task.mediaInfo.is_video"
                          class="absolute bottom-0.5 right-0.5 bg-black/80 rounded px-0.5 text-[8px] font-mono text-gray-300 leading-tight"
                        >
                          {{ (task.endTime && task.startTime !== undefined ? (task.endTime - task.startTime) : task.mediaInfo.duration).toFixed(1) }}s
                        </span>
                      </div>
                    </td>

                    <!-- 2. 原文件名 + 截取区间/裁切标签 -->
                    <td class="py-2 px-3">
                      <div class="space-y-0.5">
                        <div class="font-medium text-white truncate max-w-[220px]" :title="task.mediaInfo.file_path">
                          {{ task.mediaInfo.file_name }}
                        </div>
                        <div
                          v-if="task.clipLabel || task.crop || (task.cropRadius && task.cropRadius > 0.001)"
                          class="flex items-center gap-1.5 text-[11px] font-mono text-[#2eb5f7]"
                        >
                          <span v-if="task.clipLabel">{{ task.clipLabel }}</span>
                          <span v-if="task.crop" class="text-emerald-400 font-sans text-[10px]">
                            [✂️ {{ cropRadiusLabel(task.cropRadius) }} {{ task.crop[2] }}×{{ task.crop[3] }}]
                          </span>
                          <span
                            v-else-if="task.cropRadius && task.cropRadius > 0.001"
                            class="text-emerald-400 font-sans text-[10px]"
                          >
                            [✂️ {{ cropRadiusLabel(task.cropRadius) }}]
                          </span>
                        </div>
                      </div>
                    </td>

                    <!-- 3. 原规格 -->
                    <td class="py-2 px-3 text-center font-mono text-[11px] text-gray-300">
                      <div v-if="task.mediaInfo.is_video">
                        {{ task.mediaInfo.width }}×{{ task.mediaInfo.height }} | {{ (task.mediaInfo.duration || 0).toFixed(1) }}s | {{ Math.round(task.mediaInfo.fps || 30) }}fps
                        <span v-if="task.mediaInfo.has_alpha" class="text-emerald-400 font-sans ml-1">🟢Alpha</span>
                      </div>
                      <div v-else>
                        {{ task.mediaInfo.width }}×{{ task.mediaInfo.height }} | 静态图
                        <span v-if="task.mediaInfo.has_alpha" class="text-emerald-400 font-sans ml-1">🟢透明</span>
                      </div>
                    </td>

                    <!-- 4. 目标文件名（双击编辑关联 Emoji） -->
                    <td class="py-2 px-3">
                      <input
                        v-if="editingEmojiTaskId === task.taskId"
                        ref="emojiInputRef"
                        v-model="task.emoji"
                        @click.stop
                        @keydown.enter.prevent="commitEmojiEdit(task)"
                        @keydown.escape.prevent="commitEmojiEdit(task)"
                        @blur="commitEmojiEdit(task)"
                        placeholder="输入关联 Emoji（可留空）"
                        class="w-full bg-[#171a21] border border-[#24a1de] px-2 py-1 rounded-md text-xs font-mono text-white text-center focus:outline-none"
                      />
                      <div
                        v-else
                        data-emoji-edit
                        @dblclick.stop="startEmojiEdit(task)"
                        class="bg-[#171a21] border border-[#2d323e] hover:border-[#24a1de] px-2 py-1 rounded-md text-xs font-mono text-gray-200 truncate cursor-text"
                        :title="task.outputPath ? `输出路径: ${task.outputPath}\n双击可修改关联 Emoji` : '双击可修改关联 Emoji'"
                      >
                        {{ computeTargetFilename(task) }}
                      </div>
                    </td>

                    <!-- 5. 进度与状态 -->
                    <td class="py-2 px-3">
                      <div class="space-y-1">
                        <div class="w-full h-2 bg-[#20232b] rounded-full overflow-hidden">
                          <div
                            class="h-full transition-all duration-150"
                            :class="[
                              task.status === 'success' ? 'bg-emerald-500' :
                              task.status === 'failed' ? 'bg-red-500' : 'bg-[#24a1de]'
                            ]"
                            :style="{ width: `${task.progress}%` }"
                          ></div>
                        </div>
                        <div class="flex items-center justify-between text-[11px]">
                          <span
                            :class="[
                              task.status === 'success' ? 'text-emerald-400 font-medium' :
                              task.status === 'failed' ? 'text-red-400 font-medium' :
                              task.status === 'converting' ? 'text-[#2eb5f7]' : 'text-gray-400'
                            ]"
                          >
                            {{ task.statusMsg }}
                          </span>
                          <span v-if="task.status === 'converting'" class="font-mono text-[10px] text-gray-400">
                            {{ task.progress }}%
                          </span>
                        </div>
                      </div>
                    </td>

                    <!-- 6. 体积 -->
                    <td class="py-2 px-3 text-center font-mono text-[11px]">
                      <span v-if="task.outputSize > 0" :class="task.outputSize <= 256 * 1024 ? 'text-emerald-400 font-semibold' : 'text-amber-400 font-semibold'">
                        {{ (task.outputSize / 1024).toFixed(1) }} KB
                      </span>
                      <span v-else class="text-gray-500">
                        {{ (task.mediaInfo.file_size / (1024 * 1024)).toFixed(1) }} MB
                      </span>
                    </td>

                    <!-- 7. 操作 -->
                    <td class="py-2 px-3 text-right">
                      <div class="flex items-center justify-end gap-1">
                        <button
                          @click.stop="openTaskClipModal(task)"
                          class="p-1 rounded hover:bg-[#252831] text-amber-400 transition"
                          :title="task.mediaInfo.is_video ? '截取画面与视频片段' : '裁切画面样式'"
                        >
                          <Scissors class="w-3.5 h-3.5" />
                        </button>
                        <button
                          v-if="task.status === 'success'"
                          @click.stop="openFolder(task.outputPath)"
                          class="p-1 rounded hover:bg-[#252831] text-blue-400 transition"
                          title="打开所在文件夹"
                        >
                          <FolderOpen class="w-3.5 h-3.5" />
                        </button>
                        <button
                          @click.stop="removeTask(task.taskId)"
                          class="p-1 rounded hover:bg-red-500/20 text-gray-400 hover:text-red-400 transition"
                          title="移除此项"
                        >
                          <Trash2 class="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- ================= RIGHT CARD (Settings & Actions Panel) ================= -->
      <!-- Matches right_card in PySide6 MainWindow: 360px wide, cardFrame -->
      <div
        data-panel="settings"
        class="w-[360px] min-w-[320px] max-w-[420px] bg-[#1a1c22] border border-[#282b35] rounded-xl flex flex-col p-3.5 gap-3 shrink-0 overflow-hidden"
      >
        
        <!-- Scrollable Settings Container -->
        <div class="flex-1 overflow-y-auto space-y-3.5 pr-1 text-xs">
          
          <!-- Group 1: 🎯 输出规格 (Segmented Control) -->
          <div class="space-y-1.5">
            <h4 class="text-xs font-bold text-white flex items-center gap-1.5">
              🎯 输出规格
            </h4>
            <div class="grid grid-cols-2 bg-[#15171c] border border-[#282b35] rounded-lg p-1 gap-1">
              <button
                @click="globalOptions.is_custom_emoji = false; saveCurrentSettings()"
                :class="[
                  'py-1.5 px-2 text-xs font-medium rounded-md transition text-center cursor-pointer',
                  !globalOptions.is_custom_emoji
                    ? 'bg-[#24a1de] text-white font-semibold shadow-sm'
                    : 'text-gray-400 hover:text-white'
                ]"
              >
                🎨 标准贴纸 (512px)
              </button>
              <button
                @click="globalOptions.is_custom_emoji = true; saveCurrentSettings()"
                :class="[
                  'py-1.5 px-2 text-xs font-medium rounded-md transition text-center cursor-pointer',
                  globalOptions.is_custom_emoji
                    ? 'bg-[#24a1de] text-white font-semibold shadow-sm'
                    : 'text-gray-400 hover:text-white'
                ]"
              >
                😀 自定义表情 (100px)
              </button>
            </div>
          </div>

          <!-- Group 2: 🎨 编码预设 -->
          <div class="space-y-1.5">
            <h4 class="text-xs font-bold text-white flex items-center gap-1.5">
              🎨 编码预设
            </h4>
            <select
              v-model="globalOptions.preset_style"
              :disabled="isConverting"
              @change="saveCurrentSettings"
              class="w-full bg-[#15171c] border border-[#282b35] hover:border-[#333844] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-[#24a1de] cursor-pointer"
            >
              <option value="anime">🎨 动漫 / 插画（轻度锐化）</option>
              <option value="cinema">🎬 真人实拍（平滑降噪）</option>
              <option value="fast">⚡ 快速导出（单遍编码）</option>
            </select>
          </div>

          <!-- Group 3: 📁 输出目录 -->
          <div class="space-y-1.5">
            <h4 class="text-xs font-bold text-white flex items-center gap-1.5">
              📁 输出目录
            </h4>
            <label class="flex items-center gap-2 cursor-pointer select-none">
              <input
                v-model="globalOptions.same_dir"
                type="checkbox"
                :disabled="isConverting"
                @change="saveCurrentSettings"
                class="rounded bg-[#15171c] border-[#333844] text-[#24a1de] focus:ring-0 w-3.5 h-3.5 cursor-pointer"
              />
              <span class="text-gray-300">保存至原文件所在目录</span>
            </label>

            <div v-if="!globalOptions.same_dir" class="flex items-center gap-2">
              <input
                v-model="globalOptions.custom_output_dir"
                type="text"
                @input="saveCurrentSettings"
                placeholder="选择输出目录..."
                class="flex-1 bg-[#15171c] border border-[#282b35] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-[#24a1de]"
              />
              <button
                @click="selectCustomOutputDir"
                class="px-2.5 py-1.5 bg-[#242730] hover:bg-[#2e333e] border border-[#333844] rounded-lg text-gray-200 text-xs font-medium cursor-pointer"
              >
                浏览...
              </button>
            </div>
          </div>
        </div>

        <!-- Right Bottom Action Buttons (Faithful to PySide6 MainWindow) -->
        <div class="space-y-2 pt-2 border-t border-[#252831] shrink-0">
          <button
            @click="startConversion"
            :disabled="tasks.length === 0 || isConverting"
            class="w-full py-2.5 rounded-lg bg-[#24a1de] hover:bg-[#2eb5f7] active:bg-[#1d89be] text-white text-xs font-bold flex items-center justify-center gap-2 shadow-lg shadow-[#24a1de]/20 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            🚀 开始转换
          </button>

          <button
            @click="cancelConversion"
            :disabled="!isConverting"
            class="w-full py-2 rounded-lg bg-[#ef4444] hover:bg-[#dc2626] active:bg-[#b91c1c] text-white text-xs font-semibold flex items-center justify-center gap-2 transition cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
          >
            🛑 停止
          </button>

          <button
            @click="handleOpenOutputFolder"
            class="w-full py-2 rounded-lg bg-[#242730] hover:bg-[#2e333e] border border-[#333844] text-gray-200 text-xs font-medium flex items-center justify-center gap-2 transition cursor-pointer"
          >
            📂 打开输出目录
          </button>
        </div>
      </div>
    </div>

    <!-- 3. Bottom Collapsible Log Drawer (Faithful to PySide6 CollapsibleLogDrawer) -->
    <div class="bg-[#16181d] border border-[#252831] rounded-lg shrink-0 flex flex-col overflow-hidden transition-all duration-200">
      <!-- Handle Bar -->
      <div
        @click="isLogOpen = !isLogOpen"
        class="h-9 px-3 flex items-center justify-between cursor-pointer select-none text-xs text-gray-300 hover:bg-[#1f2229]/60"
      >
        <div class="flex items-center gap-2 font-semibold">
          <span>📋 运行日志</span>
        </div>

        <div class="text-[11px] text-gray-400 font-mono truncate max-w-md">
          {{ statusSummaryText }}
        </div>

        <div class="flex items-center gap-2">
          <button
            @click.stop="logs = []"
            class="px-2 py-0.5 rounded text-[11px] text-gray-400 hover:text-white hover:bg-[#252831] transition"
          >
            清空日志
          </button>
          <ChevronUp v-if="!isLogOpen" class="w-4 h-4 text-gray-400" />
          <ChevronDown v-else class="w-4 h-4 text-gray-400" />
        </div>
      </div>

      <!-- Drawer Log Content -->
      <div
        v-if="isLogOpen"
        ref="logContainer"
        class="h-44 bg-[#121316] border-t border-[#252831] p-3 overflow-y-auto font-mono text-[11px] text-gray-300 space-y-1"
      >
        <div v-if="logs.length === 0" class="text-gray-600 italic">暂无输出日志...</div>
        <div v-for="(log, idx) in logs" :key="idx" class="leading-relaxed whitespace-pre-wrap">
          {{ log }}
        </div>
      </div>
    </div>

    <!-- Custom Right-Click Context Menu -->
    <div
      v-if="contextMenu.visible && contextMenu.task"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      data-skip-deselect
      class="fixed z-50 bg-[#16181d] border border-[#282b35] rounded-xl shadow-2xl p-1 text-xs text-gray-200 min-w-[170px] space-y-0.5 select-none"
    >
      <template v-if="selectedTaskIds.size > 1">
        <button
          @click="triggerAiTagAll(); contextMenu.visible = false"
          class="w-full text-left px-3 py-2 rounded-lg hover:bg-[#24a1de] hover:text-white flex items-center gap-2 transition cursor-pointer"
        >
          ✨ AI 识别选中项 ({{ selectedTaskIds.size }})
        </button>

        <div class="h-px bg-[#252831] my-1"></div>

        <button
          @click="selectAll(); contextMenu.visible = false"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#252831] hover:text-white flex items-center justify-between text-gray-300 transition cursor-pointer"
        >
          <span>全选</span>
          <span class="text-[10px] text-gray-500 font-mono">Ctrl+A</span>
        </button>
        <button
          @click="invertSelection(); contextMenu.visible = false"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#252831] hover:text-white flex items-center gap-2 text-gray-300 transition cursor-pointer"
        >
          反选
        </button>
        <button
          @click="clearSelection(); contextMenu.visible = false"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#252831] hover:text-white flex items-center gap-2 text-gray-300 transition cursor-pointer"
        >
          取消选择
        </button>

        <div class="h-px bg-[#252831] my-1"></div>

        <button
          @click="removeSelectedTasks(); contextMenu.visible = false"
          class="w-full text-left px-3 py-2 rounded-lg hover:bg-red-500 hover:text-white flex items-center justify-between text-red-400 transition cursor-pointer"
        >
          <span>🗑️ 移除选中项 ({{ selectedTaskIds.size }})</span>
          <span class="text-[10px] opacity-70 font-mono">Del</span>
        </button>
      </template>

      <template v-else>
        <button
          @click="openTaskClipModal(contextMenu.task!); contextMenu.visible = false"
          class="w-full text-left px-3 py-2 rounded-lg hover:bg-[#24a1de] hover:text-white flex items-center gap-2 transition cursor-pointer"
        >
          {{ contextMenu.task.mediaInfo.is_video ? '✂️ 截取与裁切' : '✂️ 裁切画面' }}
        </button>

        <button
          @click="aiTagSingle(contextMenu.task!); contextMenu.visible = false"
          class="w-full text-left px-3 py-2 rounded-lg hover:bg-[#24a1de] hover:text-white flex items-center gap-2 transition cursor-pointer"
        >
          ✨ AI 识别此项 Emoji
        </button>

        <button
          v-if="contextMenu.task.status === 'success'"
          @click="openFolder(contextMenu.task!.outputPath); contextMenu.visible = false"
          class="w-full text-left px-3 py-2 rounded-lg hover:bg-[#24a1de] hover:text-white flex items-center gap-2 transition cursor-pointer"
        >
          📂 打开所在目录
        </button>

        <div class="h-px bg-[#252831] my-1"></div>

        <button
          @click="selectAll(); contextMenu.visible = false"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#252831] hover:text-white flex items-center justify-between text-gray-300 transition cursor-pointer"
        >
          <span>全选</span>
          <span class="text-[10px] text-gray-500 font-mono">Ctrl+A</span>
        </button>
        <button
          @click="invertSelection(); contextMenu.visible = false"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#252831] hover:text-white flex items-center gap-2 text-gray-300 transition cursor-pointer"
        >
          反选
        </button>

        <div class="h-px bg-[#252831] my-1"></div>

        <button
          @click="removeTask(contextMenu.task!.taskId); contextMenu.visible = false"
          class="w-full text-left px-3 py-2 rounded-lg hover:bg-red-500 hover:text-white flex items-center justify-between text-red-400 transition cursor-pointer"
        >
          <span>🗑️ 移除此项</span>
          <span class="text-[10px] opacity-70 font-mono">Del</span>
        </button>
      </template>
    </div>

    <!-- Modals -->
    <!-- Video Clip Modal -->
    <VideoClipModal
      v-if="activeClipTask"
      :media-info="activeClipTask.mediaInfo"
      :stream-base-url="streamBaseUrl"
      :initial-start-time="activeClipTask.startTime"
      :initial-end-time="activeClipTask.endTime"
      :initial-crop="activeClipTask.crop"
      :initial-crop-radius="activeClipTask.cropRadius"
      :initial-emoji="activeClipTask.emoji"
      @close="activeClipTask = null"
      @confirm="handleClipsGenerated"
    />

    <!-- Settings Modal -->
    <SettingsModal
      v-model="showSettings"
      @saved="initPywebview"
    />
  </div>
</template>
