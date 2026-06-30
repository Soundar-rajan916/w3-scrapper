import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import json
import logging
import random
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel

logger = logging.getLogger("main")
logging.basicConfig(level=logging.INFO)

playwright_instance = None
browser = None
tutorial_catalog = None

CATALOG_URL = "https://www.w3schools.com/"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global playwright_instance, browser
    playwright_instance = await async_playwright().start()
    browser = await playwright_instance.chromium.launch(headless=True)
    logger.info("Chromium browser started")
    yield
    await browser.close()
    await playwright_instance.stop()
    logger.info("Chromium browser stopped")


app = FastAPI(
    title="W3Schools Scraper",
    description="Scrapes full W3Schools tutorials using Playwright",
    version="1.0.0",
    lifespan=lifespan,
)


class PageData(BaseModel):
    page_title: str
    url: str
    headings: list[str]
    paragraphs: list[str]
    code_examples: list[str]


class TopicItem(BaseModel):
    title: str
    url: str


class LanguageItem(BaseModel):
    slug: str
    title: str
    start_url: str
    base_url: str


class TopicsResult(BaseModel):
    language: str
    total_pages: int
    topics: list[TopicItem]


class LanguagesResult(BaseModel):
    total_languages: int
    languages: list[LanguageItem]


class ScrapeResult(BaseModel):
    language: str
    total_pages: int
    pages: list[PageData]


async def fetch_html(url: str) -> str:
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("div#main", timeout=10000)
        except Exception:
            pass
        html = await page.content()
        return html
    finally:
        await page.close()


def build_slug(path: str) -> str:
    parts = [part for part in path.strip("/").split("/")[:-1] if part]
    return "-".join(parts)


def build_base_url(start_url: str) -> str:
    return start_url.rsplit("/", 1)[0] + "/"


def is_tutorial_root(href: str, title: str) -> bool:
    lower_title = title.lower()
    if "tutorial" not in lower_title:
        return False

    parsed = urlparse(urljoin(CATALOG_URL, href))
    if parsed.netloc != "www.w3schools.com":
        return False

    path = parsed.path.lower()
    if path.startswith(("/videos/", "/tryit/", "/references/", "/exercises/", "/practice/", "/academy/", "/spaces/")):
        return False

    return path.endswith("/default.asp") or path.endswith("/index.php")


async def get_tutorial_catalog() -> dict[str, LanguageItem]:
    global tutorial_catalog
    if tutorial_catalog is not None:
        return tutorial_catalog

    html = await fetch_html(CATALOG_URL)
    soup = BeautifulSoup(html, "lxml")

    catalog: dict[str, LanguageItem] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        title = anchor.get("title", "").strip() or anchor.get_text(strip=True)
        if not href or not title or not is_tutorial_root(href, title):
            continue

        full_url = urljoin(CATALOG_URL, href)
        path = urlparse(full_url).path
        slug = build_slug(path)
        if not slug or slug in catalog:
            continue

        display_title = title.replace(" Tutorial", "").strip()
        catalog[slug] = LanguageItem(
            slug=slug,
            title=display_title,
            start_url=full_url,
            base_url=build_base_url(full_url),
        )

    if not catalog:
        raise RuntimeError("Failed to discover W3Schools tutorials")

    tutorial_catalog = dict(sorted(catalog.items()))
    return tutorial_catalog


async def get_language_item(lang: str) -> LanguageItem:
    catalog = await get_tutorial_catalog()
    item = catalog.get(lang.lower())
    if not item:
        supported = ", ".join(sorted(catalog))
        raise HTTPException(400, f"Unsupported language '{lang}'. Use one of: {supported}")
    return item


async def get_sidebar_topics(language: LanguageItem) -> list[TopicItem]:
    html = await fetch_html(language.start_url)
    soup = BeautifulSoup(html, "lxml")

    sidebar = (
        soup.find("div", id="leftmenuinnerinner")
        or soup.find("div", id="leftmenu")
        or soup.find("div", class_="sidenav")
    )

    topics = []
    if sidebar:
        for a in sidebar.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http"):
                full_url = href
            else:
                full_url = urljoin(language.base_url, href)
            title = a.get_text(strip=True)
            if title and "w3schools.com" in full_url:
                topics.append(TopicItem(title=title, url=full_url))

    seen = set()
    unique = []
    for topic in topics:
        if topic.url not in seen:
            seen.add(topic.url)
            unique.append(topic)

    return unique


async def scrape_page(url: str) -> PageData | None:
    try:
        html = await fetch_html(url)
        soup = BeautifulSoup(html, "lxml")
        main = soup.find("div", id="main")
        if not main:
            return None

        headings = [
            h.get_text(strip=True)
            for h in main.find_all(["h1", "h2", "h3"])
            if h.get_text(strip=True)
        ]
        paragraphs = [
            p.get_text(strip=True)
            for p in main.find_all("p")
            if p.get_text(strip=True)
        ]
        code_examples = [
            c.get_text(strip=True)
            for c in main.find_all(
                ["pre", "code", "div"],
                class_=lambda x: x and ("w3-code" in x or "w3-codespan" in x),
            )
            if c.get_text(strip=True)
        ]

        title = headings[0] if headings else url.split("/")[-1]

        return PageData(
            page_title=title,
            url=url,
            headings=headings,
            paragraphs=paragraphs,
            code_examples=code_examples,
        )
    except Exception as e:
        logger.warning(f"Failed to scrape {url}: {e}")
        return None


async def scrape_language(lang: str, limit: int = None) -> ScrapeResult:
    language = await get_language_item(lang)
    topics = await get_sidebar_topics(language)
    if limit:
        topics = topics[:limit]

    pages = []
    for i, topic in enumerate(topics):
        logger.info(f"Scraping [{i + 1}/{len(topics)}] {topic.url}")
        page_data = await scrape_page(topic.url)
        if page_data:
            pages.append(page_data)
        await asyncio.sleep(random.uniform(1.0, 2.0))

    return ScrapeResult(language=language.slug, total_pages=len(pages), pages=pages)


@app.get("/")
async def root():
    return {
        "message": "W3Schools Scraper API",
        "endpoints": {
            "GET /languages": "List all discovered W3Schools tutorial languages",
            "GET /scrape/{lang}": "Scrape all pages for one discovered language. Optional: ?limit=N",
            "GET /scrape/{lang}/topics": "List all tutorial page URLs (fast, no page visits)",
            "GET /scrape/{lang}/first": "Scrape only the first page (quick test)",
            "GET /scrape/{lang}/page": "Scrape one page: ?url=https://...",
            "GET /scrape/all": "Scrape all discovered languages",
            "GET /export/{lang}": "Scrape and save to {lang}_full.json",
        },
    }


@app.get("/languages", response_model=LanguagesResult)
async def get_languages():
    catalog = await get_tutorial_catalog()
    languages = list(catalog.values())
    return LanguagesResult(total_languages=len(languages), languages=languages)


@app.get("/scrape/{lang}/topics", response_model=TopicsResult)
async def get_topics(lang: str):
    language = await get_language_item(lang)
    topics = await get_sidebar_topics(language)
    return TopicsResult(language=language.slug, total_pages=len(topics), topics=topics)


@app.get("/scrape/{lang}/first", response_model=PageData)
async def scrape_first(lang: str):
    language = await get_language_item(lang)
    topics = await get_sidebar_topics(language)
    if not topics:
        raise HTTPException(404, "No pages found in sidebar")
    result = await scrape_page(topics[0].url)
    if not result:
        raise HTTPException(503, "Failed to scrape first page")
    return result


@app.get("/scrape/{lang}/page", response_model=PageData)
async def scrape_single(lang: str, url: str):
    await get_language_item(lang)
    result = await scrape_page(url)
    if not result:
        raise HTTPException(503, f"Failed to scrape {url}")
    return result


@app.get("/scrape/all")
async def scrape_all():
    results = {}
    catalog = await get_tutorial_catalog()
    for lang in catalog:
        try:
            result = await scrape_language(lang)
            results[lang] = result.model_dump()
        except Exception as e:
            results[lang] = {"error": str(e)}
    return results


@app.get("/scrape/{lang}", response_model=ScrapeResult)
async def scrape_lang(lang: str, limit: int = None):
    try:
        return await scrape_language(lang, limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scrape failed for {lang}: {e}")
        raise HTTPException(503, f"Scraping failed: {str(e)}")


@app.get("/export/{lang}")
async def export_lang(lang: str, limit: int = None):
    language = await get_language_item(lang)
    result = await scrape_language(language.slug, limit)
    filename = f"{language.slug}_full.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2, ensure_ascii=False)
    return {
        "message": f"Saved to {filename}",
        "total_pages": result.total_pages,
        "file": filename,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
