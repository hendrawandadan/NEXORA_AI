import streamlit as st
from nexora_dashboard.ui import render_table
render_table("Model Artifacts", "model_artifacts")
st.caption("Artifact files are never opened by this dashboard.")
