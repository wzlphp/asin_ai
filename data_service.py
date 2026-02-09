"""
数据服务层 - 基于真实 Amazon 爬虫获取产品和竞品数据
调用 scraper.py → subprocess → scrape_worker.py (Playwright)
"""

import re
import logging
from collections import Counter
from scraper import fetch_product, fetch_search

logger = logging.getLogger(__name__)


def search_product(asin: str, domain: str = "us") -> dict | None:
    """根据 ASIN 查询产品完整信息"""
    asin = asin.strip().upper()
    if not re.match(r"^[A-Z0-9]{10}$", asin):
        return None

    product = fetch_product(asin, domain)
    if not product or not product.get("title"):
        return None

    # 补充默认字段
    product.setdefault("price_promo", product.get("price_daily"))
    product.setdefault("price_original", product.get("price_daily"))
    product.setdefault("variant_count", 0)
    product.setdefault("variant_dimension", "")
    product.setdefault("rating", None)
    product.setdefault("review_count", 0)
    product.setdefault("bsr", None)
    product.setdefault("category_node", "")
    product.setdefault("bullet_points", [])
    product.setdefault("fulfillment", "未知")
    product.setdefault("stock_status", "未知")
    product.setdefault("coupon", "无")
    product.setdefault("related_asins", [])
    product.setdefault("reviews", [])

    # 主打卖点（取第一条 bullet）
    if product["bullet_points"]:
        first = product["bullet_points"][0]
        product["main_selling_point"] = first[:80] + ("..." if len(first) > 80 else "")
    else:
        product["main_selling_point"] = ""

    return product


def find_competitors(asin: str, domain: str = "us", count: int = 5,
                     progress_callback=None) -> list[dict]:
    """
    查找竞品：
    1. 优先从产品页 related_asins 获取
    2. 不足时用标题关键词搜索补充
    """
    target = search_product(asin, domain)
    if not target:
        return []

    candidate_asins = []

    # 来源1: 产品页相关产品
    related = [a for a in target.get("related_asins", []) if a != asin.upper()]
    candidate_asins.extend(related)

    # 来源2: 标题关键词搜索补充
    if len(candidate_asins) < count and target.get("title"):
        words = target["title"].split()[:5]
        search_kw = " ".join(words)
        if progress_callback:
            progress_callback(f"搜索关键词: {search_kw}")

        search_results = fetch_search(search_kw, domain)
        for sr in search_results:
            if sr["asin"] != asin.upper() and sr["asin"] not in candidate_asins:
                candidate_asins.append(sr["asin"])

    # 去重截取
    seen = set()
    unique = []
    for a in candidate_asins:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    candidate_asins = unique[:count]

    # 逐个抓取竞品详情
    competitors = []
    for i, comp_asin in enumerate(candidate_asins):
        if progress_callback:
            progress_callback(f"正在抓取竞品 {i+1}/{len(candidate_asins)}: {comp_asin}")

        comp = search_product(comp_asin, domain)
        if comp:
            # BSR 分层
            if comp.get("bsr") and target.get("bsr"):
                if comp["bsr"] <= 10:
                    comp["tier"] = "头部"
                elif abs(comp["bsr"] - target["bsr"]) < target["bsr"] * 0.5:
                    comp["tier"] = "对标"
                else:
                    comp["tier"] = "潜力"
            else:
                comp["tier"] = "对标"

            comp["name"] = f"{comp.get('brand', '')} ({comp['asin']})"
            competitors.append(comp)

        if len(competitors) >= count:
            break

    return competitors


def get_review_analysis(product: dict) -> dict:
    """
    从产品数据中分析评价（评价在产品页抓取时已提取）
    返回 {positive_keywords, negative_keywords, reviews, total, positive_count, negative_count}
    """
    all_reviews = product.get("reviews", [])

    if not all_reviews:
        return {"positive_keywords": [], "negative_keywords": [],
                "reviews": [], "total": 0, "positive_count": 0, "negative_count": 0}

    # 去重
    seen = set()
    unique = []
    for r in all_reviews:
        body = r.get("body", "")
        if body and body not in seen:
            seen.add(body)
            unique.append(r)

    positive_texts, negative_texts = [], []
    for r in unique:
        stars = r.get("stars")
        text = f"{r.get('title', '')} {r.get('body', '')}"
        if stars and stars >= 4:
            positive_texts.append(text)
        elif stars and stars <= 3:
            negative_texts.append(text)

    return {
        "positive_keywords": _extract_keywords(" ".join(positive_texts))[:10],
        "negative_keywords": _extract_keywords(" ".join(negative_texts))[:10],
        "reviews": unique,
        "total": len(unique),
        "positive_count": len(positive_texts),
        "negative_count": len(negative_texts),
    }


def get_keyword_rankings(keywords: list[str], target_asin: str,
                         competitor_asins: list[str],
                         domain: str = "us",
                         progress_callback=None) -> list[dict]:
    """搜索关键词，查找目标和竞品的排名位置"""
    all_asins = {target_asin.upper(): f"本品 ({target_asin.upper()})"}
    for a in competitor_asins:
        all_asins[a.upper()] = a.upper()

    data = []
    for kw in keywords:
        if progress_callback:
            progress_callback(f"搜索关键词: {kw}")

        all_results = []
        for page in range(1, 4):
            results = fetch_search(kw, domain, page=page)
            if not results:
                break
            offset = len(all_results)
            for r in results:
                r["rank"] += offset
            all_results.extend(results)

        for result_asin, name in all_asins.items():
            found = False
            for r in all_results:
                if r["asin"] == result_asin:
                    data.append({
                        "关键词": kw,
                        "产品": name,
                        "自然排名": r["rank"],
                        "是否广告": "广告" if r.get("is_sponsored") else "自然",
                    })
                    found = True
                    break
            if not found:
                data.append({
                    "关键词": kw, "产品": name,
                    "自然排名": None, "是否广告": "-",
                })

    return data


def extract_keywords_from_title(title: str) -> list[str]:
    """从产品标题提取搜索关键词"""
    if not title:
        return []
    stop = {"the", "a", "an", "and", "or", "for", "with", "in", "on", "to",
            "of", "by", "is", "it", "at", "as", "from", "that", "this", "-", "/", "|", ",", ".", "&", "+"}
    words = [w for w in re.findall(r"[a-zA-Z]+", title.lower()) if w not in stop and len(w) > 1]
    keywords = []
    if len(words) >= 2:
        keywords.append(" ".join(words[:3]))
        keywords.append(" ".join(words[:2]))
        if len(words) >= 4:
            keywords.append(" ".join(words[1:4]))
    return keywords[:5]


def _extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """从英文文本提取高频关键词"""
    if not text:
        return []
    text = re.sub(r"[^\w\s]", " ", text.lower())
    stop = {
        "the", "a", "an", "and", "or", "for", "with", "in", "on", "to",
        "of", "by", "is", "it", "at", "as", "from", "that", "this", "was",
        "but", "are", "be", "have", "has", "had", "not", "they", "them",
        "we", "my", "me", "i", "you", "your", "its", "so", "very",
        "just", "will", "would", "could", "can", "do", "did", "get",
        "got", "been", "being", "than", "then", "no", "if", "all",
        "one", "two", "also", "about", "out", "up", "how", "what",
        "which", "when", "there", "their", "our", "these", "those",
        "some", "other", "each", "into", "only", "over", "such",
        "after", "before", "between", "through", "same", "any",
        "much", "more", "most", "both", "own", "still", "even",
        "really", "product", "item", "bought", "purchase", "use",
        "using", "used", "like", "good", "great", "nice", "well",
        "best", "better", "love", "work", "works", "working",
    }
    words = [w for w in text.split() if w not in stop and len(w) > 2]
    counter = Counter(words)
    for i in range(len(words) - 1):
        counter[f"{words[i]} {words[i+1]}"] += 1
    return [w for w, _ in counter.most_common(top_n)]
