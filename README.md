<div align="center">

# ⚡ pv-report-automation

**Solar Plant Maintenance Intelligence Suite**

*Automatización de reportes de mantenimiento para sistemas fotovoltaicos.*

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](Dockerfile)
[![Code Style](https://img.shields.io/badge/Code%20Style-PEP8-000000?style=for-the-badge)](https://peps.python.org/pep-0008/)

Script en Python que procesa logs de rendimiento de inversores solares, detecta anomalías mediante reglas de negocio industriales, genera reportes ejecutivos (PDF + HTML interactivo) y envía alertas automáticas multi-canal (Email + Slack).

**Actualizado con IA** para mejorar código, modularidad y funcionalidad.

[Instalación](#-instalación) •
[Uso](#-uso-rápido) •
[Arquitectura](#-arquitectura) •
[Documentación](#-documentación)

</div>

---

## 💡 Impacto en Operaciones — ENERTEC LATINOAMÉRICA

> Este no es un proyecto académico. Es una herramienta que nació de **9 años de experiencia real** en soporte técnico y mantenimiento de plantas solares.

| Métrica | Resultado |
|:--|:--|
| **Optimización del MTTR** | Reducción del tiempo promedio de reparación en un **40%** al identificar la causa raíz (sombreado vs. falla de hardware) antes de enviar a la cuadrilla técnica. |
| **Eficiencia Operativa** | Automatización del proceso de consolidación de logs de 15 plantas solares, pasando de **4 horas de trabajo manual a 45 segundos** de procesamiento automatizado. |
| **Disponibilidad del Sistema** | Mejora de la disponibilidad global de energía en un **12%** mediante la detección temprana de micro-cortes en inversores de cadena. |

---

## 🤖 Actualizado con IA — Historia de Evolución

Este repositorio es la **versión 2.0** de un script que usaba diariamente en **ENERTEC LATINOAMÉRICA** para procesar logs de inversores. La versión original era un script monolítico de ~200 líneas que:

- Leía un CSV con `pandas`
- Calculaba promedios básicos
- Imprimía resultados en consola

**Con asistencia de IA, se transformó en:**

| Aspecto | v1.0 (Original) | v2.0 (Con IA) |
|:--|:--|:--|
| Arquitectura | Script monolítico | POO con SOLID + Strategy Pattern |
| Anomalías | Límites hardcodeados | 3 detectores especializados con métricas industriales |
| Reportes | `print()` en consola | PDF ejecutivo + HTML interactivo (Plotly) |
| Alertas | Ninguna | Multi-canal (Email SMTP/TLS + Slack Webhook) |
| Testing | Ninguno | pytest con cobertura (12 tests) |
| CI/CD | Ninguno | GitHub Actions automático |
| Despliegue | `python script.py` | Docker con HEALTHCHECK |
| Documentación | Ninguna | README, arquitectura, diagramas de flujo |

> La IA no reemplaza la experiencia de campo — la amplifica. Cada regla de negocio (soiling, clipping, isolation fault) viene de situaciones reales que viví como técnico.

---

## 📊 ¿Qué Detecta?

### 1. Soiling (Suciedad en Paneles)
Detecta caída progresiva del **Performance Ratio** (>1%/día durante 5 días consecutivos). Evita enviar cuadrillas innecesariamente — solo cuando el patrón confirma suciedad real.

### 2. Inverter Clipping
Identifica cuando la potencia AC se mantiene plana mientras la irradiación sigue subiendo. Señal de que el inversor alcanzó su límite térmico o de diseño.

### 3. Isolation Fault (Falla de Aislamiento)
Si el voltaje DC entre strings difiere más del **15%** por más de 15 minutos, se dispara alerta **CRÍTICA** de revisión de cableado y conectores MC4.

---

## 📁 Estructura del Proyecto

```
pv-report-automation/
├── .github/
│   └── workflows/
│       └── ci.yml                 # CI/CD con GitHub Actions
├── src/
│   ├── __init__.py                # Metadata del paquete
│   ├── transformer.py             # SolarDataTransformer (ETL)
│   ├── anomaly_engine.py          # AnomalyEngine + Strategy Pattern
│   ├── report_generator.py        # PDF (FPDF2) + HTML (Plotly)
│   └── notifications.py           # Email SMTP/TLS + Slack Webhook
├── tests/
│   ├── test_transformer.py        # Tests ETL (12 casos)
│   ├── test_anomaly_engine.py     # Tests detección (8 casos)
│   └── test_notifications.py      # Tests notificaciones (10 casos)
├── sample_data/
│   └── plant_log_2024.csv         # 399 registros realistas con anomalías
├── docs/
│   ├── architecture.md            # Arquitectura SOLID + patrones
│   └── flowchart.md               # Diagramas de flujo (Mermaid)
├── output/                        # Reportes generados (gitignored)
├── main.py                        # Punto de entrada CLI
├── config.example.py              # Template de credenciales
├── generate_sample_data.py        # Generador de datos de prueba
├── requirements.txt               # Dependencias Python
├── Dockerfile                     # Contenedor Docker listo
├── .gitignore
├── LICENSE                        # MIT
└── README.md
```

---

## 🚀 Instalación

### Requisitos Previos
- Python 3.9 o superior
- pip (gestor de paquetes)

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/pv-report-automation.git
cd pv-report-automation

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. (Opcional) Configurar credenciales para alertas reales
cp config.example.py config.py
# Editar config.py con tus credenciales SMTP y Slack
```

### Docker

```bash
# Construir la imagen
docker build -t pv-report-automation .

# Ejecutar con volumen para obtener los reportes
docker run --rm -v $(pwd)/output:/app/output pv-report-automation
```

---

## ⚡ Uso Rápido

### Procesamiento básico (modo simulación)

```bash
python main.py
```

### Con archivo personalizado

```bash
python main.py --input data/mi_planta.csv --plant "Solar Bogotá Norte" --power 15.0
```

### Con notificaciones reales (requiere config.py)

```bash
python main.py --input data/mi_planta.csv --notify
```

### Opciones disponibles

```
--input    Ruta al archivo CSV (default: sample_data/plant_log_2024.csv)
--output   Directorio de reportes (default: output/)
--plant    Nombre de la planta (default: ENERTEC Solar Plant)
--power    Capacidad nominal en kW (default: 10.0)
--notify   Activar notificaciones reales (Email + Slack)
--verbose  Logging detallado (debug)
```

---

## 📄 Ejemplo de Output

### Ejecución de consola

```
============================================================
  ⚡ pv-report-automation v2.0.0
  Solar Plant Maintenance Intelligence Suite
  ENERTEC LATINOAMÉRICA
============================================================

  ✅ Loaded 399 records from sample_data/plant_log_2024.csv

  🔍 Anomaly Engine: 3 detectors registered
  ⚠️  Alerts found: 2
     🔴 [CRITICAL] Isolation Fault: String voltage mismatch detected...
     🟡 [WARNING] Soiling Detection: Performance Ratio has declined...

  📊 Summary Statistics:
     Energy Generated : 187.43 kWh
     CO₂ Avoided      : 23.62 kg
     Avg PR           : 79.3%
     Peak Power       : 9214.0 W
     Max Temperature  : 52.8°C

  📄 HTML Report: output/report.html
  📄 PDF Report:  output/report.pdf

============================================================
  ✅ Pipeline complete!
============================================================
```

### Email de Alerta Simulada

```
============================================================
⚡ SIMULATED ALERT DISPATCH — pv-report-automation v2.0
============================================================

  Alert #1
  🔴 Severity : CRITICAL
  📋 Rule     : Isolation Fault
  💬 Message  : String voltage mismatch detected: avg ΔV = 25.1%
                (threshold: 15.0%) for 180 minutes.
                Immediate wiring inspection required.
  🕐 Start    : 2024-03-16 10:00:00-05:00
  🕐 End      : 2024-03-16 13:00:00-05:00

  Alert #2
  🟡 Severity : WARNING
  📋 Rule     : Soiling Detection
  💬 Message  : Performance Ratio has declined for 5 consecutive
                days (avg drop: -1.15%/day).
                Panel cleaning is recommended.
  🕐 Start    : 2024-03-13 00:00:00
  🕐 End      : 2024-03-17 00:00:00

  Total Alerts: 2
  Channels: Slack ✅ | Email ✅ (simulated)

============================================================
```

---

## 🧪 Testing

```bash
# Ejecutar todos los tests
pytest tests/ -v

# Con reporte de cobertura
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## 🏗️ Arquitectura

El sistema implementa principios **SOLID** y patrones de diseño **GoF**:

```
main.py (Orchestration)
  │
  ├── SolarDataTransformer      Pipeline    ETL → Clean DataFrame
  │
  ├── AnomalyEngine             Strategy    3 detectores intercambiables
  │   ├── SoilingDetector
  │   ├── ClippingDetector
  │   └── IsolationFaultDetector
  │
  ├── ReportGenerator           Builder     PDF + HTML reports
  │
  └── NotificationOrchestrator  Mediator    Email + Slack routing
```

Documentación completa en [`docs/architecture.md`](docs/architecture.md) y [`docs/flowchart.md`](docs/flowchart.md).

---

## 📚 Documentación

| Documento | Descripción |
|:--|:--|
| [`docs/architecture.md`](docs/architecture.md) | Arquitectura SOLID, patrones de diseño, decisiones técnicas |
| [`docs/flowchart.md`](docs/flowchart.md) | Diagramas de flujo del pipeline (Mermaid) |
| [`config.example.py`](config.example.py) | Template de configuración de credenciales |

---

## 🛠️ Stack Tecnológico

| Herramienta | Uso |
|:--|:--|
| **Python 3.9+** | Lenguaje principal |
| **Pandas** | Procesamiento y análisis de datos |
| **NumPy** | Operaciones numéricas |
| **Plotly** | Gráficos interactivos HTML |
| **FPDF2** | Generación de reportes PDF |
| **pytest** | Testing automatizado |
| **Docker** | Contenedorización |
| **GitHub Actions** | CI/CD automatizado |

---

## 🤔 ¿Por Qué Este Proyecto Importa?

1. **Problema real:** No es un TODO app o un proyecto de tutorial. Es una herramienta que resolvía un problema diario en una empresa de energía solar.

2. **Código de producción:** POO con SOLID, testing, CI/CD, Docker. No es un notebook de Jupyter — es software mantenible.

3. **Impacto medible:** 4 horas → 45 segundos. 40% menos en MTTR. 12% más de disponibilidad.

4. **Evolución visible:** La historia de v1.0 a v2.0 demuestra capacidad de aprendizaje continuo y adopción de mejores prácticas.

5. **Conocimiento de dominio:** Las reglas de negocio (PR, soiling, clipping, isolation fault) demuestran experiencia real en energía solar, no solo habilidad en programación.

---

## 📫 Contacto

**Miguel Ángel Mejía Sánchez**
- Profesional IT | 9 años de experiencia
- Soporte técnico & Automatización | ENERTEC LATINOAMÉRICA
- Colombia 🇨🇴

---

<div align="center">

*Hecho con ☀️ por alguien que sabe que un panel sucio no genera lo mismo que uno limpio.*

</div>
