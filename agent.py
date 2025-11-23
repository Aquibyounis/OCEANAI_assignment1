import os
import json
import re
import glob
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI 
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser

# --- CONFIGURATION ---
CHROMA_PATH = "chroma_db"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
STORED_FILES_DIR = "stored_files"

# Ensure API Key is set
if "OPENROUTER_API_KEY" not in os.environ:
    os.environ["OPENROUTER_API_KEY"] = "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" 

# --- HELPER: GET STORED HTML ---
def get_stored_html_details():
    if not os.path.exists(STORED_FILES_DIR):
        return None, None, None
    files = glob.glob(os.path.join(STORED_FILES_DIR, "*.html"))
    if not files:
        return None, None, None
    full_path = files[0]
    filename = os.path.basename(full_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return full_path, filename, content
    except Exception:
        return None, None, None

# --- HELPER: CLEAN JSON ---
def clean_and_parse_json(ai_output):
    try:
        text = ai_output.replace("```json", "").replace("```", "")
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1:
            start = text.find("{")
            end = text.rfind("}") + 1
        if start == -1 or end == 0: return {"error": "No JSON found in AI response"}
        
        json_str = text[start:end]
        json_str = re.sub(r'\\(?![\\/\"bfnrtu])', '/', json_str)
        return json.loads(json_str)
    except Exception as e:
        return {"error": f"Failed to parse JSON: {str(e)}", "raw_output": ai_output}

# --- HELPER: CLEAN PYTHON CODE ---
def clean_python_code(ai_output):
    code = ai_output.replace("```python", "").replace("```", "")
    if "import os" in code:
        code = code[code.find("import os"):]
    return code.strip()

# --- HELPER: GET LLM ---
def get_llm():
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        model="meta-llama/llama-3.1-8b-instruct",
        temperature=0
    )

# --- PHASE 2: GENERATE TEST CASES (RAW LIST FORMAT) ---
def generate_test_cases(query: str):
    embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    try:
        db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
    except:
        return {"error": "Knowledge Base not found. Please run Phase 1 ingest."}

    results = db.similarity_search(query, k=6)
    context_text = "\n\n".join([
        f"Source: {doc.metadata.get('source', 'Unknown')}\nContent: {doc.page_content}" 
        for doc in results
    ])

    llm = get_llm()
    
    prompt = ChatPromptTemplate.from_template(
        """
        You are a Senior QA Lead.
        CONTEXT: {context}
        REQUEST: {query}
        
        INSTRUCTIONS:
        1. Analyze the requirements deeply.
        2. Generate a comprehensive Test Plan.
        3. **FORMAT:** Return a raw JSON LIST (Array of Objects).
        4. **PATH FORMAT:** Use Forward Slashes (/) for all paths.
        5. Study (test case + html data flow) strictly and based on that create test case flow.
        
        OUTPUT SCHEMA (JSON List):
        [
            {{
                "id": "TC001",
                "title": "Verify Discount Code",
                "description": "Enter 'SAVE15' and check if price updates",
                "preconditions": "Cart must have items",
                "steps": "1. Add item\\n2. Enter Code\\n3. Click Apply",
                "expected_result": "Total reduced by 15%",
                "source_file": "specs.md"
            }}
        ]
        """
    )
    chain = prompt | llm | StrOutputParser()
    raw_response = chain.invoke({"context": context_text, "query": query})
    return clean_and_parse_json(raw_response)

# --- PHASE 3: GENERATE SELENIUM SCRIPT ---
def generate_selenium_script(selected_test_case: dict):
    
    html_path, html_filename, html_content = get_stored_html_details()
    
    if not html_content:
        return "# Error: No HTML file found in 'stored_files'. Please re-upload in Phase 1."

    context_text = "No extra documentation found."
    try:
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
        query = f"{selected_test_case.get('title')} {selected_test_case.get('description')} {selected_test_case.get('expected_result')}"
        results = db.similarity_search(query, k=3)
        if results:
            context_text = "\n".join([doc.page_content for doc in results])
    except Exception as e:
        print(f"Warning: RAG retrieval failed: {e}")

    llm = get_llm()
    
    # --- STRICT STEP-BY-STEP PROMPT ---
    system_template = """You are a Senior QA Automation Engineer in selenium code generator expert.
    Act according to positive or negative test case.
    write only code no text no extras, Refer to full html_code and then use it like map and understand the flow of data and results and intermediate steps.
    YOUR GOAL: Generate a robust Python Selenium script that strictly follows the Test Case Steps.
    check full code and understand it and then check test case and follow what needs to be done and how much needs to be done instead of going too far.
    and based on test case flow check sequence one by one and predict what will happen in html code and implement it in selenium code and then move to next step in test case and then implement that and predict what will happen after that step  from html and then after steps predict output and check alerts clearly based on html code dont hallucinate just check what is there in html and understand it clearly.
    CRITICAL RULES:
    1. **Follow Steps Exactly:**
       - If the steps are "Add Item -> Enter Code -> Click Apply", then DO NOT fill Name, Email, or Address.
       - Only fill "Required Fields" if the test step explicitly says "Submit Form" or "Pay Now".
    
    2. **Visibility Logic:**
       - Before typing in an input, check if its parent is hidden. If hidden, click a trigger (like "Add to Cart").
    
    3. **Safe Assertions (The Fix):**
       - Use keywords from the 'Expected Result' for validation.
       - Do NOT hardcode generic words like "error" or "success" unless they are in the Expected Result.
       - **Correct Example:** If Expected="Invalid code", use `assert "Invalid" in alert_text`.
       - **Wrong Example:** `assert "error" in alert_text` (This fails if the message is just "Invalid code").
    4. Handle alerts and all and extract the data in html and check according to it
    Use time.sleep(0.5) or time.sleep(1) based on work done in between lines to show user what is happening instead of rapidly doing all.
    Study (test case + html data flow) and based on that create code flow.
    STRICT OUTPUT RULES:
    1. Return the FULL Python script using the Skeleton below.
    2. No extra text or markdown.
    3. Look out for alerts when ever necessary. Last time you skipped some alerts and mishandled codes
    """

    user_template = """
    TEST CASE DETAILS:
    ID: {id}
    Title: {title}
    Steps: {steps}
    Expected: {expected_result}
    
    TARGET HTML FILE: {filename}
    TARGET HTML CONTENT:
    {html_code}
    Include full skeleton not just run_test(): function
    ------------------------------------------------
    GENERATE THE PYTHON SCRIPT USING THIS SKELETON:
    
    import os
    import pathlib
    import time
    import re
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException, NoAlertPresentException

    def setup_driver():
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        driver = webdriver.Chrome(service=service, options=options)
        return driver

    def get_html_path():
        base_dir = pathlib.Path(__file__).parent.absolute()
        possible_paths = [
            base_dir / "{filename}",
            base_dir / "stored_files" / "{filename}"
        ]
        for p in possible_paths:
            if p.exists():
                return p.as_uri()
        raise FileNotFoundError(f"CRITICAL: {filename} not found.")

    def handle_alert(driver):
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            text = alert.text
            print(f" Alert: '{{text}}'")
            alert.accept()
            return text
        except (TimeoutException, NoAlertPresentException):
            return None

    def run_test():
        driver = setup_driver()
        try:
            print(f"🚀 Starting Test: {id}")
            driver.get(get_html_path())
            time.sleep(2)
            
            # --- GENERATED LOGIC STARTS HERE ---
            # [AI: 1. VISIBILITY CHECK (Cart/Form)]
            # [AI: 2. EXECUTE ONLY THE STEPS LISTED IN THE TEST CASE]
            # [AI: 3. HANDLE ALERTS: alert_text = handle_alert(driver)]
            # [AI: 4. ASSERTION: Compare alert_text with keywords from '{expected_result}']
            # --- GENERATED LOGIC ENDS HERE ---
            
            print("Test Completed Successfully")
            
        except AssertionError as e:
            print(f"Assertion: {{e}}")
        except Exception as e:
            print(f"Tested: {{e}}")
        finally:
            print("✅ Testing done")
            print("⏳ Closing browser...")
            time.sleep(3)
            driver.quit()

    if __name__ == "__main__":
        run_test()
    """

    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system_template),
        HumanMessagePromptTemplate.from_template(user_template)
    ])
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        # Map keys safely including 'steps'
        raw_code = chain.invoke({
            "id": selected_test_case.get('id', 'TC000'),
            "title": selected_test_case.get('title', 'Test Case'),
            "steps": str(selected_test_case.get('steps', [])), 
            "expected_result": selected_test_case.get('expected_result', ''),
            "context": context_text,
            "filename": html_filename, 
            "html_code": html_content
        })
        return clean_python_code(raw_code)
    except Exception as e:
        return f"# Error generating script: {str(e)}"