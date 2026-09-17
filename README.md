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
| **批量导入** | 拖拽文件 / 文件夹，或用对话框多选。支持 MP4、MKV、WebM、MOV、AVI、FLV、M4V、PNG、JPG、WebP、GIF、APNG、BMP、TIFF、ICO、HEIC/HEIF |
| **视频贴纸** | 长边 512px、无音轨 VP9 WebM，体积压到 **≤ 256 KB** |
| **自定义表情** | 固定 100×100，体积压到 **≤ 64 KB** |
| **静态贴纸** | Lanczos 缩放 WebP（优先无损，超限再有损），**≤ 512 KB** |
| **裁切与外形** | 全窗口时间轴截取；画面自由 / 1:1 / 原始 / 16:9 / 4:3 / 9:16；圆角 0%（直角）→ 100%（正圆或胶囊形），边缘带 Alpha。默认比例与圆角会记住 |
| **画质规划** | 运动量探测 + 2-Pass VP9 VBR；体积超限最多 **4 次**码率 / 帧率回退（30→24→20→18→15，极限 12 fps） |
| **3 秒破限** | 保留全部帧，仅把 WebM EBML 头部 Duration 写成 `2.99s`，便于通过 `@Stickers` 时长检查 |
| **关键词** | 每张贴纸最多 20 个关键词、合计 64 字符，写入输出目录的 `stickers.json` |
| **AI Emoji** | 兼容 OpenAI Vision API，按表情推荐 Emoji，并按 `{序号}_{Emoji}` 命名 |
| **转换输出** | 「开始转换」旁默认勾选「输出为压缩包」：ZIP 内含贴纸 + `stickers.json`。取消勾选则写入时间戳文件夹（如 `TG_Stickers_20260916_153045`），同样带清单，不散落文件 |
| **贴纸列表** | 不转码即可导出 / 导入：源文件+JSON，或已裁切的转换前文件。进度可取消；拖入 zip / JSON 也能还原 |

---

## Telegram 规格对照

| 类型 | 分辨率 | 格式 | 编码 | 体积上限 | 官方时长 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 常规视频贴纸 | 一边 512px，另一边 ≤ 512px | `.webm` | VP9，无音频 | **≤ 256 KB** | ≤ 3.0 s（本工具可破限） |
| 自定义表情 | **100 × 100** | `.webm` | VP9，无音频 | **≤ 64 KB** | ≤ 3.0 s |
| 静态贴纸 | 一边 512px，另一边 ≤ 512px | `.webp` | WebP，可透明 | **≤ 512 KB** | — |

输出像素会按 **16 对齐**（自定义表情固定 100×100，短边偶数对齐），避免 VP9 缩放伪影。透明 GIF / APNG / 带 Alpha 的视频走 `yuva420p`；圆角或圆形裁切会保留透明通道。iPhone HEIC/HEIF 经 Pillow 预处理后编码。

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

仓库已包含 `frontend/dist` 构建产物，日常使用不必装 Node。生产模式由本地流服务托管该产物。

### 3. 运行测试

```bash
uv run pytest
```

---

## 使用流程

1. **导入**：把文件或文件夹拖进窗口，或点「添加文件 / 添加文件夹」。也可点「导入」，或直接拖入之前导出的 zip / JSON。任务列表会自动保存到本机配置目录，关掉再开会接着做（源文件仍须在原位置）。
2. **规格**：右侧选择「标准贴纸 512px」或「自定义表情 100px」，再选编码预设。
3. **裁切（可选）**：点条目上的剪刀，或工具栏「截取视频片段」，打开全窗口预览。
   - 时间：拖时间轴、滚轮缩放 / 平移、`[` / `]` 打点。
   - 播放：空格播放 / 暂停；可调倍速（`,` 减速、`.` 加速）；片段列表可「播放一次」或「循环」。
   - 画面：开启裁切框，调比例与圆角。默认比例 / 圆角会写入设置。
   - 一段素材可拆成多条片段：点「添加片段」从当前指针开始、终点留空，再用 `]` 打终点。确认后同一组会记住，再点剪刀会整组重开。
4. **Emoji / 关键词**：可手改 Emoji；点条目上的关键词打开编辑（最多 20 个、合计 64 字符）。也可开 AI 批量识别（右上角设置）。
5. **输出**：默认 `桌面/TG_Stickers`，或勾选「保存至原文件所在目录」。
   - 勾选「输出为压缩包」（默认）：成功项打成 `TG_Stickers_时间戳.zip`，内含 `stickers.json`。
   - 不勾选：写入同级时间戳文件夹，并生成 `stickers.json`，避免散落在输出目录根下。
6. **转换或导出**：点「开始转换」压成贴纸；或点「导出」只保存列表 / 原片（见下节）。最多 **2 路并行**；转换、导出、导入都可随时停止。

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

## 贴纸列表：导出与导入

「开始转换」旁的 **导出** 不走贴纸码率，用于备份任务或换机继续做：

| 模式 | 勾选「输出为压缩包」 | 不勾选 |
| :--- | :--- | :--- |
| **源文件 + JSON** | 打包原片与参数清单为 zip（`sticker_list.json`） | 复制原片到文件夹，并附带参数清单 |
| **贴纸列表文件** | 按当前裁切结果打包已裁切源文件（不压成贴纸码率） | 同样输出已裁切源文件到文件夹 |

列表会记下路径、起止时间、裁切框、圆角 / 形状、Emoji、关键词和片段分组。圆形或圆角视频导出为带 Alpha 的 WebM，再导入后转换仍保留透明通道。

**导入**：点「导入」，或把 zip / JSON / 导出文件夹拖进窗口。会还原裁切、片段与关键词；缺失的源文件会跳过并记入日志。导入过程显示进度，可点「停止」取消。

---

## 截取预览

截取窗口铺满整个应用。MP4 / WebM 走 HTTP Range 直出，拖进度不卡。MKV 等浏览器不好快进的格式，可点右上角 **缓存代理**：生成 480p H.264 代理并缓存在系统临时目录（`tg_sticker_maker_proxies`）。右侧「预览代理」可查看占用并一键清除。

时间轴：

- 滚轮缩放，拖动平移；「总览」条可显示 / 隐藏并记住。
- 「适应片段」（`F`）把当前片段放到中间；`0` 回到全长。
- 不能拖片段边缘改起止，避免误触；用 `[` / `]` 或时间输入改。

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

提示词偏向聊天表情（😂😭😡🥺 等），避免装饰性符号。识别失败时留空，可手动填写。右键任务可对选中项批量识别。

---

## 快捷键

**任务列表**

| 键 | 作用 |
| :--- | :--- |
| `Ctrl` / `⌘` + `A` | 全选 |
| `Delete` | 删除选中（转换 / 导出 / 导入中不可用） |
| `Esc` | 取消选择 |

**裁切预览（视频）**

| 键 | 作用 |
| :--- | :--- |
| `Space` | 播放 / 暂停 |
| `[` / `]` | 当前时刻设为起点 / 终点 |
| `←` / `→` | 小步跳转（默认 0.5s） |
| `Shift` + `←` / `→` | 大步跳转（默认 5s） |
| `+` / `-` | 时间轴放大 / 缩小 |
| `F` | 适应选中片段 |
| `0` | 显示完整时长 |

步长可在预览窗设置里改，并写入配置。片段列表上的播放按钮：播一次到头停止，或循环该片段。

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

可选：`uv run app --port 8765` 固定本地流服务端口（默认随机）。该服务同时提供 Range 预览、缩略图、代理状态，以及生产模式下的前端静态资源。

---

## 项目结构

```
sticker_maker/
├── main_web.py              # pywebview 入口
├── core/                    # 分析、规划、编码、打包、导入导出
│   ├── analyzer.py
│   ├── encode_plan.py       # 码率 / 帧率 / 滤镜规划（无 I/O）
│   ├── encoder.py           # FFmpeg 执行与体积回退
│   ├── ebml_patcher.py
│   ├── crop_shape.py
│   ├── pack_output.py       # ZIP / 时间戳文件夹 + stickers.json
│   ├── sticker_list.py      # 贴纸列表导出 / 导入（不转码）
│   ├── session_store.py     # 关闭后再开的任务进度
│   ├── proxy_manager.py     # 480p 预览代理缓存
│   ├── ai_tagger.py
│   └── settings_store.py
├── server/
│   ├── api.py               # 暴露给前端的 JS API
│   └── stream_server.py     # HTTP 206 预览流 + 缩略图 + dist
├── frontend/                # Vue 3 + Tailwind 4 + Vite
├── tests/
├── pyproject.toml
└── 启动.bat
```

架构：`pywebview` 原生窗加载前端；Python `AppAPI` 做转码、设置与列表导入导出；本地 `ThreadingHTTPServer` 提供 Range 流（MP4/WebM 直出，MKV 等可转封装或走代理），保证长视频拖进度不卡。

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

**MKV 预览拖进度卡顿**  
在截取窗口点「缓存代理」，等 480p 代理生成后再拖。缓存可在右侧「清除预览缓存」删掉。

**AI 一直失败**  
检查 Base URL 是否带 `/v1`、模型是否支持 vision、密钥是否有效。

**关掉再开，上次的列表还在吗**  
会。任务、裁切、Emoji、关键词会写到 `%USERPROFILE%\.config\telegram_sticker_maker\session.json`（macOS / Linux 为 `~/.config/telegram_sticker_maker/`）。源文件被移动或删除的项会跳过。换电脑请仍用「导出」带走原片。

**导入后缺文件**  
「源文件 + JSON」依赖当时的绝对路径；换机器请用带原片的 zip / 文件夹导出。缺失项会跳过并写日志。

**macOS / Linux 白屏或无法拖文件**  
pywebview 需要系统 WebView（GTK/Qt 或 WebKit）。Windows 走 Edge WebView2；`pythonnet` 仅在 Windows 作为依赖安装。

---

## 许可与声明

MIT License。EBML 时长补丁仅改容器头部，不删帧。是否允许上传以 Telegram 当时规则为准，本仓库不保证 `@Stickers` 永久接受破限文件。
