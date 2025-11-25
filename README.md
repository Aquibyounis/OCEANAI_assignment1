# OceanAI_Autonomous QA Agent for Test Case and Script Generation

This project includes setup instructions, environment configuration, dependency installation, running the app (Streamlit + agents), and few troubleshooting tips.

---

## Project Overview

OceanAI is built on RAG with 2 Agents using:
- Streamlit (frontend)
- agents / Orchestration (backend)
- ChromaDB for embeddings & vector store
- OpenRouter and Huggingface embeddings

This README focuses on reproducible local setup and quickly getting the app running.

---

## Table of Contents
- [Software Requirements](#software-requirements)
- [Quick Setup](#quick-setup-windows---powershell)
- [Create `.env` & Database Folder](#create-env--database-folder)
- [Create OpenRouter API Key](#create-openrouter-api-key)
- [Running Locally (two terminals)](#running-locally-two-terminals)
- [Troubleshooting](#troubleshooting)


---

## Software Requirements

- Python **3.10+** (3.11 recommended)
- `git`
- `pip`
- Optional: `virtualenv` (or use `python -m venv`)

---
## Instructions to set up repo on your local machine
```bash
git clone "https://github.com/Aquibyounis/OCEANAI_assignment1.git"
cd OCEANAI_assignment1
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```
## Creating .env & databases
```
"OPENROUTER_API_KEY=" | Out-File .env 
mkdir -p chroma_db
```
Paste the API key (you will create in next step) with **NO** Quotations

Format is - 
```
OPENROUTER_API_KEY=sk-or-v1-5.....c
```

## Creating Your OpenRouter API Key

To use OpenRouter as your LLM provider, you must generate an API key.

### Steps to create your API key:
1. Visit **OpenRouter**:  
   ➡️ https://openrouter.ai/
2. Sign in with Google, GitHub, or Email.
3. Open your **Dashboard**.
4. Go to the **API Keys** tab.
5. Click **“Create Key”**.
6. Copy your new key.
7. Paste it in env with no quotations.


## Running the code

### Open 2 terminals in vscode
### Terminal-1: 
```
venv\scripts\activate
streamlit run app.py
```
### Terminal-2: 
```
venv\scripts\activate
python main.py
```

## 🛠️ Troubleshooting

Below are the most common issues you may encounter while running OceanAI locally, along with their solutions.

---

## 1. Virtual Environment Not Activating
- If venv not found 
```
python -m venv venv
```
Fix:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
venv\Scripts\Activate.ps1
```
## 2. Packages Not Installed / ModuleNotFoundError

If you get:

- ModuleNotFoundError


Fix:
```
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
## 3. .env Not Loading (API Key Missing)

### Common mistakes:

- .env missing

- .env in wrong folder

- Key written with quotes

- Wrong variable name

### Correct format:
```
OPENROUTER_API_KEY=sk-or-v1-123abc...
```
Restart terminal after editing .env.
##  4. OpenRouter API Errors

### Error:

- 401 Unauthorized

- Invalid API Key


Fix:

- Create a new key at: https://openrouter.ai/api-keys

- Add to .env (no quotes)

- Restart both terminals

### 5. Streamlit Port Already in Use

- Port 8501 is already in use


Run:
```
streamlit run app.py --server.port 8502
```

### 6. HuggingFace Embedding Model Errors

If download fails:

- SSL error
- Connection failed


Fix:
```
pip install --upgrade certifi
```
Or connect to VPN.

### 7. Wrong Working Directory

- Ensure you're inside the project folder:
```
cd OCEANAI_assignment1
```

### 8. Slow or Hanging on First Run

This is normal because:
- HuggingFace model is downloading
- ChromaDB is initializing
- Wait for first run to complete.

### 9. JSON Parse Error in Tese Case generation

Fix: 
- Click **Generate** option again

### 10. Half or Invalid code 
Fix: 
- Click **Generate** button again.




