"""
Amazon 数据获取模块（API 版）
通过内部 API 获取产品数据，替代 Playwright 爬虫
API: http://genie-data.hbo-vps.com/main/api/v1/asin/{ASIN}?marketplace={MARKETPLACE}&force_refresh=true
"""

import json
import os
import sys
import subprocess
import logging
import time
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

# API 配置（优先从环境变量读取，支持 Streamlit Cloud Secrets）
API_BASE_URL = os.environ.get("API_BASE_URL", "http://genie-data.hbo-vps.com/main/api/v1/asin")
API_TIMEOUT = 60  # 秒

# 域名代码 → API marketplace 映射
DOMAIN_TO_MARKETPLACE = {
    "us": "US", "uk": "UK", "de": "DE", "jp": "JP",
    "fr": "FR", "it": "IT", "es": "ES", "ca": "CA",
    "au": "AU", "in": "IN", "sg": "SG", "mx": "MX",
    "br": "BR", "ae": "AE",
}

# Amazon 域名（用于截图功能）
AMAZON_DOMAINS = {
    "us": "https://www.amazon.com",
    "uk": "https://www.amazon.co.uk",
    "de": "https://www.amazon.de",
    "jp": "https://www.amazon.co.jp",
    "fr": "https://www.amazon.fr",
    "it": "https://www.amazon.it",
    "es": "https://www.amazon.es",
    "ca": "https://www.amazon.ca",
    "au": "https://www.amazon.com.au",
    "in": "https://www.amazon.in",
    "sg": "https://www.amazon.sg",
    "mx": "https://www.amazon.com.mx",
    "br": "https://www.amazon.com.br",
    "ae": "https://www.amazon.ae",
}

# worker 脚本路径（截图功能仍需 Playwright）
_WORKER = str(Path(__file__).parent / "scrape_worker.py")
_PYTHON = sys.executable
_BROWSER_INSTALLED = False


def fetch_product(asin: str, domain: str = "us") -> dict | None:
    """通过 API 获取产品数据，返回结构化 dict（含 5xx 重试）"""
    marketplace = DOMAIN_TO_MARKETPLACE.get(domain, domain.upper())
    url = f"{API_BASE_URL}/{asin}"
    params = {
        "marketplace": marketplace,
        "force_refresh": "true",
    }

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=API_TIMEOUT)
            if resp.status_code == 404:
                logger.info(f"产品未找到: {asin} ({marketplace})")
                return None
            if resp.status_code >= 500 and attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"API 返回 {resp.status_code}，{wait}s 后重试 ({attempt+1}/{max_retries}): {asin}")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            api_data = resp.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"网络错误，{wait}s 后重试 ({attempt+1}/{max_retries}): {asin} - {e}")
                time.sleep(wait)
                continue
            logger.error(f"API 请求失败（已重试 {max_retries} 次）: {e}")
            return None
        except requests.RequestException as e:
            logger.error(f"API 请求失败: {e}")
            return None
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"API 响应解析失败: {e}")
            return None

        if api_data.get("status") != "ok":
            logger.warning(f"API 返回错误: {api_data}")
            return None

        if attempt > 0:
            logger.info(f"重试成功: {asin}（第 {attempt+1} 次尝试）")
        return _map_api_response(api_data)

    return None


def _map_api_response(api: dict) -> dict:
    """将 API 响应映射为内部产品数据格式"""
    # BSR 类目提取
    bsr_details = api.get("bsr_details") or []
    category_parts = []
    for detail in bsr_details:
        cat = detail.get("category", "")
        if cat:
            category_parts.append(cat)

    # 主类目取第一个
    category_node = category_parts[0] if category_parts else ""

    # similar_products → related_asins
    similar = api.get("similar_products") or []
    related_asins = [p["asin"] for p in similar if p.get("asin")]

    # 变体信息
    variations = api.get("variations")
    variant_count = len(variations) if variations else 0

    product = {
        "asin": api.get("asin", ""),
        "title": api.get("title", ""),
        "brand": api.get("brand", ""),
        "main_image": api.get("image", ""),
        "images": api.get("images") or [],
        "price_daily": api.get("price"),
        "currency": api.get("currency", ""),
        "rating": api.get("rating"),
        "review_count": api.get("review_count", 0),
        "bsr": api.get("bsr"),
        "bsr_details": bsr_details,
        "category_node": category_node,
        "bullet_points": api.get("bullet_points") or [],
        "product_details": api.get("product_details") or {},
        "variant_count": variant_count,
        "variant_dimension": "",
        "stock_status": api.get("availability", "未知"),
        "fulfillment": "未知",
        "coupon": "无",
        "seller": "",
        "related_asins": related_asins,
        "similar_products": similar,
        "best_seller_badge": api.get("best_seller_badge", False),
        "amazon_choice_badge": api.get("amazon_choice_badge", False),
        "parent_asin": api.get("parent_asin", ""),
        "url": api.get("url", ""),
        "reviews": [],  # API 不提供评论详情
    }

    # 价格相关
    product["price_promo"] = product["price_daily"]
    product["price_original"] = product["price_daily"]

    return product


def fetch_search(keyword: str, domain: str = "us", page: int = 1) -> list[dict]:
    """抓取搜索结果页（仍使用 Playwright worker）"""
    result = _run_worker("search", keyword, domain, extra_args=[str(page)])
    if isinstance(result, list):
        return result
    return []


def fetch_screenshot(asin: str, domain: str = "us", language: str | None = None) -> str | None:
    """截取产品页面截图（仍使用 Playwright worker）"""
    extra = [language] if language else None
    result = _run_worker("screenshot", asin, domain, extra_args=extra, timeout=30)
    if isinstance(result, dict) and "screenshot" in result:
        return result["screenshot"]
    if isinstance(result, dict):
        logger.warning(f"截图失败: {result.get('message', result.get('error'))}")
    return None


# ============================================================
# Playwright Worker（仅用于搜索和截图）
# ============================================================

def _ensure_browser():
    global _BROWSER_INSTALLED
    if _BROWSER_INSTALLED:
        return
    try:
        result = subprocess.run(
            [_PYTHON, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            logger.info("Playwright chromium 安装成功")
        else:
            logger.warning(f"Playwright install 输出: {result.stderr[:300]}")
    except Exception as e:
        logger.warning(f"Playwright install 跳过: {e}")
    _BROWSER_INSTALLED = True


def _run_worker(command: str, arg: str, domain: str = "us",
                extra_args: list | None = None, timeout: int = 45) -> dict | list | None:
    """调用 scrape_worker.py 子进程，返回解析后的 JSON"""
    _ensure_browser()

    cmd = [_PYTHON, _WORKER, command, arg, domain]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=str(Path(__file__).parent),
        )

        if result.returncode != 0:
            logger.warning(f"Worker 进程退出码 {result.returncode}: {result.stderr[:200]}")

        stdout = result.stdout.strip()
        if not stdout:
            logger.error(f"Worker 无输出: stderr={result.stderr[:200]}")
            return None

        return json.loads(stdout)

    except subprocess.TimeoutExpired:
        logger.error(f"Worker 超时 ({timeout}s): {command} {arg}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Worker 输出 JSON 解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"Worker 调用失败: {e}")
        return None
