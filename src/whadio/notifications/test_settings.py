from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import HttpUrl, SecretStr, ValidationError

from .settings import MailDelivery, OutboxSettings, SmtpSettings, load_notification_settings


@pytest.fixture(autouse=True)
def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WHADIO_PUBLIC_URL", "https://whadio.example.com")


def test_settings_without_an_smtp_section_have_no_relay() -> None:
    # Act
    settings = load_notification_settings()

    # Assert
    assert settings.smtp is None


def test_settings_read_the_nested_smtp_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_SMTP__HOST", "127.0.0.1")
    monkeypatch.setenv("WHADIO_SMTP__PORT", "1025")
    monkeypatch.setenv("WHADIO_SMTP__STARTTLS", "false")
    monkeypatch.setenv("WHADIO_SMTP__FROM_ADDRESS", "whadio@localhost")

    # Act
    settings = load_notification_settings()

    # Assert
    assert settings.smtp == SmtpSettings(
        host="127.0.0.1", port=1025, starttls=False, from_address="whadio@localhost"
    )


def test_settings_read_the_dotenv_file_of_the_working_directory(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".env").write_text(
        "WHADIO_SMTP__HOST=smtp.example.com\nWHADIO_SMTP__FROM_ADDRESS=noreply@example.com\n",
        encoding="utf-8",
    )

    # Act
    settings = load_notification_settings()

    # Assert
    assert settings.smtp is not None


def test_smtp_section_without_a_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_SMTP__PORT", "1025")
    monkeypatch.setenv("WHADIO_SMTP__FROM_ADDRESS", "whadio@localhost")

    # Act / Assert
    with pytest.raises(ValidationError, match=r"smtp\.host"):
        load_notification_settings()


def test_settings_without_a_relay_or_a_public_url_have_no_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")

    # Act
    settings = load_notification_settings()

    # Assert
    assert settings.delivery() is None


def test_relay_without_a_public_url_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("WHADIO_PUBLIC_URL")
    monkeypatch.setenv("WHADIO_SMTP__HOST", "smtp.example.com")
    monkeypatch.setenv("WHADIO_SMTP__FROM_ADDRESS", "noreply@example.com")

    # Act / Assert
    with pytest.raises(ValidationError, match="WHADIO_PUBLIC_URL"):
        load_notification_settings()


def test_relay_with_a_public_url_delivers_with_both(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_SMTP__HOST", "smtp.example.com")
    monkeypatch.setenv("WHADIO_SMTP__FROM_ADDRESS", "noreply@example.com")

    # Act
    delivery = load_notification_settings().delivery()

    # Assert
    assert delivery == MailDelivery(
        SmtpSettings(host="smtp.example.com", from_address="noreply@example.com"),
        HttpUrl("https://whadio.example.com"),
    )


def test_public_url_without_a_relay_has_no_delivery() -> None:
    # Act
    settings = load_notification_settings()

    # Assert
    assert settings.delivery() is None


def test_relay_defaults_to_starttls_on_the_submission_port() -> None:
    # Act
    smtp = SmtpSettings(host="smtp.example.com", from_address="noreply@example.com")

    # Assert
    assert (smtp.port, smtp.starttls, smtp.timeout) == (587, True, timedelta(seconds=30))


def test_relay_without_a_host_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="host"):
        SmtpSettings(host="", from_address="noreply@example.com")


@pytest.mark.parametrize("port", [0, 65536], ids=["below-range", "above-range"])
def test_relay_port_outside_the_tcp_range_is_refused(port: int) -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="port"):
        SmtpSettings(host="smtp.example.com", port=port, from_address="noreply@example.com")


@pytest.mark.parametrize("port", [1, 65535], ids=["lowest", "highest"])
def test_relay_port_at_the_tcp_range_bounds_is_accepted(port: int) -> None:
    # Act
    smtp = SmtpSettings(host="smtp.example.com", port=port, from_address="noreply@example.com")

    # Assert
    assert smtp.port == port


def test_relay_with_a_zero_timeout_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="timeout"):
        SmtpSettings(
            host="smtp.example.com", from_address="noreply@example.com", timeout=timedelta(0)
        )


@pytest.mark.parametrize(
    "address",
    ["noreply", "noreply@", "@example.com", "Whadio <noreply@example.com>", "a@b\nBcc: c@d"],
    ids=["no-domain", "empty-domain", "empty-local-part", "display-name", "header-injection"],
)
def test_sender_that_is_not_a_bare_address_is_refused(address: str) -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="from_address"):
        SmtpSettings(host="smtp.example.com", from_address=address)


def test_sender_on_a_local_domain_is_accepted() -> None:
    # Act
    smtp = SmtpSettings(host="mail.corp.local", from_address="whadio@corp.local")

    # Assert
    assert smtp.from_address == "whadio@corp.local"


def test_username_without_a_password_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="both the SMTP username and password"):
        SmtpSettings(host="smtp.example.com", username="whadio", from_address="noreply@example.com")


def test_password_without_a_username_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="both the SMTP username and password"):
        SmtpSettings(
            host="smtp.example.com",
            password=SecretStr("relay-secret"),
            from_address="noreply@example.com",
        )


def test_credentials_without_starttls_are_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="only over STARTTLS"):
        SmtpSettings(
            host="smtp.example.com",
            starttls=False,
            username="whadio",
            password=SecretStr("relay-secret"),
            from_address="noreply@example.com",
        )


def test_settings_read_the_nested_outbox_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_OUTBOX__BATCH_SIZE", "10")
    monkeypatch.setenv("WHADIO_OUTBOX__RETENTION", "P1D")
    # Act
    outbox = load_notification_settings().outbox
    # Assert
    assert (outbox.batch_size, outbox.retention) == (10, timedelta(days=1))


def test_outbox_defaults_retry_for_about_two_days_and_keep_sent_notices_a_week() -> None:
    # Act
    outbox = OutboxSettings()
    # Assert
    assert (
        outbox.retry_backoff,
        outbox.max_retry_backoff,
        outbox.max_attempts,
        outbox.retention,
    ) == (timedelta(minutes=1), timedelta(hours=6), 16, timedelta(days=7))


def test_backoff_cap_shorter_than_the_first_backoff_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="max_retry_backoff"):
        OutboxSettings(retry_backoff=timedelta(minutes=10), max_retry_backoff=timedelta(minutes=5))


def test_backoff_cap_equal_to_the_first_backoff_is_accepted() -> None:
    # Act
    outbox = OutboxSettings(
        retry_backoff=timedelta(minutes=5), max_retry_backoff=timedelta(minutes=5)
    )
    # Assert
    assert outbox.max_retry_backoff == timedelta(minutes=5)


@pytest.mark.parametrize("batch_size", [0, 1001], ids=["below-range", "above-range"])
def test_batch_size_outside_its_range_is_refused(batch_size: int) -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="batch_size"):
        OutboxSettings(batch_size=batch_size)


def test_zero_retention_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="retention"):
        OutboxSettings(retention=timedelta(0))
