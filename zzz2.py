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

    class_list = []
    for c in classes:
        class_list.extend(c.split())

    buttons = re.findall(r'<button[^>]*>', html_content)
    inputs = re.findall(r'<input[^>]*>', html_content)
    textareas = re.findall(r'<textarea[^>]*>', html_content)

    selector_doc = []

    for i in ids:
        selector_doc.append(f"ID: #{i}")

    for c in class_list:
        selector_doc.append(f"CLASS: .{c}")

    for btn in buttons:
        if 'class="' in btn:
            cls = re.findall(r'class="([^"]+)"', btn)[0].split()[0]
            selector_doc.append(f"BUTTON: .{cls} button")
        else:
            selector_doc.append("BUTTON: <button> (no class)")

    for inp in inputs:
        id_match = re.findall(r'id="([^"]+)"', inp)
        if id_match:
            selector_doc.append(f"INPUT: #{id_match[0]}")

    for ta in textareas:
        id_match = re.findall(r'id="([^"]+)"', ta)
        if id_match:
            selector_doc.append(f"TEXTAREA: #{id_match[0]}")

    return "\n".join(selector_doc)

def analyze_html_structure(html_content):
    """Analyzes HTML to extract DOM structure, visibility logic, and data flow"""
    
    analysis = {
        "hidden_elements": [],
        "conditional_visibility": [],
        "parent_child_relationships": [],
        "event_triggers": [],
        "data_flow_sequence": []
    }
    
    # Find hidden elements
    hidden_pattern = r'<(\w+)[^>]*style="[^"]*display:\s*none[^"]*"[^>]*(?:id="([^"]+)")?[^>]*>'
    for match in re.finditer(hidden_pattern, html_content, re.IGNORECASE):
        element_type = match.group(1)
        element_id = match.group(2) if match.group(2) else "unknown"
        analysis["hidden_elements"].append(f"{element_type}#{element_id}")
    
    # Find parent-child relationships for hidden containers
    cart_pattern = r'<div[^>]*id="cart-summary"[^>]*>(.+?)</div>\s*</div>'
    cart_match = re.search(cart_pattern, html_content, re.DOTALL | re.IGNORECASE)
    if cart_match:
        inner_content = cart_match.group(1)
        if 'discount' in inner_content.lower():
            analysis["parent_child_relationships"].append(
                "CRITICAL: #cart-summary contains discount section (both hidden initially)"
            )
        if 'id="subtotal"' in inner_content:
            analysis["parent_child_relationships"].append(
                "CRITICAL: #cart-summary contains price elements (#subtotal, #total-price)"
            )
    
    # Detect JavaScript event triggers
    onclick_pattern = r'onclick="([^"]+)"'
    for match in re.finditer(onclick_pattern, html_content):
        func_call = match.group(1)
        analysis["event_triggers"].append(f"JavaScript: {func_call}")
    
    # Analyze conditional visibility logic
    if 'style="display: none;"' in html_content and 'cart-summary' in html_content:
        analysis["conditional_visibility"].append(
            "VISIBILITY RULE: #cart-summary hidden until item added to cart"
        )
        analysis["conditional_visibility"].append(
            "CONSEQUENCE: All child elements inside #cart-summary are inaccessible until cart has items"
        )
    
    # Build data flow sequence
    if '.product-card' in html_content and 'addToCart' in html_content:
        analysis["data_flow_sequence"].append("STEP 1: User clicks product 'Add to Cart' button")
        analysis["data_flow_sequence"].append("STEP 2: JavaScript addToCart() executes")
        analysis["data_flow_sequence"].append("STEP 3: #cart-summary becomes visible (display:block)")
        analysis["data_flow_sequence"].append("STEP 4: Cart elements (#discount-code, #subtotal, etc.) become accessible")
        analysis["data_flow_sequence"].append("STEP 5: User can now interact with cart features")
    
    # Format output
    output = []
    output.append("═══ HTML STRUCTURE ANALYSIS ═══\n")
    
    if analysis["hidden_elements"]:
        output.append("🔒 HIDDEN ELEMENTS (display:none):")
        for elem in analysis["hidden_elements"]:
            output.append(f"  - {elem}")
        output.append("")
    
    if analysis["conditional_visibility"]:
        output.append("⚠️  CONDITIONAL VISIBILITY LOGIC:")
        for rule in analysis["conditional_visibility"]:
            output.append(f"  - {rule}")
        output.append("")
    
    if analysis["parent_child_relationships"]:
        output.append("🔗 PARENT-CHILD DEPENDENCIES:")
        for rel in analysis["parent_child_relationships"]:
            output.append(f"  - {rel}")
        output.append("")
    
    if analysis["data_flow_sequence"]:
        output.append("📊 DATA FLOW SEQUENCE:")
        for step in analysis["data_flow_sequence"]:
            output.append(f"  {step}")
        output.append("")
    
    if analysis["event_triggers"]:
        output.append("⚡ JAVASCRIPT EVENT TRIGGERS:")
        for trigger in analysis["event_triggers"][:5]:  # Limit to 5
            output.append(f"  - {trigger}")
        output.append("")
    
    return "\n".join(output)


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
        """You are an Expert QA Test Designer. Your ONLY job is to analyze requirements and design precise, actionable test cases.

CONTEXT:
{context}

USER REQUEST:
{query}

CRITICAL RULES:
1. Each test case tests ONE specific behavior
2. Steps must be MINIMAL and SPECIFIC - only include actions directly related to the test objective
3. Do NOT add extra steps beyond what's needed to verify the specific behavior
4. Preconditions identify what must be true BEFORE the test starts
5. Steps describe ONLY the actions needed to test the specific functionality
6. Expected result describes ONLY the outcome being verified

EXAMPLE - GOOD vs BAD:
❌ BAD (over-specified):
Test: "Verify discount code applies"
Steps: "1. Add item to cart\n2. Wait for cart\n3. Enter code\n4. Click apply\n5. Fill name\n6. Fill email\n7. Submit form"
→ Why bad? Steps 5-7 are NOT needed to verify discount application

✅ GOOD (precise):
Test: "Verify discount code applies"
Preconditions: "Cart contains at least one item"
Steps: "1. Enter discount code 'SAVE15'\n2. Click Apply button"
Expected: "Discount of 15% applied, total price reduced accordingly"

OUTPUT FORMAT (JSON array only, no markdown):
[
  {{
    "id": "TC001",
    "title": "Brief test objective",
    "description": "What specific behavior is being tested",
    "preconditions": "State that must exist before test runs",
    "steps": "Numbered steps - ONLY actions needed for THIS test",
    "expected_result": "Specific, observable outcome",
    "source_file": "filename.html"
  }}
]

Now generate test cases following these rules exactly."""
    )

    chain = prompt | llm | StrOutputParser()
    raw = chain.invoke({"context": context_text, "query": query})
    return clean_and_parse_json(raw)

def generate_selenium_script(db_id, selected_test_case):
    html_path, html_filename, html_content = get_stored_html_details()
    selector_map = extract_selectors(html_content)
    html_analysis = analyze_html_structure(html_content)

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

🎯 YOUR MISSION: Study the HTML structure like a map, understand the data flow like a journey, then write the EXACT Selenium code needed.

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
        
        # [IMPLICIT PREREQUISITES - Based on HTML structure analysis]
        # TODO: Add implicit setup steps if HTML structure requires them
        
        # [EXPLICIT TEST STEPS - From test case]
        # TODO: Implement each step from test case
        
        # [VERIFICATION - Expected result]
        # TODO: Assert expected outcome with flexible matching
        
        # --- GENERATED LOGIC ENDS HERE ---
        
        print("✅ Test Passed")
        
    except AssertionError as e:
        print(f"❌ Assertion Failed: {{e}}")
    except Exception as e:
        print(f"❌ Test Error: {{e}}")
    finally:
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
            "description": selected_test_case.get("description", ""),
            "preconditions": selected_test_case.get("preconditions", "None"),
            "steps": selected_test_case.get("steps"),
            "expected_result": selected_test_case.get("expected_result"),
            "html_code": html_content,
            "filename": html_filename,
            "selector_map": selector_map,
            "html_analysis": html_analysis
        })
        return clean_python_code(raw)
    except Exception as e:
        return f"# Error: {e}"