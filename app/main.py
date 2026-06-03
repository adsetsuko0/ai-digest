from fastapi import FastAPI
from app.api.auth import router as auth_router

app = FastAPI(
    title="AI Digest",
    description="Персональный дайджест новостей на основе RSS и GPT",
    version="0.1.0"
)

app.include_router(auth_router)

@app.get("/")
def root():
    return {"message": "AI Digest работает!"}

@app.get("/health")
def health():
    return {"status": "ok"}