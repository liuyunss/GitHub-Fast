"""
IP 解析模块 — 从多种来源获取域名对应的 IP 地址
来源：DoH（DNS-over-HTTPS）、DNS 直查、网页抓取
"""

import asyncio
import base64
import os
import re
import struct
import subprocess
import time
import logging
from dataclasses import dataclass, field

import aiohttp
import aiodns
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ============================================================
# 环境变量
# ============================================================

_PROXY = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
          os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
if _PROXY:
    logger.info(f"检测到代理: {_PROXY}")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ============================================================
# DNS Wire Format（RFC 8484）
# ============================================================

def _build_dns_wire(domain: str, qtype: int = 1) -> bytes:
    """构建 DNS 查询 wire format（A 记录 = qtype 1）"""
    header = struct.pack('>HHHHHH', 0, 0x0100, 1, 0, 0, 0)
    qname = b''
    for part in domain.split('.'):
        qname += bytes([len(part)]) + part.encode()
    qname += b'\x00'
    return header + qname + struct.pack('>HH', qtype, 1)


def _parse_dns_wire(data: bytes) -> list[str]:
    """解析 DNS wire format 响应，提取 A 记录 IP"""
    ips = []
    if len(data) < 12:
        return ips
    offset = 12
    while offset < len(data) and data[offset] != 0:
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
            break
        offset += data[offset] + 1
    else:
        offset += 1
    offset += 4
    for _ in range(struct.unpack('>H', data[6:8])[0]):
        if offset >= len(data):
            break
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        else:
            while offset < len(data) and data[offset] != 0:
                offset += data[offset] + 1
            offset += 1
        rtype = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 8
        rdlen = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        if rtype == 1 and rdlen == 4:
            ips.append('.'.join(str(b) for b in data[offset:offset+4]))
        offset += rdlen
    return ips


def _make_wire_b64(domain: str) -> str:
    """构建 base64 编码的 DNS wire query"""
    return base64.urlsafe_b64encode(_build_dns_wire(domain)).decode().rstrip("=")


# ============================================================
# 速率限制器
# ============================================================

class RateLimiter:
    """滑动窗口速率限制器"""

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            self.timestamps = [t for t in self.timestamps if now - t < 60]
            if len(self.timestamps) >= self.max_per_minute:
                wait_time = 60 - (now - self.timestamps[0]) + 0.1
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    self.timestamps = [t for t in self.timestamps if now - t < 60]
            self.timestamps.append(time.monotonic())


_rate_limiters: dict[str, RateLimiter] = {}


def _get_rate_limiter(source: dict) -> RateLimiter | None:
    name = source["name"]
    limit = source.get("rate_limit")
    if not limit:
        return None
    if name not in _rate_limiters:
        _rate_limiters[name] = RateLimiter(limit)
    return _rate_limiters[name]


# ============================================================
# 数据结构
# ============================================================

@dataclass
class IPResult:
    source: str
    source_type: str   # doh / dns / web
    ip: str
    latency_ms: float = -1


@dataclass
class DomainIPs:
    domain: str
    results: list[IPResult] = field(default_factory=list)


# ============================================================
# 工具函数
# ============================================================

def _is_valid_ip(ip: str) -> bool:
    parts = ip.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def _make_result(name: str, source_type: str, ip: str, latency: float) -> IPResult | None:
    """创建 IPResult，无效 IP 返回 None"""
    if _is_valid_ip(ip):
        return IPResult(source=name, source_type=source_type, ip=ip, latency_ms=latency)
    return None


def _make_results(name: str, source_type: str, ips: list[str], latency: float) -> list[IPResult]:
    """批量创建 IPResult，过滤无效 IP"""
    return [r for ip in ips if (r := _make_result(name, source_type, ip, latency)) is not None]


# ============================================================
# DoH 策略
# ============================================================

async def _doh_json(session: aiohttp.ClientSession, url: str, domain: str) -> list[str]:
    """标准 JSON 格式 DoH 查询"""
    async with session.get(
        url,
        params={"name": domain, "type": "A"},
        headers={"accept": "application/dns-json"},
        timeout=aiohttp.ClientTimeout(total=10),
        proxy=_PROXY,
    ) as resp:
        if resp.status != 200:
            return []
        try:
            data = await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return []
        return [ans["data"] for ans in data.get("Answer", [])
                if ans.get("type") == 1]


async def _doh_wire(session: aiohttp.ClientSession, url: str, domain: str) -> list[str]:
    """Wire format DoH 查询"""
    async with session.get(
        url,
        params={"dns": _make_wire_b64(domain)},
        headers={"accept": "application/dns-message"},
        timeout=aiohttp.ClientTimeout(total=10),
        proxy=_PROXY,
    ) as resp:
        if resp.status != 200:
            return []
        return _parse_dns_wire(await resp.read())


async def _doh_wire_via_curl(session: aiohttp.ClientSession, url: str, domain: str) -> list[str]:
    """通过 curl 子进程执行 wire format DoH（解决 aiohttp 不支持 HTTP/2）"""
    query_url = f"{url}?dns={_make_wire_b64(domain)}"

    def _run():
        cmd = ["curl", "-s", "--http2", "--max-time", "10",
               "-H", "accept: application/dns-message", query_url]
        if _PROXY:
            cmd.extend(["--proxy", _PROXY])
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        return result.stdout if result.returncode == 0 else b""

    wire = await asyncio.to_thread(_run)
    return _parse_dns_wire(wire) if wire else []


_DOH_STRATEGIES = {
    "json": _doh_json,
    "wire": _doh_wire,
    "wire_curl": _doh_wire_via_curl,
}


# ============================================================
# 通用查询封装
# ============================================================

async def _timed_resolve(
    name: str,
    source_type: str,
    semaphore: asyncio.Semaphore,
    query_fn,
    log_prefix: str,
    domain: str,
) -> list[IPResult]:
    """统一的带计时和异常处理的查询封装"""
    async with semaphore:
        start = time.monotonic()
        try:
            ips = await query_fn()
            latency = (time.monotonic() - start) * 1000
            return _make_results(name, source_type, ips, latency)
        except asyncio.TimeoutError:
            logger.warning(f"[{log_prefix}] {name} 查询 {domain} 超时")
        except Exception as e:
            logger.warning(f"[{log_prefix}] {name} 查询 {domain} 异常: {e}")
    return []


# ============================================================
# 各类型查询函数
# ============================================================

async def _query_doh(session, domain, source):
    """DoH 查询 IP"""
    strategy = source.get("strategy", "json")
    fn = _DOH_STRATEGIES.get(strategy, _doh_json)
    return await fn(session, source["url"], domain)


async def _query_dns(domain, source):
    """DNS 直查 IP"""
    resolver = aiodns.DNSResolver()
    resolver.nameservers = [source["server"]]
    response = await resolver.query(domain, "A")
    return [item.host for item in response]


async def _query_web(session, domain, source):
    """网页抓取 IP"""
    name = source["name"]
    if name == "ipaddress.com":
        return await _fetch_ipaddress(session, domain)
    elif name == "ip-api.com":
        return await _fetch_ip_api(session, domain)
    return []


# ============================================================
# 网页抓取实现
# ============================================================

async def _fetch_ipaddress(session: aiohttp.ClientSession, domain: str) -> list[str]:
    """从 ipaddress.com 查询 IP（Cloudflare WAF 可能封锁，重试 3 次）"""
    url = f"https://sites.ipaddress.com/{domain}"
    for attempt in range(3):
        try:
            async with session.get(
                url, headers={"User-Agent": _UA},
                timeout=aiohttp.ClientTimeout(total=10),
                proxy=_PROXY,
            ) as resp:
                if resp.status == 403:
                    if attempt < 2:
                        await asyncio.sleep(1)
                        continue
                    logger.warning(f"[Web] ipaddress.com 查询 {domain} 被 Cloudflare 封锁")
                    return []
                if resp.status != 200:
                    logger.warning(f"[Web] ipaddress.com 查询 {domain} 失败: HTTP {resp.status}")
                    return []
                html = await resp.text()
                # 用 BeautifulSoup 解析 HTML，只提取结果表格中的 IP
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                ip_pat = re.compile(r"^\s*((?:[0-9]{1,3}\.){3}[0-9]{1,3})\s*$")
                ips = []
                for td in soup.find_all("td"):
                    m = ip_pat.match(td.get_text())
                    if m:
                        ips.append(m.group(1))
                return ips
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt < 2:
                await asyncio.sleep(1)
                continue
            raise
    return []


async def _fetch_ip_api(session: aiohttp.ClientSession, domain: str) -> list[str]:
    """从 ip-api.com 查询 IP（免费限 45 次/分钟，429 自动重试）"""
    # 注意：ip-api.com 免费版不支持 HTTPS，域名查询以明文传输
    url = f"http://ip-api.com/json/{domain}?lang=zh-CN"
    for attempt in range(2):
        async with session.get(
            url, headers={"User-Agent": _UA},
            timeout=aiohttp.ClientTimeout(total=10),
            proxy=_PROXY,
        ) as resp:
            if resp.status == 429:
                if attempt == 0:
                    logger.warning(f"[Web] ip-api.com 查询 {domain} 触发限流，等待重试")
                    await asyncio.sleep(3)
                    continue
                return []
            if resp.status != 200:
                logger.warning(f"[Web] ip-api.com 查询 {domain} 失败: HTTP {resp.status}")
                return []
            try:
                data = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError):
                return []
            query = data.get("query", "")
            if data.get("status") == "success" and _is_valid_ip(query):
                return [query]
            return []
    return []


# ============================================================
# 域名解析入口
# ============================================================

async def resolve_domain(
    domain: str,
    sources: dict,
    semaphores: dict[str, asyncio.Semaphore],
    session: aiohttp.ClientSession,
) -> DomainIPs:
    """并发查询一个域名的所有来源"""
    result = DomainIPs(domain=domain)
    tasks = []

    for src in sources.get("doh", []):
        if src.get("enabled", True):
            tasks.append(_timed_resolve(
                src["name"], "doh", semaphores["doh"],
                lambda s=src: _query_doh(session, domain, s),
                "DoH", domain,
            ))
    for src in sources.get("dns", []):
        if src.get("enabled", True):
            tasks.append(_timed_resolve(
                src["name"], "dns", semaphores["dns"],
                lambda s=src: _query_dns(domain, s),
                "DNS", domain,
            ))
    for src in sources.get("web", []):
        if src.get("enabled", True):
            async def _web_task(s=src):
                limiter = _get_rate_limiter(s)
                if limiter:
                    await limiter.acquire()
                return await _query_web(session, domain, s)
            tasks.append(_timed_resolve(
                src["name"], "web", semaphores["web"],
                _web_task, "Web", domain,
            ))

    all_results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in all_results:
        if isinstance(r, Exception):
            logger.warning(f"[{domain}] 查询异常: {r}")
        elif isinstance(r, list):
            result.results.extend(r)

    logger.info(f"[{domain}] 获取到 {len(result.results)} 个 IP 结果")
    return result


# ============================================================
# 批量解析
# ============================================================

async def resolve_all_domains(
    domains: list[str],
    sources: dict,
    concurrency: dict,
) -> dict[str, DomainIPs]:
    """批量解析所有域名"""
    # Semaphore 在全局创建，所有域名共享
    semaphores = {
        "doh": asyncio.Semaphore(concurrency.get("doh", 15)),
        "dns": asyncio.Semaphore(concurrency.get("dns", 10)),
        "web": asyncio.Semaphore(concurrency.get("web", 3)),
    }

    # 清空速率限制器
    _rate_limiters.clear()

    results = {}
    async with aiohttp.ClientSession() as session:
        # 所有域名一次性 gather，Semaphore 控制全局并发
        tasks = [
            resolve_domain(d, sources, semaphores, session)
            for d in domains
        ]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        for d, r in zip(domains, all_results):
            if isinstance(r, Exception):
                logger.error(f"[{d}] 解析异常: {r}")
            else:
                results[d] = r

    return results
