from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate
)
from langchain_core.output_parsers import StrOutputParser

from helpers import (
    get_llm, 
    load_chroma, 
    get_stored_html_details, 
    extract_selectors, 
    clean_python_code
)

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
     - For Negative Tests (e.g., 'Verify Empty', 'Verify Not Visible'): DO NOT use the standard 10-second wait. You MUST use verify_element_not_visible(driver, selector, timeout=2) to avoid waiting unnecessarily.

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
    RE-WRITE THE FULL SKELETON. Do not just output the logic block.
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
    def verify_element_not_visible(driver, selector, timeout=2):
        try:
            # Wait only 2 seconds to see if it appears
            WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(selector))
            raise AssertionError(f"Element {selector_map} appeared, but should be hidden!")
        except TimeoutException:
            # If it times out, that means it's NOT visible, which is GOOD for this test
            pass

    def run_test():
        driver = setup_driver()
        try:
            print(f"🚀 Starting Test: {id}")
            driver.get(get_html_path())
            time.sleep(2)
            
            # [AI: 1. SETUP & PAGE LOAD]
            # [AI: 2. ADD ITEM TO CART (TRIGGER VISIBILITY)]
            # [AI: 3. WAIT FOR #cart-summary TO BE VISIBLE]
            # [AI: 4. APPLY DISCOUNT (If in steps)]
            # [AI: 5. FILL FORM (#fullname, #email, #address)]
            # [AI: 6. CLICK PAY (If in steps)]
            
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