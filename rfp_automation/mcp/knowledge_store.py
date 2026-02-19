import chromadb
from chromadb.utils import embedding_functions
import os

class KnowledgeBaseStore:
    def __init__(self):
        if not os.path.exists("./chroma_db"):
            os.makedirs("./chroma_db")
            
        self.client = chromadb.PersistentClient(path="./chroma_db")
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        self.collection = self.client.get_or_create_collection(name="knowledge_base", embedding_function=self.ef)
        
        # Seed if empty
        if self.collection.count() == 0:
            self.seed_knowledge()

    def seed_knowledge(self):
        # Real capabilities (Mock data but persistent structure)
        docs = [
            "We have extensive experience in Cloud Migration to AWS and Azure, having completed 50+ enterprise migrations.",
            "Our cybersecurity team is ISO 27001 certified and specializes in Zero Trust architecture.",
            "We provide 24/7 managed support with a 15-minute SLA for critical incidents.",
            "Our AI/ML division extracts insights from unstructured data using RAG pipelines.",
            "We follow Agile methodology with 2-week sprints and daily standups.",
            "We are GDPR and HIPAA compliant.",
            "We have a localized presence in US, UK, and Singapore.",
            "Our rates are competitive: Blended rate of $150/hr for senior engineering."
        ]
        ids = [f"kb_{i}" for i in range(len(docs))]
        metadatas = [{"source": "seed"} for _ in docs]
        
        self.collection.add(documents=docs, ids=ids, metadatas=metadatas)
        print("[KnowledgeBaseStore] Seeded knowledge base with default capabilities.")

    def search(self, query_text: str, k: int = 3):
        results = self.collection.query(
            query_texts=[query_text],
            n_results=k
        )
        return results['documents'][0] if results['documents'] else []
