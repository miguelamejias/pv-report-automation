# System Architecture — `pv-report-automation`

> Solar Plant Maintenance Intelligence Suite

## High-Level Architecture

This system follows a **pipeline architecture** where data flows sequentially through specialized components. Each component is a standalone Python class following SOLID principles, making the system easily testable and extensible.

```
                    ┌──────────────────────────────────┐
                    │         CSV Log Files             │
                    │   (Inverter Data Loggers)         │
                    └──────────────┬───────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────────┐
                    │     SolarDataTransformer          │
                    │     ─────────────────────         │
                    │  • Parse timestamps (UTC-5)       │
                    │  • Clean NaN / negative values    │
                    │  • Decode hex status codes        │
                    │  • Compute: ΔV, PR, efficiency    │
                    └──────────────┬───────────────────┘
                                   │
                              pd.DataFrame
                                   │
                                   ▼
                    ┌──────────────────────────────────┐
                    │         AnomalyEngine             │
                    │     ─────────────────────         │
                    │  Strategy Pattern (GoF):          │
                    │  ├─ SoilingDetector               │
                    │  ├─ ClippingDetector              │
                    │  └─ IsolationFaultDetector        │
                    └──────────────┬───────────────────┘
                                   │
                           list[Alert]
                                   │
                        ┌──────────┴──────────┐
                        │                     │
                        ▼                     ▼
         ┌─────────────────────┐  ┌──────────────────────┐
         │   ReportGenerator   │  │NotificationOrchestrator│
         │   ───────────────   │  │────────────────────── │
         │  • PDF (FPDF2)      │  │ Routing by severity:  │
         │  • HTML (Plotly)    │  │ ├─ CRITICAL → Email+  │
         │  • Summary stats    │  │ │              Slack   │
         │  • CO₂ calculation  │  │ ├─ WARNING → Both     │
         └─────────┬───────────┘  │ └─ INFO → Slack only  │
                   │              └──────────────────────┘
                   ▼
         ┌─────────────────────┐
         │   output/           │
         │   ├─ report.pdf     │
         │   └─ report.html    │
         └─────────────────────┘
```

## Design Principles Applied

### SOLID Principles

| Principle | Application |
|:--|:--|
| **Single Responsibility** | Each class has one job: transform, detect, report, or notify. |
| **Open/Closed** | New anomaly detectors can be added without modifying `AnomalyEngine`. |
| **Liskov Substitution** | All detectors implement the `AnomalyDetector` Protocol. |
| **Interface Segregation** | `AnomalyDetector` defines only the `detect()` method — nothing more. |
| **Dependency Inversion** | `AnomalyEngine` depends on the `AnomalyDetector` abstraction, not concrete classes. |

### Design Patterns

| Pattern | Where Used | Why |
|:--|:--|:--|
| **Strategy** | `AnomalyEngine` + detectors | Swap detection rules at runtime without touching the engine. |
| **Factory Method** | `AnomalyEngine.create_default()` | Pre-configure the engine with all built-in detectors. |
| **Mediator** | `NotificationOrchestrator` | Centralizes routing decisions between Email and Slack channels. |
| **Pipeline** | `SolarDataTransformer` method chain | Data flows through sequential transformation steps. |

## Module Dependency Map

```
main.py
  ├── src/transformer.py        (pandas, numpy)
  ├── src/anomaly_engine.py      (pandas, numpy)
  ├── src/report_generator.py   (plotly, fpdf2, pandas)
  └── src/notifications.py      (smtplib, ssl, json, urllib)
```

## Key Technical Decisions

1. **Why Protocol over ABC?**
   Python's `Protocol` (PEP 544) enables structural typing — any class with a `detect()` method works, without explicit inheritance.  This is more Pythonic and flexible.

2. **Why FPDF2 over ReportLab?**
   FPDF2 is lightweight (no C dependencies), simpler API, and sufficient for our use case.  ReportLab is heavier and better suited for complex typesetting.

3. **Why Plotly over Matplotlib?**
   Plotly generates self-contained HTML files with interactive zoom, hover, and pan. Recruiters can open the report in any browser without installing Python.

4. **Why not a database?**
   CSV is the universal format exported by inverter data loggers (SMA, Huawei, Fronius). Using CSV keeps the system compatible with real field equipment.
