"""Shared Streamlit rendering helpers for schema-driven pages."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from contextlib import closing

from .database import MAX_ROWS, connect_readonly, quote_identifier, schema_snapshot, table_rows

TABLE_MAP = {
    "Datasets": "datasets", "Training Jobs": "training_jobs", "Training Runs": "training_runs",
    "Checkpoints": "checkpoints", "Model Artifacts": "model_artifacts",
    "Validation": "validation_results", "Audit Logs": "audit_logs",
}


def apply_theme() -> None:
    """Apply a shared Tailwind-palette theme across every page."""
    st.markdown("""
    <style>
    :root {
      color-scheme: dark;
      --nx-slate-950: #020617; --nx-slate-900: #0f172a; --nx-slate-800: #1e293b;
      --nx-slate-700: #334155; --nx-slate-400: #94a3b8; --nx-slate-300: #cbd5e1;
      --nx-emerald-400: #34d399; --nx-emerald-500: #10b981; --nx-sky-400: #38bdf8;
      --nx-amber-400: #fbbf24;
    }
    .stApp { background: radial-gradient(ellipse at 15% -12%, #1d3552 0, var(--nx-slate-900) 48%, var(--nx-slate-950) 100%); color: #f1f5f9; }
    [data-testid="stHeader"] { background: rgba(15, 23, 42, .92); border-bottom: 1px solid #26354d; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #111c30, #0b1222); border-right: 1px solid #293850; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p, [data-testid="stSidebar"] label { color: var(--nx-slate-300); }
    [data-testid="stSidebarNav"] { padding-top: .5rem; }
    [data-testid="stSidebarNav"] a { border-radius: 10px; margin: 3px 8px; transition: background .16s ease; }
    [data-testid="stSidebarNav"] a:hover { background: #1b2b43; }
    [data-testid="stSidebarNav"] a[aria-current="page"] { background: #12352f; border-left: 3px solid var(--nx-emerald-400); }
    [data-testid="stSidebarNav"] a[aria-current="page"] span { color: #ecfdf5; font-weight: 650; }
    .block-container { max-width: 1560px; padding-top: 2rem; padding-bottom: 3rem; }
    h1 { color: #f8fafc !important; font-size: clamp(1.8rem, 3vw, 2.45rem) !important; letter-spacing: -.035em; }
    h2, h3 { color: #f1f5f9 !important; letter-spacing: -.02em; }
    p, label, [data-testid="stCaptionContainer"] { color: var(--nx-slate-300); }
    [data-testid="stMetric"] { background: linear-gradient(145deg, #1e2c42, #172338); border: 1px solid #3a4b64; border-top-color: #52647b; padding: 19px 20px; border-radius: 16px; box-shadow: 0 10px 28px rgba(2,6,23,.2); min-height: 112px; }
    [data-testid="stMetricLabel"] { color: #cbd5e1 !important; font-size: .84rem; font-weight: 600; }
    [data-testid="stMetricValue"] { color: #f8fafc !important; font-weight: 700; letter-spacing: -.035em; }
    [data-testid="stMetricDelta"] { color: var(--nx-emerald-400) !important; }
    [data-testid="stPlotlyChart"], [data-testid="stDataFrame"], [data-testid="stTable"] { border: 1px solid #33445d; border-radius: 14px; overflow: hidden; background: rgba(30, 41, 59, .7); }
    [data-testid="stDataFrame"] { padding: 4px; }
    [data-baseweb="select"] > div { background: #172338; color: #f1f5f9; border-color: #475569; }
    .stTextInput input, .stTextArea textarea { background: #172338; color: #f1f5f9; border-color: #475569; }
    button[kind="primary"] { background: #047857; border: 1px solid #34d399; color: #ecfdf5; font-weight: 650; }
    button[kind="primary"]:hover { background: #059669; border-color: #6ee7b7; }
    [data-testid="stAlert"] { border-radius: 12px; background: #1e293b; border-color: #475569; color: #e2e8f0; }
    hr { border-color: #334155; }
    @media (max-width: 760px) { .block-container { padding: 1.3rem 1rem 2rem; } [data-testid="stMetric"] { padding: 14px; min-height: 94px; } }
    </style>
    """, unsafe_allow_html=True)


@st.cache_data(ttl=10, show_spinner=False)
def load_schema():
    return schema_snapshot()


def show_database_error(exc: Exception) -> None:
    st.error("Database unavailable. Check the configured local database path and read permissions.")
    st.caption(f"Details: {type(exc).__name__}")


def render_table(title: str, table: str) -> None:
    apply_theme()
    st.title(title)
    try:
        schema = load_schema()
        if table not in schema["tables"]:
            st.info(f"Table `{table}` is not present in the connected schema.")
            return
        fields = schema["columns"][table]
        colnames = [field["name"] for field in fields]
        search = st.text_input("Search", key=f"search_{table}")
        filter_cols = [name for name in ("status", "symbol", "timeframe") if name in colnames]
        active = {}
        filter_widgets = st.columns(max(1, len(filter_cols)))
        for i, name in enumerate(filter_cols):
            with filter_widgets[i]:
                options = _distinct(table, name)
                selected = st.multiselect(name.replace("_", " ").title(), options, key=f"filter_{table}_{name}")
                if selected:
                    active[name] = selected
        page_size = 50
        total = _count_filtered(table, search, active)
        pages = max(1, (total + page_size - 1) // page_size)
        page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=f"page_{table}")
        names, rows, _ = table_rows(table, search=search, limit=page_size,
                                    offset=(page - 1) * page_size, filters=active)
        st.caption(f"{total:,} rows · page {page} of {pages}")
        if rows:
            frame = pd.DataFrame(rows, columns=names)
            if table == "training_runs" and {"started_at", "ended_at"}.issubset(names):
                started = pd.to_datetime(frame["started_at"], errors="coerce", utc=True)
                ended = pd.to_datetime(frame["ended_at"], errors="coerce", utc=True)
                frame["duration"] = (ended - started).astype("string")
            st.dataframe(frame, use_container_width=True, hide_index=True)
            if "id" in names:
                id_index = names.index("id")
                selected_id = st.selectbox("Row detail", [row[id_index] for row in rows], key=f"detail_{table}")
                selected_row = next(row for row in rows if row[id_index] == selected_id)
                with st.expander("Selected record"):
                    st.json(dict(zip(names, selected_row)))
                    if table == "training_jobs":
                        links = _job_datasets(selected_id, schema)
                        st.markdown("**Dataset relation**")
                        st.dataframe(pd.DataFrame(links), use_container_width=True, hide_index=True) if links else st.caption("No linked datasets recorded.")
        else:
            st.info("No records match the current search and filters.")
    except Exception as exc:
        show_database_error(exc)


def _distinct(table: str, column: str) -> list[str]:
    with closing(connect_readonly()) as conn:
        result = conn.execute(f"SELECT DISTINCT {quote_identifier(column)} FROM {quote_identifier(table)} "
                              f"WHERE {quote_identifier(column)} IS NOT NULL ORDER BY 1 LIMIT 200").fetchall()
    return [str(row[0]) for row in result]


def _count_filtered(table: str, search: str, filters: dict) -> int:
    schema = load_schema()
    names = [field["name"] for field in schema["columns"][table]]
    clauses, params = [], []
    if search.strip() and names:
        clauses.append("(" + " OR ".join(f"CAST({quote_identifier(n)} AS TEXT) LIKE ?" for n in names) + ")")
        params.extend([f"%{search.strip()}%"] * len(names))
    for column, values in filters.items():
        clauses.append(f"{quote_identifier(column)} IN ({','.join('?' for _ in values)})")
        params.extend(values)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(connect_readonly()) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}{where}", params).fetchone()[0]


def _job_datasets(job_id, schema):
    if "training_job_datasets" not in schema["tables"]:
        return []
    link_columns = {field["name"] for field in schema["columns"]["training_job_datasets"]}
    if not {"job_id", "dataset_id"}.issubset(link_columns):
        return []
    with closing(connect_readonly()) as conn:
        links = conn.execute(
            f"SELECT * FROM {quote_identifier('training_job_datasets')} WHERE {quote_identifier('job_id')} = ?",
            (job_id,),
        ).fetchall()
        result = []
        dataset_cols = {field["name"] for field in schema["columns"].get("datasets", [])}
        for link in links:
            item = dict(link)
            if "datasets" in schema["tables"] and "id" in dataset_cols:
                row = conn.execute(
                    f"SELECT * FROM {quote_identifier('datasets')} WHERE {quote_identifier('id')} = ?",
                    (link["dataset_id"],),
                ).fetchone()
                if row:
                    item["dataset"] = dict(row)
            result.append(item)
        return result
