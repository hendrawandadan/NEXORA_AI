from contextlib import closing

import pandas as pd
import plotly.express as px
import streamlit as st

from nexora_dashboard.database import connect_readonly, schema_snapshot, table_rows
from nexora_dashboard.ui import apply_theme, show_database_error

apply_theme()

st.title("Database Overview")
st.caption("TRADING INTELLIGENCE  /  LIVE DATABASE MONITOR")

try:
    snapshot = schema_snapshot()
    st.success("Database connected · read-only mode")
    version = snapshot["schema_version"] if snapshot["schema_version"] is not None else "Unavailable"
    st.caption(f"Schema version: {version} · {len(snapshot['tables'])} tables · {snapshot['index_count']} indexes")
    labels = [("◈  Datasets", "datasets"), ("◷  Training jobs", "training_jobs"),
              ("↗  Training runs", "training_runs"), ("▣  Checkpoints", "checkpoints"),
              ("◇  Model artifacts", "model_artifacts"), ("✓  Validation results", "validation_results"),
              ("≋  Audit logs", "audit_logs")]
    groups = [st.columns(4), st.columns(3)]
    for index, (label, table) in enumerate(labels):
        group, slot = (groups[0], index) if index < 4 else (groups[1], index - 4)
        with group[slot]:
            st.metric(label, f"{snapshot['counts'].get(table, 0):,}" if table in snapshot["tables"] else "—")
    st.markdown("### Operational signals")
    left, right = st.columns(2)
    for col, table, title in [(left, "training_jobs", "Job status distribution"),
                              (right, "training_runs", "Training run status distribution")]:
        with col:
            st.subheader(title)
            if table in snapshot["tables"] and "status" in [c["name"] for c in snapshot["columns"][table]]:
                with closing(connect_readonly()) as conn:
                    result = conn.execute(
                        f'SELECT status, COUNT(*) AS total FROM "{table}" GROUP BY status ORDER BY status'
                    ).fetchall()
                if result:
                    chart = px.pie(pd.DataFrame([dict(row) for row in result]), names="status", values="total",
                                   hole=.58, color_discrete_sequence=px.colors.sequential.Teal)
                    chart.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                                        plot_bgcolor="rgba(0,0,0,0)", font_color="#d8e5f2",
                                        margin=dict(l=12, r=12, t=16, b=12), legend_title_text="Status")
                    st.plotly_chart(chart, use_container_width=True)
                else:
                    st.info("No status records yet.")
            else:
                st.info("No compatible status column is available.")
    st.subheader("Recent activity")
    if "audit_logs" in snapshot["tables"]:
        names, rows, _ = table_rows("audit_logs", limit=10, offset=0)
        if rows:
            st.dataframe(pd.DataFrame(rows, columns=names), use_container_width=True, hide_index=True)
        else:
            st.info("No audit events recorded.")
    else:
        st.info("The schema has no audit log table.")
    with st.expander("Database integrity"):
        with closing(connect_readonly()) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        st.write(result)
except Exception as exc:
    show_database_error(exc)
