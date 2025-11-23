import os
import json
import re
import glob
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI

from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate
)
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

if not os.getenv("OPENROUTER_API_KEY"):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)

raw_key = os.getenv("OPENROUTER_API_KEY")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
STORED_FILES_DIR = "stored_files"
PROJECTS_INDEX = os.path.join("databases", "projects.json")

if raw_key:
    OPENROUTER_API_KEY = raw_key.strip().strip('"').strip("'")
    os.environ["OPENAI_API_KEY"] = OPENROUTER_API_KEY
    os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
    os.environ["OPENAI_API_URL"] = "https://openrouter.ai/api/v1"
    os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY

embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

def load_db_info(db_id):
    with open(PROJECTS_INDEX, "r", encoding="utf-8") as f:
        index = json.load(f)
    return index.get(db_id)

def load_chroma(db_id):
    info = load_db_info(db_id)
    persist_dir = info["persist_dir"]
    return Chroma(persist_directory=persist_dir, embedding_function=embedding_function)

def get_llm():
    return ChatOpenAI(
        model="meta-llama/llama-3.1-8b-instruct",
        openai_api_key=os.environ["OPENROUTER_API_KEY"],
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0,
        default_headers={
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "OceanAI Agent"
        }
    )

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
    except:
        return None, None, None

def clean_and_parse_json(ai_output):
    try:
        text = ai_output.replace("```json", "").replace("```", "")
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1:
            start = text.find("{")
            end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return {"error": "No JSON found"}
        json_str = text[start:end]
        json_str = re.sub(r'\\(?![\\/\"bfnrtu])', '/', json_str)
        return json.loads(json_str)
    except:
        return {"error": "JSON parse error", "raw": ai_output}

def clean_python_code(ai_output):
    code = ai_output.replace("```python", "").replace("```", "")
    if "import os" in code:
        code = code[code.find("import os"):]
    return code.strip()

def generate_test_cases(db_id, query):
    try:
        db = load_chroma(db_id)
    except:
        return {"error": "DB not found"}

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
    raw = chain.invoke({"context": context_text, "query": query})
    return clean_and_parse_json(raw)

def generate_selenium_script(db_id, selected_test_case):
    html_path, html_filename, html_content = get_stored_html_details()
    if not html_content:
        return "# No HTML found."

    try:
        db = load_chroma(db_id)
        q = f"{selected_test_case.get('title')} {selected_test_case.get('description')}"
        results = db.similarity_search(q, k=3)
        context_text = "\n".join([doc.page_content for doc in results])
    except:
        context_text = ""

    llm = get_llm()
    system_template = """
You are a Senior QA Automation Engineer who is expert in creating selenium codes for replacing senior automation software tester.
Refer to html code + test case and based on both use selectors and understand the data flow and create selenium script in python which is 100% accurate with html code.
generate only code no extra explaination no extra texts. just code with template of code.

STRICT RULES (MANDATORY — DO NOT BREAK):
1. You MUST NOT invent selectors.
2. You MUST ONLY use IDs, classes, and structures found inside the provided HTML code.
3. Before generating any step, SCAN the HTML and list the EXACT selectors available:
   - Valid IDs
   - Valid classes
   - Valid tag structures
4. If a selector from the test steps does not exist in the HTML, FIX the selector to the closest valid match.
5. You MUST NOT produce selectors like '#id.class' or '.class1.class2'.
6. You MUST NOT add classes that do not exist in the HTML.
7. You MUST NOT shorten or expand selector names.
8. If a required element does not exist in HTML, you MUST stop and return an error message explaining what is missing.

EXTRACTED SELECTORS FROM HTML:
- Cart summary: #cart-summary
- Discount input: #discount-code
- Discount apply button: button inside .discount-group
- Product card button: .product-card button
- Subtotal: #subtotal
- Discount amount: #discount-amount
- Shipping cost: #shipping-cost
- Total: #total-price
- Form: #checkout-form
- Inputs: #fullname, #email, #address
- Pay now: #checkout-form .pay-btn

ALLOWED SELECTOR FORMAT:
- By.ID("id_here")
- By.CLASS_NAME("class_here")
- By.CSS_SELECTOR("parent child")
- By.CSS_SELECTOR(".class button")
- By.CSS_SELECTOR("#id .child")
(NEVER join ID + class in one token.)

HTML HIDDEN LOGIC RULE:
- #cart-summary is hidden until an item is added.
- So for ANY test involving discounts or totals:
  Step 1 MUST be: click ".product-card button"

OUTPUT REQUIREMENTS:
- Return ONLY the final Python script.
- No markdown, no explanation."""


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
        raise FileNotFoundError(f"CRITICAL: checkout.html not found. Make sure you are keeping html code in name of checkout.html")

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
        raw = chain.invoke({
            "id": selected_test_case.get("id"),
            "title": selected_test_case.get("title"),
            "steps": selected_test_case.get("steps"),
            "expected_result": selected_test_case.get("expected_result"),
            "html_code": html_content,
            "filename": html_filename
        })
        return clean_python_code(raw)
    except Exception as e:
        return f"# Error: {e}"
