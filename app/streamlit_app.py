import streamlit as st
import requests
import os

API_URL = os.getenv("API_URL", "http://localhost:8000/analyze")

st.set_page_config(page_title="LA Property Analyzer", layout="wide")
st.title("🏠 LA Property Analyzer")

# שני שדות נפרדים עבור רחוב ומספר בית
street_name = st.text_input("Enter street name")
house_number = st.text_input("Enter house number")

data = None  # ודא ש־data מוגדר מראש

if st.button("Analyze", type="primary") and street_name and house_number:
    with st.spinner("Analyzing..."):
        try:
            # שליחת הכתובת כפרמטרים נפרדים
            r = requests.post(API_URL, json={"street_name": street_name, "house_number": house_number}, timeout=180)
            r.raise_for_status()
            data = r.json()
            if "sections" not in data and "report" in data:
                rpt = data.get("report") or {}
                data["sections"] = rpt.get("sections", [])
                data["sources"] = rpt.get("sources", [])
                data["warnings"] = rpt.get("warnings", [])
            
            st.success("Done!")
        except Exception as e:
            st.error(f"Request failed: {e}")
            st.stop()

if data:  # הצגת התוכן רק אם data הוגדרה
    # הצגה במסך (כותרות יפות)
    address = data.get("address") or f"{data.get('house_number','')} {data.get('street_name','')}"
    if address:
        st.header(f"📍 {address}")


    # פאנלים (ZIMAS) בצד שמאל, אם יש
    panels = (data.get("la_data") or {}).get("panels") or data.get("panels") or {}
    if panels:
        st.subheader("פאנלים רשמיים (ZIMAS)")
        for title, content in panels.items():
            with st.expander(title, expanded=False):
                st.text(content if content else "(ריק)")

    # ה-sections של הדוח
    if data.get("sections"):
        st.subheader("דוח מנותח")
        for sec in data["sections"]:
            with st.expander(sec.get("title","Section"), expanded=(sec.get("title") == "Summary")):
                st.markdown(sec.get("content",""))

    # מקורות
    if data.get("sources"):
        st.subheader("מקורות")
        for s in data["sources"]:
            st.markdown(f"- [{s.get('name','source')}]({s.get('url','')})")

    # אזהרות
    if data.get("warnings"):
        st.warning("יש אזהרות בדו\"ח – גלול לתחתית לקבלת פירוט.")
        with st.expander("אזהרות/שגיאות"):
            for w in data["warnings"]:
                st.write(f"- {w}")

    # הצגת תוצאות Tavily עם כותרות מסודרות
    if data.get("tavily_results"):
        st.subheader("תוצאות מתבילי")
        for idx, result in enumerate(data["tavily_results"], 1):
            st.write(f"**Query {idx}:** {result.get('query')}")
            if result.get("results"):
                for item in result["results"]:
                    st.write(f"**Title:** {item.get('title')}")
                    st.write(f"**Content:** {item.get('content')}")
                    st.write(f"**URL:** {item.get('url')}")
                st.write("---")


# --- תוצאות ממוקדות (tavily_search_many) ---
    st.write("aaaaaaaaaaaaaaaaaaaaaa")
    notes = data.get("search_notes") or []
    if notes:
        st.subheader("תוצאות חיפוש ממוקדות (tavily_search_many)")
        # אפשרויות תצוגה
        col1, col2 = st.columns(2)
        with col1:
            top_k = st.number_input("כמה להציג (Top-K)", min_value=1, max_value=100, value=min(15, len(notes)))
        with col2:
            sort_desc = st.checkbox("מיון לפי Score (גבוה→נמוך)", value=True)

        # מיון והגבלה
        display_notes = sorted(notes, key=lambda x: x.get("score", 0.0), reverse=sort_desc)[:top_k]

        for i, item in enumerate(display_notes, 1):
            with st.expander(f"[{i}] {item.get('title') or 'ללא כותרת'}", expanded=False):
                if item.get("score") is not None:
                    st.write(f"**Score:** {item.get('score')}")
                if item.get("url"):
                    st.write(f"**URL:** {item.get('url')}")
                content = (item.get("raw_text") or item.get("content") or "").strip()
                st.write(content if content else "(אין תקציר זמין)")
    st.write("bbbbbbbbbbbbbbbbbbbbbbb")

    # כפתור להורדה כ-TXT
    def format_text_report(d: dict) -> str:
        lines = []
        addr = d.get("address") or f"{d.get('house_number','')} {d.get('street_name','')}"
        if addr:
            lines += [f"כתובת: {addr}", "-"*40]

        # Panels (ZIMAS) אם קיימים
        panels = (d.get("la_data") or {}).get("panels") or d.get("panels") or {}
        if panels:
            lines.append("פאנלים רשמיים (ZIMAS):")
            for title, content in panels.items():
                if content:
                    lines += [f"\n[{title}]", content]
            lines.append("-"*40)

        # Sections (דוח ה-LLM)
        sections = d.get("sections") or []
        for sec in sections:
            title = sec.get("title", "Section")
            content = sec.get("content", "").strip()
            lines += [f"\n## {title}", content if content else "(אין תוכן)"]

        # Sources
        sources = d.get("sources") or []
        if sources:
            lines += ["\nמקורות:"]
            for s in sources:
                name = s.get("name","source")
                url = s.get("url","")
                lines.append(f"- {name} — {url}")

        # Warnings
        warnings = d.get("warnings") or []
        if warnings:
            lines += ["\nאזהרות/שגיאות:"]
            for w in warnings:
                lines.append(f"- {w}")

        return "\n".join(lines).strip()

    txt = format_text_report(data)
    st.download_button("⬇️ הורדה כטקסט", data=txt, file_name="report.txt", mime="text/plain")
