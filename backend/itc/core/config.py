from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    llm_provider: str
    llm_model: str
    smtp_host: str
    smtp_port: int
    jwt_public_key_path: str

    use_llm_matcher: bool = False
