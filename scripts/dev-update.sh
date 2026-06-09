#!/bin/bash
# ============================================================
# GitHubFast — 开发者用：本地重新生成 hosts 文件
# ============================================================
# 用途：在本地运行 DNS 解析，重新生成 hosts 文件
# 适用：项目维护者/贡献者，普通用户不需要此脚本
#       普通用户请用 apply.sh（curl 一键替换）
# 用法: bash scripts/dev-update.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== GitHub-fast 更新 ==="

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi

# 检查/安装依赖
if ! python3 -c "import aiohttp, aiodns, yaml" 2>/dev/null; then
    echo "安装依赖..."
    pip3 install -r requirements.txt
fi

# 运行更新
echo "开始解析..."
python3 -m src.main

echo ""
echo "更新完成！hosts 文件: $PROJECT_DIR/hosts"
echo "如需应用到系统，请运行: sudo bash scripts/apply.sh"
