# -*- coding: utf-8 -*-
import streamlit as st
import requests
import os
import json  # For RAW debugging

API_URL = os.getenv("API_URL", "http://localhost:8000/analyze")

st.set_page_config(page_title="LA Property Analyzer", layout="wide")
st.title("🏠 LA Property Analyzer")

# --- Address inputs ---
street_name = st.text_input("Enter street name")
house_number = st.text_input("Enter house number")

# --- session state init ---
if "user_questions" not in st.session_state:
    st.session_state.user_questions = []
if "question_input" not in st.session_state:
    st.session_state.question_input = ""
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "_clear_q" not in st.session_state:
    st.session_state._clear_q = False
if "show_raw" not in st.session_state:
    st.session_state.show_raw = False  # By default, do not show raw data

# --- callbacks ---
def add_question_cb():
    q = (st.session_state.question_input or "").strip()
    if q:
        st.session_state.user_questions.append(q)
        st.session_state._clear_q = True

def clear_questions_cb():
    st.session_state.user_questions = []

def run_analysis_cb():
    if not (street_name and house_number):
        st.warning("Please enter a street name and a house number.")
        return
    try:
        payload = {
            "street_name": street_name,
            "house_number": house_number,
            "user_questions": st.session_state.user_questions or None,
        }
        with st.spinner("Analyzing..."):
            r = requests.post(API_URL, json=payload, timeout=240)
            r.raise_for_status()

            # Server might return a plain string instead of JSON
            try:
                data = r.json()
            except ValueError:
                txt = (r.text or "").strip()
                data = {"formatted_text": txt}

            # --- FORCE formatted_text from any possible location ---
            rpt = (data.get("report") or {}) if isinstance(data, dict) else {}
            data["raw_llm_text"] = (data.get("raw_llm_text") or rpt.get("raw_llm_text") or "").strip()
            data["formatted_text"] = (
                (data.get("formatted_text") or "").strip()
                or (rpt.get("formatted_text") or "").strip()
                or data["raw_llm_text"]
            )

            # Normalize from nested 'report' if present
            if isinstance(data, dict) and isinstance(data.get("report"), dict):
                rpt = data["report"]
                for k in ("formatted_text", "sections", "sources", "warnings", "la_data", "raw_llm_text"):
                    if k in rpt and rpt[k] is not None and (not data.get(k)):
                        data[k] = rpt[k]

            # Safety net 1: if no formatted_text but have sections -> join to string
            if not (data.get("formatted_text") or "").strip():
                parts = []
                for s in (data.get("sections") or []):
                    title = s.get("title", "Section")
                    body  = (s.get("content") or "").strip()
                    parts.append(f"## {title}\n\n{body}".strip())
                if parts:
                    data["formatted_text"] = "\n\n".join(parts).strip()

            # Safety net 2: still no formatted_text but have raw_llm_text -> use it
            if not (data.get("formatted_text") or "").strip() and (data.get("raw_llm_text") or "").strip():
                data["formatted_text"] = data["raw_llm_text"].strip()

            # Final cleanup
            data["formatted_text"] = (data.get("formatted_text") or "").strip()
            data["raw_llm_text"]   = (data.get("raw_llm_text") or "").strip()

            st.session_state.last_result = data

        st.success("Done!")
    except Exception as e:
        st.error(f"Request failed: {e}")

# --- User-provided Tavily questions builder ---
st.subheader("Tavily Search Questions (optional)")
col_a, col_b = st.columns([3, 1], gap="small")
with col_a:
    if st.session_state._clear_q:
        st.session_state.question_input = ""
        st.session_state._clear_q = False
    st.text_input(
        "Enter a question",
        key="question_input",
        placeholder="e.g., height district & FAR for 123 Main St (planning.lacity.gov / zimas.lacity.org / ladbs.org)",
    )
with col_b:
    st.button("➕ Add question", use_container_width=True, on_click=add_question_cb)

if st.session_state.user_questions:
    st.caption("These questions will be sent to Tavily:")
    for i, uq in enumerate(st.session_state.user_questions, 1):
        st.write(f"{i}. {uq}")
    st.button("🗑️ Clear questions list", on_click=clear_questions_cb)

st.divider()
left, right = st.columns([1, 1])
with left:
    st.button("✅ Run analysis", type="primary", on_click=run_analysis_cb)
with right:
    st.toggle("Show raw (ZIMAS/Tavily)", key="show_raw", help="For testing/debugging only")

# --- Render results ---
data = st.session_state.last_result

# 🔥 RAW DEBUG payload – visible only when the toggle is on
if data and st.session_state.show_raw:
    st.subheader("🔥 DEBUG RAW PAYLOAD")
    st.code(json.dumps(data, ensure_ascii=False, indent=2))

if data:
    address = data.get("address") or f"{data.get('house_number','')} {data.get('street_name','')}"
    if address:
        st.header(f"📍 {address}")

    # === Main view: single edited summary from the LLM ===
    st.subheader("Edited summary")
    fmt = (data.get("formatted_text") or "").strip()
    if fmt:
        st.markdown(fmt)
    else:
        st.info("No edited summary was returned by the LLM.")

    # === Raw data — only if requested ===
    if st.session_state.show_raw:
        st.divider()
        st.subheader("Raw data (for debugging)")

        # RAW LLM text (if any)
        if (data.get("raw_llm_text") or "").strip():
            with st.expander("Raw LLM Text (exact content)", expanded=False):
                st.code(data["raw_llm_text"])

        # Panels (ZIMAS)
        panels = (data.get("la_data") or {}).get("panels") or data.get("panels") or {}
        if panels:
            st.markdown("**Official panels (ZIMAS)**")
            for title, content in panels.items():
                with st.expander(title, expanded=False):
                    st.text(content if content else "(empty)")

        # Focused Tavily notes
        notes = data.get("search_notes") or []
        if notes:
            st.markdown("**Focused search results (Tavily)**")
            col1, col2 = st.columns(2)
            with col1:
                top_k = st.number_input("How many to show (Top-K)", min_value=1, max_value=100, value=min(15, len(notes)))
            with col2:
                sort_desc = st.checkbox("Sort by Score (high → low)", value=True)
            display_notes = sorted(notes, key=lambda x: x.get("score", 0.0), reverse=sort_desc)[:top_k]
            for i, item in enumerate(display_notes, 1):
                with st.expander(f"[{i}] {item.get('title') or 'Untitled'}", expanded=False):
                    if item.get("score") is not None:
                        st.write(f"**Score:** {item.get('score')}")
                    if item.get("url"):
                        st.write(f"**URL:** {item.get('url')}")
                    content = (item.get("raw_text") or item.get("content") or "").strip()
                    st.write(content if content else "(no summary available)")

        # Sources & Warnings (only inside raw data)
        if data.get("sources"):
            st.markdown("**Sources:**")
            for s in data["sources"]:
                name = s.get("name", "source")
                url = s.get("url", "")
                if url:
                    st.markdown(f"- [{name}]({url})")
                else:
                    st.markdown(f"- {name}")

        if data.get("warnings"):
            with st.expander("Warnings / Errors"):
                for w in data["warnings"]:
                    st.write(f"- {w}")

    # Download as text
    def format_text_report(d: dict) -> str:
        lines = []
        addr = d.get("address") or f"{d.get('house_number','')} {d.get('street_name','')}"
        if addr:
            lines += [f"Address: {addr}", "-" * 40]
        if d.get("formatted_text"):
            lines += [d["formatted_text"]]
        # If raw data is shown — include it in the text file as well
        if st.session_state.show_raw:
            if (d.get("raw_llm_text") or "").strip():
                lines += ["\n---\nRaw LLM Text:\n", d["raw_llm_text"]]
            panels = (d.get("la_data") or {}).get("panels") or d.get("panels") or {}
            if panels:
                lines.append("\nOfficial panels (ZIMAS):")
                for title, content in panels.items():
                    if content:
                        lines += [f"\n[{title}]", content]
            sources = d.get("sources") or []
            if sources:
                lines += ["\nSources:"]
                for s in sources:
                    name = s.get("name", "source")
                    url = s.get("url", "")
                    lines.append(f"- {name} — {url}" if url else f"- {name}")
            warnings = d.get("warnings") or []
            if warnings:
                lines += ["\nWarnings / Errors:"]
                for w in warnings:
                    lines.append(f"- {w}")
        return "\n".join(lines).strip()

    txt = format_text_report(data)
    st.download_button("⬇️ Download as text", data=txt, file_name="report.txt", mime="text/plain")
