# -*- coding: utf-8 -*-
import os, json, httpx, yaml, re, time
from typing import Dict, List, Any
from loguru import logger
from langsmith import traceable
from app.prompts import PLAN_QUERIES_SYSTEM_PROMPT, EXTRACT_SYSTEM_PROMPT

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")

# ---------- helpers to shrink payload (מפחית TPM) ----------
def _clip(s: str, max_chars: int) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= max_chars else (s[:max_chars].rstrip() + " …")

def _shrink_panels(la_data: Dict, max_chars_per_panel: int = 1200) -> Dict:
    la = dict(la_data or {})
    panels = dict((la.get("panels") or {}))
    small = {}
    for k, v in panels.items():
        small[k] = _clip(v or "", max_chars_per_panel)
    la["panels"] = small
    if "notes" in la:
        la["notes"] = _clip(la["notes"], 1200)
    if "sources" in la:
        la["sources"] = la["sources"][:10]
    if "zoning" in la:
        for kk in list(la["zoning"].keys()):
            la["zoning"][kk] = _clip(la["zoning"][kk], 200)
    if "permits" in la:
        la["permits"] = la["permits"][:10]
    return la

def _shrink_notes(search_notes: List[Dict], top_k: int = 5, max_chars: int = 700) -> List[Dict]:
    notes = list(search_notes or [])
    notes = sorted(notes, key=lambda x: x.get("score", 0.0), reverse=True)[:top_k]
    small = []
    for n in notes:
        small.append({
            "title": _clip(n.get("title") or "", 200),
            "url": n.get("url") or "",
            "content": _clip(n.get("content") or n.get("raw_text") or "", max_chars),
            "score": n.get("score", 0.0),
        })
    return small
# -----------------------------------------------------------

def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _headers() -> dict:
    cfg = _load_config()
    provider = (cfg.get("integrations", {})
                  .get("llm", {})
                  .get("provider", "openrouter")).lower()

    if provider == "groq":
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise RuntimeError("Missing GROQ_API_KEY")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    # Default: OpenRouter
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing OPENROUTER_API_KEY")
    return {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": os.getenv("OR_REFERER", "http://localhost"),
        "X-Title": os.getenv("OR_TITLE", "Property Analysis Agentic System"),
        "Content-Type": "application/json",
    }

def _build_messages(system_prompt: str, address: str, la_data: Dict, search_notes: List[Dict]) -> List[Dict[str, Any]]:
    la_small = _shrink_panels(la_data, max_chars_per_panel=1200)
    notes_small = _shrink_notes(search_notes, top_k=5, max_chars=700)
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Address: {address}\n"
                f"LA data (condensed): {json.dumps(la_small, ensure_ascii=False)}\n"
                f"Search notes (top): {json.dumps(notes_small, ensure_ascii=False)}"
            ),
        },
    ]

def _make_timeout(total_seconds: int) -> httpx.Timeout:
    connect = min(20, max(5, total_seconds - 10))
    read    = min(120, max(10, total_seconds - 5))
    write   = 30
    pool    = 30
    try:
        return httpx.Timeout(total=total_seconds, connect=connect, read=read, write=write, pool=pool)
    except TypeError:
        return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)

@traceable(name="openrouter_llm")
def analyze_with_llm(address: str, la_data: Dict, search_notes: List[Dict], system_prompt: str) -> Dict[str, Any]:
    """
    מבקשת מה-LLM טקסט מסוכם בודד (Markdown), ללא JSON-mode.
    משתמשת בקיטום קלט כדי להפחית TPM, ומחזירה תמיד מילון עם formatted_text.
    """
    print("in analyze number 1111111111111111111111111111111")
    cfg = _load_config()
    llm_cfg = cfg["integrations"]["llm"]

    timeout = _make_timeout(int(llm_cfg.get("request_timeout_sec", 90)))
    messages = _build_messages(system_prompt, address, la_data, search_notes)

    # פלט סביר שמאפשר סיכום נקי אך לא מתנגש קשות עם TPM
    max_tokens = min(int(llm_cfg.get("max_tokens", 900)), 800)
    model = llm_cfg["model"]

    with httpx.Client(timeout=timeout, headers=_headers()) as client:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": llm_cfg.get("temperature", 0.2),
                "max_tokens": max_tokens,
                # חשוב: אין response_format כלל
            }
            print("in analyze number 222222222222222222222222")
            r = client.post(llm_cfg["base_url"], json=payload)
            if r.status_code != 200:
                logger.error(f"[LLM] HTTP {r.status_code} model={model} body={r.text[:600]}")
            r.raise_for_status()
            data = r.json()
            if "choices" in data and data["choices"]:
                print("in analyze number 3333333333333333333333")
                content = (data["choices"][0]["message"]["content"] or "").strip()
                print(content)
                return {
                    "formatted_text": content,   # הסיכום כמחרוזת אחת
                    "raw_llm_text": content,     # ← גלגל הצלה לדיבוג/קליינט
                    "sections": [],
                    "sources": [],
                    "warnings": [],
                }
            print("in analyze number 6666666666666")                    
        except httpx.HTTPStatusError as e:
            try:
                body = e.response.text[:600] if e.response is not None else ""
            except Exception:
                body = ""
            logger.error(f"[LLM] HTTP error model={model}: {e} body={body}")
        except Exception as e:
            logger.warning(f"[LLM] request failed (model={model}): {e}")

   
    # אם נכשל, נחזיר אינדיקציה — ה-UI יציג הודעה בהתאם
    print("in analyze number 444444444444444444444444")
    return {
        "formatted_text": "",
        "sections": [{"title": "Error", "content": "LLM request failed. See server logs."}],
        "sources": [],
        "warnings": ["LLM call failed."],
    }


# ---------- JSON helper for planner/extractor ----------
def _llm_json(messages: List[Dict[str, Any]], llm_cfg: dict) -> Dict[str, Any]:
    """
    קריאת JSON "חסכונית": מודל יחיד, ניסיון יחיד, max_tokens קטן.
    דוחפת לוגים, ומטפלת 413/429 בהחזרת שגיאה קריאה.
    """
    timeout = _make_timeout(int(llm_cfg.get("request_timeout_sec", 90)))
    model = llm_cfg["model"]
    max_tokens = 400  # פלט קטן לפלנר/איחוד

    with httpx.Client(timeout=timeout, headers=_headers()) as client:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": llm_cfg.get("temperature", 0.2),
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            # לוג: אורך הודעות כדי להבין עומס
            try:
                lens = [len(m.get("content","")) for m in messages if isinstance(m, dict)]
                logger.info(f"[LLM-JSON] model={model} max_tokens={max_tokens} msg_lens={lens}")
            except Exception:
                pass

            r = client.post(llm_cfg["base_url"], json=payload)
            if r.status_code != 200:
                logger.error(f"[LLM-JSON] HTTP {r.status_code} model={model} body={r.text[:600]}")
            r.raise_for_status()

            data = r.json()
            if data.get("choices"):
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)

        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            body = ""
            try:
                body = e.response.text[:600] if e.response is not None else ""
            except Exception:
                pass
            if status == 413:
                # קלט גדול מדי – נחזיר הודעה מלוחלק ולא נפיל את התהליך
                logger.error(f"[LLM-JSON] 413 Payload Too Large: {body}")
                raise RuntimeError("Input too large for JSON step (413). Reduce panels/notes before retry.")
            elif status == 429:
                logger.error(f"[LLM-JSON] 429 Rate Limit: {body}")
                raise RuntimeError("Rate limited in JSON step (429). Try again later or reduce input.")
            else:
                logger.error(f"[LLM-JSON] HTTP error {status}: {e} body={body}")
                raise

        except Exception as e:
            logger.error(f"[LLM-JSON] failed: {e}")
            raise RuntimeError("LLM JSON request failed") from e

def plan_queries(address: str, la_data: Dict) -> Dict:
    """
    מתכנן שאילתות Tavily על סמך חסרים. שולח קלט מצומצם כדי להימנע מ-413.
    """
    cfg = _load_config(); llm_cfg = cfg["integrations"]["llm"]
    # מצמצמים אגרסיבי לפלנר
    la_small = _shrink_panels(la_data, max_chars_per_panel=600)
    # מסירים שדות לא קריטיים אם קיימים
    la_small.pop("permits", None)
    la_small.pop("notes", None)

    messages = [
        {"role": "system", "content": PLAN_QUERIES_SYSTEM_PROMPT},
        {"role": "user", "content": f"ADDRESS: {address}\nLA_DATA:\n{json.dumps(la_small, ensure_ascii=False)}"}
    ]
    try:
        out = _llm_json(messages, llm_cfg)
        return out if isinstance(out, dict) else {"queries": [], "include_domains": [], "stop_condition": "error"}
    except Exception as e:
        logger.warning(f"[plan_queries] failed: {e}")
        return {"queries": [], "include_domains": [], "stop_condition": "error"}

def _pack_notes(search_notes: List[Dict]) -> str:
    """Compact string from Tavily results for the extractor."""
    lines = []
    for i, r in enumerate(search_notes, 1):
        title = r.get("title") or r.get("query") or f"Note {i}"
        url   = r.get("url") or ""
        content = r.get("content") or r.get("raw_text") or ""
        score = r.get("score")
        lines.append(f"[{i}] {title} :: {url} :: score={score}\n{content}\n")
    return "\n---\n".join(lines)

def extract_merge(address: str, la_data: Dict, search_notes: List[Dict]) -> Dict:
    """
    מאחד עובדות נתמכות. שולח לגרעין ה-LLM רק תמצית קצרה (Top-3 הערות, פאנלים מקוצרים).
    """
    cfg = _load_config(); llm_cfg = cfg["integrations"]["llm"]

    la_small = _shrink_panels(la_data, max_chars_per_panel=600)
    notes_small = _shrink_notes(search_notes, top_k=3, max_chars=400)

    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"ADDRESS: {address}\n"
                f"NOTES_MINI:\n{json.dumps(notes_small, ensure_ascii=False)}\n"
                f"CURRENT_MINI:\n{json.dumps(la_small, ensure_ascii=False)}"
            )
        }
    ]
    try:
        out = _llm_json(messages, llm_cfg)
    except Exception as e:
        logger.warning(f"[extract_merge] failed: {e}")
        return la_data  # לא נכשיל את כל הזרימה

    patch = (out or {}).get("patch", {}) if isinstance(out, dict) else {}
    merged = dict(la_data)
    if "zoning" in patch:
        merged.setdefault("zoning", {})
        for k, v in (patch["zoning"] or {}).items():
            merged["zoning"][k] = v or merged["zoning"].get(k)
    if "overlays" in patch and patch["overlays"]:
        merged["overlays"] = sorted(set((merged.get("overlays") or []) + patch["overlays"]))
    if "permits" in patch and patch["permits"]:
        merged["permits"] = (merged.get("permits") or []) + patch["permits"]
    if "notes" in patch and patch["notes"]:
        merged["notes"] = ((merged.get("notes") or "") + "\n" + patch["notes"]).strip()
    merged["sources"] = (merged.get("sources") or []) + (out.get("sources") or [])
    return merged

