import argparse
import os
import sys

import webview

from server.api import AppAPI
from server.stream_server import start_stream_server


def main():
    parser = argparse.ArgumentParser(description="Telegram Sticker Maker - Web Edition")
    parser.add_argument("--dev", action="store_true", help="Launch against Vite dev server at localhost:5173")
    parser.add_argument("--port", type=int, default=0, help="Stream server port")
    args = parser.parse_args()

    # 1. Start local streaming server
    stream_server = start_stream_server(port=args.port)
    print(f"[*] Local stream server listening on: {stream_server.get_url()}")

    # 2. Determine frontend target URL
    api = AppAPI()
    dist_index = os.path.abspath(os.path.join(os.path.dirname(__file__), "frontend", "dist", "index.html"))

    if args.dev:
        target_url = "http://localhost:5173"
        print(f"[*] Connecting to Vite dev server at {target_url}")
    elif os.path.isfile(dist_index):
        target_url = stream_server.get_url()
        print(f"[*] Loading bundled frontend from {target_url}")
    else:
        raise FileNotFoundError(f"未找到前端资源: {dist_index}")

    # 3. Create pywebview native window
    window = webview.create_window(
        title="Telegram Sticker Maker - 贴纸转换工具",
        url=target_url,
        js_api=api,
        width=1500,
        height=820,
        min_size=(1180, 640),
        background_color="#0f1117",
    )

    # 4. Start pywebview GUI loop
    webview.start(debug=args.dev)


if __name__ == "__main__":
    main()

