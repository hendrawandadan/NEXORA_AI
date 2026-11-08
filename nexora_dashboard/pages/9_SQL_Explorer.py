import pandas as pd
import sqlite3
import streamlit as st
from nexora_dashboard.database import QueryRejected, execute_readonly
from nexora_dashboard.ui import apply_theme, show_database_error

apply_theme()

st.title("SQL Explorer")
st.caption("Read-only SQL · maximum 1,000 rows · 5 second execution deadline")
query = st.text_area("Query", value="SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name LIMIT 100",
                     height=160, help="Allowed: SELECT, EXPLAIN QUERY PLAN, and approved read-only PRAGMA statements.")
if st.button("Run query", type="primary"):
    try:
        columns, rows, truncated = execute_readonly(query)
        if columns:
            st.dataframe(pd.DataFrame(rows, columns=columns), use_container_width=True, hide_index=True)
            st.caption(f"Returned {len(rows)} row(s)." + (" Results capped at 1,000 rows." if truncated else ""))
        else:
            st.info("Statement completed with no result set.")
    except QueryRejected as exc:
        st.error(str(exc))
    except sqlite3.OperationalError as exc:
        if "interrupt" in str(exc).lower():
            st.error("Query exceeded the 5 second execution deadline.")
        else:
            st.error("SQLite could not execute this read-only query. Check the table and column names.")
    except sqlite3.Error:
        st.error("Query rejected or could not be completed.")
    except Exception:
        st.error("Unexpected query error. No database changes were made.")
