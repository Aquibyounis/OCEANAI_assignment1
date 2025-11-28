import os
import json
import requests
import streamlit as st
from agent import generate_test_cases, generate_selenium_script

BACKEND_URL = "http://127.0.0.1:8000"
LOCAL_HTML_PATH = "/mnt/data/44f69aee-a339-48e3-853c-0ebabea98a94.html"

st.set_page_config(page_title="QA Agent", layout="wide")
st.title("🤖 Autonomous QA Agent")

# session state
if "test_plan" not in st.session_state:
    st.session_state.test_plan = None

# Do NOT auto-populate selected_db from any existing DBs.
# selected_db will only be set when /ingest returns a db_id for the current run.
if "selected_db" not in st.session_state:
    st.session_state.selected_db = None

tab1, tab2, tab3 = st.tabs([
    "🧠 Phase 1: Knowledge Base",
    "🧪 Phase 2: Test Agent",
    "🤖 Phase 3: Selenium Scripts"
])

# ------------------ PHASE 1 ------------------
with tab1:
    st.header("Build Knowledge Base (Ingestion)")

    col1, col2 = st.columns(2)
    with col1:
        uploaded_docs = st.file_uploader("Support Docs (PDF, MD, JSON) — required", accept_multiple_files=True)

    with col2:
        st.markdown("**HTML**")
        html_input_mode = st.radio(
            "Choose HTML input method:",
            ("Upload HTML file", "Paste HTML code"),
            index=0
        )

        uploaded_html = None
        pasted_html = None

        if html_input_mode == "Upload HTML file":
            uploaded_html = st.file_uploader("Target HTML (checkout.html)", type=["html"], key="html_uploader")
        elif html_input_mode == "Paste HTML code":
            pasted_html = st.text_area("Paste HTML code here", height=250, key="html_paste")

    if st.button("🚀 Build Brain", type="primary"):
        # Require support docs
        if not uploaded_docs or len(uploaded_docs) == 0:
            st.warning("Upload at least one support doc (PDF, MD, JSON) — building requires support docs.")
        else:
            # Decide which HTML to use (upload > paste > local-if-selected)
            html_available = False
            html_bytes = None
            html_filename = None

            if html_input_mode == "Upload HTML file" and uploaded_html:
                html_available = True
                html_filename = uploaded_html.name
                html_bytes = uploaded_html.getvalue()
            elif html_input_mode == "Paste HTML code" and pasted_html and pasted_html.strip():
                html_available = True
                html_filename = "pasted.html"
                html_bytes = pasted_html.encode("utf-8")
            elif html_input_mode == "Use local HTML (fallback only)":
                # only allow local if that mode explicitly selected
                if os.path.exists(LOCAL_HTML_PATH):
                    try:
                        with open(LOCAL_HTML_PATH, "rb") as f:
                            html_available = True
                            html_filename = os.path.basename(LOCAL_HTML_PATH)
                            html_bytes = f.read()
                    except Exception as e:
                        st.error(f"Failed to read local HTML: {e}")
                        html_available = False

            if not html_available:
                st.warning("Provide a target HTML: upload a file, paste HTML code, or choose local HTML (and ensure it exists).")
            else:
                with st.spinner("Ingesting and creating a new Knowledge DB..."):
                    files = []
                    # add support docs
                    for d in uploaded_docs:
                        files.append(("files", (d.name, d.getvalue(), d.type)))

                    # attach the chosen HTML bytes
                    files.append(("html_file", (html_filename, html_bytes, "text/html")))

                    try:
                        resp = requests.post(f"{BACKEND_URL}/ingest", files=files, timeout=120)
                    except Exception as e:
                        st.error(f"Connection Error: {e}")
                        resp = None

                    if not resp:
                        st.error("No response from backend. Ensure the backend is running and accessible.")
                    else:
                        if resp.status_code == 200:
                            data = resp.json()
                            st.success(data.get("message", "Ingest completed."))
                            # IMPORTANT: only accept db_id returned by this ingest call
                            db_id = data.get("db_id") or data.get("dbId") or data.get("id")
                            if db_id:
                                st.session_state.selected_db = db_id
                                st.success("New Knowledge DB created and selected for this session.")
                            else:
                                # Do NOT auto-select any old/existing DBs.
                                st.warning(
                                    "Ingest succeeded but backend did not return a new db_id. "
                                    "Please check backend response and try again."
                                )
                        else:
                            st.error(f"Ingest failed: {resp.status_code} - {resp.text}")

# ------------------ PHASE 2 ------------------
with tab2:
    st.header("Generate Test Cases")
    # Strong enforcement: require selected_db created in this session
    if not st.session_state.selected_db:
        st.error("No Knowledge Base available for this session. Please go to Phase 1, upload support docs and HTML, and click 'Build Brain' to create a new Knowledge DB.")
    else:
        user_query = st.text_input("Describe what to test:", "Generate test cases for the discount code feature.")

        if st.button("🔍 Generate Plan"):
            with st.spinner("Thinking..."):
                result = generate_test_cases(st.session_state.selected_db, user_query)

                if isinstance(result, dict) and "error" in result:
                    st.error(result["error"])
                else:
                    if isinstance(result, dict) and "test_cases" in result:
                        st.session_state.test_plan = result["test_cases"]
                    else:
                        st.session_state.test_plan = result

                    st.success(f"Generated {len(st.session_state.test_plan)} Test Cases")

        if st.session_state.test_plan:
            st.subheader("Test Plan JSON")
            st.json(st.session_state.test_plan)

            st.subheader("Detailed View")
            for tc in st.session_state.test_plan:
                t_id = tc.get('id') or tc.get('Test_ID')
                t_title = tc.get('title') or tc.get('Feature')
                t_desc = tc.get('description') or tc.get('Test_Scenario')

                with st.expander(f"{t_id}: {t_title}"):
                    st.write(t_desc)
                    st.caption(f"Expected: {tc.get('expected_result') or tc.get('Expected_Result')}")

# ------------------ PHASE 3 ------------------
with tab3:
    st.header("Generate Automation Scripts")

    if not st.session_state.test_plan:
        st.info("⚠️ Generate test cases in Phase 2 first.")
    elif not st.session_state.selected_db:
        st.warning("No Knowledge Base selected.")
    else:
        def format_func(option):
            t_id = option.get('id') or option.get('Test_ID')
            t_title = option.get('title') or option.get('Feature')
            return f"{t_id} - {t_title}"

        selected_tc = st.selectbox(
            "Select Test Case:",
            st.session_state.test_plan,
            format_func=format_func
        )

        if st.button("⚡ Generate Selenium Code"):
            with st.spinner("Generating..."):
                code = generate_selenium_script(
                    st.session_state.selected_db,
                    selected_tc
                )

                st.subheader("Generated Script")
                st.code(code, language="python")
