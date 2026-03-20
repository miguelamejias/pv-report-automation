# -*- coding: utf-8 -*-
"""
AnomalyEngine — Rule-Based Detection for PV System Anomalies
=============================================================

Implements the **Strategy Pattern** so that new anomaly rules can be added
without modifying the core engine.  Each rule is a callable that receives
a DataFrame and returns a list of Alert objects.

Built-in Strategies:
  1. SoilingDetector — Detects progressive soiling via PR degradation.
  2. ClippingDetector — Identifies inverter power clipping events.
  3. IsolationFaultDetector — Flags DC string voltage mismatches.

Design Pattern:
  - Strategy (GoF): Each detector is interchangeable.
  - Open/Closed Principle: New detectors can be registered without
    modifying AnomalyEngine source code.

Author: Miguel Ángel Mejía Sánchez
Updated with AI: Extracted from inline if-else blocks into a clean
                 Strategy pattern with typed dataclasses.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class Severity(Enum):
    """Alert severity levels — maps to notification channel routing."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Represents a single anomaly detection result.

    Attributes
    ----------
    rule_name : str
        Name of the detection rule that triggered this alert.
    severity : Severity
        Alert severity (INFO, WARNING, CRITICAL).
    message : str
        Human-readable description of the anomaly.
    timestamp_start : datetime
        When the anomaly condition began.
    timestamp_end : datetime | None
        When the anomaly condition ended (None if ongoing).
    details : dict
        Additional context (e.g., measured values, thresholds).
    """
    rule_name: str
    severity: Severity
    message: str
    timestamp_start: datetime
    timestamp_end: datetime | None = None
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------

@runtime_checkable
class AnomalyDetector(Protocol):
    """Protocol (interface) that all anomaly detection strategies must follow.

    Any callable class with a `detect(df) -> list[Alert]` method can be
    registered with the AnomalyEngine.
    """

    def detect(self, df: pd.DataFrame) -> list[Alert]:
        """Analyze the DataFrame and return a list of detected anomalies."""
        ...


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class SoilingDetector:
    """Detects progressive panel soiling via Performance Ratio degradation.

    Business Rule:
      If the daily average PR drops by more than `daily_drop_threshold`%
      for `consecutive_days` days in a row, it is likely that panels need
      cleaning.  This saves unnecessary truck rolls by confirming the
      trend before dispatching a crew.

    Parameters
    ----------
    daily_drop_threshold : float
        Minimum daily PR drop (in percentage points) to flag (default: 1.0).
    consecutive_days : int
        Number of consecutive days of decline required (default: 5).
    """

    def __init__(
        self,
        daily_drop_threshold: float = 1.0,
        consecutive_days: int = 5,
    ) -> None:
        self.daily_drop_threshold = daily_drop_threshold
        self.consecutive_days = consecutive_days

    def detect(self, df: pd.DataFrame) -> list[Alert]:
        alerts: list[Alert] = []
        daylight = df[df["is_daylight"]].copy()

        if daylight.empty:
            return alerts

        # Compute daily average PR
        daylight["date"] = daylight["timestamp"].dt.date
        daily_pr = daylight.groupby("date")["performance_ratio"].mean()

        if len(daily_pr) < self.consecutive_days:
            return alerts

        # Calculate day-over-day PR change
        pr_diff = daily_pr.diff()

        # Find consecutive declining days
        streak = 0
        streak_start = None
        for date, change in pr_diff.items():
            if change is not None and change < -self.daily_drop_threshold:
                if streak == 0:
                    streak_start = date
                streak += 1
                if streak >= self.consecutive_days:
                    alerts.append(Alert(
                        rule_name="Soiling Detection",
                        severity=Severity.WARNING,
                        message=(
                            f"Performance Ratio has declined for {streak} consecutive "
                            f"days (avg drop: {pr_diff.iloc[-streak:].mean():.2f}%/day). "
                            f"Panel cleaning is recommended."
                        ),
                        timestamp_start=datetime.combine(
                            streak_start, datetime.min.time()
                        ),
                        timestamp_end=datetime.combine(date, datetime.min.time()),
                        details={
                            "streak_days": streak,
                            "avg_daily_drop_pct": round(
                                float(pr_diff.iloc[-streak:].mean()), 2
                            ),
                            "pr_start": round(float(daily_pr.iloc[-streak - 1]), 2),
                            "pr_end": round(float(daily_pr.iloc[-1]), 2),
                        },
                    ))
                    logger.warning("Soiling detected: %d-day PR decline.", streak)
                    break
            else:
                streak = 0
                streak_start = None

        return alerts


class ClippingDetector:
    """Detects inverter power clipping events.

    Business Rule:
      When AC power remains flat (within `flat_tolerance_pct`% of the
      maximum observed output) while irradiance continues to rise,
      the inverter is operating at its thermal or design limit.

    This helps operations decide whether the inverter needs to be
    upsized or if the thermal management system is underperforming.

    Parameters
    ----------
    flat_tolerance_pct : float
        Maximum % deviation from peak AC power to consider "flat" (default: 2.0).
    min_irradiance_rise : float
        Minimum irradiance increase (W/m²) over the clipping window (default: 100).
    min_clipping_minutes : int
        Minimum duration of clipping window in minutes (default: 30).
    """

    def __init__(
        self,
        flat_tolerance_pct: float = 2.0,
        min_irradiance_rise: float = 100,
        min_clipping_minutes: int = 30,
    ) -> None:
        self.flat_tolerance_pct = flat_tolerance_pct
        self.min_irradiance_rise = min_irradiance_rise
        self.min_clipping_minutes = min_clipping_minutes

    def detect(self, df: pd.DataFrame) -> list[Alert]:
        alerts: list[Alert] = []
        daylight = df[df["is_daylight"]].copy()

        if daylight.empty:
            return alerts

        peak_power = daylight["p_ac_output"].max()
        if peak_power <= 0:
            return alerts

        # Define "flat" band around peak power
        lower_bound = peak_power * (1 - self.flat_tolerance_pct / 100)

        # Find rows where power is in the flat band
        clipping_mask = daylight["p_ac_output"] >= lower_bound
        clipping_rows = daylight[clipping_mask]

        if len(clipping_rows) < 2:
            return alerts

        # Check if irradiance is rising during clipping
        irr_start = clipping_rows["irradiance_poa"].iloc[0]
        irr_end = clipping_rows["irradiance_poa"].iloc[-1]
        irr_rise = irr_end - irr_start

        # Check duration
        time_start = clipping_rows["timestamp"].iloc[0]
        time_end = clipping_rows["timestamp"].iloc[-1]
        duration_minutes = (time_end - time_start).total_seconds() / 60

        if (
            irr_rise >= self.min_irradiance_rise
            and duration_minutes >= self.min_clipping_minutes
        ):
            alerts.append(Alert(
                rule_name="Inverter Clipping",
                severity=Severity.INFO,
                message=(
                    f"Inverter clipping detected for {duration_minutes:.0f} minutes. "
                    f"AC power capped at ~{peak_power:.0f}W while irradiance rose "
                    f"by {irr_rise:.0f} W/m². Consider inverter capacity review."
                ),
                timestamp_start=time_start.to_pydatetime(),
                timestamp_end=time_end.to_pydatetime(),
                details={
                    "peak_power_w": round(float(peak_power), 1),
                    "irradiance_rise_wm2": round(float(irr_rise), 1),
                    "duration_minutes": round(duration_minutes, 1),
                },
            ))
            logger.info("Clipping detected: %.0f min at %.0fW.", duration_minutes, peak_power)

        return alerts


class IsolationFaultDetector:
    """Detects DC string voltage mismatches indicating wiring issues.

    Business Rule:
      If the percentage difference between String 1 and String 2 voltages
      exceeds `delta_threshold_pct`% for more than `min_duration_minutes`,
      a wiring review is needed.  This catches partial shading,
      disconnected connectors, and degraded bypass diodes.

    Parameters
    ----------
    delta_threshold_pct : float
        Minimum ΔV (%) between strings to flag (default: 15.0).
    min_duration_minutes : int
        Minimum anomaly duration in minutes (default: 15).
    """

    def __init__(
        self,
        delta_threshold_pct: float = 15.0,
        min_duration_minutes: int = 15,
    ) -> None:
        self.delta_threshold_pct = delta_threshold_pct
        self.min_duration_minutes = min_duration_minutes

    def detect(self, df: pd.DataFrame) -> list[Alert]:
        alerts: list[Alert] = []
        daylight = df[df["is_daylight"]].copy()

        if daylight.empty:
            return alerts

        # Find rows where ΔV exceeds threshold
        fault_mask = daylight["delta_v_dc_pct"] > self.delta_threshold_pct
        fault_rows = daylight[fault_mask]

        if fault_rows.empty:
            return alerts

        # Group consecutive fault readings into windows
        fault_rows = fault_rows.copy()
        fault_rows["time_diff"] = fault_rows["timestamp"].diff()

        # Split into separate fault windows (gap > 30 min = new window)
        windows: list[pd.DataFrame] = []
        current_window: list[int] = []

        for idx, row in fault_rows.iterrows():
            if (
                current_window
                and row["time_diff"].total_seconds() > 1800  # 30-minute gap
            ):
                windows.append(fault_rows.loc[current_window])
                current_window = []
            current_window.append(idx)

        if current_window:
            windows.append(fault_rows.loc[current_window])

        for window in windows:
            duration = (
                window["timestamp"].iloc[-1] - window["timestamp"].iloc[0]
            ).total_seconds() / 60

            if duration >= self.min_duration_minutes:
                avg_delta = window["delta_v_dc_pct"].mean()
                alerts.append(Alert(
                    rule_name="Isolation Fault",
                    severity=Severity.CRITICAL,
                    message=(
                        f"String voltage mismatch detected: avg ΔV = {avg_delta:.1f}% "
                        f"(threshold: {self.delta_threshold_pct}%) for "
                        f"{duration:.0f} minutes. Immediate wiring inspection required."
                    ),
                    timestamp_start=window["timestamp"].iloc[0].to_pydatetime(),
                    timestamp_end=window["timestamp"].iloc[-1].to_pydatetime(),
                    details={
                        "avg_delta_v_pct": round(float(avg_delta), 2),
                        "max_delta_v_pct": round(float(window["delta_v_dc_pct"].max()), 2),
                        "duration_minutes": round(duration, 1),
                        "threshold_pct": self.delta_threshold_pct,
                    },
                ))
                logger.critical(
                    "Isolation fault: ΔV=%.1f%% for %.0f min.", avg_delta, duration
                )

        return alerts


# ---------------------------------------------------------------------------
# Core engine (orchestrates strategies)
# ---------------------------------------------------------------------------

class AnomalyEngine:
    """Central engine that runs all registered anomaly detection strategies.

    Design:
      Uses the Strategy pattern (GoF) to decouple detection logic from
      orchestration.  New rules can be registered at runtime without
      modifying this class (Open/Closed Principle).

    Usage:
        >>> engine = AnomalyEngine()
        >>> engine.register(SoilingDetector())
        >>> engine.register(ClippingDetector())
        >>> engine.register(IsolationFaultDetector())
        >>> alerts = engine.analyze(df)
    """

    def __init__(self) -> None:
        self._detectors: list[AnomalyDetector] = []

    def register(self, detector: AnomalyDetector) -> "AnomalyEngine":
        """Register a new detection strategy.

        Parameters
        ----------
        detector : AnomalyDetector
            Any object implementing the detect(df) -> list[Alert] interface.

        Returns
        -------
        AnomalyEngine
            Self, for method chaining.
        """
        if not isinstance(detector, AnomalyDetector):
            raise TypeError(
                f"{type(detector).__name__} does not implement AnomalyDetector protocol."
            )
        self._detectors.append(detector)
        logger.info("Registered detector: %s", type(detector).__name__)
        return self

    def analyze(self, df: pd.DataFrame) -> list[Alert]:
        """Run all registered detectors against the processed DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Cleaned and enriched DataFrame from SolarDataTransformer.

        Returns
        -------
        list[Alert]
            Aggregated list of all detected anomalies, sorted by severity.
        """
        all_alerts: list[Alert] = []
        for detector in self._detectors:
            name = type(detector).__name__
            logger.info("Running detector: %s", name)
            try:
                alerts = detector.detect(df)
                all_alerts.extend(alerts)
                logger.info("%s found %d alert(s).", name, len(alerts))
            except Exception as exc:
                logger.error("Detector %s failed: %s", name, exc, exc_info=True)

        # Sort by severity: CRITICAL > WARNING > INFO
        severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
        all_alerts.sort(key=lambda a: severity_order.get(a.severity, 99))

        logger.info("Total alerts detected: %d", len(all_alerts))
        return all_alerts

    @property
    def detector_count(self) -> int:
        """Number of currently registered detectors."""
        return len(self._detectors)

    @classmethod
    def create_default(cls) -> "AnomalyEngine":
        """Factory method: creates an engine with all built-in detectors.

        Returns
        -------
        AnomalyEngine
            Pre-configured engine with Soiling, Clipping, and Isolation
            fault detectors using default thresholds.
        """
        engine = cls()
        engine.register(SoilingDetector())
        engine.register(ClippingDetector())
        engine.register(IsolationFaultDetector())
        return engine
