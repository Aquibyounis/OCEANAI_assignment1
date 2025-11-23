from dotenv import load_dotenv
import os

print("Loading .env…")
load_dotenv()

print("Key:", os.getenv("OPENROUTER_API_KEY"))
