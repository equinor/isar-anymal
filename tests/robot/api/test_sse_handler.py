from unittest.mock import MagicMock

import pytest
from requests import ConnectionError

from isar_anymal.robot.api.sse_handler import SSEHandler


def test_sse_reconnects_after_connection_failure_with_bounded_timeout():
    handler = SSEHandler()
    response = MagicMock()
    response.iter_lines.return_value = []
    handler.request_handler = MagicMock()
    handler.request_handler.get.side_effect = [ConnectionError(), response]
    handler._sleep_before_reconnecting = MagicMock(side_effect=[0.2, StopIteration])

    with pytest.raises(StopIteration):
        handler.subscribe_to_sse("http://robot/events", MagicMock(), MagicMock())

    assert handler.request_handler.get.call_count == 2
    for call in handler.request_handler.get.call_args_list:
        assert call.kwargs["request_timeout"] == (10, 30)
        assert call.kwargs["stream"] is True
    response.close.assert_called_once()
