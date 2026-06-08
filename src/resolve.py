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

logger = logging.getLogger(__name__)

# 从环境变量读取代理
_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or \
         os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
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
    # 跳过 QNAME
    while offset < len(data) and data[offset] != 0:
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
            break
        offset += data[offset] + 1
    else:
        offset += 1
    offset += 4  # QTYPE + QCLASS
    # 解析 Answer
    for _ in range(struct.unpack('>H', data[6:8])[0]):
        if offset >= len(data):
            break
        # 跳过 NAME
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        else:
            while offset < len(data) and data[offset] != 0:
                offset += data[offset] + 1
            offset += 1
        rtype = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 8  # TYPE + CLASS + TTL
        rdlen = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        if rtype == 1 and rdlen == 4:  # A record
            ips.append('.'.join(str(b) for b in data[offset:offset+4]))
        offset += rdlen
    return ips


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
                    logger.debug(f"[RateLimiter] 等待 {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    self.timestamps = [t for t in self.timestamps if now - t < 60]
            self.timestamps.append(time.monotonic())


_rate_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(source: dict) -> RateLimiter | None:
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
    source: str        # 来源名称
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
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def _make_result(name: str, source_type: str, ip: str, latency: float) -> IPResult | None:
    """创建 IPResult，无效 IP 返回 None"""
    return IPResult(source=name, source_type=source_type, ip=ip, latency_ms=latency) \
        if _is_valid_ip(ip) else None


# ============================================================
# DoH 解析
# ============================================================

async def _doh_json(session: aiohttp.ClientSession, url: str, domain: str) -> list[str]:
    """标准 JSON 格式 DoH 查询（Cloudflare, Google 等）"""
    async with session.get(
        url,
        params={"name": domain, "type": "A"},
        headers={"accept": "application/dns-json"},
        timeout=aiohttp.ClientTimeout(total=10),
        proxy=_PROXY,
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json(content_type=None)
        return [ans["data"] for ans in data.get("Answer", [])
                if ans.get("type") == 1]


async def _doh_wire(session: aiohttp.ClientSession, url: str, domain: str) -> list[str]:
    """Wire format DoH 查询（Quad9 等，需要 HTTP/2）"""
    dns_b64 = base64.urlsafe_b64encode(
        _build_dns_wire(domain)
    ).decode().rstrip("=")
    async with session.get(
        url,
        params={"dns": dns_b64},
        headers={"accept": "application/dns-message"},
        timeout=aiohttp.ClientTimeout(total=10),
        proxy=_PROXY,
    ) as resp:
        if resp.status != 200:
            return []
        return _parse_dns_wire(await resp.read())


async def _doh_wire_via_curl(url: str, domain: str) -> list[str]:
    """通过 curl 子进程执行 wire format DoH（解决 aiohttp 不支持 HTTP/2 的问题）"""
    dns_b64 = base64.urlsafe_b64encode(
        _build_dns_wire(domain)
    ).decode().rstrip("=")
    query_url = f"{url}?dns={dns_b64}"

    def _run():
        cmd = ["curl", "-s", "--http2", "--max-time", "10",
               "-H", "accept: application/dns-message", query_url]
        if _PROXY:
            cmd.extend(["--proxy", _PROXY])
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        return result.stdout if result.returncode == 0 else b""

    wire = await asyncio.to_thread(_run)
    return _parse_dns_wire(wire) if wire else []


# DoH 查询策略分派
_DOH_STRATEGIES = {
    "json": _doh_json,
    "wire": _doh_wire,
    "wire_curl": _doh_wire_via_curl,
}


async def resolve_doh(
    session: aiohttp.ClientSession,
    domain: str,
    source: dict,
    semaphore: asyncio.Semaphore,
) -> list[IPResult]:
    """通过 DNS-over-HTTPS 查询 IP"""
    name = source["name"]
    strategy = source.get("strategy", "json")

    async with semaphore:
        start = time.monotonic()
        try:
            if strategy == "wire_curl":
                ips = await _doh_wire_via_curl(source["url"], domain)
            else:
                fn = _DOH_STRATEGIES[strategy]
                ips = await fn(session, source["url"], domain)

            latency = (time.monotonic() - start) * 1000
            return [r for ip in ips
                    if (r := _make_result(name, "doh", ip, latency)) is not None]
        except asyncio.TimeoutError:
            logger.warning(f"[DoH] {name} 查询 {domain} 超时")
        except Exception as e:
            logger.warning(f"[DoH] {name} 查询 {domain} 异常: {e}")

    return []


# ============================================================
# DNS 直查
# ============================================================

async def resolve_dns(
    domain: str,
    source: dict,
    semaphore: asyncio.Semaphore,
) -> list[IPResult]:
    """通过 UDP DNS 直查 IP"""
    name = source["name"]
    server = source["server"]

    async with semaphore:
        start = time.monotonic()
        try:
            resolver = aiodns.DNSResolver()
            resolver.nameservers = [server]
            response = await resolver.query(domain, "A")
            latency = (time.monotonic() - start) * 1000
            return [r for item in response
                    if (r := _make_result(name, "dns", item.host, latency)) is not None]
        except aiodns.error.DNSError as e:
            logger.warning(f"[DNS] {name} 查询 {domain} 失败: {e}")
        except Exception as e:
            logger.warning(f"[DNS] {name} 查询 {domain} 异常: {e}")

    return []


# ============================================================
# 网页抓取
# ============================================================

async def resolve_web(
    session: aiohttp.ClientSession,
    domain: str,
    source: dict,
    semaphore: asyncio.Semaphore,
) -> list[IPResult]:
    """通过网页抓取获取 IP"""
    name = source["name"]

    async with semaphore:
        limiter = get_rate_limiter(source)
        if limiter:
            await limiter.acquire()

        start = time.monotonic()
        try:
            ips = await _fetch_web_source(session, name, domain)
            latency = (time.monotonic() - start) * 1000
            return [r for ip in ips
                    if (r := _make_result(name, "web", ip, latency)) is not None]
        except asyncio.TimeoutError:
            logger.warning(f"[Web] {name} 查询 {domain} 超时")
        except Exception as e:
            logger.warning(f"[Web] {name} 查询 {domain} 异常: {e}")

    return []


async def _fetch_web_source(
    session: aiohttp.ClientSession, name: str, domain: str,
) -> list[str]:
    """根据来源名称分发到对应的抓取逻辑"""
    if name == "ipaddress.com":
        return await _fetch_ipaddress(session, domain)
    elif name == "ip-api.com":
        return await _fetch_ip_api(session, domain)
    else:
        logger.warning(f"[Web] 未知来源: {name}")
        return []


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
                return re.findall(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", html)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt < 2:
                await asyncio.sleep(1)
                continue
            raise
    return []


async def _fetch_ip_api(session: aiohttp.ClientSession, domain: str) -> list[str]:
    """从 ip-api.com 查询 IP（免费限 45 次/分钟，429 自动重试）"""
    url = f"http://ip-api.com/json/{domain}?lang=zh-CN"
    headers = {"User-Agent": _UA}

    for attempt in range(2):
        async with session.get(
            url, headers=headers,
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
            data = await resp.json(content_type=None)
            query = data.get("query", "")
            if data.get("status") == "success" and _is_valid_ip(query):
                return [query]
            return []

    return []


# ============================================================
# 主入口：对一个域名并发查询所有来源
# ============================================================

async def resolve_domain(
    domain: str,
    sources: dict,
    concurrency: dict,
) -> DomainIPs:
    """并发查询一个域名的所有来源"""
    result = DomainIPs(domain=domain)

    doh_sem = asyncio.Semaphore(concurrency.get("doh", 15))
    dns_sem = asyncio.Semaphore(concurrency.get("dns", 10))
    web_sem = asyncio.Semaphore(concurrency.get("web", 3))

    async with aiohttp.ClientSession() as session:
        tasks = []
        for src in sources.get("doh", []):
            if src.get("enabled", True):
                tasks.append(resolve_doh(session, domain, src, doh_sem))
        for src in sources.get("dns", []):
            if src.get("enabled", True):
                tasks.append(resolve_dns(domain, src, dns_sem))
        for src in sources.get("web", []):
            if src.get("enabled", True):
                tasks.append(resolve_web(session, domain, src, web_sem))

        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in all_results:
            if isinstance(r, Exception):
                logger.warning(f"[{domain}] 查询异常: {r}")
            elif isinstance(r, list):
                result.results.extend(r)

    logger.info(f"[{domain}] 获取到 {len(result.results)} 个 IP 结果")
    return result


# ============================================================
# 批量解析所有域名
# ============================================================

async def resolve_all_domains(
    domains: list[str],
    sources: dict,
    concurrency: dict,
) -> dict[str, DomainIPs]:
    """批量解析所有域名，分批处理"""
    results = {}
    batch_size = 10
    for i in range(0, len(domains), batch_size):
        batch = domains[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[resolve_domain(d, sources, concurrency) for d in batch],
            return_exceptions=True,
        )
        for d, r in zip(batch, batch_results):
            if isinstance(r, Exception):
                logger.error(f"[{d}] 批量解析异常: {r}")
            else:
                results[d] = r
    return results
