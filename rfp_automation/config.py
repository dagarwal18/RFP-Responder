from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    OPENAI_API_KEY: str = ""
    MONGO_URI: str = "mongodb://localhost:27017"
    
    class Config:
        env_file = ".env"

settings = Settings()
