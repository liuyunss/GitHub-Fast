1|# GitHubFast
     2|
     3|<p align="center">
     4|  <a href="https://github.com/liuyunss/GitHub-Fast/stargazers"><img src="https://img.shields.io/github/stars/liuyunss/GitHub-Fast?style=flat&logo=github&label=Stars" alt="Stars"></a>
     5|  <a href="https://github.com/liuyunss/GitHub-Fast/commits/main"><img src="https://img.shields.io/github/last-commit/liuyunss/GitHub-Fast?style=flat&label=Last%20Commit" alt="Last Commit"></a>
     6|  <img src="https://visitor-badge.laobi.icu/badge?page_id=liuyunss.GitHub-Fast&style=flat&label=Visitors" alt="Visitors">
     7|  <img src="https://img.shields.io/badge/自动更新-每8小时-blue?style=flat" alt="Update">
     8|  <a href="https://github.com/liuyunss/GitHub-Fast/blob/main/LICENSE"><img src="https://img.shields.io/github/license/liuyunss/GitHub-Fast?style=flat" alt="License"></a>
     9|</p>
    10|
    11|> 🔧 GitHub 访问加速 — 多源 DNS + DoH + 网页抓取，智能选择最佳 IP
    12|>
    13|> ⭐ 如果对你有帮助，请点个 Star 支持一下！
    14|
    15|## 为什么需要这个？
    16|
    17|DNS 污染导致 GitHub 域名解析到错误 IP，无法访问。本项目通过 **多个 DNS 来源** 并发查询真实 IP，用 **出现次数** 智能选择最佳 IP，自动生成 hosts 文件。
    18|
    19|## 特性
    20|
    21|- **多来源查询**：DoH + DNS 直查 + 网页抓取，覆盖国内外
    22|- **智能选 IP**：出现次数最多的 Top 3，每个域名保留 3 个
    23|- **自动更新**：GitHub Actions 每天 3 次自动运行
    24|- **配置灵活**：按分组管理域名，可单独开关
    25|- **错误容错**：任何来源失败不影响整体
    26|- **来源统计**：每次运行输出各源成功率，方便排查
    27|
    28|## 快速使用
    29|
    30|### 方式一：curl 一键替换（推荐）
    31|
    32|**一次性替换 hosts：**
    33|
    34|```bash
    35|curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash
    36|```
    37|
    38|**启用定时任务（默认每小时自动更新）：**
    39|
    40|```bash
    41|curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --install
    42|```
    43|
    44|**自定义更新间隔（如每 30 分钟）：**
    45|
    46|```bash
    47|curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --install --cron "*/30 * * * *"
    48|```
    49|
    50|**卸载定时任务：**
    51|
    52|```bash
    53|curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --uninstall
    54|```
    55|
    56|**删除 hosts 中的 GitHubFast 内容：**
    57|
    58|```bash
    59|curl -fsSL https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/scripts/apply.sh | sudo bash -s -- --clean
    60|```
    61|
    62|> 默认只替换，不开启定时。`--install` 启用后，crontab 会开机自启，无需额外配置。
    63|
    64|### 方式二：SwitchHosts 自动更新
    65|
    66|**从 URL 导入：**
    67|
    68|```
    69|https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/config/switchhosts.json
    70|```
    71|
    72|SwitchHosts 左下角 `+` → `从 URL 导入` → 粘贴上面地址。
    73|
    74|**从文件导入：**
    75|
    76|下载 [switchhosts.json](config/switchhosts.json)，SwitchHosts 左下角 `+` → `从文件导入` → 选择下载的文件。
    77|
    78|### 方式三：复制粘贴
    79|
    80|打开 [hosts](https://fastly.jsdelivr.net/gh/liuyunss/GitHub-Fast@main/hosts) 文件，复制内容，粘贴到系统 hosts 文件：
    81|
    82|| 系统 | hosts 文件路径 |
    83||------|---------------|
    84|| **Windows** | `C:\Windows\System32\drivers\etc\hosts` |
    85|| **macOS** | `/etc/hosts` |
    86|| **Linux** | `/etc/hosts` |
    87|
    88|粘贴后刷新 DNS 缓存：
    89|
    90|```bash
    91|# Windows
    92|ipconfig /flushdns
    93|
    94|# macOS
    95|sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
    96|
    97|# Linux
    98|sudo systemd-resolve --flush-caches
    99|```
   100|
   101|### 方式四：手动执行
   102|
   103|```bash
   104|git clone https://github.com/liuyunss/GitHub-Fast.git
   105|cd GitHub-Fast
   106|pip install -r requirements.txt
   107|python -m src.main
   108|```
   109|
   110|## 工作原理
   111|
   112|```
   113|多来源并发查询
   114|    ├── DoH（Cloudflare, Google, Quad9）
   115|    ├── DNS 直查（114DNS, AliDNS, DNSPod）
   116|    └── 网页抓取（ipaddress.com, ip-api.com）
   117|         │
   118|         ▼
   119|    合并去重 + 统计出现次数
   120|         │
   121|         ▼
   122|    选择出现次数最多的 Top 3 = 每域名 3 个 IP
   123|         │
   124|         ▼
   125|    写入 hosts 文件
   126|```
   127|
   128|## 配置说明
   129|
   130|编辑 `config.yaml` 可以：
   131|- 关闭/开启整个域名分组
   132|- 关闭/开启单个域名
   133|- 添加/删除 DNS 来源
   134|- 调整并发数量
   135|- 配置 ping 测试开关
   136|- 配置速率限制
   137|
   138|## 域名分组
   139|
   140|| 分组 | 说明 | 关闭影响 |
   141||------|------|---------|
   142|| 核心服务 | github.com 等 | GitHub 主站无法访问 |
   143|| 认证与安全 | 登录/OAuth 相关 | 登录异常 |
   144|| 头像与用户内容 | 头像/图片 | 图片加载失败 |
   145|| 代码与文件 | raw/云存储 | 代码/文件无法下载 |
   146|| CDN与加速 | Fastly CDN | 加速失效 |
   147|| Releases与下载 | S3 存储 | Release 下载失败 |
   148|| Packages与包管理 | 包仓库 | 包安装失败 |
   149|| GitHub Actions | CI/CD | Actions 异常 |
   150|| GitHub Copilot | AI 辅助 | Copilot 不可用 |
   151|| GitHub Pages | 静态站点 | Pages 无法访问 |
   152|
   153|## License
   154|
   155|MIT
   156|