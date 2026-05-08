import logging
from typing import Type, TypeVar

from pydantic import ValidationError, BaseModel
from requests import Response, JSONDecodeError, RequestException
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotCommunicationException,
    RobotUnknownErrorException,
    RobotNoMissionRunningException,
)

from isar_anymal.config.settings import settings
from isar_anymal.robot.api.anymal_api.enums import (
    ANYmalServiceCallStatus,
    ControlMissionStatus,
    ServiceCallStatus,
    UserInteractionMode,
)
from isar_anymal.robot.api.anymal_api.models import (
    ControlMissionResponseDto,
    LeaseControlResponseDto,
    ReleaseControlResponseDto,
    GetUserInteractionModeResponseDto,
    ProtectiveStopResponseDto,
)
from isar_anymal.robot.api.request_handler import RequestHandler

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class ANYmalAPI:
    def __init__(self, request_handler: RequestHandler) -> None:
        self.request_handler: RequestHandler = request_handler

    def request_control_authority_lease(self) -> str:
        request_body: dict = {"clientName": "opc", "clientType": "CLCT_REMOTE"}

        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/control-authority/lease",
                json_body=request_body,
                params={"anymal": settings.ROBOT_NAME},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to get control lease failed"
            ) from e

        lease_response: LeaseControlResponseDto = _parse_response_into_model(
            response=response, model_type=LeaseControlResponseDto
        )

        if lease_response.status != ServiceCallStatus.SCS_OK:
            error_description: str = (
                f"ANYmal API service call to request control authority lease failed with status: "
                f"{lease_response.status} and message: {lease_response.message}"
            )
            logger.error(error_description)
            raise RobotUnknownErrorException(error_description)

        return lease_response.lease_id

    def release_control_authority_lease(self, lease_id: str) -> None:
        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/control-authority/release",
                params={"anymal": settings.ROBOT_NAME, "leaseId": lease_id},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to release control lease failes"
            ) from e

        release_response: ReleaseControlResponseDto = _parse_response_into_model(
            response=response, model_type=ReleaseControlResponseDto
        )

        if release_response.status != ServiceCallStatus.SCS_OK:
            error_description: str = (
                f"ANYmal API service call to release control authority lease failed with status: "
                f"{release_response.status} and message: {release_response.message}"
            )
            logger.error(error_description)
            raise RobotUnknownErrorException(error_description)

    def disengage_protective_stop(self, lease_id: str) -> None:
        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/protective-stop/disengage",
                params={"anymal": settings.ROBOT_NAME, "leaseId": lease_id},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to disengage protective stop failed"
            ) from e

        protective_stop_response = _parse_response_into_model(
            response=response, model_type=ProtectiveStopResponseDto
        )

        if protective_stop_response.status != ServiceCallStatus.SCS_OK:
            error_description: str = (
                f"ANYmal API service call to disengage protective stop failed with status: "
                f"{protective_stop_response.status} and message: {protective_stop_response.message}"
            )
            logger.error(error_description)
            raise RobotAPIException(error_description)

    def get_user_interaction_mode(self) -> UserInteractionMode:
        try:
            response: Response = self.request_handler.get(
                url=f"{settings.SERVER_URL}/anymal-api/user-interaction-mode",
                params={"anymal": settings.ROBOT_NAME},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to get user interaction mode failed"
            ) from e

        try:
            interaction_mode_response = _parse_response_into_model(
                response=response,
                model_type=GetUserInteractionModeResponseDto,
            )
        except RobotAPIException:
            return UserInteractionMode.UIM_UNDEFINED

        if interaction_mode_response.header.status != ANYmalServiceCallStatus.ASCS_OK:
            logger.error(
                f"ANYmal API service call to get user interaction mode failed with status: "
                f"{interaction_mode_response.header.status} and message: {interaction_mode_response.header.message}"
            )
            return UserInteractionMode.UIM_UNDEFINED

        return interaction_mode_response.user_interaction_mode

    def set_user_interaction_mode(
        self, user_interaction_mode: UserInteractionMode, lease_id: str
    ) -> None:
        if user_interaction_mode == self.get_user_interaction_mode():
            return

        request_body: dict = {
            "userInteractionMode": user_interaction_mode,
            "leaseId": lease_id,
        }
        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/user-interaction-mode",
                json_body=request_body,
                params={"anymal": settings.ROBOT_NAME},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to set user interaction mode failed"
            ) from e

        interaction_mode_response = _parse_response_into_model(
            response=response, model_type=GetUserInteractionModeResponseDto
        )

        if interaction_mode_response.status != ServiceCallStatus.SCS_OK:
            error_description: str = (
                f"ANYmal API service call to set user interaction mode failed with status: "
                f"{interaction_mode_response.status} and message: {interaction_mode_response.message}"
            )
            logger.error(error_description)
            raise RobotAPIException(error_description)

    def start_predefined_mission(
        self,
        mission_id: str,
        lease_id: str,
        starting_task_id: str = "",
    ) -> ControlMissionResponseDto:
        request_body: dict = {
            "missionDescription": {
                "missionUid": mission_id,
                "startingTaskUid": starting_task_id,
            }
        }

        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/mission/start-predefined",
                json_body=request_body,
                params={"leaseId": lease_id, "anymal": settings.ROBOT_NAME},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to start mission failed"
            ) from e

        start_response: ControlMissionResponseDto = _parse_response_into_model(
            response=response, model_type=ControlMissionResponseDto
        )

        _raise_if_response_not_successful(start_response)
        return start_response

    def pause_mission(
        self, mission_run_uid: str, lease_id: str
    ) -> ControlMissionResponseDto:
        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/mission/pause",
                json_body={"runUid": mission_run_uid},
                params={"leaseId": lease_id, "anymal": settings.ROBOT_NAME},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to pause mission failed"
            ) from e

        pause_response: ControlMissionResponseDto = _parse_response_into_model(
            response=response, model_type=ControlMissionResponseDto
        )

        _raise_if_pause_with_no_active_mission(response=pause_response)
        _raise_if_response_not_successful(response=pause_response)
        return pause_response

    def resume_mission(
        self, mission_run_uid: str, lease_id: str
    ) -> ControlMissionResponseDto:
        try:
            response: Response = self.request_handler.post(
                url=f"{settings.SERVER_URL}/anymal-api/mission/resume",
                json_body={"runUid": mission_run_uid},
                params={"leaseId": lease_id, "anymal": settings.ROBOT_NAME},
            )
        except RequestException as e:
            raise RobotCommunicationException(
                error_description="API request to resume mission failed"
            ) from e

        resume_response: ControlMissionResponseDto = _parse_response_into_model(
            response=response, model_type=ControlMissionResponseDto
        )

        _raise_if_response_not_successful(response=resume_response)
        return resume_response


def _parse_response_into_model(response: Response, model_type: Type[TModel]) -> TModel:
    try:
        payload: dict = response.json()
    except JSONDecodeError as e:
        error_description_decode_json: str = (
            f"Failed to decode JSON response when requesting model type {model_type.__name__} through ANYmal API. "
            f"The response content was: {response.content}"
        )
        logger.exception(error_description_decode_json)
        raise RobotAPIException(error_description_decode_json) from e

    try:
        return model_type.model_validate(payload)
    except ValidationError as e:
        error_description_validation: str = (
            f"A validation error occurred when parsing into object of type {model_type.__name__} "
            f"from ANYmal API. The JSON attempted parsed was: {response.json()}"
        )
        logger.exception(error_description_validation)
        raise RobotAPIException(error_description_validation) from e


def _raise_if_response_not_successful(response: ControlMissionResponseDto) -> None:
    if not response:
        error_description: str = "Response received from ANYmal API was None"
        logger.error(error_description)
        raise RobotAPIException(error_description)

    if response.status != ANYmalServiceCallStatus.ASCS_OK:
        error_description_service_call_status: str = (
            f"ANYmal API service call failed with service call status: {response.status}, "
            f"control mission status: {response.control_mission_status} and message: {response.message}"
        )
        logger.error(error_description_service_call_status)
        raise RobotAPIException(error_description_service_call_status)

    if response.control_mission_status != ControlMissionStatus.CMS_OK:
        error_description_control_mission_status: str = (
            f"ANYmal API control mission failed with control mission status: {response.control_mission_status}, "
            f"service call status: {response.status} and message: {response.message}"
        )
        logger.error(error_description_control_mission_status)
        raise RobotAPIException(error_description_control_mission_status)


def _raise_if_pause_with_no_active_mission(response: ControlMissionResponseDto) -> bool:
    if (
        response.control_mission_status
        == ControlMissionStatus.CMS_ERROR_REQUEST_INVALID
        and response.message == "No mission is active."
    ):
        error_description: str = (
            "There was no actively running mission on the robot when attempting to pause"
        )
        logger.warning(error_description)
        raise RobotNoMissionRunningException(error_description)

    return False
