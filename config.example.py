# -*- coding: utf-8 -*-
"""
Configuration Template — pv-report-automation
===============================================

Copy this file to `config.py` and fill in your credentials.
NEVER commit config.py to version control (it's in .gitignore).

Security best practice:
  For production, use environment variables instead of this file.
  This template exists for local development convenience.

Author: Miguel Ángel Mejía Sánchez
"""

# ---------------------------------------------------------------------------
# Email (SMTP) Configuration
# ---------------------------------------------------------------------------
# For Gmail: Use an App Password, NOT your personal password.
# Guide: https://support.google.com/accounts/answer/185833

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587  # 587 for STARTTLS, 465 for SSL
SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your_app_specific_password"
RECIPIENTS = [
    "supervisor@enertec.com",
    "operaciones@enertec.com",
]

# ---------------------------------------------------------------------------
# Slack Webhook Configuration
# ---------------------------------------------------------------------------
# Create a webhook: https://api.slack.com/messaging/webhooks

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# ---------------------------------------------------------------------------
# Plant Configuration
# ---------------------------------------------------------------------------

PLANT_NAME = "ENERTEC Solar Plant — Bogotá"
NOMINAL_POWER_KW = 10.0  # Nameplate capacity in kW
TIMEZONE = "America/Bogota"
