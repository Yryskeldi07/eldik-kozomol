from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    app_secret: str
    admin_api_key: str = ""
    cors_origins: str = ""
    superadmin_username: str = "yrys07"
    superadmin_email: str = "headset.kg@gmail.com"
    superadmin_password: str = ""
    upload_dir: str = "/app/uploads"
    max_upload_mb: int = 10
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
