from typing import List, Dict, Any
from loguru import logger
import os, httpx, yaml
from langsmith import traceable
import requests
from dotenv import load_dotenv

load_dotenv() 
TAVILY_API = os.getenv("TAVILY_API_KEY")
print(f"TAVILY_API_KEY: {TAVILY_API}")
if not TAVILY_API:
    print("TAVILY_API_KEY is not set!")

CONFIG_PATH = os.getenv("CONFIG_PATH", "config/config.yaml")

def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)



@traceable(name="tavily_search")
def tavily_search(address: str) -> List[Dict[str, Any]]:
    queries = [
        f"{address} Los Angeles property information",
        f"{address} zoning regulations",
        f"{address} property value assessment",
        f"{address} neighborhood development plans",
        f"{address} recent sales comparable properties"
    ]
    
    results = []
    
    # שליחה לתבילי עם כל אחד מהפרומפטים
    for query in queries:
        response = requests.post("https://api.tavily.com/search", json={"query": query, "api_key": TAVILY_API})
        if response.status_code == 200:
            result = response.json()
            if result:
                results.append({
                    "query": query,
                    "results": result.get("results", []),
                    "follow_up_questions": result.get("follow_up_questions", None),
                    "answer": result.get("answer", None)
                })  # הוספת תוצאות לתוך results
            else:
                print(f"No results for query: {query}")
        else:
            print(f"Error with Tavily API: {response.status_code}, {response.text}")
    
    print(f"Tavily results: {results}")  # הדפסה לטרמינל
    return results

# @traceable(name="tavily_search")
# def tavily_search(address: str) -> List[Dict[str, Any]]:
#     # רשימה של פרומפטים ממוקדים
#     queries = [
#         f"{address} Los Angeles property information",
#         f"{address} zoning regulations",
#         f"{address} property value assessment",
#         f"{address} neighborhood development plans",
#         f"{address} recent sales comparable properties"
#     ]
    
#     results = []
    
#     # שליחה לתבילי עם כל אחד מהפרומפטים
#     for query in queries:
#         response = requests.post("https://api.tavily.com/search", json={"query": query, "api_key": TAVILY_API})
#         if response.status_code == 200:
#             result = response.json()
#             if result:
#                 results.append(result)  # הוספת תוצאה לתוך results
#             else:
#                 print(f"No results for query: {query}")
#         else:
#             print(f"Error with Tavily API: {response.status_code}, {response.text}")
    
#     print(f"Tavily results: {results}")  # הדפסה לטרמינל
#     return results



def tavily_search_many(queries: List[str], include_domains: List[str]) -> List[Dict]:
    base_url = "https://api.tavily.com/search"
    # TAVILY_API = os.getenv("TAVILY_API_KEY")
    print(TAVILY_API)
    # key = os.getenv("TAVILY_API_KEY","")
    if not TAVILY_API: 
        logger.warning("Missing TAVILY_API_KEY")
        print("================ "+TAVILY_API+" ============")
        return []
    timeout = httpx.Timeout(connect=10, read=30, write=15, pool=10)
    results: List[Dict] = []
    inc = list({d.lower() for d in include_domains})[:6] if include_domains else None

    with httpx.Client(timeout=timeout) as client:
        for q in queries[:6]:  # הוספת פרומפטים ממוקדים
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
                        "title": item.get("title",""),
                        "url": item.get("url",""),
                        "content": item.get("content",""),
                        "score": item.get("score",0.0),
                    }
                    results.append(rec)
            except Exception as e:
                logger.error(f"Tavily query failed: {q} | {e}")
    return results

