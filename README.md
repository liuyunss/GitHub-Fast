# GitHubFast

> 🔧 GitHub 访问加速 — 多源 DNS + DoH + 网页抓取，智能选择最佳 IP
>
> ⭐ 如果对你有帮助，请点个 Star 支持一下！

## 为什么需要这个？

DNS 污染导致 GitHub 域名解析到错误 IP，无法访问。本项目通过 **多个 DNS 来源** 并发查询真实 IP，用 **出现次数** 智能选择最佳 IP，自动生成 hosts 文件。

## 特性

- **多来源查询**：DoH + DNS 直查 + 网页抓取，覆盖国内外
- **智能选 IP**：出现次数最多的 Top 3，每个域名保留 3 个
- **自动更新**：GitHub Actions 每天 3 次自动运行
- **配置灵活**：按分组管理域名，可单独开关
- **错误容错**：任何来源失败不影响整体
- **来源统计**：每次运行输出各源成功率，方便排查

## 快速使用

### 方式一：curl 一键替换（推荐）

```bash
# 一次性替换 hosts
curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash

# 启用定时任务（默认每小时自动更新）
curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --install

# 自定义更新间隔（如每 30 分钟）
curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --install --cron "*/30 * * * *"

# 卸载定时任务
curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --uninstall
```

> 默认只替换，不开启定时。`--install` 启用后，crontab 会开机自启，无需额外配置。

### 方式二：SwitchHosts 自动更新

1. 下载 [SwitchHosts](https://github.com/oldj/SwitchHosts)
2. **方式 A：从 URL 导入（推荐）**
   - 点击左下角 `+` → `从 URL 导入`
   - 填入加速源地址：`https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/hosts`
   - 自动更新：`12 小时`
3. **方式 B：从文件导入**
   - 下载 [switchhosts.json](config/switchhosts.json)
   - 点击左下角 `+` → `从文件导入` → 选择下载的 json 文件
4. **方式 C：手动添加远程规则**
   - 方案名：`GitHubFast`
   - 类型：`远程`
   - 加速源：`https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/hosts`
   - GitHub 直连：`https://raw.githubusercontent.com/liuyunss/GitHub-Fast/main/hosts`
   - 自动更新：`12 小时`

### 方式三：复制粘贴

打开 [hosts](https://raw.githubusercontent.com/liuyunss/GitHub-Fast/main/hosts) 文件，复制内容，粘贴到系统 hosts 文件：

| 系统 | hosts 文件路径 |
|------|---------------|
| **Windows** | `C:\Windows\System32\drivers\etc\hosts` |
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

### 方式四：手动执行

```bash
git clone https://github.com/liuyunss/GitHub-Fast.git
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
