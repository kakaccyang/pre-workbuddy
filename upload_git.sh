#!/bin/bash
# 上传项目到 git：
# 提交前自动把 config.py 里的 API_KEY 替换为占位符，推送完成后自动恢复本地真实 key。
# 用法：
#   ./upload_git.sh "提交说明"          # 提交并推送
# 首次使用先配置远程仓库：
#   git remote add origin <你的仓库地址>
set -e
cd "$(dirname "$0")"

COMMIT_MSG="${1:-update}"
CONFIG_FILE="config.py"
PLACEHOLDER='API_KEY = "your-api-key-here"'

# 首次运行自动 git init
if [ ! -d .git ]; then
  echo "未发现 git 仓库，自动执行 git init"
  git init
fi

# 必须已配置远程仓库
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "错误：还没配置远程仓库，请先执行："
  echo "  git remote add origin <你的仓库地址>"
  exit 1
fi

# 备份真实配置，并保证脚本无论成功失败退出前都恢复
BACKUP_FILE="$(mktemp)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
restore() {
  cp "$BACKUP_FILE" "$CONFIG_FILE"
  rm -f "$BACKUP_FILE"
  echo "本地 config.py 的真实 API_KEY 已恢复"
}
trap restore EXIT

# 隐藏 API_KEY（兼容 macOS sed）
sed -i '' 's|^API_KEY *= *".*"|'"$PLACEHOLDER"'|' "$CONFIG_FILE"
echo "已临时隐藏 config.py 中的 API_KEY"

git add -A
if git diff --cached --quiet; then
  echo "没有需要提交的改动"
  exit 0
fi

git commit -m "$COMMIT_MSG"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git push -u origin "$BRANCH"

echo "推送完成：$BRANCH -> origin（仓库中的 config.py 不含真实 API_KEY）"
