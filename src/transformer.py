# -*- coding: utf-8 -*-
"""
SolarDataTransformer — ETL Pipeline for Photovoltaic System Logs
================================================================

Responsible for the full Extract-Transform-Load cycle:
  1. Extract: Read raw CSV logs from inverter data loggers.
  2. Transform: Clean nulls, normalize units, parse hex status codes,
     and compute derived metrics (efficiency, Performance Ratio).
  3. Load: Return a validated Pandas DataFrame ready for analysis.

Design Decisions:
  - Uses method chaining for a fluent pipeline API.
  - Separates validation from transformation (Single Responsibility).
  - All thresholds are configurable via class constructor to allow
    per-plant customization without code changes.

Author: Miguel Ángel Mejía Sánchez
Updated with AI: Refactored from a monolithic script into a reusable
                 ETL class following SOLID principles.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hardware status code mapping — reflects real inverter register values
# ---------------------------------------------------------------------------
STATUS_CODE_MAP = {
    "0x00": "OK",
    "0x01": "Grid Error",
    "0x02": "Overcurrent",
    "0x03": "Overvoltage DC",
    "0x04": "Overtemperature",
    "0x05": "Isolation Fault",
    "0x06": "Ground Fault",
    "0x07": "Fan Failure",
    "0xFF": "Communication Lost",
}


class SolarDataTransformer:
    """ETL pipeline that cleans and enriches raw photovoltaic log data.

    Parameters
    ----------
    nominal_power_kw : float
        Nameplate capacity of the plant in kW (used for PR calculation).
    timezone : str
        IANA timezone string for timestamp localization (default: America/Bogota).
    max_temp_threshold : float
        Maximum acceptable heatsink temperature in °C (default: 85.0).
    min_irradiance : float
        Minimum irradiance in W/m² to consider the plant "active" (default: 50.0).
    """

    def __init__(
        self,
        nominal_power_kw: float = 10.0,
        timezone: str = "America/Bogota",
        max_temp_threshold: float = 85.0,
        min_irradiance: float = 50.0,
    ) -> None:
        self.nominal_power_kw = nominal_power_kw
        self.nominal_power_w = nominal_power_kw * 1000
        self.timezone = timezone
        self.max_temp_threshold = max_temp_threshold
        self.min_irradiance = min_irradiance
        self._raw_row_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_csv(self, filepath: str | Path) -> pd.DataFrame:
        """Load a CSV file and run the full transformation pipeline.

        Parameters
        ----------
        filepath : str or Path
            Path to the raw CSV log file.

        Returns
        -------
        pd.DataFrame
            Cleaned, enriched DataFrame ready for anomaly analysis.

        Raises
        ------
        FileNotFoundError
            If the CSV file does not exist.
        ValueError
            If required columns are missing from the file.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Log file not found: {filepath}")

        logger.info("Loading raw data from %s", filepath)
        df = pd.read_csv(filepath)
        self._raw_row_count = len(df)

        # --- Full pipeline via method chaining ---
        df = (
            self._validate_columns(df)
            .pipe(self._parse_timestamps)
            .pipe(self._clean_numeric_columns)
            .pipe(self._decode_status_codes)
            .pipe(self._compute_derived_metrics)
        )

        logger.info(
            "Pipeline complete: %d raw → %d clean rows (%.1f%% retained)",
            self._raw_row_count,
            len(df),
            (len(df) / self._raw_row_count * 100) if self._raw_row_count else 0,
        )
        return df

    # ------------------------------------------------------------------
    # Pipeline steps (private)
    # ------------------------------------------------------------------

    def _validate_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure all required columns are present in the raw data.

        Required: timestamp, v_dc_string_1, v_dc_string_2, i_dc_total,
                  p_ac_output, temp_heatsink, irradiance_poa, status_code.
        Optional: v_dc_string_3, v_dc_string_4 (multi-string plants).
        """
        required = {
            "timestamp",
            "v_dc_string_1",
            "v_dc_string_2",
            "i_dc_total",
            "p_ac_output",
            "temp_heatsink",
            "irradiance_poa",
            "status_code",
        }
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        logger.debug("Column validation passed.")
        return df

    def _parse_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert timestamp strings to timezone-aware datetime objects."""
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["timestamp"] = df["timestamp"].dt.tz_convert(self.timezone)
        df = df.sort_values("timestamp").reset_index(drop=True)
        logger.debug("Timestamps parsed and sorted.")
        return df

    def _clean_numeric_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Handle missing values and clip physically impossible readings.

        Strategy:
          - Negative irradiance or power → set to 0 (sensor noise at night).
          - NaN in voltage/current → forward-fill, then drop remaining.
          - Temperature > max_temp_threshold is preserved (it's an anomaly,
            not bad data).
        """
        df = df.copy()
        numeric_cols = [
            "v_dc_string_1",
            "v_dc_string_2",
            "i_dc_total",
            "p_ac_output",
            "temp_heatsink",
            "irradiance_poa",
        ]
        # Include optional multi-string columns if present
        for optional_col in ["v_dc_string_3", "v_dc_string_4"]:
            if optional_col in df.columns:
                numeric_cols.append(optional_col)
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Physical constraints: negative power/irradiance is sensor noise
        df["p_ac_output"] = df["p_ac_output"].clip(lower=0)
        df["irradiance_poa"] = df["irradiance_poa"].clip(lower=0)

        # Forward-fill small gaps (up to 2 consecutive NaNs)
        df[numeric_cols] = df[numeric_cols].ffill(limit=2)

        rows_before = len(df)
        df = df.dropna(subset=numeric_cols)
        dropped = rows_before - len(df)
        if dropped:
            logger.warning("Dropped %d rows with unrecoverable NaN values.", dropped)

        return df

    def _decode_status_codes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map hex status codes to human-readable descriptions."""
        df = df.copy()
        df["status_code"] = df["status_code"].astype(str).str.strip().str.lower()
        df["status_description"] = df["status_code"].map(STATUS_CODE_MAP)
        df["status_description"] = df["status_description"].fillna("Unknown Code")
        return df

    def _compute_derived_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate key performance indicators used by the anomaly engine.

        Derived columns:
          - delta_v_dc_pct: Percentage difference between string voltages.
          - efficiency: Ratio of AC output to theoretical DC power.
          - performance_ratio: Industry-standard PR metric.
          - is_daylight: Boolean flag for active generation hours.
        """
        df = df.copy()

        # ΔV between strings — key indicator for isolation faults
        # Use all available string voltages for a robust average
        string_cols = [c for c in ["v_dc_string_1", "v_dc_string_2",
                                    "v_dc_string_3", "v_dc_string_4"]
                       if c in df.columns]
        v_avg = df[string_cols].mean(axis=1)
        df["delta_v_dc_pct"] = (
            (df["v_dc_string_1"] - df["v_dc_string_2"]).abs()
            / v_avg.replace(0, np.nan)
            * 100
        )
        df["delta_v_dc_pct"] = df["delta_v_dc_pct"].fillna(0)

        # Theoretical DC power (P = V_avg × I)
        df["p_dc_theoretical"] = v_avg * df["i_dc_total"]

        # Inverter efficiency (AC / DC)
        df["efficiency"] = np.where(
            df["p_dc_theoretical"] > 0,
            (df["p_ac_output"] / df["p_dc_theoretical"]) * 100,
            0,
        )

        # Performance Ratio: PR = P_ac / (P_nominal × G / G_stc)
        # where G_stc = 1000 W/m²  (Standard Test Conditions)
        g_ratio = df["irradiance_poa"] / 1000
        theoretical_output = self.nominal_power_w * g_ratio
        df["performance_ratio"] = np.where(
            theoretical_output > 0,
            (df["p_ac_output"] / theoretical_output) * 100,
            0,
        )

        # Daylight flag — only consider readings with meaningful irradiance
        df["is_daylight"] = df["irradiance_poa"] >= self.min_irradiance

        logger.debug("Derived metrics computed: delta_v, efficiency, PR, daylight.")
        return df
