import logging

import httpx2
import pytest

from .logs import configure_logging


def test_logged_requests_leave_out_signed_urls(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    caplog.set_level(logging.INFO)
    configure_logging("INFO")
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(200))

    # Act
    with httpx2.Client(transport=transport) as client:
        client.get("http://seaweedfs:8333/recordings/a.flac?X-Amz-Signature=secret")

    # Assert
    assert "X-Amz-Signature=secret" not in caplog.text
