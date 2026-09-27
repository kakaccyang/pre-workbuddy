#!/bin/bash
# 下载本地对话模型 Qwen3.5-4B-Q4_K_M.gguf 到 model_file/ 目录
# 优先用 ModelScope（国内速度快），没有则用 HuggingFace
# 可用环境变量覆盖：MODEL_REPO / MODEL_FILE
set -e
cd "$(dirname "$0")"

MODEL_REPO="${MODEL_REPO:-Qwen/Qwen3.5-4B-GGUF}"
MODEL_FILE="${MODEL_FILE:-Qwen3.5-4B-Q4_K_M.gguf}"
SAVE_DIR="model_file"

if [ -f "$SAVE_DIR/$MODEL_FILE" ]; then
  echo "模型已存在：$SAVE_DIR/$MODEL_FILE ，跳过下载"
  exit 0
fi

mkdir -p "$SAVE_DIR"

if command -v modelscope >/dev/null 2>&1; then
  echo "使用 ModelScope 下载 $MODEL_REPO/$MODEL_FILE ..."
  modelscope download --model "$MODEL_REPO" "$MODEL_FILE" --local_dir "$SAVE_DIR"
elif command -v hf >/dev/null 2>&1; then
  echo "使用 HuggingFace(hf) 下载 $MODEL_REPO/$MODEL_FILE ..."
  hf download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$SAVE_DIR"
elif command -v huggingface-cli >/dev/null 2>&1; then
  echo "使用 HuggingFace 下载 $MODEL_REPO/$MODEL_FILE ..."
  huggingface-cli download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$SAVE_DIR"
else
  echo "未找到下载工具，请先安装其一："
  echo "  pip install modelscope          # 国内推荐"
  echo "  pip install -U huggingface_hub  # HuggingFace 官方"
  exit 1
fi

echo "下载完成：$SAVE_DIR/$MODEL_FILE"
