     1|     1|#!/bin/bash
     2|     2|# ============================================================
     3|     3|# GitHubFast — 一键应用到系统 hosts
     4|     4|# ============================================================
     5|     5|# 用法:
     6|     6|#   curl -fsSL <url> | sudo bash                       # 一次性替换
     7|     7|#   curl -fsSL <url> | sudo bash -s -- --install        # 启用定时任务（默认每小时）
     8|     8|#   curl -fsSL <url> | sudo bash -s -- --install --cron "*/30 * * * *"  # 自定义间隔
     9|     9|#   curl -fsSL <url> | sudo bash -s -- --uninstall      # 卸载定时任务
    10|    10|#   curl -fsSL <url> | sudo bash -s -- --clean           # 删除 hosts 中的 GitHubFast 内容
    11|    11|# ============================================================
    12|    12|
    13|    13|set -e
    14|    14|
    15|    15|# === 配置 ===
    16|    16|CDN_HOSTS_URL="https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/hosts"
    17|    17|RAW_SCRIPT_URL="https://raw.githubusercontent.com/liuyunss/GitHub-Fast/main/scripts/apply.sh"
    18|    19|INSTALL_DIR="/usr/local/bin"
    19|    20|INSTALL_NAME="githubfast"
    20|    21|CRON_TAG="# GitHubFast auto-update"
    21|    22|DEFAULT_CRON="0 * * * *"
    22|    23|LOG_FILE="/var/log/githubfast.log"
    23|    24|
    24|    25|# === 参数解析 ===
    25|    26|ACTION="apply"  CRON_EXPR=""
    26|    27|
    27|    28|while [[ $# -gt 0 ]]; do
    28|    29|    case $1 in
    29|    30|        --install)    ACTION="install";  shift ;;
    30|    31|        --uninstall)  ACTION="uninstall"; shift ;;
    31|    32|        --clean)      ACTION="clean";    shift ;;
    32|    33|        --cron)       CRON_EXPR="$2";    shift 2 ;;
    33|    34|        --help|-h)
    34|    35|            echo "用法: curl -fsSL <url> | sudo bash -s -- [选项]"
    35|    36|            echo ""
    36|    37|            echo "选项:"
    37|    38|            echo "  (无参数)          一次性替换 hosts"
    38|    39|            echo "  --install         启用定时任务（默认每小时）"
    39|    40|            echo "  --install --cron  自定义 cron 表达式"
    40|    41|            echo "  --uninstall       卸载定时任务"
    41|    42|            echo "  --clean           删除 hosts 中的 GitHubFast 内容"
    42|    43|            exit 0
    43|    44|            ;;
    44|    45|        *) shift ;;
    45|    46|    esac
    46|    47|done
    47|    48|
    48|    49|# === 检查 ===
    49|    50|if [ "$EUID" -ne 0 ]; then
    50|    51|    echo "❌ 请使用 sudo 运行此脚本"
    51|    52|    exit 1
    52|    53|fi
    53|    54|
    54|    55|if [ -f /etc/hosts ]; then
    55|    56|    SYSTEM_HOSTS="/etc/hosts"
    56|    57|elif [ -f /c/Windows/System32/drivers/etc/hosts ]; then
    57|    58|    SYSTEM_HOSTS="/c/Windows/System32/drivers/etc/hosts"
    58|    59|else
    59|    60|    echo "❌ 未找到系统 hosts 文件"
    60|    61|    exit 1
    61|    62|fi
    62|    63|
    63|    64|# === 工具函数 ===
    64|    65|http_get() {
    65|    66|    local url="$1" output="$2"
    66|    67|    if command -v curl &>/dev/null; then
    67|    68|        curl -fsSL "$url" -o "$output" 2>/dev/null
    68|    69|    elif command -v wget &>/dev/null; then
    69|    70|        wget -q "$url" -O "$output" 2>/dev/null
    70|    71|    else
    71|    72|        echo "❌ 未找到 curl 或 wget"
    72|    73|        exit 1
    73|    74|    fi
    74|    75|}
    75|    76|
    76|    77|# 删除文件中 Start/End 标记之间的内容（perl 跨平台，不依赖 sed）
    77|    78|remove_section() {
    78|    79|    local file="$1" start="$2" end="$3"
    79|    80|    perl -i -ne "print unless /$start/../$end/" "$file"
    80|    81|}
    81|    82|
    82|    83|flush_dns() {
    83|    84|    if command -v dscacheutil &>/dev/null; then
    84|    85|        dscacheutil -flushcache 2>/dev/null
    85|    86|        killall -HUP mDNSResponder 2>/dev/null
    86|    87|    elif command -v systemd-resolve &>/dev/null; then
    87|    88|        systemd-resolve --flush-caches 2>/dev/null
    88|    89|    fi
    89|    90|}
    90|    91|
    91|    92|# === 核心操作 ===
    92|    93|do_apply() {
    93|    94|    local tmp="/tmp/ghfast_$$.hosts"
    94|    95|
    95|    96|    echo "⏳ 下载最新 hosts..."
    96|    97|    http_get "$CDN_HOSTS_URL" "$tmp"
    97|    98|
    98|    99|    if [ ! -s "$tmp" ]; then
    99|   100|        echo "❌ 下载失败，hosts 未更新"
   100|   101|        rm -f "$tmp"
   101|   102|        exit 1
   102|   103|    fi
   103|   104|
   104|   105|    # 备份
   105|   106|    local backup="$SYSTEM_HOSTS.bak.$(date +%Y%m%d%H%M%S)"
   106|   107|    cp "$SYSTEM_HOSTS" "$backup"
   107|   108|    echo "📦 已备份: $backup"
   108|   109|
   109|   110|    # 删除旧的 GitHubFast 部分（幂等：没有就跳过）
   110|   111|    remove_section "$SYSTEM_HOSTS" "GitHubFast Start" "GitHubFast End"
   111|   112|
   112|   113|    # 追加新内容
   113|   114|    echo "" >> "$SYSTEM_HOSTS"
   114|   115|    echo "# GitHubFast Start" >> "$SYSTEM_HOSTS"
   115|   116|    cat "$tmp" >> "$SYSTEM_HOSTS"
   116|   117|    echo "# GitHubFast End" >> "$SYSTEM_HOSTS"
   117|   118|
   118|   119|    rm -f "$tmp"
   119|   120|    flush_dns
   120|   121|    echo "✅ hosts 更新成功！"
   121|   122|}
   122|   123|
   123|   124|do_install() {
   124|   125|    echo "=== 安装 GitHubFast 定时任务 ==="
   125|   126|
   126|   127|    local target="$INSTALL_DIR/$INSTALL_NAME"
   127|   128|
   128|   129|    # 下载脚本到持久化位置
   129|   130|    echo "📥 下载脚本到 $target ..."
   130|   131|    http_get "$RAW_SCRIPT_URL" "$target" 2>/dev/null || \
   131|   132|    http_get "$RAW_SCRIPT_URL" "$target" 2>/dev/null || {
   132|   133|        echo "❌ 脚本下载失败"
   133|   134|        exit 1
   134|   135|    }
   135|   136|    chmod +x "$target"
   136|   137|    echo "📦 脚本已安装: $target"
   137|   138|
   138|   139|    # 清除旧的 crontab 条目
   139|   140|    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - 2>/dev/null || true
   140|   141|
   141|   142|    # 添加新的 crontab 条目
   142|   143|    local cron="$CRON_EXPR"
   143|   144|    [ -z "$cron" ] && cron="$DEFAULT_CRON"
   144|   145|
   145|   146|    (crontab -l 2>/dev/null; echo "$cron sudo $target >> $LOG_FILE 2>&1 $CRON_TAG") | crontab -
   146|   147|    echo "⏰ 定时任务已添加: $cron"
   147|   148|    echo "📝 日志: $LOG_FILE"
   148|   149|
   149|   150|    # 立即执行一次
   150|   151|    echo ""
   151|   152|    do_apply
   152|   153|    echo ""
   153|   154|    echo "💡 管理命令:"
   154|   155|    echo "   查看日志:   tail -f $LOG_FILE"
   155|   156|    echo "   卸载:       curl -fsSL <url> | sudo bash -s -- --uninstall"
   156|   157|}
   157|   158|
   158|   159|do_uninstall() {
   159|   160|    echo "=== 卸载 GitHubFast 定时任务 ==="
   160|   161|
   161|   162|    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - 2>/dev/null || true
   162|   163|    rm -f "$INSTALL_DIR/$INSTALL_NAME"
   163|   164|
   164|   165|    echo "✅ 定时任务已卸载"
   165|   166|    echo "💡 原有的 hosts 内容仍保留在系统中，不会被删除"
   166|   167|}
   167|   168|
   168|   169|do_clean() {
   169|   170|    echo "=== 清除系统 hosts 中的 GitHubFast 内容 ==="
   170|   171|    if grep -q "# GitHubFast Start" "$SYSTEM_HOSTS"; then
   171|   172|        cp "$SYSTEM_HOSTS" "$SYSTEM_HOSTS.bak.$(date +%Y%m%d%H%M%S)"
   172|   173|        remove_section "$SYSTEM_HOSTS" "GitHubFast Start" "GitHubFast End"
   173|   174|        # 删除多余空行
   174|   175|        awk 'NF{p=1}p' "$SYSTEM_HOSTS" > "$SYSTEM_HOSTS.tmp" && mv "$SYSTEM_HOSTS.tmp" "$SYSTEM_HOSTS"
   175|   176|        flush_dns
   176|   177|        echo "✅ GitHubFast 内容已清除，DNS 缓存已刷新"
   177|   178|    else
   178|   179|        echo "ℹ️  系统 hosts 中没有 GitHubFast 内容，无需清理"
   179|   180|    fi
   180|   181|}
   181|   182|
   182|   183|# === 执行 ===
   183|   184|case "$ACTION" in
   184|   185|    apply)     do_apply ;;
   185|   186|    install)   do_install ;;
   186|   187|    uninstall) do_uninstall ;;
   187|   188|    clean)     do_clean ;;
   188|   189|esac
   189|   190|