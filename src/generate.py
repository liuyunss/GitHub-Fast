"""
hosts 文件生成模块
将解析和排序后的 IP 写入标准 hosts 文件格式
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

HOSTS_HEADER = """\
# ============================================================
# GitHubFast — GitHub 访问加速
# ============================================================

"""

HOSTS_FOOTER = """\
# ============================================================
# 🔄 更新时间: {update_time}
# 🔧 项目地址: https://github.com/{repo}
# ⭐ 如果对你有帮助，点个 Star 支持一下！
# ============================================================
"""


def generate_hosts(
    domain_ips: dict[str, list[str]],
    groups: list[dict],
    repo: str = "liuyunss/GitHub-Fast",
    output_path: str = "hosts",
) -> str:
    """生成 hosts 文件内容并写入文件"""
    tz = timezone(timedelta(hours=8))
    update_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S CST")

    lines = [HOSTS_HEADER]

    seen_domains: set[str] = set()
    # Track notes per domain — if a later occurrence has a note
    # and the earlier one didn't, merge it in (defensive fix).
    domain_notes: dict[str, str] = {}

    for group in groups:
        if not group.get("enabled", True):
            continue

        group_name = group["name"]
        group_lines: list[str] = [f"# --- {group_name} ---"]

        for item in group.get("domains", []):
            if not item.get("enabled", True):
                continue
            domain = item.get("domain")
            if not domain:
                continue
            note = item.get("note", "")
            ips = domain_ips.get(domain, [])

            if domain in seen_domains:
                # Merge note if new one is non-empty and old one is empty
                if note and not domain_notes.get(domain):
                    domain_notes[domain] = note
                continue
            seen_domains.add(domain)
            domain_notes[domain] = note

            if not ips:
                group_lines.append(f"# {domain}  # 未获取到 IP")
                continue

            for i, ip in enumerate(ips):
                if i == 0 and domain_notes.get(domain):
                    group_lines.append(f"{ip:<40} {domain}  # {domain_notes[domain]}")
                else:
                    group_lines.append(f"{ip:<40} {domain}")

        if len(group_lines) > 1:
            lines.extend(group_lines)

    lines.append("")  # 内容结束空行
    lines.append(HOSTS_FOOTER.format(update_time=update_time, repo=repo))

    content = "\n".join(lines)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")

    return content


def generate_readme(
    repo: str = "liuyunss/GitHub-Fast",
) -> str:
    """生成 README.md 内容"""
    return f"""# GitHubFast

> 🔧 GitHub 访问加速 — 多源 DNS + DoH + 网页抓取，智能选择最佳 IP
>
> ⭐ 如果对你有帮助，请点个 Star 支持一下！

## 为什么需要这个？

DNS 污染导致 GitHub 域名解析到错误 IP，无法访问。本项目通过 **多个 DNS 来源** 并发查询真实 IP，用 **出现次数** 智能选择最佳 IP，自动生成 hosts 文件。

## 特性

- **多来源查询**：DoH + DNS 直查 + 网页抓取，覆盖国内外
- **智能选 IP**：出现次数最多的 Top 3，每个域名保留 3 个
- **自动更新**：GitHub Actions 每 2 小时自动运行
- **配置灵活**：按分组管理域名，可单独开关
- **错误容错**：任何来源失败不影响整体
- **来源统计**：每次运行输出各源成功率，方便排查

## 快速使用

### 方式一：SwitchHosts 自动更新（推荐）

1. 下载 [SwitchHosts](https://github.com/oldj/SwitchHosts)
2. 添加远程规则：
   - 方案名：`GitHubFast`
   - 类型：`远程`
   - 地址1（推荐）：`https://raw.githubusercontent.com/{repo}/main/hosts`
   - 自动更新：`12 小时`

### 方式二：复制粘贴

打开 [hosts](https://raw.githubusercontent.com/{repo}/main/hosts) 文件，复制内容，粘贴到系统 hosts 文件：

| 系统 | hosts 文件路径 |
|------|---------------|
| **Windows** | `C:\\Windows\\System32\\drivers\\etc\\hosts` |
| **macOS** | `/etc/hosts` |
| **Linux** | `/etc/hosts` |

粘贴后刷新 DNS 缓存：

```bash
# Windows
ipconfig /flushdns

# macOS
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder

# Linux
sudo systemd-resolve --flush-caches
```

### 方式三：命令行一键更新

```bash
curl -fsSL https://raw.githubusercontent.com/{repo}/main/scripts/apply.sh | bash
```

### 方式四：手动执行

```bash
git clone https://github.com/{repo}.git
cd GitHub-Fast
pip install -r requirements.txt
python -m src.main
```

## 工作原理

```
多来源并发查询
    ├── DoH（Cloudflare, Google, Quad9）
    ├── DNS 直查（114DNS, AliDNS, DNSPod）
    └── 网页抓取（ipaddress.com, ip-api.com）
         │
         ▼
    合并去重 + 统计出现次数
         │
         ▼
    选择出现次数最多的 Top 3 = 每域名 3 个 IP
         │
         ▼
    写入 hosts 文件
```

## 配置说明

编辑 `config.yaml` 可以：
- 关闭/开启整个域名分组
- 关闭/开启单个域名
- 添加/删除 DNS 来源
- 调整并发数量
- 配置 ping 测试开关
- 配置速率限制

## 域名分组

| 分组 | 说明 | 关闭影响 |
|------|------|---------|
| 核心服务 | github.com 等 | GitHub 主站无法访问 |
| 认证与安全 | 登录/OAuth 相关 | 登录异常 |
| 头像与用户内容 | 头像/图片 | 图片加载失败 |
| 代码与文件 | raw/云存储 | 代码/文件无法下载 |
| CDN与加速 | Fastly CDN | 加速失效 |
| Releases与下载 | S3 存储 | Release 下载失败 |
| Packages与包管理 | 包仓库 | 包安装失败 |
| GitHub Actions | CI/CD | Actions 异常 |
| GitHub Copilot | AI 辅助 | Copilot 不可用 |
| GitHub Pages | 静态站点 | Pages 无法访问 |

## License

MIT
"""
