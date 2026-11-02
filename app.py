# app.py
import streamlit as st
import pandas as pd
import invoice
import contabilidad
import instagram  # <--- Importamos tu nuevo archivo para manejar las vistas de Instagram
from contabilidad import conectar_db
from datetime import datetime

# 1. Configuración de página
st.set_page_config(page_title="Sistema King Driver", layout="wide")

# 🛑 1.5 ENRUTADOR NUCLEAR DE INSTAGRAM (ANTES DE TODO)
try:
    modulo_url = str(st.query_params.get("modulo", "")).strip().lower()
except:
    modulo_url = ""

if modulo_url:
    # Blindamos la sesión de invitado de inmediato
    st.session_state["logueado"] = True
    st.session_state["usuario"] = "invitado_insta"
    st.session_state["user"] = "invitado_insta"
    st.session_state["rol"] = "admin"
    st.session_state["DB_ACTUAL"] = "kingdriver_ca"
    st.session_state["CLIENTE_NOMBRE"] = "King Driver, C.A."
    
    # Enrutar al módulo correspondiente dentro de instagram.py
    if modulo_url == "libro_compras":
        instagram.modulo_compras()
    elif modulo_url == "libro_ventas":
        instagram.modulo_ventas()
    elif modulo_url == "retencion_islr":
        instagram.modulo_retencion_islr()
    elif modulo_url == "retencion_iva":
        instagram.modulo_retencion_iva()
    else:
        instagram.aplicar_estilo_publico()
        st.error("Módulo de Instagram no válido o no encontrado.")
    
    st.stop()  # Detenemos por completo para que NUNCA cargue el login ni la app normal

# 2. Inicialización de sesión normal
if "session_initialized" not in st.session_state:
    st.session_state["id_empresa_seleccionada"] = None
    if "DB_ACTUAL" not in st.session_state:
        st.session_state["DB_ACTUAL"] = None
    if "logueado" not in st.session_state:
        st.session_state["logueado"] = False
    st.session_state["session_initialized"] = True

# 3. CSS Blindado para la app normal
st.markdown(
    """
    <style>
    .block-container { max-width: 98% !important; padding-top: 1rem !important; }
    div[data-testid="stVerticalBlock"] { gap: 0rem; }
    </style>
""",
    unsafe_allow_html=True,
)


# 4. Función Reset
def reset_empresa():
    st.session_state.conn = None
    st.session_state.data_loaded = False
    st.session_state.pop("opcion_menu_auditoria", None)
    st.rerun()


# 5. Lógica de Login Normal (Solo para administradores / usuarios internos)
if not st.session_state.logueado:
    contabilidad.login_screen()
    st.stop()

# --- BARRA LATERAL (SIDEBAR NORMAL) ---
with st.sidebar:
    st.image(
        "https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=100
    )
    st.write(f"Bienvenido, **{st.session_state.get('usuario')}**")

    if st.button("🚪 Cerrar Sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.markdown("---")

    user_rol = st.session_state.get("rol")
    user_cliente_id = st.session_state.get("cliente_id")

    conn_ctrl = conectar_db()
    if user_rol == "admin":
        query = "SELECT id, nombre_empresa, nombre_bd FROM clientes"
    else:
        query = f"SELECT id, nombre_empresa, nombre_bd FROM clientes WHERE id = {user_cliente_id}"

    df_empresas = pd.read_sql(query, conn_ctrl)
    conn_ctrl.close()

    if df_empresas.empty:
        st.error("No tienes empresas asignadas.")
        st.stop()

    empresa_elegida = st.selectbox(
        "Seleccione Empresa:",
        df_empresas["nombre_empresa"].tolist(),
        key="selector_empresa",
        on_change=reset_empresa,
    )

    fila = df_empresas[
        df_empresas["nombre_empresa"] == empresa_elegida
    ].iloc[0]
    st.session_state["DB_ACTUAL"] = fila["nombre_bd"]
    st.session_state["CLIENTE_NOMBRE"] = empresa_elegida

    st.markdown("---")
    opcion = st.radio("Módulo:", ["Facturación", "Auditoría"], key="mod_nav")

# --- NAVEGACIÓN PRINCIPAL NORMAL ---
if opcion == "Auditoría":
    contabilidad.panel_administracion(st.session_state.get("DB_ACTUAL"))
elif opcion == "Facturación":
    invoice.modulo_facturacion()
