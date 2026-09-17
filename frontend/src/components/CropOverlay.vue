<template>
  <div
    ref="containerRef"
    class="absolute inset-0 select-none overflow-hidden"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
  >
    <svg
      class="absolute inset-0 w-full h-full pointer-events-none"
      :viewBox="`0 0 ${containerW} ${containerH}`"
      preserveAspectRatio="none"
    >
      <defs>
        <mask :id="maskId">
          <rect :width="containerW" :height="containerH" fill="white" />
          <rect
            :x="boxRect.x"
            :y="boxRect.y"
            :width="boxRect.w"
            :height="boxRect.h"
            :rx="cornerPx"
            :ry="cornerPx"
            fill="black"
          />
        </mask>
      </defs>
      <rect
        :width="containerW"
        :height="containerH"
        fill="rgba(0,0,0,0.65)"
        :mask="`url(#${maskId})`"
      />
    </svg>

    <!-- The Crop Box -->
    <div
      class="absolute cursor-move border-2 border-[#24a1de] shadow-2xl touch-none"
      :style="{
        left: `${boxRect.x}px`,
        top: `${boxRect.y}px`,
        width: `${boxRect.w}px`,
        height: `${boxRect.h}px`,
        borderRadius: boxBorderRadius
      }"
      @pointerdown="onPointerDown($event, 'body')"
    >
      <!-- Rule of Thirds Grid -->
      <div
        class="absolute inset-0 pointer-events-none overflow-hidden grid grid-cols-3 grid-rows-3"
        :style="{ borderRadius: boxBorderRadius }"
      >
        <div class="border-r border-b border-white/20" />
        <div class="border-r border-b border-white/20" />
        <div class="border-b border-white/20" />
        <div class="border-r border-b border-white/20" />
        <div class="border-r border-b border-white/20" />
        <div class="border-b border-white/20" />
        <div class="border-r border-white/20" />
        <div class="border-r border-white/20" />
        <div />
      </div>

      <!-- Floating Dimension Badge -->
      <div
        class="absolute left-1/2 -translate-x-1/2 bg-slate-900/90 text-sky-300 border border-sky-500/40 text-[11px] font-mono font-semibold px-2 py-0.5 rounded shadow pointer-events-none whitespace-nowrap"
        :style="{ top: boxRect.h > 70 ? '8px' : '-28px' }"
      >
        {{ nativeCrop[2] }}×{{ nativeCrop[3] }}
      </div>

      <!-- Corner Handles (L-shaped thick cyan brackets) -->
      <div
        class="absolute -top-1.5 -left-1.5 w-4 h-4 border-t-4 border-l-4 border-[#38bdf8] cursor-nwse-resize"
        @pointerdown.stop="onPointerDown($event, 'tl')"
      />
      <div
        class="absolute -top-1.5 -right-1.5 w-4 h-4 border-t-4 border-r-4 border-[#38bdf8] cursor-nesw-resize"
        @pointerdown.stop="onPointerDown($event, 'tr')"
      />
      <div
        class="absolute -bottom-1.5 -left-1.5 w-4 h-4 border-b-4 border-l-4 border-[#38bdf8] cursor-nesw-resize"
        @pointerdown.stop="onPointerDown($event, 'bl')"
      />
      <div
        class="absolute -bottom-1.5 -right-1.5 w-4 h-4 border-b-4 border-r-4 border-[#38bdf8] cursor-nwse-resize"
        @pointerdown.stop="onPointerDown($event, 'br')"
      />

      <!-- Edge Center Handles (white pills with dark borders) -->
      <div
        class="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 w-5 h-1.5 bg-white border border-slate-900 rounded-full cursor-ns-resize"
        @pointerdown.stop="onPointerDown($event, 't')"
      />
      <div
        class="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 w-5 h-1.5 bg-white border border-slate-900 rounded-full cursor-ns-resize"
        @pointerdown.stop="onPointerDown($event, 'b')"
      />
      <div
        class="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 w-1.5 h-5 bg-white border border-slate-900 rounded-full cursor-ew-resize"
        @pointerdown.stop="onPointerDown($event, 'l')"
      />
      <div
        class="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-1.5 h-5 bg-white border border-slate-900 rounded-full cursor-ew-resize"
        @pointerdown.stop="onPointerDown($event, 'r')"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { clampCropRadius } from '../types'

const props = withDefaults(
  defineProps<{
    videoWidth: number
    videoHeight: number
    aspectMode?: string
    radius?: number
    modelValue?: [number, number, number, number] | null
  }>(),
  {
    aspectMode: '1:1',
    radius: 0,
    modelValue: null
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', val: [number, number, number, number]): void
  (e: 'change', val: [number, number, number, number]): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const containerW = ref(800)
const containerH = ref(500)
const maskId = `crop-mask-${Math.random().toString(36).slice(2, 8)}`
const cornerPx = computed(() => {
  const r = clampCropRadius(props.radius)
  return Math.min(boxRect.value.w, boxRect.value.h) * 0.5 * r
})
const boxBorderRadius = computed(() => `${cornerPx.value}px`)

const updateDimensions = () => {
  if (containerRef.value) {
    containerW.value = containerRef.value.clientWidth || 800
    containerH.value = containerRef.value.clientHeight || 500
  }
}

// Letterbox/Pillarbox effective video rectangle
const renderRect = computed(() => {
  const cw = containerW.value
  const ch = containerH.value
  const vw = Math.max(1, props.videoWidth)
  const vh = Math.max(1, props.videoHeight)
  const vRatio = vw / vh
  const cRatio = cw / ch

  let rw = cw
  let rh = ch
  let rx = 0
  let ry = 0

  if (cRatio > vRatio) {
    rh = ch
    rw = ch * vRatio
    rx = (cw - rw) / 2
  } else {
    rw = cw
    rh = cw / vRatio
    ry = (ch - rh) / 2
  }
  return { x: rx, y: ry, w: rw, h: rh }
})

// Current native video crop coordinates [x, y, w, h]
const nativeCrop = ref<[number, number, number, number]>([0, 0, 100, 100])

// Target aspect ratio float
const targetRatio = computed<number | null>(() => {
  switch (props.aspectMode) {
    case '1:1':
      return 1.0
    case '16:9':
      return 16 / 9
    case '9:16':
      return 9 / 16
    case '4:3':
      return 4 / 3
    case 'original':
      return props.videoWidth / Math.max(1, props.videoHeight)
    default:
      return null
  }
})

// Convert native coords [nx, ny, nw, nh] to screen box {x, y, w, h}
const boxRect = computed(() => {
  const rr = renderRect.value
  const vw = Math.max(1, props.videoWidth)
  const vh = Math.max(1, props.videoHeight)
  const [nx, ny, nw, nh] = nativeCrop.value

  const bx = rr.x + (nx / vw) * rr.w
  const by = rr.y + (ny / vh) * rr.h
  const bw = (nw / vw) * rr.w
  const bh = (nh / vh) * rr.h
  return { x: bx, y: by, w: Math.max(20, bw), h: Math.max(20, bh) }
})

// Reset to default centered crop
const resetToDefault = () => {
  const vw = Math.max(16, props.videoWidth)
  const vh = Math.max(16, props.videoHeight)
  const ratio = targetRatio.value

  let bw = vw
  let bh = vh
  if (ratio) {
    if (vw / vh >= ratio) {
      bh = vh
      bw = Math.round(vh * ratio)
    } else {
      bw = vw
      bh = Math.round(vw / ratio)
    }
  }
  bw = Math.min(vw, Math.max(16, bw - (bw % 2)))
  bh = Math.min(vh, Math.max(16, bh - (bh % 2)))
  let bx = Math.max(0, Math.floor((vw - bw) / 2))
  let by = Math.max(0, Math.floor((vh - bh) / 2))
  bx -= bx % 2
  by -= by % 2

  nativeCrop.value = [bx, by, bw, bh]
  emit('update:modelValue', nativeCrop.value)
  emit('change', nativeCrop.value)
}

watch(
  () => props.modelValue,
  (val) => {
    if (val && val.length === 4) {
      nativeCrop.value = [...val]
    }
  },
  { immediate: true }
)

watch(() => props.aspectMode, () => {
  resetToDefault()
})

// Drag logic
let activeHandle = ''
let dragStartPos = { x: 0, y: 0 }
let dragStartBox = { x: 0, y: 0, w: 0, h: 0 }

const onPointerDown = (e: PointerEvent, handle: string) => {
  activeHandle = handle
  dragStartPos = { x: e.clientX, y: e.clientY }
  dragStartBox = { ...boxRect.value }
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
}

const onPointerMove = (e: PointerEvent) => {
  if (!activeHandle) return

  const dx = e.clientX - dragStartPos.x
  const dy = e.clientY - dragStartPos.y
  const rr = renderRect.value
  const ratio = targetRatio.value
  const minSize = 24

  let { x, y, w, h } = dragStartBox

  if (activeHandle === 'body') {
    x = Math.max(rr.x, Math.min(x + dx, rr.x + rr.w - w))
    y = Math.max(rr.y, Math.min(y + dy, rr.y + rr.h - h))
  } else {
    let l = x
    let t = y
    let r = x + w
    let b = y + h

    if (activeHandle.includes('r')) {
      r = Math.max(l + minSize, Math.min(rr.x + rr.w, r + dx))
      if (ratio) {
        b = t + (r - l) / ratio
        if (b > rr.y + rr.h) {
          b = rr.y + rr.h
          r = l + (b - t) * ratio
        }
      }
    }
    if (activeHandle.includes('l')) {
      l = Math.min(r - minSize, Math.max(rr.x, l + dx))
      if (ratio) {
        b = t + (r - l) / ratio
        if (b > rr.y + rr.h) {
          b = rr.y + rr.h
          l = r - (b - t) * ratio
        }
      }
    }
    if (activeHandle.includes('b') && !ratio) {
      b = Math.max(t + minSize, Math.min(rr.y + rr.h, b + dy))
    }
    if (activeHandle.includes('t') && !ratio) {
      t = Math.min(b - minSize, Math.max(rr.y, t + dy))
    }

    x = l
    y = t
    w = Math.max(minSize, r - l)
    h = Math.max(minSize, b - t)
  }

  // Convert back to native resolution
  const vw = Math.max(1, props.videoWidth)
  const vh = Math.max(1, props.videoHeight)
  let nx = Math.round(((x - rr.x) / rr.w) * vw)
  let ny = Math.round(((y - rr.y) / rr.h) * vh)
  let nw = Math.round((w / rr.w) * vw)
  let nh = Math.round((h / rr.h) * vh)

  // Clamp & evenize
  nx = Math.max(0, Math.min(nx, vw - 16))
  ny = Math.max(0, Math.min(ny, vh - 16))
  nw = Math.max(16, Math.min(nw, vw - nx))
  nh = Math.max(16, Math.min(nh, vh - ny))
  nx -= nx % 2
  ny -= ny % 2
  nw -= nw % 2
  nh -= nh % 2

  nativeCrop.value = [nx, ny, nw, nh]
  emit('update:modelValue', nativeCrop.value)
}

const onPointerUp = () => {
  if (activeHandle) {
    activeHandle = ''
    emit('change', nativeCrop.value)
  }
}

onMounted(() => {
  updateDimensions()
  const ro = new ResizeObserver(updateDimensions)
  if (containerRef.value) ro.observe(containerRef.value)
  if (!props.modelValue || props.modelValue.length !== 4) {
    resetToDefault()
  }
})

defineExpose({
  resetToDefault
})
</script>
