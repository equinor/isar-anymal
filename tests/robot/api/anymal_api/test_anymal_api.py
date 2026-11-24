from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture
from requests import Timeout
from robot_interface.models.exceptions.robot_exceptions import (
    RobotAPIException,
    RobotCommunicationException,
)
from robot_interface.models.robots.battery_state import BatteryState

from isar_anymal.config import settings
from isar_anymal.robot.api import API
from isar_anymal.robot.api.anymal_api.api import ANYmalAPI
from isar_anymal.robot.api.request_handler import RequestHandler
from tests.robot.utilities import (
    _mock_response_object,
    mock_subscribe_callback_functions,
)


def test_pause_and_resume_mission(mocker: MockerFixture) -> None:
    mock_subscribe_callback_functions(mocker)

    anymal: API = API()
    anymal.battery_handler.battery.state = BatteryState.Normal
    anymal.battery_handler.battery.level = 50.0

    expected_lease_payload = {
        "leaseId": "c238ded5-0737-495a-9230-8c78a375240a",
        "status": "SCS_OK",
        "message": "Lease control granted successfully.",
    }
    expected_release_payload = {"status": "SCS_OK", "message": "Released successfully."}
    expected_pause_or_resume_mission_payload = {
        "status": "ASCS_OK",
        "controlMissionStatus": "CMS_OK",
        "timestamp": "10000000000",
        "runUid": "fake_run_uid",
        "message": "Mission paused/resumed successfully.",
    }

    lease_url = "/anymal-api/control-authority/lease"
    release_url = "/anymal-api/control-authority/release"
    pause_mission_url = "/anymal-api/mission/pause"
    resume_mission_url = "/anymal-api/mission/resume"

    def post_side_effect(*, url: str, **kwargs):
        if url.endswith(lease_url):
            return _mock_response_object(expected_lease_payload)
        elif url.endswith(release_url):
            return _mock_response_object(expected_release_payload)
        elif url.endswith((pause_mission_url, resume_mission_url)):
            return _mock_response_object(expected_pause_or_resume_mission_payload)
        raise AssertionError(f"Unexpected url: {url}")

    anymal.anymal_api.request_handler.post = Mock(side_effect=post_side_effect)

    anymal.pause_mission(
        mission_run_uid=expected_pause_or_resume_mission_payload["runUid"]
    )
    anymal.resume_mission(
        mission_run_uid=expected_pause_or_resume_mission_payload["runUid"]
    )


def start_response(status: str = "CMS_OK", service_status: str = "ASCS_OK") -> Mock:
    return _mock_response_object(
        {
            "status": service_status,
            "controlMissionStatus": status,
            "timestamp": "now",
            "runUid": "run-id" if status == "CMS_OK" else "",
        }
    )


@pytest.fixture
def sync_api(mocker: MockerFixture) -> ANYmalAPI:
    now = [0.0]

    def sleep(seconds: float):
        now[0] += seconds

    mocker.patch(
        "isar_anymal.robot.api.anymal_api.api.time.monotonic",
        side_effect=lambda: now[0],
    )
    mocker.patch("isar_anymal.robot.api.anymal_api.api.time.sleep", side_effect=sleep)
    mocker.patch.object(settings, "MISSION_SYNC_TIMEOUT", 12)
    mocker.patch.object(settings, "MISSION_SYNC_RETRY_INTERVAL", 5)
    return ANYmalAPI(Mock(spec=RequestHandler))


def test_new_mission_retries_only_until_synchronized(sync_api: ANYmalAPI):
    sync_api.request_handler.post.side_effect = [
        start_response("CMS_ERROR_MISSION_UNKNOWN"),
        start_response("CMS_ERROR_MISSION_UNKNOWN"),
        start_response(),
    ]
    result = sync_api.start_predefined_mission("mission", "lease", wait_for_sync=True)
    assert result.run_uid == "run-id"
    assert [
        call.kwargs["request_timeout"]
        for call in sync_api.request_handler.post.call_args_list
    ] == [12, 7, 2]


def test_sync_timeout_is_bounded_and_releases_control(
    sync_api: ANYmalAPI, mocker: MockerFixture
):
    sync_api.request_handler.post.return_value = start_response(
        "CMS_ERROR_MISSION_UNKNOWN"
    )
    wrapper = object.__new__(API)
    wrapper.anymal_api = sync_api
    mocker.patch.object(wrapper, "take_control", return_value="lease")
    release = mocker.patch.object(wrapper, "release_control")
    mocker.patch.object(sync_api, "set_user_interaction_mode")
    with pytest.raises(RobotAPIException, match="did not synchronize"):
        wrapper.start_mission("mission", wait_for_sync=True)
    assert sync_api.request_handler.post.call_count == 3
    release.assert_called_once_with(lease_id="lease")


@pytest.mark.parametrize(
    "response",
    [
        start_response("CMS_ERROR_MISSION_EXECUTING"),
        start_response("CMS_ERROR_REQUEST_INVALID"),
        start_response("CMS_ERROR_MISSION_UNKNOWN", "ASCS_ERROR_ANYMAL_OFFLINE"),
        start_response("CMS_ERROR_PROTECTIVE_STOP_ENABLED"),
    ],
)
def test_sync_does_not_retry_other_failures(sync_api: ANYmalAPI, response: Mock):
    sync_api.request_handler.post.return_value = response
    with pytest.raises(RobotAPIException):
        sync_api.start_predefined_mission("mission", "lease", wait_for_sync=True)
    sync_api.request_handler.post.assert_called_once()


def test_sync_does_not_retry_ambiguous_network_failure(sync_api: ANYmalAPI):
    sync_api.request_handler.post.side_effect = Timeout("no response")
    with pytest.raises(RobotCommunicationException):
        sync_api.start_predefined_mission("mission", "lease", wait_for_sync=True)
    sync_api.request_handler.post.assert_called_once()


def test_stored_mission_does_not_wait_for_sync(sync_api: ANYmalAPI):
    sync_api.request_handler.post.return_value = start_response(
        "CMS_ERROR_MISSION_UNKNOWN"
    )
    with pytest.raises(RobotAPIException, match="CMS_ERROR_MISSION_UNKNOWN"):
        sync_api.start_predefined_mission("stored", "lease")
    sync_api.request_handler.post.assert_called_once()
