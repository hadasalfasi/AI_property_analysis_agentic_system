from typing import List, Dict, Any
from loguru import logger
import os, httpx, yaml
from langsmith import traceable

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")

def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

@traceable(name="tavily_search")
def tavily_search(query: str) -> List[Dict[str, Any]]:
    cfg = _load_config()
    scfg = cfg["integrations"]["search"]
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        logger.warning("TAVILY_API_KEY missing; returning empty results.")
        return []

    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": scfg.get("max_results", 6),
        "include_answer": scfg.get("include_answer", False),
        "include_images": scfg.get("include_images", False),
    }
    timeout = httpx.Timeout(scfg.get("request_timeout_sec", 30), connect=10)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.post(scfg.get("base_url"), json=payload)
        r.raise_for_status()
        data = r.json()

    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "content": item.get("content"),
            "score": item.get("score"),
        }
        for item in data.get("results", [])
    ]


def tavily_search_many(queries: List[str], include_domains: List[str]) -> List[Dict]:
    base_url = "https://api.tavily.com/search"
    key = os.getenv("TAVILY_API_KEY","")
    if not key: 
        logger.warning("Missing TAVILY_API_KEY"); return []
    timeout = httpx.Timeout(connect=10, read=30, write=15, pool=10)
    results: List[Dict] = []
    inc = list({d.lower() for d in include_domains})[:6] if include_domains else None
    with httpx.Client(timeout=timeout) as client:
        for q in queries[:6]:
            payload = {
                "api_key": key,
                "query": q,
                "search_depth": "advanced",
                "max_results": 6,
                "include_answer": False,
            }
            if inc:
                payload["include_domains"] = inc
            try:
                r = client.post(base_url, json=payload)
                r.raise_for_status()
                data = r.json()
                for item in data.get("results", []):
                    rec = {
                        "title": item.get("title",""),
                        "url": item.get("url",""),
                        "content": item.get("content",""),
                        "score": item.get("score",0.0),
                    }
                    try:
                        page = client.get(rec["url"])
                        if page.status_code == 200:
                            rec["raw_text"] = page.text[:20000]
                    except Exception:
                        pass
                    results.append(rec)
            except Exception as e:
                logger.error(f"Tavily query failed: {q} | {e}")
    return results
