# -*- coding: utf-8 -*-
"""
Tests for GoogleSheetsManager — Live Telemetry Sync & Restoration
=================================================================
"""

from src.sheets_manager import GoogleSheetsManager


def test_sheets_manager_local_lifecycle_inject_and_restore(tmp_path):
    csv_path = tmp_path / "live_telemetry.csv"
    mgr = GoogleSheetsManager(local_csv_path=csv_path)
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
