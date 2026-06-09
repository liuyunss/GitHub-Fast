"""
IP 排序与选择模块
ping 关闭时：直接取出现次数最多的 3 个
ping 开启时：从出现次数 Top N 中并发 ping，取延迟最低的 1 个 + 频次最高的 1 个
"""

import asyncio
import logging
import platform
import re
import statistics
import subprocess
from collections import Counter

from .resolve import DomainIPs

logger = logging.getLogger(__name__)

# ============================================================
# 默认配置（可通过 config.yaml 覆盖）
# ============================================================
TARGET_IP_COUNT = 3       # 每个域名最终保留的 IP 数量
PING_TOP_N = 5            # 对出现次数 Top N 的 IP 做 ping 测试
PING_TIMES = 3            # 每个 IP ping 的次数
PING_TIMEOUT = 1          # ping 超时（秒）
PING_ENABLED = False      # 默认关闭，GitHub Actions 环境不支持 ICMP


# ============================================================
# Ping 测试
# ============================================================

def _ping_one(ip: str, count: int = PING_TIMES, timeout: int = PING_TIMEOUT) -> float:
    """Ping 单个 IP，返回平均延迟（毫秒）。失败返回 99999。"""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout * count + 2,
        )
        if result.returncode != 0:
            return 99999.0

        output = result.stdout
        if system == "windows":
            match = re.search(r"Average\s*=\s*(\d+)", output)
            if match:
                return float(match.group(1))
        else:
            match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", output)
            if match:
                return float(match.group(1))
            times = re.findall(r"time[=<](\d+\.?\d*)\s*ms", output)
            if times:
                return statistics.mean([float(t) for t in times])

        return 99999.0
    except Exception:
        return 99999.0


async def _ping_one_async(ip: str, count: int = PING_TIMES, timeout: int = PING_TIMEOUT) -> tuple[str, float]:
    """异步封装：在线程池中执行 ping，返回 (ip, latency_ms)。"""
    loop = asyncio.get_event_loop()
    latency = await loop.run_in_executor(None, _ping_one, ip, count, timeout)
    return ip, latency


async def ping_ips_concurrent(ips: list[str]) -> dict[str, float]:
    """并发 ping 多个 IP，返回 {ip: latency_ms}"""
    if not ips:
        return {}

    tasks = [_ping_one_async(ip) for ip in ips]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ping_map = {}
    for r in results:
        if isinstance(r, Exception):
            continue
        ip, latency = r
        ping_map[ip] = latency
        if latency < 99999:
            logger.info(f"Ping {ip}: {latency:.1f} ms")
        else:
            logger.info(f"Ping {ip}: 超时")
    return ping_map


# ============================================================
# IP 选择算法
# ============================================================

def _count_ips(domain_result: DomainIPs) -> list[tuple[str, int]]:
    """统计每个 IP 的出现次数，按次数降序返回 [(ip, count), ...]"""
    source_ip_map: dict[str, set[str]] = {}
    for r in domain_result.results:
        key = f"{r.source_type}:{r.source}"
        if key not in source_ip_map:
            source_ip_map[key] = set()
        source_ip_map[key].add(r.ip)

    ip_count: Counter[str] = Counter()
    for ip_set in source_ip_map.values():
        for ip in ip_set:
            ip_count[ip] += 1

    return ip_count.most_common()


def _select_by_freq(sorted_by_freq: list[tuple[str, int]], count: int) -> list[str]:
    """直接取出现次数最多的 N 个"""
    return [ip for ip, _ in sorted_by_freq[:count]]


async def select_ips(domain_result: DomainIPs, ping_enabled: bool = PING_ENABLED) -> list[str]:
    """
    从查询结果中选择最终的 IP 列表

    ping 关闭：直接取出现次数最多的 TARGET_IP_COUNT 个
    ping 开启：对 Top N 做并发 ping，取延迟最低的 1 个 + 频次最高的 1 个，不足按频次补
    """
    if not domain_result.results:
        return []

    sorted_by_freq = _count_ips(domain_result)
    if not sorted_by_freq:
        return []

    logger.info(f"[{domain_result.domain}] IP 出现次数: {sorted_by_freq}")

    # === ping 关闭：纯频次 ===
    if not ping_enabled:
        selected = _select_by_freq(sorted_by_freq, TARGET_IP_COUNT)
        logger.info(f"[{domain_result.domain}] 最终选择(频次): {selected}")
        return selected

    # === ping 开启：并发 ping Top N ===
    top_n_ips = [ip for ip, _ in sorted_by_freq[:PING_TOP_N]]
    ping_results = await ping_ips_concurrent(top_n_ips)

    # 延迟最低的 1 个
    ping_sorted = sorted(
        [(ip, lat) for ip, lat in ping_results.items() if lat < 99999],
        key=lambda x: x[1],
    )

    selected = []

    # 频次最高的 1 个
    best_freq_ip = sorted_by_freq[0][0]
    selected.append(best_freq_ip)
    logger.info(f"[{domain_result.domain}] 出现最多: {best_freq_ip} ({sorted_by_freq[0][1]}次)")

    # 延迟最低的 1 个（如果不重复）
    if ping_sorted:
        best_lat_ip = ping_sorted[0][0]
        if best_lat_ip not in selected:
            selected.append(best_lat_ip)
            logger.info(f"[{domain_result.domain}] 延迟最低: {best_lat_ip} ({ping_sorted[0][1]:.1f}ms)")

    # 不足则按频次补充
    for ip, _ in sorted_by_freq:
        if len(selected) >= TARGET_IP_COUNT:
            break
        if ip not in selected:
            selected.append(ip)
            logger.info(f"[{domain_result.domain}] 补充: {ip}")

    logger.info(f"[{domain_result.domain}] 最终选择: {selected}")
    return selected[:TARGET_IP_COUNT]
