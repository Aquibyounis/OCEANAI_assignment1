# OceanAI_2.0

A compact, developer-friendly starter for OceanAI_2.0 — includes setup instructions, environment configuration, dependency installation, running the app (Streamlit + agents), a safe ChromaDB seed script, and troubleshooting tips.

---

## Table of Contents

1. [Project Overview](#project-overview)  
2. [Requirements](#requirements)  
3. [Quick start — copy & paste (fresh clone)](#quick-start---copy--paste-fresh-clone)  
4. [Create & activate virtual environment (venv)](#create--activate-virtual-environment-venv)  
5. [Install dependencies](#install-dependencies)  
6. [Environment variables & `.env`](#environment-variables--env)  
7. [Run the app & common commands](#run-the-app--common-commands)  
8. [ChromaDB — local persistence & seeding](#chromadb---local-persistence--seeding)  
9. [Recommended file structure](#recommended-file-structure)  
10. [Troubleshooting](#troubleshooting)  
11. [Security & housekeeping](#security--housekeeping)  
12. [Contributing](#contributing)

---

## Project Overview

OceanAI_2.0 is a local-first developer project using:
- Streamlit (frontend)
- agent(s) / scripts (backend)
- ChromaDB for embeddings & vector store
- OpenAI / OpenRouter or other embedding providers (configurable)

This README focuses on reproducible local setup and quickly getting the app running.

---

## Requirements

- Python **3.10+** (3.11 recommended)
- `git`
- `pip`
- Optional: `virtualenv` (or use `python -m venv`)

---
## Creating Your OpenRouter API Key

To use OpenRouter as your LLM provider, you must generate an API key.

### Steps to create your API key:
1. Visit **OpenRouter**:  
   👉 https://openrouter.ai/
2. Sign in with Google, GitHub, or Email.
3. Open your **Dashboard**.
4. Go to the **API Keys** tab.
5. Click **“Create Key”**.
6. Copy your new key.

Example key format:

## Quick start — copy & paste (fresh clone)

Use this block to get running from a fresh clone (macOS / Linux). It creates a `.venv`, installs, copies `.env.example`, creates the Chroma folder, and runs Streamlit.

```bash
git clone <your-repo-url> myproject && cd myproject
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env   # edit .env to add your keys
mkdir -p chroma_db
streamlit run app.py
