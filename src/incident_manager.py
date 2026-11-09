# -*- coding: utf-8 -*-
"""
IncidentManager — Closed-Loop Solar NOC State Machine
=====================================================

Coordinates the end-to-end lifecycle of a real-time solar plant incident:
  1. AVAILABLE (🟢)         : Technician registered, telemetry nominal.
  2. EMERGENCY_ASSIGNED (🔴): Anomaly detected in Google Sheets -> Work Order
                              PDF generated -> Single alert email sent to
                              on-duty technician -> Logged in Incident History
                              as EN EMERGENCIA ASIGNADA.
  3. RESOLVED (🟢)          : Technician replies to the alert email ->
                              Google Sheets restored to nominal values ->
                              Incident History updated to RESUELTO ->
                              Platform returns to normal operation.

Includes persistent deduplication across page reloads: before dispatching an
alert email, checks both in-memory state and the persisted `incident_history.csv`
so reloading the web page never sends duplicate emails for an already-notified fault.

Author: Miguel Ángel Mejía Sánchez
"""

import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

from src.anomaly_engine import Alert, AnomalyEngine, Severity
from src.imap_listener import IMAPListener
from src.notifications import NotificationOrchestrator
from src.report_generator import ReportGenerator
from src.sheets_manager import GoogleSheetsManager

logger = logging.getLogger(__name__)


class TechnicianState(Enum):
    """Operational state of the registered field technician."""

    AVAILABLE = "available"
    EMERGENCY_ASSIGNED = "emergency_assigned"
    RESOLVED = "resolved"


class IncidentManager:
    """State machine managing technician registration, incident dispatch, and resolution."""

    def __init__(
        self,
        sheets_manager: GoogleSheetsManager,
        output_dir: str | Path = "output",
        orchestrator: Optional[NotificationOrchestrator] = None,
        imap_listener: Optional[IMAPListener] = None,
        plant_name: str = "ENERTEC Planta Sabana Norte",
        nominal_power_kw: float = 10.0,
    ) -> None:
        self.sheets_manager = sheets_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.orchestrator = orchestrator or NotificationOrchestrator()
        self.imap_listener = imap_listener or IMAPListener()
        self.engine = AnomalyEngine.create_default()
        self.report_generator = ReportGenerator(
            plant_name=plant_name,
            nominal_power_kw=nominal_power_kw,
            output_dir=self.output_dir,
        )

        self.state: TechnicianState = TechnicianState.AVAILABLE
        self.technician_name: str = "Técnico en Turno"
        self.technician_email: str = ""
        self.supervisor_name: str = "Ing. Miguel Ángel Mejía Sánchez"

        self.active_incident_id: Optional[str] = None
        self.active_created_at: Optional[str] = None
        self.active_alerts: list[Alert] = []
        self.active_pdf_path: Optional[Path] = None
        self.email_dispatched_count: int = 0
        self.last_email_result: Optional[dict] = None
        self.incident_history: list[dict] = (
            self.sheets_manager.fetch_incident_history().to_dict("records")
        )
        self._incident_counter: int = len(self.incident_history)

        # Restore active incident state from persisted history if page was reloaded
        open_inc = self._find_open_incident_in_history()
        if open_inc:
            self.state = TechnicianState.EMERGENCY_ASSIGNED
            self.active_incident_id = str(open_inc.get("incident_id", ""))
            self.active_created_at = str(open_inc.get("created_at", ""))
            if open_inc.get("technician_name"):
                self.technician_name = str(open_inc["technician_name"])
            if open_inc.get("technician_email"):
                self.technician_email = str(open_inc["technician_email"])
            if open_inc.get("supervisor_name"):
                self.supervisor_name = str(open_inc["supervisor_name"])
            pdf_candidate = self.output_dir / f"incident_{self.active_incident_id}.pdf"
            if pdf_candidate.exists():
                self.active_pdf_path = pdf_candidate

    def _find_open_incident_in_history(
        self, panel_id: Optional[str] = None
    ) -> Optional[dict]:
        """Check persisted incident history for an already-notified open emergency."""
        hist_df = self.sheets_manager.fetch_incident_history()
        if hist_df.empty or "status" not in hist_df.columns:
            return None
        open_rows = hist_df[
            hist_df["status"].astype(str).str.upper() == "EN EMERGENCIA ASIGNADA"
        ]
        if open_rows.empty:
            return None
        if panel_id and "panel_id" in open_rows.columns:
            panel_match = open_rows[
                open_rows["panel_id"].astype(str) == str(panel_id)
            ]
            if not panel_match.empty:
                return panel_match.iloc[0].to_dict()
        return open_rows.iloc[0].to_dict()

    def register_technician(
        self,
        name: str,
        email: str,
        supervisor: str = "Ing. Miguel Ángel Mejía Sánchez",
    ) -> None:
        """Register the recruiter/technician on duty."""
        self.technician_name = name.strip() or "Técnico en Turno"
        self.technician_email = email.strip()
        self.supervisor_name = supervisor.strip() or "Ing. Miguel Ángel Mejía Sánchez"
        logger.info(
            "Registered on-duty technician: %s <%s>",
            self.technician_name,
            self.technician_email,
        )

    def evaluate_telemetry(self, df: pd.DataFrame) -> dict:
        """Evaluate current telemetry DataFrame and transition state without duplicate emails."""
        alerts = self.engine.analyze(df)
        actionable = [
            a for a in alerts if a.severity in (Severity.CRITICAL, Severity.WARNING)
        ]

        if not actionable:
            self.state = TechnicianState.AVAILABLE
            self.active_incident_id = None
            self.active_created_at = None
            self.active_alerts = []
            self.active_pdf_path = None
            return self._snapshot()

        primary = actionable[0]
        panel_id = str(primary.details.get("panel_id", "PNL-B04-12"))

        # Deduplication cycle: check both in-memory state and persisted incident_history.csv
        existing_open = self._find_open_incident_in_history(panel_id=panel_id)
        already_notified = (
            getattr(self.state, "value", None)
            == TechnicianState.EMERGENCY_ASSIGNED.value
            and bool(self.active_incident_id)
        ) or (existing_open is not None)

        if not already_notified:
            self._incident_counter = len(self.sheets_manager.fetch_incident_history()) + 1
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y%m%d-%H%M")
            self.active_incident_id = f"INC-{now_str}-{self._incident_counter:02d}"
            self.active_created_at = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            self.state = TechnicianState.EMERGENCY_ASSIGNED
            self.active_alerts = actionable

            self.active_pdf_path = self.report_generator.generate_incident_pdf(
                df=df,
                alerts=actionable,
                incident_id=self.active_incident_id,
                technician_name=self.technician_name,
                supervisor_name=self.supervisor_name,
            )

            self.last_email_result = self.orchestrator.send_incident_alert(
                alerts=actionable,
                incident_id=self.active_incident_id,
                technician_name=self.technician_name,
                technician_email=self.technician_email or "tecnico@enertec.com",
                supervisor_name=self.supervisor_name,
                pdf_path=self.active_pdf_path,
            )
            self.email_dispatched_count += 1

            active_record = {
                "incident_id": self.active_incident_id,
                "status": "EN EMERGENCIA ASIGNADA",
                "created_at": self.active_created_at,
                "resolved_at": "Pendiente",
                "panel_id": panel_id,
                "location_block": primary.details.get(
                    "location_block", "Bloque B - Fila 4 - Posicion 12"
                ),
                "technician_name": self.technician_name,
                "technician_email": self.technician_email,
                "supervisor_name": self.supervisor_name,
                "resolution_note": "En atención de emergencia por técnico en turno",
            }
            hist_df = self.sheets_manager.upsert_incident_record(active_record)
            self.incident_history = hist_df.to_dict("records")
        else:
            # Fault already notified: restore state from persisted history without sending duplicate email
            self.state = TechnicianState.EMERGENCY_ASSIGNED
            if existing_open and not self.active_incident_id:
                self.active_incident_id = str(existing_open.get("incident_id", ""))
                self.active_created_at = str(existing_open.get("created_at", ""))
            self.active_alerts = actionable
            if self.active_incident_id:
                pdf_candidate = (
                    self.output_dir / f"incident_{self.active_incident_id}.pdf"
                )
                if pdf_candidate.exists():
                    self.active_pdf_path = pdf_candidate
            self.incident_history = (
                self.sheets_manager.fetch_incident_history().to_dict("records")
            )

        return self._snapshot()

    def poll_imap_for_resolution(self) -> Optional[dict]:
        """Check IMAP inbox if an incident is currently active; resolve automatically if reply arrived."""
        if (
            getattr(self.state, "value", None)
            != TechnicianState.EMERGENCY_ASSIGNED.value
            or not self.active_incident_id
        ):
            return None

        reply = self.imap_listener.check_for_resolution_reply(
            incident_id=self.active_incident_id,
            technician_email=self.technician_email,
        )
        if reply:
            return self.process_resolution(
                resolution_note=reply.get("body", "Atendido por correo electrónico."),
                resolved_by=f"email_reply ({reply.get('from', self.technician_email)})",
            )
        return None

    def process_resolution(
        self,
        resolution_note: str,
        resolved_by: str = "email_reply",
    ) -> dict:
        """Restore Google Sheets telemetry to nominal values and close the active incident."""
        existing_open = self._find_open_incident_in_history()
        inc_id = (
            self.active_incident_id
            or (str(existing_open["incident_id"]) if existing_open else None)
            or "INC-MANUAL"
        )
        created_at = (
            self.active_created_at
            or (str(existing_open["created_at"]) if existing_open else None)
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        primary = self.active_alerts[0] if self.active_alerts else None
        panel_id = (
            primary.details.get("panel_id")
            if primary
            else (existing_open.get("panel_id") if existing_open else "PNL-B04-12")
        )
        location_block = (
            primary.details.get("location_block")
            if primary
            else (
                existing_open.get("location_block")
                if existing_open
                else "Bloque B - Fila 4 - Posicion 12"
            )
        )

        self.sheets_manager.restore_nominal_values()

        record = {
            "incident_id": inc_id,
            "status": "RESUELTO",
            "created_at": created_at,
            "resolved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "panel_id": panel_id,
            "location_block": location_block,
            "technician_name": self.technician_name,
            "technician_email": self.technician_email,
            "supervisor_name": self.supervisor_name,
            "resolved_by": resolved_by,
            "resolution_note": resolution_note,
        }
        hist_df = self.sheets_manager.upsert_incident_record(record)
        self.incident_history = hist_df.to_dict("records")

        self.state = TechnicianState.RESOLVED
        self.active_incident_id = None
        self.active_created_at = None
        self.active_alerts = []
        return self._snapshot()

    def _snapshot(self) -> dict:
        """Return a serializable dictionary of the current NOC state."""
        primary = self.active_alerts[0] if self.active_alerts else None
        return {
            "state": self.state,
            "incident_id": self.active_incident_id,
            "technician_name": self.technician_name,
            "technician_email": self.technician_email,
            "supervisor_name": self.supervisor_name,
            "email_dispatched_count": self.email_dispatched_count,
            "last_email_result": self.last_email_result,
            "pdf_path": str(self.active_pdf_path) if self.active_pdf_path else None,
            "active_alerts": self.active_alerts,
            "affected_panel": primary.details if primary else None,
            "history": self.incident_history,
        }
