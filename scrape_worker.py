"""
Playwright 爬虫工作进程
独立运行（通过 subprocess 调用），避免与 Streamlit 事件循环冲突

用法：
    python scrape_worker.py product <asin> [domain]
    python scrape_worker.py search <keyword> [domain] [page]
    python scrape_worker.py screenshot <asin> [domain] [language]

返回 JSON 到 stdout
"""

import sys
import json
import re
import base64
import logging
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# 确保 UTF-8 输出
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

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


def fetch_page(url: str, wait_selector: str | None = None) -> str | None:
    """用 Playwright 抓取页面 HTML"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except Exception:
                    pass
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(1500)
            html = page.content()

            # 检查 captcha
            lower = html.lower()
            captcha_signals = ["captcha", "robot check", "sorry, we just need to make sure",
                               "type the characters you see"]
            if any(s in lower for s in captcha_signals):
                print(json.dumps({"error": "captcha", "message": "触发反爬验证"}),
                      file=sys.stderr)
                return None
            return html
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            return None
        finally:
            browser.close()


def fetch_screenshot(url: str) -> str | None:
    """用 Playwright 截取页面截图，返回 base64 编码的 PNG"""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.wait_for_selector("#productTitle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            screenshot_bytes = page.screenshot(full_page=False)
            return base64.b64encode(screenshot_bytes).decode("ascii")
        except Exception as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            return None
        finally:
            browser.close()


# ============================================================
# 解析函数
# ============================================================

def parse_product(html: str, asin: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    data = {"asin": asin}

    title_el = soup.select_one("#productTitle")
    data["title"] = title_el.get_text(strip=True) if title_el else ""
    if not data["title"]:
        return None

    # 品牌
    brand_el = soup.select_one("#bylineInfo") or soup.select_one("a#bylineInfo")
    if brand_el:
        brand_text = brand_el.get_text(strip=True)
        brand_text = re.sub(r"^(Visit the |Brand:\s*)", "", brand_text)
        brand_text = re.sub(r"\s*Store$", "", brand_text)
        data["brand"] = brand_text
    else:
        data["brand"] = ""

    # 主图
    img_el = (soup.select_one("#landingImage")
              or soup.select_one("#imgTagWrapperId img")
              or soup.select_one("#main-image-container img")
              or soup.select_one("#imageBlock img"))
    if img_el:
        # 优先取 data-old-hires（高清大图），其次 src
        data["main_image"] = (img_el.get("data-old-hires")
                              or img_el.get("src")
                              or "")
    else:
        data["main_image"] = ""

    # 价格
    data["price_daily"] = _parse_price(soup)
    was_el = soup.select_one("span.a-price[data-a-strike='true'] span.a-offscreen")
    if was_el:
        was_price = _extract_number(was_el.get_text(strip=True))
        if was_price and data["price_daily"] and was_price > data["price_daily"]:
            data["price_original"] = was_price
            data["price_promo"] = data["price_daily"]
        else:
            data["price_original"] = data["price_daily"]
            data["price_promo"] = data["price_daily"]
    else:
        data["price_original"] = data["price_daily"]
        data["price_promo"] = data["price_daily"]

    # 星级
    rating_el = (soup.select_one("span[data-hook='rating-out-of-text']")
                 or soup.select_one("#acrPopover"))
    if rating_el:
        rn = _extract_number(rating_el.get_text(strip=True))
        data["rating"] = rn if rn and rn <= 5 else None
    else:
        data["rating"] = None

    # 评价数
    review_el = soup.select_one("#acrCustomerReviewText")
    data["review_count"] = _extract_int(review_el.get_text(strip=True)) if review_el else 0

    # BSR
    data["bsr"], data["bsr_category"] = _parse_bsr(soup)

    # 类目
    crumbs = soup.select("#wayfinding-breadcrumbs_container a") or soup.select(".a-breadcrumb a")
    data["category_node"] = " > ".join(a.get_text(strip=True) for a in crumbs) if crumbs else data.get("bsr_category", "")

    # 五点
    bullets = soup.select("#feature-bullets li span.a-list-item")
    data["bullet_points"] = [b.get_text(strip=True) for b in bullets if b.get_text(strip=True)]

    # 变体
    sections = soup.select("#variation_size_name li, #variation_color_name li, #variation_style_name li")
    if sections:
        dim_el = soup.select_one("#variation_size_name .a-form-label, #variation_color_name .a-form-label, #variation_style_name .a-form-label")
        data["variant_dimension"] = dim_el.get_text(strip=True).rstrip(":") if dim_el else ""
        data["variant_count"] = len(sections)
    else:
        twister = soup.select("#twister .a-button-text")
        data["variant_count"] = len(twister) if twister else 0
        data["variant_dimension"] = ""

    # 发货 — 从 "Ships from" 字段判断
    ships_from = ""
    for label_div in soup.select("div.offer-display-feature-label"):
        if "ships from" in label_div.get_text(strip=True).lower():
            val_div = label_div.find_next_sibling("div", class_="offer-display-feature-text")
            if val_div:
                # 取第一个 span 的文本（避免重复拼接）
                first_span = val_div.select_one("span.a-size-small")
                ships_from = (first_span.get_text(strip=True) if first_span
                              else val_div.get_text(strip=True))
            break
    if ships_from:
        data["fulfillment"] = "FBA" if "amazon" in ships_from.lower() else f"FBM ({ships_from})"
    else:
        ful_el = soup.select_one("#fulfilledBy, #deliveryShortLine")
        if ful_el:
            ft = ful_el.get_text(strip=True)
            data["fulfillment"] = "FBA" if "amazon" in ft.lower() else f"FBM ({ft})"
        else:
            data["fulfillment"] = "未知"

    # 库存
    avail_el = soup.select_one("#availability span")
    if avail_el:
        at = avail_el.get_text(strip=True).lower()
        if "in stock" in at:
            data["stock_status"] = "有货"
        elif "only" in at and "left" in at:
            data["stock_status"] = f"库存紧张 ({avail_el.get_text(strip=True)})"
        elif "unavailable" in at or "out of stock" in at:
            data["stock_status"] = "断货"
        else:
            data["stock_status"] = avail_el.get_text(strip=True)
    else:
        data["stock_status"] = "未知"

    # 优惠券
    coupon_el = soup.select_one("#couponBadgeRegularVpc, #vpcButton")
    data["coupon"] = coupon_el.get_text(strip=True) if coupon_el else "无"

    # 卖家
    seller_el = soup.select_one("#merchant-info") or soup.select_one("#sellerProfileTriggerId")
    data["seller"] = seller_el.get_text(strip=True) if seller_el else ""

    # 相关 ASIN
    asins = set()
    for link in soup.select("a[href*='/dp/']"):
        match = re.search(r"/dp/([A-Z0-9]{10})", link.get("href", ""))
        if match and match.group(1) != asin:
            asins.add(match.group(1))
    data["related_asins"] = list(asins)[:20]

    # 页面上的评价
    reviews = []
    for div in soup.select("[data-hook='review']"):
        review = {}
        star_el = div.select_one("[data-hook='review-star-rating'] span, [data-hook='cmps-review-star-rating'] span")
        review["stars"] = _extract_number(star_el.get_text(strip=True)) if star_el else None
        title_el = div.select_one("[data-hook='review-title'] span:last-child")
        review["title"] = title_el.get_text(strip=True) if title_el else ""
        body_el = div.select_one("[data-hook='review-body'] span")
        review["body"] = body_el.get_text(strip=True) if body_el else ""
        date_el = div.select_one("[data-hook='review-date']")
        review["date"] = date_el.get_text(strip=True) if date_el else ""
        if review.get("body") or review.get("title"):
            reviews.append(review)
    data["reviews"] = reviews

    return data


def parse_search(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    items = soup.select("[data-component-type='s-search-result']")
    for rank, item in enumerate(items, 1):
        asin = item.get("data-asin", "")
        if not asin:
            continue
        title_el = item.select_one("h2 a span")
        price_el = item.select_one("span.a-price span.a-offscreen")
        rating_el = item.select_one("span.a-icon-alt")
        review_el = (item.select_one("span.a-size-base.s-underline-text")
                     or item.select_one("[aria-label*='stars'] + span")
                     or item.select_one("a[href*='customerReviews'] span"))
        sponsored = bool(item.select_one("[data-component-type='sp-sponsored-result']")
                         or item.select_one(".s-label-popover-default"))
        results.append({
            "rank": rank,
            "asin": asin,
            "title": title_el.get_text(strip=True) if title_el else "",
            "price": _extract_number(price_el.get_text(strip=True)) if price_el else None,
            "rating": _extract_number(rating_el.get_text(strip=True)) if rating_el else None,
            "review_count": _extract_int(review_el.get_text(strip=True)) if review_el else 0,
            "is_sponsored": sponsored,
        })
    return results


# ============================================================
# 辅助函数
# ============================================================

def _parse_price(soup):
    for sel in ["span.a-price:not([data-a-strike]) span.a-offscreen",
                "#priceblock_ourprice", "#priceblock_dealprice",
                "#price_inside_buybox", "span.a-price span.a-offscreen"]:
        el = soup.select_one(sel)
        if el:
            p = _extract_number(el.get_text(strip=True))
            if p and p > 0:
                return p
    return None


def _parse_bsr(soup):
    bsr_row = soup.find("th", string=re.compile(r"Best Sellers Rank", re.I))
    if bsr_row:
        td = bsr_row.find_next_sibling("td")
        if td:
            m = re.search(r"#([\d,]+)\s+in\s+(.+?)(?:\(|$)", td.get_text(strip=True))
            if m:
                return int(m.group(1).replace(",", "")), m.group(2).strip()
    for el in soup.find_all(string=re.compile(r"Best Sellers Rank")):
        parent = el.find_parent()
        if parent:
            m = re.search(r"#([\d,]+)\s+in\s+(.+?)(?:\(|$)", parent.get_text())
            if m:
                return int(m.group(1).replace(",", "")), m.group(2).strip()
    return None, ""


def _extract_number(text):
    if not text:
        return None
    m = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def _extract_int(text):
    if not text:
        return 0
    m = re.search(r"[\d,]+", text)
    if m:
        try:
            return int(m.group().replace(",", ""))
        except ValueError:
            return 0
    return 0


# ============================================================
# 入口
# ============================================================

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: scrape_worker.py <command> <arg> [domain] [page]"}))
        sys.exit(1)

    command = sys.argv[1]
    arg = sys.argv[2]
    domain = sys.argv[3] if len(sys.argv) > 3 else "us"

    base_url = AMAZON_DOMAINS.get(domain, AMAZON_DOMAINS["us"])

    if command == "product":
        url = f"{base_url}/dp/{arg}"
        html = fetch_page(url, wait_selector="#productTitle")
        if html:
            result = parse_product(html, arg)
            if result:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(json.dumps({"error": "parse_failed", "message": "无法解析产品页面"}))
        else:
            print(json.dumps({"error": "fetch_failed", "message": "无法抓取产品页面"}))

    elif command == "search":
        page_num = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        url = f"{base_url}/s?k={quote_plus(arg)}&page={page_num}"
        html = fetch_page(url, wait_selector="[data-component-type='s-search-result']")
        if html:
            results = parse_search(html)
            print(json.dumps(results, ensure_ascii=False))
        else:
            print(json.dumps([]))

    elif command == "screenshot":
        language = sys.argv[4] if len(sys.argv) > 4 else None
        url = f"{base_url}/dp/{arg}"
        if language:
            url += f"?language={language}"
        img_b64 = fetch_screenshot(url)
        if img_b64:
            print(json.dumps({"screenshot": img_b64}))
        else:
            print(json.dumps({"error": "screenshot_failed", "message": "无法截取页面"}))

    else:
        print(json.dumps({"error": f"unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
