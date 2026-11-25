import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    db_path: str = os.getenv("DB_PATH", "sales_agent.db")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    crm_webhook_url: str = os.getenv("CRM_WEBHOOK_URL", "").strip()
    kb_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "knowledge_base")


settings = Settings()
