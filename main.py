# main.py
import os
import shutil
import uuid
import json
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from langchain_community.document_loaders import PyPDFLoader, TextLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import uvicorn

# -----------------------
# Config
# -----------------------
BASE_DIR = os.path.abspath(".")
DATABASES_ROOT = os.path.join(BASE_DIR, "databases")
STORED_FILES_PATH = os.path.join(BASE_DIR, "stored_files")  # persistent storage for HTML
TEMP_FILES_PATH = os.path.join(BASE_DIR, "temp_data")      # temporary uploads
PROJECTS_INDEX = os.path.join(DATABASES_ROOT, "projects.json")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Developer-provided uploaded file path (will be transformed into a URL by infra if needed)
# (Provided per developer instruction — this points to the uploaded image you used earlier.)
UPLOADED_FILE_PATH_URL = "sandbox:/mnt/data/b8575693-f652-466e-96f9-fec5f91daaf9.png"

# Ensure directories exist
os.makedirs(DATABASES_ROOT, exist_ok=True)
os.makedirs(STORED_FILES_PATH, exist_ok=True)
os.makedirs(TEMP_FILES_PATH, exist_ok=True)

# Initialize Embeddings (single instance per process)
embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

# FastAPI app
app = FastAPI(title="QA Agent Backend - multi-db per upload")

# -----------------------
# Helpers: project index (projects.json)
# -----------------------
def _load_projects_index():
    if not os.path.exists(PROJECTS_INDEX):
        return {}
    try:
        with open(PROJECTS_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_projects_index(index: dict):
    with open(PROJECTS_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)

def register_db_entry(display_name: str, persist_dir: str, extra: Optional[dict] = None):
    index = _load_projects_index()
    db_id = "db_" + uuid.uuid4().hex[:12]
    entry = {
        "id": db_id,
        "name": display_name,
        "persist_dir": persist_dir,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    if extra:
        entry.update(extra)
    index[db_id] = entry
    _save_projects_index(index)
    return entry

def list_db_entries():
    index = _load_projects_index()
    return sorted(index.values(), key=lambda x: x["created_at"], reverse=True)

def get_db_entry(db_id: str):
    index = _load_projects_index()
    return index.get(db_id)

def delete_db_entry(db_id: str):
    index = _load_projects_index()
    entry = index.pop(db_id, None)
    if entry:
        _save_projects_index(index)
    return entry

# -----------------------
# Helpers: file saving & loaders
# -----------------------
def save_file(file: UploadFile, persist: bool = False) -> str:
    folder = STORED_FILES_PATH if persist else TEMP_FILES_PATH
    os.makedirs(folder, exist_ok=True)
    # use a unique filename to avoid collisions
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(folder, filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return file_path

def load_documents(file_paths: List[str]):
    documents = []
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        loader = None
        try:
            if ext == ".pdf":
                loader = PyPDFLoader(path)
            elif ext == ".md":
                try:
                    loader = UnstructuredMarkdownLoader(path)
                except Exception:
                    loader = TextLoader(path, encoding="utf-8")
            elif ext in [".txt", ".html", ".json"]:
                loader = TextLoader(path, encoding="utf-8")
            else:
                # fallback to text loader for unknown types
                loader = TextLoader(path, encoding="utf-8")

            if loader:
                docs = loader.load()
                for doc in docs:
                    # ensure source metadata is set to base filename
                    if not getattr(doc, "metadata", None):
                        doc.metadata = {}
                    doc.metadata["source"] = os.path.basename(path)
                documents.extend(docs)
        except Exception as e:
            # log and skip problematic files
            print(f"[load_documents] error loading {path}: {e}")
            continue
    return documents

# -----------------------
# Helper: create unique chroma persist directory
# -----------------------
def generate_chroma_path() -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid = uuid.uuid4().hex[:8]
    folder = f"chromadb_{ts}_{uid}"
    path = os.path.join(DATABASES_ROOT, folder)
    os.makedirs(path, exist_ok=True)
    return path

# -----------------------
# Request/Response models
# -----------------------
class ProcessResponse(BaseModel):
    message: str
    chunks_count: int
    db_id: Optional[str] = None
    persist_dir: Optional[str] = None

class QueryRequest(BaseModel):
    db_id: str
    query: str
    top_k: Optional[int] = 5

class QueryResponse(BaseModel):
    results: List[str]

# -----------------------
# Endpoints
# -----------------------
@app.post("/ingest", response_model=ProcessResponse)
async def ingest_knowledge_base(
    files: List[UploadFile] = File(...), 
    html_file: UploadFile = File(...)
):
    """
    Ingests uploaded support files (temporary) and an HTML file (persisted).
    Creates a NEW unique Chroma DB folder for this ingestion and registers it.
    """
    temp_paths = []
    try:
        # 1) Save support docs (temp)
        for file in files:
            temp_paths.append(save_file(file, persist=False))

        # 2) Save HTML (persist)
        html_path = save_file(html_file, persist=True)

        # 3) Load & extract content
        all_paths = temp_paths + [html_path]
        raw_documents = load_documents(all_paths)
        if not raw_documents:
            raise HTTPException(status_code=400, detail="No content extracted from uploaded files.")

        # 4) Split text into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            add_start_index=True,
        )
        chunks = text_splitter.split_documents(raw_documents)

        # 5) Create a unique chroma folder and persist DB there
        persist_dir = generate_chroma_path()

        # Use langchain_chroma convenience method to create and persist
        Chroma.from_documents(
            documents=chunks,
            embedding=embedding_function,
            persist_directory=persist_dir
        )

        # 6) Register this DB in projects index so we can list/query/delete
        entry = register_db_entry(
            display_name=f"Ingest {datetime.utcnow().isoformat()}",
            persist_dir=persist_dir,
            extra={"source_html": os.path.basename(html_path)}
        )

        return ProcessResponse(
            message=f"Knowledge Base built",
            chunks_count=len(chunks),
            db_id=entry["id"],
            persist_dir=persist_dir
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ingest] Server error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up ONLY temp uploaded docs; keep persisted HTML in stored_files
        for path in temp_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                print(f"[ingest] error cleaning temp file {path}: {e}")

@app.get("/databases")
def list_databases():
    """Return all registered DB entries from projects.json"""
    entries = list_db_entries()
    return {"count": len(entries), "databases": entries}

@app.delete("/databases/{db_id}")
def delete_database(db_id: str):
    """
    Delete a DB entry and its persisted folder from disk.
    CAUTION: irreversible.
    """
    entry = get_db_entry(db_id)
    if not entry:
        raise HTTPException(status_code=404, detail="DB not found")

    persist_dir = entry["persist_dir"]
    # remove folder
    try:
        if os.path.exists(persist_dir):
            shutil.rmtree(persist_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete DB folder: {e}")

    # remove registry entry
    delete_db_entry(db_id)
    return {"message": f"Deleted DB {db_id} and folder {persist_dir}"}

@app.post("/query", response_model=QueryResponse)
def query_database(req: QueryRequest):
    """
    Query a previously created DB by db_id.
    Returns top-k nearest chunk texts (simple similarity search).
    """
    entry = get_db_entry(req.db_id)
    if not entry:
        raise HTTPException(status_code=404, detail="DB not found")

    persist_dir = entry["persist_dir"]
    if not os.path.exists(persist_dir):
        raise HTTPException(status_code=404, detail="DB persist directory not found on disk")

    try:
        # Recreate a Chroma vectorstore instance pointing to that persist directory
        vectorstore = Chroma(persist_directory=persist_dir, embedding_function=embedding_function)
        # similarity_search is provided by LangChain VectorStore interface
        results = vectorstore.similarity_search(req.query, k=req.top_k or 5)

        # results are Document objects (LangChain). Extract text safely.
        out = []
        for r in results:
            text = getattr(r, "page_content", None) or getattr(r, "content", None) or str(r)
            # Optional: include source meta
            meta = getattr(r, "metadata", {}) or {}
            src = meta.get("source")
            if src:
                out.append(f"[{src}] {text}")
            else:
                out.append(text)

        return QueryResponse(results=out)

    except Exception as e:
        print(f"[query] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Health check
@app.get("/health")
def health():
    return {"status": "ok", "databases_root": DATABASES_ROOT, "stored_files": STORED_FILES_PATH, "temp_files": TEMP_FILES_PATH}

# -----------------------
# Run server
# -----------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
