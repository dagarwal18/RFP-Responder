import os
from datetime import datetime
from persistence.mongo_client import get_db
from cryptography.fernet import Fernet, InvalidToken

class SecretsRepo:
    def __init__(self):
        self.db = get_db()
        self.collection = self.db["secrets"]
        master_key = os.environ.get("MASTER_KEY")
        if not master_key:
            raise RuntimeError("MASTER_KEY env var must be set to a URL-safe base64 key for encrypting secrets.")
        self.fernet = Fernet(master_key.encode() if isinstance(master_key, str) else master_key)

    def set_key(self, provider: str, api_key: str):
        token = self.fernet.encrypt(api_key.encode("utf-8"))
        now = datetime.utcnow()
        self.collection.update_one(
            {"provider": provider},
            {"$set": {"key": token.decode("utf-8"), "updated_at": now}},
            upsert=True
        )

    def get_key(self, provider: str) -> str:
        doc = self.collection.find_one({"provider": provider})
        if not doc or "key" not in doc:
            return None
        try:
            token = doc["key"].encode("utf-8")
            plain = self.fernet.decrypt(token).decode("utf-8")
            return plain
        except InvalidToken:
            raise RuntimeError("Failed to decrypt stored key: invalid MASTER_KEY or corrupted token.")
