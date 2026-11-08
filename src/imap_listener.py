# -*- coding: utf-8 -*-
"""
IMAPListener — Inbound Technician Email Reply Poller
====================================================

Monitors an IMAP SSL inbox (e.g., imap.gmail.com:993) for replies from
the on-duty technician confirming that an assigned solar plant incident
([INC-XXXX]) has been resolved in the field.

Author: Miguel Ángel Mejía Sánchez
"""

import email
import imaplib
import logging
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)


class IMAPConfig:
    """IMAP SSL connection configuration."""

    def __init__(
        self,
        imap_server: str = "imap.gmail.com",
        imap_port: int = 993,
        email_address: str = "",
        password: str = "",
    ) -> None:
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.email_address = email_address
        self.password = password


class IMAPListener:
    """Polls IMAP inbox for technician incident resolution replies."""

    def __init__(self, config: Optional[IMAPConfig] = None) -> None:
        self.config = config

    @staticmethod
    def parse_reply_body(raw_body: str) -> str:
        """Extract clean technician reply text, stripping quoted history."""
        if not raw_body:
            return ""
        clean_lines = []
        for line in raw_body.splitlines():
            stripped = line.strip()
            if stripped.startswith(">"):
                continue
            if (
                stripped.lower().startswith("on ")
                and stripped.lower().endswith("wrote:")
            ):
                break
            if stripped.lower().startswith("el ") and "escribi" in stripped.lower():
                break
            clean_lines.append(line)
        result = "\n".join(clean_lines).strip()
        return result or raw_body.strip()

    @staticmethod
    def _decode_mime_header(value: str) -> str:
        """Decode RFC2047 MIME-encoded email headers safely."""
        if not value:
            return ""
        parts = decode_header(value)
        decoded = []
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded.append(content.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(str(content))
        return "".join(decoded)

    @classmethod
    def _extract_text_from_message(cls, msg: email.message.Message) -> str:
        """Extract plain text body from a single or multipart email message."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return cls.parse_reply_body(
                            payload.decode(charset, errors="replace")
                        )
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return cls.parse_reply_body(payload.decode(charset, errors="replace"))
        return ""

    def check_for_resolution_reply(
        self,
        incident_id: str,
        technician_email: str,
    ) -> Optional[dict]:
        """Search inbox for a reply matching [incident_id] or from technician_email.

        Returns
        -------
        dict or None
            If a reply is found: {"incident_id": str, "from": str, "subject": str, "body": str}
        """
        if not self.config or not self.config.email_address or not self.config.password:
            return None

        try:
            with imaplib.IMAP4_SSL(
                self.config.imap_server, self.config.imap_port
            ) as mail:
                mail.login(self.config.email_address, self.config.password)
                mail.select("INBOX")

                # Search unseen messages first
                status, data = mail.search(None, "UNSEEN")
                if status != "OK" or not data or not data[0]:
                    return None

                msg_ids = data[0].split()
                for num in reversed(msg_ids[-15:]):
                    res, msg_data = mail.fetch(num, "(RFC822)")
                    if res != "OK" or not msg_data:
                        continue
                    raw_email = msg_data[0][1]
                    if not isinstance(raw_email, bytes):
                        continue
                    msg = email.message_from_bytes(raw_email)
                    subject = self._decode_mime_header(msg.get("Subject", ""))
                    sender = self._decode_mime_header(msg.get("From", ""))

                    # Avoid matching our own outbound initial alert if it hasn't been replied to
                    is_reply = (
                        subject.lower().startswith("re:")
                        or "respuesta" in subject.lower()
                        or (
                            technician_email
                            and technician_email.lower() in sender.lower()
                            and self.config.email_address.lower() not in sender.lower()
                        )
                    )
                    matches_incident = (
                        incident_id.lower() in subject.lower()
                        or (
                            technician_email
                            and technician_email.lower() in sender.lower()
                        )
                    )

                    if is_reply and matches_incident:
                        body = self._extract_text_from_message(msg)
                        logger.info(
                            "Detected technician resolution email for %s from %s",
                            incident_id,
                            sender,
                        )
                        return {
                            "incident_id": incident_id,
                            "from": sender,
                            "subject": subject,
                            "body": body or "Incidente atendido y normalizado en campo.",
                        }
        except Exception as exc:
            logger.warning("IMAP check failed: %s", exc)
        return None
