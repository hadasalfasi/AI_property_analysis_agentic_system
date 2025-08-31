# -*- coding: utf-8 -*-
from typing import Dict, List, Optional
from loguru import logger
from langsmith import traceable

from playwright.sync_api import sync_playwright, Page, Locator
from bs4 import BeautifulSoup
import re
import os
import time

OFFICIAL_SOURCES = [
    "https://planning.lacity.gov",
    "https://zimas.lacity.org",
    "https://www.ladbs.org",
]

# --- diagnostics printing limits ---
PANEL_PRINT_MAX_CHARS = int(os.getenv("PANEL_PRINT_MAX_CHARS", "4000"))
PANEL_PRINT_MAX_LINES = int(os.getenv("PANEL_PRINT_MAX_LINES", "120"))

def _print_panel(title: str, content: Optional[str]) -> None:
    print(f"\n===== PANEL: {title} =====")
    if not content:
        print("[EMPTY]")
        print("===== END PANEL =====\n")
        return
    text = (content or "").strip()
    if len(text) > PANEL_PRINT_MAX_CHARS:
        text = text[:PANEL_PRINT_MAX_CHARS] + "\n... [truncated]"
    lines = text.splitlines()
    if len(lines) > PANEL_PRINT_MAX_LINES:
        text = "\n".join(lines[:PANEL_PRINT_MAX_LINES]) + "\n... [truncated]"
    print(text)
    print("===== END PANEL =====\n")

def _norm(s: str) -> str:
    s = (s or "").replace("\u00A0", " ")
    s = " ".join(s.split())
    s = re.sub(r"\s*/\s*", "/", s)
    return s.strip()

def _list_available_tabs(page: Page) -> List[str]:
    texts = page.locator("#divLeftInformationBar td.DataTabs").locator("a, span, div").all_inner_texts()
    cleaned = []
    for t in texts:
        s = t.replace("\u00A0", " ")
        s = " ".join(s.split())
        if s:
            cleaned.append(s)
    logger.info(f"[TABS] {cleaned}")
    print(f"[TABS] {cleaned}")
    return cleaned

TAB_ALIASES = {
    "Address / Legal": [
        "Address / Legal", "Address/Legal", "Address /Legal", "Address/ Legal", "Address & Legal"
    ],
    "Planning and Zoning": ["Planning and Zoning", "Planning & Zoning"],
    "Assessor": ["Assessor"],
    "Case Numbers": ["Case Numbers", "Planning Case Numbers", "Cases"],
    "Citywide / Code Amendment Cases": [
        "Citywide / Code Amendment Cases", "Citywide/Code Amendment Cases",
        "Citywide Code Amendment Cases", "Citywide – Code Amendment Cases",
    ],
    "Housing": ["Housing", "Housing Dept", "Housing (HCD)"],
}

def _find_tab_locator(page: Page, canonical_name: str) -> Optional[Locator]:
    root = page.locator("#divLeftInformationBar")
    aliases = TAB_ALIASES.get(canonical_name, [canonical_name])

    patterns = []
    for alias in aliases:
        pat = re.escape(_norm(alias))
        pat = pat.replace("/", r"\s*/\s*")
        patterns.append(re.compile(rf"^{pat}$", re.IGNORECASE))

    for rx in patterns:
        try:
            loc = root.get_by_role("link", name=rx).first
            if loc.count() > 0:
                return loc
        except Exception:
            pass
        containers = root.locator("td.DataTabs").locator("a, span, div")
        n = containers.count()
        for i in range(n):
            el = containers.nth(i)
            try:
                txt = el.inner_text(timeout=200)
            except Exception:
                continue
            if rx.match(_norm(txt) or ""):
                return el
    return None

def _table_to_lines(table: BeautifulSoup) -> List[str]:
    out: List[str] = []
    rows = table.find_all("tr")
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) >= 2:
            label = _norm(tds[0].get_text(" ", strip=True))
            value = _norm(tds[1].get_text(" ", strip=True))
            if label or value:
                out.append(f"{label}: {value}")
        else:
            txt = _norm(tr.get_text(" ", strip=True))
            if txt:
                out.append(txt)
    return out

def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    tables = soup.find_all("table")
    if tables:
        lines: List[str] = []
        for tb in tables:
            lines.extend(_table_to_lines(tb))
        return "\n".join(lines)
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _clean_panel_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if "<" in v and ">" in v:
        try:
            return _html_to_text(v)
        except Exception:
            return _norm(v)
    return _norm(v)

def _open_tab_and_get_content(page: Page, tab_text: str, timeout: int = 60000) -> Optional[str]:
    t0 = time.time()
    anchor = _find_tab_locator(page, tab_text)
    if anchor is None or anchor.count() == 0:
        avail = _list_available_tabs(page)
        logger.warning(f"Tab not found: {tab_text}; available: {avail}; aliases: {TAB_ALIASES.get(tab_text)}")
        print(f"[WARN] Tab not found: {tab_text}; available: {avail}; aliases: {TAB_ALIASES.get(tab_text)}")
        return None
    try:
        anchor.scroll_into_view_if_needed()
    except Exception:
        pass
    icon = anchor.locator("img").first
    try:
        src = icon.get_attribute("src") or ""
    except Exception:
        src = ""
    if "twist_closed" in src:
        anchor.click()
        page.wait_for_timeout(200)
    else:
        try:
            anchor.click()
            page.wait_for_timeout(120)
        except Exception:
            pass

    tab_td = anchor.locator("xpath=ancestor::td[contains(@class,'DataTabs')]").first
    tab_tr = tab_td.locator("xpath=ancestor::tr[1]").first
    content_tr = tab_tr.locator("xpath=following-sibling::tr[not(td[contains(@class,'DataTabs')])]").first

    if content_tr.count() == 0:
        logger.warning(f"No content row found for tab: {tab_text}")
        print(f"[WARN] No content row found for tab: {tab_text}")
        return None

    try:
        raw_text = (content_tr.inner_text(timeout=timeout) or "").strip()
        if raw_text:
            dt = time.time() - t0
            logger.info(f"[PANEL] {tab_text}: extracted=True in {dt:.2f}s")
            print(f"[PANEL] {tab_text}: OK in {dt:.2f}s")
            return _clean_panel_text(raw_text)

        raw_html = (content_tr.inner_html(timeout=timeout) or "").strip()
        dt = time.time() - t0
        logger.info(f"[PANEL] {tab_text}: extracted={'True' if raw_html else 'False'} in {dt:.2f}s | preview: {raw_html[:160] if raw_html else ''}")
        print(f"[PANEL] {tab_text}: {'OK' if raw_html else 'EMPTY/None'} in {dt:.2f}s")
        return _clean_panel_text(raw_html) if raw_html else None

    except Exception as e:
        logger.warning(f"Failed extracting content for tab {tab_text}: {e}")
        print(f"[WARN] Failed extracting content for tab {tab_text}: {e}")
        return None

@traceable(name="la_scrape")
def scrape_la_city_planning(street_name: str, house_number: str) -> Dict:
    """
    ZIMAS scrape by street/house number.
    Tavily queries are handled elsewhere (planner or user-supplied).
    """
    address = f"{house_number} {street_name}, Los Angeles, CA"
    panels: Dict[str, Optional[str]] = {
        "Address / Legal": None,
        "Planning and Zoning": None,
        "Assessor": None,
        "Case Numbers": None,
        "Citywide / Code Amendment Cases": None,
        "Housing": None,
    }

    sources: List[Dict] = []
    notes_parts: List[str] = []

    # ZIMAS
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://zimas.lacity.org/", wait_until="domcontentloaded")

        page.click("#btn")
        page.fill("#txtStreetName", street_name)
        page.fill("#txtHouseNumber", house_number)
        page.click("#btnSearchGo")

        page.wait_for_selector("#divLeftInformationBar", timeout=60000)

        for tab_name in list(panels.keys()):
            content = _open_tab_and_get_content(page, tab_name)
            panels[tab_name] = content

        sources.append({"name": "ZIMAS", "url": "https://zimas.lacity.org/"})
        browser.close()

    return {
        "address": address,
        "panels": panels,
        "tavily_results": [],  # kept for compatibility; user/agent search happens later
        "notes": "\n".join(notes_parts),
        "sources": sources,
    }
