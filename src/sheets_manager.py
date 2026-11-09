# -*- coding: utf-8 -*-
"""
GoogleSheetsManager — Bidirectional Google Sheets & Local Telemetry Sync
========================================================================

Connects the Solar NOC platform to a shared Google Sheet in Google Drive
(or local CSV mirror) containing real-time panel telemetry, physical
location coordinates, and the persistent Incident History audit log.

Capabilities:
  1. Read telemetry from a shared Google Sheets URL/ID (via CSV export URL
     or gspread Service Account) with automatic local CSV fallback.
  2. Inject simulated hardware faults into a specific panel/string for
     recruiter demonstrations.
  3. Automatically restore faulted rows back to nominal values when the
     on-duty technician replies to the incident alert email.
  4. Record and update every incident's lifecycle state
     (EN EMERGENCIA ASIGNADA -> RESUELTO) in the Incident History sheet/CSV.

Author: Miguel Ángel Mejía Sánchez
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

TZ_COLOMBIA = timezone(timedelta(hours=-5))

DEFAULT_PANELS = [
    ("PNL-A01-01", "Bloque A - Fila 1 - Posicion 1", 4.9186, -73.9982),
    ("PNL-A01-02", "Bloque A - Fila 1 - Posicion 2", 4.9187, -73.9981),
    ("PNL-A02-04", "Bloque A - Fila 2 - Posicion 4", 4.9188, -73.9980),
    ("PNL-A03-06", "Bloque A - Fila 3 - Posicion 6", 4.9189, -73.9979),
    ("PNL-B01-03", "Bloque B - Fila 1 - Posicion 3", 4.9190, -73.9977),
    ("PNL-B02-07", "Bloque B - Fila 2 - Posicion 7", 4.9191, -73.9976),
    ("PNL-B04-12", "Bloque B - Fila 4 - Posicion 12", 4.9192, -73.9975),
    ("PNL-B05-15", "Bloque B - Fila 5 - Posicion 15", 4.9193, -73.9974),
    ("PNL-C01-02", "Bloque C - Fila 1 - Posicion 2", 4.9194, -73.9973),
    ("PNL-C02-05", "Bloque C - Fila 2 - Posicion 5", 4.9195, -73.9972),
    ("PNL-C03-08", "Bloque C - Fila 3 - Posicion 8", 4.9196, -73.9971),
    ("PNL-C04-10", "Bloque C - Fila 4 - Posicion 10", 4.9197, -73.9970),
]

HISTORY_COLUMNS = [
    "incident_id",
    "status",
    "created_at",
    "resolved_at",
    "panel_id",
    "location_block",
    "technician_name",
    "technician_email",
    "supervisor_name",
    "resolution_note",
]


class GoogleSheetsManager:
    """Manages reading/restoring solar panel telemetry and incident history in Google Sheets & CSV."""

    def __init__(
        self,
        sheet_id_or_url: Optional[str] = None,
        local_csv_path: str | Path = "sample_data/live_telemetry.csv",
        credentials_path: Optional[str | Path] = None,
        history_csv_path: str | Path = "sample_data/incident_history.csv",
    ) -> None:
        self.sheet_id = (
            self.extract_sheet_id(sheet_id_or_url) if sheet_id_or_url else ""
        )
        self.local_csv_path = Path(local_csv_path)
        self.history_csv_path = Path(history_csv_path)
        self.credentials_path = Path(credentials_path) if credentials_path else None
        self.local_csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.local_csv_path.exists():
            self._create_default_local_csv()
        if not self.history_csv_path.exists():
            pd.DataFrame(columns=HISTORY_COLUMNS).to_csv(
                self.history_csv_path, index=False
            )

    @staticmethod
    def extract_sheet_id(sheet_id_or_url: str) -> str:
        """Extract the Google Spreadsheet ID from a full URL or return raw ID."""
        if not sheet_id_or_url:
            return ""
        text = sheet_id_or_url.strip()
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
        if match:
            return match.group(1)
        return text

    @property
    def share_url(self) -> str:
        """Return the browser URL for the configured Google Sheet."""
        if not self.sheet_id:
            return ""
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit?usp=sharing"

    def _create_default_local_csv(self) -> pd.DataFrame:
        """Create a clean 12-panel nominal telemetry table on disk."""
        base_ts = datetime(2024, 3, 17, 11, 0, tzinfo=TZ_COLOMBIA)
        rows = []
        for idx, (panel_id, loc_block, lat, lon) in enumerate(DEFAULT_PANELS):
            ts = base_ts + timedelta(minutes=idx * 5)
            rows.append({
                "timestamp": ts.isoformat(),
                "panel_id": panel_id,
                "location_block": loc_block,
                "latitude": lat,
                "longitude": lon,
                "v_dc_string_1": 392.0,
                "v_dc_string_2": 390.5,
                "v_dc_string_3": 391.0,
                "v_dc_string_4": 391.5,
                "i_dc_total": 13.4,
                "p_ac_output": 4980.0,
                "temp_heatsink": 46.5,
                "irradiance_poa": 880.0,
                "status_code": "0x00",
            })
        df = pd.DataFrame(rows)
        df.to_csv(self.local_csv_path, index=False)
        return df

    def fetch_telemetry(self) -> pd.DataFrame:
        """Fetch the latest telemetry from Google Sheets (if configured) or local CSV."""
        if self.sheet_id:
            try:
                csv_export_url = (
                    f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/export?format=csv"
                )
                df = pd.read_csv(csv_export_url)
                if not df.empty and "timestamp" in df.columns:
                    df.to_csv(self.local_csv_path, index=False)
                    logger.info("Fetched %d rows from Google Sheet %s", len(df), self.sheet_id)
                    return df
            except Exception as exc:
                logger.warning(
                    "Could not fetch live Google Sheet (%s), using local mirror: %s",
                    self.sheet_id,
                    exc,
                )

        if not self.local_csv_path.exists():
            return self._create_default_local_csv()
        return pd.read_csv(self.local_csv_path)

    def save_telemetry(self, df: pd.DataFrame) -> pd.DataFrame:
        """Save updated telemetry to local CSV and sync to Google Sheets if credentials exist."""
        df.to_csv(self.local_csv_path, index=False)
        if self.sheet_id and self.credentials_path and self.credentials_path.exists():
            try:
                import gspread

                gc = gspread.service_account(filename=str(self.credentials_path))
                sh = gc.open_by_key(self.sheet_id)
                ws = sh.get_worksheet(0)
                ws.clear()
                ws.update([df.columns.values.tolist()] + df.values.tolist())
                logger.info("Synced %d rows back to Google Sheet %s", len(df), self.sheet_id)
            except Exception as exc:
                logger.warning("Could not write to Google Sheet via gspread: %s", exc)
        return df

    def fetch_incident_history(self) -> pd.DataFrame:
        """Fetch the persistent incident history log (local CSV + Google Sheets mirror)."""
        if not self.history_csv_path.exists():
            df = pd.DataFrame(columns=HISTORY_COLUMNS)
            df.to_csv(self.history_csv_path, index=False)
            return df
        try:
            df = pd.read_csv(self.history_csv_path)
            for col in HISTORY_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            return df[HISTORY_COLUMNS]
        except Exception:
            return pd.DataFrame(columns=HISTORY_COLUMNS)

    def upsert_incident_record(self, record: dict) -> pd.DataFrame:
        """Insert a new incident or update an existing incident's status in the history sheet."""
        df = self.fetch_incident_history()
        inc_id = str(record.get("incident_id", "")).strip()
        normalized_row = {col: str(record.get(col, "")) for col in HISTORY_COLUMNS}

        if not df.empty and inc_id in df["incident_id"].astype(str).values:
            mask = df["incident_id"].astype(str) == inc_id
            for col, val in normalized_row.items():
                if val or col != "created_at":
                    df.loc[mask, col] = val
        else:
            new_row_df = pd.DataFrame([normalized_row], columns=HISTORY_COLUMNS)
            df = pd.concat([new_row_df, df], ignore_index=True)

        df.to_csv(self.history_csv_path, index=False)

        if self.sheet_id and self.credentials_path and self.credentials_path.exists():
            try:
                import gspread

                gc = gspread.service_account(filename=str(self.credentials_path))
                sh = gc.open_by_key(self.sheet_id)
                try:
                    ws_hist = sh.worksheet("Historial_Incidentes")
                except Exception:
                    ws_hist = sh.add_worksheet(
                        title="Historial_Incidentes", rows=200, cols=len(HISTORY_COLUMNS)
                    )
                ws_hist.clear()
                ws_hist.update([df.columns.values.tolist()] + df.fillna("").values.tolist())
                logger.info(
                    "Synced %d incident history rows to Google Sheet tab Historial_Incidentes",
                    len(df),
                )
            except Exception as exc:
                logger.warning("Could not sync incident history to Google Sheet: %s", exc)

        return df

    def inject_fault(
        self,
        panel_id: str = "PNL-B04-12",
        v_dc_string_2: float = 175.0,
        temp_heatsink: float = 88.0,
        status_code: str = "0x05",
    ) -> pd.DataFrame:
        """Inject a hardware fault into a specific panel row for live testing."""
        df = pd.read_csv(self.local_csv_path)
        mask = df["panel_id"] == panel_id
        if not mask.any():
            target_idx = df.index[-1]
        else:
            target_idx = df[mask].index[-1]

        df.loc[target_idx, "v_dc_string_2"] = float(v_dc_string_2)
        df.loc[target_idx, "temp_heatsink"] = float(temp_heatsink)
        df.loc[target_idx, "status_code"] = str(status_code)
        df.loc[target_idx, "p_ac_output"] = 2850.0
        return self.save_telemetry(df)

    def restore_nominal_values(self) -> pd.DataFrame:
        """Restore all faulted rows back to healthy nominal values."""
        df = pd.read_csv(self.local_csv_path)
        for idx, row in df.iterrows():
            v1 = float(row.get("v_dc_string_1", 392.0))
            v2 = float(row.get("v_dc_string_2", 390.5))
            temp = float(row.get("temp_heatsink", 46.5))
            code = str(row.get("status_code", "0x00")).strip().lower()

            if abs(v1 - v2) > 20.0 or temp > 70.0 or code != "0x00":
                df.loc[idx, "v_dc_string_1"] = 392.0
                df.loc[idx, "v_dc_string_2"] = 390.5
                if "v_dc_string_3" in df.columns:
                    df.loc[idx, "v_dc_string_3"] = 391.0
                if "v_dc_string_4" in df.columns:
                    df.loc[idx, "v_dc_string_4"] = 391.5
                df.loc[idx, "temp_heatsink"] = 46.5
                df.loc[idx, "p_ac_output"] = 4980.0
                df.loc[idx, "status_code"] = "0x00"

        return self.save_telemetry(df)
