# -*- coding: utf-8 -*-
from typing import List, Dict, Any
from loguru import logger
import os, httpx, yaml
from langsmith import traceable
import requests
from dotenv import load_dotenv

load_dotenv()
TAVILY_API = os.getenv("TAVILY_API_KEY")
if not TAVILY_API:
    print("TAVILY_API_KEY is not set!")

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")

def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

@traceable(name="tavily_search")
def tavily_search(address: str) -> List[Dict[str, Any]]:
    # legacy helper (no longer used in scraper)
    queries = [
        f"{address} Los Angeles property information",
        f"{address} zoning regulations",
        f"{address} property value assessment",
        f"{address} neighborhood development plans",
        f"{address} recent sales comparable properties"
    ]
    results: List[Dict[str, Any]] = []
    for query in queries:
        resp = requests.post("https://api.tavily.com/search", json={"query": query, "api_key": TAVILY_API})
        if resp.status_code == 200:
            result = resp.json() or {}
            results.append({
                "query": query,
                "results": result.get("results", []),
                "follow_up_questions": result.get("follow_up_questions"),
                "answer": result.get("answer"),
            })
        else:
            print(f"Error with Tavily API: {resp.status_code}, {resp.text}")
    return results

def tavily_search_many(queries: List[str], include_domains: List[str]) -> List[Dict]:
    base_url = "https://api.tavily.com/search"
    if not TAVILY_API:
        logger.warning("Missing TAVILY_API_KEY")
        return []
    timeout = httpx.Timeout(connect=10, read=30, write=15, pool=10)
    results: List[Dict] = []
    inc = list({d.lower() for d in include_domains})[:6] if include_domains else None

    with httpx.Client(timeout=timeout) as client:
        for q in [q for q in queries[:12] if str(q).strip()]:
            payload = {
                "api_key": TAVILY_API,
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
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", ""),
                        "score": item.get("score", 0.0),
                    }
                    results.append(rec)
            except Exception as e:
                logger.error(f"Tavily query failed: {q} | {e}")
    return results
