import os
import json
import re
import glob
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI

# --- Configuration & Setup ---
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

# --- Helper Functions ---

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