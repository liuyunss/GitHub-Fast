#!/bin/bash
# GitHub-fast 一键应用到系统 hosts
# 用法: sudo bash scripts/apply.sh
# 会先下载最新 hosts，然后合并到系统 hosts 文件

set -e

HOSTS_URL="https://raw.githubusercontent.com/liuyunss/GitHub-fast/main/hosts"
TMP_FILE="/tmp/ghfast_hosts_download"

echo "=== GitHub-fast 应用到系统 ==="

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    echo "错误: 请使用 sudo 运行此脚本"
    exit 1
fi

# 检测系统
if [ -f /etc/hosts ]; then
    SYSTEM_HOSTS="/etc/hosts"
elif [ -f /c/Windows/System32/drivers/etc/hosts ]; then
    SYSTEM_HOSTS="/c/Windows/System32/drivers/etc/hosts"
else
    echo "错误: 未找到系统 hosts 文件"
    exit 1
fi

echo "系统 hosts 文件: $SYSTEM_HOSTS"

# 下载最新 hosts
echo "下载最新 hosts..."
if command -v curl &>/dev/null; then
    curl -fsSL "$HOSTS_URL" -o "$TMP_FILE"
elif command -v wget &>/dev/null; then
    wget -q "$HOSTS_URL" -O "$TMP_FILE"
else
    echo "错误: 未找到 curl 或 wget"
    exit 1
fi

# 备份原 hosts
BACKUP="$SYSTEM_HOSTS.bak.$(date +%Y%m%d%H%M%S)"
cp "$SYSTEM_HOSTS" "$BACKUP"
echo "已备份原 hosts 到: $BACKUP"

# 删除旧的 GitHub-fast 部分（如果存在）
sed -i '/# GitHub-fast Start/,/# GitHub-fast End/d' "$SYSTEM_HOSTS"

# 追加新的 hosts 内容
echo "" >> "$SYSTEM_HOSTS"
echo "# GitHub-fast Start" >> "$SYSTEM_HOSTS"
# 提取 GitHub-fast 标记之间的内容
sed -n '/# --- /,/# Update time/p' "$TMP_FILE" >> "$SYSTEM_HOSTS"
echo "# GitHub-fast End" >> "$SYSTEM_HOSTS"

rm -f "$TMP_FILE"

echo ""
echo "应用成功！"
echo ""

# 刷新 DNS 缓存
if command -v dscacheutil &>/dev/null; then
    # macOS
    dscacheutil -flushcache
    killall -HUP mDNSResponder
    echo "已刷新 DNS 缓存 (macOS)"
elif command -v systemd-resolve &>/dev/null; then
    # Linux (systemd)
    systemd-resolve --flush-caches
    echo "已刷新 DNS 缓存 (systemd)"
elif command -v ipconfig &>/dev/null; then
    # Windows
    ipconfig /flushdns
    echo "已刷新 DNS 缓存 (Windows)"
fi

echo "完成！请重启浏览器使更改生效。"
