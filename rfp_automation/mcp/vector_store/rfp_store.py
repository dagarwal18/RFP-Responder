import chromadb
from chromadb.utils import embedding_functions
import os

class RFPVectorStore:
    def __init__(self):
        # Create persistence directory if not exists
        if not os.path.exists("./chroma_db"):
            os.makedirs("./chroma_db")
            
        # Persistent client
        self.client = chromadb.PersistentClient(path="./chroma_db")
        
        # Use a high quality, fast embedding model
        # This will download the model on first run (might take a moment)
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(name="rfp_chunks", embedding_function=self.ef)

    def add_rfp(self, rfp_id: str, text: str):
        # Retrieve existing to avoid duplicates if re-running
        existing = self.collection.get(where={"rfp_id": rfp_id})
        if existing['ids']:
            print(f"[RFPVectorStore] Clearing existing chunks for {rfp_id}")
            self.collection.delete(where={"rfp_id": rfp_id})

        # Chunking strategy: 1000 chars overlap 100
        chunk_size = 1000
        overlap = 100
        chunks = []
        ids = []
        metadatas = []
        
        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            chunks.append(chunk)
            ids.append(f"{rfp_id}_{i}")
            metadatas.append({"rfp_id": rfp_id, "index": i})
            
        if chunks:
            self.collection.add(documents=chunks, ids=ids, metadatas=metadatas)
            print(f"[RFPVectorStore] Added {len(chunks)} chunks for {rfp_id}")

    def query(self, rfp_id: str, query_text: str, k: int = 3):
        results = self.collection.query(
            query_texts=[query_text],
            n_results=k,
            where={"rfp_id": rfp_id} # Filter by specific RFP
        )
        return results['documents'][0] if results['documents'] else []
