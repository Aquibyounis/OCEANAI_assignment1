import os
import json
import re
import glob
from dotenv import load_dotenv
import bs4
import textwrap

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


def analyze_html(html: str) -> str:
    if not html:
        return "NO HTML PROVIDED"

    soup = bs4.BeautifulSoup(html, "html.parser")

    # Hidden elements (via hidden attr or style="display:none" / aria-hidden)
    hidden = []
    for el in soup.find_all(attrs=True):
        style = el.get("style", "")
        if el.has_attr("hidden") or "display:none" in style.replace(" ", "").lower() or el.get("aria-hidden") == "true":
            hidden.append(el.name + (("#" + el.get("id")) if el.get("id") else ("." + ".".join(el.get("class", [])) if el.get("class") else "")))

    # IDs and high-occurrence classes
    ids = [f"#{tag.get('id')}" for tag in soup.find_all(attrs={"id": True})]
    classes = {}
    for tag in soup.find_all(attrs={"class": True}):
        for c in tag.get("class", []):
            classes[c] = classes.get(c, 0) + 1
    top_classes = sorted(classes.items(), key=lambda x: -x[1])[:8]

    # Find inputs/forms and possible nested dependencies
    forms = []
    for f in soup.find_all("form"):
        forms.append({
            "id": f.get("id"),
            "classes": f.get("class"),
            "inputs": [i.get("name") or i.get("id") or i.get("type") for i in f.find_all(["input","textarea","select"])]
        })

    # Look for scripts that may alter DOM on actions
    script_count = len(soup.find_all("script"))
    inline_script_snippets = []
    for s in soup.find_all("script"):
        if s.string and len(s.string.strip()) > 20:
            inline_script_snippets.append(s.string.strip()[:200].replace("\n", " "))

    parts = []
    parts.append(f"HIDDEN ELEMENTS: {', '.join(hidden) if hidden else 'NONE DETECTED'}")
    parts.append(f"IDS: {', '.join(ids) if ids else 'NONE'}")
    parts.append("COMMON CLASSES: " + (", ".join([f'{c}({cnt})' for c,cnt in top_classes]) if top_classes else "NONE"))
    parts.append(f"FORMS FOUND: {len(forms)}")
    for i, f in enumerate(forms[:5], 1):
        parts.append(f" FORM {i}: id={f['id']}, inputs={f['inputs']}")
    parts.append(f"SCRIPT TAGS: {script_count}")
    if inline_script_snippets:
        parts.append("INLINE SCRIPT SNIPPETS (truncated): " + " || ".join(inline_script_snippets[:2]))

    analysis = "\n".join(parts)
    # Wrap neatly
    return textwrap.dedent(analysis)


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
    system_template = """You are an Expert Selenium Test Engineer with deep understanding of DOM structure and web application data flow.

🎯 YOUR MISSION: Study the HTML structure like a map, understand the data flow like a journey, then write the EXACT Selenium code needed with full code in given template.
give only code and no extra texts or explainations. I dont want only methods but i need full template including all imports and helper functions like from given template.

═══════════════════════════════════════════════════════════════
🧠 STEP 0: ANALYZE HTML STRUCTURE FIRST (MANDATORY)
═══════════════════════════════════════════════════════════════
Before writing ANY code, you MUST study this structural analysis:

{html_analysis}

KEY QUESTIONS YOU MUST ANSWER:
1. Are there hidden elements that need prerequisites?
2. What is the parent-child relationship?
3. What triggers visibility changes?
4. What is the natural data flow sequence?
5. What implicit steps are needed but not stated in test case?

CRITICAL UNDERSTANDING:
- If #cart-summary is hidden → ALL its children are inaccessible
- If discount input is INSIDE hidden cart → MUST show cart first
- If form is INSIDE hidden section → MUST trigger visibility first
- Parent visibility = Child accessibility

═══════════════════════════════════════════════════════════════
🔍 STEP 1: DERIVE IMPLICIT PREREQUISITES FROM HTML STRUCTURE
═══════════════════════════════════════════════════════════════
INTELLIGENCE RULES:

IF test step mentions: "Apply discount code"
  AND HTML shows: #discount-code is inside hidden #cart-summary
  THEN implicit prerequisite: ADD ITEM TO CART FIRST
  
IF test step mentions: "Fill checkout form"
  AND HTML shows: form fields inside hidden container
  THEN implicit prerequisite: TRIGGER CONTAINER VISIBILITY
  
IF test step mentions: "Verify total price"
  AND HTML shows: #total-price inside hidden #cart-summary
  THEN implicit prerequisite: ENSURE CART IS VISIBLE

YOUR JOB: Deduce these prerequisites BY ANALYZING HTML STRUCTURE, not by being told explicitly.

═══════════════════════════════════════════════════════════════
🎯 STEP 2: BUILD EXECUTION PLAN
═══════════════════════════════════════════════════════════════
For the given test case, create a mental execution plan:

1. PREREQUISITES (derived from HTML structure):
   - What must be visible?
   - What state must exist?
   - What elements must be accessible?

2. TEST STEPS (from test case):
   - Map each step to HTML elements
   - Identify triggers (clicks, inputs)
   - Predict state changes

3. VERIFICATION (expected result):
   - What to assert?
   - Where to find the result?
   - How to extract it?

═══════════════════════════════════════════════════════════════
🚨 CRITICAL INTELLIGENCE PATTERNS
═══════════════════════════════════════════════════════════════

PATTERN 1: Hidden Cart Detection
IF you see in HTML analysis:
  - "HIDDEN ELEMENTS: div#cart-summary"
  - "discount section inside #cart-summary"
  
AND test case requires:
  - Applying discount
  - Checking prices
  - Accessing cart elements
  
THEN you MUST automatically:
  1. Click ".product-card button" to add item
  2. Wait for "#cart-summary" visibility
  3. THEN proceed with test steps

PATTERN 2: Parent-Child Dependency
IF HTML shows:
  - Element A is parent
  - Element B is child of A
  - Element A is hidden
  
AND test requires Element B:
  
THEN you MUST:
  1. Make Element A visible first
  2. Wait for Element A to appear
  3. Access Element B

PATTERN 3: JavaScript Alert Flow
IF test step involves:
  - Discount code application
  - Form submission
  - Invalid input
  
THEN expect alert:
  1. Perform action
  2. IMMEDIATELY call handle_alert(driver)
  3. Capture alert text if needed for assertion
  4. Continue

═══════════════════════════════════════════════════════════════
🔒 SELECTOR WHITELIST (USE ONLY THESE)
═══════════════════════════════════════════════════════════════
{selector_map}

═══════════════════════════════════════════════════════════════
⚙️ CODE GENERATION RULES
═══════════════════════════════════════════════════════════════

1. IMPLICIT SETUP PHASE:
   - Add prerequisites based on HTML structure analysis
   - Make hidden elements visible if test needs them
   - Don't wait for explicit instruction

2. EXPLICIT TEST PHASE:
   - Execute steps from test case exactly
   - Use correct selectors from whitelist
   - Handle alerts immediately after triggers

3. VERIFICATION PHASE:
   - Extract result from correct element
   - Use flexible assertions (substring, numeric comparison)
   - Account for text variations

4. SCOPE CONTROL:
   - Add implicit prerequisites ✓
   - Execute test steps ✓
   - Verify expected result ✓
   - Stop here ✗ (don't add extra actions)

═══════════════════════════════════════════════════════════════
💡 EXAMPLE REASONING PROCESS
═══════════════════════════════════════════════════════════════

Test Case: "Verify discount code 'SAVE15' applies correctly"
Steps: "1. Enter SAVE15 in discount field\n2. Click Apply\n3. Check discount appears"

YOUR REASONING:
1. Read HTML analysis → #discount-code is inside hidden #cart-summary
2. Deduce prerequisite → Cart must be visible first
3. Check data flow → Adding product makes cart visible
4. Build plan:
   a) [IMPLICIT] Add product to cart
   b) [IMPLICIT] Wait for #cart-summary to appear
   c) [EXPLICIT] Enter "SAVE15" in #discount-code
   d) [EXPLICIT] Click .discount-group button
   e) [IMPLICIT] Handle alert
   f) [EXPLICIT] Verify discount applied
5. Generate code implementing a→f

═══════════════════════════════════════════════════════════════
📤 OUTPUT FORMAT
═══════════════════════════════════════════════════════════════
- Output ONLY Python code (no markdown)
- Add comments explaining implicit vs explicit steps
- Use smart assertions (flexible matching)
- Include error handling for each action
- Stop after test objective achieved

IF MISSING SELECTOR:
Output: ERROR: Selector '<name>' not found in HTML for step '<step>'
"""

    user_template = """═══════════════════════════════════════════════════════════════
📋 TEST CASE TO IMPLEMENT
═══════════════════════════════════════════════════════════════
ID: {id}
TITLE: {title}
DESCRIPTION: {description}
PRECONDITIONS: {preconditions}

TEST STEPS (explicit instructions):
{steps}

EXPECTED RESULT:
{expected_result}

═══════════════════════════════════════════════════════════════
🗺️ HTML STRUCTURE ANALYSIS (YOUR MAP)
═══════════════════════════════════════════════════════════════
{html_analysis}

═══════════════════════════════════════════════════════════════
📍 AVAILABLE SELECTORS
═══════════════════════════════════════════════════════════════
{selector_map}

═══════════════════════════════════════════════════════════════
📄 COMPLETE HTML SOURCE
═══════════════════════════════════════════════════════════════
{html_code}

═══════════════════════════════════════════════════════════════
🎯 YOUR TASK
═══════════════════════════════════════════════════════════════
1. Study the HTML structure analysis above
2. Identify hidden elements and their children
3. Determine implicit prerequisites from structure (not from test case)
4. Generate Selenium code that:
   - Handles implicit prerequisites automatically
   - Handle alerts or messages based on HTML code or data flow.
   - Executes explicit test steps
   - Verifies expected results
   - Stops after achieving test objective

TEMPLATE:
═══════════════════════════════════════════════════════════════
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
    raise FileNotFoundError(f"CRITICAL: checkout.html not found")

def handle_alert(driver):
    try:
        WebDriverWait(driver, 3).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        text = alert.text
        print(f"Alert detected: '{{text}}'")
        alert.accept()
        return text
    except (TimeoutException, NoAlertPresentException):
        return None

def run_test():
    driver = setup_driver()
    try:
        print(f"🚀 Test: {id} - {title}")
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
        
        print("Tested")
        
    except AssertionError as e:
        print(f"Assertion: {{e}}")
    except Exception as e:
        print(f"Test: {{e}}")
    finally:
        print("✅ TESTING DONE")
        time.sleep(3)
        driver.quit()

if __name__ == "__main__":
    run_test()
═══════════════════════════════════════════════════════════════

NOW GENERATE THE CODE:
Analyze the HTML structure → Derive prerequisites → Implement test → Verify result
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
            # Provide description & preconditions (default to empty string if missing)
            "description": selected_test_case.get("description", ""),
            "preconditions": selected_test_case.get("preconditions", ""),
            "steps": selected_test_case.get("steps", ""),
            "expected_result": selected_test_case.get("expected_result", ""),
            # html_analysis MUST be present for your system prompt
            "html_analysis": analyze_html(html_content),
            "html_code": html_content,
            "filename": html_filename,
            "selector_map": selector_map,
        })
        return clean_python_code(raw)
    except Exception as e:
        return f"# Error: {e}"
