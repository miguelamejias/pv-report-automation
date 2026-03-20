# -*- coding: utf-8 -*-
"""
NotificationOrchestrator — Multi-Channel Alert Dispatch System
==============================================================

Routes anomaly alerts to the appropriate communication channels
based on severity:
  - CRITICAL → Email (with PDF attachment) + Slack (red blocks)
  - WARNING  → Slack (yellow blocks) + Email
  - INFO     → Slack only (green blocks)

Supports:
  - SMTP Email (SSL/TLS) with PDF report attachment
  - Slack Incoming Webhooks with Block Kit formatting

Security:
  - Credentials are loaded from environment variables or config.
  - No secrets are hardcoded (12-factor app compliance).

Author: Miguel Ángel Mejía Sánchez
Updated with AI: Extracted from a single send_email() function into
                 a fully orchestrated, severity-aware notification system.
"""

import json
import logging
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from src.anomaly_engine import Alert, Severity

logger = logging.getLogger(__name__)


class EmailConfig:
    """SMTP email configuration container.

    Parameters
    ----------
    smtp_server : str
        SMTP server hostname (e.g., smtp.gmail.com).
    smtp_port : int
        SMTP server port (587 for STARTTLS, 465 for SSL).
    sender_email : str
        Sender email address.
    sender_password : str
        App-specific password (not your personal password).
    recipients : list[str]
        List of recipient email addresses.
    use_tls : bool
        Whether to use STARTTLS (default: True).
    """

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        sender_email: str,
        sender_password: str,
        recipients: list[str],
        use_tls: bool = True,
    ) -> None:
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.recipients = recipients
        self.use_tls = use_tls


class SlackConfig:
    """Slack webhook configuration container.

    Parameters
    ----------
    webhook_url : str
        Slack Incoming Webhook URL.
    channel : str
        Channel override (optional, usually set in webhook config).
    """

    def __init__(self, webhook_url: str, channel: str = "") -> None:
        self.webhook_url = webhook_url
        self.channel = channel


class NotificationOrchestrator:
    """Multi-channel notification dispatcher with severity-based routing.

    This class implements the Mediator pattern: it centralizes the
    decision of WHERE to send an alert based on its severity, keeping
    individual channel senders decoupled from business logic.

    Usage:
        >>> orchestrator = NotificationOrchestrator(
        ...     email_config=EmailConfig(...),
        ...     slack_config=SlackConfig(...)
        ... )
        >>> orchestrator.dispatch(alerts, pdf_path="output/report.pdf")
    """

    # Severity → Slack color mapping
    SEVERITY_COLORS = {
        Severity.CRITICAL: "#E74C3C",  # Red
        Severity.WARNING: "#F39C12",   # Yellow/Amber
        Severity.INFO: "#2ECC71",      # Green
    }

    SEVERITY_EMOJI = {
        Severity.CRITICAL: "🔴",
        Severity.WARNING: "🟡",
        Severity.INFO: "🟢",
    }

    def __init__(
        self,
        email_config: Optional[EmailConfig] = None,
        slack_config: Optional[SlackConfig] = None,
    ) -> None:
        self.email_config = email_config
        self.slack_config = slack_config

    def dispatch(
        self,
        alerts: list[Alert],
        pdf_path: Optional[str | Path] = None,
    ) -> dict:
        """Route alerts to the appropriate channels based on severity.

        Parameters
        ----------
        alerts : list[Alert]
            Anomaly alerts to dispatch.
        pdf_path : str or Path, optional
            Path to the PDF report to attach to emails.

        Returns
        -------
        dict
            Summary of dispatch results: {"email": bool, "slack": bool,
            "total_alerts": int, "critical": int, "warnings": int}
        """
        if not alerts:
            logger.info("No alerts to dispatch.")
            return {"email": False, "slack": False, "total_alerts": 0}

        critical_count = sum(1 for a in alerts if a.severity == Severity.CRITICAL)
        warning_count = sum(1 for a in alerts if a.severity == Severity.WARNING)
        max_severity = alerts[0].severity  # Already sorted by severity

        result = {
            "email": False,
            "slack": False,
            "total_alerts": len(alerts),
            "critical": critical_count,
            "warnings": warning_count,
        }

        # Routing logic: CRITICAL/WARNING → both channels, INFO → Slack only
        if self.slack_config:
            result["slack"] = self._send_slack(alerts)

        if self.email_config and max_severity in (Severity.CRITICAL, Severity.WARNING):
            result["email"] = self._send_email(alerts, pdf_path)

        return result

    # ------------------------------------------------------------------
    # Slack channel
    # ------------------------------------------------------------------

    def _send_slack(self, alerts: list[Alert]) -> bool:
        """Send formatted alert blocks to Slack via Incoming Webhook.

        Uses Slack's Block Kit for rich, visual alert messages with
        color-coded severity indicators.
        """
        try:
            blocks = self._build_slack_blocks(alerts)
            payload = json.dumps({"blocks": blocks}).encode("utf-8")

            req = Request(
                self.slack_config.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=10) as response:
                if response.status == 200:
                    logger.info("Slack notification sent successfully.")
                    return True
                else:
                    logger.error("Slack returned status %d.", response.status)
                    return False

        except URLError as exc:
            logger.error("Slack webhook failed: %s", exc)
            return False
        except Exception as exc:
            logger.error("Unexpected Slack error: %s", exc, exc_info=True)
            return False

    def _build_slack_blocks(self, alerts: list[Alert]) -> list[dict]:
        """Build Slack Block Kit payload for visual alert messages."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "⚡ PV Plant Alert — Automated Report",
                    "emoji": True,
                },
            },
            {"type": "divider"},
        ]

        for alert in alerts:
            emoji = self.SEVERITY_EMOJI.get(alert.severity, "⚪")
            color = self.SEVERITY_COLORS.get(alert.severity, "#95A5A6")

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *{alert.rule_name}* — `{alert.severity.value.upper()}`\n"
                        f"{alert.message}\n"
                        f"_Start: {alert.timestamp_start}_"
                    ),
                },
            })

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "📊 Generated by *pv-report-automation v2.0* | ENERTEC LATINOAMÉRICA",
                },
            ],
        })
        return blocks

    # ------------------------------------------------------------------
    # Email channel (SMTP with SSL/TLS)
    # ------------------------------------------------------------------

    def _send_email(
        self,
        alerts: list[Alert],
        pdf_path: Optional[str | Path] = None,
    ) -> bool:
        """Send an alert email with optional PDF attachment via SMTP.

        Security:
          - Uses SSL context for encrypted connections.
          - Supports both STARTTLS (port 587) and direct SSL (port 465).
        """
        try:
            config = self.email_config

            # Build email message
            msg = MIMEMultipart()
            msg["From"] = config.sender_email
            msg["To"] = ", ".join(config.recipients)
            msg["Subject"] = self._build_email_subject(alerts)

            # HTML body
            html_body = self._build_email_html(alerts)
            msg.attach(MIMEText(html_body, "html"))

            # Attach PDF report if available
            if pdf_path:
                pdf_path = Path(pdf_path)
                if pdf_path.exists():
                    with open(pdf_path, "rb") as f:
                        attachment = MIMEBase("application", "pdf")
                        attachment.set_payload(f.read())
                    encoders.encode_base64(attachment)
                    attachment.add_header(
                        "Content-Disposition",
                        f"attachment; filename={pdf_path.name}",
                    )
                    msg.attach(attachment)
                    logger.info("PDF report attached: %s", pdf_path.name)

            # Send via SMTP
            context = ssl.create_default_context()

            if config.use_tls:
                with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(config.sender_email, config.sender_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(
                    config.smtp_server, config.smtp_port, context=context
                ) as server:
                    server.login(config.sender_email, config.sender_password)
                    server.send_message(msg)

            logger.info("Email sent to %d recipients.", len(config.recipients))
            return True

        except smtplib.SMTPException as exc:
            logger.error("SMTP error: %s", exc)
            return False
        except Exception as exc:
            logger.error("Email send failed: %s", exc, exc_info=True)
            return False

    def _build_email_subject(self, alerts: list[Alert]) -> str:
        """Generate a descriptive email subject line based on alert severity."""
        critical = sum(1 for a in alerts if a.severity == Severity.CRITICAL)
        warnings = sum(1 for a in alerts if a.severity == Severity.WARNING)

        if critical:
            return f"🔴 CRITICAL: {critical} alert(s) — PV Plant Monitoring"
        elif warnings:
            return f"🟡 WARNING: {warnings} alert(s) — PV Plant Monitoring"
        return f"🟢 INFO: {len(alerts)} notification(s) — PV Plant Monitoring"

    def _build_email_html(self, alerts: list[Alert]) -> str:
        """Generate a professional HTML email body with alert details."""
        rows = ""
        for alert in alerts:
            color = self.SEVERITY_COLORS.get(alert.severity, "#95A5A6")
            emoji = self.SEVERITY_EMOJI.get(alert.severity, "⚪")
            rows += f"""
            <tr>
                <td style="padding:10px; border-bottom:1px solid #eee;">
                    <span style="color:{color}; font-weight:bold;">
                        {emoji} {alert.severity.value.upper()}
                    </span>
                </td>
                <td style="padding:10px; border-bottom:1px solid #eee;">
                    <strong>{alert.rule_name}</strong>
                </td>
                <td style="padding:10px; border-bottom:1px solid #eee;">
                    {alert.message}
                </td>
                <td style="padding:10px; border-bottom:1px solid #eee;">
                    {alert.timestamp_start.strftime('%Y-%m-%d %H:%M') if alert.timestamp_start else 'N/A'}
                </td>
            </tr>"""

        return f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; color: #333; padding: 20px;">
            <h2 style="color: #2C3E50;">⚡ PV Plant — Automated Alert Report</h2>
            <p>The monitoring system has detected the following anomalies:</p>
            <table style="width:100%; border-collapse:collapse; margin:20px 0;">
                <thead>
                    <tr style="background:#34495E; color:white;">
                        <th style="padding:10px; text-align:left;">Severity</th>
                        <th style="padding:10px; text-align:left;">Rule</th>
                        <th style="padding:10px; text-align:left;">Details</th>
                        <th style="padding:10px; text-align:left;">Time</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
            <hr style="border:0; border-top:1px solid #ccc;">
            <p style="font-size:12px; color:#888;">
                Generated by <strong>pv-report-automation v2.0</strong> |
                ENERTEC LATINOAMÉRICA | Maintainer: Miguel Ángel Mejía Sánchez
            </p>
        </body>
        </html>"""

    # ------------------------------------------------------------------
    # Simulation (for demo / portfolio purposes)
    # ------------------------------------------------------------------

    @staticmethod
    def simulate_dispatch(alerts: list[Alert]) -> str:
        """Generate a simulated notification output for demo purposes.

        This method is used when running the system without real SMTP
        or Slack credentials (e.g., during a recruiter demo or CI/CD).

        Returns
        -------
        str
            Formatted text representation of what would be sent.
        """
        if not alerts:
            return "✅ No anomalies detected. All systems operational."

        lines = [
            "=" * 60,
            "⚡ SIMULATED ALERT DISPATCH — pv-report-automation v2.0",
            "=" * 60,
            "",
        ]

        for i, alert in enumerate(alerts, 1):
            emoji = NotificationOrchestrator.SEVERITY_EMOJI.get(alert.severity, "⚪")
            lines.extend([
                f"  Alert #{i}",
                f"  {emoji} Severity : {alert.severity.value.upper()}",
                f"  📋 Rule     : {alert.rule_name}",
                f"  💬 Message  : {alert.message}",
                f"  🕐 Start    : {alert.timestamp_start}",
                f"  🕐 End      : {alert.timestamp_end or 'Ongoing'}",
                f"  📊 Details  : {alert.details}",
                "-" * 60,
            ])

        lines.extend([
            "",
            f"  Total Alerts: {len(alerts)}",
            f"  Channels: Slack ✅ | Email ✅ (simulated)",
            "",
            "=" * 60,
        ])
        return "\n".join(lines)
