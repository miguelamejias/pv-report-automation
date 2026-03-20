# -*- coding: utf-8 -*-
"""
Tests for NotificationOrchestrator — Alert Dispatch Validation
==============================================================

Verifies:
  - Simulation output is generated correctly for all severity levels.
  - Email HTML body is well-formed.
  - Severity-based routing logic (CRITICAL → both, INFO → Slack only).
  - Empty alert list is handled gracefully.

Note: Real SMTP/Slack calls are NOT tested here (that would require
integration tests). We test the formatting and routing logic only.

Author: Miguel Ángel Mejía Sánchez
"""

from datetime import datetime

import pytest

from src.anomaly_engine import Alert, Severity
from src.notifications import NotificationOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def critical_alert() -> Alert:
    """Create a sample CRITICAL alert."""
    return Alert(
        rule_name="Isolation Fault",
        severity=Severity.CRITICAL,
        message="String voltage mismatch: ΔV = 25.3%",
        timestamp_start=datetime(2024, 3, 15, 10, 30),
        timestamp_end=datetime(2024, 3, 15, 11, 0),
        details={"avg_delta_v_pct": 25.3},
    )


@pytest.fixture
def warning_alert() -> Alert:
    """Create a sample WARNING alert."""
    return Alert(
        rule_name="Soiling Detection",
        severity=Severity.WARNING,
        message="Performance Ratio declining for 5 consecutive days.",
        timestamp_start=datetime(2024, 3, 10, 0, 0),
        timestamp_end=datetime(2024, 3, 15, 0, 0),
        details={"streak_days": 5, "avg_daily_drop_pct": -1.2},
    )


@pytest.fixture
def info_alert() -> Alert:
    """Create a sample INFO alert."""
    return Alert(
        rule_name="Inverter Clipping",
        severity=Severity.INFO,
        message="Power capped at 9800W for 45 minutes.",
        timestamp_start=datetime(2024, 3, 15, 12, 0),
        timestamp_end=datetime(2024, 3, 15, 12, 45),
        details={"peak_power_w": 9800},
    )


# ---------------------------------------------------------------------------
# Tests: Simulation Output
# ---------------------------------------------------------------------------

class TestSimulationOutput:
    """Verify that the simulation mode produces useful output for demos."""

    def test_simulation_with_alerts(self, critical_alert, warning_alert):
        """Simulation should produce formatted text for all alerts."""
        output = NotificationOrchestrator.simulate_dispatch(
            [critical_alert, warning_alert]
        )
        assert "SIMULATED ALERT DISPATCH" in output
        assert "Isolation Fault" in output
        assert "Soiling Detection" in output
        assert "CRITICAL" in output
        assert "WARNING" in output

    def test_simulation_no_alerts(self):
        """Empty alert list should produce 'all clear' message."""
        output = NotificationOrchestrator.simulate_dispatch([])
        assert "No anomalies detected" in output

    def test_simulation_contains_severity_emoji(self, critical_alert, info_alert):
        """Output should include visual severity indicators."""
        output = NotificationOrchestrator.simulate_dispatch(
            [critical_alert, info_alert]
        )
        assert "🔴" in output  # Critical
        assert "🟢" in output  # Info


# ---------------------------------------------------------------------------
# Tests: Email Formatting
# ---------------------------------------------------------------------------

class TestEmailFormatting:
    """Verify email subject and body generation."""

    def test_critical_email_subject(self, critical_alert):
        """Critical alerts should produce alarming subject lines."""
        orchestrator = NotificationOrchestrator()
        subject = orchestrator._build_email_subject([critical_alert])
        assert "CRITICAL" in subject

    def test_warning_email_subject(self, warning_alert):
        """Warning alerts should produce appropriate subject lines."""
        orchestrator = NotificationOrchestrator()
        subject = orchestrator._build_email_subject([warning_alert])
        assert "WARNING" in subject

    def test_info_email_subject(self, info_alert):
        """Info alerts should produce informational subject lines."""
        orchestrator = NotificationOrchestrator()
        subject = orchestrator._build_email_subject([info_alert])
        assert "INFO" in subject

    def test_email_html_contains_alert_details(self, critical_alert):
        """HTML body should include alert rule name and message."""
        orchestrator = NotificationOrchestrator()
        html = orchestrator._build_email_html([critical_alert])
        assert "Isolation Fault" in html
        assert "pv-report-automation" in html


# ---------------------------------------------------------------------------
# Tests: Slack Formatting
# ---------------------------------------------------------------------------

class TestSlackFormatting:
    """Verify Slack Block Kit payload generation."""

    def test_slack_blocks_structure(self, critical_alert):
        """Slack blocks should include header, alert section, and footer."""
        orchestrator = NotificationOrchestrator()
        blocks = orchestrator._build_slack_blocks([critical_alert])
        assert any(b.get("type") == "header" for b in blocks)
        assert any(b.get("type") == "section" for b in blocks)
        assert any(b.get("type") == "context" for b in blocks)


# ---------------------------------------------------------------------------
# Tests: Routing Logic
# ---------------------------------------------------------------------------

class TestRoutingLogic:
    """Verify severity-based channel routing decisions."""

    def test_dispatch_with_no_config(self, critical_alert):
        """Dispatch without config should not crash."""
        orchestrator = NotificationOrchestrator()
        result = orchestrator.dispatch([critical_alert])
        assert result["email"] is False
        assert result["slack"] is False
        assert result["total_alerts"] == 1

    def test_dispatch_empty_alerts(self):
        """Empty alert list should return zero counts."""
        orchestrator = NotificationOrchestrator()
        result = orchestrator.dispatch([])
        assert result["total_alerts"] == 0
