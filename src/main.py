"""
GitHub-fast 主入口
读取配置 → 并发解析所有域名 → 选 IP → 生成 hosts 文件
"""

import asyncio
import logging
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

from .resolve import resolve_all_domains
from .sort import select_ips
from .generate import generate_hosts, generate_readme

PROJECT_ROOT = Path(__file__).parent.parent

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# 配置加载
# ============================================================

def load_config(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"配置文件格式错误: {e}")
        sys.exit(1)


def extract_domains(config: dict) -> list[str]:
    """从配置中提取所有启用的域名（去重，保持顺序）"""
    seen = set()
    domains = []
    for group in config.get("groups", []):
        if not group.get("enabled", True):
            continue
        for item in group.get("domains", []):
            if not item.get("enabled", True):
                continue
            domain = item.get("domain")
            if not domain:
                logger.warning(f"跳过无效域名条目: {item}")
                continue
            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
    return domains


# ============================================================
# 来源统计
# ============================================================

def _log_source_stats(results: dict):
    """统计每个来源的成功率和贡献 IP 数"""
    total_domains = len(results)
    if total_domains == 0:
        return

    source_domains: Counter[str] = Counter()
    source_ips: Counter[str] = Counter()
    source_type_map: dict[str, str] = {}

    for domain_result in results.values():
        seen_sources: set[str] = set()
        for r in domain_result.results:
            key = r.source
            source_type_map[key] = r.source_type
            source_ips[key] += 1
            if key not in seen_sources:
                source_domains[key] += 1
                seen_sources.add(key)

    logger.info("")
    logger.info("=" * 60)
    logger.info("来源统计")
    logger.info("=" * 60)
    logger.info(f"{'来源':<16} {'类型':<6} {'成功域名':>8} {'总IP数':>8} {'成功率':>8}")
    logger.info("-" * 60)

    for source, count in source_domains.most_common():
        stype = source_type_map.get(source, "?")
        rate = count / total_domains * 100
        ip_count = source_ips[source]
        logger.info(f"{source:<16} {stype:<6} {count:>6}/{total_domains} {ip_count:>8} {rate:>7.1f}%")

    total_ip_count = sum(source_ips.values())
    logger.info("-" * 60)
    logger.info(f"{'总计':<16} {'':6} {total_domains:>6}/{total_domains} {total_ip_count:>8}")
    logger.info("=" * 60)
    logger.info("")


# ============================================================
# 主流程
# ============================================================

async def run(config_path: str = "config.yaml", repo: str = "liuyunss/GitHub-fast"):
    start_time = time.monotonic()
    logger.info("=" * 50)
    logger.info("GitHub-fast 开始更新")
    logger.info("=" * 50)

    # 1. 加载配置
    config = load_config(config_path)
    sources = config.get("sources", {})
    concurrency = config.get("concurrency", {})
    groups = config.get("groups", [])
    ping_enabled = config.get("ping_enabled", False)

    domains = extract_domains(config)
    ping_status = "开启" if ping_enabled else "关闭"
    logger.info(f"共 {len(domains)} 个域名需要解析")
    logger.info(f"Ping 测试: {ping_status}")

    # 2. 并发解析所有域名
    logger.info("开始并发解析...")
    results = await resolve_all_domains(domains, sources, concurrency)
    logger.info(f"解析完成，{len(results)} 个域名有结果")

    # 2.1 来源统计
    _log_source_stats(results)

    # 3. 对每个域名选 IP（并发）
    valid_domains = [d for d in domains if d in results]
    tasks = [select_ips(results[d], ping_enabled=ping_enabled) for d in valid_domains]
    ip_results = await asyncio.gather(*tasks)

    domain_ips = {}
    for domain, ips in zip(valid_domains, ip_results):
        if ips:
            domain_ips[domain] = ips
        else:
            logger.warning(f"[{domain}] 未选出有效 IP")

    logger.info(f"共 {len(domain_ips)} 个域名成功获取 IP")

    # 4. 生成 hosts 文件
    output_path = PROJECT_ROOT / "hosts"
    hosts_content = generate_hosts(
        domain_ips=domain_ips,
        groups=groups,
        repo=repo,
        output_path=str(output_path),
    )
    logger.info(f"hosts 文件已生成: {output_path}")

    # 5. 生成 README
    readme_path = PROJECT_ROOT / "README.md"
    readme_content = generate_readme(repo=repo)
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info(f"README 已生成: {readme_path}")

    elapsed = time.monotonic() - start_time
    logger.info("=" * 50)
    logger.info(f"完成！耗时 {elapsed:.1f} 秒")
    logger.info(f"成功解析 {len(domain_ips)}/{len(domains)} 个域名")
    logger.info("=" * 50)

    return domain_ips


# ============================================================
# CLI 入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="GitHub-fast: GitHub 访问加速")
    parser.add_argument(
        "-c", "--config", default="config.yaml",
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--repo", default="liuyunss/GitHub-fast",
        help="GitHub 仓库地址",
    )
    args = parser.parse_args()
    asyncio.run(run(config_path=args.config, repo=args.repo))


if __name__ == "__main__":
    main()
