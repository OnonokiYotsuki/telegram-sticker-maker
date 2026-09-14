@echo off
chcp 65001 >nul
title Telegram Sticker Maker

echo 正在启动 Telegram Sticker Maker...

where uv >nul 2>nul
if %errorlevel% equ 0 (
    uv run app
) else (
    python main_web.py
)

if %errorlevel% neq 0 (
    echo.
    echo 程序异常退出，请检查是否已通过 uv 或 pip 安装依赖，以及 FFmpeg 是否已加入系统 PATH。
    pause
)
