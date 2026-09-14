# Telegram Sticker Maker

高质量 Telegram **视频贴纸**（`.webm` / VP9）与 **静态贴纸**（`.webp`）批量转换桌面工具。拖入素材、裁切片段、一键压到官方体积上限。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/Tailwind-4-38B2AC?logo=tailwindcss&logoColor=white" alt="Tailwind CSS 4" />
  <img src="https://img.shields.io/badge/pywebview-5-orange" alt="pywebview" />
  <img src="https://img.shields.io/badge/FFmpeg-VP9%20%7C%20WebM-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg" />
</p>

> 主要面向 Windows。macOS / Linux 在安装 FFmpeg 与 pywebview 对应后端后也可运行。

---

## 能做什么

| 能力 | 说明 |
| :--- | :--- |
| **批量导入** | 拖拽文件 / 文件夹，或用对话框多选。支持 MP4、MKV、WebM、MOV、AVI、FLV、PNG、JPG、WebP、GIF、APNG、HEIC/HEIF |
| **视频贴纸** | 长边 512px、无音轨 VP9 WebM，体积压到 **≤ 256 KB** |
| **自定义表情** | 固定 100×100，体积压到 **≤ 64 KB** |
| **静态贴纸** | Lanczos 缩放 WebP（优先无损，超限再有损），**≤ 512 KB** |
| **裁切与外形** | 时间轴毫秒级截取；画面自由 / 1:1 / 原始 / 16:9 裁切；圆角 0%（直角）→ 100%（正圆或胶囊形），边缘带 Alpha |
| **画质规划** | 运动量探测 + 2-Pass VP9 VBR；体积超限最多 **4 次**码率 / 帧率回退（30→24→20→18→15，极限 12 fps） |
| **3 秒破限** | 保留全部帧，仅把 WebM EBML 头部 Duration 写成 `2.99s`，便于通过 `@Stickers` 时长检查 |
| **AI Emoji** | 兼容 OpenAI Vision API，按表情推荐 Emoji，并按 `{序号}_{Emoji}` 命名 |
| **打包输出** | 「开始转换」旁默认勾选「输出为压缩包」，成功项打成 ZIP |

---

## Telegram 规格对照

| 类型 | 分辨率 | 格式 | 编码 | 体积上限 | 官方时长 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 常规视频贴纸 | 一边 512px，另一边 ≤ 512px | `.webm` | VP9，无音频 | **≤ 256 KB** | ≤ 3.0 s（本工具可破限） |
| 自定义表情 | **100 × 100** | `.webm` | VP9，无音频 | **≤ 64 KB** | ≤ 3.0 s |
| 静态贴纸 | 一边 512px，另一边 ≤ 512px | `.webp` | WebP，可透明 | **≤ 512 KB** | — |

输出像素会按 **16 对齐**（表情为偶数对齐），避免 VP9 缩放伪影。透明 GIF / APNG / 带 Alpha 的视频走 `yuva420p`；iPhone HEIC/HEIF 经 Pillow 预处理后编码。

---

## 快速上手

依赖：[uv](https://github.com/astral-sh/uv)、系统 **FFmpeg**（需在 `PATH` 中）。

### 1. 安装 FFmpeg

```bash
# Windows
winget install Gyan.FFmpeg

# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg
```

确认：

```bash
ffmpeg -version
```

### 2. 安装并启动

```bash
git clone https://github.com/OnonokiYotsuki/telegram-sticker-maker.git
cd telegram-sticker-maker

uv sync
uv run app
```

Windows 也可双击根目录 `启动.bat`（优先走 `uv run app`，否则回退 `python main_web.py`）。

仓库已包含 `frontend/dist` 构建产物，日常使用不必装 Node。

### 3. 运行测试

```bash
uv run pytest
```

---

## 使用流程

1. **导入**：把文件或文件夹拖进窗口，或点「添加文件 / 添加文件夹」。
2. **规格**：右侧选择「标准贴纸 512px」或「自定义表情 100px」，再选编码预设。
3. **裁切（可选）**：点条目上的剪刀图标，打开预览。
   - 时间：拖进度条、`[` / `]` 打点、循环试看。
   - 画面：开启裁切框，调比例与圆角。
   - 一段素材可拆成多条片段，各自带 Emoji。
4. **Emoji**：可手改；也可开 AI 批量识别（右上角设置）。
5. **输出**：默认 `桌面/TG_Stickers`，或勾选「保存至原文件所在目录」。开始转换旁默认勾选「输出为压缩包」。
6. **转换**：点「开始转换」。最多 **2 路并行**；可随时停止。

文件名示例：`001_😂.webm`、`002_🥺.webp`。

---

## 编码预设

| 预设 | 适用 | 行为 |
| :--- | :--- | :--- |
| **动漫 / 插画** | 二次元、线条清晰的插画 | 轻度 `unsharp`，较低 CRF，默认 2-Pass |
| **真人实拍** | 实拍、复杂纹理 | `hqdn3d` 降噪，略高 CRF，默认 2-Pass |
| **快速导出** | 预览、赶时间 | 单遍编码，画质换速度 |

长于约 4 秒且开启智能降帧时，会抽样估算运动量：静止画面尽量保留源帧率，大动作优先降帧以保证体积内的 bpp。体积低于上限约 90% 时，会再抬一档码率把额度用满。

**3 秒破限**：默认开启。真实时长 > 3s 时仍编码完整片段，再原地改写 EBML Duration。这是非官方做法，Telegram 日后可能收紧校验；上传失败时请把片段裁到 3 秒以内再转。

---

## AI Emoji 推荐

右上角 **设置** 中填写：

| 项 | 说明 |
| :--- | :--- |
| API Key | 视觉模型密钥 |
| Base URL | 兼容 OpenAI Chat Completions 的地址，例如 `https://api.openai.com/v1`、`https://api.siliconflow.cn/v1` |
| 模型 | 需支持读图，如 `gpt-4o-mini`、`Pro/Qwen/Qwen2-VL-7B-Instruct` |

也可用本地 Ollama 等 OpenAI 兼容网关。配置保存在：

```
~/.config/telegram_sticker_maker/settings.ini
~/.config/telegram_sticker_maker/ai_config.json
```

（Windows 即 `%USERPROFILE%\.config\telegram_sticker_maker\`）

提示词偏向聊天表情（😂😭😡🥺 等），避免装饰性符号。识别失败时留空，可手动填写。

---

## 快捷键

**任务列表**

| 键 | 作用 |
| :--- | :--- |
| `Ctrl` / `⌘` + `A` | 全选 |
| `Delete` | 删除选中（转换中不可用） |
| `Esc` | 取消选择 |

**裁切预览（视频）**

| 键 | 作用 |
| :--- | :--- |
| `Space` | 播放 / 暂停 |
| `[` / `]` | 当前时刻设为起点 / 终点 |
| `P` | 循环试看选中片段 |
| `←` / `→` | 小步跳转（默认 0.5s） |
| `Shift` + `←` / `→` | 大步跳转（默认 5s） |

步长可在预览窗「步长」里改，并写入设置。

---

## 前端开发

改 Vue 界面时用 Vite 热重载：

```bash
cd frontend
npm install
npm run dev
```

另开终端：

```bash
uv run app --dev
```

桌面会连 `http://localhost:5173`。改完后构建进 `frontend/dist`：

```bash
cd frontend
npm run build
```

可选：`uv run app --port 8765` 固定本地流服务端口（默认随机）。

---

## 项目结构

```
sticker_maker/
├── main_web.py          # pywebview 入口
├── core/                # 分析、规划、编码、EBML、AI
│   ├── analyzer.py
│   ├── encode_plan.py   # 码率 / 帧率 / 滤镜规划（无 I/O）
│   ├── encoder.py       # FFmpeg 执行与体积回退
│   ├── ebml_patcher.py
│   ├── crop_shape.py
│   ├── ai_tagger.py
│   └── settings_store.py
├── server/
│   ├── api.py           # 暴露给前端的 JS API
│   └── stream_server.py # HTTP 206 预览流 + 缩略图
├── frontend/            # Vue 3 + Tailwind 4 + Vite
├── tests/
├── pyproject.toml
└── 启动.bat
```

架构：`pywebview` 原生窗加载前端；Python `AppAPI` 做转码与设置；本地 `ThreadingHTTPServer` 提供 Range 流（MP4/WebM 直出，MKV 等经 FFmpeg 转封装），保证长视频拖进度不卡。

---

## 常见问题

**启动报 `FFmpeg executable not found`**  
FFmpeg 未装，或新开的终端还没刷新 `PATH`。装完重开终端，再跑 `ffmpeg -version`。

**提示未找到前端资源 `frontend/dist/index.html`**  
生产模式依赖构建产物。执行 `cd frontend && npm install && npm run build`，或用 `uv run app --dev` 对着 Vite。

**HEIC 打不开**  
依赖 `pillow-heif`。确认 `uv sync` 成功；个别损坏文件可先用系统工具转成 PNG/JPG。

**体积压不进上限**  
超长、高运动、带透明的片段更难。缩短裁切、改用「自定义表情」以外的 512 规格、或选「快速导出」以外的预设再试。回退最多 4 轮，仍超限会失败。

**AI 一直失败**  
检查 Base URL 是否带 `/v1`、模型是否支持 vision、密钥是否有效。

**macOS / Linux 白屏或无法拖文件**  
pywebview 需要系统 WebView（GTK/Qt 或 WebKit）。Windows 走 Edge WebView2；`pythonnet` 仅在 Windows 作为依赖安装。

---

## 许可与声明

MIT License。EBML 时长补丁仅改容器头部，不删帧。是否允许上传以 Telegram 当时规则为准，本仓库不保证 `@Stickers` 永久接受破限文件。
