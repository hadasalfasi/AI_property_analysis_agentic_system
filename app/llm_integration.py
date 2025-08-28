import os, json, httpx, yaml
from typing import Dict, List
from loguru import logger
from langsmith import traceable
from app.prompts import PLAN_QUERIES_SYSTEM_PROMPT, EXTRACT_SYSTEM_PROMPT
CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")

def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# def _headers():
#     key = os.getenv("OPENROUTER_API_KEY", "").strip()
#     if not key:
#         raise RuntimeError("Missing OPENROUTER_API_KEY")
#     return {
#         "Authorization": f"Bearer {key}",
#         "HTTP-Referer": os.getenv("OR_REFERER", "http://localhost"),
#         "X-Title": os.getenv("OR_TITLE", "Property Analysis Agentic System"),
#         "Content-Type": "application/json",
#     }
def _headers():
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

    # ברירת מחדל: OpenRouter (כמו שהיה)
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing OPENROUTER_API_KEY")
    return {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": os.getenv("OR_REFERER", "http://localhost"),
        "X-Title": os.getenv("OR_TITLE", "Property Analysis Agentic System"),
        "Content-Type": "application/json",
    }


def _build_messages(system_prompt: str, address: str, la_data: Dict, search_notes: List[Dict]) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Address: {address}\n"
                f"LA data: {json.dumps(la_data)}\n"
                f"Search notes: {json.dumps(search_notes)}"
            ),
        },
    ]

def _make_timeout(total_seconds: int) -> httpx.Timeout:
    """
    יוצר Timeout שתואם גם לגרסאות httpx ישנות (שאין בהן הפרמטר total).
    """
    connect = min(20, max(5, total_seconds - 10))
    read    = min(120, max(10, total_seconds - 5))
    write   = 30
    pool    = 30
    try:
        # גרסאות חדשות של httpx
        return httpx.Timeout(total=total_seconds, connect=connect, read=read, write=write, pool=pool)
    except TypeError:
        # תאימות לאחור (ללא total)
        return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)

@traceable(name="openrouter_llm")
def analyze_with_llm(address: str, la_data: Dict, search_notes: List[Dict], system_prompt: str) -> Dict:
    cfg = _load_config()
    llm_cfg = cfg["integrations"]["llm"]

    timeout = _make_timeout(int(llm_cfg.get("request_timeout_sec", 90)))
    messages = _build_messages(system_prompt, address, la_data, search_notes)
    # models_to_try = [llm_cfg["model"]] + llm_cfg.get("fallback_models", [])
    fallbacks = llm_cfg.get("fallback_models")
    if not fallbacks or not isinstance(fallbacks, list) or not fallbacks:
        # ברירת מחדל אם אין fallback בקובץ הקונפיג
        fallbacks = ["openrouter/auto"]

    models_to_try = [llm_cfg["model"]] + fallbacks
    # שימי לב: לא מעבירים transport עם 'retries' כדי להישאר תואמי-גרסה;
    # במקום זה נוסיף ריטריי ידני סביב הבקשה.
    with httpx.Client(timeout=timeout, headers=_headers()) as client:
        last_err = None
        for i, model in enumerate(models_to_try):
            payload = {
                "model": model,
                "messages": messages,
                "temperature": llm_cfg.get("temperature", 0.2),
                "max_tokens": llm_cfg.get("max_tokens", 700 if i > 0 else 700),
                "response_format": {"type": "json_object"},
            }

            # שני ניסיונות עדינים לכל מודל (תואם גם לגרסאות httpx ישנות)
            for attempt in range(2):
                try:
                    r = client.post(llm_cfg["base_url"], json=payload)
                    r.raise_for_status()
                    data = r.json()

                    if "choices" in data and data["choices"]:
                        content = data["choices"][0]["message"]["content"]
                        try:
                            return json.loads(content)
                        except Exception:
                            return {
                                "sections": [{"title": "Summary", "content": content}],
                                "sources": [],
                                "warnings": ["LLM returned non-JSON content; returned as text."],
                            }

                    return {
                        "sections": [{"title": "Error", "content": f"Unexpected response: {data}"}],
                        "sources": [],
                        "warnings": [],
                    }

                except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                    last_err = e
                    logger.error(f"LLM timeout (model={model}, attempt={attempt+1}): {e}")
                    if attempt == 1:
                        # ננסה מודל פולבק (אם יש)
                        break
                    continue
                except httpx.HTTPStatusError as e:
                    last_err = e
                    logger.error(f"LLM HTTP error (model={model}): {e}")
                    # 429/5xx – אפשר לנסות שוב או לעבור לפולבק
                    break
                except httpx.RequestError as e:
                    last_err = e
                    logger.error(f"LLM request failed (model={model}, attempt={attempt+1}): {e}")
                    if attempt == 1:
                        break
                    continue
                except Exception as e:
                    last_err = e
                    logger.error(f"LLM unexpected error (model={model}): {e}")
                    break

    return {
        "sections": [{"title": "Error", "content": f"LLM request failed: {last_err}"}],
        "sources": [],
        "warnings": [str(last_err)] if last_err else [],
    }



def _llm_json(messages, llm_cfg):
    timeout = _make_timeout(int(llm_cfg.get("request_timeout_sec", 90)))
    fallbacks = llm_cfg.get("fallback_models") or ["openrouter/auto"]
    models = [llm_cfg["model"]] + (fallbacks if isinstance(fallbacks, list) else [fallbacks])
    with httpx.Client(timeout=timeout, headers=_headers()) as client:
        last_err = None
        for i, model in enumerate(models):
            payload = {
                "model": model,
                "messages": messages,
                "temperature": llm_cfg.get("temperature", 0.2),
                "max_tokens": llm_cfg.get("max_tokens", 700 if i else 700),
                "response_format": {"type": "json_object"},
            }
            for attempt in range(2):
                try:
                    r = client.post(llm_cfg["base_url"], json=payload)
                    r.raise_for_status()
                    data = r.json()
                    if data.get("choices"):
                        return json.loads(data["choices"][0]["message"]["content"])
                except Exception as e:
                    last_err = e
                    continue
        return {"error": str(last_err) if last_err else "unknown"}

@traceable(name="plan_queries")
def plan_queries(address: str, la_data: Dict) -> Dict:
    cfg = _load_config(); llm_cfg = cfg["integrations"]["llm"]
    messages = [
        {"role": "system", "content": PLAN_QUERIES_SYSTEM_PROMPT},
        {"role": "user", "content": f"ADDRESS: {address}\nLA_DATA:\n{json.dumps(la_data)}"}
    ]
    out = _llm_json(messages, llm_cfg)
    return out if isinstance(out, dict) else {"queries": [], "include_domains": [], "stop_condition": "error"}

def _pack_notes(notes: List[Dict]) -> str:
    chunks = []
    for i, s in enumerate(notes[:6]):
        body = s.get("raw_text") or s.get("content") or ""
        chunks.append(f"[{i+1}] {s.get('title','')} | {s.get('url','')}\n{body}\n")
    return "\n---\n".join(chunks)

@traceable(name="extract_merge")
def extract_merge(address: str, la_data: Dict, search_notes: List[Dict]) -> Dict:
    cfg = _load_config(); llm_cfg = cfg["integrations"]["llm"]
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"ADDRESS: {address}\nNOTES:\n{_pack_notes(search_notes)}\nCURRENT:\n{json.dumps(la_data)}"}
    ]
    out = _llm_json(messages, llm_cfg)
    # מיזוג עדין
    patch = (out or {}).get("patch", {}) if isinstance(out, dict) else {}
    merged = dict(la_data)
    # שדות פשוטים
    if "zoning" in patch:
        merged.setdefault("zoning", {})
        for k,v in (patch["zoning"] or {}).items():
            merged["zoning"][k] = v or merged["zoning"].get(k)
    if "overlays" in patch and patch["overlays"]:
        merged["overlays"] = sorted(set((merged.get("overlays") or []) + patch["overlays"]))
    if "permits" in patch and patch["permits"]:
        merged["permits"] = (merged.get("permits") or []) + patch["permits"]
    if "notes" in patch and patch["notes"]:
        merged["notes"] = (merged.get("notes") or "") + "\n" + patch["notes"]
    # מקורות
    merged["sources"] = (merged.get("sources") or []) + (out.get("sources") or [])
    return merged