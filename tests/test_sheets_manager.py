# -*- coding: utf-8 -*-
"""
Tests for GoogleSheetsManager — Live Telemetry Sync & Restoration
=================================================================
"""

from src.sheets_manager import GoogleSheetsManager


def test_sheets_manager_local_lifecycle_inject_and_restore(tmp_path):
    csv_path = tmp_path / "live_telemetry.csv"
    mgr = GoogleSheetsManager(local_csv_path=csv_path, history_csv_path=tmp_path / "hist.csv")
    df_initial = mgr.fetch_telemetry()
    assert not df_initial.empty
    assert (df_initial["status_code"] == "0x00").all()

    # Inject fault
    target_panel = df_initial["panel_id"].iloc[-1]
    df_fault = mgr.inject_fault(
        panel_id=target_panel,
        v_dc_string_2=160.0,
        temp_heatsink=89.0,
        status_code="0x05",
    )
    fault_row = df_fault[df_fault["panel_id"] == target_panel].iloc[-1]
    assert fault_row["v_dc_string_2"] == 160.0
    assert fault_row["status_code"] == "0x05"

    # Restore nominal values
    df_restored = mgr.restore_nominal_values()
    restored_row = df_restored[df_restored["panel_id"] == target_panel].iloc[-1]
    assert restored_row["status_code"] == "0x00"
    assert restored_row["temp_heatsink"] <= 60.0
    assert abs(restored_row["v_dc_string_1"] - restored_row["v_dc_string_2"]) < 10.0


def test_extract_sheet_id_from_url():
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
    assert (
        GoogleSheetsManager.extract_sheet_id(url)
        == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    )


def test_incident_history_upsert_and_persistence(tmp_path):
    csv_path = tmp_path / "live_telemetry.csv"
    history_path = tmp_path / "incident_history.csv"
    mgr = GoogleSheetsManager(local_csv_path=csv_path, history_csv_path=history_path)

    hist_empty = mgr.fetch_incident_history()
    assert hist_empty.empty
    assert "incident_id" in hist_empty.columns
    assert "status" in hist_empty.columns

    # 1. Register active incident
    mgr.upsert_incident_record(
        {
            "incident_id": "INC-20261109-01",
            "status": "EN EMERGENCIA ASIGNADA",
            "created_at": "2026-11-09 10:00:00",
            "resolved_at": "Pendiente",
            "panel_id": "PNL-B04-12",
            "location_block": "Bloque B - Fila 4 - Posicion 12",
            "technician_name": "Laura Reclutadora",
            "technician_email": "laura@empresa.com",
            "supervisor_name": "Ing. Miguel Ángel Mejía Sánchez",
            "resolution_note": "En atención de campo",
        }
    )
    hist_active = mgr.fetch_incident_history()
    assert len(hist_active) == 1
    assert hist_active.iloc[0]["incident_id"] == "INC-20261109-01"
    assert hist_active.iloc[0]["status"] == "EN EMERGENCIA ASIGNADA"

    # 2. Update same incident when resolved (no duplicate rows)
    mgr.upsert_incident_record(
        {
            "incident_id": "INC-20261109-01",
            "status": "RESUELTO",
            "created_at": "2026-11-09 10:00:00",
            "resolved_at": "2026-11-09 10:15:00",
            "panel_id": "PNL-B04-12",
            "location_block": "Bloque B - Fila 4 - Posicion 12",
            "technician_name": "Laura Reclutadora",
            "technician_email": "laura@empresa.com",
            "supervisor_name": "Ing. Miguel Ángel Mejía Sánchez",
            "resolution_note": "Conector MC4 reemplazado",
        }
    )
    hist_resolved = mgr.fetch_incident_history()
    assert len(hist_resolved) == 1
    assert hist_resolved.iloc[0]["status"] == "RESUELTO"
    assert hist_resolved.iloc[0]["resolution_note"] == "Conector MC4 reemplazado"
