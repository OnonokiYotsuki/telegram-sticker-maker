<template>
  <div data-skip-deselect class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-[#141720] border border-[#262a35] rounded-xl w-full max-w-[1240px] h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
      
      <!-- Top Bar -->
      <div class="flex items-center justify-between px-5 py-3 border-b border-[#232731] bg-[#171922]">
        <div class="flex items-center space-x-2">
          <span class="text-lg">✂️</span>
          <span class="font-bold text-white text-sm truncate max-w-md">{{ mediaInfo.file_name }}</span>
        </div>
        <div class="text-xs text-slate-400 font-mono flex items-center space-x-3">
          <span v-if="isVideo">时长: <b class="text-sky-400">{{ formatTime(mediaInfo.duration) }}</b></span>
          <span v-if="isVideo">|</span>
          <span>{{ mediaInfo.width }}×{{ mediaInfo.height }}</span>
          <template v-if="isVideo">
            <span>|</span>
            <span>{{ Math.round(mediaInfo.fps) }} fps</span>
            <span>|</span>
            <span>{{ mediaInfo.video_codec }}</span>
          </template>
        </div>
      </div>

      <!-- Main Body: 2 Columns Split -->
      <div class="flex-1 flex overflow-hidden">
        
        <!-- Left Column: Video Preview & Controls -->
        <div class="flex-1 flex flex-col p-4 space-y-3 min-w-0">
          
          <!-- Video Screen Container -->
          <div class="flex-1 bg-black rounded-lg border border-[#232731] relative flex items-center justify-center overflow-hidden min-h-[320px]">
            <video
              v-if="isVideo"
              ref="videoRef"
              :src="streamUrl"
              class="max-w-full max-h-full object-contain pointer-events-auto"
              @timeupdate="onTimeUpdate"
              @loadedmetadata="onLoadedMetadata"
              @canplay="onCanPlay"
              @error="onVideoError"
              @play="isPlaying = true"
              @pause="isPlaying = false"
              @click="togglePlay"
            />
            <img
              v-else
              :src="imagePreviewUrl"
              class="max-w-full max-h-full object-contain pointer-events-none"
              alt="裁切预览"
            />

            <!-- Crop Overlay -->
            <CropOverlay
              v-if="cropActive"
              ref="cropOverlayRef"
              :video-width="mediaInfo.width"
              :video-height="mediaInfo.height"
              :aspect-mode="aspectMode"
              :radius="cropRadius"
              v-model="currentCrop"
              @change="onCropChange"
            />
          </div>

          <!-- Controls Card -->
          <div class="bg-[#171922] border border-[#262a35] rounded-lg p-3 space-y-2">
            
            <!-- Timeline Scrubber -->
            <div v-if="isVideo" class="flex items-center space-x-3">
              <span class="text-xs font-mono font-semibold text-sky-400 w-16 text-right">
                {{ formatTime(currentTime) }}
              </span>
              <input
                type="range"
                min="0"
                :max="mediaInfo.duration"
                step="0.01"
                :value="currentTime"
                @input="onSliderInput"
                class="flex-1 h-1.5 bg-[#252833] rounded-lg appearance-none cursor-pointer accent-sky-500"
              />
              <span class="text-xs font-mono text-slate-400 w-16">
                {{ formatTime(mediaInfo.duration) }}
              </span>
            </div>

            <div v-if="!isVideo" class="flex items-center justify-between pt-1">
              <button
                @click="toggleCrop"
                :class="[
                  'px-3 py-1 rounded font-semibold transition text-xs',
                  cropActive ? 'bg-sky-500 hover:bg-sky-400 text-white' : 'btn-subtle text-sky-400'
                ]"
                title="开启/关闭画面裁切框"
              >
                ✂️ 画面裁切
              </button>
              <button
                @click="showClipSettings = true"
                class="btn-subtle px-2 py-1 text-xs"
                title="裁剪窗口设置"
              >
                ⚙️
              </button>
            </div>

            <!-- Button Bar -->
            <div v-if="isVideo" class="flex items-center justify-between pt-1">
              <div class="flex items-center space-x-1.5 text-xs">
                <!-- Dual-gear seek -->
                <button
                  @click="seekRelative(-largeStep)"
                  class="btn-subtle px-2.5 py-1"
                  :title="`大快退 -${largeStep}s`"
                >
                  ⏪ -{{ largeStep }}s
                </button>
                <button
                  @click="seekRelative(-smallStep)"
                  class="btn-subtle px-2.5 py-1"
                  :title="`小快退 -${smallStep}s`"
                >
                  ⏮️ -{{ smallStep }}s
                </button>

                <!-- Play / Pause -->
                <button
                  @click="togglePlay"
                  class="bg-sky-500 hover:bg-sky-400 text-white font-semibold px-4 py-1 rounded transition"
                >
                  {{ isPlaying ? '⏸️ 暂停' : '▶️ 播放' }}
                </button>

                <!-- Dual-gear forward -->
                <button
                  @click="seekRelative(smallStep)"
                  class="btn-subtle px-2.5 py-1"
                  :title="`小快进 +${smallStep}s`"
                >
                  +{{ smallStep }}s ⏭️
                </button>
                <button
                  @click="seekRelative(largeStep)"
                  class="btn-subtle px-2.5 py-1"
                  :title="`大快进 +${largeStep}s`"
                >
                  +{{ largeStep }}s ⏩
                </button>

                <div class="h-4 w-px bg-slate-700 mx-1" />

                <!-- Set Start / End -->
                <button
                  @click="setCurrentAsStart"
                  class="btn-subtle px-2.5 py-1"
                  title="设当前时刻为起点 (快捷键 [)"
                >
                  🚩
                </button>
                <button
                  @click="setCurrentAsEnd"
                  :disabled="!canSetEnd"
                  :class="[
                    'btn-subtle px-2.5 py-1',
                    !canSetEnd ? 'opacity-40 cursor-not-allowed' : ''
                  ]"
                  :title="canSetEnd ? '设当前时刻为终点 (快捷键 ])' : '终点必须晚于起点'"
                >
                  🏁
                </button>

                <!-- Crop Toggle -->
                <button
                  @click="toggleCrop"
                  :class="[
                    'px-3 py-1 rounded font-semibold transition',
                    cropActive ? 'bg-sky-500 hover:bg-sky-400 text-white' : 'btn-subtle text-sky-400'
                  ]"
                  title="开启/关闭画面裁切框"
                >
                  ✂️ 画面裁切
                </button>
              </div>

              <div class="flex items-center shrink-0">
                <button
                  @click="toggleMute"
                  class="text-slate-400 hover:text-white text-base px-2"
                  title="切换静音"
                >
                  {{ isMuted ? '🔇' : '🔊' }}
                </button>
                <button
                  @click="showClipSettings = true"
                  class="btn-subtle px-2 py-1 ml-0.5"
                  title="裁剪窗口设置"
                >
                  ⚙️
                </button>
              </div>
            </div>

            <!-- Crop Toolbar (when crop active) -->
            <div v-if="cropActive" class="pt-2 border-t border-[#262a35] space-y-2 text-xs animate-in slide-in-from-top-1 duration-100">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2">
                  <span class="text-slate-300 font-semibold">✂️ 裁切比例:</span>
                  <select
                    v-model="aspectMode"
                    class="bg-[#1e222b] border border-[#334155] text-slate-200 rounded px-2 py-1 text-xs outline-none focus:border-sky-500"
                  >
                    <option v-for="opt in cropAspectOptions" :key="opt.value" :value="opt.value">
                      {{ opt.label }}
                    </option>
                  </select>

                  <button
                    @click="resetCropCenter"
                    class="btn-subtle px-2.5 py-1 text-slate-300"
                    title="将裁切框居中重置"
                  >
                    🔄 重置居中
                  </button>

                  <button
                    v-if="isVideo"
                    @click="applyCropToAll"
                    class="btn-subtle px-2.5 py-1 text-sky-300 hover:text-sky-200"
                    title="应用当前裁切区域至所有片段"
                  >
                    📌 应用于所有片段
                  </button>
                </div>

                <div class="font-mono text-sky-400 font-semibold">
                  📍 尺寸: {{ currentCrop ? `${currentCrop[2]}×${currentCrop[3]}` : '未裁切' }}
                </div>
              </div>

              <div class="flex items-center space-x-2">
                <span class="text-slate-300 font-semibold whitespace-nowrap">圆角:</span>
                <span class="text-slate-500 text-[11px]">直角</span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  :value="Math.round(cropRadius * 100)"
                  @input="onRadiusInput"
                  class="flex-1 h-1.5 bg-[#252833] rounded-lg appearance-none cursor-pointer accent-sky-500"
                  title="0 直角，100 圆形"
                />
                <span class="text-slate-500 text-[11px]">圆形</span>
                <span class="font-mono text-sky-400 w-16 text-right">{{ cropRadiusLabel(cropRadius) }}</span>
              </div>
            </div>

          </div>
        </div>

        <!-- Right Column: Clips Management List -->
        <div v-if="isVideo" class="w-80 border-l border-[#232731] bg-[#161822] flex flex-col">
          
          <div class="px-4 py-3 border-b border-[#232731] flex items-center justify-between">
            <span class="font-bold text-xs text-slate-200">📋 待添加片段列表</span>
            <span class="text-xs text-slate-400">共 {{ clips.length }} 个片段</span>
          </div>

          <!-- Clips Table List -->
          <div class="flex-1 overflow-y-auto p-2 space-y-2">
            <div
              v-for="(clip, idx) in clips"
              :key="clip.id"
              :class="[
                'p-2.5 rounded-lg border transition cursor-pointer flex items-center space-x-3',
                selectedClipIdx === idx
                  ? 'bg-[#1e2330] border-sky-500/60 shadow'
                  : 'bg-[#171922] border-[#252833] hover:border-slate-700'
              ]"
              @click="selectClip(idx)"
            >
              <!-- Thumbnail -->
              <div
                class="w-11 h-11 bg-black overflow-hidden flex-shrink-0 flex items-center justify-center border border-slate-800 rounded"
              >
                <img
                  v-if="clipThumbnails[clip.id]"
                  :src="clipThumbnails[clip.id]"
                  class="w-full h-full object-cover"
                />
                <span v-else class="text-base">🎬</span>
              </div>

              <!-- Time inputs & info -->
              <div class="flex-1 min-w-0 space-y-1">
                <div class="flex items-center space-x-1.5 text-xs font-mono">
                  <input
                    type="text"
                    :value="formatTime(clip.startTime)"
                    @change="onClipStartChange(idx, ($event.target as HTMLInputElement).value)"
                    class="w-16 bg-[#11131a] border border-[#2b3040] rounded px-1 text-center text-slate-200 focus:border-sky-500 outline-none text-[11px]"
                  />
                  <span class="text-slate-500">-</span>
                  <input
                    type="text"
                    :value="formatTime(clip.endTime)"
                    @change="onClipEndChange(idx, $event)"
                    class="w-16 bg-[#11131a] border border-[#2b3040] rounded px-1 text-center text-slate-200 focus:border-sky-500 outline-none text-[11px]"
                  />
                </div>
                <div class="text-[11px] text-slate-400 flex items-center space-x-2">
                  <span class="font-semibold text-slate-300">{{ (clip.endTime - clip.startTime).toFixed(2) }}s</span>
                  <span v-if="clip.crop" class="text-sky-400 font-mono text-[10px] bg-sky-950/60 px-1 rounded border border-sky-800/40">
                    [✂️ {{ cropRadiusLabel(clip.cropRadius) }} {{ clip.crop[2] }}×{{ clip.crop[3] }}]
                  </span>
                </div>
              </div>

              <!-- Actions -->
              <div class="flex flex-col space-y-1">
                <button
                  @click.stop="playClip(idx)"
                  :class="[
                    'p-1 rounded text-xs',
                    isLooping && selectedClipIdx === idx
                      ? 'text-emerald-400 bg-emerald-950/50 hover:bg-emerald-900/50'
                      : 'text-slate-400 hover:text-sky-400 hover:bg-slate-800'
                  ]"
                  :title="isLooping && selectedClipIdx === idx ? '停止循环播放' : '循环播放此片段'"
                >
                  {{ isLooping && selectedClipIdx === idx ? '⏸️' : '▶️' }}
                </button>
                <button
                  @click.stop="deleteClip(idx)"
                  class="p-1 text-slate-400 hover:text-rose-400 hover:bg-rose-950/40 rounded text-xs"
                  title="删除此片段"
                >
                  🗑️
                </button>
              </div>
            </div>
          </div>

          <!-- Add Clip Actions -->
          <div class="p-3 border-t border-[#232731] grid grid-cols-2 gap-2">
            <button
              @click="addNewClip"
              class="bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs py-2 rounded flex items-center justify-center space-x-1 transition"
            >
              <span>➕ 添加片段</span>
            </button>
            <button
              @click="addNextClip"
              class="bg-[#202530] hover:bg-[#282f3d] border border-[#333b4d] text-slate-200 text-xs py-2 rounded flex items-center justify-center space-x-1 transition"
            >
              <span>⚡ 顺延 (+2.5s)</span>
            </button>
          </div>

        </div>

      </div>

      <!-- Footer Bar -->
      <div class="px-5 py-3 border-t border-[#232731] bg-[#171922] flex items-center justify-end space-x-3">
        <button
          @click="$emit('close')"
          class="btn-subtle px-4 py-1.5 text-xs font-semibold"
        >
          取消
        </button>
        <button
          @click="confirmClips"
          class="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold px-5 py-1.5 rounded text-xs shadow transition flex items-center space-x-1.5"
        >
          <span>{{ isVideo ? `✔ 确认并添加到贴纸列表 (共 ${clips.length} 个)` : '✔ 确认裁切' }}</span>
        </button>
      </div>

    </div>

    <!-- Clip Window Settings -->
    <div v-if="showClipSettings" class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div class="bg-[#1b1f2b] border border-[#334155] rounded-lg p-5 w-[22rem] space-y-4 shadow-2xl animate-in fade-in zoom-in-95 duration-100">
        <h3 class="font-bold text-sm text-slate-100">⚙️ 裁剪窗口设置</h3>
        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-slate-400 mb-1">小快退/快进步长 (秒):</label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="60"
              v-model.number="smallStep"
              class="w-full bg-[#12141a] border border-[#334155] rounded px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500 font-mono"
            />
          </div>
          <div>
            <label class="block text-slate-400 mb-1">大快退/快进步长 (秒):</label>
            <input
              type="number"
              step="0.5"
              min="0.5"
              max="300"
              v-model.number="largeStep"
              class="w-full bg-[#12141a] border border-[#334155] rounded px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500 font-mono"
            />
          </div>
          <div class="h-px bg-[#2a3140]" />
          <div>
            <label class="block text-slate-400 mb-1">默认裁切比例:</label>
            <select
              v-model="defaultCropAspect"
              class="w-full bg-[#12141a] border border-[#334155] rounded px-2.5 py-1.5 text-slate-100 outline-none focus:border-sky-500"
            >
              <option v-for="opt in cropAspectOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <p class="text-[11px] text-slate-500 mt-1">新开启裁切、新片段时使用</p>
          </div>
          <div>
            <label class="block text-slate-400 mb-1">默认圆角:</label>
            <div class="flex items-center space-x-2">
              <span class="text-slate-500 text-[11px] shrink-0">直角</span>
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                :value="Math.round(defaultCropRadius * 100)"
                @input="onDefaultRadiusInput"
                class="flex-1 h-1.5 bg-[#252833] rounded-lg appearance-none cursor-pointer accent-sky-500"
              />
              <span class="text-slate-500 text-[11px] shrink-0">圆形</span>
              <span class="font-mono text-sky-400 w-16 text-right">{{ cropRadiusLabel(defaultCropRadius) }}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center justify-between pt-2">
          <button
            @click="resetClipSettings"
            class="text-xs text-slate-400 hover:text-slate-200 underline"
          >
            重置默认
          </button>
          <button
            @click="saveClipSettings"
            class="bg-sky-500 hover:bg-sky-400 text-white font-semibold text-xs px-3.5 py-1.5 rounded transition"
          >
            确定
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import CropOverlay from './CropOverlay.vue'
import {
  clampCropRadius,
  cropRadiusLabel,
  type MediaInfo,
  type ClipItem
} from '../types'

const props = defineProps<{
  mediaInfo: MediaInfo
  streamBaseUrl: string
  initialStartTime?: number
  initialEndTime?: number
  initialCrop?: [number, number, number, number]
  initialCropRadius?: number
  initialEmoji?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', clips: ClipItem[]): void
}>()

const videoRef = ref<HTMLVideoElement | null>(null)
const cropOverlayRef = ref<any>(null)

const isPlaying = ref(false)
const isMuted = ref(false)
const currentTime = ref(0)
const isLooping = ref(false)

const smallStep = ref(0.5)
const largeStep = ref(5.0)
const showClipSettings = ref(false)
const cropAspectOptions = [
  { value: '1:1', label: '1:1 (贴纸/Emoji 推荐)' },
  { value: 'free', label: '自由比例' },
  { value: 'original', label: '原始比例' },
  { value: '16:9', label: '16:9 (横屏)' },
  { value: '4:3', label: '4:3 (经典)' },
  { value: '9:16', label: '9:16 (竖屏)' },
]
const defaultCropAspect = ref('1:1')
const defaultCropRadius = ref(0)

const isVideo = computed(() => !!props.mediaInfo.is_video)
const cropActive = ref(!!props.initialCrop || !props.mediaInfo.is_video)
const aspectMode = ref('1:1')
const cropRadius = ref(clampCropRadius(props.initialCropRadius))
const currentCrop = ref<[number, number, number, number] | null>(props.initialCrop || null)

const selectedClipIdx = ref(0)
const initStart = props.initialStartTime ?? 0
const initEnd = props.initialEndTime ?? Math.min(2.5, props.mediaInfo.duration)
const clips = ref<ClipItem[]>([
  {
    id: 'clip-1',
    startTime: initStart,
    endTime: initEnd,
    duration: Math.max(0.1, initEnd - initStart),
    emoji: props.initialEmoji ?? '',
    crop: props.initialCrop,
    cropRadius: clampCropRadius(props.initialCropRadius)
  }
])

const clipThumbnails = ref<Record<string, string>>({})

// MP4/WebM/Ogg are Range-seekable. MKV and others are an FFmpeg pipe; setting
// video.currentTime only jumps the UI clock, then the live fragments pull it back.
const RANGE_SEEK_EXTS = ['.mp4', '.webm', '.ogg']
const nativeRangeSeek = computed(() => {
  const p = (props.mediaInfo.file_path || '').toLowerCase()
  const dot = p.lastIndexOf('.')
  return dot >= 0 && RANGE_SEEK_EXTS.includes(p.slice(dot))
})
const streamOffset = ref(0)
const streamReloadNonce = ref(0)
const isReloading = ref(false)
const pendingPlay = ref(false)
let queuedServerSeek: number | null = null
let serverSeekTimer: ReturnType<typeof setTimeout> | null = null

const streamUrl = computed(() => {
  const enc = encodeURIComponent(props.mediaInfo.file_path)
  const params = [`path=${enc}`]
  if (!nativeRangeSeek.value && streamOffset.value > 0.001) {
    params.push(`t=${streamOffset.value.toFixed(3)}`)
  }
  if (streamReloadNonce.value) {
    params.push(`_=${streamReloadNonce.value}`)
  }
  return `${props.streamBaseUrl}/stream?${params.join('&')}`
})

const imagePreviewUrl = computed(() => {
  const enc = encodeURIComponent(props.mediaInfo.file_path)
  return `${props.streamBaseUrl}/thumbnail?path=${enc}&size=1280`
})

const formatTime = (sec: number) => {
  if (isNaN(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = sec % 60
  const ms = Math.floor((s - Math.floor(s)) * 1000)
  const pad = (n: number, z = 2) => String(n).padStart(z, '0')
  return `${pad(m)}:${pad(Math.floor(s))}.${pad(ms, 3)}`
}

const parseTime = (str: string): number | null => {
  const clean = str.trim()
  if (clean.includes(':')) {
    const parts = clean.split(':')
    if (parts.length === 2) {
      return parseFloat(parts[0]) * 60 + parseFloat(parts[1])
    }
  }
  const val = parseFloat(clean)
  return isNaN(val) ? null : val
}

const stopLooping = () => {
  isLooping.value = false
}

const togglePlay = () => {
  if (!videoRef.value) return
  if (videoRef.value.paused) {
    videoRef.value.play()
  } else {
    videoRef.value.pause()
    stopLooping()
  }
}

const toggleMute = () => {
  if (!videoRef.value) return
  videoRef.value.muted = !videoRef.value.muted
  isMuted.value = videoRef.value.muted
}

const clampTime = (t: number) =>
  Math.max(0, Math.min(props.mediaInfo.duration || 0, t))

const playbackClock = () => {
  if (!videoRef.value) return currentTime.value
  return streamOffset.value + videoRef.value.currentTime
}

const restartStream = (absolute: number) => {
  const target = clampTime(absolute)
  const v = videoRef.value
  if (v && !v.paused) pendingPlay.value = true
  if (v) v.pause()
  isReloading.value = true
  currentTime.value = target
  if (Math.abs(streamOffset.value - target) < 0.0005) {
    streamReloadNonce.value += 1
  }
  streamOffset.value = target
}

const seekTo = (absolute: number) => {
  const target = clampTime(absolute)
  currentTime.value = target
  if (!videoRef.value) return

  if (nativeRangeSeek.value) {
    videoRef.value.currentTime = target
    return
  }

  isReloading.value = true
  queuedServerSeek = target
  if (serverSeekTimer != null) clearTimeout(serverSeekTimer)
  serverSeekTimer = setTimeout(() => {
    serverSeekTimer = null
    const t = queuedServerSeek
    queuedServerSeek = null
    if (t != null) restartStream(t)
  }, 100)
}

const seekRelative = (delta: number) => {
  stopLooping()
  const base = isReloading.value ? currentTime.value : playbackClock()
  seekTo(base + delta)
}

const onSliderInput = (e: Event) => {
  stopLooping()
  seekTo(parseFloat((e.target as HTMLInputElement).value))
}

const onTimeUpdate = () => {
  if (!videoRef.value || isReloading.value) return
  currentTime.value = playbackClock()

  if (isLooping.value) {
    const curClip = clips.value[selectedClipIdx.value]
    if (curClip && curClip.endTime > curClip.startTime) {
      if (currentTime.value >= curClip.endTime || currentTime.value < curClip.startTime - 0.2) {
        seekTo(curClip.startTime)
      }
    }
  }
}

const onLoadedMetadata = () => {
  if (videoRef.value) {
    videoRef.value.volume = 0.5
  }
}

const onCanPlay = () => {
  if (!isReloading.value) return
  isReloading.value = false
  if (pendingPlay.value && videoRef.value) {
    pendingPlay.value = false
    videoRef.value.play()
  }
}

const onVideoError = () => {
  isReloading.value = false
}

const toggleCrop = () => {
  const curClip = clips.value[selectedClipIdx.value]
  const turningOn = !cropActive.value
  if (turningOn && curClip && !curClip.crop) {
    aspectMode.value = defaultCropAspect.value
    cropRadius.value = defaultCropRadius.value
    currentCrop.value = null
  }
  cropActive.value = turningOn
  if (curClip) {
    if (cropActive.value) {
      if (curClip.crop) {
        currentCrop.value = [...curClip.crop]
        cropRadius.value = clampCropRadius(curClip.cropRadius)
      } else if (cropOverlayRef.value) {
        cropOverlayRef.value.resetToDefault()
        curClip.crop = currentCrop.value ? [...currentCrop.value] : undefined
        curClip.cropRadius = cropRadius.value
      } else {
        curClip.cropRadius = cropRadius.value
      }
    } else {
      curClip.crop = undefined
      curClip.cropRadius = 0
      currentCrop.value = null
      cropRadius.value = 0
    }
    refreshThumbnail(curClip)
  }
}

const onRadiusInput = (e: Event) => {
  const pct = parseFloat((e.target as HTMLInputElement).value)
  cropRadius.value = clampCropRadius(pct / 100)
  const curClip = clips.value[selectedClipIdx.value]
  if (curClip) {
    curClip.cropRadius = cropRadius.value
    if (currentCrop.value) curClip.crop = [...currentCrop.value]
    refreshThumbnail(curClip)
  }
}

const resetCropCenter = () => {
  if (cropOverlayRef.value) {
    cropOverlayRef.value.resetToDefault()
  }
}

const applyCropToAll = () => {
  if (!currentCrop.value) return
  const cropCopy = [...currentCrop.value] as [number, number, number, number]
  const radiusCopy = cropRadius.value
  clips.value.forEach(c => {
    c.crop = [...cropCopy]
    c.cropRadius = radiusCopy
    refreshThumbnail(c)
  })
}

const onCropChange = (crop: [number, number, number, number]) => {
  const curClip = clips.value[selectedClipIdx.value]
  if (curClip) {
    curClip.crop = [...crop]
    curClip.cropRadius = cropRadius.value
    refreshThumbnail(curClip)
  }
}

const canSetEnd = computed(() => {
  const curClip = clips.value[selectedClipIdx.value]
  return !!curClip && currentTime.value > curClip.startTime + 0.001
})

const setCurrentAsStart = () => {
  const curClip = clips.value[selectedClipIdx.value]
  if (curClip) {
    curClip.startTime = Number(currentTime.value.toFixed(3))
    if (curClip.endTime <= curClip.startTime) {
      curClip.endTime = Math.min(curClip.startTime + 2.5, props.mediaInfo.duration)
    }
    curClip.duration = curClip.endTime - curClip.startTime
    refreshThumbnail(curClip)
  }
}

const setCurrentAsEnd = () => {
  const curClip = clips.value[selectedClipIdx.value]
  if (!curClip) return
  const t = Number(currentTime.value.toFixed(3))
  if (t <= curClip.startTime) return
  curClip.endTime = t
  curClip.duration = curClip.endTime - curClip.startTime
}

const selectClip = (idx: number) => {
  selectedClipIdx.value = idx
  const curClip = clips.value[idx]
  if (!curClip) return

  if (videoRef.value) {
    seekTo(curClip.startTime)
  }

  if (curClip.crop) {
    cropActive.value = true
    currentCrop.value = [...curClip.crop]
    cropRadius.value = clampCropRadius(curClip.cropRadius)
  } else {
    cropActive.value = false
    currentCrop.value = null
    cropRadius.value = 0
  }
}

const playClip = (idx: number) => {
  if (isLooping.value && selectedClipIdx.value === idx && videoRef.value && !videoRef.value.paused) {
    videoRef.value.pause()
    stopLooping()
    return
  }
  pendingPlay.value = true
  isLooping.value = true
  selectClip(idx)
  if (nativeRangeSeek.value) videoRef.value?.play()
}

const deleteClip = (idx: number) => {
  if (clips.value.length <= 1) {
    alert('请至少保留一个片段！')
    return
  }
  clips.value.splice(idx, 1)
  if (selectedClipIdx.value >= clips.value.length) {
    selectedClipIdx.value = clips.value.length - 1
  }
  selectClip(selectedClipIdx.value)
}

const addNewClip = () => {
  const last = clips.value[clips.value.length - 1]
  const newStart = last ? Math.min(last.endTime, props.mediaInfo.duration) : 0
  const newEnd = Math.min(newStart + 2.5, props.mediaInfo.duration)
  const newClip: ClipItem = {
    id: `clip-${Date.now()}`,
    startTime: newStart,
    endTime: newEnd,
    duration: newEnd - newStart,
    emoji: '',
    crop: cropActive.value && currentCrop.value ? [...currentCrop.value] : undefined,
    cropRadius: cropActive.value ? cropRadius.value : 0
  }
  clips.value.push(newClip)
  selectClip(clips.value.length - 1)
  refreshThumbnail(newClip)
}

const addNextClip = () => {
  addNewClip()
}

const onClipStartChange = (idx: number, val: string) => {
  const t = parseTime(val)
  if (t !== null && clips.value[idx]) {
    clips.value[idx].startTime = t
    clips.value[idx].duration = Math.max(0, clips.value[idx].endTime - t)
    refreshThumbnail(clips.value[idx])
  }
}

const onClipEndChange = (idx: number, e: Event) => {
  const el = e.target as HTMLInputElement
  const clip = clips.value[idx]
  const t = parseTime(el.value)
  if (!clip || t === null || t <= clip.startTime) {
    el.value = formatTime(clip?.endTime ?? 0)
    return
  }
  clip.endTime = t
  clip.duration = t - clip.startTime
}

const refreshThumbnail = (clip: ClipItem) => {
  const enc = encodeURIComponent(props.mediaInfo.file_path)
  let url = `${props.streamBaseUrl}/thumbnail?path=${enc}&t=${clip.startTime}&size=88`
  if (clip.crop) {
    url += `&crop=${clip.crop.join(',')}`
  }
  if (clip.cropRadius && clip.cropRadius > 0.001) {
    url += `&radius=${clip.cropRadius}`
  }
  clipThumbnails.value[clip.id] = url
}

const onDefaultRadiusInput = (e: Event) => {
  defaultCropRadius.value = clampCropRadius(parseFloat((e.target as HTMLInputElement).value) / 100)
}

const resetClipSettings = () => {
  smallStep.value = 0.5
  largeStep.value = 5.0
  defaultCropAspect.value = '1:1'
  defaultCropRadius.value = 0
}

const saveClipSettings = () => {
  showClipSettings.value = false
  if ((window as any).pywebview?.api?.save_settings) {
    ;(window as any).pywebview.api.save_settings({
      small_step_sec: smallStep.value,
      large_step_sec: largeStep.value,
      default_crop_aspect: defaultCropAspect.value,
      default_crop_radius: defaultCropRadius.value,
    })
  }
}

const confirmClips = () => {
  if (isVideo.value) {
    for (const c of clips.value) {
      if (c.endTime <= c.startTime) {
        alert(`时间区间无效：${formatTime(c.startTime)} - ${formatTime(c.endTime)}，结束时间必须大于开始时间`)
        return
      }
    }
  }
  const curClip = clips.value[selectedClipIdx.value]
  if (curClip && cropActive.value && currentCrop.value) {
    curClip.crop = [...currentCrop.value]
    curClip.cropRadius = cropRadius.value
  }
  emit('confirm', clips.value)
}

// Hotkey listener
const onKeyDown = (e: KeyboardEvent) => {
  if (!isVideo.value) return
  if (showClipSettings.value) return
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

  if (e.code === 'Space') {
    e.preventDefault()
    togglePlay()
  } else if (e.key === '[') {
    e.preventDefault()
    setCurrentAsStart()
  } else if (e.key === ']') {
    e.preventDefault()
    setCurrentAsEnd()
  } else if (e.code === 'ArrowLeft') {
    e.preventDefault()
    seekRelative(e.shiftKey ? -largeStep.value : -smallStep.value)
  } else if (e.code === 'ArrowRight') {
    e.preventDefault()
    seekRelative(e.shiftKey ? largeStep.value : smallStep.value)
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  clips.value.forEach(c => refreshThumbnail(c))

  // Load step settings from backend if available
  if ((window as any).pywebview?.api?.get_settings) {
    ;(window as any).pywebview.api.get_settings().then((st: any) => {
      if (st.small_step_sec != null) smallStep.value = st.small_step_sec
      if (st.large_step_sec != null) largeStep.value = st.large_step_sec
      if (st.default_crop_aspect) defaultCropAspect.value = st.default_crop_aspect
      if (st.default_crop_radius != null) defaultCropRadius.value = clampCropRadius(st.default_crop_radius)
      if (!props.initialCrop) {
        aspectMode.value = defaultCropAspect.value
      }
      if (props.initialCropRadius == null) {
        cropRadius.value = defaultCropRadius.value
        const first = clips.value[0]
        if (first && !first.crop) first.cropRadius = defaultCropRadius.value
      }
    })
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  if (serverSeekTimer != null) clearTimeout(serverSeekTimer)
  if (videoRef.value) {
    videoRef.value.pause()
  }
})
</script>

<style scoped>
.btn-subtle {
  background-color: #20242e;
  color: #cbd5e1;
  border: 1px solid #334155;
  border-radius: 5px;
  transition: all 0.15s;
}
.btn-subtle:hover {
  background-color: #282f3c;
  color: #ffffff;
}
</style>
