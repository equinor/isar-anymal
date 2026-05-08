import logging
import time
from typing import Any, Optional

import requests
from requests.exceptions import HTTPError, RequestException
from requests.models import Response
import warnings

from isar_anymal.config import settings

logger = logging.getLogger(__name__)


class RequestHandler:
    def __init__(self) -> None:
        self.token: Optional[str] = None
        self.token_expires_at: Optional[float] = None

    def request_token(self) -> Optional[str]:
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

    def get_token(self) -> Optional[str]:
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
        headers: Optional[dict],
        json_body: Any,
        timeout: Optional[float],
        data: Any = None,
        params: Optional[dict] = None,
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
        except RequestException as e:
            raise e
        except Exception as e:
            logger.exception("An unhandled exception occurred during a request")
            raise RequestException from e

        try:
            response.raise_for_status()
        except HTTPError as e:
            response_dict: dict = e.response.json()

            try:
                error_message = response_dict["message"]
                raise RequestException(error_message)
            except KeyError:
                logger.exception(
                    f"Http error. Http status code= {response.status_code}. Http response body= {response.json()}"
                )
                raise e
        return response

    def get(
        self,
        url: str,
        json_body=None,
        request_timeout: Optional[float] = settings.API_REQUEST_TIMEOUT,
        headers: Optional[dict] = None,
        data: Optional[dict] = None,
        stream: bool = False,
        params: Optional[dict] = None,
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
        request_timeout: Optional[float] = settings.API_REQUEST_TIMEOUT,
        headers: Optional[dict] = None,
        data: Any = None,
        params: Optional[dict] = None,
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
