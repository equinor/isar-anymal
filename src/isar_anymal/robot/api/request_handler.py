import logging
import time
import warnings
from typing import Any

import requests
from pydantic import BaseModel, ValidationError
from requests.exceptions import HTTPError, RequestException
from requests.models import Response
from robot_interface.models.exceptions.robot_exceptions import RobotAPIException

from isar_anymal.config import settings

logger = logging.getLogger(__name__)


class RequestHandler:
    def __init__(self) -> None:
        self.token: str | None = None
        self.token_expires_at: float | None = None

    def request_token(self) -> str | None:
        login_payload = {
            "email": settings.API_EMAIL,
            "password": settings.API_PASSWORD,
        }
        login_headers = {"Content-Type": "application/json"}
        auth_url = f"{settings.SERVER_URL}/authentication-service/auth/login"

        auth_response = requests.post(
            auth_url,
            headers=login_headers,
            json=login_payload,
            verify=False,
        )
        if auth_response.status_code is requests.codes.created:
            self.token = auth_response.json()["accessToken"]
            self.token_expires_at = time.time() + 900  # 15 minutes
        return self.token

    def get_token(self) -> str | None:
        if (
            self.token is None
            or self.token_expires_at is None
            or time.time() >= (self.token_expires_at - 300)
        ):  # Refresh 5 minutes before expiry

            return self.request_token()

        return self.token

    def _base_request(
        self,
        url: str,
        method: str,
        headers: dict | None,
        json_body: Any,
        timeout: float | None,
        data: Any = None,
        params: dict | None = None,
        **kwargs,
    ) -> Response:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if headers is None:
                    headers = {"Authorization": f"Bearer {self.get_token()}"}
                response = requests.request(
                    url=url,
                    method=method,
                    headers=headers,
                    timeout=timeout,
                    json=json_body,
                    data=data,
                    params=params,
                    verify=False,
                    **kwargs,
                )
        except RequestException:
            raise
        except Exception as e:
            logger.exception("An unhandled exception occurred during a request")
            raise RequestException from e

        try:
            response.raise_for_status()
        except HTTPError as e:
            try:
                payload = response.json()
            except requests.JSONDecodeError:
                payload = response.text
            message = (
                payload.get("message", payload.get("detail", payload))
                if isinstance(payload, dict)
                else payload
            )
            raise RequestException(
                f"HTTP {response.status_code}: {message}", response=response
            ) from e
        return response

    def get(
        self,
        url: str,
        json_body=None,
        request_timeout: float | None = settings.API_REQUEST_TIMEOUT,
        headers: dict | None = None,
        data: dict | None = None,
        stream: bool = False,
        params: dict | None = None,
        **kwargs,
    ) -> Response:
        return self._base_request(
            url=url,
            method="GET",
            headers=headers,
            timeout=request_timeout,
            json_body=json_body,
            data=data,
            stream=stream,
            params=params,
            **kwargs,
        )

    def post(
        self,
        url: str,
        json_body=None,
        request_timeout: float | None = settings.API_REQUEST_TIMEOUT,
        headers: dict | None = None,
        data: Any = None,
        params: dict | None = None,
        **kwargs,
    ) -> Response:
        return self._base_request(
            url=url,
            method="POST",
            headers=headers,
            timeout=request_timeout,
            json_body=json_body,
            data=data,
            params=params,
            **kwargs,
        )

    def delete(self, url: str) -> Response:
        return self._base_request(
            url=url,
            method="DELETE",
            headers=None,
            timeout=settings.API_REQUEST_TIMEOUT,
            json_body=None,
        )


def parse_response[TModel: BaseModel](
    response: Response, model_type: type[TModel]
) -> TModel:
    try:
        return model_type.model_validate(response.json())
    except (requests.JSONDecodeError, ValidationError) as e:
        message = f"Invalid API response for {model_type.__name__}: {e}"
        logger.exception(message)
        raise RobotAPIException(message) from e
