import os
import shutil
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from langchain_community.document_loaders import PyPDFLoader, TextLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
import uvicorn

app = FastAPI(title="QA Agent Backend")

# Configuration
CHROMA_PATH = "chroma_db"
STORED_FILES_PATH = "stored_files" # New persistent folder for Phase 3
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Ensure directories exist
os.makedirs(STORED_FILES_PATH, exist_ok=True)

# Initialize Embeddings
embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

class ProcessResponse(BaseModel):
    message: str
    chunks_count: int

def save_file(file: UploadFile, persist: bool = False) -> str:
    """
    Helper to save uploaded file to disk.
    If persist=True, saves to 'stored_files' (keeps it for Phase 3).
    If persist=False, saves to 'temp_data' (deleted after ingestion).
    """
    folder = STORED_FILES_PATH if persist else "temp_data"
    os.makedirs(folder, exist_ok=True)
    
    file_path = os.path.join(folder, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return file_path

def load_documents(file_paths: List[str]):
    """Load documents with robust error handling"""
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
                except:
                    # Fallback if unstructured is missing
                    loader = TextLoader(path, encoding="utf-8")
            elif ext in [".txt", ".html", ".json"]:
                loader = TextLoader(path, encoding="utf-8")
            
            if loader:
                docs = loader.load()
                # Ensure source metadata is set to the filename
                for doc in docs:
                    if "source" not in doc.metadata:
                        doc.metadata["source"] = os.path.basename(path)
                documents.extend(docs)
                
        except Exception as e:
            print(f"Error loading {path}: {e}")
            
    return documents

@app.post("/ingest", response_model=ProcessResponse)
async def ingest_knowledge_base(
    files: List[UploadFile] = File(...), 
    html_file: UploadFile = File(...)
):
    """
    Ingests documents and HTML.
    IMPORTANT: Keeps checkout.html in 'stored_files' for Phase 3 usage.
    """
    temp_paths = []
    
    try:
        # 1. Save Support Docs (Temp)
        for file in files:
            temp_paths.append(save_file(file, persist=False))
            
        # 2. Save HTML File (PERSISTENT)
        # We need the full HTML later for Selenium script generation
        html_path = save_file(html_file, persist=True)
        
        # List of all files to process
        all_paths = temp_paths + [html_path]
        
        # 3. Load Content
        print("--- Starting Document Loading ---")
        raw_documents = load_documents(all_paths)
        
        if not raw_documents:
            raise HTTPException(status_code=400, detail="No content extracted.")

        # 4. Split Text
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            add_start_index=True,
        )
        chunks = text_splitter.split_documents(raw_documents)

        # 5. Vector Database Ingestion
        # This persists the vector data to disk
        Chroma.from_documents(
            documents=chunks, 
            embedding=embedding_function, 
            persist_directory=CHROMA_PATH
        )

        return {
            "message": f"Knowledge Base built! ({len(chunks)} chunks). HTML saved for Phase 3.",
            "chunks_count": len(chunks)
        }

    except Exception as e:
        print(f"Server Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Cleanup ONLY temp support docs, keep HTML
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)