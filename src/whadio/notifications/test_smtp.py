import smtplib
import ssl
import time
import traceback
from email.message import EmailMessage
from typing import override
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel, Field, SecretStr

from .settings import SmtpSettings
from .smtp import ISmtpConnector, ISmtpSession, MailDeliveryError, OutgoingMail, SmtpMailSender

MAIL = OutgoingMail(
    recipient="olena@example.com", subject="“Weekly sync” is ready", body="Open the meeting.\n"
)
PLAIN_RELAY = SmtpSettings(
    host="relay.example.com", port=1025, starttls=False, from_address="noreply@example.com"
)
AUTHENTICATED_RELAY = SmtpSettings(
    host="relay.example.com",
    username="whadio",
    password=SecretStr("relay-secret"),
    from_address="noreply@example.com",
)


class FakeSmtpSession(ISmtpSession):
    def __init__(self, failure: OSError | None = None, quit_failure: OSError | None = None) -> None:
        self.calls: list[str] = []
        self.messages: list[EmailMessage] = []
        self.tls_context: ssl.SSLContext | None = None
        self.credentials: tuple[str, str] | None = None
        self._failure: OSError | None = failure
        self._quit_failure: OSError | None = quit_failure

    @override
    def starttls(self, *, context: ssl.SSLContext | None = None) -> tuple[int, bytes]:
        self.calls.append("starttls")
        self.tls_context = context
        return (220, b"ready")

    @override
    def login(self, user: str, password: str) -> tuple[int, bytes]:
        self.calls.append("login")
        self.credentials = (user, password)
        return (235, b"authenticated")

    @override
    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]:
        self.calls.append("send_message")
        if self._failure is not None:
            raise self._failure
        self.messages.append(msg)
        return {}

    @override
    def quit(self) -> tuple[int, bytes]:
        self.calls.append("quit")
        if self._quit_failure is not None:
            raise self._quit_failure
        return (221, b"bye")

    @override
    def close(self) -> None:
        self.calls.append("close")


class FakeConnector(ISmtpConnector):
    def __init__(self, session: FakeSmtpSession, refusal: OSError | None = None) -> None:
        self.session: FakeSmtpSession = session
        self.addresses: list[tuple[str, int, float]] = []
        self._refusal: OSError | None = refusal

    @override
    def __call__(self, host: str, port: int, *, timeout: float) -> ISmtpSession:
        self.addresses.append((host, port, timeout))
        if self._refusal is not None:
            raise self._refusal
        return self.session


def _send(
    settings: SmtpSettings, session: FakeSmtpSession, refusal: OSError | None = None
) -> FakeConnector:
    connector = FakeConnector(session, refusal)
    SmtpMailSender(settings, connector).send(MAIL)
    return connector


def test_sender_connects_to_the_configured_relay_with_its_timeout() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    connector = _send(PLAIN_RELAY, session)

    # Assert
    assert connector.addresses == [("relay.example.com", 1025, 30.0)]


def test_message_is_addressed_from_the_sender_to_the_recipient() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(PLAIN_RELAY, session)

    # Assert
    message = session.messages[0]
    assert (message["From"], message["To"], message["Subject"]) == (
        "noreply@example.com",
        "olena@example.com",
        "“Weekly sync” is ready",
    )


def test_message_body_is_the_plain_text_of_the_mail() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(PLAIN_RELAY, session)

    # Assert
    message = session.messages[0]
    assert (message.get_content_type(), message.get_content()) == ("text/plain", MAIL.body)


def test_message_is_marked_as_automatically_sent() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(PLAIN_RELAY, session)

    # Assert
    assert session.messages[0]["Auto-Submitted"] == "auto-generated"


def test_message_id_names_the_domain_of_the_sender() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(PLAIN_RELAY, session)

    # Assert
    assert "@example.com>" in session.messages[0]["Message-ID"]


def test_plain_relay_is_sent_to_without_tls_or_login() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(PLAIN_RELAY, session)

    # Assert
    assert session.calls == ["send_message", "quit", "close"]


def test_authenticated_relay_upgrades_to_tls_before_logging_in() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(AUTHENTICATED_RELAY, session)

    # Assert
    assert session.calls == ["starttls", "login", "send_message", "quit", "close"]


def test_starttls_verifies_the_certificate_of_the_relay() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(AUTHENTICATED_RELAY, session)

    # Assert
    context = session.tls_context
    assert context is not None
    assert (context.verify_mode, context.check_hostname) == (ssl.CERT_REQUIRED, True)


def test_login_uses_the_secret_password() -> None:
    # Arrange
    session = FakeSmtpSession()

    # Act
    _send(AUTHENTICATED_RELAY, session)

    # Assert
    assert session.credentials == ("whadio", "relay-secret")


def test_unreachable_relay_is_a_delivery_error() -> None:
    # Act / Assert
    with pytest.raises(MailDeliveryError, match="ConnectionRefusedError"):
        _send(PLAIN_RELAY, FakeSmtpSession(), refusal=ConnectionRefusedError())


def test_refused_mail_closes_the_connection() -> None:
    # Arrange
    session = FakeSmtpSession(failure=smtplib.SMTPDataError(554, b"rejected"))

    # Act
    with pytest.raises(MailDeliveryError):
        _send(PLAIN_RELAY, session)

    # Assert
    assert session.calls[-1] == "close"


def test_delivery_error_traceback_names_no_recipient() -> None:
    # Arrange
    refusal = smtplib.SMTPRecipientsRefused({MAIL.recipient: (550, b"<olena@example.com> unknown")})

    # Act
    with pytest.raises(MailDeliveryError) as raised:
        _send(PLAIN_RELAY, FakeSmtpSession(failure=refusal))

    # Assert
    assert MAIL.recipient not in "".join(traceback.format_exception(raised.value))


def test_failed_quit_after_an_accepted_mail_is_not_a_delivery_error() -> None:
    # Arrange
    session = FakeSmtpSession(quit_failure=smtplib.SMTPServerDisconnected("gone"))

    # Act
    _send(PLAIN_RELAY, session)

    # Assert
    assert len(session.messages) == 1


# --- Delivery through Mailpit ---


class _MailpitAddress(BaseModel):
    address: str = Field(alias="Address", description="Email address")


class _MailpitMessage(BaseModel):
    subject: str = Field(alias="Subject", description="Subject header")
    to: list[_MailpitAddress] = Field(alias="To", description="Recipients")


class _MailpitMessages(BaseModel):
    messages: list[_MailpitMessage] = Field(description="Most recent messages first")


def _wait_for_mailpit_message(subject: str) -> _MailpitMessage | None:
    deadline = time.monotonic() + 5
    with httpx.Client(base_url="http://127.0.0.1:8025", timeout=2) as client:
        while time.monotonic() < deadline:
            response = client.get("/api/v1/messages")
            response.raise_for_status()
            listing = _MailpitMessages.model_validate_json(response.content)
            for message in listing.messages:
                if message.subject == subject:
                    return message
            time.sleep(0.1)
    return None


@pytest.mark.slow
def test_mail_sent_through_the_relay_reaches_mailpit() -> None:
    # Arrange
    subject = f"Whadio test {uuid4()}"
    recipient = f"{uuid4()}@example.com"
    settings = SmtpSettings(
        host="127.0.0.1", port=1025, starttls=False, from_address="whadio@localhost"
    )

    # Act
    SmtpMailSender(settings).send(OutgoingMail(recipient=recipient, subject=subject, body="Hi.\n"))

    # Assert
    received = _wait_for_mailpit_message(subject)
    assert received is not None
    assert [to.address for to in received.to] == [recipient]
