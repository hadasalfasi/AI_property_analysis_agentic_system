
# חוזר טוב אבל כגוש ולא שורה שורה השארתי התכתבות אחרונה עם גיפיטי

from typing import Dict, List, Optional
from loguru import logger
from langsmith import traceable
from app.search_integration import tavily_search

from playwright.sync_api import sync_playwright, Page, Locator
from bs4 import BeautifulSoup  # <<< חשוב: המרת HTML לטקסט
import re
import os
import time

OFFICIAL_SOURCES = [
    "https://planning.lacity.gov",
    "https://zimas.lacity.org",
    "https://www.ladbs.org",
]

# ========= כלי עזר להדפסות =========
# כמה תווים/שורות להדפיס לכל טאב (ניתן לשנות ע"י משתני סביבה)
PANEL_PRINT_MAX_CHARS = int(os.getenv("PANEL_PRINT_MAX_CHARS", "4000"))
PANEL_PRINT_MAX_LINES = int(os.getenv("PANEL_PRINT_MAX_LINES", "120"))

def _print_panel(title: str, content: Optional[str]) -> None:
    print(f"\n===== PANEL: {title} =====")
    if not content:
        print("[EMPTY]")
        print("===== END PANEL =====\n")
        return
    # הדפסה עם הגבלה ידידותית — גם לפי תווים וגם לפי שורות
    text = (content or "").strip()
    if len(text) > PANEL_PRINT_MAX_CHARS:
        text = text[:PANEL_PRINT_MAX_CHARS] + "\n... [truncated]"
    lines = text.splitlines()
    if len(lines) > PANEL_PRINT_MAX_LINES:
        text = "\n".join(lines[:PANEL_PRINT_MAX_LINES]) + "\n... [truncated]"
    print(text)
    print("===== END PANEL =====\n")

# ========= נרמול טקסטים =========
def _norm(s: str) -> str:
    s = (s or "").replace("\u00A0", " ")
    s = " ".join(s.split())
    s = re.sub(r"\s*/\s*", "/", s)
    return s.strip()

# ========= דיאגנוסטיקה: רשימת טאבים =========
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

# ========= אליאסים =========
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

    # ניסיון לפי role=link
    for rx in patterns:
        try:
            loc = root.get_by_role("link", name=rx).first
            if loc.count() > 0:
                return loc
        except Exception:
            pass

        # Fallback: חיפוש ידני
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

# ========= המרות HTML -> טקסט נקי =========

def _table_to_lines(table: BeautifulSoup) -> List[str]:
    """
    ממיר טבלת HTML לשורות 'Label: Value'. עובד לטאב Address / Legal.
    """
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
    """
    ממיר HTML לטקסט קריא עם שורות חדשות.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # להמיר <br> לשורה חדשה
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # אם יש טבלאות — לפרק שורה-שורה
    tables = soup.find_all("table")
    if tables:
        lines: List[str] = []
        for tb in tables:
            lines.extend(_table_to_lines(tb))
        return "\n".join(lines)

    # אחרת — נשתמש ב־get_text עם מפרידי שורות
    text = soup.get_text("\n", strip=True)
    # ניקוי רווחים כפולים ושבירות מיותרות
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _clean_panel_text(value: Optional[str]) -> Optional[str]:
    """
    מקבלת מחרוזת (טקסט או HTML) ומחזירה טקסט נקי עם שורות מסודרות.
    """
    if not value:
        return None
    v = value.strip()
    if "<" in v and ">" in v:
        try:
            return _html_to_text(v)
        except Exception:
            return _norm(v)
    return _norm(v)


# ========= שליפת תוכן טאב =========

def _open_tab_and_get_content(page: Page, tab_text: str, timeout: int = 60000) -> Optional[str]:
    """
    מחזיר תמיד טקסט נקי (אם אפשר).
    קודם מנסה inner_text; אם ריק — מנסה inner_html ואז ממיר ל־text.
    """
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

    # לפתוח אם סגור (twist_closed) או "לנגוע" בקליק
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
        # 1) ננסה טקסט נקי
        raw_text = (content_tr.inner_text(timeout=timeout) or "").strip()
        if raw_text:
            dt = time.time() - t0
            logger.info(f"[PANEL] {tab_text}: extracted=True in {dt:.2f}s")
            print(f"[PANEL] {tab_text}: OK in {dt:.2f}s")
            return _clean_panel_text(raw_text)

        # 2) אם אין טקסט — ננסה HTML ונמיר לטקסט נקי
        raw_html = (content_tr.inner_html(timeout=timeout) or "").strip()
        dt = time.time() - t0
        logger.info(f"[PANEL] {tab_text}: extracted={'True' if raw_html else 'False'} in {dt:.2f}s | preview: {raw_html[:160] if raw_html else ''}")
        print(f"[PANEL] {tab_text}: {'OK' if raw_html else 'EMPTY/None'} in {dt:.2f}s")
        return _clean_panel_text(raw_html) if raw_html else None

    except Exception as e:
        logger.warning(f"Failed extracting content for tab {tab_text}: {e}")
        print(f"[WARN] Failed extracting content for tab {tab_text}: {e}")
        return None

# ========= נקודת הכניסה לשאיבה =========

@traceable(name="la_scrape")
def scrape_la_city_planning(street_name: str, house_number: str) -> Dict:
    """
    שליפה מזימאס לפי רחוב ומספר:
    - פותח את העמוד, מאשר תנאים, מזין רחוב+מספר, ומחכה לסיידבר.
    - שולף את הטאבים שביקשת ומחזיר/מדפיס טקסט נקי (ללא תגיות).
    בגרסה זו ויתרנו על "Zoning בסיסי" (Base Zone/Height/FAR).
    """
    address = f"{house_number} {street_name}, Los Angeles, CA"
    logger.info(f"Scraping official sources for: {address}")
    print(f"[INFO] Scraping: {address}")

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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        logger.info("Navigating to ZIMAS page...")
        print("[INFO] Navigating to ZIMAS...")
        page.goto("https://zimas.lacity.org/", wait_until="domcontentloaded")

        # קבלת תנאים
        page.wait_for_selector("#btn", timeout=60000)
        page.click("#btn")
        print("[INFO] Accepted terms.]")

        # מילוי חיפוש
        logger.info(f"Filling search fields: street={street_name}, number={house_number}")
        print(f"[INFO] Fill search: street='{street_name}', number='{house_number}'")
        page.wait_for_selector("#txtStreetName", timeout=60000)
        page.fill("#txtStreetName", street_name)
        page.wait_for_selector("#txtHouseNumber", timeout=60000)
        page.fill("#txtHouseNumber", house_number)
        page.wait_for_selector("#btnSearchGo", timeout=60000)
        page.click("#btnSearchGo")
        print("[INFO] Clicked GO button.")

        # להמתין לסיידבר
        t0 = time.time()
        page.wait_for_selector("#divLeftInformationBar", timeout=60000)
        print(f"[TIMING] Initial nav + search ready in {time.time() - t0:.2f}s")

        # דיאגנוסטיקה: אילו טאבים יש בפועל
        _list_available_tabs(page)

        # שליפת הטאבים והדפסה מלאה (נקיה)
        logger.info("Extracting requested sidebar panels...")
        print("[INFO] Extracting panels...")
        for tab_name in list(panels.keys()):
            try:
                content = _open_tab_and_get_content(page, tab_name)
                panels[tab_name] = content  # כבר טקסט נקי!
                logger.info(f"Panel '{tab_name}' extracted: {bool(content)}")
                _print_panel(tab_name, content)
            except Exception as e:
                logger.warning(f"Failed extracting panel '{tab_name}': {e}")
                print(f"[WARN] Failed extracting panel '{tab_name}': {e}")
                panels[tab_name] = None

        sources.append({"name": "ZIMAS", "url": "https://zimas.lacity.org/"})
        browser.close()

    # אופציונלי: הקשר חיצוני
    try:
        logger.info("Performing Tavily search for additional context.")
        print("[INFO] Tavily: searching for extra context…")
        search_results = tavily_search(address) or []
        print(f"[INFO] Tavily results: {len(search_results)}")
        for idx, result in enumerate(search_results[:6], 1):
            if result.get("title") and result.get("content"):
                clip = (result["content"] or "").strip()
                if len(clip) > 300:
                    clip = clip[:300] + "…"
                print(f"[NOTE {idx}] {clip}")
                notes_parts.append(result["content"])
        sources.append({"name": "TAVILY", "url": "https://tavily.com"})
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        print(f"[WARN] Tavily search failed: {e}")

    print("[TIMING] scrape_la_city_planning done.")
    logger.info("Returning scraped data.")
    return {
        "address": address,
        "panels": panels,  # << כאן כל הטקסטים שחולצו לכל טאב — כבר נקיים מ־HTML
        "notes": "\n".join(notes_parts) or "Official scrape completed; panel values may be partial.",
        "sources": sources,
    }

