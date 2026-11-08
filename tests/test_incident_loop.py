# -*- coding: utf-8 -*-
"""
Tests for IMAPListener & IncidentManager Closed-Loop State Machine
==================================================================
"""

from src.imap_listener import IMAPListener
from src.incident_manager import IncidentManager, TechnicianState
from src.sheets_manager import GoogleSheetsManager
from src.transformer import SolarDataTransformer


def test_parse_reply_body_strips_quoted_lines():
    raw = (
        "Ya revisé el panel PNL-B04-12 y cambié el conector MC4.\n\n"
        "> El 08/11/2026 escribió:\n"
        "> Alerta crítica"
    )
    cleaned = IMAPListener.parse_reply_body(raw)
    assert "cambié el conector MC4" in cleaned
    assert "> Alerta crítica" not in cleaned


def test_full_closed_loop_incident_lifecycle_no_duplicate_emails(tmp_path):
    csv_path = tmp_path / "live_telemetry.csv"
    sheets = GoogleSheetsManager(local_csv_path=csv_path)
    transformer = SolarDataTransformer()
    manager = IncidentManager(sheets_manager=sheets, output_dir=tmp_path)

    manager.register_technician("Laura Reclutadora", "laura@empresa.com")
    assert manager.state == TechnicianState.AVAILABLE

    # 1. Normal telemetry -> stays AVAILABLE
    df_clean = transformer.transform_dataframe(sheets.fetch_telemetry())
    status_1 = manager.evaluate_telemetry(df_clean)
    assert status_1["state"] == TechnicianState.AVAILABLE

    # 2. Sabotage telemetry -> transitions to EMERGENCY_ASSIGNED and sends 1 email
    sheets.inject_fault(
        panel_id="PNL-B04-12",
        v_dc_string_2=165.0,
        temp_heatsink=88.0,
        status_code="0x05",
    )
    df_fault = transformer.transform_dataframe(sheets.fetch_telemetry())
    status_2 = manager.evaluate_telemetry(df_fault)
    assert status_2["state"] == TechnicianState.EMERGENCY_ASSIGNED
    assert status_2["email_dispatched_count"] == 1
    incident_id = status_2["incident_id"]

    # 3. Re-evaluating same fault on Streamlit refresh does NOT send duplicate email
    status_3 = manager.evaluate_telemetry(df_fault)
    assert status_3["incident_id"] == incident_id
    assert status_3["email_dispatched_count"] == 1

    # 4. Technician replies to email -> restores sheet and normalizes platform
    resolution = manager.process_resolution(
        resolution_note="Conector MC4 reemplazado y coordinado con supervisor.",
        resolved_by="email_reply",
    )
    assert resolution["state"] == TechnicianState.RESOLVED
    df_after = transformer.transform_dataframe(sheets.fetch_telemetry())
    status_4 = manager.evaluate_telemetry(df_after)
    assert status_4["state"] == TechnicianState.AVAILABLE
