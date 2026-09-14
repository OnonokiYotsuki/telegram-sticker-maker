export interface MediaInfo {
  file_path: string
  file_name: string
  file_size: number
  is_video: boolean
  width: number
  height: number
  duration: number
  fps: number
  has_alpha: boolean
  format_name: string
  video_codec: string
  error?: string
}

export function clampCropRadius(radius?: number | null): number {
  if (radius == null || Number.isNaN(radius)) return 0
  return Math.max(0, Math.min(1, radius))
}

export function cropRadiusLabel(radius?: number | null): string {
  const r = clampCropRadius(radius)
  if (r <= 0.001) return '直角'
  if (r >= 0.999) return '圆形'
  return `圆角 ${Math.round(r * 100)}%`
}

export interface TaskItem {
  taskId: number
  inputPath: string
  outputPath: string
  mediaInfo: MediaInfo
  emoji: string
  index: number
  clipLabel?: string
  startTime?: number
  endTime?: number
  crop?: [number, number, number, number]
  cropRadius?: number
  status: 'waiting' | 'converting' | 'success' | 'failed'
  progress: number
  statusMsg: string
  outputSize: number
}

export interface GlobalOptions {
  preset_style: 'anime' | 'cinema' | 'fast'
  is_custom_emoji: boolean
  same_dir: boolean
  custom_output_dir: string
}

export interface AppSettings extends GlobalOptions {
  spoof_duration?: boolean
  optimize_fps?: boolean
  use_emoji_naming?: boolean
  zero_pad?: boolean
  small_step_sec?: number
  large_step_sec?: number
  ai_base_url?: string
  ai_model?: string
  ai_api_key?: string
}

export interface AppInfo {
  version: string
  stream_base_url: string
  os: string
}

export interface AppAPI {
  get_info: () => Promise<AppInfo>
  get_settings: () => Promise<AppSettings>
  save_settings: (data: Partial<AppSettings>) => Promise<{ status?: string; error?: string }>
  get_dropped_files: () => Promise<string[]>
  scan_directory: (folder_path: string) => Promise<string[]>
  select_files: () => Promise<string[]>
  select_directory: () => Promise<string>
  open_folder: (folder_path: string) => Promise<void>
  analyze_file: (file_path: string) => Promise<MediaInfo>
  get_stream_url: (file_path: string, t?: number) => Promise<string>
  get_thumbnail_url: (
    file_path: string,
    t?: number,
    crop?: string | null,
    size?: number,
    radius?: number | null,
  ) => Promise<string>
  start_conversion: (tasks: Record<string, unknown>[], global_options: Record<string, unknown>) => Promise<{ status: string }>
  cancel_conversion: () => Promise<void>
  ai_tag_single: (task_id: number, input_path: string, start_time?: number, end_time?: number) => Promise<{ status: string }>
  ai_tag_all: (tasks: Record<string, unknown>[]) => Promise<{ status: string }>
}

export interface ClipItem {
  id: string
  startTime: number
  endTime: number
  duration: number
  emoji: string
  crop?: [number, number, number, number]
  cropRadius?: number
}

declare global {
  interface Window {
    pywebview?: {
      api?: AppAPI
      platform?: string
      _QWebChannel?: unknown
    }
    chrome?: {
      webview?: {
        postMessage: (message: any) => void
        postMessageWithAdditionalObjects?: (message: any, objects: any) => void
      }
    }
    onLog?: (msg: string) => void
    onTaskStarted?: (taskId: number) => void
    onTaskProgress?: (taskId: number, p: number, msg: string) => void
    onTaskFinished?: (taskId: number, success: boolean, msg: string, outPath: string, size: number) => void
    onAllCompleted?: () => void
    onAiItemStarted?: (taskId: number, fileName: string) => void
    onAiItemFinished?: (taskId: number, emoji: string) => void
    onAiItemError?: (taskId: number, err: string) => void
    onAiAllCompleted?: () => void
  }
}
