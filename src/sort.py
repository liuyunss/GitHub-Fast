"""
IP 排序与选择模块
算法：出现次数 Top2 取第1 + 延迟最低 Top3 取第1 = 3 个 IP
不足 3 个时按综合评分补充
"""

import logging
import re
import subprocess
import platform
import statistics
from collections import Counter

from .resolve import DomainIPs, IPResult

logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================
TARGET_IP_COUNT = 3       # 每个域名最终保留的 IP 数量
PING_TOP_N = 5            # 对出现次数 Top N 的 IP 做 ping 测试
PING_TIMES = 3            # 每个 IP ping 的次数
PING_TIMEOUT = 2          # ping 超时（秒）
FREQ_PICK = 2             # 出现次数 Top 中取几个
LATENCY_PICK = 1          # 延迟最低中取几个


# ============================================================
# Ping 测试
# ============================================================

def _ping_ip(ip: str, count: int = PING_TIMES, timeout: int = PING_TIMEOUT) -> float:
    """Ping 一个 IP，返回平均延迟（毫秒）。失败返回 99999。"""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), ip]
    elif system == "darwin":
        cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout * count + 5,
        )
        if result.returncode != 0:
            return 99999.0

        # 从 ping 输出中提取延迟
        # Linux/macOS: "rtt min/avg/max/mdev = 1.234/2.345/3.456/0.123 ms"
        # Windows: "Minimum = 1ms, Maximum = 3ms, Average = 2ms"
        output = result.stdout

        if system == "windows":
            match = re.search(r"Average\s*=\s*(\d+)", output)
            if match:
                return float(match.group(1))
        else:
            match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", output)
            if match:
                return float(match.group(1))
            # fallback: try time=xx ms pattern
            times = re.findall(r"time[=<](\d+\.?\d*)\s*ms", output)
            if times:
                return statistics.mean([float(t) for t in times])

        return 99999.0
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Ping {ip} 异常: {e}")
        return 99999.0


def ping_ips(ips: list[str]) -> dict[str, float]:
    """批量 ping 测试，返回 {ip: latency_ms}"""
    results = {}
    for ip in ips:
        latency = _ping_ip(ip)
        results[ip] = latency
        if latency < 99999:
            logger.info(f"Ping {ip}: {latency:.1f} ms")
        else:
            logger.info(f"Ping {ip}: 超时")
    return results


# ============================================================
# IP 选择算法
# ============================================================

def select_ips(domain_result: DomainIPs) -> list[str]:
    """
    从查询结果中选择最终的 IP 列表

    算法：
    1. 统计每个 IP 的出现次数（跨来源去重计数）
    2. 对出现次数 Top N 的 IP 做 ping 测试
    3. 选出：出现次数 Top2 的第1名 + 延迟最低 Top3 的第1名
    4. 不足 TARGET_IP_COUNT 个时，按综合评分补充
    """
    if not domain_result.results:
        return []

    # --- Step 1: 统计出现次数（按 IP 去重，同一来源只计一次）---
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

    if not ip_count:
        return []

    # 按出现次数排序
    sorted_by_freq = ip_count.most_common()
    logger.info(f"[{domain_result.domain}] IP 出现次数: {sorted_by_freq}")

    # --- Step 2: 对 Top N 做 ping 测试 ---
    top_n_ips = [ip for ip, _ in sorted_by_freq[:PING_TOP_N]]
    ping_results = ping_ips(top_n_ips)

    # --- Step 3: 选择 ---
    selected = []

    # 出现次数 Top2 取第1名
    freq_top2 = sorted_by_freq[:FREQ_PICK]
    if freq_top2:
        best_freq_ip = freq_top2[0][0]
        selected.append(best_freq_ip)
        logger.info(f"[{domain_result.domain}] 出现最多: {best_freq_ip} ({freq_top2[0][1]}次)")

    # 延迟最低 Top3 取前1名
    ping_sorted = sorted(
        [(ip, lat) for ip, lat in ping_results.items() if lat < 99999],
        key=lambda x: x[1],
    )
    latency_top = ping_sorted[:3]
    for ip, lat in latency_top[:LATENCY_PICK]:
        if ip not in selected:
            selected.append(ip)
            logger.info(f"[{domain_result.domain}] 延迟最低: {ip} ({lat:.1f}ms)")

    # --- Step 4: 不足则按综合评分补充 ---
    if len(selected) < TARGET_IP_COUNT:
        # 综合评分：出现次数权重 0.6 + 延迟倒数权重 0.4
        max_freq = sorted_by_freq[0][1] if sorted_by_freq else 1
        candidates = []
        for ip, freq in sorted_by_freq:
            if ip in selected:
                continue
            freq_score = freq / max_freq
            lat = ping_results.get(ip, 99999)
            lat_score = max(0, 1 - lat / 1000) if lat < 99999 else 0
            score = freq_score * 0.6 + lat_score * 0.4
            candidates.append((ip, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        for ip, score in candidates:
            if len(selected) >= TARGET_IP_COUNT:
                break
            selected.append(ip)
            logger.info(f"[{domain_result.domain}] 补充: {ip} (评分: {score:.3f})")

    # 如果 ping 全部超时，fallback：只按出现次数排序选 Top 3
    if not ping_sorted and len(selected) < TARGET_IP_COUNT:
        for ip, _ in sorted_by_freq:
            if ip not in selected:
                selected.append(ip)
                if len(selected) >= TARGET_IP_COUNT:
                    break

    logger.info(f"[{domain_result.domain}] 最终选择: {selected}")
    return selected[:TARGET_IP_COUNT]
