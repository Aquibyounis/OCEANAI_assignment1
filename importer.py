import sys
import os

# --- PATH SETUP ---
# Get the absolute path to the 'agents' folder
current_dir = os.path.dirname(os.path.abspath(__file__))
agents_dir = os.path.join(current_dir, 'agents')

# Add 'agents' to sys.path so Python can find 'helpers' when 'test_case.py' asks for it
if agents_dir not in sys.path:
    sys.path.append(agents_dir)

# --- IMPORTS ---
# Now we can import directly as if the files were in the root
from helpers import *
from test_case import generate_test_cases
from selenium_generator import generate_selenium_script

# --- EXPORTS ---
__all__ = [
    'generate_test_cases',
    'generate_selenium_script',
    'get_llm',
    'load_chroma',
    'get_stored_html_details',
    'extract_selectors',
    'clean_python_code',
    'clean_and_parse_json'
]