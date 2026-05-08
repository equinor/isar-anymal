import logging
from pathlib import Path
from typing import Optional

import requests

from pydantic import BaseModel
from requests import Response, RequestException
from robot_interface.models.exceptions.robot_exceptions import (
    RobotCommunicationException,
    RobotAPIException,
)

logger = logging.getLogger(__name__)


class SendFileResponse(BaseModel):
    success: bool
    destination_path: str
    error_description: Optional[str] = None


SEND_FILE_URL: str = "http://0.0.0.0:8081/send-file-to-robot-computer"
GET_FILE_URL: str = "http://0.0.0.0:8081/get-file-from-robot-computer"


def send_file_through_ads_api(
    computer: str,
    destination_path: str,
    robot_name: str,
    file_path: Path,
    prune: bool = False,
    url: str = SEND_FILE_URL,
    timeout: float = 60,
) -> SendFileResponse:
    if isinstance(file_path, str):
        file_path = Path(file_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File does not exist: {file_path}")

    data: dict = {
        "computer": computer,
        "destination_path": destination_path,
        "robot_name": robot_name,
        "prune": prune,
    }

    with file_path.open("rb") as f:
        files: dict = {"file": (file_path.name, f, "application/octet-stream")}

        response: Response = _send_post_request(
            url=url, data=data, files=files, timeout=timeout
        )

        return SendFileResponse.model_validate(response.json())


def get_file_through_ads_api(
    *,
    computer: str,
    robot_name: str,
    file_path_on_robot: str,
    output_dir: Path = Path("."),
    url: str = GET_FILE_URL,
    timeout: float = 60,
) -> Path:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "computer": computer,
        "robot_name": robot_name,
        "file_path_on_robot": file_path_on_robot,
    }

    response: Response = _send_post_request(
        url=url, data=data, files={}, timeout=timeout
    )

    filename: str = Path(file_path_on_robot).name
    local_path: Path = output_dir / filename

    local_path.write_bytes(response.content)
    return local_path


def _send_post_request(
    url: str, data: dict, files: Optional[dict] = None, timeout: float = 60
) -> Response:
    try:
        response: Response = requests.post(url, data=data, files=files, timeout=timeout)

    except (RequestException, Exception) as e:
        error_description_post_request: str = (
            "Exception occurred when sending post request to ads-api"
        )
        logger.exception(error_description_post_request)
        raise RobotCommunicationException(error_description_post_request) from e

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        response_dict: dict = e.response.json()

        try:
            error_message = response_dict["detail"]
            raise RobotAPIException(error_message) from e
        except KeyError:
            error_description_key_error: str = (
                f"Http error. Http status code= {response.status_code}. Http response body= {response.json()}"
            )
            logger.exception(error_description_key_error)
            raise RobotAPIException(error_description_key_error) from e

    return response
