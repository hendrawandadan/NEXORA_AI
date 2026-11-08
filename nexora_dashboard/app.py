import streamlit as st
from pathlib import Path
from nexora_dashboard.ui import apply_theme

from nexora_dashboard.config import BIND_ADDRESS, PORT

st.set_page_config(page_title="NEXORA Database Intelligence Console", page_icon="◈",
                   layout="wide", initial_sidebar_state="expanded")
apply_theme()

st.sidebar.markdown("# NEXORA AI")
st.sidebar.caption("Database Intelligence Console")
st.sidebar.caption("Autonomous Trading Intelligence — Database Monitor")
st.sidebar.markdown("---")
st.sidebar.markdown(f"<div style='padding:9px 11px;border:1px solid #065f46;background:#12352f;border-radius:10px;color:#6ee7b7;font-size:.86rem'>● &nbsp;Local-only · {BIND_ADDRESS}:{PORT}</div>", unsafe_allow_html=True)
st.sidebar.caption("Read-only monitor · no training or write controls")

pages = [
    st.Page(Path(__file__).parent / "pages/1_Overview.py", title="Overview", default=True),
    st.Page(Path(__file__).parent / "pages/2_Datasets.py", title="Datasets"),
    st.Page(Path(__file__).parent / "pages/3_Training_Jobs.py", title="Training Jobs"),
    st.Page(Path(__file__).parent / "pages/4_Training_Runs.py", title="Training Runs"),
    st.Page(Path(__file__).parent / "pages/5_Checkpoints.py", title="Checkpoints"),
    st.Page(Path(__file__).parent / "pages/6_Model_Artifacts.py", title="Model Artifacts"),
    st.Page(Path(__file__).parent / "pages/7_Validation.py", title="Validation"),
    st.Page(Path(__file__).parent / "pages/8_Audit_Logs.py", title="Audit Logs"),
    st.Page(Path(__file__).parent / "pages/9_SQL_Explorer.py", title="SQL Explorer"),
]
st.navigation(pages).run()
