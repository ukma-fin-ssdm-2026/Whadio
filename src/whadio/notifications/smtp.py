import smtplib
import ssl
from contextlib import suppress
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from .settings import SmtpSettings


@dataclass(frozen=True, slots=True)
class OutgoingMail:
    recipient: str
    subject: str
    body: str


class MailDeliveryError(Exception):
    pass


class IMailSender(Protocol):
    def send(self, mail: OutgoingMail) -> None:
        """Hand the mail to the relay, or raise MailDeliveryError naming no address or body."""
        ...


class ISmtpSession(Protocol):
    def starttls(self, *, context: ssl.SSLContext | None = None) -> tuple[int, bytes]: ...

    def login(self, user: str, password: str) -> tuple[int, bytes]: ...

    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]: ...

    def quit(self) -> tuple[int, bytes]: ...

    def close(self) -> None: ...


class ISmtpConnector(Protocol):
    def __call__(self, host: str, port: int, *, timeout: float) -> ISmtpSession: ...


class SmtpMailSender:
    def __init__(self, settings: SmtpSettings, connect: ISmtpConnector = smtplib.SMTP) -> None:
        self._settings: SmtpSettings = settings
        self._connect: ISmtpConnector = connect

    def send(self, mail: OutgoingMail) -> None:
        message = self._compose(mail)
        settings = self._settings
        try:
            session = self._connect(
                settings.host, settings.port, timeout=settings.timeout.total_seconds()
            )
            try:
                if settings.starttls:
                    session.starttls(context=ssl.create_default_context())
                if settings.username is not None and settings.password is not None:
                    session.login(settings.username, settings.password.get_secret_value())
                session.send_message(message)
                # The relay has accepted the mail; a failed QUIT must not make the caller resend.
                with suppress(smtplib.SMTPException, OSError):
                    session.quit()
            finally:
                session.close()
        except (smtplib.SMTPException, OSError) as error:
            # smtplib's errors carry the recipients and the relay's replies; chaining them would
            # put addresses in any logged traceback (threat model R-11).
            raise MailDeliveryError(f"SMTP delivery failed: {type(error).__name__}") from None

    def _compose(self, mail: OutgoingMail) -> EmailMessage:
        sender = self._settings.from_address
        message = EmailMessage()
        message["From"] = sender
        message["To"] = mail.recipient
        message["Subject"] = mail.subject
        message["Date"] = formatdate(usegmt=True)
        message["Message-ID"] = make_msgid(domain=Address(addr_spec=sender).domain)
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(mail.body)
        return message
