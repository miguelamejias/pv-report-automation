# -*- coding: utf-8 -*-
"""
pv-report-automation — Main Entry Point
========================================

Solar Plant Maintenance Intelligence Suite for photovoltaic systems.
Processes inverter logs, detects anomalies, generates executive reports,
and dispatches multi-channel alerts.

This is the orchestration layer that wires together:
  1. SolarDataTransformer → ETL pipeline
  2. AnomalyEngine → Rule-based detection (Strategy pattern)
  3. ReportGenerator → PDF & HTML reports
  4. NotificationOrchestrator → Email & Slack alerts

Usage:
    python main.py                            # Process default sample data
    python main.py --input data/custom.csv    # Process a specific file
    python main.py --input data/custom.csv --notify  # With real notifications

Author: Miguel Ángel Mejía Sánchez
Version: 2.0.0 — Refactored with AI assistance from a simple CSV reader
                  into a modular, production-ready monitoring system.
"""

import argparse
import logging
import sys
from pathlib import Path

# Force UTF-8 encoding for standard output/error to display emojis correctly on Windows
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from src import __version__
from src.transformer import SolarDataTransformer
from src.anomaly_engine import (
    AnomalyEngine,
    ClippingDetector,
    IsolationFaultDetector,
    SoilingDetector,
)
from src.report_generator import ReportGenerator
from src.notifications import (
    EmailConfig,
    NotificationOrchestrator,
    SlackConfig,
)


# ---------------------------------------------------------------------------
# Logging configuration — structured output for monitoring
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool = False) -> None:
    """Configure application logging with appropriate detail level.

    Why this format:
      - Timestamp: Essential for correlating with inverter logs.
      - Module name: Quickly identify which component logged the message.
      - Level: Filter noise in production vs. debug environments.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for flexible execution.

    Supports:
      --input   : Path to the CSV log file (default: sample data).
      --output  : Output directory for reports (default: output/).
      --plant   : Plant name for report headers.
      --power   : Nominal plant capacity in kW.
      --notify  : Enable real email/Slack notifications.
      --verbose : Enable debug-level logging.
    """
    parser = argparse.ArgumentParser(
        prog="pv-report-automation",
        description=(
            "Solar Plant Maintenance Intelligence Suite — "
            "Process PV logs, detect anomalies, generate reports."
        ),
        epilog="Author: Miguel Ángel Mejía Sánchez | ENERTEC LATINOAMÉRICA",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="sample_data/plant_log_2024.csv",
        help="Path to the CSV log file (default: sample_data/plant_log_2024.csv)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="Directory for generated reports (default: output/)",
    )
    parser.add_argument(
        "--plant",
        type=str,
        default="ENERTEC Solar Plant",
        help="Plant name for report headers",
    )
    parser.add_argument(
        "--power",
        type=float,
        default=10.0,
        help="Nominal plant capacity in kW (default: 10.0)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Enable real email/Slack notifications (requires config.py)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    """Execute the full PV monitoring pipeline.

    Pipeline steps:
      1. Load & transform raw CSV data (ETL).
      2. Run anomaly detection engine (3 strategies).
      3. Generate HTML + PDF executive reports.
      4. Dispatch alerts (simulated or real).
    """
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("main")

    print()
    print("=" * 60)
    print("  ⚡ pv-report-automation v{} ".format(__version__))
    print("  Solar Plant Maintenance Intelligence Suite")
    print("  ENERTEC LATINOAMÉRICA")
    print("=" * 60)
    print()

    # ------------------------------------------------------------------
    # STEP 1: ETL — Extract, Transform, Load
    # ------------------------------------------------------------------
    logger.info("STEP 1/4: Loading and transforming data...")
    transformer = SolarDataTransformer(
        nominal_power_kw=args.power,
        timezone="America/Bogota",
    )

    try:
        df = transformer.load_csv(args.input)
    except FileNotFoundError:
        logger.error("File not found: %s", args.input)
        logger.info("Run with: python main.py --input path/to/your/data.csv")
        sys.exit(1)
    except ValueError as e:
        logger.error("Data validation failed: %s", e)
        sys.exit(1)

    print(f"  ✅ Loaded {len(df)} records from {args.input}")
    print()

    # ------------------------------------------------------------------
    # STEP 2: Anomaly Detection (Strategy Pattern)
    # ------------------------------------------------------------------
    logger.info("STEP 2/4: Running anomaly detection engine...")
    engine = AnomalyEngine.create_default()

    alerts = engine.analyze(df)

    print(f"  🔍 Anomaly Engine: {engine.detector_count} detectors registered")
    print(f"  ⚠️  Alerts found: {len(alerts)}")
    for alert in alerts:
        severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
        emoji = severity_emoji.get(alert.severity.value, "⚪")
        print(f"     {emoji} [{alert.severity.value.upper()}] {alert.rule_name}: "
              f"{alert.message[:80]}...")
    print()

    # ------------------------------------------------------------------
    # STEP 3: Report Generation (PDF + HTML)
    # ------------------------------------------------------------------
    logger.info("STEP 3/4: Generating executive reports...")
    report_gen = ReportGenerator(
        plant_name=args.plant,
        nominal_power_kw=args.power,
        output_dir=args.output,
    )

    # Summary statistics
    summary = report_gen.compute_summary(df)
    print(f"  📊 Summary Statistics:")
    print(f"     Energy Generated : {summary['energy_kwh']:.2f} kWh")
    print(f"     CO₂ Avoided      : {summary['co2_avoided_kg']:.2f} kg")
    print(f"     Avg PR           : {summary['avg_performance_ratio']:.1f}%")
    print(f"     Peak Power       : {summary['peak_power_w']:.0f} W")
    print(f"     Max Temperature  : {summary['max_temperature_c']:.1f}°C")
    print()

    # Generate reports
    html_path = report_gen.generate_html(df, alerts)
    pdf_path = report_gen.generate_pdf(df, alerts)

    if html_path.exists():
        print(f"  📄 HTML Report: {html_path}")
    if pdf_path.exists():
        print(f"  📄 PDF Report:  {pdf_path}")
    print()

    # ------------------------------------------------------------------
    # STEP 4: Alert Dispatch (Multi-channel)
    # ------------------------------------------------------------------
    logger.info("STEP 4/4: Dispatching alerts...")

    if args.notify:
        # Load real credentials from config
        try:
            from config import (
                SMTP_SERVER,
                SMTP_PORT,
                SENDER_EMAIL,
                SENDER_PASSWORD,
                RECIPIENTS,
                SLACK_WEBHOOK_URL,
            )

            orchestrator = NotificationOrchestrator(
                email_config=EmailConfig(
                    smtp_server=SMTP_SERVER,
                    smtp_port=SMTP_PORT,
                    sender_email=SENDER_EMAIL,
                    sender_password=SENDER_PASSWORD,
                    recipients=RECIPIENTS,
                ),
                slack_config=SlackConfig(webhook_url=SLACK_WEBHOOK_URL),
            )
            result = orchestrator.dispatch(alerts, pdf_path=pdf_path)
            print(f"  📬 Notifications sent: Email={result['email']}, "
                  f"Slack={result['slack']}")

        except ImportError:
            logger.warning(
                "config.py not found. Copy config.example.py to config.py "
                "and fill in your credentials."
            )
            print("  ⚠️  config.py not found. Running in simulation mode.")
            print()
            print(NotificationOrchestrator.simulate_dispatch(alerts))
    else:
        # Simulation mode (default for demos)
        print(NotificationOrchestrator.simulate_dispatch(alerts))

    print()
    print("=" * 60)
    print("  ✅ Pipeline complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
