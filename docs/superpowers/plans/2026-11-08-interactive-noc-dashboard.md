# pv-report-automation v3.0 Interactive NOC & Closed-Loop Incident Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive Streamlit Solar NOC platform connected to Google Sheets and SMTP/IMAP email where a recruiter registers as the on-duty technician, edits a Google Sheet cell to trigger an incident with physical panel location and PDF work order, receives an alert email, and replies to that email to automatically restore the Google Sheet and resolve the incident.

**Architecture:** Modular Python architecture extending the v2.0 SOLID classes (`SolarDataTransformer`, `AnomalyEngine`, `ReportGenerator`, `NotificationOrchestrator`) with three new services: `GoogleSheetsManager` (bidirectional Google Sheets / local CSV sync), `IMAPListener` (inbound reply detection), and `IncidentManager` (anti-spam state machine `IDLE -> ACTIVE_ALERT -> RESOLVED`), orchestrated through `app.py` (Streamlit web UI).

**Tech Stack:** Python 3.9+, `streamlit`, `pandas`, `numpy`, `plotly`, `fpdf2`, `gspread`, `google-auth`, standard library `smtplib`, `imaplib`, `email`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-08-interactive-noc-dashboard-design.md`

## Global Constraints

- Backward-compatible with existing v2.0 CSV files (`sample_data/plant_log_2024.csv`) and `main.py` CLI.
- All 33 existing tests plus new tests must pass (`pytest tests/ -v`) with >80% total coverage.
- Zero duplicate emails on Streamlit reruns: `IncidentManager` only sends one outbound email per active incident transition.
- Graceful fallback: if Google API write credentials or IMAP server are unreachable, local CSV / simulation controls must keep the live interview demo working without crashing.
- Never commit secrets (`config.py`, `.env`, service account JSONs) to Git.

## Review Focus

1. **Legacy CSV without location columns (`panel_id`, `location_block`, `latitude`, `longitude`):** `SolarDataTransformer` must populate sensible default values (`PNL-A01-01`, `Bloque A - Fila 1 - Posición 1`, `4.9186`, `-73.9982`) so v2.0 CSVs never fail validation.
2. **Single-row edit in Google Sheets:** A recruiter editing just one row (e.g., dropping `v_dc_string_2` from `395` to `200`, raising `temp_heatsink` to `88`, or setting `status_code` to `0x05`) must immediately trigger a `CRITICAL` `InstantPanelFaultDetector` alert containing `panel_id`, `location_block`, `latitude`, and `longitude` in `Alert.details`.
3. **Repeated Streamlit refresh cycles while fault is active:** Calling `IncidentManager.evaluate_telemetry(df)` multiple times while the same fault persists must NOT send a second email or generate a new `incident_id`.
4. **Multipart or quoted-reply emails from Gmail/Outlook:** `IMAPListener` must extract the plain-text reply body cleanly (stripping quoted lines starting with `>`) and match either `[INC-XXXX]` in the `Subject` header OR the registered technician's email address in `From`.
5. **Unicode characters in Incident Work Order PDF:** Spanish accents (`á, é, í, ó, ú, ñ`) and symbols (`Δ, °, ²`) in panel locations or technician notes must pass through `ReportGenerator._sanitize_for_pdf()` without raising `FPDFUnicodeEncodingException`.

---

### Task 1: Enrich `SolarDataTransformer` & Sample Data with Panel Location Metadata

**Files:**
- Modify: `src/transformer.py:131-259`
- Modify: `generate_sample_data.py:100-185`
- Modify: `sample_data/plant_log_2024.csv`
- Test: `tests/test_transformer.py`

**Interfaces:**
- Consumes: raw CSV or DataFrame with required telemetry columns and optional `panel_id`, `location_block`, `latitude`, `longitude`.
- Produces:
  - `SolarDataTransformer.transform_dataframe(df: pd.DataFrame) -> pd.DataFrame` (new public method so `GoogleSheetsManager` can pass an in-memory DataFrame directly without writing to disk).
  - Guaranteed columns on output DataFrame: `panel_id` (`str`), `location_block` (`str`), `latitude` (`float`), `longitude` (`float`).

- [ ] **Step 1: Write the failing tests in `tests/test_transformer.py`**

```python
def test_default_location_columns_populated_when_missing(sample_raw_df):
    transformer = SolarDataTransformer()
    df = transformer.transform_dataframe(sample_raw_df)
    assert "panel_id" in df.columns
    assert "location_block" in df.columns
    assert "latitude" in df.columns
    assert "longitude" in df.columns
    assert df["panel_id"].iloc[0] == "PNL-A01-01"


def test_preserves_existing_location_columns(sample_raw_df):
    sample_raw_df["panel_id"] = "PNL-B04-12"
    sample_raw_df["location_block"] = "Bloque B - Fila 4 - Posicion 12"
    sample_raw_df["latitude"] = 4.9200
    sample_raw_df["longitude"] = -73.9900
    transformer = SolarDataTransformer()
    df = transformer.transform_dataframe(sample_raw_df)
    assert df["panel_id"].iloc[0] == "PNL-B04-12"
    assert df["location_block"].iloc[0] == "Bloque B - Fila 4 - Posicion 12"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transformer.py -k "location_columns" -v`
Expected: FAIL with `AttributeError: 'SolarDataTransformer' object has no attribute 'transform_dataframe'`

- [ ] **Step 3: Implement `transform_dataframe` and location column enrichment in `src/transformer.py` and update `generate_sample_data.py`**

In `src/transformer.py`:
- Extract the method-chaining pipeline from `load_csv` into `transform_dataframe(self, df: pd.DataFrame) -> pd.DataFrame` and have `load_csv` call `self.transform_dataframe(df)`.
- Add `_ensure_location_columns(self, df: pd.DataFrame) -> pd.DataFrame` to the pipeline, setting defaults when missing:
  - `panel_id = "PNL-A01-01"`
  - `location_block = "Bloque A - Fila 1 - Posicion 1"`
  - `latitude = 4.9186`
  - `longitude = -73.9982`
- Update `generate_sample_data.py` to include rotating realistic panel IDs (`PNL-A01-01` through `PNL-C03-08`), block locations, and GPS coordinates around Sabana Norte (`4.9186, -73.9982`), and regenerate `sample_data/plant_log_2024.csv`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_transformer.py -v`
Expected: PASS (all existing + 2 new tests)

- [ ] **Step 5: Commit**

```bash
git add src/transformer.py generate_sample_data.py sample_data/plant_log_2024.csv tests/test_transformer.py
git commit -m "feat(transformer): support in-memory DataFrame transform and panel location metadata"
```

---

### Task 2: Fix Anomaly Detectors & Add `InstantPanelFaultDetector` with Location Context

**Files:**
- Modify: `src/anomaly_engine.py:97-449`
- Test: `tests/test_anomaly_engine.py`

**Interfaces:**
- Consumes: transformed DataFrame from `SolarDataTransformer`.
- Produces:
  - `InstantPanelFaultDetector(delta_v_threshold_pct: float = 15.0, max_temp_c: float = 75.0)` implementing `AnomalyDetector`.
  - Fixed `ClippingDetector` (groups by date before checking clipping windows so multi-day datasets work accurately).
  - Enriched `Alert.details` containing `panel_id`, `location_block`, `latitude`, `longitude`, and `row_index` for affected panels.
  - `AnomalyEngine.create_default()` registers `InstantPanelFaultDetector` alongside `SoilingDetector`, `ClippingDetector`, and `IsolationFaultDetector`.

- [ ] **Step 1: Write the failing tests in `tests/test_anomaly_engine.py`**

```python
from src.anomaly_engine import InstantPanelFaultDetector, Severity


def test_instant_detector_catches_single_row_voltage_drop(base_daylight_df):
    df = base_daylight_df.copy()
    df["panel_id"] = "PNL-B04-12"
    df["location_block"] = "Bloque B - Fila 4 - Posicion 12"
    df["latitude"] = 4.9195
    df["longitude"] = -73.9975
    # Sabotage a single row (simulating Google Sheets edit)
    df.loc[df.index[-1], "v_dc_string_2"] = 180.0
    df.loc[df.index[-1], "delta_v_dc_pct"] = 42.0

    detector = InstantPanelFaultDetector()
    alerts = detector.detect(df)
    assert len(alerts) == 1
    assert alerts[0].severity == Severity.CRITICAL
    assert alerts[0].details["panel_id"] == "PNL-B04-12"
    assert alerts[0].details["location_block"] == "Bloque B - Fila 4 - Posicion 12"


def test_instant_detector_catches_hardware_status_or_overtemp(base_daylight_df):
    df = base_daylight_df.copy()
    df["panel_id"] = "PNL-C02-05"
    df["location_block"] = "Bloque C - Fila 2 - Posicion 5"
    df["latitude"] = 4.9180
    df["longitude"] = -73.9990
    df.loc[df.index[-1], "temp_heatsink"] = 89.5
    df.loc[df.index[-1], "status_code"] = "0x04"

    detector = InstantPanelFaultDetector()
    alerts = detector.detect(df)
    assert len(alerts) >= 1
    assert alerts[0].severity == Severity.CRITICAL
    assert alerts[0].details["panel_id"] == "PNL-C02-05"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_anomaly_engine.py -k "instant_detector" -v`
Expected: FAIL with `ImportError: cannot import name 'InstantPanelFaultDetector'`

- [ ] **Step 3: Implement `InstantPanelFaultDetector` and fix `ClippingDetector` in `src/anomaly_engine.py`**

- Implement `InstantPanelFaultDetector.detect(self, df: pd.DataFrame) -> list[Alert]` inspecting the latest readings (or any row with `delta_v_dc_pct > self.delta_v_threshold_pct`, `temp_heatsink > self.max_temp_c`, or `status_code != "0x00"`), populating `Alert.details` with `panel_id`, `location_block`, `latitude`, `longitude`, `row_index`, `v_dc_string_1`, `v_dc_string_2`, `temp_heatsink`, and `status_code`.
- Update `ClippingDetector.detect()` to group `daylight` by `daylight["timestamp"].dt.date` and evaluate peak power clipping per day so multi-day datasets trigger properly.
- Register `InstantPanelFaultDetector()` in `AnomalyEngine.create_default()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_anomaly_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/anomaly_engine.py tests/test_anomaly_engine.py
git commit -m "feat(anomaly-engine): add InstantPanelFaultDetector with location metadata and fix daily clipping detection"
```

---

### Task 3: Upgrade `ReportGenerator` & `NotificationOrchestrator` for Work Orders & Supervisor Instructions

**Files:**
- Modify: `src/report_generator.py:324-582`
- Modify: `src/notifications.py:131-385`
- Create: `tests/test_report_generator.py`
- Modify: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `Alert` list (with `panel_id`, `location_block`, `latitude`, `longitude` in `details`), `incident_id: str`, `technician_name: str`, `technician_email: str`, `supervisor_name: str`.
- Produces:
  - `ReportGenerator.generate_incident_pdf(df: pd.DataFrame, alerts: list[Alert], incident_id: str, technician_name: str, supervisor_name: str = "Ing. Miguel Angel Mejia Sanchez", filename: str | None = None) -> Path`
  - `NotificationOrchestrator.send_incident_alert(alerts: list[Alert], incident_id: str, technician_name: str, technician_email: str, supervisor_name: str = "Ing. Miguel Angel Mejia Sanchez", pdf_path: str | Path | None = None) -> dict`

- [ ] **Step 1: Write the failing tests in `tests/test_report_generator.py` and `tests/test_notifications.py`**

In `tests/test_report_generator.py`:
```python
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
        df, [alert], incident_id="INC-2026-0001", technician_name="Carlos Reclutador"
    )
    assert html_path.exists()
    assert pdf_path.exists()
    assert inc_path.exists()
    assert inc_path.name == "incident_INC-2026-0001.pdf"
```

In `tests/test_notifications.py`:
```python
def test_incident_email_contains_incident_id_location_and_supervisor_instructions(sample_alerts):
    sample_alerts[0].details = {
        "panel_id": "PNL-B04-12",
        "location_block": "Bloque B - Fila 4 - Posicion 12",
        "latitude": 4.9186,
        "longitude": -73.9982,
    }
    orchestrator = NotificationOrchestrator()
    subject = orchestrator._build_incident_subject("INC-2026-0001", sample_alerts)
    body = orchestrator._build_incident_email_html(
        alerts=sample_alerts,
        incident_id="INC-2026-0001",
        technician_name="Ana Reclutadora",
        supervisor_name="Ing. Miguel Angel Mejia Sanchez",
    )
    assert "[INC-2026-0001]" in subject
    assert "PNL-B04-12" in body
    assert "Bloque B - Fila 4 - Posicion 12" in body
    assert "Ing. Miguel Angel Mejia Sanchez" in body
    assert "preparar" in body.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_generator.py tests/test_notifications.py -v`
Expected: FAIL with missing `generate_incident_pdf` and `_build_incident_subject`

- [ ] **Step 3: Implement `generate_incident_pdf` in `src/report_generator.py` and incident email builders in `src/notifications.py`**

- In `src/report_generator.py`:
  - Ensure `_sanitize_for_pdf` is applied to all dynamic strings in headers, alert tables, and recommendations.
  - Add `generate_incident_pdf(...)` that renders an official **Orden de Trabajo de Emergencia (`incident_<incident_id>.pdf`)** including: Incident ID, Assigned Technician, Supervisor (`Ing. Miguel Ángel Mejía Sánchez`), Panel ID & Physical Location (`Bloque / Fila / Coordenadas GPS`), Technical Diagnosis, and Mandatory Safety Checklist (*1. Preparar EPP dieléctrico y multímetro DC, 2. Reportarse con el supervisor antes de intervenir, 3. Responder al correo de alerta al finalizar*).
- In `src/notifications.py`:
  - Add `_build_incident_subject(self, incident_id: str, alerts: list[Alert]) -> str` returning `f"🔴 [ALERTA CRÍTICA] [{incident_id}] Falla en Planta Solar — Acción Requerida"`.
  - Add `_build_incident_email_html(...)` containing the panel location table, PPE/tools preparation checklist, instruction to coordinate with Supervisor `Ing. Miguel Ángel Mejía Sánchez`, and instruction to **reply directly to this email (`Responder`)** once the emergency is resolved.
  - Add `send_incident_alert(...)` which sends (or simulates if SMTP credentials are not configured) the email to `technician_email` with the PDF attached.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_generator.py tests/test_notifications.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report_generator.py src/notifications.py tests/test_report_generator.py tests/test_notifications.py
git commit -m "feat(reports,notifications): add incident work order PDF and technician alert email with supervisor checklist"
```

---

### Task 4: Build `GoogleSheetsManager` & Provision Live Google Sheet in Drive

**Files:**
- Create: `src/sheets_manager.py`
- Create: `tests/test_sheets_manager.py`

**Interfaces:**
- Produces `GoogleSheetsManager`:
  - `__init__(self, sheet_id_or_url: str | None = None, local_csv_path: str | Path = "sample_data/live_telemetry.csv", credentials_path: str | Path | None = None)`
  - `fetch_telemetry(self) -> pd.DataFrame`: Reads live telemetry from Google Sheets CSV export URL (`https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv`) or `gspread` when configured, falling back to `local_csv_path` if offline.
  - `inject_fault(self, panel_id: str = "PNL-B04-12", v_dc_string_2: float = 175.0, temp_heatsink: float = 88.0, status_code: str = "0x05") -> pd.DataFrame`: Injects a fault into the active telemetry table (updates local CSV and Google Sheet if write access is available).
  - `restore_nominal_values(self) -> pd.DataFrame`: Restores any faulted rows (`status_code != "0x00"`, `temp_heatsink > 75.0`, or large string voltage mismatch) back to nominal values (`v_dc_string_2 = v_dc_string_1`, `temp_heatsink = 48.0`, `status_code = "0x00"`) in both Google Sheets (if connected) and `local_csv_path`.

- [ ] **Step 1: Write the failing tests in `tests/test_sheets_manager.py`**

```python
from src.sheets_manager import GoogleSheetsManager


def test_sheets_manager_local_lifecycle_inject_and_restore(tmp_path):
    csv_path = tmp_path / "live_telemetry.csv"
    mgr = GoogleSheetsManager(local_csv_path=csv_path)
    df_initial = mgr.fetch_telemetry()
    assert not df_initial.empty
    assert (df_initial["status_code"] == "0x00").all()

    # Inject fault
    df_fault = mgr.inject_fault(
        panel_id=df_initial["panel_id"].iloc[-1],
        v_dc_string_2=160.0,
        temp_heatsink=89.0,
        status_code="0x05",
    )
    assert df_fault["v_dc_string_2"].iloc[-1] == 160.0
    assert df_fault["status_code"].iloc[-1] == "0x05"

    # Restore nominal values
    df_restored = mgr.restore_nominal_values()
    assert df_restored["status_code"].iloc[-1] == "0x00"
    assert df_restored["temp_heatsink"].iloc[-1] <= 60.0
    assert abs(df_restored["v_dc_string_1"].iloc[-1] - df_restored["v_dc_string_2"].iloc[-1]) < 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sheets_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.sheets_manager'`

- [ ] **Step 3: Implement `src/sheets_manager.py` and create `sample_data/live_telemetry.csv`**

- Implement `GoogleSheetsManager` in `src/sheets_manager.py` supporting:
  1. Extracting `sheet_id` from a full Google Sheets URL (`https://docs.google.com/spreadsheets/d/<ID>/edit...`) or raw ID.
  2. Reading live data via Google Sheets CSV export URL or `gspread` (when service account / CLI exists) and syncing with `sample_data/live_telemetry.csv` (a clean 20-row active plant telemetry table with 20 distinct panels across Blocks A, B, and C).
  3. Writing back nominal values via `gspread` or `agy` Google Sheets CLI when available, and always updating `local_csv_path`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sheets_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sheets_manager.py sample_data/live_telemetry.csv tests/test_sheets_manager.py
git commit -m "feat(sheets): add GoogleSheetsManager for live telemetry sync and automatic restoration"
```

---

### Task 5: Build `IMAPListener` & `IncidentManager` Closed-Loop State Machine

**Files:**
- Create: `src/imap_listener.py`
- Create: `src/incident_manager.py`
- Create: `tests/test_incident_loop.py`

**Interfaces:**
- `IMAPListener`:
  - `check_for_resolution_reply(self, incident_id: str, technician_email: str) -> dict | None`
  - Static helper `parse_reply_body(raw_body: str) -> str` (strips quoted lines starting with `>` or `On ... wrote:`).
- `IncidentManager`:
  - States: `TechnicianState.AVAILABLE` (`"available"`), `TechnicianState.EMERGENCY_ASSIGNED` (`"emergency_assigned"`), `TechnicianState.RESOLVED` (`"resolved"`).
  - `register_technician(self, name: str, email: str, supervisor: str = "Ing. Miguel Angel Mejia Sanchez") -> None`
  - `evaluate_telemetry(self, df: pd.DataFrame) -> dict`: Runs `AnomalyEngine`, transitions from `AVAILABLE` to `EMERGENCY_ASSIGNED` if critical/warning anomalies exist, generates the work order PDF once, sends the alert email once (`email_sent = True`), and returns current incident state.
  - `process_resolution(self, resolution_note: str, resolved_by: str = "email_reply") -> dict`: Calls `sheets_manager.restore_nominal_values()`, transitions state to `RESOLVED` (and technician back to `AVAILABLE`), records timestamp and note in `incident_history`.

- [ ] **Step 1: Write the failing tests in `tests/test_incident_loop.py`**

```python
from src.incident_manager import IncidentManager, TechnicianState
from src.imap_listener import IMAPListener
from src.sheets_manager import GoogleSheetsManager
from src.transformer import SolarDataTransformer


def test_parse_reply_body_strips_quoted_lines():
    raw = "Ya revisé el panel PNL-B04-12 y cambié el conector MC4.\n\n> El 08/11/2026 escribió:\n> Alerta crítica"
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
    sheets.inject_fault(panel_id="PNL-B04-12", v_dc_string_2=165.0, temp_heatsink=88.0, status_code="0x05")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_incident_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.incident_manager'`

- [ ] **Step 3: Implement `src/imap_listener.py` and `src/incident_manager.py`**

- Implement `IMAPListener` in `src/imap_listener.py` using `imaplib.IMAP4_SSL` and `email.message_from_bytes` to search `UNSEEN` / recent messages matching `incident_id` in `Subject` or `technician_email` in `From`, plus `parse_reply_body`.
- Implement `IncidentManager` in `src/incident_manager.py` wiring `AnomalyEngine`, `ReportGenerator`, `NotificationOrchestrator`, `GoogleSheetsManager`, and `IMAPListener` with deduplicated state transitions and JSON state persistence (`output/noc_state.json`) so state survives Streamlit reruns.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_incident_loop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/imap_listener.py src/incident_manager.py tests/test_incident_loop.py
git commit -m "feat(incident-loop): add IncidentManager state machine and IMAP reply listener"
```

---

### Task 6: Build the Interactive Streamlit NOC Dashboard (`app.py`) & Provision Google Drive Sheet

**Files:**
- Create: `app.py`
- Modify: `requirements.txt`
- Modify: `config.example.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `SolarDataTransformer`, `GoogleSheetsManager`, `IncidentManager`, `IMAPListener`, `ReportGenerator`.
- Produces:
  - Interactive Streamlit web app (`streamlit run app.py`) with:
    1. **Sidebar — Registro de Técnico de Turno (Reclutador):** Inputs for Technician Name, Technician Email, Google Sheet URL/ID (pre-filled with the shared Google Drive Sheet), SMTP/IMAP status indicator, and auto-sync toggle.
    2. **Top Banner — Estado Operativo del Técnico en Tiempo Real:**
       - `🟢 DISPONIBLE — En Espera de Operaciones` (when normal)
       - `🔴 EMERGENCIA ASIGNADA — [INC-XXXX]` (when fault detected in Google Sheet)
       - `✅ INCIDENTE RESUELTO — Sistema Normalizado al 100%` (after technician email reply)
    3. **Panel de Incidente Activo & Mapa de Ubicación del Panel:** Shows the exact faulted panel (`panel_id`, `location_block`, interactive map/scatter of Blocks A/B/C highlighting the broken panel in red), checklist (*"1. Preparar EPP y herramientas, 2. Contactar al Supervisor Ing. Miguel Ángel Mejía Sánchez, 3. Responder al correo de alerta para cerrar el ticket"*), download button for the generated Work Order PDF, and an interview safety-net button (*"📩 Simular Recepción de Respuesta por Correo"* naast live IMAP polling).
    4. **Telemetría en Vivo (Google Sheets) & Curvas Plotly:** Interactive table and Plotly charts of voltage, temperature, irradiance, and PR.

- [ ] **Step 1: Update `requirements.txt` and `config.example.py`**

Add `streamlit>=1.32.0` to `requirements.txt` and add `IMAP_SERVER = "imap.gmail.com"`, `IMAP_PORT = 993`, and `GOOGLE_SHEET_URL` settings to `config.example.py`.

- [ ] **Step 2: Create `app.py` with full NOC UI and closed-loop controls**

Implement `app.py` connecting `GoogleSheetsManager`, `SolarDataTransformer`, `IncidentManager`, and `IMAPListener`. Include a syntax/import smoke test check.

- [ ] **Step 3: Provision a real Google Sheet in the user's Google Drive (if Google Workspace plugin is authenticated) or generate ready-to-share sheet + verify all tests and coverage**

Run:
```bash
python -m pytest tests/ -v --cov=src --cov-report=term-missing
```
Expected: All tests PASS with >80% total coverage across `src/`.

- [ ] **Step 4: Update `README.md` with v3.0 Interactive NOC instructions**

Document the new v3.0 interactive interview flow (`streamlit run app.py`), Google Sheets live link setup, and email reply loop.

- [ ] **Step 5: Commit all changes**

```bash
git add app.py requirements.txt config.example.py README.md docs/superpowers/
git commit -m "feat(noc-dashboard): launch v3.0 interactive Streamlit NOC with Google Sheets and IMAP loop"
```
