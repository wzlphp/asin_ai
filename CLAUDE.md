# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**asin_ai** — 亚马逊竞品分析工具。输入 ASIN，通过 Playwright 无头浏览器实时爬取 Amazon 产品数据，自动查找竞品，四大维度深度分析。

需求文档：`亚马逊竞品分析要点.docx`（中文）

## Build & Run

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app.py
# 或直接双击 run.bat (Windows)
```

访问 http://localhost:8501

## Architecture

```
app.py           Streamlit UI（ASIN输入→5个Tab分析展示）
data_service.py  数据服务层（search_product / find_competitors / get_review_analysis / get_keyword_rankings）
scraper.py       爬虫层（Playwright 无头浏览器抓取 Amazon 页面 + BeautifulSoup 解析）
```

**数据流：** `app.py` → `data_service.py` → `scraper.py` → Amazon 网页

- `scraper.py`：浏览器单例管理、反检测注入、页面抓取、HTML 解析（产品页/搜索结果页/评价页）
- `data_service.py`：组装业务逻辑（竞品发现策略：related_asins + 关键词搜索补充；评价分析：从产品页提取评价避免登录限制）
- `app.py`：Streamlit session_state 缓存已抓数据，避免重复请求

## Tech Stack

Python 3.11+ / Streamlit / Playwright / BeautifulSoup / Pandas / Plotly

## Notes

- 爬虫使用 Playwright headless Chrome 绕过 Amazon 反爬验证（captcha）
- 评价从产品页直接提取（约8-10条），评价详情页需要登录
- 价格受服务器 IP 地区影响，可能显示为 HKD 等非 USD 货币
- BSR 历史数据需要 Keepa 等第三方 API，当前仅获取实时 BSR
- 支持 Amazon 多站点：us / uk / de / jp
