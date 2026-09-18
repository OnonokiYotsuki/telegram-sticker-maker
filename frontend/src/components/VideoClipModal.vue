<template>
  <div data-skip-deselect class="fixed inset-0 z-50 bg-[#141720] flex">
    <div class="bg-[#141720] w-full h-full flex flex-col overflow-hidden">
      
      <!-- Top Bar -->
      <div class="flex items-center justify-between px-5 py-3 border-b border-[#232731] bg-[#171922] gap-3">
        <div class="flex items-center space-x-2 min-w-0">
          <span class="text-lg">✂️</span>
          <span class="font-bold text-white text-sm truncate max-w-md">{{ mediaInfo.file_name }}</span>
        </div>
        <div class="flex items-center space-x-3 shrink-0">
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
          <button
            v-if="isVideo && needsProxyFile"
            type="button"
            :disabled="proxyReady || proxyLoading"
            :class="[
              'px-2.5 py-1 rounded text-[11px] font-semibold transition shrink-0',
              proxyReady
                ? 'bg-emerald-950/70 text-emerald-400 border border-emerald-800/50 cursor-default'
                : proxyLoading
                  ? 'btn-subtle text-sky-300 cursor-wait'
                  : proxyError
                    ? 'btn-subtle text-rose-300'
                    : 'btn-subtle text-sky-300'
            ]"
            :title="proxyReady
              ? '已使用缓存的流畅预览'
              : proxyError
                ? proxyError
                : '生成可 Range 快进的 480p 代理并缓存到临时目录'"
            @click="startProxyCache"
          >
            <template v-if="proxyReady">已缓存</template>
            <template v-else-if="proxyLoading">缓存中 {{ proxyProgress }}%</template>
            <template v-else-if="proxyError">缓存失败 · 重试</template>
            <template v-else>缓存代理</template>
          </button>
        </div>
      </div>

      <!-- Main Body: 2 Columns Split -->
      <div class="flex-1 flex overflow-hidden">
        
        <!-- Left Column: Video Preview & Controls -->
        <div class="flex-1 flex flex-col p-4 space-y-3 min-w-0">
          
          <!-- Video Screen Container -->
          <div
            class="flex-1 bg-black rounded-lg border border-[#232731] relative flex items-center justify-center overflow-hidden min-h-[320px]"
            @wheel.prevent="onTimelineWheel"
          >
            <video
              v-if="isVideo"
              ref="videoRef"
              :src="streamUrl"
              class="absolute inset-0 w-full h-full object-contain pointer-events-auto"
              :style="currentMirror ? { transform: 'scaleX(-1)' } : undefined"
              @timeupdate="onTimeUpdate"
              @loadedmetadata="onLoadedMetadata"
              @canplay="onCanPlay"
              @error="onVideoError"
              @play="onPlay"
              @pause="onPause"
              @click="togglePlay"
            />
            <img
              v-else
              :src="imagePreviewUrl"
              class="absolute inset-0 w-full h-full object-contain pointer-events-none"
              :style="currentMirror ? { transform: 'scaleX(-1)' } : undefined"
              alt="裁切预览"
            />

            <!-- Crop Overlay -->
            <CropOverlay
              v-if="cropActive && selectedClip"
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
            <div v-if="isVideo" class="space-y-1.5" @wheel.prevent="onTimelineWheel">
              <div class="flex items-center justify-between gap-3 text-xs font-mono tabular-nums">
                <span class="font-semibold text-sky-400 min-w-[5.5rem]">{{ formatTime(currentTime) }}</span>
                <span v-if="hoverTime != null" class="text-[11px] text-sky-200">
                  {{ formatTime(hoverTime) }}
                </span>
                <span
                  v-else-if="selectedClip"
                  class="text-[11px] truncate"
                  :class="inSelectedClip ? 'text-sky-300' : 'text-slate-500'"
                >
                  片段 {{ formatTime(selectedClip.startTime) }} – {{ clipHasEnd(selectedClip) ? formatTime(selectedClip.endTime) : '未设终点' }}
                  <span v-if="clipHasEnd(selectedClip)" class="text-slate-500">({{ (selectedClip.endTime! - selectedClip.startTime).toFixed(2) }}s)</span>
                  <span v-if="selectedClip.emoji" class="text-amber-300 ml-1 font-sans">({{ selectedClip.emoji }})</span>
                </span>
                <span class="text-slate-500 text-right flex items-center justify-end gap-1.5 shrink-0">
                  <button
                    type="button"
                    :class="[
                      'px-1.5 py-0.5 rounded text-[10px] font-sans border',
                      showOverview
                        ? 'text-sky-300 bg-sky-500/10 border-sky-500/30 hover:bg-sky-500/20'
                        : 'text-slate-400 bg-white/5 border-slate-600/60 hover:bg-white/10'
                    ]"
                    :title="showOverview ? '隐藏总览条' : '显示总览条'"
                    @click="toggleOverview"
                  >
                    总览
                  </button>
                  <button
                    type="button"
                    :disabled="!hasSelectedClip"
                    :class="[
                      'px-1.5 py-0.5 rounded text-[10px] font-sans border',
                      hasSelectedClip
                        ? 'text-sky-300 bg-sky-500/10 border-sky-500/30 hover:bg-sky-500/20'
                        : 'text-slate-500 bg-white/5 border-slate-700/50 opacity-40 cursor-not-allowed'
                    ]"
                    :title="hasSelectedClip ? '把当前片段放到时间轴中间 (F)' : '请先选择一个片段'"
                    @click="zoomToSelectedClip"
                  >
                    适应片段
                  </button>
                  <button
                    v-if="isTimelineZoomed"
                    type="button"
                    class="px-1.5 py-0.5 rounded text-[10px] font-sans text-slate-300 bg-white/5 border border-slate-600/60 hover:bg-white/10"
                    title="显示完整时长 (0)"
                    @click="resetTimelineZoom"
                  >
                    全长 {{ viewSpan.toFixed(viewSpan < 2 ? 2 : 1) }}s
                  </button>
                  <span>{{ formatTime(mediaInfo.duration) }}</span>
                </span>
              </div>

              <div
                v-if="showOverview"
                ref="overviewRef"
                class="overview"
                :class="{ 'is-dragging': timelineAction === 'overview' }"
                title="总览：拖动窗口平移，点击跳转"
                @pointerdown="onOverviewPointerDown"
                @pointermove="onOverviewPointerMove"
                @pointerup="onOverviewPointerUp"
                @pointercancel="onOverviewPointerUp"
              >
                <div
                  v-for="(clip, idx) in clips"
                  :key="'ov-' + clip.id"
                  class="overview-clip"
                  :class="{ 'is-active': idx === selectedClipIdx }"
                  :style="overviewClipStyle(clip)"
                />
                <div class="overview-window" :style="overviewWindowStyle" />
                <div class="overview-head" :style="{ left: overviewPlayheadPct + '%' }" />
              </div>

              <div
                ref="timelineRef"
                class="timeline"
                :class="{
                  'is-scrubbing': timelineAction === 'scrub',
                  'is-panning': timelineAction === 'pan'
                }"
                role="slider"
                tabindex="0"
                aria-label="播放进度"
                :aria-valuemin="0"
                :aria-valuemax="mediaInfo.duration"
                :aria-valuenow="currentTime"
                @pointerdown="onTimelinePointerDown"
                @pointermove="onTimelinePointerMove"
                @pointerup="onTimelinePointerUp"
                @pointercancel="onTimelinePointerUp"
                @pointerleave="onTimelinePointerLeave"
                @dblclick="onTimelineDblClick"
              >
                <div
                  v-for="tick in timelineTicks"
                  :key="tick"
                  class="timeline-tick"
                  :style="{ left: timeToPct(tick) + '%' }"
                />
                <div
                  v-for="tick in timelineTicks"
                  :key="'lbl-' + tick"
                  class="timeline-tick-label"
                  :style="{ left: timeToPct(tick) + '%' }"
                >
                  {{ formatTick(tick) }}
                </div>

                <div class="timeline-track">
                  <div class="timeline-played" :style="playedStyle" />
                </div>

                <div
                  v-for="(clip, idx) in clips"
                  :key="clip.id"
                  class="timeline-clip"
                  :class="{ 'is-active': idx === selectedClipIdx }"
                  :style="clipRangeStyle(clip)"
                  :title="clipRangeTitle(clip, idx)"
                />

                <div
                  v-if="hoverTime != null && timelineAction !== 'pan'"
                  class="timeline-hover-line"
                  :style="{ left: hoverPct + '%' }"
                />

                <div
                  v-if="progressPct >= -2 && progressPct <= 102"
                  class="timeline-head"
                  :style="{ left: progressPct + '%' }"
                />
              </div>

              <div class="flex justify-between text-[10px] font-mono tabular-nums text-slate-500">
                <span>{{ formatTime(timelineViewStart) }}</span>
                <span>滚轮缩放 · Shift 平移</span>
                <span>{{ formatTime(timelineViewEnd) }}</span>
              </div>
            </div>

            <div v-if="!isVideo" class="flex items-center justify-between pt-1">
              <div class="flex items-center space-x-1.5 text-xs">
                <button
                  :disabled="!hasSelectedClip"
                  @click="toggleCrop"
                  :class="[
                    'px-3 py-1 rounded font-semibold transition text-xs disabled:opacity-40 disabled:cursor-not-allowed',
                    cropActive ? 'bg-sky-500 hover:bg-sky-400 text-white' : 'btn-subtle text-sky-400'
                  ]"
                  :title="hasSelectedClip ? '开启/关闭画面裁切框' : '请先选择一个片段'"
                >
                  ✂️ 画面裁切
                </button>
                <button
                  type="button"
                  :disabled="!hasSelectedClip"
                  @click="toggleMirror"
                  :class="[
                    'px-3 py-1 rounded font-semibold transition flex items-center space-x-1 disabled:opacity-40 disabled:cursor-not-allowed',
                    currentMirror ? 'bg-amber-500 hover:bg-amber-400 text-white' : 'btn-subtle text-amber-400'
                  ]"
                  :title="!hasSelectedClip
                    ? '请先选择一个片段'
                    : currentMirror ? '已开启镜像翻转 (快捷键 M)' : '镜像翻转画面 (快捷键 M)'"
                >
                  <span>🪞 镜像</span>
                </button>

                <div class="h-4 w-px bg-slate-700 mx-1" />

                <!-- Emoji setting for image -->
                <div
                  class="flex items-center space-x-1.5 bg-[#12141a] border border-[#2b3040] rounded px-2 py-1 text-xs"
                  :class="!hasSelectedClip ? 'opacity-40 cursor-not-allowed' : ''"
                >
                  <span class="text-slate-400 text-xs font-semibold whitespace-nowrap">关联 Emoji:</span>
                  <input
                    type="text"
                    :disabled="!hasSelectedClip"
                    :value="selectedClip?.emoji || ''"
                    @input="onSelectedClipEmojiInput(($event.target as HTMLInputElement).value)"
                    placeholder="未设置"
                    title="设置此贴纸的关联 Emoji"
                    class="w-20 bg-transparent text-slate-200 placeholder:text-slate-600 focus:outline-none text-xs text-center font-sans disabled:cursor-not-allowed"
                  />
                </div>
              </div>
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
                  :disabled="!hasSelectedClip"
                  :class="[
                    'btn-subtle px-2.5 py-1',
                    !hasSelectedClip ? 'opacity-40 cursor-not-allowed' : ''
                  ]"
                  :title="hasSelectedClip ? '设当前时刻为起点 (快捷键 [)' : '请先选择一个片段'"
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
                  :title="!hasSelectedClip
                    ? '请先选择一个片段'
                    : canSetEnd ? '设当前时刻为终点 (快捷键 ])' : '终点必须晚于起点'"
                >
                  🏁
                </button>

                <!-- Crop Toggle -->
                <button
                  @click="toggleCrop"
                  :disabled="!hasSelectedClip"
                  :class="[
                    'px-3 py-1 rounded font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed',
                    cropActive ? 'bg-sky-500 hover:bg-sky-400 text-white' : 'btn-subtle text-sky-400'
                  ]"
                  :title="hasSelectedClip ? '开启/关闭画面裁切框' : '请先选择一个片段'"
                >
                  ✂️ 画面裁切
                </button>

                <!-- Mirror Toggle -->
                <button
                  type="button"
                  @click="toggleMirror"
                  :disabled="!hasSelectedClip"
                  :class="[
                    'px-3 py-1 rounded font-semibold transition flex items-center space-x-1 disabled:opacity-40 disabled:cursor-not-allowed',
                    currentMirror ? 'bg-amber-500 hover:bg-amber-400 text-white' : 'btn-subtle text-amber-400'
                  ]"
                  :title="!hasSelectedClip
                    ? '请先选择一个片段'
                    : currentMirror ? '已开启镜像翻转 (快捷键 M)' : '镜像翻转画面 (快捷键 M)'"
                >
                  <span>🪞 镜像</span>
                </button>

                <div class="h-4 w-px bg-slate-700 mx-1" />

                <!-- Current clip emoji setting -->
                <div
                  class="flex items-center space-x-1.5 bg-[#12141a] border border-[#2b3040] rounded px-2 py-1 text-xs"
                  :class="!hasSelectedClip ? 'opacity-40 cursor-not-allowed' : ''"
                >
                  <span class="text-slate-400 text-xs font-semibold whitespace-nowrap">关联 Emoji:</span>
                  <input
                    type="text"
                    :disabled="!hasSelectedClip"
                    :value="selectedClip?.emoji || ''"
                    @input="onSelectedClipEmojiInput(($event.target as HTMLInputElement).value)"
                    placeholder="未设置"
                    title="设置当前选中片段的关联 Emoji"
                    class="w-16 bg-transparent text-slate-200 placeholder:text-slate-600 focus:outline-none text-xs text-center font-sans disabled:cursor-not-allowed"
                  />
                </div>
              </div>

              <div class="flex items-center shrink-0">
                <select
                  :value="String(playbackRate)"
                  class="btn-subtle px-1.5 py-1 text-[11px] font-mono text-sky-300 outline-none cursor-pointer"
                  title="播放倍速（, 减速 · . 加速）"
                  @change="onPlaybackRateChange"
                >
                  <option v-for="r in PLAYBACK_RATES" :key="r" :value="String(r)">
                    {{ formatPlaybackRate(r) }}
                  </option>
                </select>
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
                    :disabled="!hasSelectedClip"
                    :class="[
                      'bg-[#1e222b] border border-[#334155] text-slate-200 rounded px-2 py-1 text-xs outline-none focus:border-sky-500',
                      !hasSelectedClip ? 'opacity-40 cursor-not-allowed' : ''
                    ]"
                  >
                    <option v-for="opt in cropAspectOptions" :key="opt.value" :value="opt.value">
                      {{ opt.label }}
                    </option>
                  </select>

                  <button
                    @click="resetCropCenter"
                    :disabled="!hasSelectedClip"
                    :class="[
                      'btn-subtle px-2.5 py-1 text-slate-300',
                      !hasSelectedClip ? 'opacity-40 cursor-not-allowed' : ''
                    ]"
                    :title="hasSelectedClip ? '将裁切框居中重置' : '请先选择一个片段'"
                  >
                    🔄 重置居中
                  </button>

                  <button
                    v-if="isVideo"
                    @click="applyCropShapeToAll"
                    :disabled="!hasSelectedClip || !currentCrop"
                    :class="[
                      'btn-subtle px-2.5 py-1 text-sky-300 hover:text-sky-200',
                      !hasSelectedClip || !currentCrop ? 'opacity-40 cursor-not-allowed' : ''
                    ]"
                    :title="!hasSelectedClip
                      ? '请先选择一个片段'
                      : '将当前宽高与圆角应用到所有片段，保留各自位置'"
                  >
                    📐 同步形状
                  </button>

                  <button
                    type="button"
                    @click="clearCrop"
                    :disabled="!hasSelectedClip"
                    :class="[
                      'btn-subtle px-2.5 py-1 text-slate-400 hover:text-rose-400',
                      !hasSelectedClip ? 'opacity-40 cursor-not-allowed' : ''
                    ]"
                    :title="hasSelectedClip ? '清除当前片段的裁切框' : '请先选择一个片段'"
                  >
                    🗑️ 清除裁切
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
                  :disabled="!hasSelectedClip"
                  :value="Math.round(cropRadius * 100)"
                  @input="onRadiusInput"
                  :class="[
                    'flex-1 h-1.5 bg-[#252833] rounded-lg appearance-none accent-sky-500',
                    hasSelectedClip ? 'cursor-pointer' : 'opacity-40 cursor-not-allowed'
                  ]"
                  :title="hasSelectedClip ? '0 直角，100 圆形' : '请先选择一个片段'"
                />
                <span class="text-slate-500 text-[11px]">圆形</span>
                <span class="font-mono text-sky-400 w-16 text-right">{{ cropRadiusLabel(cropRadius) }}</span>
              </div>
            </div>

          </div>
        </div>

        <!-- Right Column: Clips Management List -->
        <div v-if="isVideo" class="w-80 border-l border-[#232731] bg-[#161822] flex flex-col">
          
          <div
            class="px-4 py-3 border-b border-[#232731] flex items-center justify-between"
            @click="clearClipSelection"
          >
            <span class="font-bold text-xs text-slate-200">📋 待添加片段列表</span>
            <span class="text-xs text-slate-400">共 {{ clips.length }} 个片段</span>
          </div>

          <!-- Clips Table List -->
          <div class="flex-1 overflow-y-auto p-2 space-y-2" @click="clearClipSelection">
            <div
              v-for="(clip, idx) in clips"
              :key="clip.id"
              :class="[
                'p-2.5 rounded-lg border transition cursor-pointer flex items-center space-x-3',
                selectedClipIdx === idx
                  ? 'bg-[#1e2330] border-sky-500/60 shadow'
                  : 'bg-[#171922] border-[#252833] hover:border-slate-700'
              ]"
              @click.stop="selectClip(idx)"
              @contextmenu.prevent="onClipContextMenu($event, idx)"
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
                    title="起始时间"
                    class="w-16 bg-[#11131a] border border-[#2b3040] rounded px-1 text-center text-slate-200 focus:border-sky-500 outline-none text-[11px]"
                  />
                  <span class="text-slate-500">-</span>
                  <input
                    type="text"
                    :value="clip.endTime == null ? '' : formatTime(clip.endTime)"
                    placeholder="终点"
                    @change="onClipEndChange(idx, $event)"
                    title="结束时间"
                    class="w-16 bg-[#11131a] border border-[#2b3040] rounded px-1 text-center text-slate-200 placeholder:text-slate-600 focus:border-sky-500 outline-none text-[11px]"
                  />
                  <input
                    type="text"
                    v-model="clip.emoji"
                    placeholder="Emoji"
                    title="关联 Emoji（如 😂、🐱）"
                    @click.stop="selectClip(idx)"
                    class="flex-1 min-w-[3.4rem] bg-[#11131a] border border-[#2b3040] rounded px-1.5 py-0.5 text-center text-slate-200 placeholder:text-slate-600 focus:border-sky-500 outline-none text-[11px] font-sans"
                  />
                </div>
                <div class="text-[11px] text-slate-400 flex items-center flex-wrap gap-1.5">
                  <span class="font-semibold text-slate-300">{{ clipDurationLabel(clip) }}</span>
                  <span
                    v-if="clip.emoji"
                    class="text-amber-300 font-sans text-[10px] bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-800/40 truncate max-w-[80px]"
                    :title="`关联 Emoji: ${clip.emoji}`"
                  >
                    {{ clip.emoji }}
                  </span>
                  <span v-if="clip.mirror" class="text-amber-400 font-mono text-[10px] bg-amber-950/60 px-1 rounded border border-amber-800/40">
                    🪞 镜像
                  </span>
                  <span v-if="clip.crop" class="text-sky-400 font-mono text-[10px] bg-sky-950/60 px-1 rounded border border-sky-800/40">
                    [✂️ {{ cropRadiusLabel(clip.cropRadius) }} {{ clip.crop[2] }}×{{ clip.crop[3] }}]
                  </span>
                  <span
                    v-if="isClipPlaying(idx, 'once')"
                    class="text-emerald-400 font-mono text-[10px] bg-emerald-950/60 px-1 rounded border border-emerald-800/40"
                  >
                    ▶️ 播放中
                  </span>
                  <span
                    v-else-if="isClipPlaying(idx, 'loop')"
                    class="text-emerald-400 font-mono text-[10px] bg-emerald-950/60 px-1 rounded border border-emerald-800/40"
                  >
                    🔁 循环中
                  </span>
                </div>
              </div>

              <!-- Context menu trigger button -->
              <button
                type="button"
                @click.stop="onClipContextMenu($event, idx)"
                class="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition text-xs opacity-70 hover:opacity-100"
                title="片段选项 (右键菜单)"
              >
                ⋮
              </button>
            </div>
          </div>

          <!-- Add Clip Actions -->
          <div class="p-3 border-t border-[#232731]">
            <button
              @click="addNewClip"
              class="w-full bg-sky-600 hover:bg-sky-500 text-white font-medium text-xs py-2 rounded flex items-center justify-center space-x-1 transition"
              title="从当前指针开始，终点留空，用 ] 打点"
            >
              <span>➕ 添加片段</span>
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
          <label class="flex items-center justify-between gap-3 cursor-pointer">
            <span class="text-slate-400">显示时间轴总览条</span>
            <input type="checkbox" v-model="showOverview" class="accent-sky-500" />
          </label>
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

    <!-- Clip Item Right-Click Context Menu -->
    <Teleport to="body">
      <div
        v-if="clipContextMenu.visible && clipContextMenu.clipIdx >= 0"
        :style="{ left: `${clipContextMenu.x}px`, top: `${clipContextMenu.y}px` }"
        class="fixed z-[9999] bg-[#16181d] border border-[#282b35] rounded-xl shadow-2xl p-1 text-xs text-gray-200 min-w-[150px] space-y-0.5 select-none animate-in fade-in zoom-in-95 duration-75"
        @click.stop
      >
        <button
          @click="playClipFromMenu('once')"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#24a1de] hover:text-white flex items-center gap-2 transition cursor-pointer"
        >
          <span>{{ isClipPlaying(clipContextMenu.clipIdx, 'once') ? '⏸️ 停止播放' : '▶️ 播放' }}</span>
        </button>

        <button
          @click="playClipFromMenu('loop')"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-[#24a1de] hover:text-white flex items-center gap-2 transition cursor-pointer"
        >
          <span>{{ isClipPlaying(clipContextMenu.clipIdx, 'loop') ? '⏸️ 停止循环' : '🔁 循环播放' }}</span>
        </button>

        <div class="h-px bg-[#252831] my-1"></div>

        <button
          @click="deleteClipFromMenu"
          class="w-full text-left px-3 py-1.5 rounded-lg hover:bg-red-500 hover:text-white flex items-center justify-between text-red-400 transition cursor-pointer"
        >
          <span>🗑️ 删除</span>
          <span class="text-[10px] opacity-70 font-mono">Del</span>
        </button>
      </div>
    </Teleport>

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
  initialMirror?: boolean
  initialEmoji?: string
  initialClips?: ClipItem[]
  initialClipIndex?: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', clips: ClipItem[]): void
}>()

const videoRef = ref<HTMLVideoElement | null>(null)
const timelineRef = ref<HTMLDivElement | null>(null)
const overviewRef = ref<HTMLDivElement | null>(null)
const cropOverlayRef = ref<any>(null)

const isPlaying = ref(false)
const isMuted = ref(false)
const currentTime = ref(0)
const clipPlayMode = ref<'once' | 'loop' | null>(null)
const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4] as const
const playbackRate = ref(1)

function formatPlaybackRate(rate: number) {
  return `${rate}×`
}

function snapPlaybackRate(rate: number) {
  let best: number = PLAYBACK_RATES[0]
  let bestDist = Math.abs(rate - best)
  for (const r of PLAYBACK_RATES) {
    const d = Math.abs(rate - r)
    if (d < bestDist) {
      best = r
      bestDist = d
    }
  }
  return best
}

function applyPlaybackRate() {
  if (videoRef.value) videoRef.value.playbackRate = playbackRate.value
}

function setPlaybackRate(rate: number, persist = true) {
  playbackRate.value = snapPlaybackRate(rate)
  applyPlaybackRate()
  if (persist) persistClipSettings()
}

function nudgePlaybackRate(dir: 1 | -1) {
  const i = PLAYBACK_RATES.findIndex((r) => Math.abs(r - playbackRate.value) < 0.001)
  const idx = i < 0 ? PLAYBACK_RATES.indexOf(1) : i
  const next = PLAYBACK_RATES[Math.max(0, Math.min(PLAYBACK_RATES.length - 1, idx + dir))]
  setPlaybackRate(next)
}

function onPlaybackRateChange(e: Event) {
  setPlaybackRate(parseFloat((e.target as HTMLSelectElement).value))
}

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

function resolveInitialClips(): ClipItem[] {
  if (props.initialClips && props.initialClips.length > 0) {
    return props.initialClips.map((c, i) => ({
      id: c.id || `clip-${i + 1}`,
      startTime: c.startTime,
      endTime: c.endTime,
      duration: c.endTime != null ? Math.max(0.1, c.endTime - c.startTime) : 0,
      emoji: c.emoji ?? '',
      keywords: c.keywords,
      crop: c.crop,
      cropRadius: clampCropRadius(c.cropRadius),
      mirror: !!c.mirror,
    }))
  }
  const start = props.initialStartTime ?? 0
  const end = props.initialEndTime ?? Math.min(2.5, props.mediaInfo.duration)
  return [
    {
      id: 'clip-1',
      startTime: start,
      endTime: end,
      duration: Math.max(0.1, end - start),
      emoji: props.initialEmoji ?? '',
      crop: props.initialCrop,
      cropRadius: clampCropRadius(props.initialCropRadius),
      mirror: !!props.initialMirror,
    },
  ]
}

const clips = ref<ClipItem[]>(resolveInitialClips())
const selectedClipIdx = ref(
  Math.max(0, Math.min(props.initialClipIndex ?? 0, clips.value.length - 1)),
)
const focusedInit = clips.value[selectedClipIdx.value]
if (focusedInit) currentTime.value = focusedInit.startTime
const cropActive = ref(!!focusedInit?.crop || !props.mediaInfo.is_video)
const aspectMode = ref('1:1')
const cropRadius = ref(clampCropRadius(focusedInit?.cropRadius ?? props.initialCropRadius))
const currentCrop = ref<[number, number, number, number] | null>(
  focusedInit?.crop || props.initialCrop || null,
)
const currentMirror = ref(!!focusedInit?.mirror || !!props.initialMirror)

const hoverTime = ref<number | null>(null)
const showOverview = ref(true)
const timelineAction = ref<'idle' | 'scrub' | 'pan' | 'overview'>('idle')
const isScrubbing = computed(() => timelineAction.value === 'scrub')

const clipThumbnails = ref<Record<string, string>>({})
const selectedClip = computed(() => clips.value[selectedClipIdx.value] ?? null)
const hasSelectedClip = computed(() => !!selectedClip.value)

function clipHasEnd(clip: ClipItem | null | undefined): clip is ClipItem & { endTime: number } {
  return !!clip && clip.endTime != null && Number.isFinite(clip.endTime) && clip.endTime > clip.startTime
}

function clipDurationLabel(clip: ClipItem) {
  if (!clipHasEnd(clip)) return '未设终点'
  return `${(clip.endTime - clip.startTime).toFixed(2)}s`
}

function clipRangeTitle(clip: ClipItem, idx: number) {
  const end = clipHasEnd(clip) ? formatTime(clip.endTime) : '未设终点'
  return `片段 ${idx + 1}: ${formatTime(clip.startTime)} – ${end}`
}

const inSelectedClip = computed(() => {
  const clip = selectedClip.value
  if (!clip) return false
  if (currentTime.value < clip.startTime - 0.001) return false
  if (!clipHasEnd(clip)) return true
  return currentTime.value <= clip.endTime + 0.001
})
const timelineDuration = computed(() => Math.max(0.0001, props.mediaInfo.duration || 0))
const timelineViewStart = ref(0)
const timelineViewEnd = ref(Math.max(0.0001, props.mediaInfo.duration || 0))
const MIN_VIEW_SEC = 0.12
const viewSpan = computed(() =>
  Math.max(0.0001, timelineViewEnd.value - timelineViewStart.value)
)
const isTimelineZoomed = computed(
  () => viewSpan.value < timelineDuration.value - 0.02
)
const progressPct = computed(() => timeToPct(currentTime.value))
const hoverPct = computed(() => (hoverTime.value == null ? 0 : timeToPct(hoverTime.value)))
const playedStyle = computed(() => {
  const pct = Math.max(0, Math.min(100, progressPct.value))
  return { width: `${pct}%` }
})
const overviewWindowStyle = computed(() => {
  const dur = timelineDuration.value
  return {
    left: `${(timelineViewStart.value / dur) * 100}%`,
    width: `${(viewSpan.value / dur) * 100}%`
  }
})
const overviewPlayheadPct = computed(() =>
  Math.max(0, Math.min(100, (currentTime.value / timelineDuration.value) * 100))
)
const timelineTicks = computed(() => {
  const start = timelineViewStart.value
  const end = timelineViewEnd.value
  const span = end - start
  if (span <= 0) return [] as number[]
  const steps = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
  let step = steps[steps.length - 1]
  for (const s of steps) {
    if (span / s <= 8) {
      step = s
      break
    }
  }
  const first = Math.ceil((start + step * 0.08) / step) * step
  const ticks: number[] = []
  for (let t = first; t < end - step * 0.08; t += step) ticks.push(Number(t.toFixed(6)))
  return ticks
})

let followResumeAt = 0
let panDrag: { originX: number; originStart: number } | null = null
let overviewDragAnchor = 0

function bumpFollowSuspend() {
  followResumeAt = performance.now() + 800
}

function timeToPct(t: number) {
  return ((t - timelineViewStart.value) / viewSpan.value) * 100
}

function clipRangeStyle(clip: ClipItem) {
  if (!clipHasEnd(clip)) {
    const left = timeToPct(clip.startTime)
    if (left < -2 || left > 102) return { display: 'none' }
    return { left: `${left}%`, width: '2px' }
  }
  const leftT = Math.max(clip.startTime, timelineViewStart.value)
  const rightT = Math.min(clip.endTime, timelineViewEnd.value)
  if (rightT <= leftT) return { display: 'none' }
  const left = timeToPct(leftT)
  const width = timeToPct(rightT) - left
  return { left: `${left}%`, width: `${Math.max(0.25, width)}%` }
}

function overviewClipStyle(clip: ClipItem) {
  const dur = timelineDuration.value
  const left = (clip.startTime / dur) * 100
  if (!clipHasEnd(clip)) return { left: `${left}%`, width: '2px' }
  const width = Math.max(0.35, ((clip.endTime - clip.startTime) / dur) * 100)
  return { left: `${left}%`, width: `${width}%` }
}

function clampTimelineView(start: number, end: number) {
  const dur = timelineDuration.value
  let span = Math.max(Math.min(MIN_VIEW_SEC, dur), Math.min(dur, end - start))
  let s = start
  let e = s + span
  if (s < 0) {
    s = 0
    e = span
  }
  if (e > dur) {
    e = dur
    s = Math.max(0, e - span)
  }
  timelineViewStart.value = s
  timelineViewEnd.value = e
}

function resetTimelineZoom() {
  timelineViewStart.value = 0
  timelineViewEnd.value = timelineDuration.value
  bumpFollowSuspend()
}

function panTimelineView(dt: number) {
  clampTimelineView(timelineViewStart.value + dt, timelineViewEnd.value + dt)
}

function zoomTimelineAt(pivot: number, factor: number) {
  const oldStart = timelineViewStart.value
  const oldSpan = viewSpan.value
  const ratio = oldSpan <= 0 ? 0.5 : Math.max(0, Math.min(1, (pivot - oldStart) / oldSpan))
  clampTimelineView(pivot - ratio * oldSpan * factor, pivot + (1 - ratio) * oldSpan * factor)
  bumpFollowSuspend()
}

function zoomToClip(clip: ClipItem | null | undefined) {
  if (!clip) return
  if (!clipHasEnd(clip)) {
    const pad = Math.max(1, viewSpan.value * 0.25)
    clampTimelineView(clip.startTime - pad, clip.startTime + pad)
    bumpFollowSuspend()
    return
  }
  const dur = Math.max(0.08, clip.endTime - clip.startTime)
  const pad = Math.max(dur * 0.6, 0.2)
  clampTimelineView(clip.startTime - pad, clip.endTime + pad)
  bumpFollowSuspend()
}

function zoomToSelectedClip() {
  zoomToClip(selectedClip.value)
}

function keepPlayheadInView(t: number) {
  if (!isTimelineZoomed.value) return
  if (performance.now() < followResumeAt) return
  const start = timelineViewStart.value
  const span = viewSpan.value
  const end = timelineViewEnd.value
  const leftM = start + span * 0.1
  const rightM = end - span * 0.12
  if (t >= leftM && t <= rightM) return
  const target = t - span * 0.35
  clampTimelineView(target, target + span)
}

function wheelDeltaPx(e: WheelEvent, axis: 'x' | 'y') {
  let v = axis === 'x' ? e.deltaX : e.deltaY
  if (e.deltaMode === 1) v *= 16
  else if (e.deltaMode === 2) v *= 400
  return Math.max(-160, Math.min(160, v))
}

function isPointerOnEl(el: HTMLElement | null, e: { clientX: number; clientY: number }) {
  if (!el) return false
  const r = el.getBoundingClientRect()
  return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom
}

function onTimelineWheel(e: WheelEvent) {
  if (!isVideo.value) return
  const dur = timelineDuration.value
  if (dur <= 0) return

  const isPan = e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)
  const bar = timelineRef.value
  const width = bar?.getBoundingClientRect().width || 1
  if (isPan) {
    const deltaPx = e.shiftKey ? wheelDeltaPx(e, 'y') : wheelDeltaPx(e, 'x')
    panTimelineView((deltaPx / width) * viewSpan.value)
    bumpFollowSuspend()
    return
  }

  const onBar = isPointerOnEl(bar, e)
  const pivot = onBar ? timeFromClientX(e.clientX) : currentTime.value
  const factor = Math.exp(wheelDeltaPx(e, 'y') * 0.00115)
  zoomTimelineAt(pivot, factor)
}

// MP4/WebM/Ogg are Range-seekable. MKV and others are an FFmpeg pipe; setting
// video.currentTime only jumps the UI clock, then the live fragments pull it back.
const RANGE_SEEK_EXTS = ['.mp4', '.webm', '.ogg']
const needsProxyFile = computed(() => {
  const p = (props.mediaInfo.file_path || '').toLowerCase()
  const dot = p.lastIndexOf('.')
  return isVideo.value && (dot < 0 || !RANGE_SEEK_EXTS.includes(p.slice(dot)))
})
const proxyReady = ref(false)
const proxyLoading = ref(false)
const proxyProgress = ref(0)
const proxyError = ref<string | null>(null)
let proxyPollTimer: ReturnType<typeof setTimeout> | null = null
let pendingProxySeek: number | null = null

const nativeRangeSeek = computed(() => !needsProxyFile.value || proxyReady.value)
const streamOffset = ref(focusedInit ? focusedInit.startTime : 0)
const streamReloadNonce = ref(0)
const isReloading = ref(false)
const pendingPlay = ref(false)
let initialSeekDone = false
let queuedServerSeek: number | null = null
let serverSeekTimer: ReturnType<typeof setTimeout> | null = null
let clockRaf = 0

const streamUrl = computed(() => {
  const enc = encodeURIComponent(props.mediaInfo.file_path)
  const params = [`path=${enc}`]
  if (!nativeRangeSeek.value) {
    params.push('live=1')
    if (streamOffset.value > 0.001) {
      params.push(`t=${streamOffset.value.toFixed(3)}`)
    }
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

function formatTick(t: number) {
  if (viewSpan.value >= 30) return formatTime(t).slice(0, 5)
  if (viewSpan.value >= 4) {
    const m = Math.floor(t / 60)
    const s = t % 60
    return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`
  }
  return formatTime(t)
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

const stopClipPlayback = () => {
  clipPlayMode.value = null
}

const isClipPlaying = (idx: number, mode: 'once' | 'loop') =>
  clipPlayMode.value === mode && selectedClipIdx.value === idx && isPlaying.value

const togglePlay = () => {
  if (!videoRef.value) return
  if (videoRef.value.paused) {
    applyPlaybackRate()
    videoRef.value.play()
  } else {
    videoRef.value.pause()
    stopClipPlayback()
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
  stopClipPlayback()
  const base = isReloading.value ? currentTime.value : playbackClock()
  seekTo(base + delta)
}

function timeFromClientX(clientX: number) {
  const el = timelineRef.value
  if (!el) return timelineViewStart.value
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0) return timelineViewStart.value
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  return timelineViewStart.value + ratio * viewSpan.value
}

function timeFromOverviewX(clientX: number) {
  const el = overviewRef.value
  if (!el) return 0
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0) return 0
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  return ratio * timelineDuration.value
}

function endPointerOn(el: HTMLElement, e: PointerEvent) {
  if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
  const rect = el.getBoundingClientRect()
  const inside =
    e.clientX >= rect.left &&
    e.clientX <= rect.right &&
    e.clientY >= rect.top &&
    e.clientY <= rect.bottom
  if (!inside) hoverTime.value = null
  timelineAction.value = 'idle'
  panDrag = null
}

const onTimelinePointerDown = (e: PointerEvent) => {
  if (e.button !== 0 && e.button !== 1) return
  e.preventDefault()
  const t = timeFromClientX(e.clientX)
  hoverTime.value = t
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)

  if (e.button === 1 || e.altKey) {
    timelineAction.value = 'pan'
    panDrag = { originX: e.clientX, originStart: timelineViewStart.value }
    bumpFollowSuspend()
    return
  }

  stopClipPlayback()
  timelineAction.value = 'scrub'
  const hit = clips.value.findIndex((c) => clipHasEnd(c) && t >= c.startTime && t <= c.endTime)
  if (hit >= 0 && hit !== selectedClipIdx.value) {
    selectedClipIdx.value = hit
    applyClipVisuals(clips.value[hit])
  }
  seekTo(t)
}

const onTimelinePointerMove = (e: PointerEvent) => {
  const t = timeFromClientX(e.clientX)
  hoverTime.value = t

  if (timelineAction.value === 'pan' && panDrag) {
    const width = timelineRef.value?.getBoundingClientRect().width || 1
    const dt = ((panDrag.originX - e.clientX) / width) * viewSpan.value
    clampTimelineView(panDrag.originStart + dt, panDrag.originStart + dt + viewSpan.value)
    return
  }

  if (timelineAction.value === 'scrub') seekTo(t)
}

const onTimelinePointerUp = (e: PointerEvent) => {
  if (timelineAction.value === 'idle') return
  endPointerOn(e.currentTarget as HTMLElement, e)
}

const onTimelinePointerLeave = () => {
  if (timelineAction.value === 'idle') hoverTime.value = null
}

const onTimelineDblClick = (e: MouseEvent) => {
  const t = timeFromClientX(e.clientX)
  const hit = clips.value.findIndex((c) => clipHasEnd(c) && t >= c.startTime && t <= c.endTime)
  if (hit >= 0) {
    selectedClipIdx.value = hit
    applyClipVisuals(clips.value[hit])
    zoomToClip(clips.value[hit])
    return
  }
  resetTimelineZoom()
}

const onOverviewPointerDown = (e: PointerEvent) => {
  if (e.button !== 0) return
  e.preventDefault()
  const t = timeFromOverviewX(e.clientX)
  const start = timelineViewStart.value
  const end = timelineViewEnd.value
  if (isTimelineZoomed.value && t >= start && t <= end) {
    overviewDragAnchor = t - start
  } else {
    overviewDragAnchor = viewSpan.value / 2
    clampTimelineView(t - overviewDragAnchor, t - overviewDragAnchor + viewSpan.value)
  }
  timelineAction.value = 'overview'
  bumpFollowSuspend()
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

const onOverviewPointerMove = (e: PointerEvent) => {
  if (timelineAction.value !== 'overview') return
  const t = timeFromOverviewX(e.clientX)
  clampTimelineView(t - overviewDragAnchor, t - overviewDragAnchor + viewSpan.value)
}

const onOverviewPointerUp = (e: PointerEvent) => {
  if (timelineAction.value !== 'overview') return
  endPointerOn(e.currentTarget as HTMLElement, e)
}

const syncPlaybackClock = () => {
  if (!videoRef.value || isReloading.value || isScrubbing.value) return
  currentTime.value = playbackClock()

  if (clipPlayMode.value) {
    const curClip = clips.value[selectedClipIdx.value]
    if (curClip && clipHasEnd(curClip)) {
      if (currentTime.value >= curClip.endTime) {
        if (clipPlayMode.value === 'loop') {
          seekTo(curClip.startTime)
        } else {
          clipPlayMode.value = null
          pendingPlay.value = false
          videoRef.value.pause()
          seekTo(curClip.endTime)
        }
      } else if (currentTime.value < curClip.startTime - 0.2) {
        seekTo(curClip.startTime)
      }
    }
  }

  if (isPlaying.value && timelineAction.value === 'idle') {
    keepPlayheadInView(currentTime.value)
  }
}

const stopClockLoop = () => {
  if (!clockRaf) return
  cancelAnimationFrame(clockRaf)
  clockRaf = 0
}

const tickClock = () => {
  clockRaf = requestAnimationFrame(tickClock)
  syncPlaybackClock()
}

const startClockLoop = () => {
  if (clockRaf) return
  clockRaf = requestAnimationFrame(tickClock)
}

const onPlay = () => {
  isPlaying.value = true
  startClockLoop()
}

const onPause = () => {
  isPlaying.value = false
  stopClockLoop()
  syncPlaybackClock()
}

const onTimeUpdate = () => {
  if (isPlaying.value) return
  syncPlaybackClock()
}

const onLoadedMetadata = () => {
  if (!videoRef.value) return
  videoRef.value.volume = 0.5
  applyPlaybackRate()
  if (nativeRangeSeek.value && !initialSeekDone) {
    const t = clips.value[selectedClipIdx.value]?.startTime ?? currentTime.value
    if (t != null) {
      initialSeekDone = true
      videoRef.value.currentTime = t
      currentTime.value = t
    }
  }
}

const onCanPlay = () => {
  if (pendingProxySeek != null && videoRef.value && nativeRangeSeek.value) {
    const t = pendingProxySeek
    pendingProxySeek = null
    videoRef.value.currentTime = t
  }
  applyPlaybackRate()
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
  const curClip = selectedClip.value
  if (!curClip) return
  const turningOn = !cropActive.value
  if (turningOn && !curClip.crop && !currentCrop.value) {
    aspectMode.value = defaultCropAspect.value
    cropRadius.value = defaultCropRadius.value
  }
  cropActive.value = turningOn
}

const clearCrop = () => {
  if (!hasSelectedClip.value) return
  cropActive.value = false
  const curClip = clips.value[selectedClipIdx.value]
  if (curClip) {
    curClip.crop = undefined
    curClip.cropRadius = 0
    currentCrop.value = null
    cropRadius.value = 0
    refreshThumbnail(curClip)
  }
}

const onRadiusInput = (e: Event) => {
  if (!hasSelectedClip.value) return
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
  if (!hasSelectedClip.value) return
  if (cropOverlayRef.value) {
    cropOverlayRef.value.resetToDefault()
  }
}

function evenCrop(n: number) {
  return n - (n % 2)
}

function clampCropBox(
  x: number,
  y: number,
  w: number,
  h: number,
): [number, number, number, number] {
  const vw = Math.max(16, props.mediaInfo.width)
  const vh = Math.max(16, props.mediaInfo.height)
  const bw = Math.max(16, Math.min(evenCrop(w), evenCrop(vw)))
  const bh = Math.max(16, Math.min(evenCrop(h), evenCrop(vh)))
  const bx = evenCrop(Math.max(0, Math.min(Math.round(x), vw - bw)))
  const by = evenCrop(Math.max(0, Math.min(Math.round(y), vh - bh)))
  return [bx, by, bw, bh]
}

const applyCropShapeToAll = () => {
  if (!hasSelectedClip.value || !currentCrop.value) return
  const [, , sw, sh] = currentCrop.value
  const radiusCopy = cropRadius.value
  const vw = Math.max(16, props.mediaInfo.width)
  const vh = Math.max(16, props.mediaInfo.height)
  clips.value.forEach((c) => {
    const ox = c.crop ? c.crop[0] : Math.floor((vw - sw) / 2)
    const oy = c.crop ? c.crop[1] : Math.floor((vh - sh) / 2)
    c.crop = clampCropBox(ox, oy, sw, sh)
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
  const curClip = selectedClip.value
  if (curClip) {
    curClip.startTime = Number(currentTime.value.toFixed(3))
    if (curClip.endTime != null && curClip.endTime <= curClip.startTime) {
      curClip.endTime = null
      curClip.duration = 0
    } else if (curClip.endTime != null) {
      curClip.duration = curClip.endTime - curClip.startTime
    }
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

const toggleMirror = () => {
  const curClip = selectedClip.value
  if (!curClip) return
  currentMirror.value = !currentMirror.value
  curClip.mirror = currentMirror.value
  if (curClip.crop) {
    const vw = Math.max(16, props.mediaInfo.width)
    const [cx, cy, cw, ch] = curClip.crop
    const newCx = Math.max(0, Math.min(vw - cw, vw - cx - cw))
    curClip.crop = [newCx, cy, cw, ch]
    currentCrop.value = [...curClip.crop]
  }
  refreshThumbnail(curClip)
}

const clipContextMenu = ref({
  visible: false,
  x: 0,
  y: 0,
  clipIdx: -1,
})

const closeClipContextMenu = () => {
  clipContextMenu.value.visible = false
}

const onClipContextMenu = (e: MouseEvent, idx: number) => {
  e.preventDefault()
  e.stopPropagation()
  selectClip(idx)

  const menuWidth = 160
  const menuHeight = 120
  const x = Math.min(e.clientX, window.innerWidth - menuWidth - 8)
  const y = Math.min(e.clientY, window.innerHeight - menuHeight - 8)

  clipContextMenu.value = {
    visible: true,
    x: Math.max(8, x),
    y: Math.max(8, y),
    clipIdx: idx,
  }
}

const playClipFromMenu = (mode: 'once' | 'loop') => {
  const idx = clipContextMenu.value.clipIdx
  closeClipContextMenu()
  if (idx >= 0 && idx < clips.value.length) {
    playClip(idx, mode)
  }
}

const deleteClipFromMenu = () => {
  const idx = clipContextMenu.value.clipIdx
  closeClipContextMenu()
  if (idx >= 0 && idx < clips.value.length) {
    deleteClip(idx)
  }
}

const onSelectedClipEmojiInput = (val: string) => {
  const clip = selectedClip.value
  if (clip) clip.emoji = val
}


const applyClipVisuals = (curClip: ClipItem) => {
  currentMirror.value = !!curClip.mirror
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

const selectClip = (idx: number) => {
  selectedClipIdx.value = idx
  const curClip = clips.value[idx]
  if (!curClip) return

  if (videoRef.value) {
    seekTo(curClip.startTime)
  }
  applyClipVisuals(curClip)
  zoomToClip(curClip)
}

const clearClipSelection = () => {
  if (selectedClipIdx.value < 0) return
  selectedClipIdx.value = -1
  stopClipPlayback()
}

const playClip = (idx: number, mode: 'once' | 'loop') => {
  if (clipPlayMode.value === mode && selectedClipIdx.value === idx && videoRef.value && !videoRef.value.paused) {
    videoRef.value.pause()
    stopClipPlayback()
    return
  }
  pendingPlay.value = true
  clipPlayMode.value = mode
  selectClip(idx)
  applyPlaybackRate()
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
  const dur = props.mediaInfo.duration || 0
  const newStart = Number(Math.max(0, Math.min(currentTime.value, dur)).toFixed(3))
  const newClip: ClipItem = {
    id: `clip-${Date.now()}`,
    startTime: newStart,
    endTime: null,
    duration: 0,
    emoji: '',
    crop: currentCrop.value ? [...currentCrop.value] : undefined,
    cropRadius: currentCrop.value ? cropRadius.value : 0,
    mirror: currentMirror.value,
  }
  clips.value.push(newClip)
  selectedClipIdx.value = clips.value.length - 1
  applyClipVisuals(newClip)
  refreshThumbnail(newClip)
}

const onClipStartChange = (idx: number, val: string) => {
  const t = parseTime(val)
  const clip = clips.value[idx]
  if (t === null || !clip) return
  clip.startTime = t
  if (clip.endTime != null && clip.endTime <= t) {
    clip.endTime = null
    clip.duration = 0
  } else if (clip.endTime != null) {
    clip.duration = clip.endTime - t
  }
  refreshThumbnail(clip)
}

const onClipEndChange = (idx: number, e: Event) => {
  const el = e.target as HTMLInputElement
  const clip = clips.value[idx]
  if (!clip) return
  const raw = el.value.trim()
  if (!raw) {
    clip.endTime = null
    clip.duration = 0
    return
  }
  const t = parseTime(raw)
  if (t === null || t <= clip.startTime) {
    el.value = clip.endTime == null ? '' : formatTime(clip.endTime)
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
  if (clip.mirror) {
    url += '&mirror=1'
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
  showOverview.value = true
  setPlaybackRate(1, false)
}

function persistClipSettings() {
  if ((window as any).pywebview?.api?.save_settings) {
    ;(window as any).pywebview.api.save_settings({
      small_step_sec: smallStep.value,
      large_step_sec: largeStep.value,
      default_crop_aspect: defaultCropAspect.value,
      default_crop_radius: defaultCropRadius.value,
      show_timeline_overview: showOverview.value,
      playback_rate: playbackRate.value,
    })
  }
}

function toggleOverview() {
  showOverview.value = !showOverview.value
  persistClipSettings()
}

const saveClipSettings = () => {
  showClipSettings.value = false
  persistClipSettings()
}

const confirmClips = () => {
  if (isVideo.value) {
    for (const c of clips.value) {
      if (!clipHasEnd(c)) {
        alert(`时间区间无效：请为片段设置结束时间（起点 ${formatTime(c.startTime)}）`)
        return
      }
    }
  }
  const curClip = clips.value[selectedClipIdx.value]
  if (curClip) {
    if (currentCrop.value) {
      curClip.crop = [...currentCrop.value]
      curClip.cropRadius = cropRadius.value
    } else {
      curClip.crop = undefined
      curClip.cropRadius = 0
    }
    curClip.mirror = currentMirror.value
  }
  emit('confirm', clips.value)
}

// Hotkey listener
const onKeyDown = (e: KeyboardEvent) => {
  if (clipContextMenu.value.visible) {
    if (e.key === 'Escape') {
      e.preventDefault()
      closeClipContextMenu()
      return
    }
  }

  if (showClipSettings.value) return
  if (
    e.target instanceof HTMLInputElement
    || e.target instanceof HTMLTextAreaElement
    || e.target instanceof HTMLSelectElement
  ) return

  if (e.key === 'm' || e.key === 'M') {
    if (!hasSelectedClip.value) return
    e.preventDefault()
    toggleMirror()
    return
  }

  if (!isVideo.value) return

  if (e.code === 'Space') {
    e.preventDefault()
    togglePlay()
  } else if (e.key === ',' || e.key === '<') {
    e.preventDefault()
    nudgePlaybackRate(-1)
  } else if (e.key === '.' || e.key === '>') {
    e.preventDefault()
    nudgePlaybackRate(1)
  } else if (e.key === '[') {
    if (!hasSelectedClip.value) return
    e.preventDefault()
    setCurrentAsStart()
  } else if (e.key === ']') {
    if (!hasSelectedClip.value) return
    e.preventDefault()
    setCurrentAsEnd()
  } else if (e.code === 'ArrowLeft') {
    e.preventDefault()
    seekRelative(e.shiftKey ? -largeStep.value : -smallStep.value)
  } else if (e.code === 'ArrowRight') {
    e.preventDefault()
    seekRelative(e.shiftKey ? largeStep.value : smallStep.value)
  } else if (e.key === '=' || e.key === '+') {
    e.preventDefault()
    zoomTimelineAt(currentTime.value, 0.84)
  } else if (e.key === '-' || e.key === '_') {
    e.preventDefault()
    zoomTimelineAt(currentTime.value, 1.19)
  } else if (e.key === '0') {
    e.preventDefault()
    resetTimelineZoom()
  } else if (e.key === 'f' || e.key === 'F') {
    if (!hasSelectedClip.value) return
    e.preventDefault()
    zoomToSelectedClip()
  }
}

const applyProxyReady = () => {
  const clock = isReloading.value ? currentTime.value : playbackClock()
  const wasPlaying = videoRef.value ? !videoRef.value.paused : false
  proxyReady.value = true
  proxyLoading.value = false
  proxyError.value = null
  pendingPlay.value = wasPlaying || pendingPlay.value
  pendingProxySeek = clock
  streamOffset.value = 0
  streamReloadNonce.value += 1
  isReloading.value = true
}

const checkProxyStatus = async (start = false) => {
  if (!needsProxyFile.value || !props.streamBaseUrl) return
  if (proxyPollTimer) {
    clearTimeout(proxyPollTimer)
    proxyPollTimer = null
  }
  const enc = encodeURIComponent(props.mediaInfo.file_path)
  const qs = start ? 'start=1' : 'start=0'
  try {
    const res = await fetch(`${props.streamBaseUrl}/proxy_status?path=${enc}&${qs}`)
    if (!res.ok) {
      if (proxyLoading.value) {
        proxyLoading.value = false
        proxyError.value = `查询代理状态失败 (HTTP ${res.status})`
      }
      return
    }
    const data = await res.json()
    if (data.status === 'ready' || data.status === 'not_needed') {
      if (!proxyReady.value) applyProxyReady()
      else {
        proxyReady.value = true
        proxyLoading.value = false
        proxyError.value = null
      }
      return
    }
    if (data.status === 'error') {
      proxyLoading.value = false
      proxyError.value = data.error || '代理生成失败'
      return
    }
    if (data.status === 'generating') {
      proxyLoading.value = true
      const pct = (data.progress || 0) * 100
      proxyProgress.value = pct > 0 ? Math.max(1, Math.min(99, Math.round(pct))) : 0
      proxyPollTimer = setTimeout(() => checkProxyStatus(false), 200)
    } else if (start || proxyLoading.value) {
      proxyLoading.value = true
      if (data.status === 'not_started' && proxyLoading.value) {
        proxyPollTimer = setTimeout(() => checkProxyStatus(true), 300)
      } else {
        proxyPollTimer = setTimeout(() => checkProxyStatus(false), 200)
      }
    }
  } catch {
    if (proxyLoading.value) {
      proxyPollTimer = setTimeout(() => checkProxyStatus(false), 500)
    }
  }
}

const startProxyCache = () => {
  if (proxyReady.value || proxyLoading.value) return
  proxyError.value = null
  proxyLoading.value = true
  proxyProgress.value = 0
  void checkProxyStatus(true)
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('click', closeClipContextMenu)
  clips.value.forEach(c => refreshThumbnail(c))
  if (isVideo.value) {
    const focused = clips.value[selectedClipIdx.value] || clips.value[0]
    if (focused) zoomToClip(focused)
  }

  const reopenedGroup = !!(props.initialClips && props.initialClips.length > 0)
  if ((window as any).pywebview?.api?.get_settings) {
    ;(window as any).pywebview.api.get_settings().then((st: any) => {
      if (st.small_step_sec != null) smallStep.value = st.small_step_sec
      if (st.large_step_sec != null) largeStep.value = st.large_step_sec
      if (st.default_crop_aspect) defaultCropAspect.value = st.default_crop_aspect
      if (st.default_crop_radius != null) defaultCropRadius.value = clampCropRadius(st.default_crop_radius)
      if (st.show_timeline_overview != null) showOverview.value = !!st.show_timeline_overview
      if (st.playback_rate != null) setPlaybackRate(Number(st.playback_rate), false)
      if (!props.initialCrop && !reopenedGroup) {
        aspectMode.value = defaultCropAspect.value
      }
      if (props.initialCropRadius == null && !reopenedGroup) {
        cropRadius.value = defaultCropRadius.value
        const first = clips.value[0]
        if (first && !first.crop) first.cropRadius = defaultCropRadius.value
      }
      if (needsProxyFile.value) void checkProxyStatus(false)
    })
  } else if (needsProxyFile.value) {
    void checkProxyStatus(false)
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('click', closeClipContextMenu)
  stopClockLoop()
  if (serverSeekTimer != null) clearTimeout(serverSeekTimer)
  if (proxyPollTimer) {
    clearTimeout(proxyPollTimer)
    proxyPollTimer = null
  }
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

.overview {
  position: relative;
  height: 16px;
  border-radius: 4px;
  background: #12141c;
  border: 1px solid #252833;
  cursor: pointer;
  overflow: hidden;
  touch-action: none;
}
.overview.is-dragging {
  cursor: grabbing;
}
.overview-window {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgba(56, 189, 248, 0.16);
  border: 1px solid rgba(56, 189, 248, 0.55);
  border-radius: 3px;
  pointer-events: none;
}
.overview-clip {
  position: absolute;
  top: 3px;
  height: 10px;
  border-radius: 1px;
  background: rgba(56, 189, 248, 0.32);
  pointer-events: none;
}
.overview-clip.is-active {
  background: rgba(56, 189, 248, 0.75);
}
.overview-head {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  margin-left: -0.5px;
  background: #f8fafc;
  pointer-events: none;
}

.timeline {
  position: relative;
  height: 48px;
  cursor: pointer;
  touch-action: none;
  outline: none;
  overflow: hidden;
}
.timeline.is-panning {
  cursor: grabbing;
}
.timeline:focus-visible {
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.35);
  border-radius: 6px;
}
.timeline-track {
  position: absolute;
  left: 0;
  right: 0;
  top: 26px;
  height: 8px;
  border-radius: 999px;
  background: #1a1d27;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}
.timeline-played {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0284c7, #38bdf8);
  opacity: 0.38;
}
.timeline-clip {
  position: absolute;
  top: 22px;
  height: 16px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.2);
  border: 1px solid rgba(56, 189, 248, 0.28);
  pointer-events: none;
}
.timeline-clip.is-active {
  height: 18px;
  top: 21px;
  background: rgba(56, 189, 248, 0.52);
  border-color: rgba(186, 230, 253, 0.9);
  box-shadow: 0 0 0 1px rgba(14, 165, 233, 0.2);
}
.timeline-tick {
  position: absolute;
  top: 2px;
  width: 1px;
  height: 6px;
  background: #3b4254;
  pointer-events: none;
}
.timeline-tick-label {
  position: absolute;
  top: 8px;
  transform: translateX(-50%);
  font-size: 9px;
  line-height: 1;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
  white-space: nowrap;
}
.timeline-hover-line {
  position: absolute;
  top: 18px;
  bottom: 4px;
  width: 1px;
  margin-left: -0.5px;
  background: rgba(255, 255, 255, 0.35);
  pointer-events: none;
}
.timeline-head {
  position: absolute;
  top: 16px;
  bottom: 4px;
  width: 2px;
  margin-left: -1px;
  background: #f8fafc;
  border-radius: 1px;
  box-shadow: 0 0 0 1px rgba(14, 165, 233, 0.45), 0 0 8px rgba(56, 189, 248, 0.4);
  pointer-events: none;
  z-index: 4;
}
.timeline-head::before {
  content: '';
  position: absolute;
  top: -3px;
  left: 50%;
  width: 11px;
  height: 11px;
  margin-left: -5.5px;
  border-radius: 999px;
  background: #fff;
  border: 2px solid #38bdf8;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.45);
}
</style>
