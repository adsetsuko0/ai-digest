import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only-0123456789abcdef")
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["RATE_LIMIT_STORAGE_URI"] = "memory://"
