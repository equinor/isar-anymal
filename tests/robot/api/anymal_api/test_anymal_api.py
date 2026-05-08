from unittest.mock import Mock

from pytest_mock import MockerFixture
from robot_interface.models.robots.battery_state import BatteryState

from isar_anymal.robot.api import API
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
        elif url.endswith(pause_mission_url) or url.endswith(resume_mission_url):
            return _mock_response_object(expected_pause_or_resume_mission_payload)
        raise AssertionError(f"Unexpected url: {url}")

    anymal.anymal_api.request_handler.post = Mock(side_effect=post_side_effect)

    anymal.pause_mission(
        mission_run_uid=expected_pause_or_resume_mission_payload["runUid"]
    )
    anymal.resume_mission(
        mission_run_uid=expected_pause_or_resume_mission_payload["runUid"]
    )
