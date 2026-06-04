from fastapi import FastAPI
from fastapi.security import HTTPBearer
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.feeds import router as feeds_router

security = HTTPBearer()

app = FastAPI(
    title="AI Digest",
    description="Personal news digest based on RSS and GPT",
    version="0.1.0"
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(feeds_router)

@app.get("/")
def root():
    return {"message": "AI Digest is running!"}

@app.get("/health")
def health():
    return {"status": "ok"}