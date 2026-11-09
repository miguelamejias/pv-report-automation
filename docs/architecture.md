# System Architecture — `pv-report-automation v3.0`

> Interactive Solar NOC & Closed-Loop Incident Platform

## High-Level Architecture (v3.0 Closed-Loop NOC)

The system combines a **SOLID data-processing pipeline** with a **closed-loop state machine (`IncidentManager`)** and **Streamlit web interface (`app.py`)** that synchronizes bidirectional telemetry and incident history with Google Sheets and Gmail (SMTP/TLS + IMAP/SSL).

```
   ┌──────────────────────────────────────────────────────────────┐
   │        Google Sheets (Drive) / live_telemetry.csv            │
   │  (Panel ID, Block/Row/Pos, GPS Lat/Lon, V_DC, Temp, Status)  │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │             GoogleSheetsManager (src/sheets_manager.py)      │
   │  • Live CSV export fetch + gspread Service Account sync      │
   │  • Fault injection & nominal telemetry restoration           │
   │  • Persistent Incident History (incident_history.csv / Tab)  │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │             SolarDataTransformer (src/transformer.py)        │
   │  • Timestamp parsing (UTC-5) & NaN/negative value cleaning   │
   │  • Panel geolocation preservation & hex status decoding      │
   │  • Derived KPIs: ΔV_DC %, Performance Ratio, Efficiency      │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │               AnomalyEngine (src/anomaly_engine.py)          │
   │  Strategy Pattern (4 Detectors):                             │
   │  ├─ InstantPanelFaultDetector (Panel/Block/GPS fault logic)  │
   │  ├─ IsolationFaultDetector                                   │
   │  ├─ ClippingDetector                                         │
   │  └─ SoilingDetector                                          │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │            IncidentManager (src/incident_manager.py)         │
   │  State Machine: AVAILABLE (🟢) ➔ EMERGENCY (🔴) ➔ RESOLVED   │
   │  • Persistent Reload Deduplication (_find_open_incident)     │
   │  ├─► ReportGenerator.generate_incident_pdf() (Work Order)    │
   │  ├─► NotificationOrchestrator.send_incident_alert() (SMTP)   │
   │  └─◄ IMAPListener.check_for_resolution_reply() (IMAP SSL)    │
   └──────────────────────────────────────────────────────────────┘
```

## Design Principles Applied

### SOLID Principles

| Principle | Application |
|:--|:--|
| **Single Responsibility** | Each module has one responsibility: `transformer` (ETL), `anomaly_engine` (detection), `report_generator` (PDF/HTML), `notifications` (outbound SMTP/Slack), `imap_listener` (inbound IMAP), `sheets_manager` (persistence), `incident_manager` (state machine). |
| **Open/Closed** | New anomaly detectors can be registered in `AnomalyEngine` without modifying existing engine logic. |
| **Liskov Substitution** | All 4 detectors implement the `AnomalyDetector` Protocol (`detect(df) -> list[Alert]`). |
| **Interface Segregation** | `AnomalyDetector` requires only `detect()`. |
| **Dependency Inversion** | `IncidentManager` accepts injectable `GoogleSheetsManager`, `NotificationOrchestrator`, and `IMAPListener` instances. |

### Key Technical Mechanisms in v3.0

1. **Persistent Reload Deduplication (`IncidentManager._find_open_incident_in_history`):**
   Streamlit re-runs `app.py` on user interactions and creates a fresh session on full browser reloads (`F5`). Before generating a new incident ID or sending an email, `IncidentManager` checks both in-memory state and `sample_data/incident_history.csv` for an existing record in state `EN EMERGENCIA ASIGNADA`. If found, it restores the active incident without re-sending any email.
2. **Closed-Loop Resolution via Email Reply (`IMAPListener`):**
   Searches `INBOX` over `IMAP4_SSL` (`imap.gmail.com:993`) for unseen or recent replies matching `[INC-XXXX]`, strips quoted reply history, restores healthy panel parameters in `GoogleSheetsManager`, and updates the incident record from `EN EMERGENCIA ASIGNADA` to `RESUELTO`.
3. **Aerial + GPS Plant Layout (`app.py`):**
   Combines a top panoramic aerial reference banner (`assets/solar_plant_banner.jpg`) with an interactive Plotly scatter map overlaid on `assets/solar_plant_aerial.jpg`, followed by a single full-width editable telemetry table and real-time incident history table.
