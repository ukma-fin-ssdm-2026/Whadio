from typing import override

from .smtp import IMailSender, OutgoingMail


class RecordingMailSender(IMailSender):
    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    @override
    def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)
