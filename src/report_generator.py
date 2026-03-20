# -*- coding: utf-8 -*-
"""
ReportGenerator — Executive PDF & Interactive HTML Report Builder
=================================================================

Generates two types of reports from processed PV plant data:
  1. **Interactive HTML** (Plotly): Browser-viewable charts with hover
     tooltips, zoom, and pan. Perfect for daily operations review.
  2. **Executive PDF** (FPDF2): Formal document with summary statistics,
     alert tables, and performance charts. Suitable for management and
     client-facing communication.

Key Metrics Reported:
  - Total energy generated (kWh)
  - CO₂ emissions avoided (tons)
  - Performance Ratio trend
  - Active alerts and their timeline

Author: Miguel Ángel Mejía Sánchez
Updated with AI: Rebuilt from print-statement outputs to professional
                 multi-format report generation.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Unicode → ASCII replacements for PDF (Helvetica doesn't support full Unicode)
_PDF_CHAR_MAP = {
    "\u0394": "Delta ",  # Δ
    "\u00b2": "2",       # ²
    "\u00b0": " ",       # °
    "\u2265": ">=",      # ≥
    "\u2264": "<=",      # ≤
    "\u00d7": "x",       # ×
    "\u2248": "~",       # ≈
}


try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    from fpdf import FPDF

    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

from src.anomaly_engine import Alert, Severity

logger = logging.getLogger(__name__)

# CO₂ emission factor: kg CO₂ avoided per kWh of solar generation
# Source: Colombian grid average ~0.126 kg CO₂/kWh (UPME, 2023)
CO2_FACTOR_KG_PER_KWH = 0.126


class ReportGenerator:
    """Generates executive reports in PDF and interactive HTML formats.

    Parameters
    ----------
    plant_name : str
        Name of the solar plant (used in report headers).
    nominal_power_kw : float
        Nameplate capacity in kW.
    output_dir : str or Path
        Directory where reports will be saved (default: "output").
    """

    def __init__(
        self,
        plant_name: str = "ENERTEC Solar Plant",
        nominal_power_kw: float = 10.0,
        output_dir: str | Path = "output",
    ) -> None:
        self.plant_name = plant_name
        self.nominal_power_kw = nominal_power_kw
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize_for_pdf(text: str) -> str:
        """Replace Unicode characters unsupported by Helvetica with ASCII."""
        for char, replacement in _PDF_CHAR_MAP.items():
            text = text.replace(char, replacement)
        # Fallback: replace any remaining non-latin1 chars
        return text.encode("latin-1", errors="replace").decode("latin-1")

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------

    def compute_summary(self, df: pd.DataFrame) -> dict:
        """Compute key performance metrics for the reporting period.

        Parameters
        ----------
        df : pd.DataFrame
            Processed DataFrame from SolarDataTransformer.

        Returns
        -------
        dict
            Summary statistics including energy, CO₂, PR, and period info.
        """
        daylight = df[df["is_daylight"]]

        # Energy calculation: integrate power over time (trapezoidal rule)
        if len(daylight) >= 2:
            # Time intervals in hours
            time_hours = (
                daylight["timestamp"].diff().dt.total_seconds().fillna(0) / 3600
            )
            energy_wh = (daylight["p_ac_output"] * time_hours).sum()
            energy_kwh = energy_wh / 1000
        else:
            energy_kwh = 0.0

        co2_avoided_kg = energy_kwh * CO2_FACTOR_KG_PER_KWH

        avg_pr = daylight["performance_ratio"].mean() if not daylight.empty else 0
        avg_efficiency = daylight["efficiency"].mean() if not daylight.empty else 0
        max_temp = df["temp_heatsink"].max() if not df.empty else 0
        peak_power_w = df["p_ac_output"].max() if not df.empty else 0

        return {
            "plant_name": self.plant_name,
            "period_start": df["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M")
            if not df.empty
            else "N/A",
            "period_end": df["timestamp"].iloc[-1].strftime("%Y-%m-%d %H:%M")
            if not df.empty
            else "N/A",
            "total_records": len(df),
            "daylight_records": len(daylight),
            "energy_kwh": round(energy_kwh, 2),
            "co2_avoided_kg": round(co2_avoided_kg, 2),
            "co2_avoided_tons": round(co2_avoided_kg / 1000, 4),
            "avg_performance_ratio": round(avg_pr, 2),
            "avg_efficiency": round(avg_efficiency, 2),
            "max_temperature_c": round(max_temp, 1),
            "peak_power_w": round(peak_power_w, 1),
            "nominal_power_kw": self.nominal_power_kw,
        }

    # ------------------------------------------------------------------
    # Interactive HTML Report (Plotly)
    # ------------------------------------------------------------------

    def generate_html(
        self,
        df: pd.DataFrame,
        alerts: list[Alert],
        filename: str = "report.html",
    ) -> Path:
        """Generate an interactive HTML report with Plotly charts.

        Charts included:
          1. AC Power vs. Irradiance (dual-axis time series)
          2. Performance Ratio trend (daily average with threshold line)
          3. String Voltage Comparison (ΔV detection)
          4. Heatsink Temperature profile

        Parameters
        ----------
        df : pd.DataFrame
            Processed DataFrame.
        alerts : list[Alert]
            Detected anomalies to annotate on charts.
        filename : str
            Output filename (default: "report.html").

        Returns
        -------
        Path
            Absolute path to the generated HTML file.
        """
        if not PLOTLY_AVAILABLE:
            logger.warning("Plotly not installed. Skipping HTML report.")
            return Path("")

        summary = self.compute_summary(df)

        fig = make_subplots(
            rows=4,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            subplot_titles=(
                "AC Power Output & Solar Irradiance",
                "Performance Ratio (Daily Average)",
                "DC String Voltages (ΔV Detection)",
                "Heatsink Temperature",
            ),
        )

        # -- Chart 1: Power vs Irradiance (dual axis) --
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["p_ac_output"],
                name="AC Power (W)",
                line=dict(color="#3498DB", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(52, 152, 219, 0.15)",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["irradiance_poa"],
                name="Irradiance (W/m²)",
                line=dict(color="#F39C12", width=1.5, dash="dot"),
                yaxis="y2",
            ),
            row=1,
            col=1,
        )

        # -- Chart 2: Daily Performance Ratio --
        daylight = df[df["is_daylight"]].copy()
        if not daylight.empty:
            daylight["date"] = daylight["timestamp"].dt.date
            daily_pr = daylight.groupby("date")["performance_ratio"].mean()
            fig.add_trace(
                go.Bar(
                    x=[str(d) for d in daily_pr.index],
                    y=daily_pr.values,
                    name="Avg PR (%)",
                    marker_color=[
                        "#2ECC71" if pr >= 80 else "#E74C3C"
                        for pr in daily_pr.values
                    ],
                ),
                row=2,
                col=1,
            )
            # Target PR line
            fig.add_hline(
                y=80,
                line_dash="dash",
                line_color="#E74C3C",
                annotation_text="Target PR: 80%",
                row=2,
                col=1,
            )

        # -- Chart 3: String Voltages --
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["v_dc_string_1"],
                name="String 1 (V)",
                line=dict(color="#9B59B6", width=1.5),
            ),
            row=3,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["v_dc_string_2"],
                name="String 2 (V)",
                line=dict(color="#1ABC9C", width=1.5),
            ),
            row=3,
            col=1,
        )

        # -- Chart 4: Temperature --
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["temp_heatsink"],
                name="Heatsink Temp (°C)",
                line=dict(color="#E74C3C", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(231, 76, 60, 0.1)",
            ),
            row=4,
            col=1,
        )
        fig.add_hline(
            y=60,
            line_dash="dash",
            line_color="#E74C3C",
            annotation_text="Warning: 60°C",
            row=4,
            col=1,
        )

        # Layout styling
        fig.update_layout(
            title=dict(
                text=(
                    f"📊 {self.plant_name} — Performance Report<br>"
                    f"<sub>{summary['period_start']} to {summary['period_end']} | "
                    f"Energy: {summary['energy_kwh']:.1f} kWh | "
                    f"CO₂ Avoided: {summary['co2_avoided_kg']:.1f} kg</sub>"
                ),
                font=dict(size=16),
            ),
            height=1200,
            template="plotly_dark",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.05),
            font=dict(family="Segoe UI, Arial, sans-serif"),
        )

        output_path = self.output_dir / filename
        fig.write_html(str(output_path), include_plotlyjs=True)
        logger.info("HTML report saved: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Executive PDF Report (FPDF2)
    # ------------------------------------------------------------------

    def generate_pdf(
        self,
        df: pd.DataFrame,
        alerts: list[Alert],
        filename: str = "report.pdf",
    ) -> Path:
        """Generate a formal executive PDF report.

        Sections:
          1. Executive Summary (energy, CO₂, PR).
          2. Alert Table (time, severity, details).
          3. Key Recommendations.

        Parameters
        ----------
        df : pd.DataFrame
            Processed DataFrame.
        alerts : list[Alert]
            Detected anomalies.
        filename : str
            Output filename (default: "report.pdf").

        Returns
        -------
        Path
            Absolute path to the generated PDF file.
        """
        if not FPDF_AVAILABLE:
            logger.warning("FPDF2 not installed. Skipping PDF report.")
            return Path("")

        summary = self.compute_summary(df)

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)

        # -- Page 1: Executive Summary --
        pdf.add_page()
        self._pdf_header(pdf, summary)
        self._pdf_executive_summary(pdf, summary)
        self._pdf_alert_table(pdf, alerts)
        self._pdf_recommendations(pdf, alerts, summary)
        self._pdf_footer(pdf)

        output_path = self.output_dir / filename
        pdf.output(str(output_path))
        logger.info("PDF report saved: %s", output_path)
        return output_path

    # -- PDF helper methods --

    def _pdf_header(self, pdf: FPDF, summary: dict) -> None:
        """Render the PDF report header."""
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(44, 62, 80)
        pdf.cell(0, 15, f"{self.plant_name}", ln=True, align="C")

        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(127, 140, 141)
        pdf.cell(
            0,
            8,
            f"Performance Report | {summary['period_start']} to {summary['period_end']}",
            ln=True,
            align="C",
        )
        pdf.ln(5)
        # Divider line
        pdf.set_draw_color(52, 152, 219)
        pdf.set_line_width(0.5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(8)

    def _pdf_executive_summary(self, pdf: FPDF, summary: dict) -> None:
        """Render the executive summary section."""
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(44, 62, 80)
        pdf.cell(0, 10, "Executive Summary", ln=True)
        pdf.ln(3)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(52, 73, 94)

        metrics = [
            (
                "Total Energy Generated",
                f"{summary['energy_kwh']:.2f} kWh",
            ),
            (
                "CO2 Emissions Avoided",
                f"{summary['co2_avoided_kg']:.2f} kg ({summary['co2_avoided_tons']:.4f} tons)",
            ),
            (
                "Average Performance Ratio",
                f"{summary['avg_performance_ratio']:.1f}%",
            ),
            (
                "Average Inverter Efficiency",
                f"{summary['avg_efficiency']:.1f}%",
            ),
            (
                "Peak Power Achieved",
                f"{summary['peak_power_w']:.0f} W / {summary['nominal_power_kw']:.0f} kW nominal",
            ),
            (
                "Max Heatsink Temperature",
                f"{summary['max_temperature_c']:.1f} C",
            ),
            (
                "Data Points Analyzed",
                f"{summary['total_records']} ({summary['daylight_records']} daylight)",
            ),
        ]

        for label, value in metrics:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(80, 7, f"  {label}:", ln=False)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, value, ln=True)

        pdf.ln(5)

    def _pdf_alert_table(self, pdf: FPDF, alerts: list[Alert]) -> None:
        """Render the alert summary table."""
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(44, 62, 80)
        pdf.cell(0, 10, f"Detected Anomalies ({len(alerts)})", ln=True)
        pdf.ln(3)

        if not alerts:
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(39, 174, 96)
            pdf.cell(0, 7, "  No anomalies detected. All systems operational.", ln=True)
            pdf.ln(5)
            return

        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(52, 73, 94)
        pdf.set_text_color(255, 255, 255)
        col_widths = [25, 35, 95, 35]
        headers = ["Severity", "Rule", "Details", "Time"]
        for w, h in zip(col_widths, headers):
            pdf.cell(w, 8, h, border=1, fill=True, align="C")
        pdf.ln()

        # Table rows
        pdf.set_font("Helvetica", "", 8)
        for alert in alerts:
            pdf.set_text_color(52, 73, 94)

            # Severity with color
            if alert.severity == Severity.CRITICAL:
                pdf.set_text_color(231, 76, 60)
            elif alert.severity == Severity.WARNING:
                pdf.set_text_color(243, 156, 18)
            else:
                pdf.set_text_color(46, 204, 113)

            pdf.cell(25, 7, alert.severity.value.upper(), border=1, align="C")
            pdf.set_text_color(52, 73, 94)
            pdf.cell(35, 7, alert.rule_name[:20], border=1, align="C")

            # Truncate long messages for PDF and sanitize Unicode
            msg = alert.message[:60] + "..." if len(alert.message) > 60 else alert.message
            msg = self._sanitize_for_pdf(msg)
            pdf.cell(95, 7, msg, border=1)

            time_str = (
                alert.timestamp_start.strftime("%m-%d %H:%M")
                if alert.timestamp_start
                else "N/A"
            )
            pdf.cell(35, 7, time_str, border=1, align="C")
            pdf.ln()

        pdf.ln(5)

    def _pdf_recommendations(
        self,
        pdf: FPDF,
        alerts: list[Alert],
        summary: dict,
    ) -> None:
        """Generate actionable recommendations based on analysis results."""
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(44, 62, 80)
        pdf.cell(0, 10, "Recommendations", ln=True)
        pdf.ln(3)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(52, 73, 94)

        recommendations = []

        for alert in alerts:
            if alert.rule_name == "Soiling Detection":
                recommendations.append(
                    "* Schedule panel cleaning within the next 48 hours to "
                    "recover Performance Ratio."
                )
            elif alert.rule_name == "Inverter Clipping":
                recommendations.append(
                    "* Review inverter sizing vs. array capacity. Consider "
                    "DC/AC ratio optimization."
                )
            elif alert.rule_name == "Isolation Fault":
                recommendations.append(
                    "* URGENT: Dispatch technician for wiring inspection. "
                    "Check MC4 connectors and bypass diodes."
                )

        if summary["max_temperature_c"] > 60:
            recommendations.append(
                "* Heatsink temperature exceeded 60 C. Verify ventilation "
                "and fan operation."
            )

        if summary["avg_performance_ratio"] < 75:
            recommendations.append(
                "* Average PR below 75%. Comprehensive system audit recommended."
            )

        if not recommendations:
            recommendations.append(
                "* System operating within normal parameters. Continue "
                "scheduled maintenance."
            )

        for rec in recommendations:
            pdf.multi_cell(0, 6, f"  {rec}")
            pdf.ln(2)

    def _pdf_footer(self, pdf: FPDF) -> None:
        """Render the PDF footer."""
        pdf.ln(10)
        pdf.set_draw_color(52, 152, 219)
        pdf.set_line_width(0.3)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(149, 165, 166)
        pdf.cell(
            0,
            5,
            f"Generated by pv-report-automation v2.0 | "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | "
            f"ENERTEC LATINOAMERICA",
            ln=True,
            align="C",
        )
        pdf.cell(
            0,
            5,
            "Maintainer: Miguel Angel Mejia Sanchez",
            ln=True,
            align="C",
        )
