import streamlit as st
import requests
import os

API_URL = os.getenv("API_URL", "http://localhost:8000/analyze")

st.set_page_config(page_title="LA Property Analyzer", layout="wide")
st.title("🏠 LA Property Analyzer")

# שני שדות נפרדים עבור רחוב ומספר בית
street_name = st.text_input("Enter street name")
house_number = st.text_input("Enter house number")

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
        except Exception as e:
            st.error(f"Request failed: {e}")
            st.stop()
        st.success("Done!")
        st.json(data)
        for sec in data.get("sections", []):
            with st.expander(sec.get("title", "Section"), expanded=(sec.get("title") == "Summary")):
                st.write(sec.get("content", ""))
