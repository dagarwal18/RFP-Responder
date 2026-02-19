from fastapi import FastAPI
from rfp_automation.api.routes import router
from rfp_automation.config import settings

app = FastAPI(title="RFP Automation System")

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
