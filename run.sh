#!/bin/bash
# 啟動名片管理系統：http://localhost:8000
# 第一次執行會自動：clone RapidOCR 原始碼到 vendor/、建立 .venv、安裝套件
cd "$(dirname "$0")"
if [ ! -d vendor/RapidOCR ]; then
  git clone --depth 1 https://github.com/RapidAI/RapidOCR.git vendor/RapidOCR
fi
if [ ! -d .venv ]; then
  uv venv -p 3.11 .venv && source .venv/bin/activate && uv pip install -r requirements.txt
else
  source .venv/bin/activate
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
