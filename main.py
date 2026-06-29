'''
#main.py
import streamlit as st
import invoice
import contabilidad

import streamlit as st
import invoice
import contabilidad

# 1. Configuración de página (Única vez)
st.set_page_config(page_title="Sistema King Driver", layout="wide")

# 2. CSS PARA FORZAR ANCHO (Blindado)
st.markdown("""
    <style>
    .block-container { max-width: 98% !important; padding-top: 1rem !important; }
    div[data-testid="stVerticalBlock"] { gap: 0rem; }
    </style>
""", unsafe_allow_html=True)

# 3. Inicialización de sesión
if 'logueado' not in st.session_state:
    st.session_state.logueado = False

if not st.session_state.logueado:
    contabilidad.login_screen()
    st.stop() # Aquí sí debe ir para detener el resto si no hay login
else:
    # Solo si está logueado, pasamos la conexión y permitimos la navegación
    opcion = st.sidebar.radio("Seleccione Módulo:", ["Facturación", "Auditoría"])
    if opcion == "Auditoría":
        contabilidad.panel_administracion(conn)
'''


# main.py
import streamlit as st
import pandas as pd
import invoice
import contabilidad
from contabilidad import conectar_db
from datetime import datetime

# 1. Configuración de página
st.set_page_config(page_title="Sistema King Driver", layout="wide")

# 2. CSS Blindado
st.markdown("""
    <style>
    .block-container { max-width: 98% !important; padding-top: 1rem !important; }
    div[data-testid="stVerticalBlock"] { gap: 0rem; }
    </style>
""", unsafe_allow_html=True)

# 3. Función Reset
def reset_empresa():
    st.session_state.conn = None 
    st.session_state.data_loaded = False
    if 'opcion_menu_auditoria' in st.session_state:
        del st.session_state['opcion_menu_auditoria']
    st.rerun()

# 4. Inicialización de sesión
if 'logueado' not in st.session_state:
    st.session_state.logueado = False

if not st.session_state.logueado:
    contabilidad.login_screen()
    st.stop()

# --- BARRA LATERAL (SIDEBAR) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=100)
    st.write(f"Bienvenido, **{st.session_state.get('usuario')}**")
    
    if st.button("🚪 Cerrar Sesión"):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()

    st.markdown("---")
    
    # Carga de empresas
    user_rol = st.session_state.get('rol')
    user_cliente_id = st.session_state.get('cliente_id')
    
    conn_ctrl = conectar_db('control_central')
    if user_rol == 'admin':
        query = "SELECT id, nombre_empresa, nombre_bd FROM clientes"
    else:
        query = f"SELECT id, nombre_empresa, nombre_bd FROM clientes WHERE id = {user_cliente_id}"
        
    df_empresas = pd.read_sql(query, conn_ctrl)
    conn_ctrl.close() # Importante cerrar conexión
    
    if df_empresas.empty:
        st.error("No tienes empresas asignadas.")
        st.stop()
        
    empresa_elegida = st.selectbox(
        "Seleccione Empresa:", 
        df_empresas['nombre_empresa'].tolist(),
        key="selector_empresa",
        on_change=reset_empresa
    )
    
    # Sincronización de sesión
    fila = df_empresas[df_empresas['nombre_empresa'] == empresa_elegida].iloc[0]
    st.session_state['DB_ACTUAL'] = fila['nombre_bd']
    st.session_state['CLIENTE_NOMBRE'] = empresa_elegida
    
    st.markdown("---")
    opcion = st.radio("Módulo:", ["Facturación", "Auditoría"], key="mod_nav")

# --- NAVEGACIÓN PRINCIPAL ---
if opcion == "Auditoría":
    contabilidad.panel_administracion(st.session_state.get('DB_ACTUAL'))
elif opcion == "Facturación":
    invoice.modulo_facturacion()



import streamlit as st

# Esto es lo primero que debe ejecutarse al arrancar la App
def setup_session():
    if "session_initialized" not in st.session_state:
        st.session_state["id_empresa_seleccionada"] = None
        st.session_state["DB_ACTUAL"] = None
        st.session_state["session_initialized"] = True

setup_session()