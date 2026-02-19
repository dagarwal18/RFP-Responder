from pymongo import MongoClient
import os

def get_mongo_client():
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    return MongoClient(uri)

def get_db():
    client = get_mongo_client()
    return client["rfp_responder"]
