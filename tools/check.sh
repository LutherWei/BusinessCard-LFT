#!/bin/bash
# 跑單元測試 + 真實名片評估（只列出錯的）
cd "$(dirname "$0")/.."
source .venv/bin/activate
python -m pytest tests/ -q 2>&1 | tail -5
python -m tests.eval_real --set all 2>&1 | grep -v Warn | grep -v "^✅"
