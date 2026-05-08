from importlib.resources import as_file, files

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    def __init__(self) -> None:
        try:
            source = files("isar_anymal").joinpath("config").joinpath("settings.env")
            with as_file(source) as eml:
                env_file = eml
        except ModuleNotFoundError:
            env_file = None
        super().__init__(_env_file=env_file)

    ROBOT_NAME: str = Field(default="d104")

    # The basis for a coordinate transform between robot and asset maps
    MAP_NAME: str = Field(default="klab_compressor")

    # Credentials for the API
    API_EMAIL: str = Field(default="email")
    API_PASSWORD: str = Field(default="password")

    # Timeout for api requests
    API_REQUEST_TIMEOUT: float = Field(default=60)

    # Server settings
    SERVER_URL: str = Field(default="http://localhost:11314")

    # File transfer
    ENVIRONMENT_NAME: str = Field(default="northern_lights")
    ENVIRONMENT_FILE_NAME: str = Field(default="environment.yaml")
    ENVIRONMENT_FILE_SYNC_DELAY: int = Field(default=5)
    ENVIRONMENT_FILE_WORKING_FOLDER: str = Field(default="/app/data/")

    # How to treat the protective stop
    AUTO_DISABLE_PROTECTIVE_STOP: bool = Field(default=True)

    # Docking information
    DOCK_MISSION_NAME: str = Field(default="Dock")
    DOCK_TASK_ID: str = Field(default="Dock")

    # MQTT telemetry settings
    MAX_TELEMETRY_RETRIES: int = Field(default=5)
    TELEMETRY_RETRY_INTERVAL: int = Field(default=5)

    # Battery settings
    BATTERY_FULL_VALUE: float = Field(default=98.0)

    # File retrieval settings
    FILE_RETRIEVAL_NUM_RETRIES: int = Field(default=10)
    FILE_RETRIEVAL_RETRY_INTERVAL: int = Field(default=10)

    model_config = SettingsConfigDict(
        env_prefix="ANYMAL_",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
