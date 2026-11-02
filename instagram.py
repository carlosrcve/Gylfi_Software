# instagram.py - Módulo Independiente del Libro de Compras
import io
import ssl
import time
from datetime import date as d_tipo, datetime, datetime as dt_tipo
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import pymysql
import streamlit as st
from sqlalchemy import create_engine, text


def aplicar_estilo_publico():
    """Oculta la barra lateral y ajusta el contenedor principal."""
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none !important; width: 0 !important; }
            [data-testid="collapsedControl"] { display: none !important; }
            section.main { width: 100% !important; margin-left: 0 !important; }
        </style>
    """, unsafe_allow_html=True)


def conectar_db(db_name=None):
    """Establece una conexión directa segura con TiDB Cloud."""
    target_db = db_name if db_name else st.session_state.get("DB_ACTUAL", "kingdriver_ca")
    try:
        password_escaped = quote_plus("W3Zkbr4E2trGCfoX")
        conn = pymysql.connect(
            host="gateway01.us-east-1.prod.aws.tidbcloud.com",
            user="4K4VAw4t4ZPFUTF.root",
            password="W3Zkbr4E2trGCfoX",
            database=target_db,
            port=4000,
            ssl={"ssl": None},
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn
    except Exception as e:
        return None


@st.cache_data(ttl=300)
def obtener_datos_agente_db(valor_busqueda):
    """Consulta segura de los datos de la empresa para el encabezado."""
    conn_central = conectar_db("kingdriver_ca")
    if not conn_central:
        return {
            "nombre_empresa": "King Driver, C.A.",
            "rif": "J-XXXXXXXX-X",
            "domicilio_fiscal": "Caracas, Venezuela"
        }
    
    cursor = None
    try:
        cursor = conn_central.cursor(pymysql.cursors.DictCursor)
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif, db_nombre, estado, direccion_fiscal FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif, db_nombre, estado, direccion_fiscal FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        return datos if datos else {
            "nombre_empresa": "King Driver, C.A.",
            "rif": "J-XXXXXXXX-X",
            "domicilio_fiscal": "Caracas, Venezuela"
        }
    except Exception:
        return {
            "nombre_empresa": "King Driver, C.A.",
            "rif": "J-XXXXXXXX-X",
            "domicilio_fiscal": "Caracas, Venezuela"
        }
    finally:
        if cursor: cursor.close()
        if conn_central: conn_central.close()


@st.cache_resource(show_spinner=False)
def obtener_engine_cached(db_name):
    """Crea y almacena en caché la conexión de SQLAlchemy."""
    password_escaped = quote_plus("W3Zkbr4E2trGCfoX")
    database_url = f"mysql+pymysql://4K4VAw4t4ZPFUTF.root:{password_escaped}@gateway01.us-east-1.prod.aws.tidbcloud.com:4000/{db_name}"
    return create_engine(
        database_url,
        connect_args={"ssl": {"ssl_ca": None, "check_hostname": False}},
    )


# --- FUNCIÓN CON CACHÉ GLOBAL (Fuera de modulo_compras) ---
@st.cache_data(ttl=30, show_spinner=False)
def consultar_libro_compras_cached(empresa, ver_todo_val, f_desde, f_hasta):
    df_res = pd.DataFrame()
    conn = conectar_db(empresa)
    if conn:
        try:
            conn.ping(reconnect=True)
            if ver_todo_val:
                query = "SELECT * FROM libro_compras ORDER BY fecha_operacion DESC"
                df_res = pd.read_sql(query, conn)
            else:
                query = "SELECT * FROM libro_compras WHERE fecha_operacion BETWEEN %s AND %s ORDER BY fecha_operacion ASC"
                df_res = pd.read_sql(query, conn, params=(f_desde, f_hasta))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return df_res


# --- FUNCIÓN PRINCIPAL DEL MÓDULO ---
def modulo_compras():
    aplicar_estilo_publico()

    db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
    empresa_data = obtener_datos_agente_db(db_actual)
    st.title("📖 Libro de Compras")
    st.markdown(f"### 🏢 {empresa_data.get('nombre_empresa', 'King Driver, C.A.')}")
    st.markdown(f"**RIF:** {empresa_data.get('rif', 'N/D')}")
    st.markdown("---")

    # Estructura principal de pestañas
    tab_titles = [
        "🔍 Consultar y Editar",
        "📸 Escaneo Inteligente",
        "🚨 Vaciado de Rango",
        "📊 Cargar desde Excel",
        "📁 PDFs POR LOTES",
        "📝 Notas de Crédito / Débito"
    ]
    tabs = st.tabs(tab_titles)
    tab1, tab2, tab3, tab4, tab5, tab6 = tabs

    # ==========================================
    # TAB 1: CONSULTAR Y EDITAR
    # ==========================================
    with tab1:
        st.subheader("🔍 Consulta y Edición: Libro de Compras")
        
        col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
        with col_c3:
            ver_todo = st.checkbox("📂 Ver todo", key="todo_compras")

        def _obtener_f_segura(key_s):
            val = st.session_state.get(key_s)
            if val is not None:
                try:
                    if hasattr(val, "year") and hasattr(val, "month"):
                        return val
                    elif isinstance(val, str):
                        return dt_tipo.strptime(val, "%Y-%m-%d").date()
                except Exception:
                    pass
            return d_tipo.today()

        with col_c1:
            desde_c = st.date_input("Desde", _obtener_f_segura("f_inicio_global"), key="desde_c", disabled=ver_todo)
        with col_c2:
            hasta_c = st.date_input("Hasta", _obtener_f_segura("f_fin_global"), key="hasta_c", disabled=ver_todo)

        st.error("⚠️ **Atención:** Las acciones aquí solo afectan al Libro de Compras.")

        if st.button("📊 Consultar Compras", key="btn_consultar_compras"):
            df_recuperado = consultar_libro_compras_cached(db_actual, ver_todo, desde_c, hasta_c)
            if df_recuperado is not None and not df_recuperado.empty:
                st.session_state.df_compras_editor = df_recuperado
            else:
                st.warning("No se encontraron registros en el rango seleccionado.")
                if "df_compras_editor" in st.session_state:
                    del st.session_state.df_compras_editor

        if "df_compras_editor" in st.session_state:
            df_mostrar_compras = st.session_state.df_compras_editor.copy()

            df_visual_c = df_mostrar_compras.copy()
            cols_moneda_c = ["total_compras", "importe_exento", "base_imponible", "iva_monto", "monto_iva_retenido"]
            for col in cols_moneda_c:
                if col in df_visual_c.columns:
                    df_visual_c[col] = df_visual_c[col].apply(
                        lambda x: "{:,.2f}".format(x).replace(",", "X").replace(".", ",").replace("X", ".") if pd.notnull(x) else "0,00"
                    )

            st.subheader("👁️ Vista de Consulta")
            st.dataframe(df_visual_c, use_container_width=True, hide_index=True)

    # ==========================================
    # TAB 2: ESCANEO INTELIGENTE (OCR)
    # ==========================================
    with tab2:
        st.subheader("📸 Escaneo Inteligente de Documentos (OCR)")
        if "df_buffer_escaneo" not in st.session_state:
            st.session_state.df_buffer_escaneo = pd.DataFrame()
        archivo = st.file_uploader("Sube factura, nota de crédito o débito (PDF o Imagen)", type=['jpg', 'png', 'jpeg', 'pdf'], key="uploader_factura")

    # ==========================================
    # TAB 3: VACIADO DE RANGO
    # ==========================================
    with tab3:
        st.subheader("🚨 Vaciado de Compras por Rango")
        st.warning("Herramienta para depuración de rangos de fechas en el libro de compras.")

    # ==========================================
    # TAB 4: CARGAR DESDE EXCEL
    # ==========================================
    with tab4:
        st.subheader("📊 Cargar desde Excel")
        st.info("📊 Carga Masiva desde Excel (LIBROS DE COMPRAS)")

    # ==========================================
    # TAB 5: PDFs POR LOTES
    # ==========================================
    with tab5:
        st.subheader("📁 PDFs POR LOTES")
        st.info("Bandeja de Entrada - Procesamiento Local de Facturas (PDF)")

    # ==========================================
    # TAB 6: NOTAS DE CRÉDITO / DÉBITO
    # ==========================================
    with tab6:
        st.subheader("📝 Gestión de Notas de Crédito y Débito")
        st.info("💡 **Flujo Fiscal:** Consulta el libro de compras por fecha y genera su documento de ajuste.")


if __name__ == "__main__":
    modulo_compras()



