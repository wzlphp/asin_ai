"""
Amazon 爬虫模块（进程隔离版）
通过 subprocess 调用 scrape_worker.py 运行 Playwright，
避免与 Streamlit 的异步事件循环冲突
"""

import json
import sys
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# worker 脚本路径
_WORKER = str(Path(__file__).parent / "scrape_worker.py")
_PYTHON = sys.executable

# 确保 Playwright 浏览器已安装（Streamlit Cloud 等环境首次运行时需要）
_BROWSER_INSTALLED = False


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


def fetch_product(asin: str, domain: str = "us") -> dict | None:
    """抓取并解析产品页，返回结构化 dict"""
    result = _run_worker("product", asin, domain)
    if isinstance(result, dict) and "error" not in result:
        return result
    if isinstance(result, dict):
        logger.warning(f"产品抓取失败: {result.get('message', result.get('error'))}")
    return None


def fetch_search(keyword: str, domain: str = "us", page: int = 1) -> list[dict]:
    """抓取搜索结果页，返回结果列表"""
    result = _run_worker("search", keyword, domain, extra_args=[str(page)])
    if isinstance(result, list):
        return result
    return []


def fetch_screenshot(asin: str, domain: str = "us", language: str | None = None) -> str | None:
    """截取产品页面截图，返回 base64 编码的 PNG 字符串"""
    extra = [language] if language else None
    result = _run_worker("screenshot", asin, domain, extra_args=extra, timeout=30)
    if isinstance(result, dict) and "screenshot" in result:
        return result["screenshot"]
    if isinstance(result, dict):
        logger.warning(f"截图失败: {result.get('message', result.get('error'))}")
    return None
