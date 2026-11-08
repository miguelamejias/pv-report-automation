# -*- coding: utf-8 -*-
"""
Tests for ReportGenerator — Executive PDF, HTML, and Incident Work Order PDF
===========================================================================
"""

from datetime import datetime

from src.anomaly_engine import Alert, Severity
from src.report_generator import ReportGenerator
from src.transformer import SolarDataTransformer


def test_generate_pdf_and_html_and_incident_work_order(tmp_path):
    transformer = SolarDataTransformer()
    df = transformer.load_csv("sample_data/plant_log_2024.csv")
    alert = Alert(
        rule_name="Instant Panel Fault",
        severity=Severity.CRITICAL,
        message="Caída crítica de voltaje ΔV = 42.1% en PNL-B04-12 (°C: 78.5)",
        timestamp_start=datetime.now(),
        details={
            "panel_id": "PNL-B04-12",
            "location_block": "Bloque B - Fila 4 - Posición 12",
            "latitude": 4.9186,
            "longitude": -73.9982,
        },
    )
    gen = ReportGenerator(output_dir=tmp_path)
    html_path = gen.generate_html(df, [alert])
    pdf_path = gen.generate_pdf(df, [alert])
    inc_path = gen.generate_incident_pdf(
        df,
        [alert],
        incident_id="INC-2026-0001",
        technician_name="Carlos Reclutador",
        supervisor_name="Ing. Miguel Ángel Mejía Sánchez",
    )
    assert html_path.exists()
    assert pdf_path.exists()
    assert inc_path.exists()
    assert inc_path.name == "incident_INC-2026-0001.pdf"
