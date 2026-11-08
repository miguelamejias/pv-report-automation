# -*- coding: utf-8 -*-
"""
pv-report-automation — Solar Plant Maintenance Intelligence Suite
================================================================

A modular, production-grade toolkit for processing photovoltaic system logs,
detecting hardware anomalies, and generating executive reports with automated
multi-channel alerts.

Architecture follows SOLID principles with Strategy pattern for anomaly
detection rules. Originally a simple CSV reader used daily at ENERTEC
LATINOAMÉRICA, refactored with AI assistance into a professional,
scalable system.

Modules:
    - transformer: ETL pipeline for solar data (SolarDataTransformer)
    - anomaly_engine: Rule-based detection engine (AnomalyEngine)
    - report_generator: PDF & interactive HTML reports (ReportGenerator)
    - notifications: Multi-channel alert system (NotificationOrchestrator)
    - sheets_manager: Google Sheets & local CSV telemetry sync (GoogleSheetsManager)
    - imap_listener: Inbound technician email reply detector (IMAPListener)
    - incident_manager: Closed-loop NOC state machine (IncidentManager)

Author: Miguel Ángel Mejía Sánchez
Version: 3.0.0
"""

__version__ = "3.0.0"
__author__ = "Miguel Ángel Mejía Sánchez"
