#!/bin/bash
# ============================================================
# GitHubFast — 一键应用到系统 hosts
# ============================================================
# 用法:
#   curl -fsSL <url> | sudo bash                       # 一次性替换
#   curl -fsSL <url> | sudo bash -s -- --install        # 启用定时任务（默认每小时）
#   curl -fsSL <url> | sudo bash -s -- --install --cron "*/30 * * * *"  # 自定义间隔
#   curl -fsSL <url> | sudo bash -s -- --uninstall      # 卸载定时任务
# ============================================================

set -e

# === 配置 ===
CDN_HOSTS_URL="https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/hosts"
CDN_SCRIPT_URL="https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh"
RAW_SCRIPT_URL="https://raw.githubusercontent.com/liuyunss/GitHub-Fast/main/scripts/apply.sh"
INSTALL_DIR="/usr/local/bin"
INSTALL_NAME="githubfast"
CRON_TAG="# GitHubFast auto-update"
DEFAULT_CRON="0 * * * *"
LOG_FILE="/var/log/githubfast.log"

# === 参数解析 ===
ACTION="apply"
CRON_EXPR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --install)    ACTION="install"; shift ;;
        --uninstall)  ACTION="uninstall"; shift ;;
        --cron)       CRON_EXPR="$2"; shift 2 ;;
        --help|-h)
            sed -n '2,/^# ===/{ /^#/s/^# \?//p }' "$0"
            exit 0
            ;;
        *) shift ;;
    esac
done

# === 检查 ===
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用 sudo 运行此脚本"
    exit 1
fi

if [ -f /etc/hosts ]; then
    SYSTEM_HOSTS="/etc/hosts"
elif [ -f /c/Windows/System32/drivers/etc/hosts ]; then
    SYSTEM_HOSTS="/c/Windows/System32/drivers/etc/hosts"
else
    echo "❌ 未找到系统 hosts 文件"
    exit 1
fi

# === 工具函数 ===
http_get() {
    local url="$1" output="$2"
    if command -v curl &>/dev/null; then
        curl -fsSL "$url" -o "$output" 2>/dev/null
    elif command -v wget &>/dev/null; then
        wget -q "$url" -O "$output" 2>/dev/null
    else
        echo "❌ 未找到 curl 或 wget"
        exit 1
    fi
}

flush_dns() {
    if command -v dscacheutil &>/dev/null; then
        dscacheutil -flushcache 2>/dev/null
        killall -HUP mDNSResponder 2>/dev/null
    elif command -v systemd-resolve &>/dev/null; then
        systemd-resolve --flush-caches 2>/dev/null
    fi
}

# === 核心操作 ===
do_apply() {
    local tmp="/tmp/ghfast_$$.hosts"

    echo "⏳ 下载最新 hosts..."
    http_get "$CDN_HOSTS_URL" "$tmp"

    if [ ! -s "$tmp" ]; then
        echo "❌ 下载失败，hosts 未更新"
        rm -f "$tmp"
        exit 1
    fi

    # 备份
    local backup="$SYSTEM_HOSTS.bak.$(date +%Y%m%d%H%M%S)"
    cp "$SYSTEM_HOSTS" "$backup"
    echo "📦 已备份: $backup"

    # 删除旧的 GitHubFast 部分（幂等：没有就跳过）
    sed -i '/# GitHubFast Start/,/# GitHubFast End/d' "$SYSTEM_HOSTS"

    # 追加新内容
    echo "" >> "$SYSTEM_HOSTS"
    echo "# GitHubFast Start" >> "$SYSTEM_HOSTS"
    cat "$tmp" >> "$SYSTEM_HOSTS"
    echo "# GitHubFast End" >> "$SYSTEM_HOSTS"

    rm -f "$tmp"
    flush_dns
    echo "✅ hosts 更新成功！"
}

do_install() {
    echo "=== 安装 GitHubFast 定时任务 ==="

    local target="$INSTALL_DIR/$INSTALL_NAME"

    # 下载脚本到持久化位置
    echo "📥 下载脚本到 $target ..."
    http_get "$CDN_SCRIPT_URL" "$target" 2>/dev/null || \
    http_get "$RAW_SCRIPT_URL" "$target" 2>/dev/null || {
        echo "❌ 脚本下载失败"
        exit 1
    }
    chmod +x "$target"
    echo "📦 脚本已安装: $target"

    # 清除旧的 crontab 条目
    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - 2>/dev/null || true

    # 添加新的 crontab 条目
    local cron="$CRON_EXPR"
    [ -z "$cron" ] && cron="$DEFAULT_CRON"

    (crontab -l 2>/dev/null; echo "$cron sudo $target >> $LOG_FILE 2>&1 $CRON_TAG") | crontab -
    echo "⏰ 定时任务已添加: $cron"
    echo "📝 日志: $LOG_FILE"

    # 立即执行一次
    echo ""
    do_apply
    echo ""
    echo "💡 管理命令:"
    echo "   查看日志:   tail -f $LOG_FILE"
    echo "   卸载:       curl -fsSL <url> | sudo bash -s -- --uninstall"
}

do_uninstall() {
    echo "=== 卸载 GitHubFast 定时任务 ==="

    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - 2>/dev/null || true
    rm -f "$INSTALL_DIR/$INSTALL_NAME"

    echo "✅ 定时任务已卸载"
    echo "💡 原有的 hosts 内容仍保留在系统中，不会被删除"
}

# === 执行 ===
case "$ACTION" in
    apply)     do_apply ;;
    install)   do_install ;;
    uninstall) do_uninstall ;;
esac
