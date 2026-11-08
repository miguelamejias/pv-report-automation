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
    # Closed-Loop Incident Alert Email (v3.0 NOC)
    # ------------------------------------------------------------------

    def _build_incident_subject(self, incident_id: str, alerts: list[Alert]) -> str:
        """Build subject with unique [INC-XXXX] tag for reply tracking."""
        primary = alerts[0] if alerts else None
        panel_id = primary.details.get("panel_id", "PNL-B04-12") if primary else "PNL-B04-12"
        return (
            f"🔴 [ALERTA CRÍTICA] [{incident_id}] Falla en Panel {panel_id} "
            f"— Acción Técnica Requerida"
        )

    def _build_incident_email_html(
        self,
        alerts: list[Alert],
        incident_id: str,
        technician_name: str,
        supervisor_name: str = "Ing. Miguel Ángel Mejía Sánchez",
    ) -> str:
        """Build rich HTML work order email instructing technician to prepare tools & contact supervisor."""
        primary = alerts[0] if alerts else None
        details = primary.details if primary else {}
        panel_id = details.get("panel_id", "PNL-B04-12")
        location_block = details.get("location_block", "Bloque B - Fila 4 - Posicion 12")
        lat = details.get("latitude", 4.9186)
        lon = details.get("longitude", -73.9982)
        diag_msg = primary.message if primary else "Anomalía crítica detectada en string fotovoltaico."

        return f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; color: #2C3E50; padding: 20px; background-color: #F8F9FA;">
            <div style="max-width: 680px; margin: auto; background: #FFFFFF; border-radius: 8px; border-top: 6px solid #E74C3C; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
                <h2 style="color: #E74C3C; margin-top: 0;">🚨 ORDEN DE EMERGENCIA EN PLANTA SOLAR — [{incident_id}]</h2>
                <p>Hola <strong>{technician_name}</strong>,</p>
                <p>El Centro de Operaciones de Red (NOC) de <strong>ENERTEC LATINOAMÉRICA</strong> te ha asignado un incidente crítico detectado en tiempo real:</p>

                <table style="width: 100%; border-collapse: collapse; margin: 16px 0; background: #FDF2E9; border-radius: 6px;">
                    <tr>
                        <td style="padding: 10px; font-weight: bold; width: 38%;">ID de Incidente:</td>
                        <td style="padding: 10px;"><code>{incident_id}</code></td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; font-weight: bold;">Panel / String Afectado:</td>
                        <td style="padding: 10px;"><strong>{panel_id}</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; font-weight: bold;">Ubicación Física:</td>
                        <td style="padding: 10px;"><strong>{location_block}</strong> (GPS: {lat}, {lon})</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; font-weight: bold;">Diagnóstico Técnico:</td>
                        <td style="padding: 10px;">{diag_msg}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; font-weight: bold;">Supervisor en Turno:</td>
                        <td style="padding: 10px;"><strong>{supervisor_name}</strong></td>
                    </tr>
                </table>

                <h3 style="color: #2C3E50;">🛠️ Instrucciones Obligatorias antes de Intervenir:</h3>
                <ol style="line-height: 1.6;">
                    <li><strong>Preparar equipos y EPP:</strong> Alistar multímetro DC 1000V, pinza amperimétrica, cámara termográfica, conectores MC4 de repuesto y equipo de protección dieléctrico.</li>
                    <li><strong>Hablar con tu supervisor:</strong> Reportarse inmediatamente con <strong>{supervisor_name}</strong> para validar el bloqueo/etiquetado (LOTO) antes de intervenir el arreglo en <em>{location_block}</em>.</li>
                    <li><strong>Confirmar cierre por correo:</strong> Una vez atendida la emergencia y restablecido el panel, <strong>RESPONDE DIRECTAMENTE A ESTE CORREO ("Responder / Reply")</strong> indicando las acciones realizadas para que la plataforma normalice el estado automáticamente.</li>
                </ol>

                <p style="font-size: 12px; color: #7F8C8D; margin-top: 24px; border-top: 1px solid #EAECEE; padding-top: 12px;">
                    Se adjunta Orden de Trabajo ejecutiva en PDF.<br>
                    Generado por <strong>pv-report-automation v3.0 NOC</strong> | ENERTEC LATINOAMÉRICA
                </p>
            </div>
        </body>
        </html>"""

    def send_incident_alert(
        self,
        alerts: list[Alert],
        incident_id: str,
        technician_name: str,
        technician_email: str,
        supervisor_name: str = "Ing. Miguel Ángel Mejía Sánchez",
        pdf_path: Optional[str | Path] = None,
    ) -> dict:
        """Send an incident work-order email to the registered on-duty technician."""
        subject = self._build_incident_subject(incident_id, alerts)
        html_body = self._build_incident_email_html(
            alerts=alerts,
            incident_id=incident_id,
            technician_name=technician_name,
            supervisor_name=supervisor_name,
        )

        if not self.email_config or not self.email_config.sender_password:
            logger.info(
                "SMTP credentials not configured; simulating incident email [%s] to %s",
                incident_id,
                technician_email,
            )
            return {
                "sent": False,
                "simulated": True,
                "incident_id": incident_id,
                "recipient": technician_email,
                "subject": subject,
            }

        try:
            config = self.email_config
            recipients = [technician_email] + [
                r for r in config.recipients if r != technician_email
            ]
            msg = MIMEMultipart()
            msg["From"] = config.sender_email
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if pdf_path:
                pdf_file = Path(pdf_path)
                if pdf_file.exists():
                    with open(pdf_file, "rb") as f:
                        attachment = MIMEBase("application", "pdf")
                        attachment.set_payload(f.read())
                    encoders.encode_base64(attachment)
                    attachment.add_header(
                        "Content-Disposition",
                        f"attachment; filename={pdf_file.name}",
                    )
                    msg.attach(attachment)

            context = ssl.create_default_context()
            if config.use_tls:
                with smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=15) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(config.sender_email, config.sender_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(
                    config.smtp_server, config.smtp_port, context=context, timeout=15
                ) as server:
                    server.login(config.sender_email, config.sender_password)
                    server.send_message(msg)

            logger.info("Incident email [%s] sent to %s", incident_id, technician_email)
            return {
                "sent": True,
                "simulated": False,
                "incident_id": incident_id,
                "recipient": technician_email,
                "subject": subject,
            }
        except Exception as exc:
            logger.error("Failed to send incident email [%s]: %s", incident_id, exc)
            return {
                "sent": False,
                "simulated": True,
                "error": str(exc),
                "incident_id": incident_id,
                "recipient": technician_email,
                "subject": subject,
            }

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
