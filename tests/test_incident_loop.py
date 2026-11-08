# -*- coding: utf-8 -*-
"""
Tests for IMAPListener & IncidentManager Closed-Loop State Machine
==================================================================
"""

from src.imap_listener import IMAPListener
from src.incident_manager import IncidentManager, TechnicianState
from src.sheets_manager import GoogleSheetsManager
from src.transformer import SolarDataTransformer


def test_parse_reply_body_strips_quoted_lines():
    raw = (
        "Ya revisé el panel PNL-B04-12 y cambié el conector MC4.\n\n"
        "> El 08/11/2026 escribió:\n"
        "> Alerta crítica"
    )
    cleaned = IMAPListener.parse_reply_body(raw)
    assert "cambié el conector MC4" in cleaned
    assert "> Alerta crítica" not in cleaned


def test_full_closed_loop_incident_lifecycle_no_duplicate_emails(tmp_path):
    csv_path = tmp_path / "live_telemetry.csv"
    sheets = GoogleSheetsManager(local_csv_path=csv_path)
    transformer = SolarDataTransformer()
    manager = IncidentManager(sheets_manager=sheets, output_dir=tmp_path)

    manager.register_technician("Laura Reclutadora", "laura@empresa.com")
    assert manager.state == TechnicianState.AVAILABLE

    # 1. Normal telemetry -> stays AVAILABLE
    df_clean = transformer.transform_dataframe(sheets.fetch_telemetry())
    status_1 = manager.evaluate_telemetry(df_clean)
    assert status_1["state"] == TechnicianState.AVAILABLE

    # 2. Sabotage telemetry -> transitions to EMERGENCY_ASSIGNED and sends 1 email
    sheets.inject_fault(
        panel_id="PNL-B04-12",
        v_dc_string_2=165.0,
        temp_heatsink=88.0,
        status_code="0x05",
    )
    df_fault = transformer.transform_dataframe(sheets.fetch_telemetry())
    status_2 = manager.evaluate_telemetry(df_fault)
    assert status_2["state"] == TechnicianState.EMERGENCY_ASSIGNED
    assert status_2["email_dispatched_count"] == 1
    incident_id = status_2["incident_id"]

    # 3. Re-evaluating same fault on Streamlit refresh does NOT send duplicate email
    status_3 = manager.evaluate_telemetry(df_fault)
    assert status_3["incident_id"] == incident_id
    assert status_3["email_dispatched_count"] == 1

    # 4. Technician replies to email -> restores sheet and normalizes platform
    resolution = manager.process_resolution(
        resolution_note="Conector MC4 reemplazado y coordinado con supervisor.",
        resolved_by="email_reply",
    )
    assert resolution["state"] == TechnicianState.RESOLVED
    df_after = transformer.transform_dataframe(sheets.fetch_telemetry())
    status_4 = manager.evaluate_telemetry(df_after)
    assert status_4["state"] == TechnicianState.AVAILABLE


def test_app_plant_map_figure_and_config_loader(tmp_path):
    from app import build_plant_layout_figure, load_optional_config

    cfg = load_optional_config()
    assert "smtp_server" in cfg
    assert "imap_server" in cfg

    sheets = GoogleSheetsManager(local_csv_path=tmp_path / "map_telemetry.csv")
    sheets.inject_fault(panel_id="PNL-B04-12", v_dc_string_2=160.0, temp_heatsink=89.0, status_code="0x05")
    df = SolarDataTransformer().transform_dataframe(sheets.fetch_telemetry())
    fig = build_plant_layout_figure(df)
    assert len(fig.data) == 1
    assert "#E74C3C" in fig.data[0].marker.color


def test_imap_mime_and_multipart_extraction_and_polling(monkeypatch):
    import email.message
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from src.imap_listener import IMAPConfig, IMAPListener
    from src.notifications import EmailConfig, SlackConfig

    # Config containers
    ecfg = EmailConfig("smtp.gmail.com", 587, "noc@enertec.com", "secret", ["tech@enertec.com"])
    scfg = SlackConfig("https://hooks.slack.com/test", "#solar")
    icfg = IMAPConfig("imap.gmail.com", 993, "noc@enertec.com", "secret")
    assert ecfg.smtp_port == 587
    assert scfg.channel == "#solar"
    assert icfg.imap_port == 993

    # Multipart message extraction
    msg = MIMEMultipart()
    msg["Subject"] = "Re: [INC-2026-01] Falla en Panel"
    msg["From"] = "Laura Reclutadora <laura@empresa.com>"
    msg.attach(MIMEText("Panel reparado y verificado con supervisor.\n> Texto citado", "plain", "utf-8"))

    extracted = IMAPListener._extract_text_from_message(msg)
    assert "Panel reparado" in extracted
    assert "Texto citado" not in extracted

    # Fake IMAP4_SSL for check_for_resolution_reply
    raw_bytes = msg.as_bytes()

    class FakeIMAP:
        def __init__(self, host, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, user, pwd):
            return "OK", [b"Logged in"]

        def select(self, box):
            return "OK", [b"1"]

        def search(self, charset, criteria):
            return "OK", [b"1"]

        def fetch(self, num, parts):
            return "OK", [(b"1 (RFC822)", raw_bytes)]

    import imaplib
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)

    listener = IMAPListener(config=icfg)
    reply = listener.check_for_resolution_reply("INC-2026-01", "laura@empresa.com")
    assert reply is not None
    assert reply["incident_id"] == "INC-2026-01"
    assert "Panel reparado" in reply["body"]


def test_imap_falls_back_to_all_when_unseen_empty(monkeypatch):
    from email.mime.text import MIMEText
    import imaplib
    from src.imap_listener import IMAPConfig, IMAPListener

    msg = MIMEText("Reparado en sitio y verificado.", "plain", "utf-8")
    msg["Subject"] = "Re: [INC-2026-99] Alerta"
    msg["From"] = "laura@empresa.com"
    raw_bytes = msg.as_bytes()

    class FakeIMAPSeenOnly:
        def __init__(self, host, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, user, pwd):
            return "OK", [b"Logged in"]

        def select(self, box):
            return "OK", [b"1"]

        def search(self, charset, criteria):
            if criteria == "UNSEEN":
                return "OK", [b""]
            return "OK", [b"1"]

        def fetch(self, num, parts):
            return "OK", [(b"1 (RFC822)", raw_bytes)]

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAPSeenOnly)
    icfg = IMAPConfig("imap.gmail.com", 993, "noc@enertec.com", "secret")
    listener = IMAPListener(config=icfg)
    reply = listener.check_for_resolution_reply("INC-2026-99", "laura@empresa.com")
    assert reply is not None
    assert reply["incident_id"] == "INC-2026-99"


