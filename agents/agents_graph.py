# -*- coding: utf-8 -*-
from typing import Dict, Any, List, TypedDict, Optional
from loguru import logger
from langgraph.graph import StateGraph, START, END

from app.scraper import scrape_la_city_planning
from app.search_integration import tavily_search_many
from app.llm_integration import analyze_with_llm, plan_queries, extract_merge
from app.prompts import REPORT_SYSTEM_PROMPT

# -------------------- Types & Helpers --------------------

class PropState(TypedDict, total=False):
    street_name: str
    house_number: str
    address: str
    la_data: Dict[str, Any]
    tavily_results: List[Dict[str, Any]]
    search_notes: List[Dict[str, Any]]
    queries: List[str]
    include_domains: List[str]
    stop_condition: str
    iter: int
    report: Dict[str, Any]
    errors: List[str]
    __next__: str
    user_queries: List[str]          # << new: user-provided questions

def build_address(street_name: str, house_number: str, city: str = "Los Angeles, CA") -> str:
    street = " ".join((street_name or "").split()).strip()
    number = str(house_number).strip()
    return f"{number} {street}, {city}"

def _ensure_address(state: PropState) -> str:
    if not state.get("address"):
        state["address"] = build_address(state["street_name"], state["house_number"])
    return state["address"]

# -------------------- Nodes --------------------

def node_scrape(state: PropState) -> PropState:
    try:
        data = scrape_la_city_planning(state["street_name"], state["house_number"])
        state["la_data"] = {
            "panels": data.get("panels", {}),
            "notes": data.get("notes", ""),
            "sources": data.get("sources", []),
        }
        state["tavily_results"] = data.get("tavily_results", [])
    except Exception as e:
        logger.exception("scrape failed")
        state.setdefault("errors", []).append(f"scrape:{e}")
        state["la_data"] = {
            "street_name": state["street_name"],
            "house_number": state["house_number"],
        }
    return state

def node_plan(state: PropState) -> PropState:
    try:
        address = _ensure_address(state)

        # If the user supplied queries, use them and stop planning.
        user_qs = [q.strip() for q in (state.get("user_queries") or []) if str(q).strip()]
        if user_qs:
            state["queries"] = user_qs
            # Keep official domains as a starting point; Tavily can still search broadly if needed.
            state["include_domains"] = ["planning.lacity.gov", "zimas.lacity.org", "ladbs.org"]
            state["stop_condition"] = "enough"
            return state

        # Otherwise, let planner generate focused queries
        plan = plan_queries(address, state.get("la_data", {}))
        state["queries"] = plan.get("queries", [])
        state["include_domains"] = plan.get(
            "include_domains",
            ["planning.lacity.gov", "zimas.lacity.org", "ladbs.org"]
        )
        state["stop_condition"] = plan.get("stop_condition", "")
    except Exception as e:
        logger.exception("plan failed")
        state.setdefault("errors", []).append(f"plan:{e}")
        state["queries"] = []
        state["include_domains"] = []
        state["stop_condition"] = "error"
    return state

def node_search(state: PropState) -> PropState:
    try:
        notes = tavily_search_many(state.get("queries", []), state.get("include_domains", []))
        state["search_notes"] = notes or []
    except Exception as e:
        logger.exception("search failed")
        state.setdefault("errors", []).append(f"search:{e}")
        state["search_notes"] = []
    return state

def node_extract(state: PropState) -> PropState:
    try:
        address = _ensure_address(state)
        combined_notes = (state.get("search_notes") or []) + (state.get("tavily_results") or [])
        merged = extract_merge(address, state.get("la_data", {}), combined_notes)
        state["la_data"] = merged
    except Exception as e:
        logger.exception("extract failed")
        state.setdefault("errors", []).append(f"extract:{e}")
    return state

def node_decide(state: PropState) -> PropState:
    it = state.get("iter", 0)
    stop = (state.get("stop_condition") == "enough")
    state["iter"] = it + 1
    state["__next__"] = "analyze" if stop or it >= 1 else "plan"
    return state

def node_analyze(state: PropState) -> PropState:
    try:
        address = _ensure_address(state)
        combined_notes = (state.get("search_notes") or []) + (state.get("tavily_results") or [])
        state["report"] = analyze_with_llm(
            address=address,
            la_data=state.get("la_data", {}),
            search_notes=combined_notes,
            system_prompt=REPORT_SYSTEM_PROMPT
        )
    except Exception as e:
        logger.exception("llm failed")
        state.setdefault("errors", []).append(f"llm:{e}")
        state["report"] = {"sections": [{"title": "Error", "content": str(e)}]}
    return state

def node_format(state: PropState) -> PropState:
    address = _ensure_address(state)
    rpt = state.get("report") or {}
    return {
        "address": address,
        "street_name": state.get("street_name"),
        "house_number": state.get("house_number"),
        "la_data": state.get("la_data", {}),
        "search_notes": state.get("search_notes", []),
        "tavily_results": state.get("tavily_results", []),
        "formatted_text": rpt.get("formatted_text", ""),
        "raw_llm_text": rpt.get("raw_llm_text", ""),   # ← חדש
        "sections": rpt.get("sections", []),
        "sources": (rpt.get("sources", []) + (state.get("la_data", {}).get("sources") or [])),
        "warnings": ((rpt.get("warnings", []) or []) + (state.get("errors", []) or [])),
    }


# -------------------- Graph --------------------
graph = StateGraph(PropState)
graph.add_node("scrape", node_scrape)
graph.add_node("plan", node_plan)
graph.add_node("search", node_search)
graph.add_node("extract", node_extract)
graph.add_node("decide", node_decide)
graph.add_node("analyze", node_analyze)
graph.add_node("format", node_format)

graph.add_edge(START, "scrape")
graph.add_edge("scrape", "plan")
graph.add_edge("plan", "search")
graph.add_edge("search", "extract")
graph.add_edge("extract", "decide")
graph.add_conditional_edges("decide", lambda s: s["__next__"], {"plan": "plan", "analyze": "analyze"})
graph.add_edge("analyze", "format")
graph.add_edge("format", END)

app = graph.compile()

# -------------------- Entrypoint --------------------
def run_property_workflow(street_name: str, house_number: str, user_queries: Optional[List[str]] = None) -> Dict[str, Any]:
    state: PropState = {
        "street_name": street_name,
        "house_number": house_number,
        "address": build_address(street_name, house_number),
        "iter": 0,
    }
    if user_queries:
        state["user_queries"] = [q.strip() for q in user_queries if str(q).strip()]
    result = app.invoke(state)
    return {
        "address": result.get("address"),
        "street_name": result.get("street_name"),
        "house_number": result.get("house_number"),
        "la_data": result.get("la_data"),
        "search_notes": result.get("search_notes"),
        "tavily_results": result.get("tavily_results"),
        "formatted_text": result.get("formatted_text"),
        "sections": result.get("sections"),
        "sources": result.get("sources"),
        "warnings": result.get("warnings"),
    }
