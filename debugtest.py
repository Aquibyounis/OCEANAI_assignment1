import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- CONFIGURATION ---
CHROMA_PATH = "chroma_db"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

def inspect_database():
    print("--- 🔍 INSPECTING CHROMA DATABASE ---")
    
    # 1. Initialize Embedding Function
    embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    # 2. Connect to DB
    if not os.path.exists(CHROMA_PATH):
        print(f"❌ Error: Database folder '{CHROMA_PATH}' does not exist. Run Phase 1 first.")
        return

    db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
    
    # 3. Get all data (using the underlying collection object)
    # Chroma stores data in a collection. We access it directly to peek at the data.
    collection = db._collection
    count = collection.count()
    
    print(f"✅ Connected to Database. Total Chunks Found: {count}")
    
    if count == 0:
        print("⚠️  Database is empty! Ingestion (Phase 1) failed or didn't save.")
        return

    # 4. Get all metadata to find unique sources
    # We fetch just the metadata to list files
    data = collection.get(include=['metadatas'])
    
    all_sources = set()
    for meta in data['metadatas']:
        if meta and 'source' in meta:
            all_sources.add(meta['source'])
            
    print("\n📂 SOURCES CURRENTLY IN DATABASE:")
    for source in all_sources:
        print(f"   - {source}")

    # 5. Test a specific query with scores
    test_query = "Generate test cases for the discount code functionality."
    print(f"\n🎯 TEST QUERY: '{test_query}'")
    print("   (Lower score = Closer match/Better relevance)")
    
    # Fetch more results (k=10) to see if other files appear lower down the list
    results_with_scores = db.similarity_search_with_score(test_query, k=10)
    
    print("\n📊 TOP 10 RETRIEVAL RESULTS:")
    for i, (doc, score) in enumerate(results_with_scores):
        source = doc.metadata.get("source", "Unknown")
        content_preview = doc.page_content[:100].replace("\n", " ") + "..."
        print(f"   {i+1}. [{source}] Score: {score:.4f} | Content: {content_preview}")

if __name__ == "__main__":
    inspect_database()