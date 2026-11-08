# Design Spec: pv-report-automation v3.0 — Interactive Solar NOC & Closed-Loop Incident Platform

**Date:** 2026-11-08  
**Author:** Miguel Ángel Mejía Sánchez  
**Status:** Draft for Approval

---

## 1. Intent & Why

Transform `pv-report-automation` from a CLI-only batch script (v2.0) into an **interactive, closed-loop Solar Network Operations Center (NOC) web platform (v3.0)** designed for live technical interviews.

During an interview, a senior recruiter can register as the **On-Duty Field Technician** with their own email address, edit a shared **Google Sheet** in Google Drive to simulate a real hardware failure on a specific solar panel/string, immediately see the web platform transition into an emergency state with location mapping and an executive PDF report, receive a real alert email on their phone/inbox instructing them to prepare tools/PPE and coordinate with their supervisor, and **reply directly to that email** to resolve the emergency — which automatically restores the Google Sheet telemetry and returns the web platform to `100% OPERATIONAL`.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
1. **Recruiter Onboarding (Technician Registration):** Allow a user on the web platform to register their name and email address as the active On-Duty Technician (`🟢 DISPONIBLE`).
2. **Live Google Sheets Telemetry & Location Sync:** Connect to a Google Sheet shared via Google Drive containing panel/string telemetry plus physical location metadata (`panel_id`, `block`, `row`, `string_id`, `lat`, `lon`).
3. **Accurate Anomaly Detection (Bug Fixes from v2.0):** Fix `SoilingDetector`, `ClippingDetector`, and `IsolationFaultDetector` + add single-row/instantaneous fault detection so a single edit in Google Sheets immediately triggers an incident with physical location details.
4. **Real-Time Technician Web Dashboard (Streamlit):**
   - Display technician status (`🟢 DISPONIBLE — En Planta` vs `🔴 EMERGENCIA ASIGNADA — En Atención`).
   - Show the affected panel's exact location on a plant map / block grid and telemetry charts (Plotly).
   - Generate and offer one-click download of the formal Incident Report PDF (`FPDF2`).
5. **Outbound Alert Email (SMTP/TLS):** Automatically send a rich HTML email (with the Incident PDF attached and a unique `[INC-XXXX]` tag in the subject) to the registered technician's email, instructing them to prepare PPE/tools, contact their supervisor (Miguel Ángel Mejía Sánchez), and **reply to the email** once the fault is repaired.
6. **Inbound Email Resolution Loop (IMAP SSL):** Poll the IMAP inbox for a reply (`Re: ... [INC-XXXX]`) from the technician. Upon receipt:
   - Parse the technician's resolution notes from the email body.
   - Automatically restore the affected row(s) in the Google Sheet back to nominal values (and `status_code = 0x00`).
   - Send a closure confirmation email to the supervisor/technician.
   - Transition the web dashboard back to `🟢 SISTEMA NORMALIZADO — Operación al 100%`.

### Non-Goals
- Multi-tenant authentication, RBAC, or persistent user accounts in a relational database (session/JSON state is sufficient for single-plant NOC and live demos).
- Replacing Python with a separate JS/React frontend.

### Anti-Goals (What Would Make This a Failure)
- **Demo fragility:** Requiring external tunnels (`ngrok`) or failing completely if Google API credentials or IMAP are temporarily unreachable during a live interview. Every external integration must have a seamless local fallback / one-click simulation button on the dashboard as a safety net.
- **Spamming the recruiter's inbox:** Sending duplicate emails on every Streamlit rerun for the same incident. Incident deduplication (`incident_id` state machine) is mandatory.

---

## 3. Constraints

- **Tech Stack:** Python 3.9+, `streamlit`, `pandas`, `numpy`, `plotly`, `fpdf2`, `gspread` / `google-auth` (with public CSV + Service Account write support), standard library `smtplib`, `imaplib`, `email`.
- **Testing:** Maintain `pytest` suite passing 100% with unit tests covering the new Google Sheets sync, incident state machine, IMAP parser, and report generator (>80% total coverage).
- **Security:** Credentials (`SMTP`, `IMAP`, Google Service Account JSON) loaded from `.env` / `config.py` or Streamlit `st.secrets`, never committed to Git.

---

## 4. Approaches Considered

| Approach | Summary | Trade-offs | Decision |
|:--|:--|:--|:--|
| **Option 1: Streamlit Full-Stack + Google Sheets Sync + IMAP Listener** | 100% Python web app using `streamlit` with modular services (`sheets_manager.py`, `imap_listener.py`, `incident_manager.py`). | **Pros:** Pure Python, zero-tunnel local & cloud execution, fast development, reuses 100% of v2.0 SOLID classes.<br>**Cons:** UI bound to Streamlit layout primitives (mitigated via custom CSS). | **Selected** — Best reliability and fit for a Python Engineer portfolio. |
| **Option 2: FastAPI + HTML/Tailwind/JS** | Separate REST/WebSocket API and custom JS SPA. | **Pros:** Full UI freedom.<br>**Cons:** Splits repo across two languages, doubles maintenance. | Rejected. |
| **Option 3: Google Apps Script Webhook + FastAPI** | Push webhook from Google Sheets `onEdit` to backend. | **Pros:** Sub-second push.<br>**Cons:** Fails on `localhost` without `ngrok` tunnel. | Rejected due to interview demo risk. |

---

## 5. System Architecture & Roadmap

### 5.1 Extended Data Schema (Google Sheets & CSV)
To support physical panel location tracking, the telemetry schema adds optional/enriched location columns (backward-compatible with v2.0 CSVs via defaults in `SolarDataTransformer`):

| Column | Example | Purpose |
|:--|:--|:--|
| `timestamp` | `2024-03-17T12:00:00-05:00` | Reading timestamp |
| `panel_id` | `PNL-B04-12` | Unique solar panel / string identifier |
| `location_block` | `Bloque B - Fila 4 - Posición 12` | Human-readable plant location for technician |
| `latitude` | `4.9186` | GPS Latitude (Planta Sabana Norte, Colombia) |
| `longitude` | `-73.9982` | GPS Longitude |
| `v_dc_string_1` | `395.0` | String 1 Voltage ($V_{DC}$) |
| `v_dc_string_2` | `210.0` | String 2 Voltage ($V_{DC}$) — *Editable in Sheets to trigger fault* |
| `i_dc_total` | `24.5` | Total DC Current ($A_{DC}$) |
| `p_ac_output` | `5100.0` | AC Active Power ($W$) |
| `temp_heatsink` | `58.2` | Inverter Heatsink Temperature (°C) |
| `irradiance_poa` | `890.0` | Plane of Array Irradiance ($W/m^2$) |
| `status_code` | `0x05` | Hex Hardware Status (`0x00` = OK, `0x05` = Isolation Fault) |

### 5.2 Incident State Machine (`src/incident_manager.py`)
To prevent duplicate alert emails while Streamlit auto-refreshes:
- **`IDLE` (`🟢 DISPONIBLE`):** No active anomalies. Technician is on standby.
- **`ACTIVE_ALERT` (`🔴 EMERGENCIA ASIGNADA`):**
  - Triggered when `AnomalyEngine` detects a fault in the latest Google Sheet sync.
  - Generates a deterministic/unique `incident_id` (e.g., `INC-2026-0841`), creates `output/incident_INC-2026-0841.pdf`, and sends **one** email to the registered technician (`email_sent = True`).
  - Stores the snapshot of affected rows and nominal baseline values.
- **`RESOLVED` (`🟢 SISTEMA NORMALIZADO`):**
  - Triggered when `IMAPListener` detects a reply email containing `[INC-XXXX]` in the subject (or from the registered technician's email).
  - Calls `GoogleSheetsManager.restore_nominal_values()` to fix the broken row(s) in Google Sheets.
  - Sends closure summary email to supervisor & technician.
  - Resets technician status to `🟢 DISPONIBLE` and displays the resolution audit log.

### 5.3 New & Refactored Modules (Roadmap)

```
pv-report-automation/
├── app.py                        # NEW: Streamlit NOC Interactive Web Platform
├── main.py                       # CLI entry point (kept working for batch/Docker)
├── src/
│   ├── __init__.py               # Bump to v3.0.0
│   ├── transformer.py            # REFACTOR: Add location columns + defaults
│   ├── anomaly_engine.py         # REFACTOR: Fix Soiling/Clipping + add Instant Hardware/Voltage/Temp fault rules with panel location
│   ├── report_generator.py       # REFACTOR: Add Incident Work Order PDF with panel location & supervisor instructions
│   ├── notifications.py          # REFACTOR: Add Incident Alert Email ([INC-XXXX]) with supervisor/PPE checklist
│   ├── sheets_manager.py         # NEW: Google Sheets live reader & nominal value restorer (with local CSV fallback)
│   ├── imap_listener.py          # NEW: IMAP SSL inbox poller for technician reply detection
│   └── incident_manager.py       # NEW: Closed-loop state machine (IDLE -> ACTIVE_ALERT -> RESOLVED)
└── tests/
    ├── test_transformer.py
    ├── test_anomaly_engine.py
    ├── test_notifications.py
    ├── test_report_generator.py  # NEW: Bring report_generator coverage >85%
    └── test_incident_loop.py     # NEW: End-to-end tests for Sheets -> Alert -> IMAP Reply -> Restore
```

### 5.4 What's Left to the Builder (Engineer Calls)
- **Polling Interval:** Streamlit auto-refresh set to configurable `5–10 seconds` when monitoring is active, plus a manual *"🔄 Sincronizar Ahora"* button for instant reaction during demos.
- **Google Sheets Authentication:** Support both `gspread` with Service Account JSON (for read + automatic write-back restoration) AND public Google Sheet URL reading, plus creating the live template in Google Drive.
- **IMAP Filtering:** Match incoming emails either by `[INC-XXXX]` in Subject OR `From: <registered_technician_email>` received after `incident.created_at` (handles email clients that alter subjects).
