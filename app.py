import streamlit as st
import requests
import json
# Import logic from our new agent.py file
from agent import generate_test_cases, generate_selenium_script

# Configuration
BACKEND_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="QA Agent", layout="wide")
st.title("🤖 Autonomous QA Agent")

# Initialize Session State for persistent data across tabs
if "test_plan" not in st.session_state:
    st.session_state.test_plan = None

# Tabs for different Phases
tab1, tab2, tab3 = st.tabs(["📂 Phase 1: Knowledge Base", "🧠 Phase 2: Test Agent", "💻 Phase 3: Selenium Scripts"])

# --- PHASE 1: INGESTION ---
with tab1:
    st.header("Build Knowledge Base")
    col1, col2 = st.columns(2)
    with col1:
        uploaded_docs = st.file_uploader("Support Docs (PDF, MD, JSON)", accept_multiple_files=True)
    with col2:
        uploaded_html = st.file_uploader("Target HTML (checkout.html)", type=["html"])

    if st.button("🚀 Build Brain", type="primary"):
        if uploaded_docs and uploaded_html:
            with st.spinner("Ingesting..."):
                try:
                    files = [("files", (d.name, d.getvalue(), d.type)) for d in uploaded_docs]
                    files.append(("html_file", (uploaded_html.name, uploaded_html.getvalue(), uploaded_html.type)))
                    
                    resp = requests.post(f"{BACKEND_URL}/ingest", files=files)
                    if resp.status_code == 200:
                        st.success(resp.json()["message"])
                    else:
                        st.error(resp.text)
                except Exception as e:
                    st.error(f"Connection Error: {e}")
        else:
            st.warning("Upload all files.")

# --- PHASE 2: TEST CASE GENERATION ---
with tab2:
    st.header("Generate Test Cases")
    user_query = st.text_input("Describe what to test:", "Generate test cases for the discount code feature.")
    
    if st.button("🔍 Generate Plan"):
        with st.spinner("Thinking..."):
            result = generate_test_cases(user_query)
            if isinstance(result, dict) and "error" in result:
                st.error(result["error"])
            else:
                # Handle both {test_cases: [...]} and raw [...] formats
                if isinstance(result, dict) and "test_cases" in result:
                    st.session_state.test_plan = result["test_cases"]
                else:
                    st.session_state.test_plan = result
                
                st.success(f"Generated {len(st.session_state.test_plan)} Test Cases")

    # Display Results
    if st.session_state.test_plan:
        st.subheader("Test Plan (Raw JSON)")
        st.json(st.session_state.test_plan)
        
        st.subheader("Detailed View")
        for tc in st.session_state.test_plan:
            # Fallback for keys to handle both old and new formats if needed
            t_id = tc.get('id') or tc.get('Test_ID')
            t_title = tc.get('title') or tc.get('Feature')
            t_desc = tc.get('description') or tc.get('Test_Scenario')
            
            with st.expander(f"{t_id}: {t_title}"):
                st.write(t_desc)
                st.caption(f"Expected: {tc.get('expected_result') or tc.get('Expected_Result')}")

# --- PHASE 3: SELENIUM SCRIPT ---
with tab3:
    st.header("Generate Automation Scripts")
    
    if not st.session_state.test_plan:
        st.info("⚠️ Please generate test cases in Phase 2 first.")
    else:
        # Helper to format label safely
        def format_func(option):
            t_id = option.get('id') or option.get('Test_ID')
            t_title = option.get('title') or option.get('Feature')
            return f"{t_id} - {t_title}"

        # Dropdown to select a test case
        selected_tc = st.selectbox(
            "Select Test Case to Automate:", 
            st.session_state.test_plan,
            format_func=format_func
        )
        
        if st.button("⚡ Generate Selenium Code"):
            with st.spinner("Reading HTML & Writing Code..."):
                script_code = generate_selenium_script(selected_tc)
                
                st.subheader("🐍 Generated Python Script")
                st.code(script_code, language="python")
                st.caption("Copy this code to a .py file to run it.")