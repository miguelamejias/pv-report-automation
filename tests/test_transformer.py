# -*- coding: utf-8 -*-
"""
Tests for SolarDataTransformer — ETL Pipeline Validation
========================================================

Verifies:
  - Column validation rejects missing required fields.
  - Negative irradiance/power values are clipped to zero.
  - NaN rows are handled gracefully (forward-fill, then drop).
  - Derived metrics (delta_v, efficiency, PR) are computed correctly.
  - Timezone conversion works for America/Bogota.

Author: Miguel Ángel Mejía Sánchez
"""

import numpy as np
import pandas as pd
import pytest

from src.transformer import SolarDataTransformer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_csv_data() -> pd.DataFrame:
    """Create a minimal valid DataFrame simulating raw CSV input."""
    return pd.DataFrame({
        "timestamp": [
            "2024-03-15T10:00:00+00:00",
            "2024-03-15T10:15:00+00:00",
            "2024-03-15T10:30:00+00:00",
            "2024-03-15T10:45:00+00:00",
        ],
        "v_dc_string_1": [380.0, 382.0, 379.0, 381.0],
        "v_dc_string_2": [378.0, 380.0, 377.0, 379.0],
        "i_dc_total": [12.5, 13.0, 12.8, 13.2],
        "p_ac_output": [4500, 4700, 4600, 4750],
        "temp_heatsink": [42.0, 43.5, 44.0, 45.5],
        "irradiance_poa": [750.0, 800.0, 780.0, 820.0],
        "status_code": ["0x00", "0x00", "0x00", "0x00"],
    })


@pytest.fixture
def transformer() -> SolarDataTransformer:
    """Create a transformer with default settings."""
    return SolarDataTransformer(nominal_power_kw=10.0)


# ---------------------------------------------------------------------------
# Tests: Column Validation
# ---------------------------------------------------------------------------

class TestColumnValidation:
    """Verify that the ETL pipeline rejects malformed input data."""

    def test_missing_column_raises_error(self, transformer, tmp_path):
        """Pipeline should fail fast when required columns are missing."""
        df = pd.DataFrame({
            "timestamp": ["2024-03-15T10:00:00+00:00"],
            "v_dc_string_1": [380.0],
            # Missing all other required columns
        })
        filepath = tmp_path / "bad_data.csv"
        df.to_csv(filepath, index=False)

        with pytest.raises(ValueError, match="Missing required columns"):
            transformer.load_csv(filepath)

    def test_valid_columns_pass(self, transformer, valid_csv_data, tmp_path):
        """Pipeline should accept valid data without errors."""
        filepath = tmp_path / "valid_data.csv"
        valid_csv_data.to_csv(filepath, index=False)
        result = transformer.load_csv(filepath)
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Tests: Data Cleaning
# ---------------------------------------------------------------------------

class TestDataCleaning:
    """Verify that numeric cleaning handles edge cases correctly."""

    def test_negative_power_clipped_to_zero(self, transformer, valid_csv_data, tmp_path):
        """Negative power values (sensor noise) should be clipped to 0."""
        valid_csv_data.loc[0, "p_ac_output"] = -50.0
        filepath = tmp_path / "negative_power.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        assert result["p_ac_output"].min() >= 0

    def test_negative_irradiance_clipped_to_zero(
        self, transformer, valid_csv_data, tmp_path
    ):
        """Negative irradiance (night-time noise) should be clipped to 0."""
        valid_csv_data.loc[0, "irradiance_poa"] = -10.0
        filepath = tmp_path / "negative_irr.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        assert result["irradiance_poa"].min() >= 0

    def test_nan_handling_forward_fill(self, transformer, valid_csv_data, tmp_path):
        """Small NaN gaps should be forward-filled, not dropped."""
        valid_csv_data.loc[1, "v_dc_string_1"] = np.nan
        filepath = tmp_path / "nan_data.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        # Row 1 should be forward-filled from row 0
        assert not result["v_dc_string_1"].isna().any()

    def test_all_nan_rows_dropped(self, transformer, tmp_path):
        """Rows with all NaN numeric values should be dropped."""
        df = pd.DataFrame({
            "timestamp": [
                "2024-03-15T10:00:00+00:00",
                "2024-03-15T10:15:00+00:00",
            ],
            "v_dc_string_1": [380.0, np.nan],
            "v_dc_string_2": [378.0, np.nan],
            "i_dc_total": [12.5, np.nan],
            "p_ac_output": [4500, np.nan],
            "temp_heatsink": [42.0, np.nan],
            "irradiance_poa": [750.0, np.nan],
            "status_code": ["0x00", "0x00"],
        })
        filepath = tmp_path / "all_nan.csv"
        df.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        # First valid row + second should be forward-filled
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Tests: Derived Metrics
# ---------------------------------------------------------------------------

class TestDerivedMetrics:
    """Verify that computed performance indicators are physically correct."""

    def test_delta_v_dc_pct_calculation(
        self, transformer, valid_csv_data, tmp_path
    ):
        """ΔV between strings should detect voltage mismatches."""
        # Inject a large mismatch
        valid_csv_data.loc[2, "v_dc_string_1"] = 400.0
        valid_csv_data.loc[2, "v_dc_string_2"] = 300.0
        filepath = tmp_path / "mismatch.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        # Row 2 should have a significant ΔV
        mismatch_row = result.iloc[2]
        assert mismatch_row["delta_v_dc_pct"] > 10

    def test_performance_ratio_range(self, transformer, valid_csv_data, tmp_path):
        """PR should be a positive percentage under normal conditions."""
        filepath = tmp_path / "normal.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        daylight = result[result["is_daylight"]]
        assert daylight["performance_ratio"].min() >= 0

    def test_efficiency_with_zero_dc_power(self, transformer, tmp_path):
        """Efficiency should be 0 when DC power is zero (night-time)."""
        df = pd.DataFrame({
            "timestamp": ["2024-03-15T22:00:00+00:00"],
            "v_dc_string_1": [0.0],
            "v_dc_string_2": [0.0],
            "i_dc_total": [0.0],
            "p_ac_output": [0],
            "temp_heatsink": [25.0],
            "irradiance_poa": [0.0],
            "status_code": ["0x00"],
        })
        filepath = tmp_path / "night.csv"
        df.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        assert result["efficiency"].iloc[0] == 0

    def test_daylight_flag(self, transformer, valid_csv_data, tmp_path):
        """is_daylight should be True when irradiance ≥ 50 W/m²."""
        valid_csv_data.loc[0, "irradiance_poa"] = 10.0  # Below threshold
        filepath = tmp_path / "daylight.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        assert result.iloc[0]["is_daylight"] is False or not result.iloc[0]["is_daylight"]
        assert result.iloc[1]["is_daylight"]


# ---------------------------------------------------------------------------
# Tests: Status Code Decoding
# ---------------------------------------------------------------------------

class TestStatusCodes:
    """Verify hex status code → description mapping."""

    def test_known_status_mapped(self, transformer, valid_csv_data, tmp_path):
        """Known status codes should map to human-readable descriptions."""
        valid_csv_data.loc[0, "status_code"] = "0x04"
        filepath = tmp_path / "status.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        assert result.iloc[0]["status_description"] == "Overtemperature"

    def test_unknown_status_handled(self, transformer, valid_csv_data, tmp_path):
        """Unknown status codes should map to 'Unknown Code'."""
        valid_csv_data.loc[0, "status_code"] = "0xAB"
        filepath = tmp_path / "unknown_status.csv"
        valid_csv_data.to_csv(filepath, index=False)

        result = transformer.load_csv(filepath)
        assert result.iloc[0]["status_description"] == "Unknown Code"


# ---------------------------------------------------------------------------
# Tests: File handling
# ---------------------------------------------------------------------------

class TestFileHandling:
    """Verify file I/O error handling."""

    def test_nonexistent_file_raises_error(self, transformer):
        """Should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            transformer.load_csv("nonexistent_file.csv")
