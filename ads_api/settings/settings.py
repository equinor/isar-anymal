from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    def __init__(self) -> None:
        super().__init__()

    SERVER_URL: str = Field(default="http://localhost:11314")

    # Credentials
    CREDENTIALS_DIR: Optional[str] = Field(default="/home/ads-api/credentials/")
    CREDENTIALS_CLI_CRT_FILE: str = Field(default="ads-cli.crt")
    CREDENTIALS_CLI_KEY_FILE: str = Field(default="ads-cli.pem")

    # File transfer
    ENVIRONMENT_NAME: str = Field(default="northern_lights")
    ENVIRONMENT_FILE_NAME: str = Field(default="environment.yaml")
    ENVIRONMENT_FILE_SYNC_DELAY: int = Field(default=5)
    ENVIRONMENT_FILE_WORKING_FOLDER: str = Field(default="/home/ads-api/data")

    ADS_COMMAND_PATH: str = Field(default="/opt/ros/noetic/bin/ads")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
