import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(
    page_title="JBM Consulting BI",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

st.sidebar.title("JBM Consulting")
st.sidebar.markdown("Business Intelligence Platform")

page = st.sidebar.radio(
    "Select Dashboard",
    ["Sales & CRM", "Finance & Invoicing"],
)

if page == "Sales & CRM":
    import crm_dashboard as crm
    crm.show()
elif page == "Finance & Invoicing":
    import invoicing_dashboard as inv
    inv.show()
