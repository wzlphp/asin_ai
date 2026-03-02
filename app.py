"""
亚马逊竞品分析工具
Amazon Competitive Analysis Tool

流程：输入 ASIN → 调用 API 获取数据 → 自动查找竞品 → 四大维度分析
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import base64
from data_service import (
    search_product,
    find_competitors,
    get_review_analysis,
    get_keyword_rankings,
    extract_keywords_from_title,
)
from scraper import fetch_screenshot

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="亚马逊竞品分析工具",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 亚马逊竞品分析工具")
st.caption("输入 ASIN → 调用 API 获取 Amazon 数据 → 四大维度深度分析")

# ============================================================
# 侧边栏 - ASIN 输入
# ============================================================
st.sidebar.header("🔍 产品搜索")

DOMAIN_LABELS = {
    "us": "🇺🇸 Amazon.com", "uk": "🇬🇧 Amazon.co.uk",
    "de": "🇩🇪 Amazon.de", "jp": "🇯🇵 Amazon.co.jp",
    "fr": "🇫🇷 Amazon.fr", "it": "🇮🇹 Amazon.it",
    "es": "🇪🇸 Amazon.es", "ca": "🇨🇦 Amazon.ca",
    "au": "🇦🇺 Amazon.com.au", "in": "🇮🇳 Amazon.in",
    "sg": "🇸🇬 Amazon.sg", "mx": "🇲🇽 Amazon.com.mx",
    "br": "🇧🇷 Amazon.com.br", "ae": "🇦🇪 Amazon.ae",
}

domain = st.sidebar.selectbox(
    "Amazon 站点",
    options=list(DOMAIN_LABELS.keys()),
    format_func=lambda x: DOMAIN_LABELS[x],
)

asin_input = st.sidebar.text_input(
    "输入 ASIN",
    value="",
    placeholder="例如：B0D7Q5GY93",
    help="输入亚马逊产品的 ASIN 编码（10位字母数字），可在产品页URL中找到",
)

competitor_count = st.sidebar.slider("查找竞品数量", min_value=2, max_value=8, value=5)

analyze_keywords = st.sidebar.checkbox("分析关键词排名", value=False,
                                       help="开启后会搜索关键词排名，耗时较长")

search_clicked = st.sidebar.button("🔍 开始分析", type="primary", use_container_width=True)

# ============================================================
# 搜索触发
# ============================================================
if search_clicked and asin_input.strip():
    st.session_state["active_asin"] = asin_input.strip().upper()
    st.session_state["domain"] = domain
    st.session_state["comp_count"] = competitor_count
    st.session_state["do_keywords"] = analyze_keywords
    # 清除旧的缓存数据
    for key in ["product", "competitors", "reviews", "comp_reviews", "kw_data"]:
        st.session_state.pop(key, None)

active_asin = st.session_state.get("active_asin")

# ============================================================
# 未搜索时的引导页
# ============================================================
if not active_asin:
    st.markdown("---")
    st.markdown("""
    ### 使用方法
    1. 选择 Amazon 站点（默认美国站）
    2. 在左侧输入目标产品的 **ASIN**
    3. 点击 **开始分析**，系统将通过 API 获取数据

    ### 分析维度
    | 维度 | 关注点 |
    |------|--------|
    | **基础信息** | 类目定位、价格体系、变体布局 |
    | **流量与转化** | 关键词排名、广告活动、评价分析 |
    | **产品与运营** | 供应链能力、发货方式、库存状态 |
    | **合规与风险** | 差评硬伤、违规信号分析 |

    ### 如何找到 ASIN？
    在 Amazon 产品页面 URL 中 `/dp/` 后面的10位编码就是 ASIN。
    例如：`amazon.com/dp/B0D7Q5GY93` → ASIN 为 `B0D7Q5GY93`
    """)
    st.stop()

# ============================================================
# 数据抓取（带进度条）
# ============================================================
active_domain = st.session_state.get("domain", "us")
comp_count = st.session_state.get("comp_count", 4)
do_keywords = st.session_state.get("do_keywords", False)

# 抓取目标产品
if "product" not in st.session_state:
    with st.spinner(f"正在获取产品 {active_asin} ..."):
        product = search_product(active_asin, active_domain)
        if not product or not product.get("title"):
            st.error(f"无法获取 ASIN: {active_asin} 的产品信息。可能原因：\n"
                     f"- ASIN 不正确\n- API 服务不可用\n- 产品已下架\n\n"
                     f"请检查后重试。")
            st.session_state.pop("active_asin", None)
            st.stop()
        st.session_state["product"] = product

product = st.session_state["product"]

# 抓取竞品
if "competitors" not in st.session_state:
    progress_bar = st.progress(0, text="正在查找竞品...")

    def update_progress(msg):
        progress_bar.progress(0.3, text=msg)

    competitors = find_competitors(
        active_asin, active_domain, count=comp_count,
        progress_callback=update_progress,
        target_product=product,
    )
    progress_bar.progress(1.0, text=f"找到 {len(competitors)} 个竞品")
    st.session_state["competitors"] = competitors

competitors = st.session_state["competitors"]

# ============================================================
# 侧边栏 - 竞品管理（添加/删除）
# ============================================================
st.sidebar.divider()
st.sidebar.header("📋 竞品管理")

# 显示当前竞品列表，带删除按钮
if competitors:
    for i, c in enumerate(competitors):
        col_info, col_del = st.sidebar.columns([5, 1])
        label = c.get("brand", "") or c["asin"]
        col_info.caption(f"**{c['asin']}** {label}")
        if col_del.button("✕", key=f"del_comp_{c['asin']}"):
            st.session_state["competitors"].pop(i)
            st.session_state.get("comp_reviews", {}).pop(c["asin"], None)
            st.rerun()
else:
    st.sidebar.caption("暂无竞品")

# 添加新竞品
new_comp_asin = st.sidebar.text_input(
    "添加竞品 ASIN",
    value="",
    placeholder="输入竞品 ASIN",
    key="new_comp_asin_input",
)

if st.sidebar.button("➕ 添加竞品", use_container_width=True):
    new_asin_clean = new_comp_asin.strip().upper()
    if not new_asin_clean:
        st.sidebar.warning("请输入 ASIN")
    elif new_asin_clean == active_asin:
        st.sidebar.warning("不能添加本品作为竞品")
    elif any(c["asin"] == new_asin_clean for c in competitors):
        st.sidebar.warning(f"{new_asin_clean} 已在竞品列表中")
    else:
        with st.sidebar.status(f"正在获取 {new_asin_clean} ...", expanded=True) as status:
            comp = search_product(new_asin_clean, active_domain)
            if comp and comp.get("title"):
                comp["tier"] = "手动添加"
                comp["name"] = f"{comp.get('brand', '')} ({comp['asin']})"
                st.session_state["competitors"].append(comp)
                # 同步更新评价分析
                if "comp_reviews" in st.session_state:
                    st.session_state["comp_reviews"][new_asin_clean] = get_review_analysis(comp)
                status.update(label=f"已添加 {new_asin_clean}", state="complete")
                st.rerun()
            else:
                status.update(label=f"无法获取 {new_asin_clean}", state="error")

# 评价分析
if "reviews" not in st.session_state:
    st.session_state["reviews"] = get_review_analysis(product)

if "comp_reviews" not in st.session_state:
    comp_reviews = {}
    for c in competitors:
        comp_reviews[c["asin"]] = get_review_analysis(c)
    st.session_state["comp_reviews"] = comp_reviews

reviews = st.session_state["reviews"]
comp_reviews = st.session_state["comp_reviews"]

# 关键词排名（可选，耗时较长）
if do_keywords and "kw_data" not in st.session_state:
    with st.spinner("正在分析关键词排名（需搜索多页，请耐心等待）..."):
        kw_list = extract_keywords_from_title(product.get("title", ""))
        comp_asins = [c["asin"] for c in competitors]
        kw_data = get_keyword_rankings(kw_list, active_asin, comp_asins, active_domain)
        st.session_state["kw_data"] = kw_data

kw_data = st.session_state.get("kw_data", [])

# 所有产品列表（本品 + 竞品）
all_products = [{"name": f"★ 本品 ({product['asin']})", **product}] + competitors

# 货币符号
currency = product.get("currency", "USD")
CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
    "CAD": "CA$", "AUD": "A$", "INR": "₹", "SGD": "S$",
    "MXN": "MX$", "BRL": "R$", "AED": "AED",
}
currency_symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")

# ============================================================
# 产品概览卡片
# ============================================================
st.markdown("---")
st.subheader(f"🎯 {product['title']}")

metric_cols = st.columns(7)
metric_cols[0].metric("ASIN", product["asin"])
metric_cols[1].metric("售价", f"{currency_symbol}{product['price_daily']}" if product.get("price_daily") else "N/A")
metric_cols[2].metric("货币", currency)
metric_cols[3].metric("星级", f"⭐ {product['rating']}" if product.get("rating") else "N/A")
metric_cols[4].metric("评价数", f"{product['review_count']:,}" if product.get("review_count") else "0")
metric_cols[5].metric("BSR", f"#{product['bsr']:,}" if product.get("bsr") else "N/A")
metric_cols[6].metric("变体数", product.get("variant_count", 0))

# 标签和信息行
info_parts = []
if product.get("category_node"):
    info_parts.append(f"**类目：** {product['category_node']}")
if product.get("stock_status") and product["stock_status"] != "未知":
    info_parts.append(f"**库存：** {product['stock_status']}")
if product.get("best_seller_badge"):
    info_parts.append("**🏆 Best Seller**")
if product.get("amazon_choice_badge"):
    info_parts.append("**⭐ Amazon's Choice**")
if product.get("url"):
    info_parts.append(f"**链接：** [{product['url']}]({product['url']})")
if info_parts:
    st.info("　｜　".join(info_parts))

# BSR 详情
if product.get("bsr_details"):
    bsr_parts = [f"**#{d['rank']:,}** in {d['category']}" for d in product["bsr_details"]]
    st.caption("BSR 详情：" + "　|　".join(bsr_parts))

if not competitors:
    st.warning("未找到竞品数据。以下仅展示目标产品分析。")

# ============================================================
# 页面预览
# ============================================================
LANGUAGE_OPTIONS = {
    "en_US": "English",
    "zh_CN": "中文",
    "ja_JP": "日本語",
    "de_DE": "Deutsch",
    "fr_FR": "Français",
    "es_ES": "Español",
    "it_IT": "Italiano",
    "pt_BR": "Português",
    "hi_IN": "हिन्दी",
    "ar_AE": "العربية",
}

with st.expander("🖥️ 页面预览", expanded=False):
    prev_col1, prev_col2 = st.columns([1, 3])

    with prev_col1:
        preview_domain = st.selectbox(
            "预览站点",
            options=list(DOMAIN_LABELS.keys()),
            index=list(DOMAIN_LABELS.keys()).index(active_domain),
            format_func=lambda x: DOMAIN_LABELS[x],
            key="preview_domain",
        )
        preview_lang = st.selectbox(
            "语言",
            options=list(LANGUAGE_OPTIONS.keys()),
            format_func=lambda x: LANGUAGE_OPTIONS[x],
            key="preview_lang",
        )
        take_screenshot = st.button("📸 获取截图", use_container_width=True)

    with prev_col2:
        cache_key = f"screenshot_{active_asin}_{preview_domain}_{preview_lang}"
        if take_screenshot:
            with st.spinner("正在截取页面..."):
                img_b64 = fetch_screenshot(active_asin, preview_domain, preview_lang)
                if img_b64:
                    st.session_state[cache_key] = img_b64
                else:
                    st.error("截图失败，请稍后重试。")

        if cache_key in st.session_state:
            img_bytes = base64.b64decode(st.session_state[cache_key])
            st.image(img_bytes, caption=f"{DOMAIN_LABELS[preview_domain]} - {LANGUAGE_OPTIONS[preview_lang]}", use_container_width=True)
        else:
            st.info("点击「获取截图」预览 Amazon 产品页面。")

# ============================================================
# Tab 布局
# ============================================================
tabs = st.tabs([
    "一、基础信息",
    "二、流量与转化",
    "三、产品与运营",
    "四、合规与风险",
    "五、综合对比",
])

# ============================================================
# Tab 1: 基础信息
# ============================================================
with tabs[0]:
    st.subheader("基础信息：锚定竞品定位，快速分层对标")

    # 产品主图展示
    st.markdown("#### 产品主图")
    img_cols = st.columns(min(len(all_products), 5))
    for i, p in enumerate(all_products):
        with img_cols[i % len(img_cols)]:
            name = p.get("name", p["asin"])
            img_url = p.get("main_image", "")
            if img_url:
                st.image(img_url, caption=name, width=200)
            else:
                st.markdown(f"**{name}**\n\n_(无主图)_")

    st.divider()

    basic_rows = []
    for p in all_products:
        row = {
            "产品": p.get("name", p.get("title", p["asin"])),
            "层级": p.get("tier", "本品"),
            "ASIN": p["asin"],
            "品牌": p.get("brand", ""),
            "类目": p.get("category_node", ""),
            f"售价({currency})": p.get("price_daily"),
            "变体数": p.get("variant_count", 0),
            "变体维度": p.get("variant_dimension", ""),
        }
        # 显示徽章
        badges = []
        if p.get("best_seller_badge"):
            badges.append("🏆BS")
        if p.get("amazon_choice_badge"):
            badges.append("⭐AC")
        row["徽章"] = " ".join(badges)
        basic_rows.append(row)
    st.dataframe(pd.DataFrame(basic_rows), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 价格对比")
        price_rows = []
        for p in all_products:
            name = p.get("name", p["asin"])
            if p.get("price_daily"):
                price_rows.append({"产品": name, "类型": "当前售价", "价格": p["price_daily"]})
        if price_rows:
            fig = px.bar(pd.DataFrame(price_rows), x="产品", y="价格", color="类型",
                         barmode="group", title=f"售价对比 ({currency})")
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### 变体布局")
        var_rows = [{"产品": p.get("name", p["asin"]),
                     "变体维度": p.get("variant_dimension", "N/A"),
                     "变体数": p.get("variant_count", 0)}
                    for p in all_products if p.get("variant_count", 0) > 0]
        if var_rows:
            fig = px.bar(pd.DataFrame(var_rows), x="产品", y="变体数", color="变体维度",
                         title="变体数量 & 维度")
            st.plotly_chart(fig, use_container_width=True)

    # 五点描述对比
    st.markdown("#### 五点描述（Bullet Points）对比")

    max_bullets = max((len(p.get("bullet_points", [])) for p in all_products), default=0)
    if max_bullets > 0:
        bullet_table = {}
        for p in all_products:
            name = p.get("name", p["asin"])
            bullets = p.get("bullet_points", [])
            bullet_table[name] = {f"卖点{i+1}": (bullets[i][:120] + "..." if len(bullets[i]) > 120 else bullets[i]) if i < len(bullets) else "" for i in range(max_bullets)}

        bullet_df = pd.DataFrame(bullet_table).T
        bullet_df.index.name = "产品"
        st.dataframe(bullet_df, use_container_width=True)

        with st.expander("📋 查看完整 Bullet Points 原文"):
            for p in all_products:
                name = p.get("name", p["asin"])
                bullets = p.get("bullet_points", [])
                if bullets:
                    st.markdown(f"**{name}**")
                    for i, b in enumerate(bullets, 1):
                        st.markdown(f"{i}. {b}")
                    st.markdown("---")

    # 产品详情（Product Details）
    st.markdown("#### 产品详情（Product Details）")
    details_products = [p for p in all_products if p.get("product_details")]
    if details_products:
        for p in details_products:
            name = p.get("name", p["asin"])
            details = p["product_details"]
            with st.expander(f"📦 {name}", expanded=(p.get("asin") == active_asin)):
                detail_rows = [{"属性": k, "值": v} for k, v in details.items()]
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

# ============================================================
# Tab 2: 流量与转化
# ============================================================
with tabs[1]:
    st.subheader("流量与转化：拆解核心获客逻辑")

    # --- 关键词排名 ---
    st.markdown("### 🔍 关键词排名")
    if kw_data:
        kw_df = pd.DataFrame(kw_data)
        valid_kw = kw_df[kw_df["自然排名"].notna()]
        if not valid_kw.empty:
            fig = px.scatter(valid_kw, x="关键词", y="自然排名", color="产品",
                             symbol="是否广告",
                             title="关键词排名（越低越好）")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(kw_df, use_container_width=True, hide_index=True)
    else:
        if do_keywords:
            st.info("关键词排名数据暂未获取到。")
        else:
            st.info("勾选左侧「分析关键词排名」并重新搜索，可查看关键词排名数据。（耗时较长）")

    st.divider()

    # --- 广告 & 活动 ---
    st.markdown("### 📢 广告 & 促销活动")
    ad_rows = []
    for p in all_products:
        row = {
            "产品": p.get("name", p["asin"]),
            "优惠券": p.get("coupon", "无"),
            "库存状态": p.get("stock_status", "未知"),
        }
        badges = []
        if p.get("best_seller_badge"):
            badges.append("🏆 Best Seller")
        if p.get("amazon_choice_badge"):
            badges.append("⭐ Amazon's Choice")
        row["徽章"] = ", ".join(badges) if badges else "无"
        ad_rows.append(row)
    st.dataframe(pd.DataFrame(ad_rows), use_container_width=True, hide_index=True)

    st.divider()

    # --- 评价分析 ---
    st.markdown("### 🎯 评价分析")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 评价核心数据")
        review_rows = []
        for p in all_products:
            review_rows.append({
                "产品": p.get("name", p["asin"]),
                "星级": p.get("rating"),
                "评价数": p.get("review_count", 0),
            })
        review_df = pd.DataFrame(review_rows)
        st.dataframe(review_df, use_container_width=True, hide_index=True)

        valid_review = review_df[review_df["星级"].notna() & (review_df["评价数"] > 0)]
        if not valid_review.empty:
            fig = px.scatter(valid_review, x="评价数", y="星级", color="产品",
                             size="评价数", title="星级 vs 评价数量", size_max=40)
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### 评价内容分析（好评卖点 & 差评痛点）")

        # 本品评价
        if reviews.get("positive_keywords") or reviews.get("negative_keywords"):
            with st.expander(f"📝 本品 ({active_asin}) - {reviews.get('total', 0)} 条评价", expanded=True):
                rcol1, rcol2 = st.columns(2)
                with rcol1:
                    st.markdown(f"**好评高频词** ({reviews.get('positive_count', 0)} 条好评)")
                    for kw in reviews.get("positive_keywords", []):
                        st.markdown(f"- ✅ {kw}")
                with rcol2:
                    st.markdown(f"**差评高频词** ({reviews.get('negative_count', 0)} 条差评)")
                    for kw in reviews.get("negative_keywords", []):
                        st.markdown(f"- ⚠️ {kw}")
        else:
            st.info("API 未返回评论详情数据，评价内容分析暂不可用。")

        # 竞品评价
        for c in competitors[:3]:
            cr = comp_reviews.get(c["asin"], {})
            if cr.get("positive_keywords") or cr.get("negative_keywords"):
                with st.expander(f"📝 {c.get('name', c['asin'])} - {cr.get('total', 0)} 条评价"):
                    rcol1, rcol2 = st.columns(2)
                    with rcol1:
                        st.markdown("**好评高频词**")
                        for kw in cr.get("positive_keywords", []):
                            st.markdown(f"- ✅ {kw}")
                    with rcol2:
                        st.markdown("**差评高频词**")
                        for kw in cr.get("negative_keywords", []):
                            st.markdown(f"- ⚠️ {kw}")

# ============================================================
# Tab 3: 产品与运营
# ============================================================
with tabs[2]:
    st.subheader("产品与运营：供应链 & 运营策略分析")

    ops_rows = []
    for p in all_products:
        row = {
            "产品": p.get("name", p["asin"]),
            "品牌": p.get("brand", ""),
            "库存状态": p.get("stock_status", "未知"),
            "变体数": p.get("variant_count", 0),
            f"售价({currency})": p.get("price_daily"),
        }
        badges = []
        if p.get("best_seller_badge"):
            badges.append("🏆BS")
        if p.get("amazon_choice_badge"):
            badges.append("⭐AC")
        row["徽章"] = " ".join(badges) if badges else ""
        ops_rows.append(row)
    st.dataframe(pd.DataFrame(ops_rows), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### BSR 排名对比")
        bsr_rows = [
            {"产品": p.get("name", p["asin"]),
             "BSR": p.get("bsr") or 0,
             "类目": p.get("category_node", "")}
            for p in all_products
            if p.get("bsr")
        ]
        if bsr_rows:
            bsr_df = pd.DataFrame(bsr_rows)
            fig = px.bar(bsr_df, x="产品", y="BSR", color="类目",
                         title="BSR 排名对比（越低越好）")
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown("#### 价格 vs 星级 vs 评价数")
        scatter_rows = [
            {"产品": p.get("name", p["asin"]),
             "售价": p.get("price_daily", 0),
             "星级": p.get("rating", 0),
             "评价数": p.get("review_count", 0)}
            for p in all_products
            if p.get("price_daily") and p.get("rating")
        ]
        if scatter_rows:
            fig = px.scatter(pd.DataFrame(scatter_rows),
                             x="售价", y="星级", size="评价数", color="产品",
                             title="价格-星级-评价数关系图", size_max=50)
            st.plotly_chart(fig, use_container_width=True)

    # BSR 分类详情
    st.markdown("#### BSR 分类详情")
    for p in all_products:
        bsr_details = p.get("bsr_details", [])
        if bsr_details:
            name = p.get("name", p["asin"])
            with st.expander(f"📊 {name}"):
                bsr_detail_rows = [{"排名": f"#{d['rank']:,}", "类目": d["category"]}
                                   for d in bsr_details]
                st.dataframe(pd.DataFrame(bsr_detail_rows), use_container_width=True, hide_index=True)

# ============================================================
# Tab 4: 合规与风险
# ============================================================
with tabs[3]:
    st.subheader("合规与风险：评价风险 & 违规信号分析")

    for p in all_products:
        name = p.get("name", p["asin"])
        asin_key = p["asin"]
        rev = reviews if asin_key == active_asin else comp_reviews.get(asin_key, {})

        with st.expander(f"🔎 {name}", expanded=True):
            rcol1, rcol2, rcol3 = st.columns(3)
            with rcol1:
                st.metric("星级", p.get("rating", "N/A"))
            with rcol2:
                st.metric("评价数", p.get("review_count", 0))
            with rcol3:
                neg_count = rev.get("negative_count", 0)
                total = rev.get("total", 0)
                neg_pct = f"{neg_count}/{total}" if total else "N/A"
                st.metric("差评数/抽样总数", neg_pct)

            if rev.get("negative_keywords"):
                st.markdown("**差评高频问题（潜在产品硬伤）：**")
                st.markdown("、".join(f"「{kw}」" for kw in rev["negative_keywords"][:8]))

            # 五点描述
            bullets = p.get("bullet_points", [])
            if bullets:
                st.markdown("**五点描述（Bullet Points）：**")
                for i, b in enumerate(bullets, 1):
                    st.markdown(f"{i}. {b}")

            # 显示差评原文
            bad_reviews = [r for r in rev.get("reviews", [])
                           if r.get("stars") and r["stars"] <= 3]
            if bad_reviews:
                st.markdown("**低分评价原文：**")
                for r in bad_reviews[:3]:
                    stars_display = "⭐" * int(r.get("stars", 1))
                    st.markdown(
                        f"> {stars_display} **{r.get('title', '')}**\n> "
                        f"{r.get('body', '')[:200]}{'...' if len(r.get('body', '')) > 200 else ''}"
                    )

# ============================================================
# Tab 5: 综合对比
# ============================================================
with tabs[4]:
    st.subheader("综合对比：精准对标 + 差异化突破")

    st.markdown("""
    > **核心逻辑**：复制竞品有效策略 → 规避竞品漏洞 → 放大自身优势
    > → 实现「流量比对方多、转化比对方高、产品比对方优」
    """)

    summary_rows = []
    for p in all_products:
        rating = p.get("rating") or 0
        review_count = p.get("review_count") or 0
        bsr = p.get("bsr") or 999
        price = p.get("price_daily") or 0

        score = round(
            rating * 10
            + min(review_count / 100, 30)
            + max(0, (500 - bsr)) * 0.04
            , 1
        )

        summary_rows.append({
            "产品": p.get("name", p["asin"]),
            "层级": p.get("tier", "本品"),
            "品牌": p.get("brand", ""),
            f"价格({currency})": price,
            "星级": rating,
            "评价数": review_count,
            "BSR": f"#{bsr:,}" if bsr < 999 else "N/A",
            "徽章": ("🏆" if p.get("best_seller_badge") else "") + ("⭐" if p.get("amazon_choice_badge") else ""),
            "综合得分": score,
        })

    summary_df = pd.DataFrame(summary_rows).sort_values("综合得分", ascending=False)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    # 差异化机会
    st.markdown("#### 🎯 差异化机会发现")

    my_pos = set(reviews.get("positive_keywords", []))
    all_neg = set()
    for cr in comp_reviews.values():
        all_neg.update(cr.get("negative_keywords", []))

    if all_neg:
        st.success(
            "**竞品差评高频问题（= 我方差异化机会）：**\n\n"
            + "、".join(f"「{kw}」" for kw in sorted(all_neg)[:15])
        )

    my_neg = set(reviews.get("negative_keywords", []))
    if my_neg:
        st.warning(
            "**本品差评高频问题（需优化）：**\n\n"
            + "、".join(f"「{kw}」" for kw in sorted(my_neg)[:10])
        )

    if my_pos:
        st.info(
            "**本品好评高频词（核心优势）：**\n\n"
            + "、".join(f"「{kw}」" for kw in sorted(my_pos)[:10])
        )

    st.markdown("---")
    st.markdown(
        "**建议下一步：** 针对竞品差评痛点优化产品和listing，"
        "覆盖竞品未满足的长尾关键词，建立差异化壁垒。"
    )
