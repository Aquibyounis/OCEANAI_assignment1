import os
import json
import requests
import streamlit as st
from agent import generate_test_cases, generate_selenium_script

BACKEND_URL = "http://127.0.0.1:8000"
# Path of the uploaded HTML file available in the environment (provided to assistant)
LOCAL_HTML_PATH = "/mnt/data/44f69aee-a339-48e3-853c-0ebabea98a94.html"

st.set_page_config(page_title="QA Agent", layout="wide")
st.title("🤖 Autonomous QA Agent")

if "test_plan" not in st.session_state:
    st.session_state.test_plan = None

if "selected_db" not in st.session_state:
    st.session_state.selected_db = None

# Try to fetch latest DB from backend on startup (no UI for choosing)
def fetch_latest_db():
    try:
        resp = requests.get(f"{BACKEND_URL}/databases", timeout=5)
        if resp.status_code == 200:
            data = resp.json().get("databases", [])
            if not data:
                return None
            # data is expected to be a list of dicts with keys "id" and "created_at"
            # choose the most recent by created_at if present
            try:
                latest = sorted(data, key=lambda x: x.get("created_at", ""), reverse=True)[0]
                return latest.get("id")
            except Exception:
                return data[0].get("id")
    except Exception:
        return None

# Auto-populate selected_db from backend (latest) if not already set
if not st.session_state.selected_db:
    latest = fetch_latest_db()
    if latest:
        st.session_state.selected_db = latest

tab1, tab2, tab3 = st.tabs([
    "🧠 Knowledge Base Builder",
    "🧪 Test Case Generator",
    "🧑🏻‍💻 Selenium Script Generator"
])

# ------------------ PHASE 1 ------------------
with tab1:
    st.header("Build Knowledge Base")
    col1, col2 = st.columns(2)
    with col1:
        uploaded_docs = st.file_uploader(
            "Support Docs (PDF, MD, JSON)",
            accept_multiple_files=True
        )
    with col2:
        # add radio for upload vs paste HTML while keeping UI otherwise unchanged
        html_input_mode = st.radio(
            "HTML input method:",
            ("Upload HTML file", "Paste HTML code"),
            index=0
        )

        uploaded_html = None
        pasted_html = None

        if html_input_mode == "Upload HTML file":
            uploaded_html = st.file_uploader(
                "Target HTML (checkout.html)",
                type=["html"]
            )
        elif html_input_mode == "Paste HTML code":
            pasted_html = st.text_area("Paste HTML code here", height=250)

    if st.button("🚀 Build Brain", type="primary"):
        # need at least one support doc AND some HTML (uploaded or pasted)
        has_html = (uploaded_html is not None) or (pasted_html and pasted_html.strip())
        if uploaded_docs and has_html:
            with st.spinner("Ingesting..."):
                files = []

                # support docs
                for d in uploaded_docs:
                    files.append(("files", (d.name, d.getvalue(), d.type)))

                # HTML: always send with filename "checkout.html"
                if uploaded_html is not None:
                    html_bytes = uploaded_html.getvalue()
                    files.append(
                        ("html_file", ("checkout.html", html_bytes, "text/html"))
                    )
                elif pasted_html and pasted_html.strip():
                    files.append(
                        ("html_file", ("checkout.html", pasted_html.encode("utf-8"), "text/html"))
                    )

                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/ingest",
                        files=files,
                        timeout=120
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.success(data.get("message", "Ingest completed."))
                        # backend should return db_id - if so, set it as selected DB
                        db_id = data.get("db_id") or data.get("dbId") or data.get("id")
                        if db_id:
                            st.session_state.selected_db = db_id
                        else:
                            # fallback: re-fetch latest DB list
                            st.session_state.selected_db = fetch_latest_db()
                    else:
                        st.error(resp.text)
                except Exception as e:
                    st.error(f"Connection Error: {e}")
        else:
            st.warning(
                "Upload at least one support doc and provide a target HTML "
                "(either upload or paste the HTML code)."
            )


# ------------------ PHASE 2 ------------------
with tab2:
    st.header("Generate Test Cases")

    if not st.session_state.selected_db:
        st.warning("Please build a knowledge base in Phase 1.")
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

                # 🔹 Normalize `code` to a plain string
                if isinstance(code, bytes):
                    code = code.decode("utf-8", errors="ignore")

                if isinstance(code, dict):
                    code = (
                        code.get("script")
                        or code.get("code")
                        or json.dumps(code, indent=2)
                    )

                if not isinstance(code, str):
                    code = str(code)

                st.subheader("Generated Script")
                st.code(code, language="python")
