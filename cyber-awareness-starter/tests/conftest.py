import os
import tempfile


os.environ["DATABASE_URL"] = "sqlite:///./test_cyber_awareness.db"
os.environ["DATABASE_AUTH_MODE"] = "password"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ["MOCK_AI_SERVICES"] = "true"
os.environ["MOCK_EMAIL_SERVICE"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["POSTER_STORAGE_PATH"] = tempfile.mkdtemp(prefix="cyber-posters-")
