from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://ticket_admin:ticket_pass@localhost:5432/ticket_system"

    jwt_secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    password_reset_token_ttl_minutes: int = 30

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # Optional stand-in for text generation only (see genai_service.call_model) — when
    # set, chat replies/summaries/sentiment route through Groq instead of Gemini.
    # Embeddings/RAG always use Gemini above.
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # How many times a customer can come across as angry/frustrated, or explicitly ask
    # for a human, before the AI hands the ticket off to a human agent. Set to 1 to
    # escalate on the very first such signal.
    ai_escalation_threshold: int = 2

    upload_dir: str = "uploads"
    max_upload_size_mb: int = 10

    class Config:
        env_file = ".env"


settings = Settings()
