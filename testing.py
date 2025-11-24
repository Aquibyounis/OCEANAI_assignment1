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
        print(f"Alert: '{text}'")
        alert.accept()
        return text
    except (TimeoutException, NoAlertPresentException):
        return None

def run_test():
    driver = setup_driver()
    try:
        print(f"🚀 Starting Test: TC003")
        driver.get(get_html_path())
        time.sleep(2)
        
        # --- GENERATED LOGIC STARTS HERE ---
        # [AI: 1. SETUP & PAGE LOAD]
        # [AI: 2. ADD ITEM TO CART (TRIGGER VISIBILITY)]
        driver.find_element(By.CSS_SELECTOR, ".product-card button").click()
        time.sleep(1)
        # [AI: 3. WAIT FOR #cart-summary TO BE VISIBLE]
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "cart-summary")))
        # [AI: 4. APPLY DISCOUNT (If in steps)]
        driver.find_element(By.ID, "discount-code").send_keys("INVALIDCODE")
        driver.find_element(By.CSS_SELECTOR, ".discount-group button").click()
        handle_alert(driver)
        time.sleep(1)
        # [AI: 5. FILL FORM (#fullname, #email, #address)]
        driver.find_element(By.ID, "fullname").send_keys("John Doe")
        driver.find_element(By.ID, "email").send_keys("johndoe@example.com")
        driver.find_element(By.ID, "address").send_keys("123 Main St")
        # [AI: 6. CLICK PAY (If in steps)]
        driver.find_element(By.CSS_SELECTOR, ".pay-btn").click()
        handle_alert(driver)
        time.sleep(1)
        # --- GENERATED LOGIC ENDS HERE ---
        
        print("Test Completed ")
        
    except AssertionError as e:
        print(f"Assertion: {e}")
    except Exception as e:
        print(f"Test: {e}")
    finally:
        print("✅ Test completed. Cleaning up...")
        print("⏳ Closing browser...")
        time.sleep(3)
        driver.quit()

if __name__ == "__main__":
    run_test()