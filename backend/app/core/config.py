from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    db_service_url: str = "http://localhost:8081"
    prediction_engine_url: str = "http://localhost:8090"
    opendota_base_url: str = "https://api.opendota.com/api"

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    pending_2fa_token_expire_minutes: int = 5


settings = Settings()
