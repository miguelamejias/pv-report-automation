# -*- coding: utf-8 -*-
"""
pv-report-automation v3.0 — Interactive Solar NOC & Technician Platform
=======================================================================

Streamlit web application for live technical interviews and Solar NOC
operations. Connects a shared Google Sheet (telemetry + panel location)
with real-time anomaly detection, PDF work-order generation, outbound
SMTP technician alerts, and inbound IMAP email reply resolution.

Run with:
    streamlit run app.py

Author: Miguel Ángel Mejía Sánchez | ENERTEC LATINOAMÉRICA
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import __version__
from src.imap_listener import IMAPConfig, IMAPListener
from src.incident_manager import IncidentManager, TechnicianState
from src.notifications import EmailConfig, NotificationOrchestrator
from src.sheets_manager import GoogleSheetsManager
from src.transformer import SolarDataTransformer


def load_optional_config() -> dict:
    """Load credentials from config.py if present, otherwise return defaults."""
    cfg = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "sender_email": "",
        "sender_password": "",
        "google_sheet_url": "",
        "service_account_json": "",
    }
    try:
        import config  # type: ignore

        cfg["smtp_server"] = getattr(config, "SMTP_SERVER", cfg["smtp_server"])
        cfg["smtp_port"] = getattr(config, "SMTP_PORT", cfg["smtp_port"])
        cfg["imap_server"] = getattr(config, "IMAP_SERVER", cfg["imap_server"])
        cfg["imap_port"] = getattr(config, "IMAP_PORT", cfg["imap_port"])
        sender = getattr(config, "SENDER_EMAIL", "")
        pwd = getattr(config, "SENDER_PASSWORD", "")
        if sender and "your_email" not in sender:
            cfg["sender_email"] = sender
        if pwd and "your_app" not in pwd:
            cfg["sender_password"] = pwd
        cfg["google_sheet_url"] = getattr(config, "GOOGLE_SHEET_URL", "")
        cfg["service_account_json"] = getattr(config, "GOOGLE_SERVICE_ACCOUNT_JSON", "")
    except ImportError:
        pass
    return cfg


def build_plant_layout_figure(df: pd.DataFrame) -> go.Figure:
    """Build an interactive Plotly map of solar panels by block and GPS coordinates."""
    latest_per_panel = df.groupby("panel_id", as_index=False).last()

    colors = []
    sizes = []
    statuses = []
    for _, row in latest_per_panel.iterrows():
        is_fault = (
            float(row.get("delta_v_dc_pct", 0.0)) > 15.0
            or float(row.get("temp_heatsink", 0.0)) > 75.0
            or str(row.get("status_code", "0x00")).lower() != "0x00"
        )
        if is_fault:
            colors.append("#E74C3C")
            sizes.append(22)
            statuses.append("🔴 FALLA CRÍTICA")
        else:
            colors.append("#2ECC71")
            sizes.append(14)
            statuses.append("🟢 OPERATIVO")

    latest_per_panel["estado_visual"] = statuses

    fig = go.Figure(
        data=go.Scatter(
            x=latest_per_panel["longitude"],
            y=latest_per_panel["latitude"],
            mode="markers+text",
            text=latest_per_panel["panel_id"],
            textposition="top center",
            marker=dict(
                size=sizes,
                color=colors,
                line=dict(width=2, color="#FFFFFF"),
            ),
            customdata=latest_per_panel[
                [
                    "location_block",
                    "v_dc_string_1",
                    "v_dc_string_2",
                    "temp_heatsink",
                    "status_code",
                    "estado_visual",
                ]
            ].values,
            hovertemplate=(
                "<b>%{text}</b> (%{customdata[5]})<br>"
                "Ubicación: %{customdata[0]}<br>"
                "V String 1: %{customdata[1]:.1f} V | V String 2: %{customdata[2]:.1f} V<br>"
                "Temp Disipador: %{customdata[3]:.1f} °C | Estado: %{customdata[4]}<br>"
                "GPS: (%{y:.4f}, %{x:.4f})<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title="🗺️ Mapa Físico de Paneles Solares — Planta Sabana Norte (GPS)",
        xaxis_title="Longitud (Oeste)",
        yaxis_title="Latitud (Norte)",
        template="plotly_dark",
        height=390,
        margin=dict(l=20, r=20, t=45, b=20),
    )
    return fig


def init_session_state() -> None:
    """Initialize persistent objects in Streamlit session state."""
    if "cfg" not in st.session_state:
        st.session_state.cfg = load_optional_config()

    if "sheets_manager" not in st.session_state:
        st.session_state.sheets_manager = GoogleSheetsManager(
            sheet_id_or_url=st.session_state.cfg["google_sheet_url"],
            local_csv_path="sample_data/live_telemetry.csv",
            credentials_path=st.session_state.cfg["service_account_json"] or None,
        )

    if "incident_manager" not in st.session_state:
        st.session_state.incident_manager = IncidentManager(
            sheets_manager=st.session_state.sheets_manager,
            output_dir="output",
        )


def main() -> None:
    st.set_page_config(
        page_title="ENERTEC Solar NOC v3.0 — Plataforma de Técnico en Turno",
        page_icon="⚡",
        layout="wide",
    )
    init_session_state()

    sheets_mgr: GoogleSheetsManager = st.session_state.sheets_manager
    inc_mgr: IncidentManager = st.session_state.incident_manager
    transformer = SolarDataTransformer()

    # ------------------------------------------------------------------
    # Sidebar: Recruiter Onboarding & Google Sheets / Email Connection
    # ------------------------------------------------------------------
    with st.sidebar:
        st.markdown("## 👷 Registro de Técnico en Turno")
        st.caption(
            "Regístrese con su correo real para recibir alertas de fallas desde Google Sheets y cerrar incidentes respondiendo el correo."
        )

        tech_name = st.text_input(
            "Nombre del Técnico (Reclutador)",
            value=inc_mgr.technician_name
            if inc_mgr.technician_name != "Técnico en Turno"
            else "Ing. Reclutador Invitado",
        )
        tech_email = st.text_input(
            "Correo Electrónico (Para recibir alerta)",
            value=inc_mgr.technician_email,
            placeholder="reclutador@empresa.com",
        )
        sup_name = st.text_input(
            "Supervisor Asignado",
            value=inc_mgr.supervisor_name,
        )

        if st.button("✅ Registrar / Actualizar Técnico", use_container_width=True):
            inc_mgr.register_technician(tech_name, tech_email, sup_name)
            st.success(f"Técnico activo: {inc_mgr.technician_name}")

        # Keep technician info synced cleanly
        inc_mgr.register_technician(tech_name, tech_email, sup_name)

        st.divider()
        st.markdown("## 📊 Conexión Google Sheets (Drive)")
        sheet_url_input = st.text_input(
            "URL o ID del Google Sheet compartido",
            value=sheets_mgr.share_url or st.session_state.cfg["google_sheet_url"],
            placeholder="https://docs.google.com/spreadsheets/d/...",
        )
        if sheet_url_input != sheets_mgr.share_url:
            sheets_mgr.sheet_id = GoogleSheetsManager.extract_sheet_id(sheet_url_input)

        if sheets_mgr.sheet_id:
            st.markdown(f"🔗 [Abrir Google Sheet en Vivo]({sheets_mgr.share_url})")

        with open(sheets_mgr.local_csv_path, "rb") as f_csv:
            st.download_button(
                "📥 Descargar Plantilla CSV para Drive",
                data=f_csv.read(),
                file_name="enertec_telemetria_vivo.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.divider()
        with st.expander("✉️ Configurar Correo Real (SMTP / IMAP)", expanded=False):
            sender_email = st.text_input(
                "Correo Emisor NOC (Gmail)",
                value=st.session_state.cfg["sender_email"],
                placeholder="tu_correo@gmail.com",
            )
            sender_pwd = st.text_input(
                "App Password (16 caracteres)",
                value=st.session_state.cfg["sender_password"],
                type="password",
            )
            if sender_email and sender_pwd:
                inc_mgr.orchestrator.email_config = EmailConfig(
                    smtp_server=st.session_state.cfg["smtp_server"],
                    smtp_port=int(st.session_state.cfg["smtp_port"]),
                    sender_email=sender_email,
                    sender_password=sender_pwd,
                    recipients=[tech_email] if tech_email else [sender_email],
                )
                inc_mgr.imap_listener.config = IMAPConfig(
                    imap_server=st.session_state.cfg["imap_server"],
                    imap_port=int(st.session_state.cfg["imap_port"]),
                    email_address=sender_email,
                    password=sender_pwd,
                )
                st.caption("🟢 SMTP/TLS e IMAP/SSL activos.")
            else:
                st.caption("🟡 Modo Simulación Activo (ingresa App Password para envío real).")

    # ------------------------------------------------------------------
    # Load & Evaluate Current Telemetry
    # ------------------------------------------------------------------
    raw_df = sheets_mgr.fetch_telemetry()
    df = transformer.transform_dataframe(raw_df)

    # Check IMAP if an emergency is currently active
    if inc_mgr.state == TechnicianState.EMERGENCY_ASSIGNED:
        inc_mgr.poll_imap_for_resolution()
        raw_df = sheets_mgr.fetch_telemetry()
        df = transformer.transform_dataframe(raw_df)

    snapshot = inc_mgr.evaluate_telemetry(df)

    # ------------------------------------------------------------------
    # Header & Live Status Banner
    # ------------------------------------------------------------------
    st.title(f"⚡ ENERTEC Solar NOC v{__version__} — Centro de Control e Incidentes")
    st.markdown(
        f"**Técnico en Turno:** `{inc_mgr.technician_name}` "
        f"({inc_mgr.technician_email or 'Sin correo registrado'}) | "
        f"**Supervisor:** `{inc_mgr.supervisor_name}`"
    )

    if snapshot["state"] == TechnicianState.EMERGENCY_ASSIGNED:
        panel = snapshot["affected_panel"] or {}
        st.error(
            f"🔴 **ESTADO DEL TÉCNICO: EN EMERGENCIA ASIGNADA [{snapshot['incident_id']}]** — "
            f"Falla detectada en **{panel.get('panel_id', 'PNL-B04-12')}** "
            f"({panel.get('location_block', 'Bloque B')}). "
            f"Prepare herramientas/EPP, comuníquese con su supervisor ({inc_mgr.supervisor_name}) "
            f"y responda el correo de alerta para normalizar la planta."
        )
    elif inc_mgr.incident_history:
        last_inc = inc_mgr.incident_history[0]
        st.success(
            f"🟢 **ESTADO DEL TÉCNICO: DISPONIBLE — SISTEMA NORMALIZADO AL 100%** | "
            f"Último incidente `{last_inc['incident_id']}` en `{last_inc['panel_id']}` "
            f"cerrado exitosamente ({last_inc['resolved_at']}): *\"{last_inc['resolution_note']}\"*"
        )
    else:
        st.success(
            "🟢 **ESTADO DEL TÉCNICO: DISPONIBLE — PLANTA OPERANDO AL 100%** | "
            "Todos los strings fotovoltaicos se encuentran dentro de parámetros nominales."
        )

    # ------------------------------------------------------------------
    # Quick Action Bar for Live Recruiter Demo
    # ------------------------------------------------------------------
    col_act1, col_act2, col_act3 = st.columns(3)
    with col_act1:
        if st.button("🔄 Sincronizar Google Sheets / Buzón IMAP", use_container_width=True):
            if inc_mgr.state == TechnicianState.EMERGENCY_ASSIGNED:
                inc_mgr.poll_imap_for_resolution()
            st.rerun()
    with col_act2:
        if st.button(
            "⚡ Simular Sabotaje en Panel PNL-B04-12 (Caída V_DC + Temp)",
            use_container_width=True,
        ):
            sheets_mgr.inject_fault(
                panel_id="PNL-B04-12",
                v_dc_string_2=168.0,
                temp_heatsink=87.5,
                status_code="0x05",
            )
            st.rerun()
    with col_act3:
        if st.button("🛠️ Restaurar Todos los Paneles a Nominal", use_container_width=True):
            inc_mgr.process_resolution(
                resolution_note="Restauración manual desde consola NOC.",
                resolved_by="noc_console",
            )
            st.rerun()

    # ------------------------------------------------------------------
    # Active Incident Work Order & Email Reply Panel
    # ------------------------------------------------------------------
    if snapshot["state"] == TechnicianState.EMERGENCY_ASSIGNED:
        panel = snapshot["affected_panel"] or {}
        st.markdown("### 🚨 Orden de Trabajo Activa y Ubicación del Incidente")
        inc_col1, inc_col2 = st.columns([1.2, 1])

        with inc_col1:
            st.markdown(
                f"""
| Campo Operativo | Detalle del Incidente |
| :--- | :--- |
| **ID de Incidente** | `{snapshot['incident_id']}` |
| **Panel / String Afectado** | **{panel.get('panel_id', 'PNL-B04-12')}** |
| **Ubicación en Planta** | **{panel.get('location_block', 'Bloque B - Fila 4 - Posicion 12')}** |
| **Coordenadas GPS** | `{panel.get('latitude', 4.9192)}, {panel.get('longitude', -73.9975)}` |
| **Voltaje DC (S1 vs S2)** | `{panel.get('v_dc_string_1', 392.0):.1f} V` vs `{panel.get('v_dc_string_2', 168.0):.1f} V` ($\\Delta V = {panel.get('delta_v_dc_pct', 32.5):.1f}\\%$) |
| **Temperatura Disipador** | `{panel.get('temp_heatsink', 87.5):.1f} °C` ( Estado Hex: `{panel.get('status_code', '0x05')}` ) |
| **Alerta por Correo** | Enviada a `{inc_mgr.technician_email or 'modo simulación'}` (Total envíos: `{snapshot['email_dispatched_count']}`) |
"""
            )

            if snapshot["pdf_path"] and Path(snapshot["pdf_path"]).exists():
                with open(snapshot["pdf_path"], "rb") as pdf_file:
                    st.download_button(
                        label=f"📄 Descargar Orden de Trabajo PDF ({snapshot['incident_id']})",
                        data=pdf_file.read(),
                        file_name=Path(snapshot["pdf_path"]).name,
                        mime="application/pdf",
                        use_container_width=True,
                    )

        with inc_col2:
            st.warning(
                f"**Protocolo para el Técnico ({inc_mgr.technician_name}):**\n"
                f"1. **Preparar las cosas:** Multímetro DC 1000V, cámara termográfica, conectores MC4 y EPP dieléctrico.\n"
                f"2. **Hablar con su supervisor:** Contactar a **{inc_mgr.supervisor_name}** antes de intervenir `{panel.get('location_block', '')}`.\n"
                f"3. **Dar aviso por correo:** Responda (*Reply*) al correo recibido con asunto `[{snapshot['incident_id']}]` confirmando que atendió la emergencia."
            )
            reply_note = st.text_area(
                "📩 ¿El correo corporativo tarda? Simular o registrar aquí el correo de respuesta del técnico:",
                value="Emergencia atendida en Bloque B - Fila 4. Se reemplazó conector MC4 sulfatado en PNL-B04-12 previa coordinación con el supervisor Miguel Mejía. Valores normalizados.",
                height=100,
            )
            if st.button(
                "📨 Procesar Correo de Respuesta del Técnico y Normalizar Planta",
                type="primary",
                use_container_width=True,
            ):
                inc_mgr.process_resolution(
                    resolution_note=reply_note,
                    resolved_by=f"email_reply ({inc_mgr.technician_email or 'reclutador'})",
                )
                st.rerun()

    # ------------------------------------------------------------------
    # Map + Interactive Telemetry Table (Editable like Google Sheets)
    # ------------------------------------------------------------------
    map_col, table_col = st.columns([1, 1.35])

    with map_col:
        st.plotly_chart(build_plant_layout_figure(df), use_container_width=True)

    with table_col:
        st.markdown("### 📋 Tabla de Telemetría en Vivo (Espejo Google Sheets)")
        st.caption(
            "Edita cualquier celda (ej. baja `v_dc_string_2` a `170` o sube `temp_heatsink` a `88`) y presiona **Aplicar Cambios en Tabla** para disparar el incidente."
        )
        editable_cols = [
            "panel_id",
            "location_block",
            "v_dc_string_1",
            "v_dc_string_2",
            "temp_heatsink",
            "p_ac_output",
            "irradiance_poa",
            "status_code",
        ]
        edited_df = st.data_editor(
            raw_df[editable_cols],
            use_container_width=True,
            height=310,
            num_rows="fixed",
            key="telemetry_editor",
        )
        if st.button("💾 Aplicar Cambios de la Tabla y Evaluar Planta", use_container_width=True):
            updated_raw = raw_df.copy()
            for col in editable_cols:
                updated_raw[col] = edited_df[col]
            sheets_mgr.save_telemetry(updated_raw)
            st.rerun()

    # ------------------------------------------------------------------
    # Incident Audit Log
    # ------------------------------------------------------------------
    if inc_mgr.incident_history:
        st.markdown("### 📜 Historial de Incidentes Atendidos y Cerrados por Correo")
        st.dataframe(pd.DataFrame(inc_mgr.incident_history), use_container_width=True)


if __name__ == "__main__":
    main()
