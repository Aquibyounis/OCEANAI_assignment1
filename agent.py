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

def extract_selectors(html_content):
    ids = re.findall(r'id="([^"]+)"', html_content)
    classes = re.findall(r'class="([^"]+)"', html_content)

    # Flatten class list (split multi-class entries)
    class_list = []
    for c in classes:
        class_list.extend(c.split())

    buttons = re.findall(r'<button[^>]*>', html_content)
    inputs = re.findall(r'<input[^>]*>', html_content)
    textareas = re.findall(r'<textarea[^>]*>', html_content)

    selector_doc = []

    # Add IDs
    for i in ids:
        selector_doc.append(f"ID: #{i}")

    # Add classes
    for c in class_list:
        selector_doc.append(f"CLASS: .{c}")

    # Add buttons with context
    for btn in buttons:
        if 'class="' in btn:
            cls = re.findall(r'class="([^"]+)"', btn)[0].split()[0]
            selector_doc.append(f"BUTTON: .{cls} button")
        else:
            selector_doc.append("BUTTON: <button> (no class)")

    # Add inputs
    for inp in inputs:
        id_match = re.findall(r'id="([^"]+)"', inp)
        if id_match:
            selector_doc.append(f"INPUT: #{id_match[0]}")

    # Add textareas
    for ta in textareas:
        id_match = re.findall(r'id="([^"]+)"', ta)
        if id_match:
            selector_doc.append(f"TEXTAREA: #{id_match[0]}")

    return "\n".join(selector_doc)


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
1. Analyze the HTML deeply.
2. Generate ONLY test cases that can be executed using the given HTML structure.
3. DO NOT include any steps that involve:
   - filling checkout form
   - clicking Pay
   - submitting checkout
   unless the user explicitly requests a checkout test.
4. Steps should reflect ONLY elements visible in HTML.
5. Steps MUST NOT go beyond the test case goal.
6. Always consider visibility flow:
   - cart-summary is hidden until item added
   - discount section is inside cart-summary
7. FORMAT RULE: Output only RAW JSON ARRAY.
8. Each object MUST contain:
   - id
   - title
   - description
   - preconditions
   - steps (ARRAY OF STRINGS, not one string)
   - expected_result
   - source_file
9. Generate steps inside based on intent of title, Strictly based on TITLE
10. Tell if there will be any alerts inside the steps too like when something trigger alert or message then what to do strictly based on existing html.

OUTPUT FORMAT EXAMPLE (USE THIS EXACT NEWLINE STYLE):

[
  {{
    "id": "TC001",
    "title": "Verify Discount Code",
    "description": "Enter 'SAVE15' and check if price updates",
    "preconditions": "Cart must have items",
    "steps": [
      "Add item to cart",
      "Wait for cart summary to be visible",
      "Enter 'SAVE15'",
      "Click Apply",
      "Verify price is reduced"
    ],
    "expected_result": "Total reduced by 15%",
    "source_file": "checkout.html"
  }}
]
OR 
OUTPUT FORMAT EXAMPLE (USE THIS EXACT NEWLINE STYLE):

[
  {{
    "id": "TC001",
    "title": "Verify Empty cart code",
    "description": "Cart is empty return issue",
    "preconditions": "Cart must be empty",
    "steps": [
      "dont add items to cart. leave it empty." 
      "Check for cart if not found return cart empty",
    ],
    "expected_result": "Cart is empty",
    "source_file": "checkout.html"
  }}
]

REQUIREMENTS ABOUT NEWLINES:
- NO empty lines inside JSON objects
- ONE blank line AFTER the array example
- Steps MUST be an array with ONE step per string
- NO trailing commas anywhere
- NO markdown formatting
- NO explanation

        """
    )

    chain = prompt | llm | StrOutputParser()
    raw = chain.invoke({"context": context_text, "query": query})
    return clean_and_parse_json(raw)

def generate_selenium_script(db_id, selected_test_case):
    html_path, html_filename, html_content = get_stored_html_details()
    selector_map = extract_selectors(html_content)

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
You are a Senior QA Automation Engineer who generates Selenium Python scripts that EXACTLY match the real HTML structure provided. Give only code no extra explaination
Dont hallucinate elements or selectors from HTML code, read every detail and remember and apply the context with only selectors or class names present.
Check what will happen if that step is included in final code, and i need code in order dont mix up.
Dont create full process but understand the where to start and where to end based on test case steps dont over do, Create code until i get output not over coding logic.
You must read:
1. The TEST CASE (steps + expected behavior)
2. The FULL HTML CODE
3. The EXACT list of VALID SELECTORS extracted from that HTML:  
{selector_map}

Your job is to:
- Follow do or dont of steps in test cases.
- Understand the DOM structure
- Understand the user flow and HTML flow sequence
- Map test steps to real HTML elements
- Generate a PERFECT, working Selenium script
- NO hallucinations, NO missing steps, NO altered selectors
- Generate only code no extra steps or talks or extra information.
===============================================================
🔥 STRICT NON-NEGOTIABLE RULES (DO NOT BREAK THESE)
===============================================================

1. **You MUST NOT invent selectors. EVER.**
   You may ONLY use selectors listed in `{selector_map}`.
   If a required selector is NOT in this list:
     → STOP and return an error message.

2. **If a test step uses a selector not found in HTML:**
   - DO NOT guess.
   - DO NOT create.
   - FIX it to the closest REAL selector from `{selector_map}` ONLY IF that selector represents the same element.
   - If no match exists → STOP and output an error.

3. **Selector Format Rules (MANDATORY):**
   - Valid:
       By.ID("id_here")
       By.CLASS_NAME("class_here")
       By.CSS_SELECTOR("parent child")
       By.CSS_SELECTOR(".class button")
       By.CSS_SELECTOR("#id .child")
   - INVALID (never output):
       "#id.class"
       ".class1.class2"
       Any selector not found in {selector_map}

4. **You must understand the HTML flow from the code:**
   - `.product-card button` adds an item to the cart.
   - `#cart-summary` is HIDDEN until an item is added.
   - Discount area exists INSIDE the hidden cart.
   - Form exists on the right column.
   - Shipping radio options exist with updateShipping().
   - “Pay Now” submits the checkout.

5. **HTML HIDDEN LOGIC RULE (CRITICAL):**
   #cart-summary is hidden until at least ONE product is added.
   Therefore, ANY test involving:
       - discount application
       - subtotal
       - total price
       - shipping cost
       - checkout form submission
   MUST begin with:
       click first ".product-card button"
       wait until "#cart-summary" becomes visible

6. **Flow Control Requirements:**
   - You MUST wait for elements properly using WebDriverWait.
   - You MUST fill form fields ONLY if test case requires submission.
   - You MUST NOT add steps that test case does not require.
   - You MUST execute steps in STRICT chronological order from the test case.

7. **Stability Rules:**
   - Add `time.sleep(1)` between high-level actions.
   - Use CSS selectors EXACTLY as provided.
   - Never shorten or rename IDs/classes.

8. **MANDATORY JAVASCRIPT ALERT HANDLING (CRITICAL RULE):**
   The provided HTML triggers alerts in these situations:
     - Applying “OCEAN20”
     - Applying “SAVE15”
     - Applying any invalid discount code
     - Submitting the form with an empty cart

   Therefore you MUST:
     - ALWAYS call `handle_alert(driver)` immediately AFTER clicking `.discount-group button`
     - NEVER perform Selenium clicks or typing while an alert is open
     - Detect and dismiss alerts using the provided handler
     - If alert appears unexpectedly → STOP and raise:
           ERROR: Unexpected alert — test flow blocked.
     - After ANY step that triggers alerts, always call:
           handle_alert(driver)
           time.sleep(1)

===============================================================
🔥 VALID SELECTORS FROM ACTUAL HTML (DO NOT USE ANYTHING OUTSIDE THIS)
===============================================================
{selector_map}

===============================================================
🔥 KNOWN SEMANTIC ROLE OF IMPORTANT SELECTORS (DO NOT MISINTERPRET)
===============================================================
- ".product-card button" → Adds product to cart (triggers visibility of #cart-summary)
- "#cart-summary" → Hidden cart container, visible after adding a product
- "#discount-code" → User enters discount code here
- ".discount-group button" → Apply Discount button
- "#subtotal" → Displays subtotal BEFORE discount
- "#discount-amount" → Displays discounted amount
- "#shipping-cost" → Displays shipping
- "#total-price" → Displays final computed price
- "#checkout-form" → Checkout form wrapper
- "#fullname", "#email", "#address" → Form input fields
- ".pay-btn" → Final submission button inside checkout-form

===============================================================
🔥 OUTPUT FORMAT RULES (NO EXCEPTIONS)
===============================================================
- Output **ONLY** the full Python script
- No explanation
- No markdown (NO ```python)
- The script MUST strictly follow the template provided in the user message
- The block “# --- GENERATED LOGIC STARTS HERE ---” must contain ONLY working Selenium actions

If any required HTML element **does not exist** according to selector_map → output:

    ERROR: Missing required HTML element "<selector_name>"

No further output.

===============================================================
END OF SYSTEM INSTRUCTIONS — NOW FOLLOW THE USER TEMPLATE
===============================================================

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
        raise FileNotFoundError(f"CRITICAL: checkout.html not found. Make sure you are keeping html code in name of checkout.html")

    def handle_alert(driver):
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            text = alert.text
            print(f"Alert: '{{text}}'")
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
            # --- GENERATED LOGIC ENDS HERE ---
            
            print("Test Completed ")
            
        except AssertionError as e:
            print(f"Assertion: {{e}}")
        except Exception as e:
            print(f"Test: {{e}}")
        finally:
            print("✅ Test completed. Cleaning up...")
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
            "filename": html_filename,
            "selector_map": selector_map
        })
        return clean_python_code(raw)
    except Exception as e:
        return f"# Error: {e}"
