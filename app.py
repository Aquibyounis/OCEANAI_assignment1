import streamlit as st
import requests
import json
from agent import generate_test_cases, generate_selenium_script

BACKEND_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="QA Agent", layout="wide")
st.title("🤖 Autonomous QA Agent")

if "test_plan" not in st.session_state:
    st.session_state.test_plan = None

if "selected_db" not in st.session_state:
    st.session_state.selected_db = None

tab1, tab2, tab3 = st.tabs([
    "📂 Phase 1: Knowledge Base",
    "🧠 Phase 2: Test Agent",
    "💻 Phase 3: Selenium Scripts"
])

# ------------------ PHASE 1 ------------------
with tab1:
    st.header("Build Knowledge Base")
    col1, col2 = st.columns(2)
    with col1:
        uploaded_docs = st.file_uploader("Support Docs (PDF, MD, JSON)", accept_multiple_files=True)
    with col2:
        uploaded_html = st.file_uploader("Target HTML", type=["html"])

    if st.button("🚀 Build Brain", type="primary"):
        if uploaded_docs and uploaded_html:
            with st.spinner("Ingesting..."):
                files = [("files", (d.name, d.getvalue(), d.type)) for d in uploaded_docs]
                files.append(("html_file", (uploaded_html.name, uploaded_html.getvalue(), uploaded_html.type)))

                resp = requests.post(f"{BACKEND_URL}/ingest", files=files)
                if resp.status_code == 200:
                    data = resp.json()
                    st.success(data["message"])
                    st.session_state.selected_db = data["db_id"]
                else:
                    st.error(resp.text)
        else:
            st.warning("Upload all files.")

    st.subheader("Available Databases")
    try:
        db_list = requests.get(f"{BACKEND_URL}/databases").json().get("databases", [])
    except:
        db_list = []

    def db_label(x):
        return f"{x['id']} — {x['created_at']}"

    if db_list:
        choice = st.selectbox(
            "Select Knowledge Base",
            db_list,
            format_func=db_label
        )
        st.session_state.selected_db = choice["id"]
        st.success(f"Selected DB: {st.session_state.selected_db}")

# ------------------ PHASE 2 ------------------
with tab2:
    st.header("Generate Test Cases")

    if not st.session_state.selected_db:
        st.warning("Please build or select a knowledge base in Phase 1.")
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
