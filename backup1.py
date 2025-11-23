import os
import json
import re
import glob
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI 
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("OPENROUTER_API_KEY"):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)

raw_key = os.getenv("OPENROUTER_API_KEY")

CHROMA_PATH = "chroma_db"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
STORED_FILES_DIR = "stored_files"
UPLOADED_FILE_PATH_URL = "sandbox:/mnt/data/b8575693-f652-466e-96f9-fec5f91daaf9.png"

if not raw_key:
    OPENROUTER_API_KEY = None
else:
    OPENROUTER_API_KEY = raw_key.strip().strip('"').strip("'")
    os.environ["OPENAI_API_KEY"] = OPENROUTER_API_KEY
    os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
    os.environ["OPENAI_API_URL"] = "https://openrouter.ai/api/v1"
    os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY

embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

print("CWD:", os.getcwd())
print("Script dir:", os.path.dirname(__file__))
print("OPENROUTER_API_KEY present:", bool(os.getenv("OPENROUTER_API_KEY")))


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
    # Explicitly setting openai_api_base here ensures the override works
    # even if environment variables are ignored by some library versions.
    return ChatOpenAI(
        model="meta-llama/llama-3.1-8b-instruct",
        openai_api_key=os.environ["OPENROUTER_API_KEY"],
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0,
        default_headers={
            "HTTP-Referer": "http://localhost:8501", # Required by OpenRouter
            "X-Title": "OceanAI Agent"               # Required by OpenRouter
        }
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
        2. Generate a comprehensive Test Plan for the provided HTML.
        3. **FORMAT:** Return a raw JSON LIST (Array of Objects).
        4. **CRITICAL HTML ANALYSIS:**
           - Look for `style="display: none;"` (like #cart-summary).
           - IF a test involves the cart, discount, or checkout, YOU MUST generate a Step 1: "Add item to cart" to make the section visible.
        5. **CSS RULES:** When defining steps or selectors, ALWAYS put a space between parent and child.
           - Correct: "#cart .btn"
           - Wrong: "#cart.btn" (This means ID=cart AND Class=btn on same element).
        
        OUTPUT SCHEMA (JSON List):
        [
            {{
                "id": "TC001",
                "title": "Verify Discount Code",
                "description": "Enter 'SAVE15' and check if price updates",
                "preconditions": "Cart must have items",
                "steps": "1. Add item to cart\\n2. Wait for cart summary\\n3. Enter Code\\n4. Click Apply",
                "expected_result": "Total reduced by 15%",
                "source_file": "checkout.html"
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
    
    # --- STRICT STEP-BY-STEP PROMPT TAILORED FOR YOUR HTML ---
    system_template = """You are a Senior QA Automation Engineer specializing in Python Selenium.
    
    YOUR GOAL: Generate a robust Python Selenium script that strictly follows the Test Case Steps and the provided HTML Structure.
    
    CRITICAL HTML-SPECIFIC RULES (APPLY THESE TO EVERY SCRIPT):
    1. **The "Hidden Cart" Logic:** - In this HTML, `#cart-summary` is HIDDEN (`display: none`) until an item is added.
       - **RULE:** If the test requires entering a code or checking the total, you MUST click an "Add to Cart" button (e.g., `.product-card button`) first, then `WebDriverWait` for `visibility_of_element_located((By.ID, "cart-summary"))`.
    
    2. **The "Pay Now" Flow:**
       - The form (`#checkout-form`) is visible, but submission requires items in the cart.
       - **SEQUENCE:** Add Item -> Wait for Cart -> Apply Discount (if needed) -> Fill Form -> Click Pay Now.
    
    3. **CSS Grammar Fix (Mandatory):**
       - **NEVER** output a selector like `#id.class` or `.class1.class2` (joined).
       - **ALWAYS** insert a space: `#id .class` or `.class1 .class2` (descendant).
       - Example Fix: Turn `#cart-summary.discount-group` into `#cart-summary .discount-group`.
    
    4. **Form Filling:**
       - Use specific IDs found in the HTML: `#fullname`, `#email`, `#address`.
       - Fill them with dummy data if the step implies "Fill form" or "Pay".
       - Do NOT fill them if the test is just checking the empty cart state.
    
    5. **Alert Handling:**
       - Discount codes (`OCEAN20`, `SAVE15`) trigger a browser alert.
       - Use the `handle_alert` helper immediately after clicking "Apply".
    
    STRICT OUTPUT RULES:
    1. Return the FULL Python script using the Skeleton below.
    2. No extra text or markdown.
    3. Use `time.sleep(1)` between major actions to ensure stability.
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
            base_dir / "checkout.html",
            base_dir / "stored_files" / "checkout.html"
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
            print(f"⚠️ Alert: '{{text}}'")
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
            # [AI: 1. SETUP & PAGE LOAD]
            # [AI: 2. ADD ITEM TO CART (TRIGGER VISIBILITY)]
            # [AI: 3. WAIT FOR #cart-summary TO BE VISIBLE]
            # [AI: 4. APPLY DISCOUNT (If in steps)]
            # [AI: 5. FILL FORM (#fullname, #email, #address)]
            # [AI: 6. CLICK PAY (If in steps)]
            # [AI: 7. ASSERTIONS]
            # --- GENERATED LOGIC ENDS HERE ---
            
            print("Test Completed ")
            
        except AssertionError as e:
            print(f"Assertion: {{e}}")
        except Exception as e:
            print(f"Test: {{e}}")
        finally:
            print("Test completed. Cleaning up...")
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