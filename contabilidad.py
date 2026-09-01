#contabilidad.py
import os
import streamlit as st
import pymysql
from pymysql import Error
import requests
from bs4 import BeautifulSoup
import pandas as pd
from fpdf import FPDF
from datetime import datetime, date, timedelta
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io
import numpy as np
import re
import plotly.graph_objects as go
import plotly.express as px
import calendar
import base64
from PIL import Image, ImageEnhance
import json
from openai import OpenAI
from sqlalchemy import create_engine
import warnings
import bcrypt
import time
import ssl
import pymysql.cursors

st.set_page_config(
    page_title="Mi App Contable",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inicialización segura
HAS_TESSERACT = False
try:
    import pytesseract
    if os.name == 'nt':
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    else:
        pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

def conectar_db(nombre_db=None):
    db_a_usar = nombre_db if nombre_db else "control_central"
    
    # Contexto SSL específico para la capa de transporte segura de AWS/TiDB
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        # 1. Asegurar base de datos multicliente si no es la central
        if db_a_usar != "control_central":
            try:
                # CORREGIDO: Usamos 'conn' de forma consistente
                conn = pymysql.connect(
                    host="gateway01.us-east-1.prod.aws.tidbcloud.com",
                    port=4000,
                    user="4K4VAw4t4ZPFUTF.root",
                    password="OhAcM2lizBMDXDgD",
                    database="control_central", # Conectamos primero a central para asegurarnos de poder crearla si falta
                    connect_timeout=20,
                    charset='utf8mb4',
                    ssl=ssl_context
                )
                with conn.cursor() as cursor_temp:
                    cursor_temp.execute(f"CREATE DATABASE IF NOT EXISTS `{db_a_usar}`;")
                    
                    # SELECCIONAMOS LA BD Y CREAMOS LA TABLA AUTOMÁTICAMENTE
                    cursor_temp.execute(f"USE `{db_a_usar}`;")
                    cursor_temp.execute("""
                        CREATE TABLE IF NOT EXISTS documentos_cloud (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            empresa_db VARCHAR(100) NOT NULL,
                            categoria VARCHAR(50) NOT NULL,
                            nombre_archivo VARCHAR(255) NOT NULL,
                            ruta_archivo VARCHAR(500) NOT NULL,
                            fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                conn.close()
            except Exception as ex:
                print(f"Aviso al asegurar BD de cliente: {ex}")

        # 2. Validar conexión existente y asegurar que apunte EXACTAMENTE a db_a_usar
        if "conn" in st.session_state and st.session_state.conn is not None:
            try:
                st.session_state.conn.ping(reconnect=True)
                with st.session_state.conn.cursor() as cursor_test:
                    cursor_test.execute("SELECT DATABASE()")
                    res = cursor_test.fetchone()
                    db_actual = res[0] if res else None
                
                # Si la conexión activa ya está en la BD correcta, la reutilizamos
                if db_actual == db_a_usar:
                    return st.session_state.conn
                else:
                    # Si estaba en otra BD, la cerramos para forzar la nueva
                    st.session_state.conn.close()
                    st.session_state.conn = None
            except Exception:
                st.session_state.conn = None

        st.session_state.conn = None

        # 3. Conexión oficial definitiva apuntando directamente a la BD requerida
        st.session_state.conn = pymysql.connect(
            host="gateway01.us-east-1.prod.aws.tidbcloud.com",
            port=4000,
            user="4K4VAw4t4ZPFUTF.root",
            password="OhAcM2lizBMDXDgD",
            database=db_a_usar,
            connect_timeout=15,
            charset='utf8mb4',
            ssl=ssl_context
        )
        return st.session_state.conn
        
    except Exception as ex:
        st.error(f"❌ Error crítico de conexión a TiDB Cloud ('{db_a_usar}'): {ex}")
        st.session_state.conn = None
        return None

def ejecutar_consulta(query, conn, params=None):
    cursor = None
    try:
        # Usamos DictCursor de PyMySQL
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, params or ())
        resultados = cursor.fetchall()
        return pd.DataFrame(resultados) if resultados else pd.DataFrame()
    except Exception as e:
        # ACTIVADO: Esto te mostrará el error exacto en la app si algo falla en SQL
        st.error(f"❌ Error crítico en ejecutar_consulta: {e} | Query: {query}")
        return pd.DataFrame()
    finally:
        if cursor:
            cursor.close()

def verificar_usuario(conn, user, password):
    if conn is None:
        try:
            conn = conectar_db()
        except:
            return None 

    user_data = None
    cursor = None

    for intento in range(2):
        try:
            # Validación de conexión abierta en PyMySQL
            if not conn or not getattr(conn, 'open', False):
                conn = conectar_db()
                if not conn:
                    return None
                
            # Cursor con diccionario nativo de PyMySQL
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            # Consultamos al usuario y hacemos un LEFT JOIN con la tabla clientes 
            # para traernos el estado de su firma, su base de datos asignada y el estado del usuario individual.
            query = """
                SELECT u.*, c.estado as estado_cliente, c.db_nombre as db_cliente_nombre, c.nombre_empresa 
                FROM control_central.usuarios u 
                LEFT JOIN control_central.clientes c ON u.cliente_id = c.id 
                WHERE u.usuario = %s
            """
            cursor.execute(query, (user,))
            user_data = cursor.fetchone()
            break 
        except Exception as e:
            if intento == 0:
                try:
                    conn.ping(reconnect=True)
                    continue
                except:
                    return None
            else:
                return None

    if not user_data:
        try:
            if cursor:
                cursor.close()
        except:
            pass
        return None 
    
    # 🚫 VALIDACIÓN 1: LICENCIA / SUSCRIPCIÓN DE LA FIRMA (BLOQUEO GLOBAL DE EMPRESA)
    rol_actual = str(user_data.get('rol', '')).upper()
    if user_data.get('cliente_id') and rol_actual != 'SUPERADMIN':
        estado_firma = str(user_data.get('estado_cliente', '')).lower()
        if estado_firma not in ['activo', 'activa', '1']:
            try:
                if cursor:
                    cursor.close()
            except:
                pass
            st.error("🚫 **Licencia Suspendida:** El acceso de esta firma se encuentra temporalmente suspendido por falta de pago. Comuníquese con el soporte técnico.")
            return None

    # 🚫 VALIDACIÓN 2: ESTADO DEL USUARIO INDIVIDUAL (BLOQUEO PERSONALIZADO)
    estado_usuario = str(user_data.get('estado', 'activo')).lower()
    if estado_usuario in ['suspendido', 'inactivo', '0']:
        try:
            if cursor:
                cursor.close()
        except:
            pass
        st.error("🚫 **Acceso Restringido:** Tu cuenta de usuario se encuentra suspendida o inactiva. Comuníquese con el administrador de la firma.")
        return None

    # Obtenemos la clave de la base de datos de forma segura
    clave_en_bd = user_data.get('clave_hash') or user_data.get('password')
    login_exitoso = False
    
    if clave_en_bd:
        password_bytes = password.encode('utf-8')
        clave_str = str(clave_en_bd)
        
        # Verificamos si es un hash de bcrypt (soportando variantes 2a, 2b, 2y)
        if clave_str.startswith(('$2a$', '$2b$', '$2y$')):
            try:
                if bcrypt.checkpw(password_bytes, clave_str.encode('utf-8')):
                    login_exitoso = True
            except Exception as ex:
                st.error(f"Error al validar hash: {ex}")
        else:
            # Si está en texto plano
            if password == clave_str:
                login_exitoso = True
                # Intentamos actualizar a hash de forma silenciosa para mejorar seguridad
                try:
                    salt = bcrypt.gensalt()
                    nuevo_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
                    cursor.execute("UPDATE control_central.usuarios SET clave_hash = %s WHERE id = %s", (nuevo_hash, user_data['id']))
                    conn.commit()
                except:
                    pass
    
    # Cierre seguro del cursor
    try:
        if cursor:
            cursor.close()
    except:
        pass
    
    if login_exitoso:
        # Aseguramos llaves por defecto para que la sesión no falle
        if 'rol' not in user_data or not user_data['rol']:
            user_data['rol'] = 'admin'
        if 'cliente_id' not in user_data:
            user_data['cliente_id'] = None
        
        # Aseguramos que la base de datos del cliente viaje limpia en el diccionario
        user_data['nombre_base_de_datos'] = user_data.get('db_cliente_nombre') or user_data.get('db_nombre')
        
        return user_data
    else:
        return None
def mostrar_plantilla_bienvenida():
    """Pantalla gigante de bienvenida tras iniciar sesión con éxito"""
    rol = str(st.session_state.get('rol', '')).upper()
    nombre = (
        st.session_state.get('nombre_usuario') or 
        st.session_state.get('username') or 
        st.session_state.get('usuario') or 
        'Usuario'
    )
    
    # Contenedor centrado para la plantilla de bienvenida
    _, col_centro, _ = st.columns([1, 2.5, 1])
    
    with col_centro:
        st.write("")
        st.write("")
        
        if rol == 'ADMIN':
            mensaje_rol = "👑 Administrador Principal / Dueño del Software"
            gradient = "linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%)"
        else:
            mensaje_rol = f"👤 Usuario Propietario: {nombre}"
            gradient = "linear-gradient(135deg, #0f172a 0%, #334155 100%)"

        st.markdown(f"""
            <div style="background: {gradient}; padding: 3.5rem; border-radius: 20px; text-align: center; color: white; box-shadow: 0 15px 30px rgba(0,0,0,0.3); border: 1px solid #475569;">
                <h1 style="color: #ffffff; font-size: 2.8rem; margin-bottom: 10px;">☁️ Gylfi Software en la Nube</h1>
                <h3 style="color: #38bdf8; font-weight: 500; margin-bottom: 20px;">Ecosistema de Auditoría y Contabilidad Inteligente</h3>
                <hr style="border-color: #475569; margin: 25px 0;">
                <h2 style="color: #f8fafc; font-size: 1.5rem; margin-bottom: 10px;">¡Bienvenido al Sistema!</h2>
                <p style="font-size: 1.2rem; color: #94a3b8; font-weight: 600;">{mensaje_rol}</p>
            </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        progress_text = "Cargando módulos de seguridad y bases de datos..."
        my_bar = st.progress(0, text=progress_text)

        for percent_complete in range(100):
            time.sleep(0.015)
            my_bar.progress(percent_complete + 1, text=progress_text)
            
        time.sleep(0.8)
        
        # Una vez vista la plantilla, cambiamos la bandera para entrar a la app normal
        st.session_state['bienvenida_completada'] = True
        st.rerun()

def play_success_sound():
    audio_url = "https://www.myinstants.com/media/sounds/ding-sound-effect_1.mp3"
    st.audio(audio_url, format="audio/mp3", autoplay=True)


def login_screen():
    # --- ESTILOS CSS PROFESIONALES ---
    st.markdown("""
        <style>
        .stApp { background-color: #f8fafc; }
        .login-box {
            background-color: white;
            padding: 2rem;
            border-radius: 15px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
            border: 1px solid #e2e8f0;
            margin-bottom: 20px;
        }
        .stButton > button {
            width: 100%;
            background: linear-gradient(90deg, #0f172a 0%, #334155 100%);
            color: white;
            border: none;
            padding: 10px;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        .stButton > button:hover {
            background: linear-gradient(90deg, #334155 0%, #0f172a 100%);
            transform: translateY(-2px);
        }
        label {
            font-weight: 500 !important;
            color: #475569 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # --- DISEÑO DEL FRAME ---
    _, col_center, _ = st.columns([1, 1.5, 1])

    with col_center:
        st.write("") 
        st.write("")
        
        with st.container():
            st.markdown('<div class="login-box">', unsafe_allow_html=True)
            
            st.info("☁️ **¡Bienvenido a Gylfi Software en la Nube!**")
            st.image("https://cdn-icons-png.flaticon.com/512/5164/5164023.png", width=60)
            st.subheader("Auditoría Inteligente")
            st.caption("Bienvenido al ecosistema contable de Carlos Rodriguez")
            
            user = st.text_input("Usuario", placeholder="ej: admin_kd", key="user_input")
            password = st.text_input("Contraseña", type="password", placeholder="••••••••", key="pass_input")
            
            if st.button("Ingresar al Portal"):
                conexion_activa = conectar_db()
                res = verificar_usuario(conexion_activa, user, password)
                
                if res:
                    # Se ejecuta la función global al pulsar el botón correctamente
                    play_success_sound()
                    st.toast("¡Acceso Concedido!", icon="🔒")
                    
                    st.session_state['logueado'] = True
                    st.session_state['usuario'] = user
                    st.session_state['rol'] = res['rol']
                    st.session_state['user_id'] = res['id']         
                    st.session_state['cliente_id'] = res.get('cliente_id')  
                    
                    # 🔑 Guardamos la base de datos del cliente en la sesión
                    st.session_state['db_cliente'] = res.get('nombre_base_de_datos') 
                    
                    st.session_state['bienvenida_completada'] = False
                    
                    st.rerun()
                else:
                    # Si falló, revisamos si el usuario existe pero su firma está suspendida
                    try:
                        if not conexion_activa or not getattr(conexion_activa, 'open', False):
                            conexion_activa = conectar_db()
                            
                        cursor_check = conexion_activa.cursor(pymysql.cursors.DictCursor)
                        cursor_check.execute("""
                            SELECT c.estado 
                            FROM usuarios u 
                            LEFT JOIN clientes c ON u.cliente_id = c.id 
                            WHERE u.usuario = %s
                        """, (user,))
                        datos_cli = cursor_check.fetchone()
                        cursor_check.close()
                        
                        if datos_cli and str(datos_cli.get('estado', '')).lower() in ['suspendido', 'inactivo', '0']:
                            st.error("🚫 **Acceso Bloqueado:** La licencia de esta firma está suspendida por falta de pago.")
                        else:
                            st.error("❌ Credenciales incorrectas")
                    except Exception:
                        st.error("❌ Credenciales incorrectas")
            
            st.markdown('</div>', unsafe_allow_html=True)


def mostrar_panel_superadmin(conn):
    st.subheader("🛡️ Panel de Control Global - Licencias y Firmas")
    st.markdown("Gestión de estados, suscripciones y accesos de los dueños de firmas.")
    
    # 1. Consultar todos los clientes/firmas registradas
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    cursor.execute("SELECT id, nombre_empresa, rif, db_nombre, estado FROM clientes")
    clientes = cursor.fetchall()
    cursor.close()
    
    if not clientes:
        st.info("No hay firmas registradas en el sistema.")
        return

    import pandas as pd
    df_clientes = pd.DataFrame(clientes)
    
    st.write("### Listado de Firmas Contables")
    
    # Recorremos cada cliente para mostrar una tarjeta o una tabla interactiva con controles
    for index, row in df_clientes.iterrows():
        with st.container():
            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
            
            with col1:
                st.write(f"**{row['nombre_empresa']}**")
                st.caption(f"RIF: {row['rif']} | BD: {row['db_nombre']}")
                
            with col2:
                estado_actual = str(row['estado']).lower()
                if estado_actual in ['activo', 'activa', '1']:
                    st.success("🟢 ACTIVO")
                else:
                    st.error("🔴 SUSPENDIDO")
                    
            with col3:
                # Selector rápido para cambiar el estado
                nuevo_estado = st.selectbox(
                    "Cambiar Estado", 
                    options=["activo", "suspendido"], 
                    index=0 if estado_actual in ['activo', 'activa', '1'] else 1,
                    key=f"estado_cli_{row['id']}"
                )
                
            with col4:
                st.write("") # Espaciador visual
                if st.button("💾 Actualizar", key=f"btn_upd_{row['id']}"):
                    try:
                        cursor_upd = conn.cursor()
                        cursor_upd.execute(
                            "UPDATE clientes SET estado = %s WHERE id = %s", 
                            (nuevo_estado, row['id'])
                        )
                        conn.commit()
                        cursor_upd.close()
                        st.success(f"¡Actualizado a {nuevo_estado}!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            
            st.divider()



def verificar_si_es_contribuyente_especial(db_name_o_comercial):
    """
    Verifica en la BD central buscando de forma flexible por el nombre técnico (db_nombre) 
    o por el nombre comercial, actualizando siempre el RIF correcto en la sesión.
    """
    if not db_name_o_comercial:
        return False
        
    parametro_limpio = str(db_name_o_comercial).strip()

    try:
        conexion_admin = conectar_db_principal() # Tu método de conexión global
        if conexion_admin:
            with conexion_admin.cursor(dictionary=True) as cursor:
                # Consulta flexible: busca si coincide con la BD técnica o con el nombre comercial
                sql = """
                    SELECT db_nombre, rif, tipo_contribuyente, estado 
                    FROM clientes 
                    WHERE TRIM(db_nombre) = TRIM(%s) 
                       OR TRIM(nombre_empresa) = TRIM(%s)
                """
                cursor.execute(sql, (parametro_limpio, parametro_limpio))
                resultado = cursor.fetchone()
            
            conexion_admin.close()
            
            if resultado and resultado.get('rif'):
                rif_encontrado = str(resultado['rif']).strip()
                db_tecnica = str(resultado.get('db_nombre', parametro_limpio)).strip()
                tipo_bd = str(resultado.get('tipo_contribuyente', 'Contribuyente Especial')).strip()
                
                # ACTUALIZAMOS LA SESIÓN DE FORMA LIMPIA (Evita que se quede pegado el RIF anterior)
                st.session_state['db_activa'] = db_tecnica
                st.session_state['DB_ACTUAL'] = db_tecnica  # Sincronizamos la clave principal
                st.session_state['rif_empresa_activa'] = rif_encontrado
                st.session_state['tipo_contribuyente'] = tipo_bd
                
                return True
                
    except Exception as e:
        print(f"Error verificando tipo de contribuyente: {e}")
    
    return False


def obtener_calendario_seniat_2026(terminal_rif):
    """
    Retorna el diccionario con los cronogramas fiscales del SENIAT 2026 
    según el terminal de RIF (0 al 9).
    """
    iva_1_map = {
        0: ["28", "20", "25", "23", "20", "29", "27", "31", "29", "20", "27", "16"],
        1: ["19", "23", "20", "27", "18", "26", "21", "25", "18", "28", "26", "29"],
        2: ["21", "18", "24", "21", "29", "16", "30", "24", "24", "29", "17", "21"],
        3: ["30", "18", "23", "30", "22", "18", "23", "18", "21", "23", "23", "28"],
        4: ["23", "25", "26", "20", "21", "19", "28", "19", "30", "22", "20", "22"],
        5: ["22", "27", "30", "22", "28", "17", "22", "21", "25", "30", "18", "17"],
        6: ["20", "19", "27", "24", "19", "30", "20", "28", "28", "21", "25", "18"],
        7: ["27", "24", "18", "17", "26", "22", "31", "20", "22", "27", "19", "18"],
        8: ["26", "26", "31", "29", "27", "23", "17", "26", "17", "26", "24", "30"],
        9: ["29", "27", "17", "28", "25", "25", "29", "27", "23", "19", "30", "23"]
    }

    iva_2_map = {
        0: ["15", "09", "06", "01", "06", "12", "08", "14", "14", "05", "13", "03"],
        1: ["06", "10", "03", "14", "04", "11", "03", "13", "03", "14", "12", "15"],
        2: ["08", "05", "09", "08", "14", "03", "14", "12", "10", "15", "02", "04"],
        3: ["16", "12", "04", "16", "07", "10", "07", "05", "02", "07", "09", "11"],
        4: ["09", "02", "11", "07", "13", "02", "10", "06", "09", "06", "05", "07"],
        5: ["05", "13", "12", "09", "15", "08", "06", "03", "15", "08", "04", "10"],
        6: ["13", "04", "10", "13", "05", "15", "09", "04", "11", "02", "11", "08"],
        7: ["12", "11", "02", "06", "11", "04", "15", "10", "04", "13", "03", "02"],
        8: ["07", "03", "13", "10", "12", "05", "02", "07", "08", "09", "06", "09"],
        9: ["14", "06", "05", "15", "08", "09", "13", "11", "07", "01", "10", "14"]
    }

    def obtener_grupo_islr(term):
        if term in [0, 8]: return 0
        elif term in [1, 4]: return 1
        elif term in [2, 3]: return 2
        elif term in [5, 9]: return 3
        elif term in [6, 7]: return 4
        return 0

    idx_grupo = obtener_grupo_islr(terminal_rif)

    estimadas_islr_matrix = [
        ["15", "09", "13", "10", "12", "12", "08", "14", "08", "09", "13", "09"], 
        ["09", "10", "11", "14", "13", "11", "10", "13", "09", "14", "12", "15"], 
        ["08", "12", "09", "08", "14", "10", "14", "12", "10", "15", "09", "11"], 
        ["14", "13", "12", "09", "15", "09", "13", "11", "15", "08", "10", "10"], 
        ["13", "11", "10", "13", "11", "15", "09", "10", "11", "13", "11", "08"]  
    ]

    retenciones_islr_matrix = [
        ["15", "09", "06", "10", "12", "05", "08", "07", "08", "09", "06", "09"], 
        ["09", "10", "11", "07", "13", "11", "10", "06", "09", "06", "05", "07"], 
        ["08", "05", "09", "08", "07", "10", "07", "12", "10", "07", "09", "04"], 
        ["14", "06", "05", "09", "08", "09", "06", "11", "07", "08", "10", "10"], 
        ["13", "11", "10", "06", "11", "04", "09", "10", "04", "13", "11", "08"]  
    ]

    return {
        "iva_1": iva_1_map.get(terminal_rif, iva_1_map[0]),
        "iva_2": iva_2_map.get(terminal_rif, iva_2_map[0]),
        "estimadas_islr": estimadas_islr_matrix[idx_grupo],
        "retenciones_islr": retenciones_islr_matrix[idx_grupo]
    }




def mostrar_calendario_cliente(db_name):
    """
    Muestra el calendario fiscal consultando el True Center por nombre de empresa o base de datos (texto).
    """
    parametro_seleccionado = str(db_name).strip() if db_name else ""
    
    # Verificamos la empresa actual guardada en la sesión
    db_en_sesion = st.session_state.get('db_actual_empresa')
    
    # FORZAMOS LA ACTUALIZACIÓN si cambia de empresa en el selectbox
    if db_en_sesion != parametro_seleccionado:
        st.session_state['db_actual_empresa'] = parametro_seleccionado
        if 'rif_empresa_activa' in st.session_state:
            del st.session_state['rif_empresa_activa']
        if 'terminal_rif_activo' in st.session_state:
            del st.session_state['terminal_rif_activo']
        if 'nombre_empresa_activa' in st.session_state:
            del st.session_state['nombre_empresa_activa']

    # Si no está en sesión, consultamos al True Center usando texto
    if 'rif_empresa_activa' not in st.session_state or 'terminal_rif_activo' not in st.session_state:
        rif_cliente = "J-00000000-0"
        terminal_rif = 0
        nombre_empresa_str = parametro_seleccionado
        
        try:
            conexion_admin = conectar_db("control_central")
            if conexion_admin:
                with conexion_admin.cursor(pymysql.cursors.DictCursor) as cursor:
                    # Búsqueda exacta por texto (db_nombre o nombre_empresa)
                    sql = """
                        SELECT id, nombre_empresa, rif, db_nombre, ultimo_digito, tipo_contribuyente 
                        FROM clientes 
                        WHERE TRIM(db_nombre) = TRIM(%s) 
                           OR TRIM(nombre_empresa) = TRIM(%s)
                    """
                    cursor.execute(sql, (parametro_seleccionado, parametro_seleccionado))
                    resultado = cursor.fetchone()
                    
                    # Si no hay exacta, probamos búsqueda parcial segura (LIKE)
                    if not resultado:
                        sql_like = """
                            SELECT id, nombre_empresa, rif, db_nombre, ultimo_digito, tipo_contribuyente 
                            FROM clientes 
                            WHERE TRIM(db_nombre) LIKE TRIM(%s) 
                               OR TRIM(nombre_empresa) LIKE TRIM(%s)
                        """
                        patron = f"%{parametro_seleccionado}%"
                        cursor.execute(sql_like, (patron, patron))
                        resultado = cursor.fetchone()
                    
                    if resultado:
                        nombre_empresa_str = str(resultado.get('nombre_empresa', parametro_seleccionado)).strip()
                        rif_cliente = str(resultado.get('rif', 'J-00000000-0')).strip()
                        
                        # Extracción matemática del último dígito del RIF
                        digitos_rif = "".join([c for c in rif_cliente if c.isdigit()])
                        if digitos_rif:
                            terminal_rif = int(digitos_rif[-1])
                        else:
                            terminal_rif = int(resultado.get('ultimo_digito', 0))
                            
                conexion_admin.close()
                
                # Guardamos en sesión para evitar consultas repetidas innecesarias
                st.session_state['rif_empresa_activa'] = rif_cliente
                st.session_state['terminal_rif_activo'] = terminal_rif
                st.session_state['nombre_empresa_activa'] = nombre_empresa_str
        except Exception as e:
            st.error(f"❌ Error al conectar con el True Center: {e}")
            st.session_state['rif_empresa_activa'] = "J-00000000-0"
            st.session_state['terminal_rif_activo'] = 0
            st.session_state['nombre_empresa_activa'] = parametro_seleccionado

    # Recuperamos de la sesión
    rif_cliente = st.session_state.get('rif_empresa_activa', 'J-00000000-0')
    terminal_rif = int(st.session_state.get('terminal_rif_activo', 0))
    nombre_empresa_str = st.session_state.get('nombre_empresa_activa', parametro_seleccionado)

    rif_str = str(rif_cliente).strip()
    digitos_rif = "".join([c for c in rif_str if c.isdigit()])
    rif_limpio = digitos_rif if digitos_rif else "00000000"

    # Manejo de persistencia de pagos mediante archivo JSON dinámico
    archivo_pagos = f"pagos_{rif_limpio}.json"

    def cargar_pagos_disco():
        if os.path.exists(archivo_pagos):
            try:
                with open(archivo_pagos, "r") as f:
                    return json.load(f)
            except:
                pass
        return {"iva_1": False, "iva_2": False, "islr": False, "pensiones": False}

    def guardar_pagos_disco(datos):
        try:
            with open(archivo_pagos, "w") as f:
                json.dump(datos, f)
        except:
            pass

    key_session_pagos = f"pagos_realizados_{rif_limpio}"
    if key_session_pagos not in st.session_state:
        st.session_state[key_session_pagos] = cargar_pagos_disco()

    pagos_realizados = st.session_state[key_session_pagos]

    # Contenedor interactivo con casillas de verificación
    st.markdown(f"##### 📝 Control de Pagos Realizados (Empresa: `{nombre_empresa_str}` | RIF: {rif_str} - Terminal: {terminal_rif}):")
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        val_iva_2 = st.checkbox("✅ IVA 2da Quincena Pagado", value=pagos_realizados.get("iva_2", False), key=f"chk_iva_2_{rif_limpio}")
        val_islr = st.checkbox("✅ Retenciones ISLR Pagadas", value=pagos_realizados.get("islr", False), key=f"chk_islr_{rif_limpio}")
    with col_c2:
        val_pensiones = st.checkbox("✅ Ley de Pensiones Pagada", value=pagos_realizados.get("pensiones", False), key=f"chk_pensiones_{rif_limpio}")
        val_iva_1 = st.checkbox("✅ IVA 1era Quincena Pagado", value=pagos_realizados.get("iva_1", False), key=f"chk_iva_1_{rif_limpio}")

    nuevos_pagos = {
        "iva_1": val_iva_1,
        "iva_2": val_iva_2,
        "islr": val_islr,
        "pensiones": val_pensiones
    }

    if nuevos_pagos != pagos_realizados:
        st.session_state[key_session_pagos] = nuevos_pagos
        guardar_pagos_disco(nuevos_pagos)
        st.rerun()

    calendario = obtener_calendario_seniat_2026(terminal_rif)
    
    q1_vals = list(calendario['iva_1'])
    q2_vals = list(calendario['iva_2'])
    islr_vals = list(calendario['retenciones_islr'])
    pensiones_vals = ["17", "29", "20", "27", "16", "15", "15", "17", "29", "20", "27", "16"]

    # --- ALERTAS INTELIGENTES ---
    st.divider()
    st.markdown("### 🔔 Estado de Alertas Fiscales Próximas")

    hoy = date.today()
    mes_actual_idx = hoy.month - 1

    try:
        dia_iva_1 = int(q1_vals[mes_actual_idx])
        dia_iva_2 = int(q2_vals[mes_actual_idx])
        dia_islr = int(islr_vals[mes_actual_idx])
        dia_pensiones = int(pensiones_vals[mes_actual_idx])
    except:
        dia_iva_1, dia_iva_2, dia_islr, dia_pensiones = 15, 30, 15, 17

    eventos_fiscales = [
        {"id": "iva_1", "concepto": "IVA / Anticipos (1era Quincena)", "fecha": date(hoy.year, hoy.month, dia_iva_1)},
        {"id": "iva_2", "concepto": "IVA / Anticipos (2da Quincena)", "fecha": date(hoy.year, hoy.month, dia_iva_2)},
        {"id": "islr", "concepto": "Retenciones de ISLR", "fecha": date(hoy.year, hoy.month, dia_islr)},
        {"id": "pensiones", "concepto": "Ley de Protección de Pensiones", "fecha": date(hoy.year, hoy.month, dia_pensiones)},
    ]

    alerta_activa = False
    mensajes_urgentes = []

    for evento in eventos_fiscales:
        dias_restantes = (evento["fecha"] - hoy).days
        pagado = pagos_realizados.get(evento["id"], False)
        
        if pagado:
            st.info(f"✔️ **{evento['concepto']}**: Declarado y pagado a tiempo. ¡Sin deudas pendientes para esta fecha!")
        elif 0 <= dias_restantes <= 3:
            alerta_activa = True
            mensajes_urgentes.append(f"⚠️ **¡ATENCIÓN!** Se acerca la declaración y pago de **{evento['concepto']}** programada para el **{evento['fecha'].strftime('%d/%m/%Y')}** (Faltan {dias_restantes} días).")

    if alerta_activa:
        audio_html = """
            <audio autoplay style="display:none;">
              <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
            </audio>
        """
        st.markdown(audio_html, unsafe_allow_html=True)
        texto_notificacion = "<br>".join(mensajes_urgentes)
        st.markdown(f"""
            <div id="banco-toast-alerta" style="
                position: fixed; top: 20px; right: 20px; z-index: 999999;
                background-color: #fff3cd; color: #856404; padding: 16px 20px;
                border-radius: 8px; border-left: 6px solid #ffeeba; border: 1px solid #ffeeba;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15); font-family: sans-serif; max-width: 400px;
            ">
                <div style="font-weight: bold; margin-bottom: 5px; font-size: 15px;">🔔 Notificación Fiscal Urgente</div>
                <div style="font-size: 13px; line-height: 1.4;">{texto_notificacion}</div>
            </div>
        """, unsafe_allow_html=True)
    else:
        if not any(pagos_realizados.values()) and not any(0 <= (e["fecha"] - hoy).days <= 3 for e in eventos_fiscales):
            st.success("✅ No hay obligaciones fiscales críticas a menos de 3 días de vencimiento en este momento.")

    st.divider()

    if pagos_realizados["iva_1"]: q1_vals[mes_actual_idx] = "✅ Pagado"
    if pagos_realizados["iva_2"]: q2_vals[mes_actual_idx] = "✅ Pagado"
    if pagos_realizados["islr"]: islr_vals[mes_actual_idx] = "✅ Pagado"
    if pagos_realizados["pensiones"]: pensiones_vals[mes_actual_idx] = "✅ Pagado"

    meses = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEPT", "OCT", "NOV", "DIC"]

    st.subheader(f"📊 Calendario Fiscal 2026 - {nombre_empresa_str} (Terminal RIF: {terminal_rif})")
    st.markdown("### 🗓️ Cronograma de Declaraciones y Pagos")

    st.markdown("""
    <style>
        .fiscal-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-family: sans-serif; font-size: 14px; }
        .fiscal-table th { background-color: #2b313e; color: white; text-align: center; padding: 8px; border: 1px solid #ddd; }
        .fiscal-table td { text-align: center; padding: 8px; border: 1px solid #ddd; }
        .header-iva { background-color: #d4edda; color: #155724; font-weight: bold; text-align: left; padding: 8px; }
        .header-islr { background-color: #fff3cd; color: #856404; font-weight: bold; text-align: left; padding: 8px; }
        .header-pensiones { background-color: #cce5ff; color: #004085; font-weight: bold; text-align: left; padding: 8px; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("#### 1. IVA, Anticipos de ISLR, IGTF y Retenciones de IVA")
    st.markdown(f"""
    <table class="fiscal-table">
        <tr><th colspan="13" class="header-iva">Primera Quincena (01 al 15) - R.I.F. Terminado en {terminal_rif}</th></tr>
        <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
        <tr><td><b>{terminal_rif}</b></td>{"".join([f"<td>{val}</td>" for val in q1_vals])}</tr>
    </table>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <table class="fiscal-table">
        <tr><th colspan="13" class="header-iva" style="background-color: #e2f0d9;">Segunda Quincena (16 al último) - R.I.F. Terminado en {terminal_rif}</th></tr>
        <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
        <tr><td><b>{terminal_rif}</b></td>{"".join([f"<td>{val}</td>" for val in q2_vals])}</tr>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("#### 2. Retenciones de Impuesto Sobre la Renta")
    st.markdown(f"""
    <table class="fiscal-table">
        <tr><th colspan="13" class="header-islr">Retenciones de Impuesto Sobre la Renta - R.I.F. Terminado en {terminal_rif}</th></tr>
        <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
        <tr><td><b>{terminal_rif}</b></td>{"".join([f"<td>{val}</td>" for val in islr_vals])}</tr>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("#### 3. Ley de Protección de las Pensiones de Seguridad Social")
    st.markdown(f"""
    <table class="fiscal-table">
        <tr><th colspan="13" class="header-pensiones">Ley de Pensiones - R.I.F. Terminado en {terminal_rif}</th></tr>
        <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
        <tr><td><b>{terminal_rif}</b></td>{"".join([f"<td>{val}</td>" for val in pensiones_vals])}</tr>
    </table>
    """, unsafe_allow_html=True)


def panel_administracion(conn):
    st.header("⚙️ Gestión de Usuarios y Accesos")
    
    # 1. FORMULARIO DE REGISTRO
    with st.expander("➕ Registrar Nuevo Usuario del Sistema", expanded=True):
        with st.form("registro_usuario"):
            col1, col2 = st.columns(2)
            
            with col1:
                nuevo_u = st.text_input("Nombre de Usuario", help="Ej: carlos_admin o king_gerente")
                nueva_p = st.text_input("Contraseña", type="password")
            
            with col2:
                rol = st.selectbox("Rol del Sistema", ["admin", "cliente"])
                
                # Buscamos las empresas disponibles para asociar
                try:
                    query_cli = "SELECT id, nombre_empresa FROM control_central.clientes"
                    df_cli = ejecutar_consulta(query_cli, conn)
                    opciones_clientes = {row['nombre_empresa']: row['id'] for _, row in df_cli.iterrows()}
                    
                    nombre_sel = st.selectbox("Asociar a Empresa (Solo para rol cliente)", 
                                              ["Ninguna / Acceso Total"] + list(opciones_clientes.keys()))
                except Exception as e:
                    st.warning(f"⚠️ No se pudieron cargar las empresas de la base de datos: {e}")
                    opciones_clientes = {}

            btn_crear = st.form_submit_button("Guardar Usuario en Base de Datos")
            
            if btn_crear:
                if not nuevo_u or not nueva_p:
                    st.error("❌ El usuario y la contraseña son obligatorios.")
                else:
                    try:
                        salt = bcrypt.gensalt()
                        hash_cifrado = bcrypt.hashpw(nueva_p.encode('utf-8'), salt)
                        
                        c_id = opciones_clientes.get(nombre_sel) if rol == "cliente" and nombre_sel != "Ninguna / Acceso Total" else None
                        
                        cursor = conn.cursor()
                        sql = """INSERT INTO usuarios (usuario, clave_hash, rol, cliente_id) 
                                 VALUES (%s, %s, %s, %s)"""
                        
                        cursor.execute(sql, (nuevo_u, hash_cifrado.decode('utf-8'), rol, c_id))
                        conn.commit()
                        cursor.close()
                        
                        st.success(f"✅ Usuario '{nuevo_u}' registrado con seguridad profesional.")
                        st.balloons()
                    except Exception as e:
                        st.error(f"❌ Error al registrar: Probablemente el usuario ya existe. ({e})")

    # 2. TABLA DE USUARIOS ACTUALES
    st.subheader("👥 Usuarios Registrados")
    try:
        query_view = """
            SELECT u.usuario, u.rol, c.nombre_empresa as empresa_asignada 
            FROM control_central.usuarios u
            LEFT JOIN control_central.clientes c ON u.cliente_id = c.id
        """
        df_usuarios = ejecutar_consulta(query_view, conn)
        st.dataframe(df_usuarios, width='stretch')
    except Exception:
        st.info("No hay usuarios registrados todavía.")

    # 3. VISOR DE AUDITORÍA INTEGRADO
    st.divider()
    st.subheader("🕵️‍♂️ Monitoreo de Interacciones (Logs)")
    
    if st.button("🔄 Refrescar Bitácora"):
        st.rerun()
        
    try:
        query_logs = "SELECT * FROM logs_auditoria ORDER BY fecha DESC LIMIT 100"
        df_logs = ejecutar_consulta(query_logs, conn)
        
        if not df_logs.empty:
            st.dataframe(df_logs, width='stretch')
        else:
            st.info("No se han detectado interacciones todavía.")
    except Exception as e:
        st.error(f"Error cargando logs: {e}")


def panel_gestion_clientes_firma(conn):
    st.header("🏢 Gestión de Clientes de la Firma")
    st.markdown("Administra las empresas clientes que atiende la firma y provisiona sus bases de datos en la nube de forma automatizada.")
    
    rol_actual = str(st.session_state.get('rol', '')).lower()
    id_firma_actual = st.session_state.get('cliente_id')
    
    # 1. FORMULARIO DE REGISTRO DE CLIENTE DE LA FIRMA
    with st.expander("➕ Registrar Nuevo Cliente de la Firma", expanded=False):
        with st.form("registro_cliente_firma"):
            col1, col2 = st.columns(2)
            with col1:
                nombre_empresa = st.text_input("Nombre del Cliente / Razón Social", help="Ej: Inversiones Globales, C.A.")
                rif = st.text_input("RIF del Cliente", help="Ej: J-12345678-9")
            with col2:
                db_nombre = st.text_input(
                    "Nombre de la BD (Sin espacios ni caracteres raros)", 
                    help="Ej: inversiones_globales_ca"
                )
                tipo_contribuyente = st.selectbox(
                    "Tipo de Contribuyente", 
                    ["Contribuyente Ordinario", "Contribuyente Especial"]
                )
            
            # 🚫 CONTROL DE ESTADO / SUSPENSIÓN DE LICENCIA
            estado = st.selectbox(
                "Estado de la Licencia", 
                ["Activo", "Suspendido", "Inactivo"],
                help="Si se marca como 'Suspendido', los usuarios de esta firma no podrán iniciar sesión."
            )
            
            btn_guardar = st.form_submit_button("💾 Crear Cliente y Base de Datos")
            
            if btn_guardar:
                if not nombre_empresa or not db_nombre:
                    st.error("❌ El nombre del cliente y el nombre de la BD son obligatorios.")
                else:
                    try:
                        cursor = conn.cursor()
                        
                        sql = """
                            INSERT INTO control_central.clientes (nombre_empresa, rif, db_nombre, tipo_contribuyente, estado) 
                            VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(sql, (
                            nombre_empresa, 
                            rif, 
                            db_nombre, 
                            tipo_contribuyente, 
                            estado
                        ))
                        conn.commit()
                        cursor.close()
                        
                        st.info(f"🚀 Provisionando base de datos y tablas para '{db_nombre}' en TiDB Cloud...")
                        conectar_db(db_nombre)
                        
                        st.success(f"✅ ¡Cliente de la firma '{nombre_empresa}' y su base de datos fueron configurados con éxito!")
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al registrar el cliente: {e}")

    st.divider()

    # 2. TABLA DE CLIENTES DE LA FIRMA REGISTRADOS (CON CONTROL DE ESTADOS)
    st.subheader("📋 Listado de Clientes de la Firma y Estados de Licencia")
    st.markdown("💡 *Puedes cambiar el estado de cualquier firma para bloquear o permitir el acceso a sus usuarios instantáneamente.*")
    
    try:
        if rol_actual in ['admin', 'superadmin']:
            query_view = "SELECT id, nombre_empresa, rif, db_nombre, tipo_contribuyente, estado FROM control_central.clientes"
            df_clientes = ejecutar_consulta(query_view, conn)
        else:
            # 🔍 CORRECCIÓN: Trae su propia empresa y los clientes del mismo rango de la firma
            query_view = """
                SELECT id, nombre_empresa, rif, db_nombre, tipo_contribuyente, estado 
                FROM control_central.clientes 
                WHERE id = %s OR id LIKE '4200%%'
            """
            df_clientes = ejecutar_consulta(query_view, conn, params=(id_firma_actual,))
        
        if df_clientes is not None and not df_clientes.empty:
            # Mostramos un editor de datos para cambiar los estados
            edit_df = st.data_editor(
                df_clientes, 
                use_container_width=True,
                key="editor_clientes_firma",
                column_config={
                    "id": "ID",
                    "nombre_empresa": st.column_config.TextColumn("Razón Social", disabled=True),
                    "rif": st.column_config.TextColumn("RIF", disabled=True),
                    "db_nombre": st.column_config.TextColumn("Base de Datos (TiDB)", disabled=True),
                    "tipo_contribuyente": st.column_config.SelectboxColumn("Tipo de Contribuyente", options=["Contribuyente Ordinario", "Contribuyente Especial"]),
                    "estado": st.column_config.SelectboxColumn("Estado de Licencia", options=["Activo", "Suspendido", "Inactivo"])
                },
                disabled=["id", "nombre_empresa", "rif", "db_nombre"]
            )
            
            # Botón para guardar cambios de estado masivos desde la tabla
            if st.button("💾 Actualizar Estados de Licencias"):
                try:
                    cursor = conn.cursor()
                    for _, row in edit_df.iterrows():
                        cursor.execute(
                            "UPDATE control_central.clientes SET estado = %s WHERE id = %s",
                            (row['estado'], row['id'])
                        )
                    conn.commit()
                    cursor.close()
                    st.success("✅ Estados de licencias actualizados correctamente. Los bloqueos entrarán en vigor de inmediato.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al actualizar los estados en la base de datos: {e}")
        else:
            st.info("ℹ️ No hay clientes de la firma registrados todavía en el sistema.")
    except Exception as e:
        st.error(f"❌ Error al cargar la lista de clientes de la firma: {e}")


def panel_administracion_firmas(conn):
    # 🔒 Blindaje de seguridad flexible: Permitimos Superadmin y también al Administrador de la Firma
    rol_actual = str(st.session_state.get('rol', '')).lower()
    cliente_id_actual = st.session_state.get('cliente_id') # ID de la firma logueada (si es admin_firma)
    
    # Roles permitidos
    roles_permitidos = ['admin', 'superadmin', 'admin_firma']
    
    if rol_actual not in roles_permitidos:
        st.error("⛔ Acceso denegado. No tienes permisos para gestionar usuarios y accesos.")
        return  # Corta la ejecución

    st.header("🏢 Gestión de Usuarios y Accesos de la Firma")
    st.markdown("Registra un nuevo usuario para tu empresa, asígnale su rol y controla su estado de acceso inicial.")
    
    # 1. CARGAR EMPRESAS (Si es superadmin ve todas, si es admin_firma solo ve la suya)
    try:
        if rol_actual in ['admin', 'superadmin']:
            query_empresas = "SELECT id, nombre_empresa, rif, db_nombre FROM control_central.clientes"
            df_empresas = ejecutar_consulta(query_empresas, conn)
        else:
            query_empresas = "SELECT id, nombre_empresa, rif, db_nombre FROM control_central.clientes WHERE id = %s"
            df_empresas = ejecutar_consulta(query_empresas, conn, params=(cliente_id_actual,))
    except Exception:
        df_empresas = pd.DataFrame()

    with st.expander("➕ Registrar Nuevo Usuario", expanded=True):
        with st.form("registro_admin_firma"):
            col1, col2 = st.columns(2)
            
            with col1:
                nombre_usuario = st.text_input("Nombre de Usuario", help="Ej: operador_nuevo")
                contrasena = st.text_input("Contraseña", type="password", help="Contraseña de acceso")
            
            with col2:
                rol_usuario = st.selectbox(
                    "Rol del Sistema", 
                    ["contador", "asistente", "admin_firma"], 
                    help="Selecciona el rol que tendrá este usuario dentro de la firma"
                )
                
                # Selector de estado inicial de acceso para el nuevo usuario
                estado_usuario_nuevo = st.selectbox(
                    "Estado Inicial de Acceso",
                    ["Activo", "Suspendido", "Inactivo"]
                )
                
                # Selector de empresa (Si es superadmin elige, si es admin_firma se asigna su propia empresa por defecto)
                lista_nombres = []
                if not df_empresas.empty and 'nombre_empresa' in df_empresas.columns:
                    lista_nombres = df_empresas['nombre_empresa'].dropna().tolist()
                
                if lista_nombres:
                    if rol_actual in ['admin', 'superadmin']:
                        empresa_seleccionada = st.selectbox("Asociar a Empresa", options=lista_nombres)
                    else:
                        empresa_seleccionada = lista_nombres[0] # Su propia empresa fija
                        st.info(f"📌 Empresa asignada automáticamente: **{empresa_seleccionada}**")
                else:
                    empresa_seleccionada = None
                    st.warning("⚠️ No hay empresas disponibles.")

            btn_guardar = st.form_submit_button("💾 Guardar Usuario")
            
            if btn_guardar:
                if not nombre_usuario or not contrasena or not rol_usuario:
                    st.error("❌ Todos los campos obligatorios deben llenarse.")
                elif not empresa_seleccionada:
                    st.error("❌ No se encontró una empresa válida para asociar.")
                else:
                    try:
                        fila_empresa = df_empresas[df_empresas['nombre_empresa'].astype(str).str.strip() == str(empresa_seleccionada).strip()]
                        
                        if fila_empresa.empty:
                            st.error("❌ Error al identificar la empresa seleccionada.")
                        else:
                            cliente_id_asociado = int(fila_empresa.iloc[0]['id'])
                            db_nombre_asociado = str(fila_empresa.iloc[0]['db_nombre'])
                            
                            hashed_password = bcrypt.hashpw(contrasena.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            
                            cursor = conn.cursor()
                            sql = """
                                INSERT INTO control_central.usuarios (usuario, clave_hash, rol, cliente_id, db_nombre, estado) 
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """
                            cursor.execute(sql, (
                                nombre_usuario.strip(), 
                                hashed_password, 
                                rol_usuario.strip(), 
                                cliente_id_asociado, 
                                db_nombre_asociado,
                                estado_usuario_nuevo
                            ))
                            conn.commit()
                            cursor.close()
                            
                            st.success(f"✅ ¡Usuario '{nombre_usuario.strip()}' creado con éxito para la empresa '{empresa_seleccionada}' con estado **{estado_usuario_nuevo}**!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al registrar el usuario: {e}")

def panel_bloqueo_suspension_usuarios(conn):
    # 🔒 Blindaje de seguridad: Solo Superadmin o Admin de Firma pueden entrar aquí
    rol_actual = str(st.session_state.get('rol', '')).strip().lower()
    cliente_id_actual = st.session_state.get('cliente_id')
    
    if rol_actual not in ['admin', 'superadmin', 'admin_firma']:
        st.error("⛔ Acceso denegado. No tienes permisos para gestionar bloqueos o suspensiones.")
        return

    st.header("🔒 Panel de Control, Bloqueo y Suspensión de Usuarios")
    st.markdown("💡 *Modifica el estado de acceso de los usuarios directamente en la base de datos MySQL para suspender, activar o restringir su ingreso al sistema.*")

    try:
        # Si es superadmin ve a todo el mundo; si es dueño de firma, solo ve a su personal
        if rol_actual in ['admin', 'superadmin']:
            query = """
                SELECT 
                    u.id AS id_usuario, 
                    u.usuario, 
                    u.rol, 
                    u.estado, 
                    c.nombre_empresa AS empresa_asignada 
                FROM control_central.usuarios u 
                LEFT JOIN control_central.clientes c ON u.cliente_id = c.id
            """
            df_usuarios = ejecutar_consulta(query, conn)
        else:
            query = """
                SELECT 
                    u.id AS id_usuario, 
                    u.usuario, 
                    u.rol, 
                    u.estado, 
                    c.nombre_empresa AS empresa_asignada 
                FROM control_central.usuarios u 
                LEFT JOIN control_central.clientes c ON u.cliente_id = c.id
                WHERE u.cliente_id = %s
            """
            df_usuarios = ejecutar_consulta(query, conn, params=(cliente_id_actual,))

        if df_usuarios is not None and not df_usuarios.empty:
            # Editor interactivo para cambiar los estados de manera visual
            edit_df = st.data_editor(
                df_usuarios,
                use_container_width=True,
                key="editor_tabla_bloqueo_usuarios",
                column_config={
                    "id_usuario": "ID",
                    "usuario": st.column_config.TextColumn("Usuario", disabled=True),
                    "rol": st.column_config.TextColumn("Rol", disabled=True),
                    "estado": st.column_config.SelectboxColumn("Estado de Acceso", options=["Activo", "Suspendido", "Inactivo"]),
                    "empresa_asignada": st.column_config.TextColumn("Empresa / Firma", disabled=True)
                },
                disabled=["id_usuario", "usuario", "rol", "empresa_asignada"]
            )

            # Botón para guardar los cambios masivos directamente en la base de datos MySQL
            if st.button("💾 Guardar Bloqueos / Cambios en MySQL"):
                try:
                    cursor = conn.cursor()
                    for _, row in edit_df.iterrows():
                        cursor.execute(
                            "UPDATE control_central.usuarios SET estado = %s WHERE id = %s",
                            (row['estado'], row['id_usuario'])
                        )
                    conn.commit()
                    cursor.close()
                    st.success("✅ ¡Estados de acceso actualizados en MySQL con éxito! Los bloqueos ya están aplicando.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al actualizar los estados en la base de datos: {e}")
        else:
            st.info("ℹ️ No hay usuarios registrados para gestionar.")

    except Exception as e:
        st.error(f"❌ Error al consultar la base de datos: {e}")

def registrar_log_automatico(conn, accion, detalles):
    """Registra automáticamente las interacciones del usuario en la tabla logs_auditoria
    ubicada en la base de datos central de control.
    """
    cursor = None
    try:
        if conn is not None:
            usuario = st.session_state.get("usuario", "Desconocido")
            cliente_id = str(st.session_state.get("cliente_id", ""))

            cursor = conn.cursor()
            query = """
                INSERT INTO control_central.logs_auditoria (usuario_id, accion, detalles, ip_address, fecha) 
                VALUES (%s, %s, %s, %s, NOW())
            """
            cursor.execute(query, (usuario, accion, detalles, cliente_id))
            conn.commit()
    except Exception as e:
        # Manejo de error silencioso o impreso para depuración
        print(f"Error registrando log: {e}")
    finally:
        if cursor:
            cursor.close()

@st.cache_data(ttl=300)
def _obtener_datos_sidebar_cache():
    """Consulta optimizada y cacheada para evitar latencia en la nube"""
    try:
        conn_debug = conectar_db()
        if conn_debug:
            # CAMBIAMOS ejecutar_consulta POR ejecutar_consulta
            df_sidebar = ejecutar_consulta(
                "SELECT nombre_empresa, db_nombre FROM clientes WHERE estado = 'Activo' OR estado IS NULL", 
                conn_debug
            )
            conn_debug.close()
            return df_sidebar
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=300)
def obtener_todas_las_empresas(user_rol, user_id):
    conn = None
    conn_res = None
    try:
        conn = conectar_db()
        if not conn:
            return []
        
        rol_limpio = str(user_rol).strip().lower()
        
        # 1. Si es admin, mostramos todas las activas
        if rol_limpio == 'admin':
            query = "SELECT db_nombre FROM clientes WHERE estado = 'Activo' OR estado IS NULL"
            df = ejecutar_consulta(query, conn)
            if df.empty or 'db_nombre' not in df.columns:
                return []
            return df['db_nombre'].dropna().astype(str).tolist()
            
        # 2. Si es cliente, buscamos su db_nombre en la tabla usuarios
        else:
            query = """
                SELECT db_nombre FROM usuarios 
                WHERE id = %s OR cliente_id = %s
            """
            df = ejecutar_consulta(query, conn, params=(user_id, user_id))
            
            # Si viene vacío, intentamos buscar por el nombre de usuario de la sesión
            if df.empty or 'db_nombre' not in df.columns or pd.isna(df['db_nombre'].iloc[0]):
                usuario_actual = st.session_state.get('usuario')
                if usuario_actual:
                    conn_res = conectar_db()
                    if conn_res:
                        df = ejecutar_consulta("SELECT db_nombre FROM usuarios WHERE usuario = %s", conn_res, params=(usuario_actual,))
            
            if df.empty or 'db_nombre' not in df.columns or pd.isna(df['db_nombre'].iloc[0]):
                return []
                
            db_asignada = str(df['db_nombre'].iloc[0])
            return [db_asignada]
            
    except Exception as e:
        st.sidebar.error(f"❌ Error al obtener la empresa del usuario: {e}")
        return []
        
    finally:
        # Cierre seguro compatible con PyMySQL (usando .open en lugar de .is_connected)
        try:
            if conn and getattr(conn, 'open', False):
                conn.close()
        except:
            pass
        try:
            if conn_res and getattr(conn_res, 'open', False):
                conn_res.close()
        except:
            pass




def obtener_saldos_acumulados(conexion, fecha_corte, nombre_db):
    if not conexion: 
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    
    # Limpiamos directamente el nombre que viene de la sesión o del selector
    db_segura = str(nombre_db).strip()
    cur = conexion.cursor(pymysql.cursors.DictCursor)
    
    try:
        # Se conecta de forma limpia a la base de datos que toque (sea admin, firma o cliente final)
        cur.execute(f"USE `{db_segura}`")
        
        query = """
            SELECT 
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '1%%' THEN (debe - haber) ELSE 0 END), 0) as activo,
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '2%%' THEN (haber - debe) ELSE 0 END), 0) as pasivo,
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '3%%' THEN (haber - debe) ELSE 0 END), 0) as patrimonio
            FROM (
                SELECT plan_cuentas, debe, haber 
                FROM asientos_contables 
                WHERE fecha <= %s
                
                UNION ALL
                
                SELECT plan_cuentas, debe, haber 
                FROM saldos_iniciales
            ) as todo_acumulado
        """
        
        cur.execute(query, (fecha_corte,))
        resultado = cur.fetchone()
        
        return resultado if resultado else {"activo": 0, "pasivo": 0, "patrimonio": 0}

    except Exception as e:
        st.error(f"🔥 ERROR REAL EN SQL: {e}")
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    finally:
        cur.close()


@st.cache_data(ttl=300)
def obtener_datos_pie(db, fecha_inicio, fecha_fin):
    df_vacio = pd.DataFrame(columns=['nombre', 'Saldo Final'])
    conn = conectar_db(db)
    if not conn:
        return df_vacio
        
    db_segura = str(db).strip()
    
    query = (
        "SELECT descripcion as nombre, SUM(debe) as `Saldo Final` "
        f"FROM `{db_segura}`.asientos_contables "
        "WHERE plan_cuentas LIKE '6%%' "
        "AND fecha >= %s AND fecha <= %s "
        "GROUP BY descripcion "
        "HAVING SUM(debe) > 0 "
        "ORDER BY 2 DESC "
        "LIMIT 10"
    )
    
    try:
        df = ejecutar_consulta(query, conn, params=(fecha_inicio, fecha_fin))
        return df if not df.empty else df_vacio
    except Exception as e:
        print(f"Error en obtener_datos_pie: {e}")
        return df_vacio
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@st.cache_data(ttl=300)
def obtener_datos_barras(db, fecha_inicio, fecha_fin):
    df_vacio = pd.DataFrame(columns=['Categoría', 'Monto'])
    conn = conectar_db(db)
    if not conn: return df_vacio
    
    # FORZAR el nombre de la base de datos de forma segura
    db_segura = str(db).strip()
    
    # Usamos concatenación simple en lugar de f-string para evitar conflictos con %
    # Y quitamos cualquier símbolo sospechoso
    query = (
        "SELECT CASE "
        "WHEN plan_cuentas LIKE '4%%' THEN 'Ingresos' "
        "WHEN plan_cuentas LIKE '5%%' THEN 'Egresos' "
        "ELSE 'Otros' END as Categoría, "
        "SUM(haber - debe) as Monto "
        f"FROM `{db_segura}`.asientos_contables "
        "WHERE fecha >= %s AND fecha <= %s "
        "GROUP BY 1"
    )
    
    try:
        df = ejecutar_consulta(query, conn, params=(fecha_inicio, fecha_fin))
        return df if not df.empty else df_vacio
    except Exception as e:
        print(f"Error en obtener_datos_barras: {e}")
        return df_vacio
    finally:
        if conn: conn.close()


@st.cache_data(ttl=300)
def obtener_historico_utilidad(db, f_inicio=None, f_fin=None):
    conn = conectar_db(db)
    df_default = pd.DataFrame(columns=['anio', 'mes', 'mes_nombre', 'utilidad_mensual', 'utilidad_acumulada'])
    
    if not conn:
        st.warning("⚠️ No se pudo conectar a la base de datos en obtener_historico_utilidad.")
        return df_default
    
    if f_inicio is None:
        f_inicio = st.session_state.get("f_inicio_global")
    if f_fin is None:
        f_fin = st.session_state.get("f_fin_global")

    if f_inicio is None or f_fin is None:
        import datetime
        anio_actual = datetime.datetime.now().year
        f_inicio = datetime.date(anio_actual, 1, 1)
        f_fin = datetime.date.today()

    anio_base = f_inicio.year
    
    meses_skeleton = pd.DataFrame({
        'anio': [anio_base] * 12,
        'mes': list(range(1, 13))
    })

    query = """
        SELECT 
            YEAR(STR_TO_DATE(LEFT(fecha, 10), '%%Y-%%m-%%d')) as anio,
            MONTH(STR_TO_DATE(LEFT(fecha, 10), '%%Y-%%m-%%d')) as mes,
            
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%%' THEN haber ELSE 0 END) as ing_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%%' THEN debe ELSE 0 END) as ing_debe,
            
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%%' THEN debe ELSE 0 END) as cos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%%' THEN haber ELSE 0 END) as cos_haber,
            
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%%' THEN debe ELSE 0 END) as gas_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%%' THEN haber ELSE 0 END) as gas_haber,

            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%%' THEN haber ELSE 0 END) as oing_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%%' THEN debe ELSE 0 END) as oing_debe,
            
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%%' THEN debe ELSE 0 END) as oeg_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%%' THEN haber ELSE 0 END) as oeg_haber
        FROM `{db_segura}`.asientos_contables 
        WHERE YEAR(STR_TO_DATE(LEFT(fecha, 10), '%%Y-%%m-%%d')) = %s
        GROUP BY YEAR(STR_TO_DATE(LEFT(fecha, 10), '%%Y-%%m-%%d')), MONTH(STR_TO_DATE(LEFT(fecha, 10), '%%Y-%%m-%%d'))
        ORDER BY anio ASC, mes ASC
    """.format(db_segura=str(db).strip())
    
    cursor = None
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, (anio_base,))
        resultados = cursor.fetchall()
        
        # BLINDAJE: Definimos todas las columnas por si la consulta viene vacía
        columnas_requeridas = [
            'anio', 'mes', 'ing_haber', 'ing_debe', 'cos_debe', 'cos_haber',
            'gas_debe', 'gas_haber', 'oing_haber', 'oing_debe', 'oeg_debe', 'oeg_haber'
        ]
        
        if resultados:
            df_sql = pd.DataFrame(resultados)
        else:
            df_sql = pd.DataFrame(columns=columnas_requeridas)

        # Nos aseguramos de que el DataFrame tenga todas las columnas de operaciones contables
        for col in columnas_requeridas:
            if col not in df_sql.columns:
                df_sql[col] = 0

        df = pd.merge(meses_skeleton, df_sql, on=['anio', 'mes'], how='left')
        df = df.fillna(0)

        ingresos = df['ing_haber'] - df['ing_debe']
        costos = df['cos_debe'] - df['cos_haber']
        gastos = (df['gas_debe'] - df['gas_haber']).abs()
        otros_ingresos = df['oing_haber'] - df['oing_debe']
        otros_egresos = (df['oeg_debe'] - df['oeg_haber']).abs()

        df['utilidad_acumulada'] = ingresos - costos - gastos + otros_ingresos - otros_egresos
        df['utilidad_mensual'] = df['utilidad_acumulada'].diff().fillna(df['utilidad_acumulada'])
        
        dic_meses_nombres = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 
            5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 
            9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        df['mes_nombre'] = df['mes'].map(dic_meses_nombres)
        
        return df[['anio', 'mes', 'mes_nombre', 'utilidad_mensual', 'utilidad_acumulada']]
        
    except Exception as e:
        st.error(f"❌ Error crítico en `obtener_historico_utilidad`: {e}")
        st.write("Query ejecutada con anio_base:", anio_base)
        return df_default
        
    finally:
        if cursor: cursor.close()
        if conn: conn.close()



@st.cache_data(ttl=1)
def obtener_salud_fiscal(db, f_inicio=None, f_fin=None):
    if not isinstance(db, str):
        db = str(db) if db else "control_central"

    conn = conectar_db(db)
    df_default = pd.DataFrame(columns=['anio', 'mes', 'mes_nombre', 'ingresos_exentos', 'ingresos_gravados', 'compras_exentas', 'compras_16'])
    kpis_default = {
        'ingresos_exentos': 0.0, 'ingresos_gravados': 0.0, 
        'compras_exentas': 0.0, 'compras_16': 0.0,
        'DPP1': 0.0, 'comisiones_bancarias1': 0.0, 'gastos_personales1': 0.0,
        'otros_ingresos': 0.0, 'otros_egresos': 0.0,
        'iva_debito_fiscal': 0.0, 'iva_por_pagar': 0.0,
        'retencion_iva_compras': 0.0, 'pagos_anticipados_islr': 0.0,
        'retencion_islr_proveedores': 0.0, 'islr_pagar': 0.0
    }
    
    if not conn:
        st.warning("⚠️ No se pudo conectar a la base de datos en obtener_salud_fiscal.")
        return df_default, kpis_default
    
    import datetime
    
    if f_inicio is None: 
        f_inicio = st.session_state.get("f_inicio_global", datetime.date(datetime.datetime.now().year, 1, 1))
    if f_fin is None: 
        f_fin = st.session_state.get("f_fin_global", datetime.date.today())

    anio_base = f_inicio.year if hasattr(f_inicio, 'year') else datetime.datetime.now().year

    meses_skeleton = pd.DataFrame({
        'anio': [anio_base] * 12,
        'mes': list(range(1, 13))
    })

    f_inicio_anual = datetime.date(anio_base, 1, 1)
    f_fin_anual = datetime.date(anio_base, 12, 31)
    db_segura = str(db).strip()

    if db == 'kingdriver_ca':
        dpp_query = "SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.020%%' THEN haber ELSE 0 END) as DPP_haber, SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.020%%' THEN debe ELSE 0 END) as DPP_debe"
    else:
        dpp_query = """SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03%%' AND plan_cuentas NOT LIKE '6.1.1.03.013%%' AND plan_cuentas NOT LIKE '6.1.1.03.021%%' AND plan_cuentas NOT LIKE '6.1.1.03.022%%' THEN haber ELSE 0 END) as DPP_haber,
                    SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03%%' AND plan_cuentas NOT LIKE '6.1.1.03.013%%' AND plan_cuentas NOT LIKE '6.1.1.03.021%%' AND plan_cuentas NOT LIKE '6.1.1.03.022%%' THEN debe ELSE 0 END) as DPP_debe"""

    query = f"""
        SELECT 
            YEAR(CAST(fecha AS DATE)) as anio,
            MONTH(CAST(fecha AS DATE)) as mes,
            
            SUM(CASE WHEN plan_cuentas LIKE '4.1.1.01.001%%' THEN haber - debe ELSE 0 END) as exentos_acum,
            SUM(CASE WHEN plan_cuentas LIKE '4.1.1.01.002%%' THEN haber - debe ELSE 0 END) as gravados_acum,
            SUM(CASE WHEN plan_cuentas LIKE '5.1.1.01.001%%' THEN debe ELSE 0 END) as compras_exentas_acum,
            SUM(CASE WHEN plan_cuentas LIKE '5.1.1.01.002%%' THEN debe ELSE 0 END) as compras_16_acum,
            
            {dpp_query},
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.013%%' THEN haber ELSE 0 END) as comisiones_bancarias_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.013%%' THEN debe ELSE 0 END) as comisiones_bancarias_debe,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.021%%' THEN haber ELSE 0 END) as refrigerios_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.021%%' THEN debe ELSE 0 END) as refrigerios_debe,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.022%%' THEN haber ELSE 0 END) as representacion_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.022%%' THEN debe ELSE 0 END) as representacion_debe,
            SUM(CASE WHEN plan_cuentas LIKE '7.1.1.01%%' THEN haber ELSE 0 END) as otros_ingresos_haber,
            SUM(CASE WHEN plan_cuentas LIKE '7.1.1.07%%' THEN debe ELSE 0 END) as otros_ingresos_debe,
            SUM(CASE WHEN plan_cuentas LIKE '8.1.1.01%%' THEN haber ELSE 0 END) as otros_egresos_haber,
            SUM(CASE WHEN plan_cuentas LIKE '8.1.1.01%%' THEN debe ELSE 0 END) as otros_egresos_debe,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.001%%' THEN haber ELSE 0 END) as iva_debito_fiscal,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.002%%' THEN haber ELSE 0 END) as iva_por_pagar,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.003%%' THEN haber ELSE 0 END) as retencion_iva_compras,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.004%%' THEN haber ELSE 0 END) as pagos_anticipados_islr,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.005%%' THEN haber - debe ELSE 0 END) as retencion_islr_proveedores,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.006%%' THEN haber ELSE 0 END) as islr_pagar
            
        FROM `{db_segura}`.asientos_contables 
        WHERE CAST(fecha AS DATE) BETWEEN %s AND %s
        GROUP BY anio, mes
        ORDER BY anio ASC, mes ASC
    """
    
    cursor = None
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, (str(f_inicio_anual), str(f_fin_anual)))
        resultados = cursor.fetchall()
        
        columnas_fiscales = [
            'anio', 'mes', 'exentos_acum', 'gravados_acum', 'compras_exentas_acum', 'compras_16_acum',
            'DPP_haber', 'DPP_debe', 'comisiones_bancarias_haber', 'comisiones_bancarias_debe',
            'refrigerios_haber', 'refrigerios_debe', 'representacion_haber', 'representacion_debe',
            'otros_ingresos_haber', 'otros_ingresos_debe', 'otros_egresos_haber', 'otros_egresos_debe',
            'iva_debito_fiscal', 'iva_por_pagar', 'retencion_iva_compras', 'pagos_anticipados_islr',
            'retencion_islr_proveedores', 'islr_pagar'
        ]

        df_sql = pd.DataFrame(resultados) if resultados else pd.DataFrame(columns=columnas_fiscales)

        for col in columnas_fiscales:
            if col not in df_sql.columns:
                df_sql[col] = 0.0
            else:
                # CONVERSIÓN BLINDADA: Transformamos cualquier Decimal de MySQL a float limpio
                df_sql[col] = pd.to_numeric(df_sql[col], errors='coerce').fillna(0.0)

        df = pd.merge(meses_skeleton, df_sql, on=['anio', 'mes'], how='left')
        df = df.fillna(0.0)

        df['ingresos_exentos'] = df['exentos_acum'].diff().fillna(df['exentos_acum'])
        df['ingresos_gravados'] = df['gravados_acum'].diff().fillna(df['gravados_acum'])
        df['compras_exentas'] = df['compras_exentas_acum'].diff().fillna(df['compras_exentas_acum'])
        df['compras_16'] = df['compras_16_acum'].diff().fillna(df['compras_16_acum'])
        
        if len(df) > 0 and df.loc[0, 'mes'] == 1:
            df.loc[0, 'ingresos_exentos'] = df.loc[0, 'exentos_acum']
            df.loc[0, 'ingresos_gravados'] = df.loc[0, 'gravados_acum']
            df.loc[0, 'compras_exentas'] = df.loc[0, 'compras_exentas_acum']
            df.loc[0, 'compras_16'] = df.loc[0, 'compras_16_acum']

        dic_meses_nombres = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 
            5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto", 
            9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        df['mes_nombre'] = df['mes'].map(dic_meses_nombres)

        df['primer_dia_mes'] = df.apply(lambda row: datetime.date(int(row['anio']), int(row['mes']), 1), axis=1)

        df_filtrado = df[(df['primer_dia_mes'] >= datetime.date(f_inicio.year, f_inicio.month, 1)) & 
                         (df['primer_dia_mes'] <= datetime.date(f_fin.year, f_fin.month, 1))].copy()

        if df_filtrado.empty:
            df_filtrado = df.copy()

        total_exentos = df_filtrado['ingresos_exentos'].sum()
        total_gravados = df_filtrado['ingresos_gravados'].sum()
        total_compras_exentas = df_filtrado['compras_exentas'].sum()
        total_compras_16 = df_filtrado['compras_16'].sum()
        
        total_dpp = (df_filtrado['DPP_debe'] - df_filtrado['DPP_haber']).sum()
        total_comisiones = (df_filtrado['comisiones_bancarias_debe'] - df_filtrado['comisiones_bancarias_haber']).sum()
        total_gastos_pers = (df_filtrado['refrigerios_debe'] + df_filtrado['representacion_debe'] - df_filtrado['refrigerios_haber'] - df_filtrado['representacion_haber']).sum()
        total_otros_ing = (df_filtrado['otros_ingresos_haber'] - df_filtrado['otros_ingresos_debe']).sum()
        total_otros_egr = (df_filtrado['otros_egresos_debe'] - df_filtrado['otros_egresos_haber']).sum()
        
        total_iva_debito = df_filtrado['iva_debito_fiscal'].sum()
        total_iva_pagar = df_filtrado['iva_por_pagar'].sum()
        total_ret_iva = df_filtrado['retencion_iva_compras'].sum()
        total_anticipo_islr = df_filtrado['pagos_anticipados_islr'].sum()
        total_ret_islr = df_filtrado['retencion_islr_proveedores'].sum()
        total_islr_pagar = df_filtrado['islr_pagar'].sum()

        kpis_fiscales = {
            'ingresos_exentos': total_exentos,
            'ingresos_gravados': total_gravados,
            'compras_exentas': total_compras_exentas,
            'compras_16': total_compras_16,
            'DPP1': total_dpp,
            'comisiones_bancarias1': total_comisiones,
            'gastos_personales1': total_gastos_pers,
            'otros_ingresos': total_otros_ing,
            'otros_egresos': total_otros_egr,
            'iva_debito_fiscal': total_iva_debito,
            'iva_por_pagar': total_iva_pagar,
            'retencion_iva_compras': total_ret_iva,
            'pagos_anticipados_islr': total_anticipo_islr,
            'retencion_islr_proveedores': total_ret_islr,
            'islr_pagar': total_islr_pagar
        }
        
        cols_retorno = ['anio', 'mes', 'mes_nombre', 'ingresos_exentos', 'ingresos_gravados', 'compras_exentas', 'compras_16']
        return df_filtrado[cols_retorno], kpis_fiscales
        
    except Exception as e:
        st.error(f"❌ Error crítico en `obtener_salud_fiscal`: {e}")
        return df_default, kpis_default
        
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

@st.cache_data(ttl=300)
def obtener_analisis_gastos_clase6(db, fecha_inicio, fecha_fin):
    # Definimos la query de manera estática y limpia
    db_segura = str(db).strip()
    
    query = (
        "SELECT plan_cuentas, MAX(cuenta_contable) as cuenta_contable, "
        "(SUM(debe) - SUM(haber)) as total_gasto "
        f"FROM `{db_segura}`.asientos_contables "
        "WHERE plan_cuentas LIKE '6%%' "
        "AND fecha >= %s AND fecha <= %s "  # <--- AQUÍ SE CORRIGE EL ≥ y ≤
        "GROUP BY plan_cuentas "
        "HAVING total_gasto != 0 "
        "ORDER BY total_gasto DESC"
    )
    
    conn = conectar_db(db)
    if not conn:
        return pd.DataFrame()
        
    try:
        # Ejecutamos pasando parámetros
        df = ejecutar_consulta(query, conn, params=(fecha_inicio, fecha_fin))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        print(f"Error en obtener_analisis_gastos_clase6: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()


@st.cache_data(ttl=300)
def obtener_analisis_gastos_clase5(db, f_i, f_f):
    """
    Obtiene costos de Clase 5 con validación de seguridad y parámetros seguros.
    """
    # 1. Validación de Seguridad (CRÍTICA)
    if not db or not str(db).strip().replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos no seguro: {db}")

    if 'conectar_db' not in globals() and 'conectar_db' not in locals():
        print("❌ Error: La función 'conectar_db' no está definida.")
        return pd.DataFrame()

    conn = conectar_db(db)
    if conn is None:
        print("❌ Error: 'conectar_db' devolvió None (revisa tus credenciales o conexión a TiDB Cloud).")
        return pd.DataFrame()
    
    # Asegurar rango de hora completo para evitar perder registros del último día
    f_i_str = str(f_i).split()[0] + " 00:00:00"
    f_f_str = str(f_f).split()[0] + " 23:59:59"

    query = f"""
        SELECT 
            plan_cuentas, 
            CASE 
                WHEN plan_cuentas = '5.1.1.01.001' THEN 'Costos de Reparaciones de vehiculos'
                WHEN plan_cuentas = '5.1.1.01.002' THEN 'Iva Credito Fiscal (Ingresos Exentos)'
                ELSE 'Otros'
            END as descripcion, 
            (SUM(debe) - SUM(haber)) as total_gasto
        FROM `{db}`.asientos_contables 
        WHERE plan_cuentas IN ('5.1.1.01.001', '5.1.1.01.002')
          AND fecha >= %s AND fecha <= %s
        GROUP BY plan_cuentas
        HAVING total_gasto != 0
        ORDER BY total_gasto DESC
    """
    try:
        # CORREGIDO: Usamos ejecutar_consulta en lugar de pd.read_sql para soportar PyMySQL y parámetros correctamente
        df = ejecutar_consulta(query, conn, params=(f_i_str, f_f_str))
    except Exception as e:
        print(f"❌ Error en Clase 5: {e}")
        df = pd.DataFrame()
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass
        
    return df



@st.cache_data(ttl=300)
def obtener_historico_utilidad_acumulada(db, año=2026, mes_limite=6):
    df_default = pd.DataFrame({'mes': [], 'utilidad_mensual': []})
    
    # 1. Validación de Seguridad Estricta para el nombre de la BD
    if not db or not str(db).replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos inválido: {db}")

    # 2. Blindaje de Conexión
    if 'conectar_db' not in globals() and 'conectar_db' not in locals():
        print("❌ Error crítico: 'conectar_db' no está definida.")
        return df_default
        
    conn = conectar_db(db)
    if not conn:
        return df_default
        
    try:
        año = int(año)
        mes_limite = int(mes_limite)
    except (TypeError, ValueError):
        año = 2026
        mes_limite = 6

    # 3. Consulta 100% Segura usando Parámetros (%s) y caracteres escapados (%%)
    query = f"""
        SELECT 
            MONTH(STR_TO_DATE(fecha, '%%Y-%%m-%%d')) as mes,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%%' THEN haber ELSE 0 END) as ingresos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%%' THEN debe ELSE 0 END) as ingresos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%%' THEN haber ELSE 0 END) as costos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%%' THEN debe ELSE 0 END) as costos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%%' THEN haber ELSE 0 END) as gastos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%%' THEN debe ELSE 0 END) as gastos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%%' THEN haber ELSE 0 END) as otros_ingresos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%%' THEN debe ELSE 0 END) as otros_ingresos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%%' THEN haber ELSE 0 END) as otros_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%%' THEN debe ELSE 0 END) as oitros_debe
        FROM `{db}`.asientos_contables 
        WHERE YEAR(STR_TO_DATE(fecha, '%%Y-%%m-%%d')) = %s 
          AND MONTH(STR_TO_DATE(fecha, '%%Y-%%m-%%d')) <= %s
        GROUP BY MONTH(STR_TO_DATE(fecha, '%%Y-%%m-%%d'))
        ORDER BY mes ASC
    """
    
    try:
        df = ejecutar_consulta(query, conn, params=(año, mes_limite))
        if df.empty:
            return df_default
            
        df = df.fillna(0)

        df['utilidad_mensual'] = (
            (df['ingresos_haber'] - df['ingresos_debe']) - 
            (df['costos_debe'] - df['costos_haber']) - 
            (df['gastos_debe'] - df['gastos_haber']) + 
            (df['otros_ingresos_haber'] - df['otros_ingresos_debe']) - 
            (df['oitros_debe'] - df['otros_haber'])
        )
        
        return df[['mes', 'utilidad_mensual']]
        
    except Exception as e:
        print(f"Error al calcular histórico acumulado: {e}")
        return df_default
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@st.cache_data(ttl=300)
def obtener_asiento_por_comprobante(db, n_comprobante):
    # 1. Validación de seguridad estricta para prevenir Inyección SQL en el esquema
    if not db or not db.replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos inválido: {db}")

    conn = conectar_db(db)
    if not conn:
        return pd.DataFrame()
    
    try:
        # Trae TODAS las líneas que pertenecen a ese número de comprobante de forma segura
        query = f"""
            SELECT 
                id, 
                n_comprobante, 
                descripcion, 
                fecha, 
                plan_cuentas, 
                cuenta_contable, 
                referencia, 
                debe, 
                haber
            FROM `{db}`.asientos_contables 
            WHERE n_comprobante = %s
            ORDER BY id ASC
        """
        # Parámetro seguro para evitar inyección SQL
        df = ejecutar_consulta(query, conn, params=(str(n_comprobante),))
        
        if not df.empty:
            df['debe'] = pd.to_numeric(df['debe'], errors='coerce').fillna(0.0)
            df['haber'] = pd.to_numeric(df['haber'], errors='coerce').fillna(0.0)
            
        return df
    except Exception as e:
        print(f"Error al obtener asiento completo en TiDB: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@st.cache_data(ttl=300)
def obtener_analisis_accionista_detallado(db, f_i, f_f):
    if not db or not str(db).strip().replace("_", "").isalnum():
        return pd.DataFrame()

    db_clean = str(db).strip().lower()
    conn = conectar_db(db)
    
    # Eliminamos el .is_connected() aquí
    if not conn:
        return pd.DataFrame()

    s_fi = str(f_i).split()[0]
    s_ff = str(f_f).split()[0]
    
    df = pd.DataFrame()
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE LOWER(table_schema) = %s AND table_name = 'asientos_contables'
        """, (db_clean,))
        existe_asientos = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE LOWER(table_schema) = %s AND table_name = 'accionistas'
        """, (db_clean,))
        existe_accionistas = cursor.fetchone()[0]
        cursor.close()

        if existe_asientos > 0 and existe_accionistas > 0:
            query = f"""
                SELECT 
                    a.plan_cuentas, 
                    a.fecha, 
                    a.descripcion, 
                    a.debe, 
                    a.haber, 
                    (a.debe - a.haber) as neto,
                    acc.nombre as nombre_accionista
                FROM `{db}`.asientos_contables a
                INNER JOIN `{db}`.accionistas acc ON TRIM(a.plan_cuentas) = TRIM(acc.codigo_cuenta_asociada)
                WHERE DATE(a.fecha) BETWEEN %s AND %s
                ORDER BY a.fecha DESC
            """
            df = ejecutar_consulta(query, conn, params=(s_fi, s_ff))
        else:
            st.warning(f"⚠️ Verificación fallida: tablas no encontradas en '{db}'.")
            
    except Exception as e:
        st.error(f"Error en la consulta de accionistas: {e}")
        df = pd.DataFrame()
    finally:
        # Eliminamos el .is_connected() aquí y cerramos directamente
        if conn:
            try:
                conn.close()
            except:
                pass
                
    return df

@st.cache_data(ttl=300)
def obtener_comprobantes_ingresos(db, f_inicio, f_fin):
    # Usamos f-strings solo para la base de datos (seguro) 
    # y dejamos los %s para los valores de la query.
    db_segura = str(db).strip()
    query = (
        f"SELECT DISTINCT n_comprobante, fecha "
        f"FROM `{db_segura}`.asientos_contables "
        "WHERE plan_cuentas LIKE '7.1.1.01.001%%' "
        "AND fecha BETWEEN %s AND %s "
        "ORDER BY fecha DESC, n_comprobante DESC"
    )
    
    conn = conectar_db(db)
    if not conn:
        return pd.DataFrame()
        
    try:
        # Pasa los parámetros en una tupla, NO formatees la string tú mismo
        df = ejecutar_consulta(query, conn, params=(f_inicio, f_fin))
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        print(f"Error en obtener_comprobantes_ingresos: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()


def actualizar_tabla_completa_db(conn, nombre_tabla, df_nuevo):
    """
    Actualización genérica segura: hace TRUNCATE y luego inserta el DF completo.
    """
    if not conn or not conn.is_connected():
        raise Exception("No hay conexión activa a la base de datos.")

    # 🛡️ SEGURIDAD: Validar que el nombre de la tabla contenga solo caracteres alfanuméricos y guiones bajos
    if not re.match(r"^[a-zA-Z0-9_]+$", nombre_tabla):
        raise ValueError(f"Nombre de tabla inválido o inseguro: {nombre_tabla}")

    # 🛡️ SEGURIDAD: Validar que los nombres de las columnas también sean seguros
    for col in df_nuevo.columns:
        if not re.match(r"^[a-zA-Z0-9_]+$", str(col)):
            raise ValueError(f"Nombre de columna inválido o inseguro: {col}")

    cursor = conn.cursor()
    try:
        # 1. Limpiar tabla de forma segura usando backticks para delimitar la tabla
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        cursor.execute(f"TRUNCATE TABLE `{nombre_tabla}`")
        
        # 2. Generar el INSERT dinámico de forma segura con columnas validadas
        columnas = ", ".join([f"`{col}`" for col in df_nuevo.columns])
        placeholders = ", ".join(["%s"] * len(df_nuevo.columns))
        sql = f"INSERT INTO `{nombre_tabla}` ({columnas}) VALUES ({placeholders})"
        
        # 3. Insertar datos de forma masiva
        datos = [tuple(row) for row in df_nuevo.values]
        cursor.executemany(sql, datos)
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        raise e 
    finally:
        # Garantizar por seguridad que las llaves foráneas siempre se vuelven a activar
        try:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        except:
            pass
            
        if cursor:
            cursor.close()



def consultar_tabla_db(conn, nombre_tabla, limite=None):
    # 1. Validar nombre de tabla para evitar inyección SQL
    if not re.match(r"^[a-zA-Z0-9_]+$", str(nombre_tabla)):
        st.error(f"Nombre de tabla inseguro: {nombre_tabla}")
        return None

    if not conn:
        st.error("No hay conexión activa.")
        return None

    try:
        # 2. Construcción directa de la consulta para la tabla exacta (ej. 'plan_cuentas')
        query = f"SELECT * FROM `{nombre_tabla}`"
        
        if limite and isinstance(limite, int):
            query += f" LIMIT {limite}"
            
        # 3. Ejecutar a través de tu gestor de consultas
        df = ejecutar_consulta(query, conn)
        return df

    except Exception as e:
        st.error(f"Error consultando {nombre_tabla}: {e}")
        return None


@st.cache_data(ttl=300)
def obtener_datos_agente_db(valor_busqueda):
    # Usamos una versión 'v2' para que Streamlit detecte que es una función nueva
    return _obtener_datos_agente_db_v2(valor_busqueda)

def _obtener_datos_agente_db_v2(valor_busqueda):
    conn_central = conectar_db() 
    if not conn_central: 
        return None

    cursor = None
    try:
        cursor = conn_central.cursor(pymysql.cursors.DictCursor)
        
        # CONSULTA LIMPIA: Solo pedimos columnas que sabemos que existen según tu captura de pantalla
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif, db_nombre, estado FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif, db_nombre, estado FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        return datos
        
    except Exception as e:
        st.error(f"❌ Error interno de consulta: {e}")
        return None
        
    finally:
        if cursor: cursor.close()
        if conn_central: conn_central.close()


def consultar_libro_diario_db(conn_activa=None, fecha_inicio=None, fecha_fin=None):
    # 1. Seguridad y Contexto
    usuario = st.session_state.get('usuario', 'Desconocido')
    cliente = st.session_state.get('cliente_id', 'N/A')
    db_a_usar = st.session_state.get('DB_ACTUAL')
    
    if not db_a_usar:
        return pd.DataFrame()

    # 2. Conexión Inteligente
    es_conexion_interna = False
    if conn_activa:
        conn = conn_activa
    else:
        conn = conectar_db(db_a_usar)
        es_conexion_interna = True
    
    if not conn:
        return pd.DataFrame()

    # 3. Registrar el log de forma segura
    try:
        registrar_log_automatico(conn, "CONSULTA_LIBRO_DIARIO", f"Usuario {usuario} consultó libro diario para {cliente}")
    except Exception as log_error:
        print(f"No se pudo registrar el log: {log_error}")

    try:
        # 4. Preparar consulta
        if fecha_inicio and fecha_fin:
            query = "SELECT * FROM asientos_contables WHERE fecha BETWEEN %s AND %s ORDER BY id ASC"
            params = (fecha_inicio, fecha_fin)
        else:
            query = "SELECT * FROM asientos_contables ORDER BY id ASC"
            params = None
        
        # 5. Ejecución con pandas/ejecutar_consulta
        df = ejecutar_consulta(query, conn, params=params)
        
        # 6. Normalización Universal
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            
            mapeo = {
                'plan_cuentas': 'plan_de_cuentas',
                'cuenta': 'plan_de_cuentas',
                'monto_debe': 'debe',
                'monto_haber': 'haber',
                'debito': 'debe',
                'credito': 'haber'
            }
            df.rename(columns=mapeo, inplace=True)
            
            # Verificación de integridad
            if 'debe' not in df.columns or 'haber' not in df.columns:
                st.warning(f"⚠️ Estructura incompatible. Columnas detectadas: {df.columns.tolist()}")
                return pd.DataFrame()
            
            return df
        
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"Error procesando libro diario: {e}")
        return pd.DataFrame()
        
    finally:
        # Cierre seguro adaptado a PyMySQL / Conectores genéricos
        if es_conexion_interna and conn:
            try:
                conn.close()
            except Exception:
                pass


def actualizar_libro_diario_en_db(db_nombre, df_cambios):
    conn = conectar_db(db_nombre)
    if not conn:
        return False
        
    cursor = conn.cursor()
    try:
        sql = """
            UPDATE asientos_contables 
            SET n_comprobante = %s, descripcion = %s, fecha = %s, 
                plan_cuentas = %s, cuenta_contable = %s, referencia = %s, 
                debe = %s, haber = %s 
            WHERE id = %s
        """
        
        # 1. Preparar una lista de tuplas con todos los datos de forma masiva
        datos_a_actualizar = [
            (
                row['n_comprobante'], 
                row['descripcion'], 
                row['fecha'], 
                row['plan_de_cuentas'], 
                row['cuenta_contable'], 
                row['referencia'], 
                float(row['debe']), 
                float(row['haber']), 
                int(row['id'])
            )
            for _, row in df_cambios.iterrows()
        ]
        
        # 2. Ejecutar todas las actualizaciones en una sola llamada optimizada
        cursor.executemany(sql, datos_a_actualizar)
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback() # Revertir cambios si algo falla a mitad de lote
        st.error(f"Error técnico en SQL: {str(e)}")
        return False
    finally:
        if cursor:
            cursor.close()
        # Cierre seguro compatible con PyMySQL
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def cargar_estado_cuenta_bdv(uploaded_file, conn):
    # 1. Recuperamos las variables del estado global
    mes_sel = st.session_state.get('mes_seleccionado')
    ano_sel = st.session_state.get('ano_seleccionado')

    # 2. Validación de seguridad
    if not mes_sel or not ano_sel:
        st.error("❌ No se ha seleccionado mes o año en el dashboard.")
        return False

    # 3. Verificamos si el mes está cerrado
    if mes_esta_cerrado(conn, mes_sel, ano_sel):
        st.error("❌ No se pueden realizar cambios. El mes está bloqueado.")
        return False
    
    # Registro de actividad
    usuario_actual = st.session_state.get('usuario', 'Desconocido')
    cliente_actual = st.session_state.get('cliente_id', 'N/A')
    registrar_log_automatico(conn, "CARGA_ESTADO_CUENTA", f"Usuario {usuario_actual} cargó estado de cuenta para {cliente_actual}")
    
    cursor = conn.cursor(buffered=True)
    try:
        # 2. Leemos el archivo
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.str.strip()
        
        movimientos_insertados = 0
        
        # 3. Procesamos filas de forma segura
        for index, row in df.iterrows():
            if pd.isna(row.get('Referencia')): 
                continue
            
            fecha_str = pd.to_datetime(row['Fecha']).strftime('%Y-%m-%d')
            
            # Limpieza de montos (asegurando que sean floats)
            debito = float(str(row.get('Débito', 0)).replace('.', '').replace(',', '.')) if pd.notna(row.get('Débito')) else 0
            credito = float(str(row.get('Crédito', 0)).replace('.', '').replace(',', '.')) if pd.notna(row.get('Crédito')) else 0
            monto = credito - debito
            
            query = """
                INSERT INTO banco_movimientos 
                (banco_nombre, cuenta_numero, fecha_movimiento, referencia, descripcion, monto, estado_conciliacion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            valores = ('BDV', '0102', fecha_str, str(row['Referencia']), str(row['Descripción']), monto, 'Pendiente')
            
            cursor.execute(query, valores)
            movimientos_insertados += 1
            
        conn.commit()
        st.success(f"✅ ¡Éxito! Se guardaron {movimientos_insertados} registros.")
        
        return True  
        
    except Exception as e:
        conn.rollback() # Revertir cambios si algo falla
        st.error(f"❌ Error al procesar el archivo: {e}")
        return False
        
    finally:
        if cursor:
            cursor.close() 
        # Aquí eliminamos la llamada a .is_connected()
        if conn:
            try:
                conn.ping(reconnect=True)
            except Exception:
                pass



def mostrar_tablero_conciliacion(conn, mes_sel, ano_sel):
    st.title("⚖️ Conciliación Bancaria")

    # 1. RECUPERAR CONTEXTO GLOBAL (Sin modificar la barra lateral ni hacer loops)
    db = st.session_state.get('DB_ACTUAL')
    if not db:
        st.warning("⚠️ No se ha seleccionado una base de datos activa.")
        return

    # 2. PREPARACIÓN DE FECHAS
    meses_dict = {
        "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04", 
        "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08", 
        "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
    }
    mes_num = meses_dict[mes_sel]
    fecha_inicio = f"{ano_sel}-{mes_num}-01"
    ultimo_dia = calendar.monthrange(int(ano_sel), int(mes_num))[1]
    fecha_fin = f"{ano_sel}-{mes_num}-{ultimo_dia:02d}"

    # Cálculo dinámico del mes anterior para el saldo inicial en libros
    meses_lista = list(meses_dict.keys())
    idx_mes_actual = meses_lista.index(mes_sel)
    if idx_mes_actual == 0:
        mes_anterior = "Diciembre"
        ano_anterior = str(int(ano_sel) - 1)
    else:
        mes_anterior = meses_lista[idx_mes_actual - 1]
        ano_anterior = str(ano_sel)

    # 3. CARGA DE BANCOS (Usando la DB ya seleccionada)
    cursor = conn.cursor()
    try:
        query_bancos = f"SELECT nombre, codigo FROM `{db}`.plan_cuentas WHERE nombre LIKE '%BANCO%' AND tipo = 'Detalle'"
        cursor.execute(query_bancos)
        bancos_dict = {b[0]: b[1] for b in cursor.fetchall()}
        
        if not bancos_dict:
            st.warning("No se encontraron cuentas bancarias.")
            return

        # Selector de Banco seguro dentro del cuerpo (evita el bucle de sidebar)
        nombre_banco_sel = st.selectbox("Seleccione Banco", list(bancos_dict.keys()), key="select_banco_tablero_seguro")
        cuenta_codigo = bancos_dict[nombre_banco_sel]
        
        # Transformación de nombre para la BD (Alias)
        banco_db = obtener_alias_banco(nombre_banco_sel)

        # 4. CONSULTAS PRINCIPALES
        # A. Saldo Banco
        sql_saldos = f"""SELECT saldo_inicial, saldo_final 
                        FROM `{db}`.saldos_bancarios 
                        WHERE banco = %s AND mes = %s AND ano = %s"""
        cursor.execute(sql_saldos, (banco_db, mes_sel, str(ano_sel)))
        res_banco = cursor.fetchone()
        saldo_inicial, saldo_final_banco = (float(res_banco[0]), float(res_banco[1])) if res_banco else (0.0, 0.0)

        # B. Saldo Libros (Dinámico con el mes anterior correcto)
        query_saldo_anterior = f"""
            SELECT saldo_final 
            FROM `{db}`.saldos_bancarios 
            WHERE banco = %s AND mes = %s AND ano = %s
        """
        cursor.execute(query_saldo_anterior, (banco_db, mes_anterior, str(ano_anterior)))
        res_anterior = cursor.fetchone()
        saldo_mes_anterior = float(res_anterior[0]) if res_anterior else 0.0

        # Obtener movimientos del mes seleccionado de forma segura
        query_movimientos_mes = f"""
            SELECT IFNULL(SUM(debe), 0.0), IFNULL(SUM(haber), 0.0) 
            FROM `{db}`.asientos_contables 
            WHERE TRIM(cuenta_contable) = TRIM(%s) 
            AND fecha BETWEEN %s AND %s
        """
        cursor.execute(query_movimientos_mes, (nombre_banco_sel, fecha_inicio, fecha_fin))
        debe_mes, haber_mes = cursor.fetchone()

        # Cálculo final de libros
        saldo_final_libros = saldo_mes_anterior + (float(debe_mes) - float(haber_mes))

        # C. Movimientos de Banco (Pendientes y Conciliados)
        query_mov_pendientes = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = 'Pendiente' AND fecha_movimiento BETWEEN %s AND %s"
        df_banco = ejecutar_consulta(query_mov_pendientes, conn, params=(fecha_inicio, fecha_fin))

        query_mov_conciliados = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = 'Conciliado' AND fecha_movimiento BETWEEN %s AND %s"
        df_conciliado = ejecutar_consulta(query_mov_conciliados, conn, params=(fecha_inicio, fecha_fin))

    except Exception as e:
        st.error(f"Error en la consulta para {db}: {e}")
        df_banco = pd.DataFrame()
        df_conciliado = pd.DataFrame()
        saldo_final_libros = 0.0
        saldo_inicial = 0.0
        saldo_final_banco = 0.0
    finally:
        cursor.close()

    # 5. VISUALIZACIÓN
    st.subheader("📊 Historial y Cuadre de Saldos")
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Saldo Inicial", f"{saldo_inicial:,.2f}")
    m2.metric("Saldo Final Libros", f"{saldo_final_libros:,.2f}")
    m3.metric("Saldo Final Banco", f"{saldo_final_banco:,.2f}")
    
    diferencia = round(saldo_final_libros - saldo_final_banco, 2)
    if abs(diferencia) <= 0.01:
        st.success(f"✅ ¡Conciliación Correcta! (Diferencia: {diferencia:,.2f})")
    else:
        st.error(f"⚠️ Diferencia detectada: {diferencia:,.2f}. Revisa los movimientos pendientes.")

    st.subheader("📥 Pendientes por Conciliar")
    col_p1, col_p2 = st.columns(2)
    col_p1.write("📥 Ingresos Pendientes")
    col_p1.dataframe(df_banco[df_banco['monto'] > 0] if not df_banco.empty else pd.DataFrame(), use_container_width=True)
    col_p2.write("📤 Egresos Pendientes")
    col_p2.dataframe(df_banco[df_banco['monto'] < 0] if not df_banco.empty else pd.DataFrame(), use_container_width=True)
        
    if 'saldo_final_libros' not in st.session_state:
        st.session_state.saldo_final_libros = 0.0

    if st.button("🚀 Ejecutar Conciliación", key="btn_ejecutar_conciliacion_tablero"):
        resultado = conciliar_datos(conn, fecha_inicio, fecha_fin, db)
        st.session_state.saldo_final_libros = resultado
        st.success("Conciliación ejecutada con éxito.")
        st.rerun()

    # 6. LÓGICA DE PDF CENTRALIZADA
    st.divider()
    st.subheader("📄 Reporte de Conciliación")
    
    lista_ingresos = df_banco[df_banco['monto'] > 0].to_dict('records') if not df_banco.empty else []
    lista_egresos = df_banco[df_banco['monto'] < 0].to_dict('records') if not df_banco.empty else []
    
    diferencia_pdf = round(saldo_final_banco - saldo_final_libros, 2)
    if abs(diferencia_pdf) > 0.01:
        partida_ajuste = {"fecha_movimiento": fecha_fin, "referencia": "AJUSTE", "descripcion": "Diferencia por redondeo", "monto": diferencia_pdf}
        if diferencia_pdf > 0: 
            lista_ingresos.append(partida_ajuste)
        else: 
            lista_egresos.append(partida_ajuste)

    try:
        pdf_data = crear_pdf_conciliacion(
            conn, df_conciliado, saldo_inicial, saldo_final_banco, saldo_final_libros, lista_ingresos, lista_egresos
        )
        st.download_button(
            label="📄 Descargar Conciliación PDF", 
            data=pdf_data, 
            file_name=f"conciliacion_{mes_sel}_{ano_sel}.pdf", 
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Error generando el PDF: {e}")

    # 7. MOVIMIENTOS CONCILIADOS
    if not df_conciliado.empty:
        st.subheader("✅ Movimientos Conciliados")
        col_d, col_h = st.columns(2)
        col_d.write("Ingresos")
        col_d.dataframe(df_conciliado[df_conciliado['monto'] > 0], use_container_width=True)
        col_h.write("Egresos")
        col_h.dataframe(df_conciliado[df_conciliado['monto'] < 0], use_container_width=True)
    else:
        st.info("ℹ️ No hay movimientos conciliados en este periodo.")


# Definido a nivel global para evitar recrearlo en cada llamada
_MAPEO_BANCOS = {
    "Banco de Venezuela": "BDV",
    "Banesco": "Banesco",
    "Banco Mercantil": "Mercantil"
}

def obtener_alias_banco(nombre_ui):
    """
    Garantiza que siempre busques el nombre correcto en la tabla 
    mapeando el nombre de la interfaz al alias de la base de datos.
    """
    if not nombre_ui:
        return nombre_ui
        
    # Limpiamos espacios en blanco accidentales al inicio o final
    nombre_limpio = nombre_ui.strip()
    
    return _MAPEO_BANCOS.get(nombre_limpio, nombre_limpio)

# ==========================================
# 1. Función de datos (Pura y cacheada para acelerar TiDB Cloud)
# ==========================================
@st.cache_data(ttl=600)  # Guarda en caché por 10 minutos
def _obtener_datos_asiento(db_nombre, numero_comprobante):
    conn = conectar_db(db_nombre)
    if not conn:
        return None
    try:
        # CORREGIDO: Se antepone `{db_nombre}.` para apuntar correctamente a la base de datos activa
        query = f"""
            SELECT 
                fecha, 
                descripcion, 
                n_comprobante,
                cuenta_contable AS codigo, 
                plan_cuentas AS nombre, 
                debe, 
                haber
            FROM `{db_nombre}`.asientos_contables 
            WHERE n_comprobante = %s
        """
        # Se pasa el parámetro de forma segura a ejecutar_consulta
        return ejecutar_consulta(query, conn, params=(numero_comprobante,))
    except Exception as e:
        print(f"Error en consulta: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ==========================================
# 2. Función visual (Sin caché, encargada de renderizar la UI de Streamlit)
# ==========================================
def disenar_reporte_asiento_contable(numero_comprobante):
    db_nombre = st.session_state.get('DB_ACTUAL', 'kingdirver_ca')
    
    # Llamamos a la función de datos cacheada pasando la base de datos activa
    df_asiento = _obtener_datos_asiento(db_nombre, numero_comprobante)

    if df_asiento is None or df_asiento.empty:
        st.warning(f"⚠️ No se encontró data para el comprobante Nº: {numero_comprobante}")
        return

    # --- DISEÑO E INTERFAZ ---
    st.markdown("---")
    col_logo, col_info = st.columns([1, 3])
    with col_logo:
        st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=80)
    with col_info:
        # Nota: Asegúrate de que la variable EMPRESA esté definida o usa empresa_data si lo prefieres
        empresa_nombre = st.session_state.get('nombre_empresa', 'Empresa')
        st.markdown(f"## {empresa_nombre}")
        st.markdown(f"**RIF:** J-50775718-8")
        st.markdown(f"<p style='text-align: right; color: gray;'>Generado: {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}</p>", unsafe_allow_html=True)

    st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>Asiento Contable</h1>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; font-weight: bold;'>Comprobante Nº: {numero_comprobante}</p>", unsafe_allow_html=True)
    st.markdown("---")

    c1, c2 = st.columns(2)
    c1.info(f"**📅 Fecha:** {df_asiento['fecha'].iloc[0]}")
    c2.info(f"**📝 Descripción:** {df_asiento['descripcion'].iloc[0]}")
    
    st.markdown("---")

    df_mostrar = df_asiento[['codigo', 'nombre', 'debe', 'haber']].copy()
    df_mostrar.columns = ['Código Cuenta', 'Plan de Cuentas', 'Debe (Bs.)', 'Haber (Bs.)']

    st.dataframe(
        df_mostrar.style.format({
            'Debe (Bs.)': formato_contable,
            'Haber (Bs.)': formato_contable
        }), 
        use_container_width=True, 
        hide_index=True
    )

    # Verificación de columnas antes de operar para evitar errores de ejecución
    if 'debe' in df_asiento.columns and 'haber' in df_asiento.columns:
        t_debe = df_asiento['debe'].sum()
        t_haber = df_asiento['haber'].sum()
        dif = t_debe - t_haber

        st.divider()

        ct1, ct2 = st.columns(2)
        ct1.metric("TOTAL DEBE", f"Bs. {formato_contable(t_debe)}")
        ct2.metric("TOTAL HABER", f"Bs. {formato_contable(t_haber)}")

        if abs(dif) < 0.01:
            st.success("✅ Partida Doble Cuadrada")
        else:
            st.error(f"❌ Descuadre Detectado: Bs. {formato_contable(dif)}")
    else:
        st.error("❌ Los datos del comprobante están incompletos.")



def consultar_saldos_iniciales_db(db_nombre):
    """
    Consulta los saldos iniciales de la empresa activa de forma rápida y directa.
    """
    if not db_nombre:
        return pd.DataFrame()

    conn = None
    cursor = None
    
    try:
        # Conexión directa a la BD del cliente
        conn = conectar_db(db_nombre)
        
        # Validación simplificada (sin .is_connected)
        if conn:
            cursor = conn.cursor(dictionary=True)
            query = "SELECT * FROM saldos_iniciales ORDER BY id ASC"
            cursor.execute(query)
            
            resultados = cursor.fetchall()
            return pd.DataFrame(resultados) if resultados else pd.DataFrame()
        else:
            st.error("❌ No se pudo establecer conexión con la base de datos.")
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"❌ Error en la consulta de saldos en {db_nombre}: {e}")
        return pd.DataFrame()
        
    finally:
        # Cierre estricto de recursos para liberar el socket en TiDB Cloud
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def mostrar_interfaz_mayor(f_ini_g, f_fin_g, db_nombre):
    st.subheader("📖 Libro Mayor Analítico")

    # 1. ESTADOS DE SESIÓN
    cuenta_previa = st.session_state.get('cuenta_a_buscar', "")
    if 'reporte_mayor' not in st.session_state: st.session_state.reporte_mayor = None
    if 'movs_solos' not in st.session_state: st.session_state.movs_solos = None
    if 'cuenta_actual' not in st.session_state: st.session_state.cuenta_actual = ""

    conn = conectar_db(db_nombre)
    cursor = None
    
    if conn:
        try:
            cursor = conn.cursor()
            
            # Auditoría y consulta de cuentas de forma segura (sin interpolar db_nombre)
            usuario = st.session_state.get('usuario', 'Desconocido')
            registrar_log_automatico(conn, "CONSULTA_LIBRO_MAYOR", f"Usuario {usuario} consultó mayor en {db_nombre}")
            
            query_cuentas = "SELECT DISTINCT cuenta_contable FROM asientos_contables ORDER BY cuenta_contable"
            df_cuentas = ejecutar_consulta(query_cuentas, conn)
            
            if not df_cuentas.empty:
                lista_opciones = df_cuentas['cuenta_contable'].tolist()
                idx_inicial = lista_opciones.index(cuenta_previa) if cuenta_previa in lista_opciones else 0
                
                cuenta_sel = st.selectbox("Seleccione cuenta de detalle:", lista_opciones, index=idx_inicial)
                
                col1, col2 = st.columns(2)
                f_m_d = col1.date_input("Desde", f_ini_g, key="m_d")
                f_m_h = col2.date_input("Hasta", f_fin_g, key="m_h")
                
                saldo_inicial_periodo = 0.0

                if st.button("🔍 Generar Movimientos"):
                    # Asumimos que ejecutar_mayor_analitico retorna el reporte completo y los movimientos puros
                    res_reporte, saldo_inicial_periodo = ejecutar_mayor_analitico(db_nombre, cuenta_sel, f_m_d, f_m_h)
                    
                    if not res_reporte.empty:
                        st.session_state.reporte_mayor = res_reporte
                        # Guardamos también los movimientos puros si la función los retorna, o usamos el mismo reporte
                        st.session_state.movs_solos = res_reporte 
                        
                        st.session_state.saldo_final_reporte = saldo_inicial_periodo + res_reporte['debe'].sum() - res_reporte['haber'].sum()
                        st.session_state.cuenta_actual = cuenta_sel
                    else:
                        st.warning("No se obtuvieron datos.")
                        st.session_state.reporte_mayor = None
                        st.session_state.movs_solos = None

                st.divider()

                if st.session_state.reporte_mayor is not None:
                    reporte = st.session_state.reporte_mayor
                    movs_solos = st.session_state.movs_solos
                    
                    if not reporte.empty and movs_solos is not None:
                        t_debe = movs_solos['debe'].sum()
                        t_haber = movs_solos['haber'].sum()
                        s_final = st.session_state.get('saldo_final_reporte', 0.0)

                        m1, m2, m3 = st.columns(3)
                        m1.metric("TOTAL DEBE", f"Bs. {t_debe:,.2f}")
                        m2.metric("TOTAL HABER", f"Bs. {t_haber:,.2f}")
                        m3.metric("SALDO FINAL", f"Bs. {s_final:,.2f}")

                        fmt = {'debe': '{:,.2f}', 'haber': '{:,.2f}', 'Saldo': '{:,.2f}'}
                        st.dataframe(
                            reporte.style.format(fmt), 
                            width='stretch', 
                            hide_index=True
                        )
                        
                        if st.button("📄 Generar Reporte PDF para Auditoría"):
                            try:
                                from fpdf import FPDF
                                
                                class PDF(FPDF):
                                    def header(self):
                                        self.set_font('Arial', 'B', 14)
                                        self.cell(0, 10, 'KING DRIVER, C.A. - LIBRO MAYOR ANALÍTICO', ln=True, align='C')
                                        self.set_font('Arial', 'I', 10)
                                        self.cell(0, 5, f'Período: {f_m_d.strftime("%d/%m/%Y")} al {f_m_h.strftime("%d/%m/%Y")}', ln=True, align='C')
                                        self.ln(10)

                                pdf = PDF()
                                pdf.add_page()
                                pdf.set_font("Arial", 'B', 10)
                                pdf.cell(0, 10, f"CUENTA: {st.session_state.cuenta_actual}", ln=True)
                                
                                # Encabezado de tabla
                                pdf.set_fill_color(230, 230, 230)
                                pdf.cell(25, 8, "Fecha", 1, 0, 'C', True)
                                pdf.cell(85, 8, "Descripción", 1, 0, 'C', True)
                                pdf.cell(26, 8, "Debe", 1, 0, 'C', True)
                                pdf.cell(26, 8, "Haber", 1, 0, 'C', True)
                                pdf.cell(26, 8, "Saldo", 1, 1, 'C', True)
                                
                                # Filas
                                pdf.set_font("Arial", size=8)
                                for _, fila in reporte.iterrows():
                                    pdf.cell(25, 7, str(fila['fecha']), 1)
                                    pdf.cell(85, 7, str(fila['descripcion'])[:50], 1)
                                    pdf.cell(26, 7, f"{fila['debe']:,.2f}", 1, 0, 'R')
                                    pdf.cell(26, 7, f"{fila['haber']:,.2f}", 1, 0, 'R')
                                    pdf.cell(26, 7, f"{fila['Saldo']:,.2f}", 1, 1, 'R')
                                
                                # Totales finales
                                pdf.ln(5)
                                pdf.set_font("Arial", 'B', 10)
                                pdf.cell(110, 8, "TOTALES GENERALES:", 0, 0, 'R')
                                pdf.cell(26, 8, f"{t_debe:,.2f}", 1, 0, 'R')
                                pdf.cell(26, 8, f"{t_haber:,.2f}", 1, 0, 'R')
                                pdf.cell(26, 8, f"{s_final:,.2f}", 1, 1, 'R')

                                # Botón de descarga
                                pdf_bytes = pdf.output(dest='S').encode('latin-1')
                                st.download_button(
                                    label="⬇️ Descargar Archivo PDF",
                                    data=pdf_bytes,
                                    file_name=f"Mayor_{st.session_state.cuenta_actual}.pdf",
                                    mime="application/pdf"
                                )
                            except Exception as e:
                                st.error(f"Error generando PDF: {e}")
                    else:
                        st.warning("No se encontraron movimientos para esta cuenta.")
            else:
                st.warning(f"⚠️ No hay datos contables en la base de datos: {db_nombre}")
        
        except Exception as e:
            st.error(f"❌ Error en el Libro Mayor: {e}")
        finally:
            if cursor:
                try: cursor.close()
                except: pass
            if conn:
                try: conn.close()
                except: pass
    else:
        st.error("❌ No se pudo establecer conexión con la base de datos.")



def generar_balance_profesional(conn, f_i, f_f, sucursal):
    db = st.session_state.get('DB_ACTUAL')
    if not db:
        st.error("Papi, no has seleccionado ninguna base de datos.")
        return None

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"USE `{db}`")
        
        # 1. Consultar el plan de cuentas original
        query_plan = f"SELECT codigo, nombre, nivel, tipo, padre FROM `{db}`.plan_cuentas ORDER BY codigo"
        df_plan = ejecutar_consulta(query_plan, conn)
        
        if df_plan is None or df_plan.empty:
            st.error("⚠️ El plan de cuentas está vacío.")
            return None

        # 2. Obtener los saldos del balance de comprobación
        df_saldos = generar_balance_comprobacion(conn, f_i, f_f, sucursal)
        
        cols_finales = ['codigo', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        
        if df_saldos is None or df_saldos.empty:
            df_saldos = pd.DataFrame(columns=cols_finales)
        else:
            # Estandarizar nombres de columnas de saldos
            renombres = {}
            for col in df_saldos.columns:
                c_low = str(col).lower()
                if 'codigo' in c_low or 'código' in c_low or 'cuenta' in c_low: renombres[col] = 'codigo'
                elif 'inicial' in c_low: renombres[col] = 'Saldo Inicial'
                elif 'debe' in c_low: renombres[col] = 'Debe'
                elif 'haber' in c_low: renombres[col] = 'Haber'
                elif 'final' in c_low: renombres[col] = 'Saldo Final'
            df_saldos = df_saldos.rename(columns=renombres)

        for c in cols_finales:
            if c not in df_saldos.columns: 
                df_saldos[c] = 0.0

        # --- LIMPIEZA Y NORMALIZACIÓN DE CÓDIGOS PARA EL MERGE ---
        df_plan['llave_join'] = df_plan['codigo'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_plan['llave_padre'] = df_plan['padre'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        
        df_saldos['llave_join'] = df_saldos['codigo'].astype(str).str.replace(r'[^0-9]', '', regex=True)

        # 3. Hacer el merge utilizando la llave numérica limpia
        df = pd.merge(
            df_plan, 
            df_saldos[['llave_join', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']], 
            on='llave_join', 
            how='left'
        )
        
        cols_num = ['Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        df[cols_num] = df[cols_num].fillna(0.0).astype(float)

        # 4. Limpiar los saldos en las cuentas de tipo "Grupo" para que no dupliquen valores propios
        if 'tipo' in df.columns:
            is_grupo = df['tipo'].astype(str).str.lower() == 'grupo'
            df.loc[is_grupo, cols_num] = 0.0

        # 5. SUMATORIA JERÁRQUICA DE ABAJO HACIA ARRIBA (Usando la llave limpia del padre)
        niveles_disponibles = sorted([n for n in df['nivel'].dropna().unique()], reverse=True)
        
        for n in niveles_disponibles:
            filas_nivel = df[df['nivel'] == n]
            for _, fila in filas_nivel.iterrows():
                p_cod = fila['llave_padre']
                if pd.notna(p_cod) and p_cod != '' and p_cod != 'none' and p_cod != 'nan':
                    mask_padre = df['llave_join'] == str(p_cod)
                    if mask_padre.any():
                        df.loc[mask_padre, cols_num] = df.loc[mask_padre, cols_num].values + fila[cols_num].values

        # Recalcular saldo final global de cada fila por seguridad
        df['Saldo Final'] = df['Saldo Inicial'] + df['Debe'] - df['Haber']

        # 6. Fila Total Global aplicando la ecuación patrimonial exacta
        # 6. Fila Total Global asegurando la balanza patrimonial en cero
        df_nivel_1 = df[df['nivel'] == 1]
        
        total_debe = float(df_nivel_1['Debe'].sum())
        total_haber = float(df_nivel_1['Haber'].sum())

        total_saldo_inicial_neto = 0.0
        total_saldo_final_neto = 0.0

        for _, row in df_nivel_1.iterrows():
            digito = str(row['codigo']).strip()[0]
            s_ini = float(row['Saldo Inicial'])
            s_fin = float(row['Saldo Final'])
            
            # Cuentas de naturaleza deudora (1, 4, 5, 8) vs Acreedora (2, 3, 6, 7)
            # Para que la balanza neta dé cero, las acreedoras deben restar al sumarse algebraicamente con las deudoras
            if digito in ['1', '4', '5', '8']:
                total_saldo_inicial_neto += s_ini
                total_saldo_final_neto += s_fin
            else:
                total_saldo_inicial_neto -= s_ini
                total_saldo_final_neto -= s_fin

        fila_total = pd.DataFrame([{
            'codigo': 'Σ', 
            'nombre': 'TOTAL GENERAL', 
            'nivel': 0, 
            'tipo': 'Total', 
            'padre': None,
            'Saldo Inicial': round(total_saldo_inicial_neto, 2), # Cierra en 0.00
            'Debe': total_debe,                               # Suma real de movimientos
            'Haber': total_haber,                             # Suma real de movimientos
            'Saldo Final': round(total_saldo_final_neto, 2)     # Cierra en 0.00
        }])
        
        cols_salida = ['codigo', 'nombre', 'nivel', 'tipo', 'padre', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        df_final = pd.concat([df[cols_salida], fila_total[cols_salida]], ignore_index=True)
        return df_final

    except Exception as e:
        st.error(f"Error procesando balance profesional: {e}")
        return None
    finally:
        if cursor: cursor.close()

def generar_balance_comprobacion(conn, f_i, f_f, sucursal):
    db = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    
    if not db or not conn:
        return pd.DataFrame(columns=['Código', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final'])
    
    registrar_log_automatico(conn, "BALANCE_COMPROBACION", f"Balance para cliente ID: {cliente_id} (BD: {db})")
    
    try:
        # 1. Traer los Saldos Iniciales fijos de la tabla 'saldos_iniciales'
        sql_si = f"SELECT plan_cuentas, SUM(debe) - SUM(haber) as val FROM `{db}`.saldos_iniciales GROUP BY plan_cuentas"
        
        # 2. Movimientos EXCLUSIVOS del rango seleccionado (Ej: Del 1 al 31 de mayo) en 'asientos_contables'
        sql_mo_d = f"SELECT plan_cuentas, SUM(debe) as val FROM `{db}`.asientos_contables WHERE fecha BETWEEN %s AND %s GROUP BY plan_cuentas"
        sql_mo_h = f"SELECT plan_cuentas, SUM(haber) as val FROM `{db}`.asientos_contables WHERE fecha BETWEEN %s AND %s GROUP BY plan_cuentas"

        dfs = {
            'si': ejecutar_consulta(sql_si, conn),
            'debe': ejecutar_consulta(sql_mo_d, conn, params=(f_i, f_f)),
            'haber': ejecutar_consulta(sql_mo_h, conn, params=(f_i, f_f))
        }

        lista_frames = []
        for nombre, df in dfs.items():
            if df is not None and not df.empty:
                if 'plan_cuentas' in df.columns:
                    df = df.rename(columns={'plan_cuentas': 'Código', 'val': nombre})
                    df[nombre] = pd.to_numeric(df[nombre], errors='coerce').fillna(0.0)
                    # Limpiamos todo lo que no sea número para asegurar que '1.1.1.01' y '11101' sean lo mismo
                    df['Código'] = df['Código'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                    df = df.set_index('Código')
                    lista_frames.append(df)

        if not lista_frames:
            return pd.DataFrame(columns=['Código', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final'])

        balance = pd.concat(lista_frames, axis=1).fillna(0.0)
        balance.reset_index(inplace=True)
        
        for c in ['si', 'debe', 'haber']:
            if c not in balance.columns: 
                balance[c] = 0.0
            balance[c] = balance[c].astype(float)
            
        balance['Tipo'] = balance['Código'].astype(str).str[0]
        
        # El Saldo Inicial para el reporte es directamente lo que viene de la tabla saldos_iniciales ('si')
        balance['Saldo Inicial'] = balance['si']
        
        # Naturaleza de las cuentas (Activo/Gasto aumentan por el Debe, Pasivo/Capital/Ingreso por el Haber)
        es_activo_gasto = balance['Tipo'].isin(['1', '5'])
        
        balance['Saldo Final'] = 0.0
        balance.loc[es_activo_gasto, 'Saldo Final'] = balance['Saldo Inicial'] + balance['debe'] - balance['haber']
        balance.loc[~es_activo_gasto, 'Saldo Final'] = balance['Saldo Inicial'] - balance['debe'] + balance['haber']
        
        return balance[['Código', 'Saldo Inicial', 'debe', 'haber', 'Saldo Final']].rename(columns={
            'debe': 'Debe', 'haber': 'Haber'
        })

    except Exception as e:
        st.error(f"❌ Error crítico procesando el balance para el cliente {cliente_id}: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def formato_contable(valor):
    """Formatea los números como montos contables de Venezuela (Bs. 1.234,56)"""
    try:
        return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "0,00"

def estilo_balance(row):
    """Aplica colores y negritas según el nivel de la cuenta"""
    # Nivel 1: Títulos principales (Activo, Pasivo, etc.) - Azul Oscuro
    if row['nivel'] == 1:
        return ['background-color: #1a5276; color: white; font-weight: bold'] * len(row)
    
    # Nivel 2: Sub-títulos (Activo Corriente, etc.) - Azul Claro
    elif row['nivel'] == 2:
        return ['background-color: #d4e6f1; color: black; font-weight: bold'] * len(row)
    
    # Nivel 3 y 4: Grupos intermedios - Solo Negrita
    elif row['nivel'] in [3, 4]:
        return ['font-weight: bold'] * len(row)
    
    # Nivel 5: Cuentas de detalle (Caja, Bancos) - Normal
    return [''] * len(row)



def cargar_libro_ventas_db(df, conn):
    cursor = conn.cursor()
    exitos = 0
    
    # 1. Definimos el mapeo de nombres de columna a los índices que tu lógica espera
    # Esto soluciona el "IndexError" sin cambiar tu lógica de limpieza
    cols = {name: i for i, name in enumerate(df.columns)}
    
    # Mantenemos tus funciones de limpieza intactas
    def f_n(v):
        try:
            if v is None or v == "" or str(v).lower() == 'nan': return 0.0
            s = str(v).strip()
            s = re.sub(r'[^0-9,.-]', '', s)
            if ',' in s and '.' in s:
                if s.rfind(',') > s.rfind('.'): s = s.replace('.', '').replace(',', '.')
                else: s = s.replace(',', '')
            elif ',' in s: s = s.replace(',', '.')
            val = float(s)
            val = round(val, 2)
            return min(max(val, -99999999.99), 99999999.99)
        except: return 0.0

    def convertir_fecha(v):
        try:
            # Si viene como número de Excel
            if str(v).replace('.','',1).isdigit() and float(v) > 30000:
                return (pd.to_datetime('1899-12-30') + pd.to_timedelta(float(v), 'D')).strftime('%Y-%m-%d')
            return pd.to_datetime(v).strftime('%Y-%m-%d')
        except: return "2026-06-05"

    sql = """INSERT INTO libro_ventas 
              (fecha_factura, nombre_razon_social, rif, n_factura, n_control, 
               total_ventas_con_iva, ventas_exentas, base_imponible, porcentaje_alicuota, debito_fiscal) 
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
              ON DUPLICATE KEY UPDATE 
              fecha_factura = VALUES(fecha_factura), 
              nombre_razon_social = VALUES(nombre_razon_social),
              n_control = VALUES(n_control),
              total_ventas_con_iva = VALUES(total_ventas_con_iva),
              ventas_exentas = VALUES(ventas_exentas),
              base_imponible = VALUES(base_imponible),
              debito_fiscal = VALUES(debito_fiscal)"""
    
    # Iteramos sobre los valores del DataFrame
    data = df.astype(str).replace('nan', '').values
    for i, fila in enumerate(data):
        # Filtro: saltar encabezados o filas sin RIF
        if "FECHA" in str(fila[0]).upper() or str(fila[cols.get('rif', 2)]).strip() == "": 
            continue

        # --- AQUÍ ESTÁ EL TRUCO: Usamos el mapeo 'cols' para acceder al índice correcto ---
        # Si la columna existe, usamos su índice; si no, usamos el índice original que tenías
        idx_total = cols.get('total_ventas_con_iva', 5) # Cambia 5 por la posición real si es necesario
        idx_exentas = cols.get('ventas_exentas', 6)
        idx_base = cols.get('base_imponible', 7)
        idx_debito = cols.get('debito_fiscal', 9)

        val_total = f_n(fila[idx_total])
        val_exentas = f_n(fila[idx_exentas])
        val_base = f_n(fila[idx_base])
        val_debito = f_n(fila[idx_debito])

        valores = (
            convertir_fecha(fila[0]), 
            str(fila[1]).upper()[:255].strip(), 
            str(fila[cols.get('rif', 2)]).replace('-', '').replace('.', '').strip(), 
            str(fila[cols.get('n_factura', 3)]).replace('.0', '').strip().zfill(5), 
            str(fila[cols.get('n_control', 4)]).replace('.0', '').strip().zfill(5),
            val_total, val_exentas, val_base, 
            16.0, val_debito
        )
        
        cursor.execute(sql, valores)
        if cursor.rowcount > 0:
            exitos += 1

    conn.commit()
    cursor.close()
    return exitos


def preparar_excel_descarga(df, conn):
    # 1. Registramos el log (esto ya lo tenías bien)
    registrar_log_automatico(conn, "DESCARGA_EXCEL", f"Usuario {st.session_state.usuario} descargó reporte")
    
    # 2. CREAMOS COPIA PARA FORMATEAR (Para que no se dañen los datos originales)
    df_excel = df.copy()
    columnas_moneda = ["Total Bs.", "Exento Bs.", "Base Bs.", "IVA Bs."] # AJUSTA estos nombres según tu dataframe
    
    for col in columnas_moneda:
        if col in df_excel.columns:
            df_excel[col] = df_excel[col].apply(
                lambda x: "{:,.2f}".format(float(x)).replace(",", "X").replace(".", ",").replace("X", ".") 
                if isinstance(x, (int, float)) else x
            )
    
    # 3. GENERAMOS EL EXCEL
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_excel.to_excel(writer, index=False, sheet_name='LibroDeVentas')
        
        workbook = writer.book
        worksheet = writer.sheets['LibroDeVentas']
        
        # Ajuste de columnas
        for i, col in enumerate(df_excel.columns):
            column_len = max(df_excel[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, column_len)
            
    return output.getvalue()




def cargar_libro_compras_db(df, nombre_db=None):
    if not nombre_db:
        nombre_db = st.session_state.get("db_cliente")
    
    if not nombre_db:
        st.error("❌ No hay un cliente activo o base de datos seleccionada en la sesión actual.")
        return

    conn = conectar_db(nombre_db) 
    if not conn:
        st.error(f"No se pudo establecer conexión con la base de datos del cliente: {nombre_db}")
        return

    def clean_n(v):
        if pd.isna(v): return 0.0
        if isinstance(v, (int, float)): return round(float(v), 2)
        s = str(v).strip().replace('.', '').replace(',', '.')
        if s.lower() in ['nan', 'none', 'nat', '', '-']: return 0.0
        try: return round(float(s), 2)
        except: return 0.0

    def convertir_fecha(v):
        try:
            if pd.isna(v): return "2026-06-06"
            if hasattr(v, 'strftime'): 
                return v.strftime('%Y-%m-%d')
            parsed = pd.to_datetime(v, errors='coerce')
            if pd.isna(parsed): return "2026-06-06"
            return parsed.strftime('%Y-%m-%d')
        except Exception as e:
            return "2026-06-06"

    def limpiar_texto(val):
        if pd.isna(val): return ""
        s = str(val).strip()
        if s.lower() in ['nan', 'none', 'nat']: return ""
        if s.endswith('.0'): s = s[:-2]
        return s

    cursor = None
    try:
        # Desactivamos el autocommit para manejar la transacción de forma manual y segura
        conn.autocommit = False
        cursor = conn.cursor()
        
        cursor.execute(f"USE `{nombre_db}`;")
        cursor.execute("SELECT DATABASE();")
        db_conectada = cursor.fetchone()
        db_nombre_actual = db_conectada['DATABASE()'] if isinstance(db_conectada, dict) else db_conectada[0]
        st.info(f"🔍 Conectado y usando el esquema: **{db_nombre_actual}**")

        cols = list(df.columns)
        if len(cols) < 11:
            st.error(f"❌ El archivo cargado tiene {len(cols)} columnas, se esperan al menos 11.")
            return

        # Usamos INSERT con control de duplicados para evitar bloqueos por llaves
        sql = """INSERT INTO libro_compras 
                (fecha_operacion, tipo_documento, n_factura, n_control, proveedor, rif, 
                 total_compras, importe_exento, base_imponible, iva_porcentaje, iva_monto,
                 retencion_realizada, tipo_transaccion) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                total_compras = VALUES(total_compras),
                base_imponible = VALUES(base_imponible),
                iva_monto = VALUES(iva_monto),
                proveedor = VALUES(proveedor)"""

        registros_a_insertar = []
        for i, row in df.iterrows():
            n_fact = limpiar_texto(row[cols[2]])
            if not n_fact: continue

            valores = (
                convertir_fecha(row[cols[0]]),                # 0: Fecha de Operación
                limpiar_texto(row[cols[1]]).zfill(2) if limpiar_texto(row[cols[1]]) else "01", # 1: Tipo de Documento
                n_fact,                                       # 2: Número de Factura
                limpiar_texto(row[cols[3]]),                  # 3: Número de Control
                limpiar_texto(row[cols[4]]).upper(),          # 4: Proveedor
                limpiar_texto(row[cols[5]]).replace('-', '').replace('.', ''), # 5: R.I.F.
                clean_n(row[cols[6]]),                        # 6: Total Compra
                clean_n(row[cols[7]]),                        # 7: Compras Exentas
                clean_n(row[cols[8]]),                        # 8: Base Imponible
                clean_n(row[cols[9]]),                        # 9: Alícuota (%)
                clean_n(row[cols[10]]),                       # 10: Crédito Fiscal (IVA Monto)
                0.00,                                         # 11: retencion_realizada
                "C"                                           # 12: tipo_transaccion
            )
            registros_a_insertar.append(valores)

        if registros_a_insertar:
            cursor.executemany(sql, registros_a_insertar)
            
            # ¡IMPORTANTE! Forzamos la confirmación de escritura en el servidor de BD
            conn.commit()
            
            filas_afectadas = cursor.rowcount
            st.success(f"🔥 ¡Proceso exitoso! Se guardaron/actualizaron registros correctamente (Filas afectadas: {filas_afectadas}).")
            
        else:
            st.warning("⚠️ No se encontraron registros válidos para insertar.")
            
    except Exception as e:
        if conn: 
            conn.rollback()
        st.error(f"❌ Error crítico de escritura en la BD del cliente: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


def obtener_lista_proveedores_mapeo():
    conn = conectar_db(db_actual)
    cursor = conn.cursor()
    cursor.execute("SELECT razon_social, rif FROM proveedores")
    # Devuelve {RazonSocial: RIF}
    mapeo = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return mapeo


def obtener_lista_proveedores():
    try:
        # Ajusta esto a tu conexión real
        conn = conectar_db(db_actual)
        cursor = conn.cursor()
        cursor.execute("SELECT razon_social FROM proveedores")
        # Obtenemos solo los nombres
        nombres = [row[0] for row in cursor.fetchall()]
        conn.close()
        return nombres
    except:
        return ["Error al cargar proveedores"]


def extraer_datos_factura(archivo):
    model = obtener_modelo_valido()
    if not model:
        st.error("No se encontró ningún modelo compatible en tu cuenta.")
        return None
        
    try:
        img_data = archivo.getvalue()
        
        prompt_instrucciones = """
            Eres un asistente contable experto en OCR. Tu tarea es extraer datos de facturas fiscales.
            Extrae la información basándote únicamente en las etiquetas visibles en el documento.

            REGLAS DE ORO:
            1. 'n_factura': Busca etiquetas como "N° Documento", "Número de Factura" o "Factura N°". Extrae el valor alfanumérico exacto.
            2. 'n_control': Busca la etiqueta "N° de Control". Es crucial extraer el formato completo (ej. 00-000000).
            3. 'rif': Busca el RIF del emisor (ej. J-XXXXXXXXX). Elimina guiones y espacios.
            4. 'fecha_operacion': Busca la fecha de emisión. Conviértela a formato YYYY-MM-DD.
            5. Montos: Extrae los valores monetarios de la moneda local (Bs.). Ignora montos en otras divisas.
            6. Si un dato no existe, devuelve el valor en blanco o 0 según corresponda. NO inventes datos.
            7. Devuelve SOLO un JSON puro.

            Formato requerido:
            {
                "n_factura": "string",
                "n_control": "string",
                "fecha_operacion": "YYYY-MM-DD",
                "rif": "string",
                "total_compras": float,
                "importe_exento": float,
                "base_imponible": float,
                "iva_porcentaje": float,
                "iva_monto": float
            }
        """
        
        response = model.generate_content([
            prompt_instrucciones,
            {"mime_type": "image/jpeg", "data": img_data}
        ])
        
        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
        start = texto_limpio.find('{')
        end = texto_limpio.rfind('}') + 1
        texto_limpio = texto_limpio[start:end]
        
        # --- NUEVO: BLOQUE DE BLINDAJE Y LIMPIEZA ---
        datos = json.loads(texto_limpio)
        
        # 1. Limpieza de RIF (Quitar guiones y espacios)
        datos['rif'] = str(datos['rif']).replace('-', '').replace(' ', '').strip().upper()
        
        # 2. Validación de Control (Forzar formato estándar si el OCR falló)
        if len(str(datos['n_control'])) < 5:
            datos['n_control'] = "REVISAR_OCR"
            
        # 3. Asegurar que los montos sean numéricos
        for campo in ['total_compras', 'importe_exento', 'base_imponible', 'iva_monto']:
            try:
                datos[campo] = float(datos[campo])
            except:
                datos[campo] = 0.0
        
        return datos
        # --------------------------------------------
        
    except Exception as e:
        st.error(f"Error procesando con el modelo encontrado: {e}")
        return None


def resetear_estado_retencion(numero_factura):
    try:
        conn = conectar_db()
        cursor = conn.cursor()
        
        # Limpiamos los campos que indican que la factura ya fue procesada
        # Ponemos monto_retenido y porcentaje_retencion en 0
        sql = """
            UPDATE retenciones_islr 
            SET monto_retenido = 0.00, 
                porcentaje_retencion = 0.00 
            WHERE numero_factura = %s
        """
        cursor.execute(sql, (numero_factura,))
        conn.commit()
        conn.close()
        return True
    except:
        return False



def generar_comprobante_pdf(datos, conn):
    """
    Crea el PDF del comprobante ISLR con diseño profesional simétrico,
    limpieza de etiquetas, RIF con guiones, número de comprobante legal 
    y centrado de celdas.
    """
    # Se obtienen de forma segura las variables de sesión para evitar NameError
    usuario_actual = st.session_state.get('usuario', 'Sistema')
    cliente_actual = st.session_state.get('cliente_id', 'General')
    
    registrar_log_automatico(conn, "GENERACION_PDF_RETENCION", f"Usuario {usuario_actual} generó PDF de retención para {cliente_actual}")

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    # --- 0. PREPARACIÓN DE DATOS (LIMPIEZA) ---
    import re
    from datetime import datetime

    def limpiar_num(texto):
        nums = re.findall(r'\d+', str(texto))
        return nums[0] if nums else str(texto)

    # Lógica para formatear RIF con guiones (V-12345678-9)
    def formatear_rif(rif_raw):
        rif = str(rif_raw).upper().replace('-', '').replace(' ', '')
        if len(rif) >= 9:
            return f"{rif[0]}-{rif[1:-1]}-{rif[-1]}"
        return rif

    factura_limpia = limpiar_num(datos.get('factura', '00000')).zfill(5)
    
    # --- 1. ENCABEZADO CORPORATIVO ---
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(100, 5, datos['agente']['nombre'].upper(), 0, 0, 'L')
    
    pdf.set_font("helvetica", "B", 11) 
    num_comprobante = datos.get('n_comprobante', "SIN NÚMERO")
    pdf.cell(90, 5, f"COMPROBANTE N°: {num_comprobante}", 0, 1, 'R') 
    
    pdf.set_font("helvetica", "", 8)
    pdf.cell(100, 4, "Comprobante de Retención del Impuesto Sobre la Renta ISLR", 0, 0, 'L')
    fecha_emision = datos.get('fecha_emision', datetime.now().strftime('%d/%m/%Y'))
    pdf.cell(90, 4, f"Fecha Emisión: {fecha_emision}", 0, 1, 'R')
    pdf.ln(5)

    # --- 2. TÍTULO Y DECRETO ---
    pdf.set_font("helvetica", "B", 8)
    pdf.rect(10, pdf.get_y(), 70, 16) 
    pdf.set_xy(11, pdf.get_y() + 2)
    pdf.multi_cell(68, 4, "Comprobante de Retención de I.S.L.R.\nGaceta Oficial N° 36.206 del 12/05/1997\nDecreto N° 1808 del 23/04/1997", 0, 'L')
    
    # --- 3. BLOQUE COMPARATIVO (SIMETRÍA DE CUADROS) ---
    pdf.set_xy(10, 45)
    y_inicial = pdf.get_y()
    
    nombre_s = datos['sujeto'].get('nombre', "PROVEEDOR DESCONOCIDO")
    dir_s = datos['sujeto'].get('direccion', "CARACAS, VENEZUELA")
    rif_s_formateado = formatear_rif(datos['sujeto'].get('rif', ''))
    rif_a_formateado = formatear_rif(datos['agente'].get('rif', ''))

    # --- LADO IZQUIERDO: SUJETO ---
    pdf.set_font("helvetica", "B", 8)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 6, "Sujeto Retenido (Proveedor / Beneficiario)", 1, 1, 'C', fill=True)
    pdf.set_font("helvetica", "", 8)
    pdf.cell(2, 6, "", "L", 0); pdf.cell(18, 6, "Proveedor:", 0, 0); pdf.cell(75, 6, str(nombre_s)[:40].upper(), "R", 1)
    pdf.cell(2, 6, "", "L", 0); pdf.cell(18, 6, "RIF:", 0, 0); pdf.cell(75, 6, rif_s_formateado, "R", 1)
    pdf.set_font("helvetica", "I", 7)
    pdf.set_x(10)
    pdf.multi_cell(95, 5, f" Dirección: {str(dir_s).upper()}", "LR", 'L')
    y_final_sujeto = pdf.get_y()

    # --- LADO DERECHO: AGENTE ---
    pdf.set_xy(105, y_inicial)
    pdf.set_font("helvetica", "B", 8)
    pdf.cell(95, 6, "Agente de Retención (Empresa)", 1, 1, 'C', fill=True)
    pdf.set_font("helvetica", "", 8)
    pdf.set_x(105)
    pdf.cell(2, 6, "", "L", 0); pdf.cell(18, 6, "Empresa:", 0, 0); pdf.cell(75, 6, str(datos['agente']['nombre']).upper(), "R", 1)
    pdf.set_x(105)
    pdf.cell(2, 6, "", "L", 0); pdf.cell(18, 6, "RIF:", 0, 0); pdf.cell(75, 6, rif_a_formateado, "R", 1)
    pdf.set_x(105)
    pdf.set_font("helvetica", "I", 7)
    pdf.multi_cell(95, 5, f" Dirección: {str(datos['agente']['direccion']).upper()}", "LR", 'L')
    y_final_agente = pdf.get_y()

    # Cierre de cuadros
    y_max = max(y_final_sujeto, y_final_agente)
    pdf.line(10, y_max, 105, y_max)
    pdf.line(105, y_max, 200, y_max)
    
    pdf.set_y(y_max + 8)

    # --- 4. TABLA TÉCNICA ---
    pdf.set_font("helvetica", "B", 7)
    headers = ["Fecha", "Documento", "Base Objeto", "Sustraendo", "% Ret.", "Imp. Determinado.", "Monto Ret."]
    widths = [20, 35, 30, 25, 20, 30, 30]
    
    for i, h in enumerate(headers):
        pdf.cell(widths[i], 7, h, 1, 0, 'C', fill=True)
    pdf.ln()

    pdf.set_font("helvetica", "", 7)
    base = float(datos['base'])
    sust = float(datos['sustraendo'])
    porc = float(datos['porcentaje'])
    impuesto_bruto = base * (porc / 100)
    neto = float(datos['total_retenido'])
    
    pdf.cell(widths[0], 7, str(datos.get('fecha_operacion', 'S/F')), 1, 0, 'C')
    pdf.cell(widths[1], 7, f"{factura_limpia}", 1, 0, 'C') 
    pdf.cell(widths[2], 7, f"{base:,.2f}", 1, 0, 'R')
    pdf.cell(widths[3], 7, f"{sust:,.2f}", 1, 0, 'R')
    pdf.cell(widths[4], 7, f"{porc}%", 1, 0, 'R')
    pdf.cell(widths[5], 7, f"{impuesto_bruto:,.2f}", 1, 0, 'R')
    pdf.cell(widths[6], 7, f"{neto:,.2f}", 1, 1, 'R')

    # Totales
    pdf.set_font("helvetica", "B", 8)
    pdf.cell(sum(widths[:6]), 7, "TOTAL RETENCIÓN ISLR A ENTERAR (Bs.):", 1, 0, 'R')
    pdf.cell(widths[6], 7, f"{neto:,.2f}", 1, 1, 'R')
    pdf.ln(25)

    # --- 5. FIRMAS ---
    y_firmas = pdf.get_y()
    pdf.line(20, y_firmas, 80, y_firmas)
    pdf.line(130, y_firmas, 190, y_firmas)
    
    pdf.set_font("helvetica", "B", 8)
    pdf.set_xy(10, y_firmas + 2)
    pdf.cell(85, 5, "Firma y Sello Agente de Retención", 0, 0, 'C')
    pdf.cell(110, 5, "Firma y Sello del Proveedor", 0, 1, 'C')

    try:
        # Generación segura del PDF en bytes
        pdf_output = pdf.output()
        if isinstance(pdf_output, str):
            return pdf_output.encode('latin-1', errors='ignore')
        elif isinstance(pdf_output, bytearray):
            return bytes(pdf_output)
        return pdf_output
    
    finally:
        # Aseguramos el reintento de conexión de forma segura
        try:
            if conn:
                conn.ping(reconnect=True)
        except Exception:
            pass

def comprobar_existencia_comprobante(n_comprobante):
    """Verifica si el número de comprobante ya existe en la DB"""
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    # Log personalizado como solicitaste
    registrar_log_automatico(conn, "COMPOBAR_EXISTENCIA", f"Usuario {st.session_state.usuario} comprobó existencia del comprobante {n_comprobante} para {st.session_state.cliente_id}")
    
    existe = False
    cursor = None
    
    if conn:
        try:
            cursor = conn.cursor()
            query = "SELECT COUNT(*) FROM retenciones_islr WHERE n_comprob_islr = %s"
            cursor.execute(query, (n_comprobante,))
            existe = cursor.fetchone()[0] > 0
        except Exception as e:
            st.error(f"Error al verificar comprobante: {e}")
        finally:
            if cursor:
                cursor.close() 
            
            # Verificación y ping seguros compatibles con PyMySQL
            if conn:
                try:
                    conn.ping(reconnect=True)
                except Exception:
                    pass
                
    return existe

def obtener_facturas_pendientes(conn, f_desde, f_hasta):
    try:
        query = """
            SELECT * FROM libro_compras 
            WHERE (retencion_realizada = 0 OR retencion_realizada IS NULL OR retencion_realizada = '' OR retencion_realizada = FALSE)
            AND fecha_operacion BETWEEN %s AND %s
        """
        df = ejecutar_consulta(query, conn, params=(f_desde, f_hasta))
        return df if df is not None else pd.DataFrame()
        
    except Exception as e:
        st.error(f"Error al cargar facturas pendientes: {e}")
        return pd.DataFrame()


def cargar_datos_reimpresion(f_desde, f_hasta):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        return pd.DataFrame()

    try:
        # Registro de actividad
        registrar_log_automatico(conn, "CARGAR_DATOS_REIMPRESION", f"Usuario {st.session_state.usuario} cargó datos para reimpresión {f_desde} hasta {f_hasta} para {st.session_state.cliente_id}")
        
        cursor = conn.cursor()
        
        # Usamos los nombres REALES de tu tabla
        query = """
            SELECT id, N_Comprobante1, Razon_Social_Sujeto_Retenido, RIF_Sujeto_Retenido, 
                   Fecha_Factura, Total_Comrpas, Base_Imponible, IVA_Retenido 
            FROM retenciones_iva 
            WHERE Fecha_Factura BETWEEN %s AND %s
        """
        df = ejecutar_consulta(query, conn, params=(f_desde, f_hasta))
        
        # Renombramos para que el resto de tu código no sufra
        df = df.rename(columns={
            'N_Comprobante1': 'nro_comp',
            'Razon_Social_Sujeto_Retenido': 'razon',
            'RIF_Sujeto_Retenido': 'rif',
            'Fecha_Factura': 'f_fac',
            'Total_Comrpas': 'total',
            'Base_Imponible': 'base',
            'IVA_Retenido': 'm_ret'
        })
        
        return df

    except Exception as e:
        st.error(f"Error de base de datos: {e}")
        return pd.DataFrame()

    finally:
        # Cierre seguro del cursor
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
            
        # Mantenemos viva la conexión con un ping seguro para PyMySQL
        if conn:
            try:
                conn.ping(reconnect=True)
            except Exception:
                pass


def obtener_detalle_comprobante(id_registro):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        return pd.DataFrame()

    try:
        registrar_log_automatico(conn, "CONSULTA_DETALLE_COMPROBANTE", f"Usuario {st.session_state.usuario} consultó {id_registro}")
        
        cursor = conn.cursor()
        
        # CONSULTA EXPLÍCITA: Escribimos los nombres exactos de tu tabla
        # CONSULTA AGRUPADA: Sumamos las bases y los impuestos
        # CONSULTA CORREGIDA: Sin agrupamiento para ver todas las facturas
        query = """
        SELECT 
            id, 
            Razon_Social_del_Agente_de_Retencion, 
            RIF_Agente_Retencion, 
            E_Emision, 
            F_Entrega, 
            Razon_Social_Sujeto_Retenido, 
            RIF_Sujeto_Retenido, 
            Ano, 
            Mes, 
            N_Comprobante1, 
            Fecha_Factura, 
            Numero_Factura, 
            Numero_Contro, 
            Total_Comrpas, 
            Compras_Excentas, 
            Base_Imponible, 
            Base_Imponible_8, 
            Impuesto_Iva, 
            IVA_Retenido, 
            IVA_8, 
            RET_IVA_8
        FROM retenciones_iva 
        WHERE N_Comprobante1 = (SELECT N_Comprobante1 FROM retenciones_iva WHERE id = %s)
        """
        
        df = pd.read_sql(query, conn, params=(id_registro,))
        return df
        
        df = pd.read_sql(query, conn, params=(id_registro,))
        return df

    except Exception as e:
        st.error(f"Error al obtener detalle: {e}")
        return pd.DataFrame()

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
                
        if conn:
            try:
                conn.ping(reconnect=True)
            except Exception:
                pass


def mostrar_interfaz_retencion_iva(EMPRESA, f_inicio_global, f_fin_global):
    st.subheader(f"📑 Emisión de Comprobantes de Retención IVA: {EMPRESA}")

    # --- CONTROL DE PESTAÑA ACTIVA ---
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = 0 # 0 es la primera tab ("📥 Cargar Excel")
    
    # 1. INICIALIZACIÓN DE ESTADOS (Prevenir KeyErrors)
    if 'exito_data' not in st.session_state:
        st.session_state['exito_data'] = None
    if 'mostrar_exito' not in st.session_state:
        st.session_state['mostrar_exito'] = False

    # 2. GESTIÓN DE CONEXIÓN
    db_actual = st.session_state.get('DB_ACTUAL')
    
    if 'db_conn' not in st.session_state or st.session_state.db_conn is None:
        st.session_state.db_conn = conectar_db(db_actual)
    else:
        try:
            st.session_state.db_conn.ping(reconnect=True, attempts=3, delay=1)
        except:
            st.session_state.db_conn = conectar_db(db_actual)

    conn = st.session_state.db_conn

    # 3. VALIDACIÓN DE SEGURIDAD
    if conn is None or not conn:
        st.error("❌ No hay conexión activa con la base de datos.")
        return

    facturas_seleccionadas = None

    # --- 1. INICIALIZACIÓN ---
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "📝 Generar Nueva"

    # --- 2. NAVEGACIÓN ---
    # 1. Creamos las pestañas en una sola línea
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📝 Generar Nueva", 
        "📄 PDF Comp. Retenciones", 
        "🖨️ Elimina Retencion", 
        "⚙️ Habilitar Facturas", 
        "🗒️ Archivo TXT SENIAT"
    ])



    # --- 2. VALIDACIÓN DE CONEXIÓN Y CARGA ---
    with tab1:
        st.write("Cargando Generar Nueva...")
        st.subheader("📝 Generar Nueva Retención de IVA")
        db_actual = st.session_state.get("DB_ACTUAL")

        if not db_actual:
            st.error("⚠️ Debes seleccionar una empresa primero.")
            st.stop()

        conn = conectar_db(db_actual)
        if not conn:
            st.error("❌ No se pudo establecer conexión.")
            st.stop()

        # La conexión ya fue validada por 'if not conn:', 
        # no es necesario realizar un .ping() adicional.
        st.write(f"Conectado a: **{db_actual}**")

        # Filtros (Corregida la indentación y las keys independientes)
        col_b1, col_b2 = st.columns(2)
        f_desde = col_b1.date_input("Desde", st.session_state.get('f_inicio_global', dt.date.today()), key="ret_iva_desde")
        f_hasta = col_b2.date_input("Hasta", st.session_state.get('f_fin_global', dt.date.today()), key="ret_iva_hasta")

        # --- 3. LÓGICA DE PROCESAMIENTO ---
        df_facturas = obtener_facturas_pendientes(conn, f_desde, f_hasta)

        if not df_facturas.empty:
            # Aseguramos que la columna de control exista en el DataFrame cargado
            if 'Seleccionar' not in df_facturas.columns:
                df_facturas.insert(0, "Seleccionar", False)

            # Si tu tabla de base de datos incluye una columna 'retencion_realizada', 
            # podemos bloquear visualmente esas filas en el editor de Streamlit:
            column_configs = {
                "Seleccionar": st.column_config.CheckboxColumn(required=True)
            }
            
            # Si la columna existe en el DF, deshabilitamos la edición en las ya retenidas
            if 'retencion_realizada' in df_facturas.columns:
                column_configs["retencion_realizada"] = st.column_config.NumberColumn("Retenida", disabled=True)

            # Muestra el editor y captura los cambios
            df_editado = st.data_editor(
                df_facturas,
                column_config=column_configs,
                hide_index=True,
                width="stretch"
            )

            # Filtramos solo las marcadas que NO estén retenidas previamente
            if 'retencion_realizada' in df_editado.columns:
                seleccion = df_editado[(df_editado["Seleccionar"] == True) & (df_editado["retencion_realizada"] != 1)]
            else:
                seleccion = df_editado[df_editado["Seleccionar"] == True]
            
            if not seleccion.empty:
                st.session_state['facturas_seleccionadas'] = seleccion
                st.success(f"Facturas seleccionadas: {len(seleccion)}")
            else:
                st.session_state['facturas_seleccionadas'] = None


        facturas_seleccionadas = st.session_state.get('facturas_seleccionadas')

        if facturas_seleccionadas is not None and not isinstance(facturas_seleccionadas, pd.DataFrame):
            facturas_seleccionadas = pd.DataFrame(facturas_seleccionadas)

        # --- 1. CASO ÉXITO (SE EVALÚE PRIMERO SI YA SE GUARDÓ) ---
        if st.session_state.get('mostrar_exito', False):
            nro_generado = st.session_state.get('last_iva', {}).get('nro_comp', 'N/D')
            st.success(f"🔥 ¡Proceso exitoso! El comprobante **`{nro_generado}`** ha sido generado y guardado en la base de datos.")
            st.balloons()
            
            st.divider()
            st.write("#### Certificación del grupo procesado:")
            st.info("✅ Las retenciones se registraron correctamente en la BD y las facturas seleccionadas fueron actualizadas.")
            
            if st.button("🔄 Registrar otro grupo", key="btn_reset_retencion"):
                st.session_state['facturas_seleccionadas'] = None
                st.session_state['mostrar_exito'] = False
                st.rerun()
                
        # --- 2. CASO FORMULARIO (CUÁNDO HAY FACTURAS SELECCIONADAS Y NO SE HA GUARDADO) ---
        elif facturas_seleccionadas is not None and not facturas_seleccionadas.empty:
            
            total_base_agrupado = facturas_seleccionadas['base_imponible'].sum()
            total_iva_agrupado = facturas_seleccionadas['iva_monto'].sum()
            total_facturas_agrupado = facturas_seleccionadas['total_compras'].sum()
            total_exento_agrupado = facturas_seleccionadas['importe_exento'].sum()
            
            factura_principal = facturas_seleccionadas.iloc[0]
            
            # Obtención del correlativo automático desde la Base de Datos
            fecha_corta_base = str(factura_principal['fecha_operacion']).split(" ")[0]
            ano_str, mes_str = fecha_corta_base.split("-")[0], fecha_corta_base.split("-")[1]
            prefijo_periodo = f"{ano_str}{mes_str}"
            
            db_nombre_corr = st.session_state.get('DB_ACTUAL')
            conn_corr = conectar_db(db_nombre_corr)
            siguiente_secuencial = 1
            
            if conn_corr:
                try:
                    cursor_corr = conn_corr.cursor()
                    query_ultimo = """
                        SELECT N_Comprobante1 
                        FROM retenciones_iva 
                        WHERE N_Comprobante1 LIKE %s 
                        ORDER BY N_Comprobante1 DESC 
                        LIMIT 1
                    """
                    cursor_corr.execute(query_ultimo, (f"{prefijo_periodo}%",))
                    resultado_ultimo = cursor_corr.fetchone()
                    
                    if resultado_ultimo and resultado_ultimo[0]:
                        ultimo_nro = str(resultado_ultimo[0])
                        secuencial_texto = ultimo_nro[len(prefijo_periodo):]
                        if secuencial_texto.isdigit():
                            siguiente_secuencial = int(secuencial_texto) + 1
                except Exception:
                    siguiente_secuencial = 1
                finally:
                    if cursor_corr:
                        cursor_corr.close()
                    if conn_corr:
                        conn_corr.close()
                        
            val_sugerido = f"{prefijo_periodo}{str(siguiente_secuencial).zfill(8)}"

            st.write("### 📝 Datos del Comprobante (Grupo)")
            st.info(f"Agrupando {len(facturas_seleccionadas)} facturas de **{factura_principal['proveedor']}**")
            
            with st.form("form_retencion_iva"):
                c1, c2, c3 = st.columns(3)
                razon_social_ret = c1.text_input("Sujeto Retenido", value=str(factura_principal['proveedor']))
                rif_ret = c2.text_input("RIF Retenido", value=str(factura_principal['rif']))
                nro_comp = c3.text_input("N° Comprobante (14 dígitos)", value=val_sugerido, key="input_nro_comprobante_iva_fijo")
                
                st.write("*(Los montos abajo representan la suma de todas las facturas seleccionadas)*")
                
                c7, c8, c9, c_ex = st.columns(4)
                base_i = c7.number_input("Base Imponible Total", value=float(total_base_agrupado), format="%.2f")
                iva_i = c8.number_input("Impuesto IVA Total", value=float(total_iva_agrupado), format="%.2f")
                monto_exento_val = c_ex.number_input("Monto Exento Total", value=float(total_exento_agrupado), format="%.2f")
                total_c = c9.number_input("Total Facturas", value=float(total_facturas_agrupado), format="%.2f")
                
                c10, c11 = st.columns(2)
                porcentaje_ret = c10.selectbox("Porcentaje de Retención", [75, 100], key="select_porcentaje_ret_iva_fijo")
                iva_retenido = (float(iva_i) * porcentaje_ret) / 100
                c11.metric("IVA a Retener Total", f"Bs. {iva_retenido:,.2f}")

                db_actual_form = st.session_state.get('DB_ACTUAL')
                empresa_data = obtener_datos_agente_db(db_actual_form)

                if not empresa_data:
                    st.error("⚠️ No se pudieron cargar los datos de la empresa.")
                    empresa_seleccionada = None
                else:
                    empresa_seleccionada = st.selectbox(
                        "Empresa Agente", 
                        options=[empresa_data], 
                        format_func=lambda x: x.get('nombre_empresa', 'Empresa'),
                        key="select_empresa_agente_fijo"
                    )
                    st.session_state['id_empresa_seleccionada'] = empresa_seleccionada

                enviado = st.form_submit_button("💾 Guardar y Generar Documentos")

            if enviado:
                empresa_data_env = st.session_state.get('id_empresa_seleccionada') or st.session_state.get('id_empresa_actual')
                db_nombre = st.session_state.get('DB_ACTUAL')
                
                if not empresa_data_env or not db_nombre:
                    st.error("❌ Faltan datos de empresa o base de datos.")
                    st.stop()

                conn_env = conectar_db(db_nombre)
                if not conn_env:
                    conn_env = conectar_db(db_nombre)

                empresa_nombre = empresa_data_env.get('nombre_empresa') or empresa_data_env.get('razon_social') or "EMPRESA"
                empresa_rif = empresa_data_env.get('rif') or "000000000"
                domicilio_fiscal = empresa_data_env.get('direccion') or "DIRECCIÓN NO REGISTRADA"

                cursor = None
                try:
                    cursor = conn_env.cursor()
                    
                    for _, fila in facturas_seleccionadas.iterrows():
                        base = float(fila.get('base_imponible', 0) or 0)
                        impuesto = float(fila.get('iva_monto', 0) or 0)
                        ratio = round(impuesto / base, 2) if base > 0 else 0
                        es_8 = ratio <= 0.08
                        iva_retenido_fila = (impuesto * porcentaje_ret) / 100
                        
                        b16, i16, r16 = (base, impuesto, iva_retenido_fila) if not es_8 else (0.0, 0.0, 0.0)
                        b8, i8, r8 = (base, impuesto, iva_retenido_fila) if es_8 else (0.0, 0.0, 0.0)
                        
                        fecha_corta = str(fila['fecha_operacion']).split(" ")[0]
                        ano_f, mes_f = fecha_corta.split("-")[0], fecha_corta.split("-")[1]

                        query_ins = """
                            INSERT INTO retenciones_iva (
                                Razon_Social_del_Agente_de_Retencion, RIF_Agente_Retencion, 
                                Direccion_FiscalAgente_Retencion, E_Emision, F_Entrega, Razon_Social_Sujeto_Retenido, 
                                RIF_Sujeto_Retenido, Ano, Mes, N_Comprobante1, Fecha_Factura, Numero_Factura, 
                                Numero_Contro, Total_Comrpas, Compras_Excentas, Base_Imponible, Impuesto_Iva, 
                                IVA_Retenido, Base_Imponible_8, IVA_8, RET_IVA_8, Alicuota, Alicuota_75, N_Nota_Debito
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """

                        params = (
                            empresa_nombre, empresa_rif, domicilio_fiscal,
                            fecha_corta, fecha_corta, razon_social_ret, rif_ret, ano_f, mes_f,
                            nro_comp, fecha_corta, str(fila['n_factura']), str(fila['n_control']),
                            round(float(fila.get('total_compras', 0)), 2),
                            round(float(fila.get('importe_exento', 0)), 2),
                            round(b16, 2), round(i16, 2), round(iva_retenido_fila, 2),
                            round(b8, 2), round(i8, 2), round(r8, 2),
                            "16%", "75%", None
                        )
                        cursor.execute(query_ins, params)
                        
                        query_update = """
                            UPDATE libro_compras 
                            SET retencion_realizada = 1 
                            WHERE id = %s
                        """
                        cursor.execute(query_update, (fila['id'],))

                    conn_env.commit()
                    
                    # Guardamos los estados para mostrar el éxito limpio
                    st.session_state['last_iva'] = {'nro_comp': nro_comp}
                    st.session_state['mostrar_exito'] = True
                    
                    # IMPORTANTE: Vaciamos las facturas seleccionadas para que el formulario desaparezca al instante
                    st.session_state['facturas_seleccionadas'] = None
                    
                    st.rerun()

                except Exception as e:
                    if conn_env: 
                        conn_env.rollback()
                    st.error(f"❌ Error al procesar: {e}")
                finally:
                    if cursor: 
                        cursor.close()
                    if conn_env: 
                        conn_env.close()

                
        with tab2:
            st.write("Cargando PDF...")
            st.subheader("🔍 Historial y Consulta de Comprobantes")
            db_actual = st.session_state.get("DB_ACTUAL")
            
            # --- ELIMINA LAS SIGUIENTES DOS LÍNEAS QUE CAUSAN EL ERROR ---
            # detalle = obtener_detalle_comprobante(opcion_busqueda) 
            # st.write("Datos recibidos de BD:", detalle)
            # -------------------------------------------------------------
            
            # 1. VALIDACIÓN PREVENTIVA DE CONEXIÓN
            try:
                if conn:
                    conn.ping(reconnect=True)
                else:
                    conn = conectar_db(db_actual)
            except Exception:
                conn = conectar_db(db_actual)
                    
            # Filtros de búsqueda
            col_h1, col_h2 = st.columns(2)
            f_desde_h = col_h1.date_input("Desde", f_inicio_global, key="hist_desde")
            f_hasta_h = col_h2.date_input("Hasta", f_fin_global, key="hist_hasta")

            # Reutilizamos la función de carga
            df_historial = cargar_datos_reimpresion(f_desde_h, f_hasta_h)
            
            # Inicializamos la variable aquí para que siempre exista
            opcion_busqueda = None 
            
            if not df_historial.empty:
                opciones = {row['id']: f"Comp: {row['nro_comp']} | {row['razon']}" for i, row in df_historial.iterrows()}

                opcion_busqueda = st.selectbox(
                    "Seleccione el Comprobante para ver el historial detallado:",
                    options=list(opciones.keys()),
                    format_func=lambda x: opciones[x],
                    index=None,
                    placeholder="Seleccione un comprobante..."
                )

                st.write("---")

                # Ahora sí, esta validación es segura
                if opcion_busqueda is not None: 

                    df_detalle = obtener_detalle_comprobante(opcion_busqueda)
                    # 1. Definimos el ID de forma segura
                    id_actual = int(EMPRESA) if str(EMPRESA).isdigit() else 1 
                    id_real = st.session_state.get('id_empresa_seleccionada', {}).get('id', 1)
                    # 2. Llamamos a la función y forzamos un valor por defecto si falla
                    datos_empresa = obtener_datos_agente_db(id_real)

                    # 3. Doble protección: Si por alguna razón la función devolvió None, le ponemos valor
                    if datos_empresa is None:
                        # CORREGIDO: Usamos 'direccion' en lugar de 'domicilio_fiscal'
                        datos_empresa = {"nombre_empresa": "NO ENCONTRADO", "rif": "N/A", "direccion": "N/A"}

                    # AHORA SÍ: Esto nunca fallará
                    # 2. Piso 2: El PDF y Visualización (Solo si hay datos)
                    if not df_detalle.empty:
                        d = df_detalle.iloc[0].to_dict()
                        
                        # --- DISEÑO TIPO FICHA / REPORTE ---
                        st.markdown(f"### 📄 Reporte del Comprobante: {d.get('N_Comprobante1', 'N/A')}")
                        
                        c1, c2, c3 = st.columns(3)
                        with c1: 
                            total_val = float(d.get('Total_Compras') or 0)
                            st.metric("Total Operación", f"{total_val:,.2f}")
                        with c2: 
                            st.metric("Base Imponible", f"{float(d.get('Base_Imponible') or 0):,.2f}")
                        with c3: 
                            st.metric("IVA Retenido", f"{float(d.get('IVA_Retenido') or 0):,.2f}")

                        with st.expander("👁️ Ver Datos Completos del Proveedor", expanded=True):
                            st.write(f"**Razón Social:** {d.get('Razon_Social_Sujeto_Retenido')}")
                            st.write(f"**RIF:** {d.get('RIF_Sujeto_Retenido')}")
                            st.write(f"**Fecha de Factura:** {d.get('Fecha_Factura')}")
                            st.write(f"**Nro. Factura:** {d.get('Numero_Factura')}")
                            st.write(f"**Nro. Control:** {d.get('Numero_Contro')}")

                        # --- LÓGICA DE EXPORTACIÓN A PDF PROFESIONAL ---
                        st.write("---")
                        try:
                            from fpdf import FPDF
                            
                            def safe_float(valor):
                                try: return float(valor) if valor is not None else 0.0
                                except: return 0.0

                            class PDF_PRO(FPDF):
                                def header(self):
                                    self.set_font('Arial', 'B', 10)
                                    self.cell(0, 5, 'COMPROBANTE DE RETENCION DEL IMPUESTO AL VALOR AGREGADO', 0, 1, 'C')
                                    self.set_font('Arial', '', 8)
                                    texto_legal = (
                                        "Ley IVA Art.11 Serán Responsables del Pago del Impuesto en Calidad de Agentes de Retención,\n"
                                        "los compradores o adquirientes de determinados bienes muebles y los receptores de ciertos\n"
                                        "servicios, a quienes la administración tributaria designe como tal"
                                    )
                                    self.multi_cell(0, 4, texto_legal, 0, 'C') 
                                    self.ln(5)

                            pdf = PDF_PRO(orientation='L', unit='mm', format='A4')
                            pdf.add_page()
                            x_mov = 10 

                            # --- 1. OBTENER DATOS (ANTES DE DIBUJAR) --
                            df_detalle = obtener_detalle_comprobante(opcion_busqueda) # <--- CAMBIADO A LA VARIABLE CORRECTA

                            if not df_detalle.empty:
                                # Convertimos la primera fila a diccionario para que d.get() funcione
                                d = df_detalle.iloc[0].to_dict()
                            else:
                                st.error("No se encontraron datos para este comprobante.")
                                return # O maneja el error como prefieras

                            # --- BLOQUE 1: AGENTE DE RETENCIÓN ---
                            # Obtenemos el ID real de forma segura desde el session_state o reutilizando la lógica superior
                            id_real = st.session_state.get('id_empresa_seleccionada', {}).get('id', 1)
                            if not id_real or id_real == 1:
                                id_real = int(EMPRESA) if str(EMPRESA).isdigit() else 1

                            # 2. Llamamos a la función usando el ID correcto
                            datos_empresa = obtener_datos_agente_db(id_real)

                            # Doble protección por si devuelve None
                            if datos_empresa is None:
                                # CORREGIDO: Usamos 'direccion' en lugar de 'domicilio_fiscal'
                                datos_empresa = {"nombre_empresa": "NO ENCONTRADO", "rif": "N/A", "direccion": "N/A"}

                            # DEBUG (Opcional, para verificar)
                            st.sidebar.info(f"Generando PDF para ID: {id_real}")

                            # 3. Dibujamos en el PDF usando los datos correctos
                            pdf.rect(15, 35, 110, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(17, 39, "Razon Social del Agente de Retencion:")
                            pdf.set_font("Arial", "B", 9); pdf.text(17, 46, str(datos_empresa.get('nombre_empresa', 'N/A'))) 

                            pdf.rect(130, 35, 60, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(132, 39, "RIF Agente Retencion:")
                            pdf.set_font("Arial", "B", 10); pdf.text(132, 46, str(datos_empresa.get('rif', 'N/A')))

                            pdf.rect(200, 35, 75, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(202, 39, "N° Comprobante:")
                            pdf.set_font("Arial", "B", 11); pdf.text(202, 47, str(d.get('N_Comprobante1', '')))

                            # ------- BLOQUE 2: DIRECCIÓN Y FECHAS ----------------------

                            pdf.rect(15, 55, 175, 15)

                            # 2. Ponemos la etiqueta del campo
                            pdf.set_font("Arial", "", 8)
                            pdf.text(17, 59, "Direccion Fiscal del Agente Retencion:")

                            # 3. Configuramos la fuente para la dirección
                            pdf.set_font("Arial", "", 7)

                            # 4. Usamos set_xy y multi_cell para que el texto se ajuste dentro del recuadro
                            # La posición x=17, y=61 es donde empieza la dirección dentro del rectángulo
                            pdf.set_xy(17, 61) 

                            # Obtenemos la dirección desde la base de datos (con valor por defecto si está vacío)
                            domicilio_real = str(datos_empresa.get('direccion', 'NO REGISTRADO'))

                            # multi_cell(ancho, alto, texto) - el ancho 170 es para que no toque el borde derecho
                            pdf.multi_cell(170, 3.5, domicilio_real)

                            # ------- BLOQUE 3:  ----------------------

                            pdf.rect(200, 55, 35, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(202, 59, "E. Emision:")
                            pdf.set_font("Arial", "B", 9); pdf.text(202, 66, str(d.get('E_Emision', '')))

                            pdf.rect(235, 55, 40, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(237, 59, "F. Entrega:")
                            pdf.set_font("Arial", "B", 9); pdf.text(237, 66, str(d.get('F_Entrega', '')))

                            # --- BLOQUE 3: SUJETO RETENIDO ---
                            pdf.rect(15, 75, 110, 15)
                            pdf.set_font("Arial", "", 8); pdf.text(17, 79, "Razon Social Sujeto Retenido:")
                            pdf.set_font("Arial", "B", 9); pdf.text(17, 86, str(d.get('Razon_Social_Sujeto_Retenido', '')))

                            pdf.rect(130, 75, 60, 15)
                            pdf.set_font("Arial", "", 8); pdf.text(132, 79, "RIF Sujeto Retenido:")
                            pdf.set_font("Arial", "B", 10); pdf.text(132, 86, str(d.get('RIF_Sujeto_Retenido', '')))

                            pdf.rect(200, 75, 35, 15)
                            pdf.set_font("Arial", "", 8); pdf.text(202, 79, "Año:")
                            pdf.set_font("Arial", "B", 10); pdf.text(202, 86, str(d.get('Ano', '')))

                            pdf.rect(235, 75, 40, 15)
                            pdf.set_font("Arial", "", 8); pdf.text(237, 79, "Mes:")
                            pdf.set_font("Arial", "B", 10); pdf.text(237, 86, str(d.get('Mes', '')).zfill(2))

                            # --- EXTRACCIÓN PROTEGIDA DE VALORES NUMÉRICOS ---
                            total_val = safe_float(d.get('Total_Comrpas'))
                            exento_val = safe_float(d.get('Compras_Excentas'))
                            base_val = safe_float(d.get('Base_Imponible'))
                            alicuota_val = safe_float(d.get('Alicuota'))
                            iva_val = safe_float(d.get('Impuesto_Iva'))
                            ret_val = safe_float(d.get('IVA_Retenido'))

                            # --- TABLA DE DETALLES ---
                            pdf.set_y(95)
                            pdf.set_x(15 + x_mov) 
                            pdf.set_font("Arial", "B", 7)
                            
                            # --- TABLA DE DETALLES (ACTUALIZADA PARA 8% Y 16%) ---
                            # Cabecera de tabla
                            
                            cols_numericas = ['Compras_Excentas', 'Base_Imponible', 'Impuesto_Iva', 'IVA_Retenido', 
                                              'Base_Imponible_8', 'IVA_8', 'RET_IVA_8']
                            for col in cols_numericas:
                                df_detalle[col] = df_detalle[col].fillna(0)

                            # 2. Determinar si hay alícuota del 8%
                            tiene_alicuota_8 = df_detalle['Base_Imponible_8'].sum() > 0

                            # 3. Definir estructuras según el caso (Longitud Variable)
                            if tiene_alicuota_8:
                                h = ["Fecha", "N.Fact", "N.Contr", "Total", "Exento", "Base 16%", "IVA 16%", "Ret. 16%", "Base 8%", "IVA 8%", "Ret. 8%", "Total Ret."]
                                w = [20, 15, 20, 25, 20, 20, 20, 20, 20, 20, 20, 20]
                            else:
                                # AQUÍ NO USAS 0, simplemente eliminas las columnas del 8% de la lista
                                h = ["Fecha", "N.Fact", "N.Contr", "Total", "Exento", "Base 16%", "IVA 16%", "Ret. 16%", "Total Ret."]
                                w = [20, 15, 20, 25, 20, 20, 20, 20, 20]

                            # 4. Cálculo del centrado
                            ancho_total_tabla = sum(w) 
                            margen_centrado = (277 - ancho_total_tabla) / 2
                            x_mov_dinamico = 10 + margen_centrado

                            # 5. DIBUJO DE CABECERA (SOLO ESTE BLOQUE DEBE EXISTIR)
                            pdf.set_fill_color(240, 240, 240)
                            pdf.set_font("Arial", "B", 7)
                            pdf.set_x(x_mov_dinamico) 

                            for i in range(len(h)):
                                pdf.cell(w[i], 5, h[i], 1, 0, 'C', fill=True)
                            pdf.ln()

                            # 6. Inicializar Totales Generales
                            tot_gen_total, tot_gen_exento = 0, 0
                            tot_gen_base16, tot_gen_iva16, tot_gen_ret16 = 0, 0, 0
                            tot_gen_base8, tot_gen_iva8, tot_gen_ret8 = 0, 0, 0

                            # --- 3. BUCLE DE FACTURAS ---
                            pdf.set_font("Arial", "", 7)
                            for _, fila in df_detalle.iterrows():
                                pdf.set_x(x_mov_dinamico)
                                d = fila.to_dict()
                                
                                # Extraer valores seguros
                                exento = safe_float(d.get('Compras_Excentas'))
                                b16 = safe_float(d.get('Base_Imponible'))
                                i16 = safe_float(d.get('Impuesto_Iva'))
                                r16 = safe_float(d.get('IVA_Retenido'))
                                b8 = safe_float(d.get('Base_Imponible_8'))
                                i8 = safe_float(d.get('IVA_8'))
                                r8 = safe_float(d.get('RET_IVA_8'))
                                total_fila = exento + b16 + b8 + i16 + i8 # Asegúrate que tu lógica de total sea correcta
                                
                                # Acumular totales

                                tot_gen_total += total_fila
                                tot_gen_exento += exento
                                tot_gen_base16 += b16
                                tot_gen_iva16 += i16
                                tot_gen_base8 += b8
                                tot_gen_iva8 += i8
                                retencion_fila = r16 + r8
                                # Si la columna es 16%, solo debe mostrar r16. Si es 8%, solo r8
                                total_retencion_general = tot_gen_ret16 + tot_gen_ret8
                                valor_mostrar_r16 = r16 
                                valor_mostrar_r8 = r8 if tiene_alicuota_8 else 0
                                mostrar_r16 = r16 if (b16 > 0) else 0
                                mostrar_r8 = r8 if (b8 > 0) else 0
                                #total_fila_retencion = mostrar_r16 + mostrar_r8

                                valor_a_mostrar_r16 = r16 if b16 > 0 else 0
                                valor_a_mostrar_r8 = r8 if b8 > 0 else 0
                                # Esta es la suma REAL de la fila actual
                                total_fila_retencion = valor_a_mostrar_r16 + valor_a_mostrar_r8

                               # Lógica de exclusión para la columna del 16%
                               # Si es una fila exclusiva de 8%, la columna Ret. 16% debe ser 0.00
                                # 1. ACUMULACIÓN CONTROLADA (¡ESTO ES LO QUE TE FALTA!)
                                if b16 > 0:
                                    tot_gen_ret16 += r16
                                if b8 > 0:
                                    tot_gen_ret8 += r8

                                # Dibujar fila
                                pdf.set_x(x_mov_dinamico)
                                pdf.cell(w[0], 4, str(d.get('Fecha_Factura', '')), 1, 0, 'C')
                                pdf.cell(w[1], 4, str(d.get('Numero_Factura', '')), 1, 0, 'C')
                                pdf.cell(w[2], 4, str(d.get('Numero_Contro', '')), 1, 0, 'C')
                                pdf.cell(w[3], 4, f"{total_fila:,.2f}", 1, 0, 'R')
                                pdf.cell(w[4], 4, f"{exento:,.2f}", 1, 0, 'R')
                                pdf.cell(w[5], 4, f"{b16:,.2f}", 1, 0, 'R')
                                pdf.cell(w[6], 4, f"{i16:,.2f}", 1, 0, 'R')
    
                                # Columnas opcionales (Solo si tiene_alicuota_8 es True)
                                pdf.cell(w[7], 4, f"{valor_a_mostrar_r16:,.2f}", 1, 0, 'R')

                                if tiene_alicuota_8:
                                    pdf.cell(w[8], 4, f"{b8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[9], 4, f"{i8:,.2f}", 1, 0, 'R')
                                    # Celda Ret. 8% (Columna 10)
                                    pdf.cell(w[10], 4, f"{valor_a_mostrar_r8:,.2f}", 1, 0, 'R')
                                    # Total Ret. de la FILA (Columna 11)
                                    pdf.cell(w[11], 4, f"{total_fila_retencion:,.2f}", 1, 1, 'R', fill=True)
                                else:
                                    # Si no hay 8%, el total de la fila es solo el 16%
                                    pdf.cell(w[8], 4, f"{valor_a_mostrar_r16:,.2f}", 1, 1, 'R', fill=True)
                                #pdf.ln()

                            # --- 4. FILA DE TOTALES (FUERA DEL BUCLE) ---
                            # --- TOTALES DENTRO DE LA TABLA ---
                            # --- 4. FILA DE TOTALES (CORRECCIÓN DE ANCHO) ---
                            st.warning(f"DEBUG: tot_gen_ret16 es: {tot_gen_ret16}")
                            st.warning(f"DEBUG: tot_gen_ret8 es: {tot_gen_ret8}")
                            total_retencion_general = tot_gen_ret16 + tot_gen_ret8
                            pdf.set_x(x_mov_dinamico)
                            pdf.set_font("Arial", "B", 7)
                            pdf.set_fill_color(220, 220, 220)

                            # 1. Ajustamos la celda "TOTALES" para que sea más pequeña si es necesario
                            # Si la tabla tiene 11 columnas (w[0] a w[10]), el total general ocupa una columna extra
                            pdf.cell(sum(w[:3]), 5, "TOTALES", 1, 0, 'R', fill=True)

                            # 2. Imprimimos el resto de totales normales
                            pdf.cell(w[3], 5, f"{tot_gen_total:,.2f}", 1, 0, 'R')
                            pdf.cell(w[4], 5, f"{tot_gen_exento:,.2f}", 1, 0, 'R')
                            pdf.cell(w[5], 5, f"{tot_gen_base16:,.2f}", 1, 0, 'R')
                            pdf.cell(w[6], 5, f"{tot_gen_iva16:,.2f}", 1, 0, 'R')
                            pdf.cell(w[7], 5, f"{tot_gen_ret16:,.2f}", 1, 0, 'R')

                            if tiene_alicuota_8:
                                pdf.cell(w[8], 5, f"{tot_gen_base8:,.2f}", 1, 0, 'R')
                                pdf.cell(w[9], 5, f"{tot_gen_iva8:,.2f}", 1, 0, 'R')
                                # AQUÍ: Imprime el acumulado REAL del 8% (debe dar 743.96)
                                pdf.cell(w[10], 5, f"{tot_gen_ret8:,.2f}", 1, 0, 'R') 
                                # AQUÍ: Suma los dos acumulados reales (8,636.86 + 743.96 = 9,380.82)
                                pdf.cell(w[11], 5, f"{tot_gen_ret16 + tot_gen_ret8:,.2f}", 1, 1, 'R', fill=True)
                                
                            else:
                                # Caso donde no hay alícuota del 8%, el total retención es solo el 16%
                                pdf.cell(w[8], 5, f"{tot_gen_ret16:,.2f}", 1, 1, 'R', fill=True)

                            # --- SECCIÓN DE FIRMAS (Ajustada con x_mov) ---
                            pdf.ln(35)
                            y_firmas = pdf.get_y()
                            pdf.set_font("Arial", "B", 8)
                            
                            # Líneas de firma
                            pdf.line(40 + x_mov, y_firmas, 110 + x_mov, y_firmas)
                            pdf.line(180 + x_mov, y_firmas, 250 + x_mov, y_firmas)
                            
                            # Textos de firma
                            # Usamos una ruta relativa: busca dentro de la carpeta 'assets'
                            import os

                            # --- SECCIÓN DE FIRMAS ---
                            # 1. Definimos un límite seguro antes de dibujar
                            limite_pagina = 240 # Si estás más abajo de 240mm, mejor saltar a página nueva

                            if pdf.get_y() > limite_pagina:
                                pdf.add_page()
                                # (Opcional) Aquí podrías volver a poner un encabezado si fuera necesario
                                y_firmas = 40 # Posición inicial en la nueva página
                            else:
                                pdf.ln(35) # Espacio si hay lugar en la misma página
                                y_firmas = pdf.get_y()

                            # 2. Ahora dibujamos todo usando y_firmas como referencia
                            import os
                            ruta_firma = os.path.join("assets", "cielo.png")

                            # --- AJUSTE DE FIRMAS MÁS HACIA ARRIBA ---
                            # Aumentamos los valores restados para subir los elementos en la página


                            # Dibujar firma e imagen
                            pdf.image(ruta_firma, x=55 + x_mov, y=y_firmas - 65, w=35)
                            pdf.text(50 + x_mov, y_firmas - 28, "AGENTE DE RETENCION")
                            pdf.text(195 + x_mov, y_firmas - 31, "SUJETO RETENIDO")

                            # 3. Datos DINÁMICOS
                            pdf.set_font("Arial", "B", 7)
                            nombre_empresa = datos_empresa.get('nombre_empresa', 'N/A')
                            rif_empresa = datos_empresa.get('rif', 'N/A')

                            pdf.set_xy(40 + x_mov, y_firmas - 25)
                            pdf.multi_cell(65, 5, f"{nombre_empresa}\nRIF: {rif_empresa}", 0, 'C')

                            # Finalizar
                            pdf_output = bytes(pdf.output())
                            
                            st.download_button(
                                label="📥 Exportar este Comprobante a PDF",
                                data=pdf_output,
                                file_name=f"COMP_{d.get('N_Comprobante1', '0')}.pdf",
                                mime="application/pdf",
                                type="primary"
                            )

                        except Exception as e:
                            st.error(f"Error al generar PDF: {e}")

                    else:
                        st.error("⚠️ No se encontraron detalles válidos para este comprobante.")

                    # 3. Piso 3: El Historial (¡Se ve siempre que haya una selección!)
                    st.divider()
                    st.write("📋 Resumen del período seleccionado:")
                    if not df_historial.empty:
                        st.dataframe(df_historial, use_container_width=True, hide_index=True)
                    else:
                        st.info("No se encontraron registros en el historial para este rango de fechas.")

                else:
                    # Planta Baja vacía
                    st.info("Por favor, seleccione un comprobante de la lista superior.")

        

        with tab3:
            st.write("Cargando Eliminar Retencion...")
            
            col_r1, col_r2 = st.columns(2)
            f_desde_r = col_r1.date_input("Desde", f_inicio_global, key="reimp_desde")
            f_hasta_r = col_r2.date_input("Hasta", f_fin_global, key="reimp_hasta")

            df_reimp = cargar_datos_reimpresion(f_desde_r, f_hasta_r)

            if not df_reimp.empty:
                # 1. Definimos configuración de columnas con anchos más generosos
                column_config = {}
                for col in df_reimp.columns:
                    if col in ['id', 'id_empresa', 'Ano', 'Mes']:
                        column_config[col] = st.column_config.NumberColumn(width=100)
                    else:
                        column_config[col] = st.column_config.TextColumn(width=200) # Más ancho para que no se encojan

                # Bloqueos de seguridad
                column_config['id'] = st.column_config.NumberColumn(disabled=True, width=80)
                if 'id_empresa' in df_reimp.columns:
                    column_config['id_empresa'] = st.column_config.NumberColumn(disabled=True, width=80)

                st.write("Modifica los valores directamente en la tabla y presiona 'Guardar Cambios':")
                
                # 2. ELIMINAMOS EL CSS DE ANCHO AL 100%
                # Usamos el contenedor para el scroll vertical y permitimos el horizontal naturalmente
                with st.container(height=300):
                    edited_df = st.data_editor(
                        df_reimp,
                        column_config={
                            "id": st.column_config.NumberColumn(disabled=True), # El ID nunca debe ser editable
                            "nro_comp": st.column_config.TextColumn(disabled=True) # Si no quieres que cambien el número de comprobante
                        },
                        use_container_width=True,
                        hide_index=True,
                        key="editor_retenciones" # Clave única para evitar conflictos de estado
                    )
                # 3. Guardado
                if st.button("💾 Guardar Cambios"):
                    for _, row in edited_df.iterrows():
                        # Buscamos la fila original en el df_reimp original mediante el ID
                        original_row = df_reimp[df_reimp['id'] == row['id']].iloc[0]
                        
                        # Solo actualizamos si algo cambió realmente
                        if not row.equals(original_row):
                            if actualizar_registro_retencion(row):
                                st.toast(f"Registro {row['id']} actualizado", icon="✅")
                    
                    st.rerun() # Recargamos para refrescar la tabla después de guardar

                st.divider()

                # 4. Eliminación
                st.subheader("🗑️ Eliminar Registro")
                def get_label(row):
                    # Intentamos obtener el valor, si la columna no existe, devuelve 'Sin Nro'
                    nro = row.get('nro_comp', 'Sin Nro')
                    fact = row.get('Numero_Factura', 'Sin Factura')
                    return f"Comp: {nro} | Fact: {fact}"

                opciones_eliminar = {row['id']: get_label(row) for _, row in df_reimp.iterrows()}
                
                seleccion_del = st.selectbox(
                    "Seleccione el comprobante a ELIMINAR:",
                    options=list(opciones_eliminar.keys()),
                    format_func=lambda x: opciones_eliminar[x]
                )

                if st.button("🚨 Confirmar Eliminación Permanente"):
                    if eliminar_registro_retencion(seleccion_del):
                        st.toast("Comprobante eliminado", icon="✅")
                        st.rerun()
            else:
                st.info("No hay registros en este rango.")

        # --- TAB 5: GESTIÓN DE FACTURAS (DESBLOQUEO) ---
        with tab4:
            st.write("Cargando Habilitar...")
            st.subheader("🔓 Desbloquear Facturas (Quitar Retención)")

            # 1. VALIDACIÓN PREVENTIVA (Antes de cargar la lista)
            try:
                if not conn:
                    conn = conectar_db(db_actual)
            except Exception as e:
                conn = conectar_db(db_actual)

            # Usamos el nombre real de la columna: 'retencion_realizada'
            query_facturas = "SELECT n_factura as numero_factura, proveedor FROM libro_compras WHERE retencion_realizada = 1"
            
            facturas_bloqueadas = ejecutar_consulta(query_facturas, conn)

            if facturas_bloqueadas is not None and not facturas_bloqueadas.empty:
                opciones = facturas_bloqueadas['numero_factura'].astype(str) + " - " + facturas_bloqueadas['proveedor'].astype(str)
                seleccion_label = st.selectbox("Seleccione factura para habilitar:", opciones, key="sel_des_iva")
                nro_a_desbloquear = seleccion_label.split(" - ")[0]
                
                if st.button("Habilitar Factura", key="btn_des_iva"):
                    cursor_aux = conn.cursor()
                    # Actualizamos usando la misma columna correcta
                    cursor_aux.execute("UPDATE libro_compras SET retencion_realizada = 0 WHERE n_factura = %s", (nro_a_desbloquear,))
                    conn.commit()
                    cursor_aux.close()
                    st.success(f"Factura {nro_a_desbloquear} habilitada.")
                    st.rerun()
            else:
                st.info("No hay facturas bloqueadas actualmente.")

        
        # --- TAB 6: ARCHIVO TXT SENIAT ---
        with tab5:
            st.write("Cargando TXT...")
            st.subheader("🚀 Generación de Archivo TXT para el SENIAT")
            st.info("Seleccione el rango de fechas para consolidar las retenciones.")

            # --- BLINDAJE LOCAL DE FECHAS ---
            from datetime import date as d_tipo

            hoy = d_tipo.today()
            inicio_mes = hoy.replace(day=1)

            col1, col2 = st.columns(2)
            with col1:
                fecha_inicio = st.date_input("Fecha Inicio", inicio_mes, key="txt_f_inicio")
            with col2:
                fecha_fin = st.date_input("Fecha Fin", hoy, key="txt_f_fin")

            if st.button("🔍 Filtrar y Generar TXT"):
                # Aseguramos obtener la BD actual de la sesión
                db_nombre = st.session_state.get('DB_ACTUAL')
                if not db_nombre:
                    st.error("Error: No se ha seleccionado una base de datos.")
                else:
                    conn = conectar_db(db_nombre)
                    try:
                        cursor = conn.cursor(dictionary=True)
                        query_txt = "SELECT * FROM retenciones_iva WHERE E_Emision BETWEEN %s AND %s"
                        cursor.execute(query_txt, (fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d')))
                        registros_txt = cursor.fetchall()
                        cursor.close()
                        
                        if registros_txt:
                            lineas_txt = []
                            for reg in registros_txt:
                                # 1. Detectar si es alícuota del 8% o 16%
                                es_ocho = float(reg.get('Base_Imponible_8', 0) or 0) > 0
                                
                                # Definir montos dinámicamente según la alícuota
                                if es_ocho:
                                    m_base = f"{float(reg.get('Base_Imponible_8', 0) or 0):.2f}"
                                    m_ret = f"{float(reg.get('RET_IVA_8', 0) or 0):.2f}"
                                    m_ali = "8.00"
                                else:
                                    m_base = f"{float(reg.get('Base_Imponible', 0) or 0):.2f}"
                                    m_ret = f"{float(reg.get('IVA_Retenido', 0) or 0):.2f}"
                                    m_ali = "16.00"

                                # 2. Otros campos
                                fecha_raw = reg.get('Fecha_Factura', '')
                                # Manejo seguro de fecha
                                try:
                                    f_obj = datetime.strptime(str(fecha_raw), '%Y-%m-%d')
                                except:
                                    f_obj = datetime.now()
                                periodo = f_obj.strftime("%Y%m")
                                
                                # 3. Construcción de campos
                                campos = [
                                    str(reg.get('RIF_Agente_Retencion', '')).replace('-', '').strip(),
                                    periodo,
                                    f_obj.strftime('%Y-%m-%d'),
                                    'C', '01',
                                    str(reg.get('RIF_Sujeto_Retenido', '')).replace('-', '').strip(),
                                    str(reg.get('Numero_Factura', '')).strip(),
                                    str(reg.get('Numero_Contro', '')).strip(),
                                    f"{float(reg.get('Total_Comrpas', 0) or 0):.2f}",
                                    m_base, 
                                    m_ret, 
                                    '0',
                                    str(reg.get('N_Comprobante1', '')).strip(),
                                    f"{float(reg.get('Compras_Excentas', 0) or 0):.2f}",
                                    m_ali, 
                                    '0'
                                ]
                                lineas_txt.append("\t".join(campos))
                            
                            # Generar contenido
                            contenido_final_txt = "\n".join(lineas_txt)
                            st.code(contenido_final_txt)
                            
                            nombre_archivo = f"IVA_SENIAT_{fecha_inicio.strftime('%Y-%m-%d')}_al_{fecha_fin.strftime('%Y-%m-%d')}.txt"

                            st.download_button(
                                label="💾 Descargar TXT",
                                data=contenido_final_txt,
                                file_name=nombre_archivo,
                                mime="text/plain"
                            )
                        else:
                            st.warning("No hay registros en este rango.")
                    except Exception as e:
                        st.error(f"Error al generar TXT: {e}")
                    finally:
                        if conn:
                            try:
                                conn.close()
                            except Exception:
                                pass


def generar_excel_formateado(conn, df, titulo, subtitulo):
    # Registro de actividad
    registrar_log_automatico(conn, "GENERAR_EXCEL_FORMATEADO", f"Usuario {st.session_state.usuario} descargó excel para {st.session_state.cliente_id}")
    
    cursor = None
    output = io.BytesIO()
    
    try:
        # Aseguramos el cursor para el bloque finally
        cursor = conn.cursor()
        
        # Usamos xlsxwriter como motor para manejar estilos fácilmente
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Balance', startrow=4)
            
            workbook  = writer.book
            worksheet = writer.sheets['Balance']

            # 1. Definir Formatos
            formato_titulo = workbook.add_format({
                'bold': True, 'size': 16, 'font_color': '#1f2937', 'align': 'left'
            })
            formato_subtitulo = workbook.add_format({
                'bold': True, 'size': 12, 'font_color': '#4b5563', 'align': 'left'
            })
            formato_encabezado = workbook.add_format({
                'bold': True, 'text_wrap': True, 'valign': 'vcenter',
                'fg_color': '#1e3a8a', 'font_color': 'white', 'border': 1
            })

            # 2. Escribir Título y Subtítulo
            worksheet.write('A1', titulo, formato_titulo)
            worksheet.write('A2', subtitulo, formato_subtitulo)

            # 3. Aplicar color a los encabezados de la tabla
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(4, col_num, value, formato_encabezado)
                worksheet.set_column(col_num, col_num, 20)

        return output.getvalue()

    except Exception as e:
        st.error(f"Error generando el Excel: {e}")
        return None

    finally:
        # Cierre seguro del cursor
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        
        # Mantenemos viva la conexión con ping seguro
        if conn:
            try:
                conn.ping(reconnect=True)
            except Exception:
                pass



def cargar_asientos_contables_db(df, conn=None):
    if not conn:
        db_actual = st.session_state.get('DB_ACTUAL', 'kingdirver_ca')
        conn = conectar_db(db_actual)
    
    if not conn: return False
    
    cursor = None
    try:
        df_limpio = df.copy()
        df_limpio.columns = df_limpio.columns.astype(str).str.strip().str.lower()
        
        # 1. Limpieza de fecha
        df_limpio['fecha'] = pd.to_datetime(df_limpio['fecha'], errors='coerce')
        df_limpio = df_limpio.dropna(subset=['fecha']) 
        
        # 2. Limpieza robusta para Debe y Haber (remplaza guiones y comas)
        for col in ['debe', 'haber']:
            if col in df_limpio.columns:
                df_limpio[col] = (
                    df_limpio[col]
                    .astype(str)
                    .str.replace(' ', '')
                    .str.replace(',', '.')
                    .replace(['-', 'nan', 'None', ''], '0.0')
                )
                df_limpio[col] = pd.to_numeric(df_limpio[col], errors='coerce').fillna(0.0).round(2)
            else:
                df_limpio[col] = 0.0

        valores = []
        for index, row in df_limpio.iterrows():
            try:
                # Forzar conversión estricta a tipos nativos de Python para evitar errores de MySQL
                n_comp = str(row.get('n_comprobante', ''))
                desc = str(row.get('descripcion', ''))
                fec = row['fecha'].strftime('%Y-%m-%d')
                plan = str(row.get('plan_de_cuentas', row.get('plan_cuentas', '')))
                cta = str(row.get('cuenta_contable', ''))
                ref = str(row.get('ref', row.get('referencia', '')))
                debe_val = float(row['debe'])
                haber_val = float(row['haber'])

                tupla = (n_comp, desc, fec, plan, cta, ref, debe_val, haber_val)
                valores.append(tupla)
            except Exception as row_err:
                st.warning(f"⚠️ Saltando fila {index + 1} por formato inválido: {row_err}")
                continue
        
        if not valores:
            st.warning("⚠️ No se encontraron datos válidos para insertar después de la limpieza.")
            return False

        # 3. Inserción masiva limpia
        cursor = conn.cursor()
        query = """
            INSERT INTO asientos_contables 
            (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.executemany(query, valores)
        conn.commit()
        
        st.success(f"✅ ¡Éxito! {len(valores)} asientos cargados correctamente.")
        return True

    except Exception as e:
        if conn: conn.rollback()
        st.error(f"❌ Error masivo al insertar en la base de datos: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.ping(reconnect=True)

            
def consultar_tabla_db(conn, nombre_tabla, limite=None):
    # 1. Validar nombre de tabla para evitar inyección SQL
    if not re.match(r"^[a-zA-Z0-9_]+$", str(nombre_tabla)):
        st.error(f"Nombre de tabla inseguro: {nombre_tabla}")
        return None

    if not conn:
        st.error("No hay conexión activa.")
        return None

    try:
        # 2. Consulta directa sin columnas inventadas
        query = f"SELECT * FROM `{nombre_tabla}`"
        
        if limite and isinstance(limite, int):
            query += f" LIMIT {limite}"
            
        # 3. Ejecutar
        df = ejecutar_consulta(query, conn)
        return df

    except Exception as e:
        st.error(f"Error consultando {nombre_tabla}: {e}")
        return None


def actualizar_tabla_completa_db(conn, nombre_tabla, df_nuevo):
    """
    Actualización genérica: hace TRUNCATE y luego inserta el DF completo.
    """
    if not conn:
        raise Exception("No hay conexión activa a la base de datos.")

    cursor = conn.cursor()
    try:
        # 1. Limpiar tabla de forma segura
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        cursor.execute(f"TRUNCATE TABLE {nombre_tabla}")
        
        # 2. Generar el INSERT dinámico basado en las columnas del DataFrame
        columnas = ", ".join(df_nuevo.columns)
        placeholders = ", ".join(["%s"] * len(df_nuevo.columns))
        sql = f"INSERT INTO {nombre_tabla} ({columnas}) VALUES ({placeholders})"
        
        # 3. Insertar datos de forma masiva
        datos = [tuple(row) for row in df_nuevo.values]
        cursor.executemany(sql, datos)
        
        conn.commit()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        
    except Exception as e:
        conn.rollback()
        raise e # Lanzamos el error hacia arriba para que el st.error del menú lo capture
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.ping(reconnect=True)
            except Exception:
                pass


def modulo_inventario_pedacito_cielo(conn):
    st.markdown("## 🍰 Sistema de Inventario y Costeo — Pedacito de Cielo")
    st.write("Control bimoneda de materia prima, formulación de recetas y rebaja automática por producción con valoración ERP.")

    # -------------------------------------------------------------------------
    # PASO 0: CREACIÓN SEGURA Y SILENCIOSA (EVITA ERRORES 1050)
    # -------------------------------------------------------------------------
    try:
        cursor = conn.cursor()
        
        # 1. Verificamos si la tabla de productos existe
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = 'pedacito_de_cielo_ca' 
              AND table_name = 'inventario_productos';
        """)
        tabla_existe = cursor.fetchone()[0] > 0
        
        # 2. Solo si NO existe, ejecutamos la creación e inserción inicial
        if not tabla_existe:
            cursor.execute("""
                CREATE TABLE pedacito_de_cielo_ca.inventario_productos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    empresa VARCHAR(150) NOT NULL DEFAULT 'REPRESENTACIONES PEDACITO DE CIELO, C.A.',
                    empresa_nombre VARCHAR(150) NOT NULL,
                    sku VARCHAR(50), 
                    descripcion VARCHAR(255) NOT NULL,
                    tipo VARCHAR(50) DEFAULT 'MATERIA_PRIMA',
                    unidad VARCHAR(20) DEFAULT 'KG',           
                    stock DECIMAL(15, 2) DEFAULT 0.00,
                    stock_minimo DECIMAL(15, 2) DEFAULT 5.00,
                    costo_usd DECIMAL(15, 4) DEFAULT 0.0000,
                    ultimo_precio_compra_usd DECIMAL(15, 4) DEFAULT 0.0000,
                    CONSTRAINT unique_sku_por_empresa UNIQUE (empresa_nombre, sku)
                );
            """)
            
            insumos_iniciales = [
                ('MP-HAR01', 'Harina de Trigo Leudante', 'MATERIA_PRIMA', 'KG', 10.00, 1.25, 1.45),
                ('MP-AZU01', 'Azúcar Refinada', 'MATERIA_PRIMA', 'KG', 8.00, 0.85, 0.95),
                ('MP-MAN01', 'Mantequilla', 'MATERIA_PRIMA', 'KG', 5.00, 2.40, 2.65),
                ('PT-TOR01', 'Torta de Vainilla Tradicional', 'PRODUCTO_TERMINADO', 'UNIDAD', 0.00, 0.00, 0.00)
            ]
            for sku, desc, tipo, unit, stock, costo_p, costo_r in insumos_iniciales:
                cursor.execute("""
                    INSERT IGNORE INTO pedacito_de_cielo_ca.inventario_productos 
                    (empresa_nombre, sku, descripcion, tipo, unidad, stock, costo_usd, ultimo_precio_compra_usd)
                    VALUES ('REPRESENTACIONES PEDACITO DE CIELO, C.A.', %s, %s, %s, %s, %s, %s, %s);
                """, (sku, desc, tipo, unit, stock, costo_p, costo_r))
            conn.commit()
            
        cursor.close()
    except Exception as e:
        st.error(f"❌ Error crítico en estructura: {e}")

    # -------------------------------------------------------------------------
    # LA JOYA CONTABLE: MOTOR DE VALORACIÓN EN LA UI
    # -------------------------------------------------------------------------
    st.sidebar.markdown("### 🧮 Motor de Costeo")
    metodo_valoracion = st.sidebar.radio(
        "Método de Valoración Activo:",
        ["Promedio Ponderado Móvil (PPM)", "Costo de Reposición (Última Compra)"],
        help="PPM: Promedio histórico exigido por el SENIAT. Reposición: Utiliza el último costo para proteger márgenes."
    )
    
    tasa_bcv_hoy = 36.50
    st.sidebar.info(f"💵 Tasa de Cambio BCV: Bs. {tasa_bcv_hoy:,.2f}")

    # AGREGA 'tab_alertas' AQUÍ ABAJO:
    tab_stock, tab_recetas, tab_movimientos, tab_alertas, tab_produccion = st.tabs([
        "📦 Control de Stock y Kardex", 
        "👩‍🍳 Recetarios y Costos", 
        "🔄 Movimientos Manuales",
        "🚨 Alertas e Inteligencia (ABC)", # <-- La nueva etiqueta para la interfaz
        "🚀 Registrar Tanda de Producción"
    ])

    # -------------------------------------------------------------------------
    # EXTRACCIÓN Y SELECCIÓN DE DATOS
    # -------------------------------------------------------------------------
    data_productos = []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sku, descripcion, tipo, unidad, stock, costo_usd, ultimo_precio_compra_usd 
            FROM pedacito_de_cielo_ca.inventario_productos 
            WHERE empresa_nombre LIKE %s
        """, ("%PEDACITO DE%CIELO%",))
        filas = cursor.fetchall()
        cursor.close()
        
        for f in filas:
            c_ppm = float(f[6]) if f[6] is not None else 0.0
            c_rep = float(f[7]) if f[7] is not None else 0.0
            costo_aplicado = c_ppm if metodo_valoracion == "Promedio Ponderado Móvil (PPM)" else c_rep
            
            data_productos.append({
                "id": f[0], "sku": f[1], "descripcion": f[2], "tipo": f[3], "unidad": f[4], 
                "stock": float(f[5]) if f[5] is not None else 0.0,
                "costo_usd": costo_aplicado,
                "costo_ppm_original": c_ppm,
                "costo_rep_original": c_rep
            })
    except Exception as e:
        st.error(f"⚠️ Error al conectar con la base de datos: {e}")

    df_prod = pd.DataFrame(data_productos) if data_productos else pd.DataFrame()

    # -------------------------------------------------------------------------
    # PESTAÑA 1: CONTROL DE STOCK Y KARDEX MULTIMONEDA
    # -------------------------------------------------------------------------
    with tab_stock:
        st.markdown(f"### 📊 Almacén Valorado vía: **{metodo_valoracion}**")
        
        if not df_prod.empty:
            c1, c2 = st.columns(2)
            with c1:
                filto_tipo = st.selectbox("Filtrar por Tipo:", ["Todos", "MATERIA_PRIMA", "PRODUCTO_TERMINADO"])
            with c2:
                buscar_prod = st.text_input("🔍 Buscar Producto/Insumo:")
                
            df_filtrado = df_prod.copy()
            if filto_tipo != "Todos":
                df_filtrado = df_filtrado[df_filtrado['tipo'] == filto_tipo]
            if buscar_prod:
                df_filtrado = df_filtrado[df_filtrado['descripcion'].str.contains(buscar_prod, case=False)]
                
            df_visual = df_filtrado.copy()
            df_visual['Costo Activo (USD)'] = df_visual['costo_usd'].map(lambda x: f"$ {x:,.2f}")
            df_visual['Valor Total (USD)'] = (df_visual['stock'] * df_visual['costo_usd']).map(lambda x: f"$ {x:,.2f}")
            df_visual['Valor Total (VES)'] = (df_visual['stock'] * df_visual['costo_usd'] * tasa_bcv_hoy).map(lambda x: f"Bs. {x:,.2f}")
            
            st.dataframe(
                df_visual[['sku', 'descripcion', 'tipo', 'stock', 'unidad', 'Costo Activo (USD)', 'Valor Total (USD)', 'Valor Total (VES)']], 
                width='stretch', hide_index=True
            )

            total_inventario_usd = (df_filtrado['stock'] * df_filtrado['costo_usd']).sum()
            met1, met2 = st.columns(2)
            with met1:
                st.metric("Total Inventario (USD)", f"$ {total_inventario_usd:,.2f}")
            with met2:
                st.metric("Total Inventario (BCV)", f"Bs. {total_inventario_usd * tasa_bcv_hoy:,.2f}")

            st.markdown("---")
            st.markdown("### 📦 Ficha Clínica del Producto (Kardex Histórico)")
            
            lista_productos_kardex = df_filtrado['descripcion'].tolist()
            producto_seleccionado = st.selectbox("Selecciona un producto para auditar su historial:", lista_productos_kardex)
            
            if producto_seleccionado:
                id_producto = df_filtrado[df_filtrado['descripcion'] == producto_seleccionado]['id'].values[0]
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT fecha, tipo_movimiento, cantidad, precio_unitario_usd, tasa_bcv, referencia, usuario
                        FROM pedacito_de_cielo_ca.inventario_kardex
                        WHERE producto_id = %s
                        ORDER BY fecha DESC
                    """, (int(id_producto),))
                    movimientos = cursor.fetchall()
                    cursor.close()
                    
                    if movimientos:
                        data_kardex = []
                        for m in movimientos:
                            cant = float(m[2])
                            p_usd = float(m[3]) if m[3] is not None else 0.0
                            tasa = float(m[4]) if m[4] is not None else 0.0
                            total_usd = cant * p_usd
                            
                            data_kardex.append({
                                "Fecha/Hora": m[0].strftime("%d/%m/%Y %H:%M") if m[0] else "N/A",
                                "Movimiento": m[1].replace("_", " "),
                                "Cantidad": cant,
                                "Precio (USD)": f"$ {p_usd:,.2f}",
                                "Tasa BCV": f"Bs. {tasa:,.2f}",
                                "Total (USD)": f"$ {total_usd:,.2f}",
                                "Total (VES)": f"Bs. {total_usd * tasa:,.2f}",
                                "Referencia": m[5],
                                "Operador": m[6]
                            })
                        st.dataframe(pd.DataFrame(data_kardex), width='stretch', hide_index=True)
                    else:
                        st.info("💡 El producto está limpio. Sin movimientos en Kardex.")
                except Exception as err_kardex:
                    st.error(f"❌ Error al consultar el Kardex: {err_kardex}")
        else:
            st.info("💡 Sin conexión o datos vacíos.")

    # -------------------------------------------------------------------------
    # PESTAÑA 2: RECETARIOS CON COSTEO EN VIVO
    # -------------------------------------------------------------------------
    with tab_recetas:
        st.markdown(f"### 👩‍🍳 Ingeniería de Recetas y Costeo Automático ({metodo_valoracion})")
        productos_terminados = df_prod[df_prod['tipo'] == 'PRODUCTO_TERMINADO']['descripcion'].tolist() if not df_prod.empty else []
        
        if productos_terminados:
            torta_seleccionada = st.selectbox("Seleccione el Producto Terminado:", productos_terminados)
            
            def obtener_costo_real(descripcion_insumo, costo_defecto):
                if not df_prod.empty:
                    match = df_prod[df_prod['descripcion'].str.contains(descripcion_insumo, case=False, na=False)]
                    if not match.empty:
                        return float(match.iloc[0]['costo_usd'])
                return costo_defecto

            costo_harina = obtener_costo_real("Harina", 1.25)
            costo_azucar = obtener_costo_real("Azúcar", 0.85)
            costo_mantequilla = obtener_costo_real("Mantequilla", 2.40)

            receta_dinamica = [
                {"Ingrediente": "Harina de Trigo", "Cantidad Requerida": 0.450, "Unidad": "KG", "Costo Unitario USD": costo_harina, "Subtotal USD": 0.450 * costo_harina},
                {"Ingrediente": "Azúcar Refinada", "Cantidad Requerida": 0.250, "Unidad": "KG", "Costo Unitario USD": costo_azucar, "Subtotal USD": 0.250 * costo_azucar},
                {"Ingrediente": "Mantequilla", "Cantidad Requerida": 0.200, "Unidad": "KG", "Costo Unitario USD": costo_mantequilla, "Subtotal USD": 0.200 * costo_mantequilla},
            ]
            df_receta = pd.DataFrame(receta_dinamica)
            df_receta_v = df_receta.copy()
            df_receta_v['Costo Unitario USD'] = df_receta_v['Costo Unitario USD'].map(lambda x: f"$ {x:,.2f}")
            df_receta_v['Subtotal USD'] = df_receta_v['Subtotal USD'].map(lambda x: f"$ {x:,.4f}")
            st.dataframe(df_receta_v, width='stretch', hide_index=True)
            
            costo_materia_prima = df_receta['Subtotal USD'].sum()
            col_rec1, col_rec2 = st.columns(2)
            with col_rec1:
                st.metric("Costo Neto MP (USD)", f"$ {costo_materia_prima:,.2f}")
            with col_rec2:
                precio_sugerido = costo_materia_prima * 2.5
                st.metric("Precio de Venta Sugerido (USD)", f"$ {precio_sugerido:,.2f}")
        else:
            st.info("💡 No hay Productos Terminados registrados.")

    # -------------------------------------------------------------------------
    # NUEVA PESTAÑA 3: MOVIMIENTOS MANUALES Y AUTOMATIZACIÓN CONTABLE (LA MARCA DE FÁBRICA)
    # -------------------------------------------------------------------------
    with tab_movimientos:
        st.markdown("### 🔄 Registro de Movimientos Manuales e Interfaz Contable ERP")
        st.write("Carga compras o ajustes. El sistema proyectará el asiento contable en tiempo real antes de impactar el libro mayor.")

        if not df_prod.empty:
            with st.form("form_movimientos_manuales"):
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    prod_mov = st.selectbox("Seleccione el Producto / Insumo:", df_prod['descripcion'].tolist())
                    tipo_m = st.selectbox("Tipo de Movimiento:", ["ENTRADA_COMPRA", "SALIDA_AJUSTE", "SALIDA_MERMA"])
                with col_m2:
                    cant_m = st.number_input("Cantidad:", min_value=0.01, step=0.5, value=1.0)
                    precio_m_usd = st.number_input("Costo/Precio Unitario (USD):", min_value=0.00, step=0.1, value=1.0)
                
                ref_m = st.text_input("Referencia / Nro Factura / Motivo:", value="Factura Proveedor Nro-")
                operador_m = st.text_input("Usuario Operador:", value="Analista Contable")

                # --- MOTOR DE CONTABILIDAD AUTOMATIZADA EN CALIENTE ---
                monto_total_usd = cant_m * precio_m_usd
                monto_total_ves = monto_total_usd * tasa_bcv_hoy
                
                st.markdown("#### 📑 Borrador de Asiento Contable Automático (Indexado)")
                
                # Definición de cuentas dinámicas según el tipo de flujo
                if tipo_m == "ENTRADA_COMPRA":
                    cuenta_debe = "1.1.03.01 - Inventario de Materia Prima"
                    cuenta_haber = "2.1.01.01 - Cuentas por Pagar Proveedores"
                elif tipo_m == "SALIDA_AJUSTE":
                    cuenta_debe = "5.1.04.02 - Gastos por Ajustes de Inventario"
                    cuenta_haber = "1.1.03.01 - Inventario de Materia Prima"
                else: # SALIDA_MERMA
                    cuenta_debe = "6.1.02.15 - Pérdidas por Mermas en Producción"
                    cuenta_haber = "1.1.03.01 - Inventario de Materia Prima"

                asiento_data = [
                    {"Código / Cuenta": cuenta_debe, "Debe (USD)": f"$ {monto_total_usd:,.2f}", "Haber (USD)": "$ 0.00", "Debe (VES)": f"Bs. {monto_total_ves:,.2f}", "Haber (VES)": "Bs. 0.00"},
                    {"Código / Cuenta": cuenta_haber, "Debe (USD)": "$ 0.00", "Haber (USD)": f"$ {monto_total_usd:,.2f}", "Debe (VES)": "Bs. 0.00", "Haber (VES)": f"Bs. {monto_total_ves:,.2f}"}
                ]
                st.table(asiento_data)
                st.caption("⚠️ Al procesar se inyectará el Kardex físico y quedará registrada la pre-póliza contable para la auditoría del SENIAT.")

                btn_procesar_m = st.form_submit_button("💾 Procesar Movimiento e Inyectar Contabilidad")

                if btn_procesar_m:
                    try:
                        cursor = conn.cursor()
                        row_prod = df_prod[df_prod['descripcion'] == prod_mov].iloc[0]
                        id_p_mov = int(row_prod['id'])
                        stock_actual = float(row_prod['stock'])
                        costo_ppm_actual = float(row_prod['costo_ppm_original'])

                        # Operación matemática del inventario físico
                        if "ENTRADA" in tipo_m:
                            nuevo_stock = stock_actual + cant_m
                            # Si es compra, recalculamos el Promedio Ponderado Móvil (PPM) exigido legalmente
                            nuevo_costo_ppm = ((stock_actual * costo_ppm_actual) + (cant_m * precio_m_usd)) / nuevo_stock if nuevo_stock > 0 else precio_m_usd
                            ultimo_costo_rep = precio_m_usd
                        else:
                            nuevo_stock = stock_actual - cant_m
                            nuevo_costo_ppm = costo_ppm_actual  # En salidas el costo promedio se mantiene
                            ultimo_costo_rep = float(row_prod['costo_rep_original'])

                        # 1. Update maestro de productos
                        cursor.execute("""
                            UPDATE pedacito_de_cielo_ca.inventario_productos 
                            SET stock = %s, costo_usd = %s, ultimo_precio_compra_usd = %s 
                            WHERE id = %s
                        """, (nuevo_stock, nuevo_costo_ppm, ultimo_costo_rep, id_p_mov))

                        # 2. Inyección en Kardex
                        cursor.execute("""
                            INSERT INTO pedacito_de_cielo_ca.inventario_kardex 
                            (producto_id, tipo_movimiento, cantidad, precio_unitario_usd, tasa_bcv, referencia, usuario)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (id_p_mov, tipo_m, cant_m, precio_m_usd, tasa_bcv_hoy, ref_m, operador_m))

                        conn.commit()
                        cursor.close()
                        st.success(f"✅ ¡Movimiento procesado! Stock actualizado a {nuevo_stock} unidades y asiento contable archivado de forma segura.")
                        st.rerun()

                    except Exception as err_mov:
                        conn.rollback()
                        st.error(f"❌ Error al ejecutar el movimiento: {err_mov}")
        else:
            st.info("💡 Registre productos primero para poder mover inventario.")

    # -------------------------------------------------------------------------
    # PESTAÑA 4: PRODUCCIÓN CON DESCUENTO AUTOMÁTICO
    # -------------------------------------------------------------------------
    with tab_produccion:
        st.markdown("### 🚀 Panel de Producción Activa")
        
        if productos_terminados:
            with st.form("form_produccion_diaria"):
                prod_a_producir = st.selectbox("¿Qué se produjo en el taller/horno?", productos_terminados)
                cantidad_tanda = st.number_input("Cantidad de Unidades Listas:", min_value=1, value=10)
                fecha_prod = st.date_input("Fecha de Producción:", datetime.now())
                pastelero_responsable = st.text_input("Pastelero Responsable:", value="Pastelero Principal")
                
                if st.form_submit_button("🔥 Procesar Tanda de Producción e Inyectar a Stock"):
                    try:
                        cursor = conn.cursor()
                        
                        cant_harina = 0.450 * cantidad_tanda
                        cant_azucar = 0.250 * cantidad_tanda
                        cant_mantequilla = 0.200 * cantidad_tanda
                        
                        def traer_metadatos(buscar):
                            cursor.execute("SELECT id, costo_usd FROM pedacito_de_cielo_ca.inventario_productos WHERE descripcion LIKE %s", (f"%{buscar}%",))
                            res = cursor.fetchone()
                            return (res[0], float(res[1])) if res else (None, 0.0)
                        
                        id_pt, costo_pt = traer_metadatos(prod_a_producir)
                        id_h, costo_h = traer_metadatos("Harina")
                        id_a, costo_a = traer_metadatos("Azúcar")
                        id_m, costo_m = traer_metadatos("Mantequilla")
                        
                        referencia_doc = f"Tanda Prod: {cantidad_tanda} Unds de {prod_a_producir}"
                        
                        # Descuentos y aumentos en caliente
                        cursor.execute("UPDATE pedacito_de_cielo_ca.inventario_productos SET stock = stock + %s WHERE id = %s", (cantidad_tanda, id_pt))
                        cursor.execute("UPDATE pedacito_de_cielo_ca.inventario_productos SET stock = stock - %s WHERE id = %s", (cant_harina, id_h))
                        cursor.execute("UPDATE pedacito_de_cielo_ca.inventario_productos SET stock = stock - %s WHERE id = %s", (cant_azucar, id_a))
                        cursor.execute("UPDATE pedacito_de_cielo_ca.inventario_productos SET stock = stock - %s WHERE id = %s", (cant_mantequilla, id_m))
                        
                        sql_kardex = """
                            INSERT INTO pedacito_de_cielo_ca.inventario_kardex 
                            (producto_id, tipo_movimiento, cantidad, precio_unitario_usd, tasa_bcv, referencia, usuario)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """
                        costo_estimado_pt = (0.450 * costo_h) + (0.250 * costo_a) + (0.200 * costo_m)
                        
                        cursor.execute(sql_kardex, (id_pt, 'ENTRADA_COMPRA', cantidad_tanda, costo_estimado_pt, tasa_bcv_hoy, referencia_doc, pastelero_responsable))
                        cursor.execute(sql_kardex, (id_h, 'SALIDA_PRODUCCION', cant_harina, costo_h, tasa_bcv_hoy, referencia_doc, pastelero_responsable))
                        cursor.execute(sql_kardex, (id_a, 'SALIDA_PRODUCCION', cant_azucar, costo_a, tasa_bcv_hoy, referencia_doc, pastelero_responsable))
                        cursor.execute(sql_kardex, (id_m, 'SALIDA_PRODUCCION', cant_mantequilla, costo_m, tasa_bcv_hoy, referencia_doc, pastelero_responsable))
                        
                        conn.commit()
                        cursor.close()
                        
                        st.success(f"💥 ¡Tanda procesada con éxito y Kardex actualizado!")
                        st.balloons()
                        st.rerun()
                        
                    except Exception as err_produccion:
                        conn.rollback()
                        st.error(f"❌ Error crítico en producción: {err_produccion}")
        else:
            st.info("💡 Registre insumos y productos terminados para habilitar producción.")

    # -------------------------------------------------------------------------
    # NUEVA PESTAÑA 4: ALERTAS INTELIGENTES Y ALGORITMO ABC (IA ENGINE)
    # -------------------------------------------------------------------------
    with tab_alertas:
        st.markdown("### 🚨 Panel de Alertas Predictivas e Inteligencia de Negocio")
        st.write("Análisis en tiempo real del inventario físico y el comportamiento de la demanda histórica del Kardex.")

        if not df_prod.empty:
            # --- PARCHE DE SEGURIDAD CONTRA KEYERROR ---
            if 'stock_minimo' not in df_prod.columns:
                df_prod['stock_minimo'] = 5.00  # Valor estándar por defecto si falta la columna

            # --- 1. MOTOR SEMÁFORO (ESTADO CRÍTICO DE STOCK) ---
            st.markdown("#### 🚦 Semáforo de Gestión de Almacén")
            
            def calcular_semaforo(row):
                stk = row['stock']
                minimo = row['stock_minimo']
                if stk < minimo:
                    return "🔴 ROJO (Quiebre Inminente)"
                elif stk <= (minimo * 1.3): # Un 30% por encima del mínimo ya es zona de alerta
                    return "🟡 AMARILLO (Cerca del Límite)"
                else:
                    return "🟢 VERDE (Surtido Optimo)"

            df_semaforo = df_prod.copy()
            df_semaforo['Estado'] = df_semaforo.apply(calcular_semaforo, axis=1)
            
            # Formateo visual para la UI del cliente
            df_semaforo_v = df_semaforo.copy()
            df_semaforo_v['Diferencia vs Mínimo'] = df_semaforo_v['stock'] - df_semaforo_v['stock_minimo']
            
            st.dataframe(
                df_semaforo_v[['Estado', 'sku', 'descripcion', 'stock', 'stock_minimo', 'Diferencia vs Mínimo', 'unidad']],
                width='stretch', hide_index=True
            )

            # Tarjetas de resumen rápidas
            cant_rojos = len(df_semaforo[df_semaforo['Estado'].str.contains("🔴")])
            cant_amarillos = len(df_semaforo[df_semaforo['Estado'].str.contains("🟡")])
            
            c_tar1, c_tar2 = st.columns(2)
            with c_tar1:
                if cant_rojos > 0:
                    st.error(f"🚨 ¡Papi, tienes {cant_rojos} producto(s) en zona de quiebre crítico! Genera compras ya.")
                else:
                    st.success("✅ No tienes productos en Rojo. ¡Excelente control de reposición!")
            with c_tar2:
                if cant_amarillos > 0:
                    st.warning(f"⚠️ Atención: {cant_amarillos} producto(s) en Amarillo. Monitorea el consumo semanal.")

            st.markdown("---")

            # --- 2. ANALÍTICA DE ROTACIÓN (ALGORITMO ABC CONTABLE) ---
            st.markdown("#### 📊 Clasificación de Rotación Automática (Algoritmo ABC)")
            st.write("Cálculo ejecutado analizando las salidas por producción, ventas o mermas registradas en los últimos 90 días.")

            try:
                cursor = conn.cursor()
                # Consultamos las salidas totales de los últimos 3 meses del Kardex
                fecha_limite = datetime.now() - timedelta(days=90)
                cursor.execute("""
                    SELECT producto_id, SUM(cantidad * precio_unitario_usd) as valor_salida_total, MAX(fecha) as ultima_salida
                    FROM pedacito_de_cielo_ca.inventario_kardex
                    WHERE tipo_movimiento LIKE 'SALIDA%' AND fecha >= %s
                    GROUP BY producto_id
                """, (fecha_limite,))
                salidas_kardex = cursor.fetchall()
                cursor.close()

                # Mapeamos salidas con los nombres de productos
                dict_salidas = {row[0]: {"valor": float(row[1]), "fecha": row[2]} for row in salidas_kardex}
                
                abc_list = []
                valor_total_salidas_global = 0.0

                for index, prod in df_prod.iterrows():
                    p_id = prod['id']
                    val_salida = dict_salidas.get(p_id, {"valor": 0.0, "fecha": None})["valor"]
                    f_salida = dict_salidas.get(p_id, {"valor": 0.0, "fecha": None})["fecha"]
                    
                    valor_total_salidas_global += val_salida
                    abc_list.append({
                        "id": p_id,
                        "sku": prod['sku'],
                        "descripcion": prod['descripcion'],
                        "Valor Inversión Movilizada (USD)": val_salida,
                        "Último Movimiento de Salida": f_salida.strftime("%d/%m/%Y") if f_salida else "Sin salidas en 90 días"
                    })

                df_abc = pd.DataFrame(abc_list)

                if valor_total_salidas_global > 0:
                    # Ordenamos de mayor a menor valor movilizado para aplicar Pareto (80/20)
                    df_abc = df_abc.sort_values(by="Valor Inversión Movilizada (USD)", ascending=False)
                    df_abc['% Participación'] = (df_abc['Valor Inversión Movilizada (USD)'] / valor_total_salidas_global) * 100
                    df_abc['% Acumulado'] = df_abc['% Participación'].cumsum()

                    # Clasificación según teoría ERP
                    def clasificar_abc(acum):
                        if acum <= 70.0:
                            return "Clase A (Alta Rotación - 70% del valor)"
                        elif acum <= 95.0:
                            return "Clase B (Rotación Media)"
                        else:
                            return "Clase C (Baja Rotación - Peligro Inmovilizado)"

                    df_abc['Clase ABC'] = df_abc['% Acumulado'].apply(clasificar_abc)
                    
                    # Formateo estético para mostrar al dueño
                    df_abc_v = df_abc.copy()
                    df_abc_v['Valor Inversión Movilizada (USD)'] = df_abc_v['Valor Inversión Movilizada (USD)'].map(lambda x: f"$ {x:,.2f}")
                    df_abc_v['% Participación'] = df_abc_v['% Participación'].map(lambda x: f"{x:.2f}%")
                    
                    st.dataframe(
                        df_abc_v[['Clase ABC', 'sku', 'descripcion', 'Valor Inversión Movilizada (USD)', '% Participación', 'Último Movimiento de Salida']],
                        width='stretch', hide_index=True
                    )
                    
                    # --- RECOMENDACIONES PREDICTIVAS DE LA IA ---
                    st.markdown("#### 💡 Recomendaciones del Asistente Contable ERP:")
                    for _, r in df_abc.iterrows():
                        if "Clase A" in r['Clase ABC']:
                            st.info(f"💎 **{r['descripcion']}** es **Clase A**. Representa el motor de tu producción. Muévelo al frente del taller y mantén stock de seguridad alto.")
                        elif "Clase C" in r['Clase ABC']:
                            st.error(f"⚠️ **{r['descripcion']}** es **Clase C**. Tiene muy baja salida financiera. Evalúa si tienes exceso de compras trancadas para cuidar el flujo de caja.")
                else:
                    st.info("💡 Para calcular la rotación ABC del taller, se necesitan registrar consumos en producción o salidas manuales primero.")
            except Exception as err_abc:
                st.error(f"❌ Error en el motor analítico ABC: {err_abc}")
        else:
            st.info("💡 Base de datos vacía.")


TIEMPO_INACTIVITY_MAX = 15 * 60  # 15 minutos totales
TIEMPO_AVISO_PREVIO = 60        # Avisar cuando falten 60 segundos

def verificar_inactividad():
    if 'logueado' in st.session_state and st.session_state['logueado']:
        tiempo_actual = time.time()
        ultimo_tiempo = st.session_state.get('ultimo_tiempo_activo', tiempo_actual)
        
        # Calculamos cuánto tiempo ha pasado sin interactuar
        inactivo_por = tiempo_actual - ultimo_tiempo
        tiempo_restante = TIEMPO_INACTIVITY_MAX - inactivo_por
        
        if inactivo_por > TIEMPO_INACTIVITY_MAX:
            # Si pasó el límite, limpiamos toda la sesión y forzamos el cierre
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.warning("⚠️ Su sesión ha expirado por inactividad.")
            time.sleep(2.0)
            st.rerun()
            
        elif tiempo_restante <= TIEMPO_AVISO_PREVIO:
            # Si está en los últimos segundos, le advertimos en pantalla
            segundos_cd = int(tiempo_restante)
            st.warning(f"⚠️ **Advertencia de inactividad:** Su sesión se cerrará en **{segundos_cd} segundos** por falta de uso. Haga clic en cualquier parte o interactúe para continuar.")
            
            # Actualizamos el cronómetro con la acción actual si el usuario hace algo,
            # pero mantenemos el aviso visible en esta recarga.
            st.session_state['ultimo_tiempo_activo'] = tiempo_actual
        else:
            # Actualizamos el cronómetro normalmente con la acción actual
            st.session_state['ultimo_tiempo_activo'] = tiempo_actual



@st.cache_data(ttl=300)
def obtener_patrimonio_acumulado(db, fecha_corte):
    conn = conectar_db(db)
    if not conn:
        return 0.0
    query = """
        SELECT SUM(saldo) as total_patrimonio FROM (
            SELECT (haber - debe) as saldo FROM saldos_iniciales WHERE plan_cuentas LIKE '3%'
            UNION ALL
            SELECT (haber - debe) as saldo FROM asientos_contables 
            WHERE plan_cuentas LIKE '3%' AND fecha <= %s
        ) as subconsulta
    """
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, (fecha_corte,))
        res = cursor.fetchone()
        return float(res['total_patrimonio'] or 0.0)
    finally:
        cursor.close()
        conn.close()

@st.cache_data(ttl=300)
def obtener_utilidad_acumulada_historica(db, fecha_corte):
    conn = conectar_db(db)
    df_default = 0.0
    if not conn:
        st.warning("⚠️ No se pudo conectar a la base de datos en obtener_utilidad_acumulada_historica.")
        return df_default
    
    fecha_fin_str = fecha_corte.strftime('%Y-%m-%d') if hasattr(fecha_corte, 'strftime') else str(fecha_corte).split()[0]

    # CORREGIDO: Se usa .format() para la BD y '%%' para evitar conflictos con Python en los LIKE
    query = """
        SELECT 
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '4%%' THEN haber ELSE 0 END), 0) as ing_haber,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '4%%' THEN debe ELSE 0 END), 0) as ing_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '5%%' THEN debe ELSE 0 END), 0) as cos_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '5%%' THEN haber ELSE 0 END), 0) as cos_haber,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '6%%' THEN debe ELSE 0 END), 0) as gas_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '6%%' THEN haber ELSE 0 END), 0) as gas_haber,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '7%%' THEN haber ELSE 0 END), 0) as oing_haber,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '7%%' THEN debe ELSE 0 END), 0) as oing_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '8%%' THEN debe ELSE 0 END), 0) as oeg_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '8%%' THEN haber ELSE 0 END), 0) as oeg_haber
        FROM `{db_segura}`.asientos_contables 
        WHERE fecha <= %s
    """.format(db_segura=str(db).strip())
    
    cursor = None
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, (fecha_fin_str,))
        res = cursor.fetchone()
        if not res:
            return 0.0

        ingresos = float(res['ing_haber'] or 0) - float(res['ing_debe'] or 0)
        costos = float(res['cos_debe'] or 0) - float(res['cos_haber'] or 0)
        gastos = abs(float(res['gas_debe'] or 0) - float(res['gas_haber'] or 0))
        otros_ingresos = float(res['oing_haber'] or 0) - float(res['oing_debe'] or 0)
        otros_egresos = abs(float(res['oeg_debe'] or 0) - float(res['oeg_haber'] or 0))

        return float(ingresos - costos - gastos + otros_ingresos - otros_egresos)
        
    except Exception as e:
        st.error(f"❌ Error crítico en `obtener_utilidad_acumulada_historica`: {e}")
        return 0.0
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def obtener_detalle_cashea(db, fecha_inicio, fecha_fin):
    # Cambia 'ref' por el nombre real de la columna si es diferente
    # Ejemplo: Si la columna se llama 'referencia', cámbiala abajo:
    query = (
        "SELECT fecha, descripcion, referencia, debe, haber, "  # <--- AJUSTA 'referencia' AQUÍ
        "SUM(haber - debe) OVER (ORDER BY fecha, id) as saldo "
        f"FROM `{str(db).strip()}`.asientos_contables "
        "WHERE plan_cuentas LIKE '2.1.3.01.001%%' "
        "AND fecha >= %s AND fecha <= %s "
        "ORDER BY fecha ASC"
    )
    
    conn = conectar_db(db)
    if not conn:
        return None
        
    try:
        df = ejecutar_consulta(query, conn, params=(fecha_inicio, fecha_fin))
        return df
    except Exception as e:
        # Esto te mostrará en la app exactamente qué columnas sí reconoce tu tabla
        print(f"Error en obtener_detalle_cashea: {e}")
        return None
    finally:
        conn.close()


def consultar_bcv_directo_sin_bd(conn=None):
    try:
        # Registro de actividad solo si conn es válido (sin is_connected)
        if conn:
            registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"Usuario {st.session_state.get('usuario', 'Desconocido')} consultando BCV")
        
        url = "https://www.bcv.org.ve/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        
        response = requests.get(url, headers=headers, verify=False, timeout=8) # Timeout un poco más corto
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_container = soup.find('div', id='dolar')
            if dolar_container:
                tasa_texto = dolar_container.find('strong').text.strip()
                return float(tasa_texto.replace(',', '.')), "Web BCV (Sin BD)"
                
    except Exception as e:
        # En lugar de pass, guarda el error en el log para saber por qué falla
        print(f"Error técnico consultando BCV: {e}")
        
    finally:
        # Mantenemos el ping de forma segura para PyMySQL
        if conn:
            try:
                conn.ping(reconnect=True)
            except Exception:
                pass
            
    return 1.0000, "Por defecto (Error Total)"


def obtener_tasa_bcv_hoy(conn):
    """
    Busca la tasa en la BD. Si no existe para hoy, la consulta en la web 
    del BCV, la guarda en la BD y la retorna. Incluye autoreconexión segura.
    """
    # 1. VERIFICACIÓN DE SEGURIDAD: Ping seguro para PyMySQL
    try:
        if conn:
            conn.ping(reconnect=True)
    except Exception:
        pass 

    # 2. Intentamos abrir el cursor
    try:
        cursor = conn.cursor(buffered=True)
    except Exception:
        return consultar_bcv_directo_sin_bd()

    hoy = date.today()
    
    try:
        # A. Verificar en BD
        cursor.execute("SELECT tasa_valor FROM kingdirver_ca.tasas_diarias WHERE fecha = %s", (hoy,))
        resultado = cursor.fetchone()
        
        if resultado:
            cursor.close()
            return float(resultado[0]), "Base de Datos"
        
        # B. Si não está en BD, consultamos la Web
        url = "https://www.bcv.org.ve/"
        headers = {"User-Agent": "Mozilla/5.0..."}
        
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_container = soup.find('div', id='dolar')
            
            if dolar_container:
                tasa_texto = dolar_container.find('strong').text.strip()
                tasa_float = float(tasa_texto.replace(',', '.'))
                
                # --- LOG DE CONSULTA ---
                try:
                    registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"El usuario {st.session_state.get('usuario', 'Desconocido')} consultó la tasa del BCV")
                except Exception:
                    pass # Si el log falla, la app sigue viva
                
                # Guardar en BD
                cursor.execute("""
                    INSERT INTO kingdirver_ca.tasas_diarias (fecha, tasa_valor) 
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE tasa_valor = %s
                """, (hoy, tasa_float, tasa_float))
                conn.commit()
                
                cursor.close()
                return tasa_float, "Web BCV"
        
        cursor.close()
        return consultar_bcv_directo_sin_bd()
        
    except Exception:
        return consultar_bcv_directo_sin_bd()


def generar_reporte_multimoneda(conn, mes, ano, db="kingdirver_ca"):
    """
    Consolida saldos iniciales con los asientos contables del mes seleccionado, 
    aplicando la conversión a USD al vuelo de forma segura.
    """
    if not conn:
        return []
        
    cursor = conn.cursor()
    
    query = f"""
        SELECT 
            t_origen.fecha,
            t_origen.plan_cuentas,      
            t_origen.cuenta_contable,
            t_origen.descripcion,
            t_origen.debe,
            t_origen.haber,
            COALESCE(
                (SELECT t.tasa_valor FROM `{db}`.tasas_diarias t WHERE t.fecha = t_origen.fecha LIMIT 1),
                (SELECT t2.tasa_valor FROM `{db}`.tasas_diarias t2 WHERE t2.fecha <= t_origen.fecha ORDER BY t2.fecha DESC LIMIT 1),
                (SELECT t3.tasa_valor FROM `{db}`.tasas_diarias t3 ORDER BY t3.fecha ASC LIMIT 1),
                1.0000
            ) AS tasa_bcv
        FROM (
            -- PARTE 1: Saldos Iniciales
            SELECT fecha, plan_cuentas, cuenta_contable, descripcion, debe, haber
            FROM `{db}`.saldos_iniciales
            WHERE YEAR(fecha) = %s
            
            UNION ALL
            
            -- PARTE 2: Asientos Contables 
            SELECT fecha, cuenta_contable AS plan_cuentas, cuenta_contable, descripcion, debe, haber
            FROM `{db}`.asientos_contables
            WHERE MONTH(fecha) = %s AND YEAR(fecha) = %s
        ) AS t_origen
        ORDER BY t_origen.fecha ASC
    """
    
    try:
        cursor.execute(query, (ano, mes, ano))
        datos = cursor.fetchall()
        cursor.close()
        return datos
    except Exception as e:
        print(f"Error en consulta contable para {db}: {e}")
        try:
            cursor.close()
        except Exception:
            pass
        return []
    
    df = pd.DataFrame(datos)
    
    if not df.empty:
        # Aseguramos que los tipos de datos sean numéricos puros para evitar fallos en la división
        df['debe'] = pd.to_numeric(df['debe'], errors='coerce').fillna(0.0)
        df['haber'] = pd.to_numeric(df['haber'], errors='coerce').fillna(0.0)
        df['tasa_bcv'] = pd.to_numeric(df['tasa_bcv'], errors='coerce').fillna(1.0)
        
        # 🔥 Operación matemática en memoria de Python
        df['debe_usd'] = df['debe'] / df['tasa_bcv']
        df['haber_usd'] = df['haber'] / df['tasa_bcv']
    
    return df


def registrar_retencion_islr_db(id_sec, rif, razon_social, direccion, factura, control, fecha, codigo, base, porc, sust, periodo, m_retenido, n_comprobante):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    if not conn: return False, 0
    
    try:
        cursor = conn.cursor()
        
        # 1. Registrar proveedor con sintaxis compatible con TiDB/MySQL
        sql_prov = """
            INSERT INTO proveedores (rif, razon_social, direccion_fiscal) 
            VALUES (%s, %s, %s) 
            ON DUPLICATE KEY UPDATE 
                direccion_fiscal = VALUES(direccion_fiscal),
                razon_social = VALUES(razon_social)
        """
        cursor.execute(sql_prov, (rif, razon_social, direccion))
        
        # 2. Insertar retención
        query_insert = """
            INSERT INTO retenciones_islr (
                id_sec, rif_retenido, numero_factura, numero_control, 
                fecha_operacion, codigo_concepto, monto_operacion, 
                porcentaje_retencion, monto_retenido, periodo_retenido,
                sustraendo, n_comprob_islr, proveedor_nombre, proveedor_direccion
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # Usamos `codigo` (el nombre correcto del parámetro) en lugar de `codigo_r`
        valores = (
            int(id_sec),           # 1. id_sec
            str(rif),              # 2. rif_retenido
            str(factura),          # 3. numero_factura
            str(control),          # 4. numero_control
            fecha,                 # 5. fecha_operacion
            str(codigo),           # 6. codigo_concepto (Corregido)
            float(base),           # 7. monto_operacion
            float(porc),           # 8. porcentaje_retencion
            float(m_retenido),     # 9. monto_retenido
            str(periodo),          # 10. periodo_retenido
            float(sust),           # 11. sustraendo
            str(n_comprobante),    # 12. n_comprob_islr
            str(razon_social),     # 13. proveedor_nombre
            str(direccion)         # 14. proveedor_direccion
        )
        
        cursor.execute(query_insert, valores)
        
        # 3. Bloqueo en libro de compras
        sql_bloqueo = """
            UPDATE libro_compras 
            SET retencion_realizada = 1 
            WHERE n_factura = %s AND rif = %s
        """
        cursor.execute(sql_bloqueo, (factura, rif))
        
        conn.commit()
        return True, m_retenido
        
    except Exception as e:
        st.error(f"⚠️ Error al guardar: {e}")
        conn.rollback()
        return False, 0
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()


def limpiar_monto_contable(valor):
    if valor is None:
        return 0.0
    
    # Si ya es un número (int o float), devuélvelo directamente
    if isinstance(valor, (int, float)):
        return float(valor)
        
    v = str(valor).strip()
    
    if v in ['-', '', 'nan', 'None', '0', '0.0']: 
        return 0.0
    
    try:
        # Si tiene tanto punto como coma (ej: "212.802.215,00")
        if '.' in v and ',' in v:
            v = v.replace('.', '')    # Quita los puntos de miles
            v = v.replace(',', '.')   # Cambia la coma decimal por punto
        elif ',' in v and '.' not in v:
            # Si solo tiene coma (ej: "4820243,00")
            v = v.replace(',', '.')
        # Si solo tiene punto, asumimos que es el separador decimal estándar de Python (ej: "4820243.00")
        # y no hacemos replace de puntos para no alterar los miles por error.
        
        return float(v)
    except:
        return 0.0


def cargar_saldos_iniciales_db(df, nombre_db):
    conn = conectar_db(nombre_db)
    
    if not conn: return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE saldos_iniciales")
        
        # Preparamos los datos en una lista de tuplas (esto es mucho más rápido)
        lista_datos = []
        for _, row in df.iterrows():
            datos = (
                str(row.get('N_comprobante', 'SI00001')),
                str(row.get('Descripcion', 'SALDOS INICIALES')),
                # Convertimos fecha de forma segura
                pd.to_datetime(row.get('Fecha')).strftime('%Y-%m-%d') if pd.notnull(row.get('Fecha')) else None,
                str(row.get('plan_de_cuentas', '')),
                str(row.get('cuenta_contable', '')),
                str(row.get('Ref', '-')),
                limpiar_monto_contable(row.get('Debe', 0)),
                limpiar_monto_contable(row.get('Haber', 0))
            )
            lista_datos.append(datos)
            
        # Inserción masiva (Patrón Pro)
        query = """INSERT INTO saldos_iniciales 
                   (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
        
        cursor.executemany(query, lista_datos)
        conn.commit()
        
        st.success("✅ Saldos iniciales procesados correctamente.")
        return True
        
    except Exception as e:
        st.error(f"❌ Error crítico en carga: {e}")
        return False
    finally:
        cursor.close()
        conn.ping(reconnect=True) # Mantenemos la conexión viva


def mostrar_analisis_rendimiento(u_v, patrimonio_total, capital_social=600000.0):
    try:
        patrimonio_total = float(patrimonio_total) if patrimonio_total is not None else 0.0
    except (ValueError, TypeError):
        patrimonio_total = 0.0

    try:
        u_v = float(u_v) if u_v is not None else 0.0
    except (ValueError, TypeError):
        u_v = 0.0

    capital_aportado = float(capital_social)
    rendimiento_pct = (u_v / capital_aportado * 100) if capital_aportado != 0 else 0

    st.subheader("📊 Composición de Capital y Rendimiento")

    c1, c2 = st.columns(2)
    c1.metric("Capital Social", f"Bs. {capital_aportado:,.2f}")
    c2.metric("Utilidad Acumulada", f"Bs. {u_v:,.2f}", f"{rendimiento_pct:.1f}% ROE")

    import plotly.graph_objects as go
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=['Capital Social', 'Utilidades Acumuladas'], 
        y=[capital_aportado, u_v], 
        name='Composición', 
        marker_color=['#2c3e50', '#27ae60']
    ))

    fig.update_layout(
        barmode='group', height=350, 
        margin=dict(l=20, r=20, t=30, b=20),
        showlegend=False
    )
    
    st.plotly_chart(fig, width='stretch', key="grafico_comparativo_capital_utilidad")

@st.cache_data(ttl=300)
def obtener_datos_agente_db(valor_busqueda):
    return _obtener_datos_agente_db_real(valor_busqueda)

def _obtener_datos_agente_db_real(valor_busqueda):
    # Forzamos a que use la conexión principal
    conn_central = conectar_db() 
    if not conn_central: 
        st.warning("⚠️ No se pudo conectar a la base de datos central en obtener_datos_agente_db.")
        return None

    cursor = None
    try:
        # Usando pymysql.cursors.DictCursor de manera consistente
        cursor = conn_central.cursor(pymysql.cursors.DictCursor)
        
        # CORREGIDO: Eliminado 'domicilio_fiscal' de ambas consultas porque no existe en la tabla
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        return datos
        
    except Exception as e:
        st.error(f"❌ Error en consulta DB: {e} | Valor buscado: {valor_busqueda}")
        return None
        
    finally:
        if cursor:
            cursor.close()
        if conn_central:
            conn_central.close()


def guardar_saldo_mensual(conn, banco, mes, ano, inicial, final, db_name=None):
    # Si no se pasa un nombre de BD explícito, intentamos sacarlo de la sesión
    if not db_name:
        db_name = st.session_state.get('DB_ACTUAL', 'kingdirver_ca')
        
    # Usamos buffered=True para que el conector consuma todo al instante
    cursor = conn.cursor(buffered=True)
    try:
        # Registro de actividad (protegido por si faltan variables en session_state)
        usuario = st.session_state.get('usuario', 'Sistema')
        cliente_id = st.session_state.get('cliente_id', 'N/A')
        registrar_log_automatico(conn, "GUARDAR_SALDO_MENSUAL", f"Usuario {usuario} guardó saldo mensual para {cliente_id} (Banco: {banco})")
        
        # Consulta dinámica usando la base de datos correcta entre backticks
        query = f"""
            INSERT INTO `{db_name}`.saldos_bancarios (banco, mes, ano, saldo_inicial, saldo_final)
            VALUES (%s, %s, %s, %s, %s) AS nuevo
            ON DUPLICATE KEY UPDATE 
            saldo_inicial = nuevo.saldo_inicial, 
            saldo_final = nuevo.saldo_final
        """
        
        cursor.execute(query, (str(banco), str(mes), int(ano), float(inicial), float(final)))
        conn.commit()
        return True
        
    except Exception as e:
        st.error(f"Error en la base de datos al guardar saldo: {e}")
        try:
            conn.rollback()
        except:
            pass
        return False
        
    finally:
        # Cerrar el cursor liberando memoria
        try:
            cursor.close() 
        except:
            pass
            
        # Mantener la conexión viva con ping en lugar de cerrarla
        try:
            conn.ping(reconnect=True)
        except:
            pass





def renderizar_tab_asientos_automatizados(db_connection):
    st.subheader("🤖 Asientos Automatizados (Comprobantes Contables)")
    st.markdown("""
    Sube tu **Libro de Compras** en Excel. El sistema procesará los datos y aplicará las reglas contables según la empresa activa.
    """)

    # ----------------------------------------------------
    # VALIDACIÓN DE ROL Y FILTRADO DE EMPRESAS (CONECTADO A `usuarios` Y `clientes`)
    # ----------------------------------------------------
    usuario_actual = str(st.session_state.get("user", st.session_state.get("usuario", "norbe"))).strip()
    
    rol_usuario = "cliente"
    es_admin = False
    db_asignada_usuario = ""

    dbs_filtradas = []
    mapa_nombres_empresas = {}
    
    try:
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_temp:
            cursor_temp.execute(
                "SELECT rol, db_nombre FROM control_central.usuarios WHERE usuario = %s", 
                (usuario_actual,)
            )
            res_usuario = cursor_temp.fetchone()
            
            if res_usuario:
                rol_usuario = str(res_usuario.get("rol", "cliente")).strip().lower()
                db_asignada_usuario = str(res_usuario.get("db_nombre", "")).strip()
            
            es_admin = rol_usuario in ["admin", "administrador"] or st.session_state.get("es_admin", False)

            cursor_temp.execute("SELECT * FROM control_central.clientes")
            clientes_db = cursor_temp.fetchall()
        
        for cli in clientes_db:
            db_name = str(cli.get("db_nombre", "")).strip()
            nombre_comercial = str(cli.get("nombre_empresa", db_name)).strip()
            
            if db_name:
                if es_admin:
                    dbs_filtradas.append(db_name)
                    mapa_nombres_empresas[db_name] = nombre_comercial
                else:
                    if db_asignada_usuario and db_name.lower() == db_asignada_usuario.lower():
                        dbs_filtradas.append(db_name)
                        mapa_nombres_empresas[db_name] = nombre_comercial
                        
    except Exception as e:
        st.warning(f"⚠️ Error consultando `control_central`: {e}")
        if es_admin:
            dbs_filtradas = ["kingdriver_ca"]
        else:
            dbs_filtradas = [db_asignada_usuario if db_asignada_usuario else "kingdriver_ca"]

    if not dbs_filtradas:
        if db_asignada_usuario:
            dbs_filtradas = [db_asignada_usuario]
        else:
            dbs_filtradas = ["kingdriver_ca"]

    if not dbs_filtradas:
        st.error("⚠️ No se encontró una empresa asignada a tu usuario en la tabla `usuarios`.")
        return

    # ----------------------------------------------------
    # INTERFAZ SEGÚN EL ROL (ADMIN VS CLIENTE)
    # ----------------------------------------------------
    if es_admin:
        st.markdown("### 🏢 Contexto de Empresa (Modo Administrador)")
        
        index_default = 0
        for i, db_name in enumerate(dbs_filtradas):
            if any(k in str(st.session_state).lower() and db_name.lower() in str(st.session_state[k]).lower() for k in st.session_state):
                index_default = i
                break
            if "driver" in db_name.lower() or "king" in db_name.lower():
                index_default = i

        format_func = lambda db: f"{mapa_nombres_empresas.get(db, db)} ({db})" if db in mapa_nombres_empresas else db
        
        nombre_db_cliente = st.selectbox(
            "Selecciona la Base de Datos de la Empresa Activa:", 
            dbs_filtradas, 
            index=index_default,
            format_func=format_func,
            key="select_db_admin_asientos"
        )
    else:
        nombre_db_cliente = dbs_filtradas[0]
        nombre_amigable = mapa_nombres_empresas.get(nombre_db_cliente, nombre_db_cliente)
        st.info(f"🏢 **Empresa Activa:** {nombre_amigable} (`{nombre_db_cliente}`)")

    if not nombre_db_cliente:
        st.error("⚠️ Debes seleccionar una base de datos.")
        return

    db_segura = str(nombre_db_cliente).strip()
    es_king_driver = any(term in db_segura.lower() for term in ["kindriver", "king_driver", "driver", "king"])

    mapa_descripciones = {}
    opciones_desplegable = []
    mapa_proveedores_cuentas = {}  

    # ----------------------------------------------------
    # CARGA SEGURA DE TABLAS: PLAN_CUENTAS Y PROVEEDORES
    # ----------------------------------------------------
    if db_connection:
        try:
            with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_opt:
                cursor_opt.execute(f"""
                    CREATE TABLE IF NOT EXISTS `{db_segura}`.plan_cuentas (
                        codigo VARCHAR(50) PRIMARY KEY,
                        nombre VARCHAR(255),
                        tipo VARCHAR(50)
                    );
                """)
                db_connection.commit()

                cursor_opt.execute(f"SELECT codigo, nombre, tipo FROM `{db_segura}`.plan_cuentas ORDER BY codigo ASC")
                cuentas_opt = cursor_opt.fetchall()
                
                cuentas_detalle = [c for c in cuentas_opt if str(c.get("tipo", "")).strip().lower() == 'detalle']
                lista_cuentas = cuentas_detalle if cuentas_detalle else cuentas_opt
                
                for c in lista_cuentas:
                    codigo = str(c.get("codigo", "")).strip()
                    nombre = str(c.get("nombre", "")).strip()
                    if codigo:
                        mapa_descripciones[codigo] = nombre
                        opciones_desplegable.append(codigo)  # Guardamos solo el código puro

                try:
                    cursor_opt.execute(f"SELECT * FROM `{db_segura}`.proveedores")
                    proveedores_db = cursor_opt.fetchall()
                    
                    for prov in proveedores_db:
                        p_nombre = str(prov.get("nombre", prov.get("razon_social", ""))).strip().upper()
                        p_rif = str(prov.get("rif", prov.get("RIF", ""))).strip().upper()
                        
                        p_codigo = str(prov.get("codigo_cuenta", prov.get("codigo", prov.get("cuenta_gasto", "")))).strip()
                        p_desc = str(prov.get("descripcion_cuenta", prov.get("descripcion", ""))).strip()
                        p_cod_pagar = str(prov.get("codigo_cuenta_pagar", "")).strip()
                        p_desc_pagar = str(prov.get("descripcion_cuenta_pagar", "")).strip()
                        
                        info_prov = {
                            "codigo_cuenta": p_codigo,
                            "descripcion_cuenta": p_desc,
                            "codigo_cuenta_pagar": p_cod_pagar,
                            "descripcion_cuenta_pagar": p_desc_pagar
                        }
                        if p_rif: mapa_proveedores_cuentas[p_rif] = info_prov
                        if p_nombre: mapa_proveedores_cuentas[p_nombre] = info_prov
                except Exception:
                    pass

                if not opciones_desplegable:
                    st.warning(f"⚠️ La tabla 'plan_cuentas' en `{db_segura}` está vacía. Se cargaron cuentas temporales de respaldo.")
                    opciones_desplegable = ["5.1.1.01.001", "5.1.1.01.002", "1.1.4.01.001", "2.1.1.01.001"]
                    mapa_descripciones = {
                        "5.1.1.01.001": "Compras Generales",
                        "5.1.1.01.002": "IVA al Costo",
                        "1.1.4.01.001": "IVA Crédito Fiscal",
                        "2.1.1.01.001": "Cuentas por Pagar Comerciales"
                    }
                
        except Exception as e:
            st.warning(f"⚠️ Advertencia al consultar tablas en `{db_segura}`: {e}. Usando plan de cuentas de emergencia.")
            opciones_desplegable = ["5.1.1.01.001", "5.1.1.01.002", "1.1.4.01.001", "2.1.1.01.001"]
            mapa_descripciones = {
                "5.1.1.01.001": "Compras Generales",
                "5.1.1.01.002": "IVA al Costo",
                "1.1.4.01.001": "IVA Crédito Fiscal",
                "2.1.1.01.001": "Cuentas por Pagar Comerciales"
            }

    default_opcion = opciones_desplegable[0] if opciones_desplegable else "5.1.1.01.001"

    def obtener_opcion_valida(codigo_buscado, fallback):
        if codigo_buscado in opciones_desplegable:
            return codigo_buscado
        return fallback

    # ----------------------------------------------------
    # PRIMER FRAME: CARGA Y VISTA PREVIA DEL EXCEL
    # ----------------------------------------------------
    st.markdown("---")
    st.markdown("### 📋 Primer Frame: Libro de Compras Subido")
    
    if es_king_driver:
        st.success("🚗 **Modo King Driver Detectado:** El sistema aplicará automáticamente el IVA al costo utilizando la cuenta `5.1.1.01.002`.")
    else:
        st.info("🏢 **Modo Empresa Regular:** El sistema aplicará Crédito Fiscal estándar.")

    archivo_excel = st.file_uploader("Subir Libro de Compras (Excel)", type=["xlsx", "xls"], key="uploader_libro_compras")

    if archivo_excel is not None:
        try:
            df_compras = pd.read_excel(archivo_excel)
            df_compras.columns = df_compras.columns.str.strip()
            
            st.dataframe(df_compras, use_container_width=True)

            st.markdown("---")
            st.markdown("### ⚙️ Configuración de Asientos")
            
            col_cfg1, col_cfg2 = st.columns(2)
            with col_cfg1:
                n_comprobante_base = st.text_input("Prefijo de Comprobante:", value="050001")
            with col_cfg2:
                st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("🔄 Generar Estructura del Segundo Frame", key="btn_generar_segundo_frame"):
                try:
                    filas_asiento_temporal = []

                    for idx, row in df_compras.iterrows():
                        # CORRECCIÓN: Se evita pasar 'default' a sí mismo en su valor por defecto
                        def buscar_valor(posibles_nombres, default_val=0.0):
                            for col in df_compras.columns:
                                c_clean = str(col).strip().lower()
                                for pos in posibles_nombres:
                                    if pos.lower() in c_clean:
                                        val = row[col]
                                        if pd.notna(val):
                                            return val
                            return default_val

                        raw_fecha = buscar_valor(["Fecha de Operación", "Fecha de Operacion", "Fecha"], "")
                        if hasattr(raw_fecha, "strftime"):
                            fecha_op = raw_fecha.strftime("%Y-%m-%d")
                        else:
                            val_str = str(raw_fecha).strip().split(" ")[0]
                            try:
                                fecha_op = pd.to_datetime(val_str).strftime("%Y-%m-%d")
                            except Exception:
                                fecha_op = val_str[:10] if val_str else ""

                        razon_social = str(buscar_valor(["Nombre o Razón Social", "Nombre o Razon Social", "Razon Social", "Proveedor"], "Sin Nombre")).strip()
                        rif_val = str(buscar_valor(["R.I.F.", "RIF", "Cedula"], "")).strip().upper()
                        nro_doc = str(buscar_valor(["Número de Documento", "Numero de Documento", "Nro Documento", "Factura"], f"{idx+1}")).strip()

                        try:
                            base_imponible = float(buscar_valor(["Base Imponible"], 0.0))
                        except Exception:
                            base_imponible = 0.0

                        try:
                            compras_exentas = float(buscar_valor(["Compras Exentas", "Exentas", "Sin Derecho a Crédito", "Sin Derecho a Credito"], 0.0))
                        except Exception:
                            compras_exentas = 0.0

                        try:
                            credito_fiscal = float(buscar_valor(["Credito Fiscales", "Crédito Fiscales", "Credito Fiscal", "IVA"], 0.0))
                        except Exception:
                            credito_fiscal = 0.0

                        try:
                            total_compras = float(buscar_valor(["Total Compras"], base_imponible + compras_exentas + credito_fiscal))
                        except Exception:
                            total_compras = base_imponible + compras_exentas + credito_fiscal

                        n_comprobante_actual = f"{n_comprobante_base}-{nro_doc}"

                        opcion_gasto = None
                        opcion_contrapartida = None
                        
                        datos_prov = mapa_proveedores_cuentas.get(rif_val) or mapa_proveedores_cuentas.get(razon_social.upper())
                        if datos_prov:
                            p_cod_gasto = str(datos_prov.get("codigo_cuenta", "")).strip()
                            if p_cod_gasto:
                                opcion_gasto = obtener_opcion_valida(p_cod_gasto, None)

                            p_cod_pagar = str(datos_prov.get("codigo_cuenta_pagar", "")).strip()
                            if p_cod_pagar:
                                opcion_contrapartida = obtener_opcion_valida(p_cod_pagar, None)

                        if not opcion_gasto:
                            for opt in opciones_desplegable:
                                if opt.startswith("5") and "iva" not in opt.lower():
                                    opcion_gasto = opt
                                    break
                        if not opcion_gasto: 
                            opcion_gasto = default_opcion

                        if not opcion_contrapartida:
                            for opt in opciones_desplegable:
                                if opt.startswith("2.1.1") or opt.startswith("2"):
                                    opcion_contrapartida = opt
                                    break
                        if not opcion_contrapartida: 
                            opcion_contrapartida = default_opcion

                        monto_costo_debe = base_imponible + compras_exentas

                        if es_king_driver:
                            filas_asiento_temporal.append({
                                "n_comprobante": n_comprobante_actual,
                                "descripcion": f"Factura {nro_doc} - {razon_social}",
                                "fecha": fecha_op,
                                "plan_cuentas": opcion_gasto,
                                "cuenta_contable": mapa_descripciones.get(opcion_gasto, ""),
                                "referencia": nro_doc,
                                "debe": monto_costo_debe,
                                "haber": 0.0
                            })

                            monto_iva_linea = 0.0
                            if credito_fiscal > 0:
                                monto_iva_linea = credito_fiscal
                                opcion_iva_kd = default_opcion
                                for opt in opciones_desplegable:
                                    if opt.startswith("5.1.1.01.002"):
                                        opcion_iva_kd = opt
                                        break
                                
                                filas_asiento_temporal.append({
                                    "n_comprobante": n_comprobante_actual,
                                    "descripcion": f"IVA al Costo Factura {nro_doc} - {razon_social}",
                                    "fecha": fecha_op,
                                    "plan_cuentas": opcion_iva_kd,
                                    "cuenta_contable": mapa_descripciones.get(opcion_iva_kd, ""),
                                    "referencia": nro_doc,
                                    "debe": credito_fiscal,
                                    "haber": 0.0
                                })
                            
                            monto_haber_total = monto_costo_debe + monto_iva_linea
                        else:
                            filas_asiento_temporal.append({
                                "n_comprobante": n_comprobante_actual,
                                "descripcion": f"Factura {nro_doc} - {razon_social}",
                                "fecha": fecha_op,
                                "plan_cuentas": opcion_gasto,
                                "cuenta_contable": mapa_descripciones.get(opcion_gasto, ""),
                                "referencia": nro_doc,
                                "debe": monto_costo_debe,
                                "haber": 0.0
                            })

                            monto_iva_linea = 0.0
                            if credito_fiscal > 0:
                                monto_iva_linea = credito_fiscal
                                opcion_iva = default_opcion
                                for opt in opciones_desplegable:
                                    if opt.startswith("1.1.4.01.001"):
                                        opcion_iva = opt
                                        break
                                
                                filas_asiento_temporal.append({
                                    "n_comprobante": n_comprobante_actual,
                                    "descripcion": f"IVA Crédito Fiscal Factura {nro_doc} - {razon_social}",
                                    "fecha": fecha_op,
                                    "plan_cuentas": opcion_iva,
                                    "cuenta_contable": mapa_descripciones.get(opcion_iva, ""),
                                    "referencia": nro_doc,
                                    "debe": credito_fiscal,
                                    "haber": 0.0
                                })
                            
                            monto_haber_total = monto_costo_debe + monto_iva_linea

                        filas_asiento_temporal.append({
                            "n_comprobante": n_comprobante_actual,
                            "descripcion": f"Cuentas por Pagar Factura {nro_doc} - {razon_social}",
                            "fecha": fecha_op,
                            "plan_cuentas": opcion_contrapartida,
                            "cuenta_contable": mapa_descripciones.get(opcion_contrapartida, ""),
                            "referencia": nro_doc,
                            "debe": 0.0,
                            "haber": monto_haber_total
                        })

                    st.session_state['df_asientos_proceso'] = pd.DataFrame(filas_asiento_temporal)
                    st.rerun()

                except Exception as proc_err:
                    st.error(f"Error procesando los datos: {proc_err}")

            # ----------------------------------------------------
            # SEGUNDO FRAME: ESTRUCTURA COMPLETA
            # ----------------------------------------------------
            if 'df_asientos_proceso' in st.session_state and not st.session_state['df_asientos_proceso'].empty:
                df_a_procesar = st.session_state['df_asientos_proceso']
                
                st.markdown(f"### 📋 Segundo Frame: Estructura Completa del Asiento Contable ({len(df_a_procesar)} registros)")
                
                def extraer_solo_codigo(val):
                    val_str = str(val).strip()
                    if " - " in val_str:
                        return val_str.split(" - ")[0].strip()
                    return val_str

                for idx in df_a_procesar.index:
                    codigo_puro = extraer_solo_codigo(df_a_procesar.at[idx, "plan_cuentas"])
                    df_a_procesar.at[idx, "plan_cuentas"] = codigo_puro
                    df_a_procesar.at[idx, "cuenta_contable"] = mapa_descripciones.get(codigo_puro, "")

                opciones_codigos_puros = list(mapa_descripciones.keys())
                if not opciones_codigos_puros:
                    opciones_codigos_puros = ["5.1.1.01.001", "5.1.1.01.002", "1.1.4.01.001", "2.1.1.01.001"]

                df_editado = st.data_editor(
                    df_a_procesar,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config={
                        "n_comprobante": st.column_config.TextColumn("n_comprobante"),
                        "descripcion": st.column_config.TextColumn("Descripción"),
                        "fecha": st.column_config.TextColumn("Fecha"),
                        "plan_cuentas": st.column_config.SelectboxColumn(
                            "Plan de Cuentas (Código)",
                            options=opciones_codigos_puros,
                            required=True
                        ),
                        "cuenta_contable": st.column_config.TextColumn("Descripción Cuenta", disabled=True),
                        "referencia": st.column_config.TextColumn("Referencia"),
                        "debe": st.column_config.NumberColumn("Debe", format="%,.2f"),
                        "haber": st.column_config.NumberColumn("Haber", format="%,.2f"),
                    },
                    key="editor_segundo_frame"
                )
                
                for idx in df_editado.index:
                    codigo_puro = extraer_solo_codigo(df_editado.at[idx, "plan_cuentas"])
                    df_editado.at[idx, "plan_cuentas"] = codigo_puro
                    df_editado.at[idx, "cuenta_contable"] = mapa_descripciones.get(codigo_puro, "")

                st.session_state['df_asientos_proceso'] = df_editado

                tot_debe = df_editado['debe'].sum()
                tot_haber = df_editado['haber'].sum()
                col_m1, col_m2 = st.columns(2)
                col_m1.metric("Total Debe (General)", f"{tot_debe:,.2f}")
                col_m2.metric("Total Haber (General)", f"{tot_haber:,.2f}")

                buffer_excel = io.BytesIO()
                with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                    df_editado.to_excel(writer, index=False, sheet_name='Asientos_Contables')
                buffer_excel.seek(0)

                st.download_button(
                    label="📥 Descargar Estructura en Excel",
                    data=buffer_excel,
                    file_name=f"asientos_contables_{db_segura}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_descargar_excel_asientos",
                    use_container_width=True
                )

                if st.button("💾 Guardar Todo el Asiento en el Libro Diario", key="btn_guardar_asientos_finales", use_container_width=True):
                    try:
                        with db_connection.cursor() as cursor:
                            cursor.execute(f"""
                                CREATE TABLE IF NOT EXISTS `{db_segura}`.asientos_contables (
                                    id INT AUTO_INCREMENT PRIMARY KEY,
                                    n_comprobante VARCHAR(50),
                                    descripcion TEXT,
                                    fecha DATE,
                                    plan_cuentas VARCHAR(100),
                                    cuenta_contable VARCHAR(255),
                                    referencia VARCHAR(100),
                                    debe DECIMAL(15, 2) DEFAULT 0.00,
                                    haber DECIMAL(15, 2) DEFAULT 0.00
                                );
                            """)
                            
                            for _, row in df_editado.iterrows():
                                codigo_limpio = extraer_solo_codigo(row["plan_cuentas"])
                                cursor.execute(f"""
                                    INSERT INTO `{db_segura}`.asientos_contables 
                                    (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """, (
                                    row["n_comprobante"],
                                    row["descripcion"],
                                    row["fecha"],
                                    codigo_limpio,
                                    row["cuenta_contable"],
                                    row["referencia"],
                                    row["debe"],
                                    row["haber"]
                                ))
                            db_connection.commit()
                            st.success("✅ ¡Asientos contables guardados exitosamente en el Libro Diario!")
                    except Exception as db_err:
                        st.error(f"Error al guardar en la base de datos: {db_err}")
        except Exception as e:
            st.error(f"Error al leer el archivo Excel: {e}")

def renderizar_tab_asientos_ventas(db_connection):
    st.subheader("🤖 Asientos Automatizados - Libro de Ventas")
    st.markdown("""
    Sube tu **Libro de Ventas** en Excel. El sistema procesará los datos, consultará la tabla de clientes comerciales por RIF y generará los asientos contables correspondientes.
    """)

    # ----------------------------------------------------
    # VALIDACIÓN DE ROL Y FILTRADO DE EMPRESAS
    # ----------------------------------------------------
    usuario_actual = str(st.session_state.get("user", st.session_state.get("usuario", "norbe"))).strip()
    
    rol_usuario = "cliente"
    es_admin = False
    db_asignada_usuario = ""

    dbs_filtradas = []
    mapa_nombres_empresas = {}
    
    try:
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_temp:
            cursor_temp.execute(
                "SELECT rol, db_nombre FROM control_central.usuarios WHERE usuario = %s", 
                (usuario_actual,)
            )
            res_usuario = cursor_temp.fetchone()
            
            if res_usuario:
                rol_usuario = str(res_usuario.get("rol", "cliente")).strip().lower()
                db_asignada_usuario = str(res_usuario.get("db_nombre", "")).strip()
            
            es_admin = rol_usuario in ["admin", "administrador"] or st.session_state.get("es_admin", False)

            cursor_temp.execute("SELECT * FROM control_central.clientes")
            clientes_db = cursor_temp.fetchall()
        
        for cli in clientes_db:
            db_name = str(cli.get("db_nombre", "")).strip()
            nombre_comercial = str(cli.get("nombre_empresa", db_name)).strip()
            
            if db_name:
                if es_admin:
                    dbs_filtradas.append(db_name)
                    mapa_nombres_empresas[db_name] = nombre_comercial
                else:
                    if db_asignada_usuario and db_name.lower() == db_asignada_usuario.lower():
                        dbs_filtradas.append(db_name)
                        mapa_nombres_empresas[db_name] = nombre_comercial
                        
    except Exception as e:
        st.warning(f"⚠️ Error consultando `control_central`: {e}")
        if es_admin:
            dbs_filtradas = ["kingdriver_ca"]
        else:
            dbs_filtradas = [db_asignada_usuario if db_asignada_usuario else "kingdriver_ca"]

    if not dbs_filtradas:
        if db_asignada_usuario:
            dbs_filtradas = [db_asignada_usuario]
        else:
            dbs_filtradas = ["kingdriver_ca"]

    if not dbs_filtradas:
        st.error("⚠️ No se encontró una empresa asignada a tu usuario en la tabla `usuarios`.")
        return

    # ----------------------------------------------------
    # INTERFAZ SEGÚN EL ROL (ADMIN VS CLIENTE)
    # ----------------------------------------------------
    if es_admin:
        st.markdown("### 🏢 Contexto de Empresa (Modo Administrador)")
        
        index_default = 0
        for i, db_name in enumerate(dbs_filtradas):
            if any(k in str(st.session_state).lower() and db_name.lower() in str(st.session_state[k]).lower() for k in st.session_state):
                index_default = i
                break
            if "driver" in db_name.lower() or "king" in db_name.lower():
                index_default = i

        format_func = lambda db: f"{mapa_nombres_empresas.get(db, db)} ({db})" if db in mapa_nombres_empresas else db
        
        nombre_db_cliente = st.selectbox(
            "Selecciona la Base de Datos de la Empresa Activa:", 
            dbs_filtradas, 
            index=index_default,
            format_func=format_func,
            key="select_db_admin_asientos_ventas"
        )
    else:
        nombre_db_cliente = dbs_filtradas[0]
        nombre_amigable = mapa_nombres_empresas.get(nombre_db_cliente, nombre_db_cliente)
        st.info(f"🏢 **Empresa Activa:** {nombre_amigable} (`{nombre_db_cliente}`)")

    if not nombre_db_cliente:
        st.error("⚠️ Debes seleccionar una base de datos.")
        return

    db_segura = str(nombre_db_cliente).strip()

    mapa_descripciones = {}
    opciones_desplegable = []

    # ----------------------------------------------------
    # CARGA SEGURA DE TABLA: PLAN_CUENTAS
    # ----------------------------------------------------
    if db_connection:
        try:
            with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_opt:
                cursor_opt.execute(f"SELECT codigo, nombre, tipo FROM `{db_segura}`.plan_cuentas ORDER BY codigo ASC")
                cuentas_opt = cursor_opt.fetchall()
                
                cuentas_detalle = [c for c in cuentas_opt if str(c.get("tipo", "")).strip().lower() == 'detalle']
                lista_cuentas = cuentas_detalle if cuentas_detalle else cuentas_opt
                
                for c in lista_cuentas:
                    codigo = str(c.get("codigo", "")).strip()
                    nombre = str(c.get("nombre", "")).strip()
                    if codigo:
                        mapa_descripciones[codigo] = nombre
                        opciones_desplegable.append(codigo)

                if not opciones_desplegable:
                    opciones_desplegable = ["1.1.2.01.001", "4.1.1.01.001", "2.1.2.01.001"]
                    mapa_descripciones = {
                        "1.1.2.01.001": "Cuentas por Cobrar Comerciales",
                        "4.1.1.01.001": "Ventas de Servicios / Ingresos",
                        "2.1.2.01.001": "IVA Débito Fiscal"
                    }
        except Exception as e:
            st.warning(f"⚠️ Advertencia al consultar plan de cuentas: {e}. Usando cuentas predeterminadas.")
            opciones_desplegable = ["1.1.2.01.001", "4.1.1.01.001", "2.1.2.01.001"]
            mapa_descripciones = {
                "1.1.2.01.001": "Cuentas por Cobrar Comerciales",
                "4.1.1.01.001": "Ventas de Servicios / Ingresos",
                "2.1.2.01.001": "IVA Débito Fiscal"
            }

    default_opcion = opciones_desplegable[0] if opciones_desplegable else "1.1.2.01.001"

    # ----------------------------------------------------
    # CARGAR CLIENTES COMERCIALES DESDE LA BASE DE DATOS
    # ----------------------------------------------------
    mapa_clientes_rif = {}
    try:
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_cli:
            cursor_cli.execute(f"SELECT rif, codigo_cuenta, descripcion_cuenta FROM `{db_segura}`.clientes_comerciales")
            clientes_registrados = cursor_cli.fetchall()
            for cli in clientes_registrados:
                rif_limpio = str(cli.get("rif", "")).strip().upper()
                mapa_clientes_rif[rif_limpio] = {
                    "codigo_cuenta": str(cli.get("codigo_cuenta", "")).strip(),
                    "descripcion_cuenta": str(cli.get("descripcion_cuenta", "")).strip()
                }
    except Exception as e:
        st.warning(f"⚠️ No se pudo consultar la tabla `clientes_comerciales`: {e}")

    # ----------------------------------------------------
    # CARGA Y VISTA PREVIA DEL EXCEL (LIBRO DE VENTAS)
    # ----------------------------------------------------
    st.markdown("---")
    st.markdown("### 📋 Primer Frame: Libro de Ventas Subido")

    archivo_excel = st.file_uploader("Subir Libro de Ventas (Excel)", type=["xlsx", "xls"], key="uploader_libro_ventas")

    if archivo_excel is not None:
        try:
            df_ventas = pd.read_excel(archivo_excel)
            df_ventas.columns = df_ventas.columns.str.strip()
            
            st.dataframe(df_ventas, use_container_width=True)

            st.markdown("---")
            st.markdown("### ⚙️ Configuración de Asientos de Ventas")
            
            col_cfg1, col_cfg2 = st.columns(2)
            with col_cfg1:
                n_comprobante_base = st.text_input("Número de Comprobante (Fijo para todas las líneas):", value="060001", key="prefijo_ventas")
            
            if st.button("🔄 Generar Estructura del Segundo Frame (Ventas)", key="btn_generar_frame_ventas"):
                try:
                    filas_asiento_temporal = []

                    for idx, row in df_ventas.iterrows():
                        def buscar_valor(posibles_nombres, default_val=0.0):
                            for col in df_ventas.columns:
                                c_clean = str(col).strip().lower()
                                for pos in posibles_nombres:
                                    if pos.lower() in c_clean:
                                        val = row[col]
                                        if pd.notna(val):
                                            return val
                            return default_val

                        # Búsqueda exclusiva para la fecha
                        raw_fecha = buscar_valor(["Fecha de Factura", "Fecha"], "")
                        if hasattr(raw_fecha, "strftime"):
                            fecha_op = raw_fecha.strftime("%Y-%m-%d")
                        else:
                            val_str = str(raw_fecha).strip().split(" ")[0]
                            try:
                                fecha_op = pd.to_datetime(val_str).strftime("%Y-%m-%d")
                            except Exception:
                                fecha_op = val_str[:10] if val_str else ""

                        razon_social = str(buscar_valor(["Nombre y Apellido o Razón Social", "Razon Social", "Cliente"], "Sin Nombre")).strip()
                        rif_cliente = str(buscar_valor(["R.I.F.", "RIF", "Rif"], "")).strip().upper()
                        
                        # Búsqueda exacta y segura del Número de Factura para que vaya a Referencia
                        nro_doc = ""
                        for col in df_ventas.columns:
                            c_clean = str(col).strip().lower()
                            if ("factura" in c_clean or "nro" in c_clean or "num" in c_clean) and "fecha" not in c_clean:
                                val = row[col]
                                if pd.notna(val) and str(val).strip() != "":
                                    nro_doc = str(val).strip()
                                    break
                        if not nro_doc:
                            nro_doc = str(idx + 1)

                        try:
                            ventas_exentas = float(buscar_valor(["Ventas Exentas", "Exentas"], 0.0))
                        except Exception:
                            ventas_exentas = 0.0

                        try:
                            base_imponible = float(buscar_valor(["Base Imponible"], 0.0))
                        except Exception:
                            base_imponible = 0.0

                        try:
                            debito_fiscal = float(buscar_valor(["Débito Fiscal", "Debito Fiscal"], 0.0))
                        except Exception:
                            debito_fiscal = 0.0

                        try:
                            total_ventas = float(buscar_valor(["Total Ventas Incluyendo el IVA", "Total Ventas"], base_imponible + ventas_exentas + debito_fiscal))
                        except Exception:
                            total_ventas = base_imponible + ventas_exentas + debito_fiscal

                        n_comprobante_actual = str(n_comprobante_base).strip()

                        # ----------------------------------------------------
                        # CRUCE CON LA TABLA `clientes_comerciales` SEGÚN EL RIF
                        # ----------------------------------------------------
                        opcion_cxc = default_opcion
                        descripcion_personalizada = f"Factura Venta {nro_doc} - {razon_social}"

                        if rif_cliente in mapa_clientes_rif:
                            info_cli = mapa_clientes_rif[rif_cliente]
                            if info_cli["codigo_cuenta"]:
                                opcion_cxc = info_cli["codigo_cuenta"]
                            if info_cli["descripcion_cuenta"]:
                                descripcion_personalizada = info_cli["descripcion_cuenta"]

                        opcion_ingreso = default_opcion
                        opcion_iva_debito = default_opcion

                        for opt in opciones_desplegable:
                            if opt.startswith("4"):
                                opcion_ingreso = opt
                                break
                        for opt in opciones_desplegable:
                            if "2.1.2" in opt or "debito" in mapa_descripciones.get(opt, "").lower():
                                opcion_iva_debito = opt
                                break

                        # 1. Cuentas por Cobrar (DEBE)
                        filas_asiento_temporal.append({
                            "n_comprobante": n_comprobante_actual,
                            "descripcion": descripcion_personalizada,
                            "fecha": fecha_op,
                            "plan_cuentas": opcion_cxc,
                            "cuenta_contable": mapa_descripciones.get(opcion_cxc, ""),
                            "referencia": nro_doc,  # <--- Número de factura exacto aquí
                            "debe": total_ventas,
                            "haber": 0.0
                        })

                        # 2. Ingresos (HABER)
                        monto_ingreso = base_imponible + ventas_exentas
                        if monto_ingreso > 0:
                            filas_asiento_temporal.append({
                                "n_comprobante": n_comprobante_actual,
                                "descripcion": f"Ingresos por Ventas Factura {nro_doc} - {razon_social}",
                                "fecha": fecha_op,
                                "plan_cuentas": opcion_ingreso,
                                "cuenta_contable": mapa_descripciones.get(opcion_ingreso, ""),
                                "referencia": nro_doc,  # <--- Número de factura exacto aquí
                                "debe": 0.0,
                                "haber": monto_ingreso
                            })

                        # 3. IVA Débito Fiscal (HABER)
                        if debito_fiscal > 0:
                            filas_asiento_temporal.append({
                                "n_comprobante": n_comprobante_actual,
                                "descripcion": f"IVA Débito Fiscal Factura {nro_doc} - {razon_social}",
                                "fecha": fecha_op,
                                "plan_cuentas": opcion_iva_debito,
                                "cuenta_contable": mapa_descripciones.get(opcion_iva_debito, ""),
                                "referencia": nro_doc,  # <--- Número de factura exacto aquí
                                "debe": 0.0,
                                "haber": debito_fiscal
                            })

                    st.session_state['df_asientos_ventas_proceso'] = pd.DataFrame(filas_asiento_temporal)
                    st.rerun()

                except Exception as proc_err:
                    st.error(f"Error procesando los datos de ventas: {proc_err}")

            # ----------------------------------------------------
            # SEGUNDO FRAME: ESTRUCTURA COMPLETA DE VENTAS
            # ----------------------------------------------------
            if 'df_asientos_ventas_proceso' in st.session_state and not st.session_state['df_asientos_ventas_proceso'].empty:
                df_a_procesar = st.session_state['df_asientos_ventas_proceso']
                
                st.markdown(f"### 📋 Segundo Frame: Estructura del Asiento de Ventas ({len(df_a_procesar)} registros)")
                
                def extraer_solo_codigo(val):
                    val_str = str(val).strip()
                    if " - " in val_str:
                        return val_str.split(" - ")[0].strip()
                    return val_str

                for idx in df_a_procesar.index:
                    codigo_puro = extraer_solo_codigo(df_a_procesar.at[idx, "plan_cuentas"])
                    df_a_procesar.at[idx, "plan_cuentas"] = codigo_puro
                    df_a_procesar.at[idx, "cuenta_contable"] = mapa_descripciones.get(codigo_puro, "")

                opciones_codigos_puros = list(mapa_descripciones.keys())
                if not opciones_codigos_puros:
                    opciones_codigos_puros = ["1.1.2.01.001", "4.1.1.01.001", "2.1.2.01.001"]

                df_editado = st.data_editor(
                    df_a_procesar,
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config={
                        "n_comprobante": st.column_config.TextColumn("n_comprobante"),
                        "descripcion": st.column_config.TextColumn("Descripción"),
                        "fecha": st.column_config.TextColumn("Fecha"),
                        "plan_cuentas": st.column_config.SelectboxColumn(
                            "Plan de Cuentas (Código)",
                            options=opciones_codigos_puros,
                            required=True
                        ),
                        "cuenta_contable": st.column_config.TextColumn("Descripción Cuenta", disabled=True),
                        "referencia": st.column_config.TextColumn("Referencia"),
                        "debe": st.column_config.NumberColumn("Debe", format="%,.2f"),
                        "haber": st.column_config.NumberColumn("Haber", format="%,.2f"),
                    },
                    key="editor_segundo_frame_ventas"
                )
                
                for idx in df_editado.index:
                    codigo_puro = extraer_solo_codigo(df_editado.at[idx, "plan_cuentas"])
                    df_editado.at[idx, "plan_cuentas"] = codigo_puro
                    df_editado.at[idx, "cuenta_contable"] = mapa_descripciones.get(codigo_puro, "")

                st.session_state['df_asientos_ventas_proceso'] = df_editado

                tot_debe = df_editado['debe'].sum()
                tot_haber = df_editado['haber'].sum()
                col_m1, col_m2 = st.columns(2)
                col_m1.metric("Total Debe (Ventas)", f"{tot_debe:,.2f}")
                col_m2.metric("Total Haber (Ventas)", f"{tot_haber:,.2f}")

                buffer_excel = io.BytesIO()
                with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                    df_editado.to_excel(writer, index=False, sheet_name='Asientos_Ventas')
                buffer_excel.seek(0)

                st.download_button(
                    label="📥 Descargar Estructura de Ventas en Excel",
                    data=buffer_excel,
                    file_name=f"asientos_ventas_{db_segura}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_descargar_excel_ventas",
                    use_container_width=True
                )

                if st.button("💾 Guardar Asientos de Ventas en el Libro Diario", key="btn_guardar_ventas_finales", use_container_width=True):
                    try:
                        with db_connection.cursor() as cursor:
                            cursor.execute(f"""
                                CREATE TABLE IF NOT EXISTS `{db_segura}`.asientos_contables (
                                    id INT AUTO_INCREMENT PRIMARY KEY,
                                    n_comprobante VARCHAR(50),
                                    descripcion TEXT,
                                    fecha DATE,
                                    plan_cuentas VARCHAR(100),
                                    cuenta_contable VARCHAR(255),
                                    referencia VARCHAR(100),
                                    debe DECIMAL(15, 2) DEFAULT 0.00,
                                    haber DECIMAL(15, 2) DEFAULT 0.00
                                );
                            """)
                            
                            for _, row in df_editado.iterrows():
                                codigo_limpio = extraer_solo_codigo(row["plan_cuentas"])
                                cursor.execute(f"""
                                    INSERT INTO `{db_segura}`.asientos_contables 
                                    (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """, (
                                    row["n_comprobante"],
                                    row["descripcion"],
                                    row["fecha"],
                                    codigo_limpio,
                                    row["cuenta_contable"],
                                    row["referencia"],
                                    row["debe"],
                                    row["haber"]
                                ))
                            db_connection.commit()
                            st.success("✅ ¡Asientos de ventas guardados exitosamente en el Libro Diario!")
                    except Exception as db_err:
                        st.error(f"Error al guardar los asientos de ventas: {db_err}")
        except Exception as e:
            st.error(f"Error al leer el archivo Excel de ventas: {e}")


def gestionar_sidebar():
    user_rol = str(st.session_state.get('rol', 'admin')).strip().lower()
    user_id = st.session_state.get('user_id', st.session_state.get('cliente_id', 'N/A'))
    nombre_usuario_actual = (
        st.session_state.get('nombre_usuario') or 
        st.session_state.get('username') or 
        st.session_state.get('usuario') or 
        'Usuario'
    )

    with st.sidebar:
        # --- ESTILOS CSS PARA CORREGIR EL EFECTO BORROSO EN LOS SELECTBOX ---
        st.markdown(
            """
            <style>
                div[data-baseweb="popover"] div[role="option"] div,
                div[data-baseweb="popover"] div[role="option"] span,
                div[data-baseweb="menu"] div,
                div[data-baseweb="menu"] span {
                    opacity: 1 !important;
                    color: #1e293b !important;
                    font-weight: 600 !important;
                }
                div[data-baseweb="popover"] {
                    background-color: #ffffff !important;
                    border: 1px solid #cbd5e1 !important;
                    border-radius: 8px !important;
                    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1) !important;
                }
                div[data-baseweb="popover"] div[role="option"]:hover {
                    background-color: #f1f5f9 !important;
                }
            </style>
            """,
            unsafe_allow_html=True
        )

        st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=100)
        st.header("Panel de Auditoría")

        # --- ETIQUETA / INSIGNIA DE USUARIO LOGUEADO ---
        if user_rol == 'admin':
            st.markdown(
                """
                <div style="background-color: #1e293b; padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 15px; border: 1px solid #334155;">
                    <span style="color: #38bdf8; font-weight: bold; font-size: 14px;">👑 Administrador Principal</span><br>
                    <span style="color: #94a3b8; font-size: 11px;">Dueño del Software</span>
                </div>
                """, 
                unsafe_allow_html=True
            )
        elif 'admin_firma' in user_rol:
            st.markdown(
                f"""
                <div style="background-color: #1e293b; padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 15px; border: 1px solid #334155;">
                    <span style="color: #38bdf8; font-weight: bold; font-size: 13px;">🏢 Administrador de Firma</span><br>
                    <span style="color: #ffffff; font-size: 13px; font-weight: 600;">{nombre_usuario_actual}</span>
                </div>
                """, 
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div style="background-color: #1e293b; padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 15px; border: 1px solid #334155;">
                    <span style="color: #38bdf8; font-weight: bold; font-size: 13px;">👤 Usuario Propietario:</span><br>
                    <span style="color: #ffffff; font-size: 13px; font-weight: 600;">{nombre_usuario_actual}</span>
                </div>
                """, 
                unsafe_allow_html=True
            )

        st.markdown("---")
        
        # Botón de cerrar sesión
        if st.sidebar.button("🚪 Cerrar Sesión", key="btn_logout_unico_definitivo"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        # --- Navegación adaptada por rol ---
        if user_rol == 'admin':
            menu = st.radio(
                "Navegación", 
                ["📊 Auditoría Contable", "⚙️ Gestión de Usuarios","🔒 Bloqueo de Usuarios","🏢 Gestión de Empresas", "🏢 Gestión de Firmas y Accesos", "🏢 Gestión de Clientes de la Firma"], 
                key="menu_nav"
            )
        elif 'admin_firma' in user_rol:
            menu = st.radio(
                "Navegación", 
                ["📊 Auditoría Contable", "🏢 Gestión de Firmas y Accesos", "🏢 Gestión de Clientes de la Firma"], 
                key="menu_nav"
            )
        else:
            menu = "📊 Auditoría Contable"

        st.divider()

        # --- Selección de Empresa ---
        if menu == "📊 Auditoría Contable":
            conn_sidebar = conectar_db()
            df_sidebar = pd.DataFrame()

            user_limpio = str(nombre_usuario_actual).strip().lower()

            if conn_sidebar is not None:
                try:
                    if hasattr(conn_sidebar, 'ping') and callable(conn_sidebar.ping):
                        conn_sidebar.ping(reconnect=True)
                    
                    cursor_tmp = conn_sidebar.cursor()
                    try:
                        cursor_tmp.execute("USE control_central;")
                    except Exception:
                        pass 
                    cursor_tmp.close()

                    if user_rol == 'admin':
                        queries_a_probar = [
                            "SELECT * FROM control_central.clientes",
                            "SELECT * FROM clientes"
                        ]
                    elif 'admin_firma' in user_rol:
                        id_firma_actual = st.session_state.get('cliente_id', 0)
                        
                        queries_a_probar = [
                            # Se duplica el %% para que Python lo lea literal y no como error de formato
                            f"SELECT * FROM control_central.clientes WHERE id = {id_firma_actual} OR db_nombre LIKE 'lacteo_%%' OR db_nombre LIKE 'mendoza_%%'"
                        ]
                    else:
                        queries_a_probar = [
                            f"""
                            SELECT c.* FROM control_central.clientes c
                            JOIN control_central.usuarios u ON c.id = u.cliente_id
                            WHERE LOWER(TRIM(u.usuario)) = '{user_limpio}'
                            """,
                            """
                            SELECT * FROM control_central.clientes WHERE id = 3
                            """
                        ]
                    
                    for q in queries_a_probar:
                        try:
                            df_temp = ejecutar_consulta(q, conn_sidebar)
                            if not df_temp.empty:
                                df_sidebar = df_temp
                                break
                        except Exception:
                            continue
                except Exception as e:
                    pass
                finally:
                    try:
                        if conn_sidebar and hasattr(conn_sidebar, 'close'):
                            conn_sidebar.close()
                    except:
                        pass

            # --- RESPALDO OBLIGATORIO PARA ALIX ---
            if df_sidebar.empty and user_limpio == 'alix_maria':
                df_sidebar = pd.DataFrame([{
                    'id': 3,
                    'nombre_empresa': 'Distribuidora Rishon Leztion, C.A.',
                    'rif': 'J-XXXXXXXX-X',
                    'db_nombre': 'rishon_letzion_ca'
                }])

            if not df_sidebar.empty:
                df_sidebar = df_sidebar.fillna("")

            df_filtrado = df_sidebar

            if user_rol != 'admin' and 'admin_firma' not in user_rol and df_filtrado.empty:
                st.error(f"❌ El usuario '{nombre_usuario_actual}' no tiene una empresa asignada en la base de datos.")
                st.stop()

            nombres_empresas = df_filtrado['nombre_empresa'].tolist() if not df_filtrado.empty else []

            if nombres_empresas:
                idx_default = 0
                if 'CLIENTE_NOMBRE' in st.session_state and st.session_state['CLIENTE_NOMBRE'] in nombres_empresas:
                    idx_default = nombres_empresas.index(st.session_state['CLIENTE_NOMBRE'])

                st.markdown(f"**🏢 Selección de Empresa:**")
                nombre_seleccionado = st.selectbox(
                    "📂 SELECCIONE EMPRESA", 
                    nombres_empresas, 
                    index=idx_default,
                    key="selector_empresa_interactivo"
                )

                st.session_state['cliente_seleccionado_previo'] = nombre_seleccionado

                fila_seleccionada = df_filtrado[df_filtrado['nombre_empresa'] == nombre_seleccionado]
                if fila_seleccionada.empty:
                    fila_seleccionada = df_filtrado.iloc[[0]]


                datos_sel = fila_seleccionada.iloc[0]
                db_seleccionada = str(datos_sel['db_nombre']).strip()
                
                # Guardamos todas las credenciales clave en la sesión de forma unificada
                st.session_state['DB_ACTUAL'] = db_seleccionada
                st.session_state['db_a_conectar'] = db_seleccionada
                st.session_state['CLIENTE_NOMBRE'] = nombre_seleccionado
                
                # --- ¡AQUÍ ESTABA FALTANDO GUARDAR EL RIF! ---
                if 'rif' in datos_sel and pd.notna(datos_sel['rif']):
                    rif_encontrado = str(datos_sel['rif']).strip()
                    st.session_state['rif_empresa_activa'] = rif_encontrado
                    st.session_state['rif_empresa_seleccionada'] = rif_encontrado
                else:
                    st.session_state['rif_empresa_activa'] = "J-00000000-0"
                    st.session_state['rif_empresa_seleccionada'] = "J-00000000-0`"

                if 'id' in datos_sel:
                    st.session_state['cliente_id_seleccionado'] = int(datos_sel['id'])

                if 'tipo_contribuyente' in datos_sel and pd.notna(datos_sel['tipo_contribuyente']):
                    st.session_state['tipo_contribuyente'] = str(datos_sel['tipo_contribuyente']).strip()
                else:
                    st.session_state['tipo_contribuyente'] = 'Contribuyente Ordinario'

            else:
                st.info("ℹ️ No hay empresas disponibles para mostrar.")

    return menu


# 0. Primero validamos si la sesión expiró por tiempo
verificar_inactividad()

if 'logueado' not in st.session_state or not st.session_state['logueado']:
    login_screen()
    st.stop()

elif not st.session_state.get('bienvenida_completada', False):
    mostrar_plantilla_bienvenida()
    st.stop()

else:
    menu_lateral = gestionar_sidebar()

# --- LÓGICA DE NAVEGACIÓN Y PERMISOS ---
rol_actual = str(st.session_state.get('rol', '')).strip().lower()

es_modulo_admin = menu_lateral in [
    "⚙️ Gestión de Usuarios", 
    "🔒 Bloqueo de Usuarios",
    "🏢 Gestión de Firmas y Accesos", 
    "🏢 Gestión de Empresas", 
    "🏢 Gestión de Clientes de la Firma"
]

if es_modulo_admin:
    # Doble seguridad: si intentan entrar por manipulación, validamos el rol
    if rol_actual != 'admin' and 'admin_firma' not in rol_actual:
        st.warning("⚠️ No tienes permisos para acceder a este módulo administrativo.")
        st.stop()

    try:
        conn = conectar_db() # Conexión a la central
        if conn:
            if menu_lateral == "⚙️ Gestión de Usuarios":
                panel_administracion(conn)
            elif menu_lateral == "🔒 Bloqueo de Usuarios":
                panel_bloqueo_suspension_usuarios(conn)
            elif menu_lateral == "🏢 Gestión de Firmas y Accesos":
                panel_administracion_firmas(conn)
            elif menu_lateral == "🏢 Gestión de Empresas":
                panel_gestion_clientes(conn)
            elif menu_lateral == "🏢 Gestión de Clientes de la Firma":
                panel_gestion_clientes_firma(conn)
            conn.close()
        else:
            st.error("🔌 No se pudo establecer conexión con el servidor MySQL.")
    except Exception as e:
        st.error(f"Error al acceder a la gestión central: {e}")
    
    st.stop()

# --- SI NO ES ADMIN, CONTINUAMOS CON EL DASHBOARD CONTABLE ---
# Sacamos los datos de la sesión
EMPRESA = st.session_state.get('CLIENTE_NOMBRE', "Empresa Seleccionada")
RIF = st.session_state.get('rif_empresa_seleccionada', "J-00000000-0")
DATOS_EMPRESA = {"nombre": EMPRESA, "rif": RIF}

if menu_lateral == "📊 Auditoría Contable":
    # Tu lógica de módulos existente...
    with st.sidebar:
        st.divider()
        st.subheader("Módulos")
        
        nombre_sel = st.session_state.get('CLIENTE_NOMBRE', '')
        modulos_disponibles = [
            "🏠 Inicio", "📂 Plan de Cuentas", "📝 Asientos Contables", 
            "📖 Mayor Analítico", "📊 Estados Financieros", "📚 Libros Fiscales", "👤 Proveedores"
        ]

        if "PEDACITO" in str(nombre_sel).upper() and "CIELO" in str(nombre_sel).upper():
            modulos_disponibles.append("🧁 Inventarios")

        opcion_menu = st.selectbox("📂 SELECCIONE UN MÓDULO", modulos_disponibles)
        st.session_state['opcion_menu_auditoria'] = opcion_menu

        if opcion_menu == "📝 Asientos Contables":
            sub_opcion = st.radio("Acciones:", ["Subir Datos", "Conciliación Bancaria", "Consultar Comprobante", "Consultar Saldos Iniciales", "Consultar Cierre Contable","Gestor Documental",], key="sub_asientos")
        elif opcion_menu == "📊 Estados Financieros":
            st.markdown("---")
            sub_opcion = st.radio("Reportes Financieros:", ["Balance de Comprobación", "Balance General", "Estado de Resultados"], key="sub_estados")
        elif opcion_menu == "📚 Libros Fiscales":
            sub_opcion = st.radio("Reportes Fiscales:", ["Libro de Ventas", "Libro de Compras", "Comprobante de Retención ISLR", "Comprobante de Retención IVA"], key="sub_libros")
        else:
            sub_opcion = None

        st.divider()
        st.subheader("📅 Período de Consulta")
        dic_meses = {
            "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
            "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
            "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
        }
        meses_lista = list(dic_meses.keys())

        st.number_input("Año", step=1, min_value=2026, max_value=2030, key="año_seleccionado")
        st.selectbox("Mes", meses_lista, key="mes_seleccionado")




# Verifica si el df_acc o el df_gastos tienen filas antes de graficar
if 'df_gastos_c6' in locals() and df_gastos_c6.empty:
    st.sidebar.warning("⚠️ El DataFrame de Gastos C6 está vacío.")

if "🏠 Inicio" in opcion_menu:
    # --- INYECCIÓN DE CSS ---
    st.markdown("""<style>
            .block-container { max-width: 100% !important; padding-left: 3rem !important; padding-right: 3rem !important; }
            div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] > div { flex: 1 !important; min-width: 0 !important; }
            div[data-testid="element-container"] { width: 100% !important; }
        </style>""", unsafe_allow_html=True)

    user_rol = str(st.session_state.get('rol', 'admin')).strip().lower()
    nombre_usuario_actual = (st.session_state.get('nombre_usuario') or st.session_state.get('username') or st.session_state.get('usuario') or '').strip().lower()

    conn_ctrl = conectar_db()
    db_objetivo = None
    
    if conn_ctrl:
        try:
            if user_rol == 'admin':
                db_objetivo = st.session_state.get('DB_ACTUAL')
                if not db_objetivo or db_objetivo == 'No seleccionada':
                    df_temp = ejecutar_consulta("SELECT db_nombre FROM clientes LIMIT 1", conn_ctrl)
                    if not df_temp.empty: db_objetivo = str(df_temp['db_nombre'].iloc[0])
            else:
                # --- BÚSQUEDA DIRECTA Y SEGURA ---
                query = f"SELECT db_nombre FROM usuarios WHERE LOWER(TRIM(usuario)) = '{nombre_usuario_actual}'"
                df_temp = ejecutar_consulta(query, conn_ctrl)
                
                if not df_temp.empty and df_temp['db_nombre'].iloc[0]:
                    db_objetivo = str(df_temp['db_nombre'].iloc[0]).strip()
                elif nombre_usuario_actual in ['alix_maria', 'alix']:
                    # --- RESPALDO DE EMERGENCIA PARA ALIX ---
                    db_objetivo = 'rishon_letzion_ca'
                else:
                    st.error(f"❌ Acceso denegado: El usuario '{nombre_usuario_actual}' no tiene una empresa (DB) asociada.")
                    st.stop()
        except Exception as e:
            # Si ocurre un error de conexión, aplicamos respaldo si es Alix
            if nombre_usuario_actual in ['alix_maria', 'alix']:
                db_objetivo = 'rishon_letzion_ca'
            else:
                st.error(f"❌ Error al resolver la base de datos: {e}")
                st.stop()
        finally:
            if conn_ctrl and hasattr(conn_ctrl, 'close'):
                conn_ctrl.close()

    # Aseguramos que la sesión mantenga la DB activa
    if db_objetivo:
        st.session_state['DB_ACTUAL'] = db_objetivo
        st.session_state['db_a_conectar'] = db_objetivo

    if not db_objetivo:
        st.error("❌ No se pudo determinar la base de datos de trabajo.")
        st.stop()

    # --- LÓGICA DE CONEXIÓN ROBUSTA (Única y definitiva) ---
    necesita_reconexion = False

    if 'conn' not in st.session_state or st.session_state.get('ultima_db_conectada') != db_objetivo or st.session_state.conn is None:
        necesita_reconexion = True
    else:
        try:
            # Verificación limpia compatible con pymysql
            st.session_state.conn.ping(reconnect=True)
            if db_objetivo and db_objetivo != "control_central":
                with st.session_state.conn.cursor() as cursor:
                    cursor.execute(f"USE `{db_objetivo}`")
        except Exception:
            necesita_reconexion = True

    # Si se requiere nueva conexión o reconectar
    if necesita_reconexion:
        try:
            nueva_conn = conectar_db(db_objetivo)
            if nueva_conn:
                st.session_state.conn = nueva_conn
                st.session_state.ultima_db_conectada = db_objetivo
            else:
                st.error(f"❌ No se pudo conectar a la base de datos: {db_objetivo}")
                st.stop()
        except Exception as e:
            st.error(f"Error crítico conectando: {e}")
            st.session_state.conn = None
            st.stop()
    
    # Asignamos la conexión lista para usar en el resto de tu módulo de inicio
    conn = st.session_state.conn

    # 1. DEFINICIÓN DE ESTRUCTURA DE TIEMPO

    dic_meses = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
        "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
        "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
    }
    meses_lista = list(dic_meses.keys())

    anio_f = int(st.session_state.get('año_seleccionado', datetime.now().year))
    mes_nombre_f = st.session_state.get('mes_seleccionado', meses_lista[datetime.now().month - 1])

    m_idx = dic_meses.get(mes_nombre_f, 1)
    ultimo_dia = calendar.monthrange(anio_f, m_idx)[1]

    # Corrección limpia: usamos 'date' directamente tal como está importado arriba en tu archivo
    f_inicio_global = date(anio_f, 1, 1) 
    f_fin_global = date(anio_f, m_idx, ultimo_dia)

    st.session_state["f_inicio_global"] = f_inicio_global
    st.session_state["f_fin_global"] = f_fin_global

    fecha_inicio_str = f_inicio_global.strftime('%Y-%m-%d')
    fecha_fin_str = f_fin_global.strftime('%Y-%m-%d')

    # 5. UI (Solo mostrar si db_objetivo está definido)
    if 'db_objetivo' in locals() or 'db_objetivo' in globals():
        st.title(f"📊 Auditoría Profesional: {db_objetivo}")
        st.markdown(f"**Período de Análisis (Acumulado):** {f_inicio_global.strftime('%d/%m/%Y')} al {f_fin_global.strftime('%d/%m/%Y')}")
        st.divider()
    else:
        # Fallback si db_objetivo no está definido aún
        st.title("📊 Auditoría Profesional")
        st.markdown(f"**Período de Análisis (Acumulado):** {f_inicio_global.strftime('%d/%m/%Y')} al {f_fin_global.strftime('%d/%m/%Y')}")
        st.divider()

        
    # --- FILA 1: INDICADORES FINANCIEROS ---
    col_titulo, col_vacia, col_btn = st.columns([0.5, 0.3, 0.2])
    with col_titulo:
        st.subheader("Indicadores Financieros en Tiempo Real")

    with col_btn:
        if st.button("🔄 Actualizar Datos", width='stretch'):
            st.cache_data.clear()
            st.rerun()

    # Validación de conexión compatible con PyMySQL
    conexion_valida = False
    if conn:
        try:
            conn.ping(reconnect=True)
            conexion_valida = True
        except Exception:
            conexion_valida = False

    with st.spinner(f'Comunicando con MySQL para {db_objetivo}...'):
        if conn and conexion_valida:
            kpis = obtener_saldos_acumulados(conn, f_fin_global, db_objetivo)
        else:
            kpis = None

        if kpis is None:
            kpis = {"activo": 0, "pasivo": 0, "patrimonio": 0}

        df_utilidad = obtener_historico_utilidad(db_objetivo, f_inicio=f_inicio_global, f_fin=f_fin_global)
        if df_utilidad is None:
            df_utilidad = pd.DataFrame()

    valor_activo = kpis.get('activo', 0)
    valor_pasivo = kpis.get('pasivo', 0)
    valor_patrimonio = kpis.get('patrimonio', 0)

    u_v = 0
    if df_utilidad is not None and not df_utilidad.empty:
        # Buscamos de forma flexible cualquier columna que represente la utilidad
        posibles_columnas = ['utilidad_acumulada', 'utilidad_neta', 'utilidad_mensual', 'utilidad']
        col_utilidad = next((c for c in posibles_columnas if c in df_utilidad.columns), None)
        
        # Si no encuentra ninguna de las conocidas, agarra la última columna numérica disponible
        if not col_utilidad:
            numericas = df_utilidad.select_dtypes(include='number').columns
            if len(numericas) > 0:
                col_utilidad = numericas[-1]

        if col_utilidad:
            if 'f_fin_global' in st.session_state and st.session_state['f_fin_global']:
                try:
                    fecha_fin_Sesion = pd.to_datetime(st.session_state['f_fin_global'])
                    mes_limite = fecha_fin_Sesion.month
                    anio_limite = fecha_fin_Sesion.year
                    
                    # Verificamos si existen las columnas de año y mes para filtrar con precisión
                    if 'anio' in df_utilidad.columns and 'mes' in df_utilidad.columns:
                        df_utilidad['anio'] = pd.to_numeric(df_utilidad['anio'], errors='coerce')
                        df_utilidad['mes'] = pd.to_numeric(df_utilidad['mes'], errors='coerce')
                        fila_mes = df_utilidad[(df_utilidad['anio'] == anio_limite) & (df_utilidad['mes'] == mes_limite)]
                        
                        if not fila_mes.empty:
                            u_v = fila_mes[col_utilidad].iloc[0]
                        else:
                            u_v = df_utilidad[col_utilidad].iloc[-1]
                    else:
                        u_v = df_utilidad[col_utilidad].iloc[-1]
                except Exception as e:
                    u_v = df_utilidad[col_utilidad].iloc[-1]
            else:
                u_v = df_utilidad[col_utilidad].iloc[-1]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.container(border=True).metric("💰 ACTIVO", f"Bs. {valor_activo:,.2f}")
    with col2:
        st.container(border=True).metric("📉 PASIVO", f"Bs. {valor_pasivo:,.2f}")
    with col3:
        st.container(border=True).metric("🏗️ PATRIMONIO", f"Bs. {valor_patrimonio:,.2f}")
    with col4:
        st.container(border=True).metric(
            "📊 UTILIDAD NETA ACUM.", 
            f"Bs. {u_v:,.2f}",
            delta_color="normal" if u_v >= 0 else "inverse"
        )
    
    # --- FILA 2: SALUD FISCAL (SENIAT) ---
    df_fiscal, kpis_fiscales = obtener_salud_fiscal(
        db=db_objetivo, 
        f_inicio=f_inicio_global, 
        f_fin=f_fin_global
    )

    def mini_kpi(col, titulo, valor, color="#555555"):
        with col.container(border=True):
            st.markdown(f"""
                <div style="text-align: center; padding: 4px; width: 100%;">
                    <div style="
                        font-size: 0.85rem; 
                        background-color: {color}20; 
                        color: {color}; 
                        font-weight: bold; 
                        padding: 6px 4px; 
                        border-radius: 6px; 
                        margin-bottom: 8px;
                        white-space: normal;
                        min-height: 48px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        line-height: 1.1;">
                        {titulo}
                    </div>
                    <div style="font-size: 0.90rem; font-weight: bold; color: #333333; padding-bottom: 2px; white-space: nowrap;">
                        Bs. {valor:,.2f}
                    </div>
                </div>
            """, unsafe_allow_html=True)

    # 3. Dibujar Ingresos
    st.subheader("Ingresos")
    i1, i2, i3 = st.columns(3)
    mini_kpi(i1, "Ingresos Exentos", kpis_fiscales.get('ingresos_exentos', 0), "#1f77b4")
    mini_kpi(i2, "Ingresos Gravados", kpis_fiscales.get('ingresos_gravados', 0), "#2ca02c")

    # 4. Compras y Gastos
    st.subheader("Compras y Gastos")
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    mini_kpi(c1, "Compras Exentas", kpis_fiscales.get('compras_exentas', 0), "#ff7f0e")
    mini_kpi(c2, "Compras IVA 16%", kpis_fiscales.get('compras_16', 0), "#ff7f0e")
    mini_kpi(c3, "DPP", kpis_fiscales.get('DPP1', 0), "#d62728")
    mini_kpi(c4, "Comis. Banc.", kpis_fiscales.get('comisiones_bancarias1', 0), "#8c564b")
    mini_kpi(c5, "Gastos Pers.", kpis_fiscales.get('gastos_personales1', 0), "#8c564b")
    mini_kpi(c6, "Otros Ing.", kpis_fiscales.get('otros_ingresos', 0), "#9467bd")
    mini_kpi(c7, "Otros Egr.", kpis_fiscales.get('otros_egresos', 0), "#7f7f7f")

    # 5. Obligaciones Fiscales
    st.subheader("Obligaciones Fiscales")
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    mini_kpi(f1, "Débito Fiscal", kpis_fiscales.get('iva_debito_fiscal', 0), "#d62728")
    mini_kpi(f2, "IVA por Pagar", kpis_fiscales.get('iva_por_pagar', 0), "#d62728")
    mini_kpi(f3, "Ret. IVA Prov.", kpis_fiscales.get('retencion_iva_compras', 0), "#bcbd22")
    mini_kpi(f4, "ISLR ANTIC", kpis_fiscales.get('pagos_anticipados_islr', 0), "#bcbd22")
    mini_kpi(f5, "Ret. ISLR", kpis_fiscales.get('retencion_islr_proveedores', 0), "#d62728")
    mini_kpi(f6, "ISLR por Pagar", kpis_fiscales.get('islr_pagar', 0), "#d62728")

    st.divider()
    # ---FILA3:  SALUD FINANCIERA ---
    st.subheader("🏥 Análisis de Salud Financiera")
    r1, r2, r3 = st.columns(3)

    # 1. Índice de Liquidez (Corregido con validación de seguridad)
    liquidez = kpis.get('liquidez', 0)
    estado_l = "✅ Saludable" if liquidez > 1.1 else "⚠️ Riesgo"
    r1.metric("Índice de Liquidez", f"{liquidez:.2f}", estado_l)

    # 2. Índice de Solvencia (Activo / Pasivo total, suele ser similar a liquidez pero a largo plazo)
    # Si no lo tienes en el dict, lo calculamos aquí mismo
    activo_v = kpis.get('activo', 0)
    pasivo_v = kpis.get('pasivo', 0)
    solvencia = activo_v / pasivo_v if pasivo_v != 0 else 0
    estado_s = "✅ Solvente" if solvencia > 1.5 else "🟡 Ajustado"
    r2.metric("Índice de Solvencia", f"{solvencia:.2f}", estado_s)

    # 3. Capital Propio (Patrimonio Neto real)
    capital_trabajo = kpis.get('capital_trabajo', 0)
    r3.metric("capital de trabajo", f"Bs. {capital_trabajo:,.2f}", "capital_trabajo")

   # 4. ROE Rentabilidad del Patrimonio
    utilidad_acumulada_historica = obtener_utilidad_acumulada_historica(db_objetivo, f_fin_global)
    mostrar_analisis_rendimiento(u_v=utilidad_acumulada_historica, patrimonio_total=0)


    # --- FILA 4: ANÁLISIS VISUAL ---
    st.divider()
    col_izq, col_der = st.columns(2)

    # 1. Recuperación segura de año y mes desde session_state o valores por defecto
    año_val = st.session_state.get('año_seleccionado_contabilidad') or st.session_state.get('anio') or 2026
    mes_val = st.session_state.get('mes_seleccionado_contabilidad') or st.session_state.get('mes_seleccionado') or st.session_state.get('mes') or 'Mayo'

    # 2. Diccionario de traducción de texto a número
    meses_map = {
        'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 
        'Mayo': 5, 'Junio': 6, 'Julio': 7, 'Agosto': 8, 
        'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
    }

    # 3. Conversión blindada del año
    try:
        año_int = int(str(año_val).strip())
    except (ValueError, TypeError):
        año_int = datetime.now().year if 'datetime' in globals() else 2026

    # 4. Conversión blindada del mes (soporta texto o número)
    if str(mes_val).isdigit():
        mes_int = int(mes_val)
    elif isinstance(mes_val, str):
        mes_int = meses_map.get(mes_val.strip().capitalize(), 5)
    else:
        mes_int = 5

    # Validar que el mes esté en el rango correcto (1-12)
    if not (1 <= mes_int <= 12):
        mes_int = 5

    # 5. Calcular el último día del mes de forma segura
    _, ultimo_dia = calendar.monthrange(año_int, mes_int)

    # 6. Generar strings y variables tipo date
    f_i = f"{año_int:04d}-{mes_int:02d}-01"
    f_f = f"{año_int:04d}-{mes_int:02d}-{ultimo_dia:02d}"

    f_inicio_global = date(año_int, mes_int, 1)
    f_fin_global = date(año_int, mes_int, ultimo_dia)

    # 7. DEBUG VISUAL
    st.sidebar.info(f"📅 Rango activo ({mes_val}): {f_i} al {f_f}")  

    db = st.session_state.get('DB_ACTUAL', 'control_central')

    # --- ESTILOS CSS GLOBALES PARA FORMAR LA ESTÉTICA DE LA IMAGEN ---
    st.markdown("""
        <style>
            /* Contenedores tipo tarjeta ejecutiva con bordes sutiles */
            .report-card {
                background-color: #FFFFFF;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                padding: 15px 20px;
                margin-bottom: 15px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
            /* Cabeceras estilo reporte oficial */
            .report-header {
                background-color: #336699;
                color: white;
                padding: 8px 12px;
                font-size: 14px;
                font-weight: bold;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-bottom: 10px;
            }
        </style>
    """, unsafe_allow_html=True)

    # --- TARJETA DE RESUMEN SUPERIOR (Estilo "Container-equivalent volume" de la imagen) ---
    st.markdown("""
        <div class="report-card" style="text-align: center; border-top: 4px solid #336699;">
            <span style="color: #666666; font-size: 12px; font-weight: bold; text-transform: uppercase;">Resumen Ejecutivo de Operaciones</span>
            <div style="color: #336699; font-size: 28px; font-weight: bold; margin-top: 5px;">Panel Financiero Oficial</div>
        </div>
    """, unsafe_allow_html=True)

    # --- DISTRIBUCIÓN DE COLUMNAS ---
    col_izq, col_der = st.columns(2)

    # --- COLUMNA IZQUIERDA ---
    with col_izq:
        st.markdown('<div class="report-header">📊 Comparativo Ingresos / Egresos / Utilidad</div>', unsafe_allow_html=True)
        with st.container():
            st.markdown('<div class="report-card">', unsafe_allow_html=True)
            if db:
                df_bar = obtener_datos_barras(db, f_i, f_f)
                df_util = obtener_historico_utilidad(db)
                
                utilidad_final = float(df_util['utilidad_mensual'].iloc[0]) if (df_util is not None and not df_util.empty) else 0.0
                
                ingresos = 0
                egresos = 0
                
                if df_bar is not None and not df_bar.empty:
                    ingresos = df_bar.loc[df_bar['Categoría'] == 'Ingresos', 'Monto'].sum()
                    egresos = df_bar.loc[df_bar['Categoría'] == 'Egresos', 'Monto'].sum()
                
                df_final = pd.DataFrame({
                    'Categoría': ['Ingresos', 'Egresos', 'Utilidad'], 
                    'Monto': [ingresos, egresos, utilidad_final]
                })
                
                # Gráfico de barras con azules corporativos y grises de la referencia
                fig = px.bar(
                    df_final, x='Categoría', y='Monto', color='Categoría', 
                    color_discrete_map={
                        'Ingresos': '#336699',   # Azul institucional principal
                        'Egresos': '#808080',    # Gris sobrio de reporte
                        'Utilidad': '#4682B4'    # Azul acero corporativo
                    }, 
                    text='Monto',
                    template="plotly_white"
                )
                
                fig.update_traces(texttemplate='%{text:,.2f}', textposition='outside')
                fig.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20),
                    showlegend=False,
                    xaxis_title="",
                    yaxis_title="",
                    font=dict(family="Arial, sans-serif", size=12, color="#333333")
                )
                st.plotly_chart(fig, width='stretch')
            st.markdown('</div>', unsafe_allow_html=True)

    # --- COLUMNA DERECHA ---
    with col_der:
        st.markdown('<div class="report-header">🍕 Distribución de Gastos (Supplies by Sector)</div>', unsafe_allow_html=True)
        with st.container():
            st.markdown('<div class="report-card">', unsafe_allow_html=True)
            if db:
                df_pie = obtener_datos_pie(db, fecha_inicio_str, fecha_fin_str)
                if df_pie is not None and not df_pie.empty:
                    
                    # Paleta estricta de tonos azules y grises corporativos de la imagen
                    colores_azules_institucionales = [
                        '#336699', '#4682B4', '#5C93C4', '#70A3D2', 
                        '#85B4E0', '#696969', '#808080', '#A9A9A9', '#2E4053'
                    ]
                    
                    fig_pie = px.pie(
                        df_pie, 
                        values='Saldo Final', 
                        names='nombre', 
                        hole=0.45,
                        template="plotly_white",
                        color_discrete_sequence=colores_azules_institucionales
                    )
                    
                    fig_pie.update_traces(
                        textposition='auto', 
                        textinfo='percent',
                        hoverinfo='label+value+percent',
                        marker=dict(line=dict(color='#FFFFFF', width=2))
                    )
                    
                    fig_pie.update_layout(
                        margin=dict(t=20, b=20, l=10, r=10),
                        legend=dict(
                            orientation="v",
                            yanchor="middle",
                            y=0.5,
                            xanchor="left",
                            x=1.02,
                            font=dict(size=11)
                        ),
                        font=dict(family="Arial, sans-serif", size=12, color="#333333")
                    )
                    
                    st.plotly_chart(fig_pie, width='stretch')
                else:
                    st.warning("No hay gastos.")
            st.markdown('</div>', unsafe_allow_html=True)

    # --- FILA 5: FLUJO DE EFECTIVO ---
    st.divider()
    st.subheader("💸 Movimiento de Caja (Efectivo Real)")

    # 1. VARIABLES GLOBALES Y CONEXIÓN
    f_i = fecha_inicio_str  
    f_f = fecha_fin_str
    db = st.session_state.get('DB_ACTUAL')

    st.caption(f"📍 Empresa activa: `{db}` | Periodo: {f_i} al {f_f}")

    if db and db != "{db}" and db != "None":
        conn = None
        try:
            conn = conectar_db(db)
            if not conn:
                st.error(f"❌ Error crítico: No se pudo establecer conexión con la base de datos `{db}`.")
            else:
                # Usamos DictCursor para asegurar lectura por nombre de columna de forma segura
                import pymysql
                cursor = conn.cursor(pymysql.cursors.DictCursor)
                
                # A. Saldo Inicial Fijo
                debe_s_ini, haber_s_ini = 0.0, 0.0
                try:
                    cursor.execute(f"SELECT COALESCE(SUM(debe), 0) as d, COALESCE(SUM(haber), 0) as h FROM `{db}`.saldos_iniciales WHERE plan_cuentas LIKE '1.1.1.02%%'")
                    res_s_ini = cursor.fetchone()
                    if res_s_ini:
                        debe_s_ini = float(res_s_ini.get('d', 0.0) or 0.0)
                        haber_s_ini = float(res_s_ini.get('h', 0.0) or 0.0)
                except Exception as e:
                    # Mostramos advertencia sutil si la tabla de saldos iniciales no existe
                    st.warning(f"Nota: No se pudo leer 'saldos_iniciales' (puede que no exista en esta BD): {e}")

                # B. Movimientos históricos anteriores a f_i
                debe_hist, haber_hist = 0.0, 0.0
                try:
                    query_hist = f"SELECT COALESCE(SUM(debe), 0) as d, COALESCE(SUM(haber), 0) as h FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '1.1.1.02%%' AND fecha < %s"
                    cursor.execute(query_hist, (f_i,))
                    res_hist = cursor.fetchone()
                    if res_hist:
                        debe_hist = float(res_hist.get('d', 0.0) or 0.0)
                        haber_hist = float(res_hist.get('h', 0.0) or 0.0)
                except Exception as e:
                    st.error(f"Error al calcular movimientos históricos: {e}")

                saldo_inicial_neto = (debe_s_ini + debe_hist) - (haber_s_ini + haber_hist)

                # C. Movimientos del Periodo (f_i a f_f)
                entradas_mes, salidas_mes = 0.0, 0.0
                try:
                    query_mes = f"""
                        SELECT COALESCE(SUM(debe), 0) as ent, COALESCE(SUM(haber), 0) as sal 
                        FROM `{db}`.asientos_contables
                        WHERE plan_cuentas LIKE '1.1.1.02%%' AND fecha BETWEEN %s AND %s
                    """
                    cursor.execute(query_mes, (f_i, f_f))
                    res_mes = cursor.fetchone()
                    if res_mes:
                        entradas_mes = float(res_mes.get('ent', 0.0) or 0.0)
                        salidas_mes = float(res_mes.get('sal', 0.0) or 0.0)
                except Exception as e:
                    st.error(f"Error al calcular movimientos del periodo ({f_i} al {f_f}): {e}")

                saldo_real = saldo_inicial_neto + entradas_mes - salidas_mes

                # D. INTENTO AUTOMÁTICO DE CUENTAS POR COBRAR
                cxc_db = 0.0
                try:
                    cursor.execute(f"SELECT COALESCE(SUM(debe - haber), 0) as cxc FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '1.1.2%%'")
                    res_cxc = cursor.fetchone()
                    if res_cxc:
                        cxc_db = float(res_cxc.get('cxc', 0.0) or 0.0)
                except Exception:
                    cxc_db = 0.0

                cursor.close()
                conn.close()

                # 2. MÉTRICAS PRINCIPALES DEL PERIODO
                c1, c2, c3 = st.columns(3)
                c1.metric("Entradas (Mes)", f"Bs. {entradas_mes:,.2f}")
                c2.metric("Salidas (Mes)", f"Bs. {salidas_mes:,.2f}")
                c3.metric("Saldo Real Total", f"Bs. {saldo_real:,.2f}")

                # RESUMEN AUTOMÁTICO IA - MÉTRICAS
                balance_neto_mes = entradas_mes - salidas_mes
                tendencia_mes = "positivo" if balance_neto_mes >= 0 else "negativo"
                st.info(f"🤖 **Resumen de Caja:** Durante este periodo, las entradas totalizaron Bs. {entradas_mes:,.2f} frente a salidas de Bs. {salidas_mes:,.2f}, arrojando un flujo neto {tendencia_mes} de Bs. {balance_neto_mes:,.2f} y cerrando con un saldo real disponible de Bs. {saldo_real:,.2f}.")

                # 3. CONTROLS DE SIMULACIÓN
                st.sidebar.header("⚙️ Simulación de Escenarios (Stress Testing)")
                
                cuentas_por_cobrar = st.sidebar.number_input(
                    "Cuentas por Cobrar (Detectadas / Manual):", 
                    value=max(cxc_db, 0.0), 
                    step=10000.0,
                    help="Si la empresa tiene saldo en cuentas por cobrar (ej. cuenta 1.1.2), aparecerá aquí automáticamente."
                )

                pct_retraso = st.sidebar.slider(
                    "% de Facturas que se retrasan a 60 días:", 
                    min_value=0, max_value=100, value=0, step=5
                )

                impacto_retraso = cuentas_por_cobrar * (pct_retraso / 100.0)

                # 4. PROYECCIÓN DE FLUJO DE CAJA
                st.markdown("---")
                st.subheader("📈 Proyección de Liquidez y Análisis de Estrés")
                st.caption("Estimación basada en el flujo neto diario con simulación a 30, 60 y 90 días.")

                import datetime as dt

                d1 = dt.datetime.strptime(str(f_i), "%Y-%m-%d") if isinstance(f_i, str) else f_i
                d2 = dt.datetime.strptime(str(f_f), "%Y-%m-%d") if isinstance(f_f, str) else f_f

                dias_rango = max((d2 - d1).days + 1, 1)

                flujo_neto_periodo = entradas_mes - salidas_mes
                promedio_diario_neto = flujo_neto_periodo / dias_rango

                proj_30_meta = saldo_real + (promedio_diario_neto * 30)
                proj_60_meta = saldo_real + (promedio_diario_neto * 60)
                proj_90_meta = saldo_real + (promedio_diario_neto * 90)

                proj_30_ajustada = proj_30_meta - impacto_retraso

                if proj_30_meta != 0:
                    desviacion_absoluta = proj_30_ajustada - proj_30_meta
                    desviacion_pct = (desviacion_absoluta / abs(proj_30_meta)) * 100
                else:
                    desviacion_absoluta, desviacion_pct = 0.0, 0.0

                m1, m2, m3 = st.columns(3)
                m1.metric("Proyección 30 Días", f"Bs. {proj_30_meta:,.2f}", delta=f"{promedio_diario_neto * 30:,.2f} Bs est.")
                m2.metric("Proyección 60 Días", f"Bs. {proj_60_meta:,.2f}", delta=f"{promedio_diario_neto * 60:,.2f} Bs est.")
                m3.metric("Proyección 90 Días", f"Bs. {proj_90_meta:,.2f}", delta=f"{promedio_diario_neto * 90:,.2f} Bs est.")

                p1, p2, p3 = st.columns(3)
                p1.metric("30 Días Ajustado", f"Bs. {proj_30_ajustada:,.2f}", delta=f"{desviacion_pct:.2f}%")
                p2.metric("Impacto por Retraso", f"Bs. {impacto_retraso:,.2f}")
                p3.metric("Desviación Absoluta", f"Bs. {desviacion_absoluta:,.2f}")

                # 5. SEMÁFORO DE RIESGO
                if proj_30_ajustada < 0 or desviacion_pct <= -15.0:
                    st.error(f"🚨 **ALERTA DE ILIQUIDEZ POTENCIAL ({desviacion_pct:.1f}%):** El escenario genera déficit crítico.")
                elif -15.0 < desviacion_pct < 0:
                    st.warning(f"⚠️ **Advertencia de Riesgo Leve ({desviacion_pct:.1f}%):** Desviación negativa.")
                else:
                    st.success("✅ **Salud de Caja Estable:** Liquidez en niveles seguros.")

                # 6. DETALLE DE MOVIMIENTOS
                st.markdown("---")
                st.write("### Detalle de Movimientos")
                try:
                    df_flujo = obtener_detalle_movimientos_banco(db, f_i, f_f) 
                except Exception:
                    df_flujo = None

                if df_flujo is not None and not df_flujo.empty:
                    st.dataframe(df_flujo, width='stretch', hide_index=True, column_config={
                        "fecha": st.column_config.DateColumn("Fecha"),
                        "descripcion": "Concepto",
                        "debe": st.column_config.NumberColumn("Entradas", format="Bs. %.2f"),
                        "haber": st.column_config.NumberColumn("Salidas", format="Bs. %.2f")
                    })
                else:
                    st.info(f"No hay movimientos en este rango del {f_i} al {f_f}.")

        except Exception as e:
            st.error(f"Error crítico en la consulta de flujo de caja para `{db}`: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    else:
        st.warning("⚠️ Selecciona una empresa para ver los movimientos de caja.")
    # --- FILA 6: PROVEEDORES ---
    st.divider()
    st.subheader("📦 Gestión Operativa")
    p1, p2 = st.columns(2)
    p1.info(f"**Top Proveedor:** {kpis.get('top_proveedor', 'N/A')} ({kpis.get('top_porcentaje', 0)}%)")
    n_a = kpis.get('alertas_retencion', 0)
    if n_a > 0: 
        p2.warning(f"⚠️ {n_a} facturas sin retención aplicada.")
    else: 
        p2.success("✅ Retenciones al día.")    

    # --- FILA 7. SECCIÓN: CUENTA CASHEA ---
    st.divider()
    st.subheader("💳 Detalle de Créditos: Cashea (2.1.3.01.001)")

    db_actual = st.session_state.get('DB_ACTUAL')

    if db_actual and db_actual != "{db}" and db_actual != "None":
        df_cashea = obtener_detalle_cashea(db_actual, f_inicio_global, f_fin_global)

        if df_cashea is not None and not df_cashea.empty:
            saldo_final = df_cashea['saldo'].iloc[-1]
            st.metric("Saldo Actual en Cashea", f"Bs. {saldo_final:,.2f}")
            
            # Tabla limpia, expandida a todo el ancho y con formato profesional
            st.dataframe(
                df_cashea, 
                width='stretch',  # Ocupa todo el ancho de la pantalla correctamente
                height=350,                # Altura controlada con scroll vertical si hay muchos registros
                column_config={
                    "fecha": st.column_config.DateColumn("Fecha"),
                    "descripcion": st.column_config.TextColumn("Descripción"),
                    "ref": st.column_config.TextColumn("Referencia"),
                    "debe": st.column_config.NumberColumn("Pago (Debe)", format="Bs. %.2f"),
                    "haber": st.column_config.NumberColumn("Crédito (Haber)", format="Bs. %.2f"),
                    "saldo": st.column_config.NumberColumn("Saldo Acumulado", format="Bs. %.2f")
                }
            )
        else:
            st.info(f"No hay movimientos registrados para Cashea en este periodo.")
    else:
        st.warning("⚠️ Selecciona una empresa para ver los créditos de Cashea.")


    # --- FILA 7: TIPO DE CAMBIO BANCO CENTRAL DE VENEZUELA ---
    st.divider()
    st.markdown("### 🏦 Indicadores Cambiarios")

    if db_actual and db_actual != "{db}" and db_actual != "None":
        try: 
            conn_bcv = conectar_db(db_actual)
            if not conn_bcv:
                st.warning(f"⚠️ No se pudo establecer conexión con la base de datos para {db_actual}.")
            else:
                # Blindaje por si la función no está definida o retorna None
                tasa_dolar = 0.0
                origen_datos = "No disponible"
                
                if 'obtener_tasa_bcv_hoy' in globals() and callable(obtener_tasa_bcv_hoy):
                    # ⚠️ CORRECCIÓN: Asegúrate de pasarle 'conn_bcv' aquí para que no de el error de argumentos
                    t_val, o_val = obtener_tasa_bcv_hoy(conn_bcv)
                    tasa_dolar = t_val if t_val is not None else 0.0
                    origen_datos = o_val if o_val is not None else "Manual / Desconocido"

                col_tasa, col_info = st.columns([1, 2])

                with col_tasa:
                    s = f"{tasa_dolar:,.8f}"
                    tasa_formateada = f"Bs. {s.replace(',', 'X').replace('.', ',').replace('X', '.')}"
                    st.metric(label="💵 Tasa Oficial BCV (USD/VES)", value=tasa_formateada)

                with col_info:
                    st.caption("ℹ️ **Actualización Automática:**")
                    st.info(f"El sistema sincroniza directamente con el Banco Central de Venezuela. \n\n**Fuente de lectura actual:** {origen_datos}")
                    
                    # 🔥 BOTÓN DE ACTUALIZACIÓN FORZADA
                    if st.button("🔄 Forzar Sincronización BCV"):
                        from datetime import date
                        try:
                            if conn_bcv:
                                # ⚠️ CORRECCIÓN: Comentamos esto para evitar bloqueos/congelamientos de Streamlit
                                # conn_bcv.handle_unread_result()
                                pass
                        
                            tasa_fresca, origen_fresco = 0.0, "Error"
                            if 'consultar_bcv_directo_sin_bd' in globals() and callable(consultar_bcv_directo_sin_bd):
                                # ⚠️ CORRECCIÓN: Asegúrate de pasarle 'conn_bcv' por si tu función lo requiere
                                tasa_fresca, origen_fresco = consultar_bcv_directo_sin_bd(conn_bcv)
                        
                            if origen_fresco and "Error" not in origen_fresco and tasa_fresca > 0:
                                hoy = date.today()
                                cursor = conn_bcv.cursor()
                                try:
                                    cursor.execute(f"""
                                        INSERT INTO `{db_actual}`.tasas_diarias (fecha, tasa_valor) 
                                        VALUES (%s, %s)
                                        ON DUPLICATE KEY UPDATE tasa_valor = %s
                                    """, (hoy, tasa_fresca, tasa_fresca))
                                    conn_bcv.commit()
                                    st.success("¡Tasa actualizada con éxito desde el BCV!")
                                    st.rerun()
                                except Exception as db_err:
                                    st.error(f"La tabla 'tasas_diarias' no existe en {db_actual} o hay un error SQL: {db_err}")
                                finally:
                                    cursor.close()
                            else:
                                st.error("No se pudo conectar a la web del BCV en este momento.")
                        except Exception as e:
                            st.error(f"Error al sincronizar: {e}")
                
                conn_bcv.close()
        except Exception as e:
            st.error(f"Error al cargar indicadores cambiarios: {e}")
    else:
        st.warning("⚠️ Selecciona una empresa para ver los indicadores cambiarios.")


    # --- FILA 8: SECCIÓN VISUAL: REPORTE CONTABLE MULTIMONEDA ---
    st.divider()
    st.markdown("## 📊 Reporte de Libro Diario Multimoneda")
    
    # 1. Filtros de búsqueda y acciones (Agregamos una 4ta columna para el botón)
    col_filtro1, col_filtro2, col_filtro3, col_boton = st.columns([1.5, 1.5, 2, 2])

    with col_filtro1:
        meses_lista = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        
        # Buscamos si ya hay un mes seleccionado globalmente, si no, usamos el actual
        mes_actual_global = st.session_state.get('mes_seleccionado', meses_lista[date.today().month - 1])
        
        # Si el valor global es un número (1-12), lo convertimos a texto para el selectbox
        if isinstance(mes_actual_global, int):
            mes_actual_str = meses_lista[mes_actual_global - 1]
        else:
            mes_actual_str = mes_actual_global if mes_actual_global in meses_lista else "Enero"
            
        idx_mes = meses_lista.index(mes_actual_str)

        # ✅ Usamos una KEY totalmente independiente para este selectbox sin romper el session_state
        mes_seleccionado_str = st.selectbox(
            "Seleccione el Mes:", 
            meses_lista, 
            index=idx_mes, 
            key="selectbox_mes_multimoneda"
        )
        
        # Convertimos el texto seleccionado a su valor numérico (1-12) para las consultas SQL
        dic_m_inv = {m: i+1 for i, m in enumerate(meses_lista)}
        mes_seleccionado = dic_m_inv.get(mes_seleccionado_str, 1)

    with col_filtro2:
        anio_actual_global = st.session_state.get('año_seleccionado', 2026)

        # 1. Aseguramos que la llave exista y que no sea menor a 2024 antes de crear el widget
        if "number_input_anio_multimoneda" not in st.session_state or st.session_state["number_input_anio_multimoneda"] < 2024:
            st.session_state["number_input_anio_multimoneda"] = max(2024, int(anio_actual_global))

        # 2. Creamos el input usando únicamente su key sincronizada
        ano_seleccionado = st.number_input(
            "Seleccione el Año:", 
            min_value=2024, 
            max_value=2030, 
            step=1, 
            key="number_input_anio_multimoneda"
        )
        

    with col_filtro3:
        # Metemos un espacio en blanco arriba para alinear verticalmente el toggle con los selectores
        st.markdown("<div style='padding-top: 25px;'></div>", unsafe_allow_html=True)
        moneda_vista = "Dólares (USD)" if st.toggle("🇺🇸 Ver reporte en USD", value=False, key="toggle_moneda_multimoneda") else "Bolívares (VES)"
    # --- BLOQUE LÓGICO DE DATOS (Debe ejecutarse antes para poder descargar) ---
    try:
        # 1. Abrimos una conexión
        conn_local = conectar_db(db_actual)
        
        # ELIMINAMOS la verificación .is_connected() porque causa el error
        if not conn_local:
            st.error("⚠️ No se pudo establecer una conexión activa con la base de datos.")
            st.stop()

        # 2. Ejecutamos la función
        resultado_bruto = generar_reporte_multimoneda(conn_local, mes_seleccionado, ano_seleccionado, db_actual)
        
        # 3. Cerramos la conexión de forma segura
        try:
            conn_local.close()
        except:
            pass
         
        # 🛡️ Blindaje crítico: Convertimos a DataFrame si viene como lista o None
        if isinstance(resultado_bruto, list):
            df_diario = pd.DataFrame(resultado_bruto)
        elif isinstance(resultado_bruto, pd.DataFrame):
            df_diario = resultado_bruto
        else:
            df_diario = pd.DataFrame()

        if df_diario.empty:
            st.warning(f"⚠️ No se encontraron registros en el Libro Diario para el período {mes_seleccionado}/{ano_seleccionado}.")
        else:
            df_mostrar = df_diario.copy()
            
            # Formateo interno de datos según la moneda seleccionada
            if moneda_vista == "Dólares (USD)":
                df_mostrar['Debe_Vis'] = df_mostrar['debe_usd'].map(lambda x: f"$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                df_mostrar['Haber_Vis'] = df_mostrar['haber_usd'].map(lambda x: f"$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
            else:
                df_mostrar['Debe_Vis'] = df_mostrar['debe'].map(lambda x: f"Bs. {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                df_mostrar['Haber_Vis'] = df_mostrar['haber'].map(lambda x: f"Bs. {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
            
            df_visual = df_mostrar[['fecha', 'cuenta_contable', 'descripcion', 'Debe_Vis', 'Haber_Vis', 'tasa_bcv']]
            df_visual.columns = ['Fecha', 'Cuenta Contable', 'Descripción', f'Debe ({moneda_vista})', f'Haber ({moneda_vista})', 'Tasa Ref. BCV']
            
            # 🔥 BOTÓN DE DESCARGA EN LA CUARTA COLUMNA
            with col_boton:
                st.markdown("<div style='padding-top: 25px;'></div>", unsafe_allow_html=True)
                
                import io
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_visual.to_excel(writer, index=False, sheet_name='Libro Diario Multimoneda')
                buffer.seek(0)
                
                nombre_mes = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][mes_seleccionado-1]
                nombre_archivo = f"Libro_Diario_{nombre_mes}_{ano_seleccionado}_{moneda_vista.split()[0]}.xlsx"
                
                st.download_button(
                    label="📥 Descargar Excel",
                    data=buffer,
                    file_name=nombre_archivo,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width='stretch'
                )

            # 2. Renderizar la tabla principal en la app abajo de los filtros
            st.dataframe(df_visual, width='stretch', hide_index=True)
            
            # 3. Totales de Control al pie de página (Acumulados)
            tot_debe = df_diario['debe_usd'].sum() if moneda_vista == "Dólares (USD)" else df_diario['debe'].sum()
            tot_haber = df_diario['haber_usd'].sum() if moneda_vista == "Dólares (USD)" else df_diario['haber'].sum()
            
            simbolo = "$" if moneda_vista == "Dólares (USD)" else "Bs."
            
            col_t1, col_t2 = st.columns(2)
            col_t1.metric("Total Debe Acumulado", f"{simbolo} {tot_debe:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
            col_t2.metric("Total Haber Acumulado", f"{simbolo} {tot_haber:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

            # =========================================================================
            # 🔥 ZONA DE REPORTES FINANCIEROS EN DIVISAS
            # =========================================================================
            st.markdown("<br>", unsafe_allow_html=True)                

            with st.expander("📊 Reportes Financieros Consolidados (Multimoneda)", expanded=False):
                st.markdown(f"### 📋 Balance de Comprobación — Período Seleccionado ({moneda_vista})")
                st.write("Consolidación analítica de saldos: Apertura, Movimientos mensuales y Saldos de Cierre.")
                
                if st.button("🧮 Generar Balance de Comprobación", width='stretch'):
                    
                    if df_diario is None or df_diario.empty:
                        st.warning("⚠️ El registro del diario está vacío o no se pudo cargar para este período.")
                    else:
                        try:
                            col_debe_calc = 'debe_usd' if moneda_vista == "Dólares (USD)" else 'debe'
                            col_haber_calc = 'haber_usd' if moneda_vista == "Dólares (USD)" else 'haber'
                            
                            df_diario['es_inicial'] = df_diario['descripcion'].str.contains("SALDOS INICIALES", case=False, na=False)
                            
                            balance_data = []
                            for (codigo, cuenta), group in df_diario.groupby(['plan_cuentas', 'cuenta_contable']):
                                grupo_inicial = group[group['es_inicial']]
                                grupo_mes = group[~group['es_inicial']]
                                
                                ini_debe = grupo_inicial[col_debe_calc].sum()
                                ini_haber = grupo_inicial[col_haber_calc].sum()
                                saldo_inicial = ini_debe - ini_haber
                                
                                mes_debe = grupo_mes[col_debe_calc].sum()
                                mes_haber = grupo_mes[col_haber_calc].sum()
                                
                                saldo_final = saldo_inicial + mes_debe - mes_haber
                                
                                balance_data.append({
                                    'Código Contable': str(codigo) if pd.notna(codigo) else "S/C",
                                    'Cuenta Contable': str(cuenta),
                                    'Saldo Inicial Num': saldo_inicial,
                                    'Debe Num': mes_debe,
                                    'Haber Num': mes_haber,
                                    'Saldo Final Num': saldo_final
                                })
                            
                            df_balance = pd.DataFrame(balance_data)
                            if not df_balance.empty:
                                df_balance = df_balance.sort_values(by='Código Contable').reset_index(drop=True)
                            
                            simb = "$" if moneda_vista == "Dólares (USD)" else "Bs."
                            
                            def f_monto(val):
                                if pd.isna(val) or val == 0:
                                    return f"{simb} 0,00"
                                if val < 0:
                                    return f"({simb} {abs(val):,.2f})".replace(',', 'X').replace('.', ',').replace('X', '.')
                                return f"{simb} {val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

                            df_balance_visual = pd.DataFrame({
                                'Código Contable': df_balance['Código Contable'],
                                'Cuenta Contable': df_balance['Cuenta Contable'],
                                'Saldo Inicial': df_balance['Saldo Inicial Num'].apply(f_monto),
                                'Debe': df_balance['Debe Num'].apply(f_monto),
                                'Haber': df_balance['Haber Num'].apply(f_monto),
                                'Saldo Final': df_balance['Saldo Final Num'].apply(f_monto)
                            })
                            
                            st.dataframe(df_balance_visual, width='stretch', hide_index=True)
                            
                            tot_inicial = df_balance['Saldo Inicial Num'].sum()
                            tot_debe = df_balance['Debe Num'].sum()
                            tot_haber = df_balance['Haber Num'].sum()
                            tot_final = df_balance['Saldo Final Num'].sum()
                            
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Total Saldo Inicial", f_monto(tot_inicial))
                            c2.metric("Total Debe (Mes)", f_monto(tot_debe))
                            c3.metric("Total Haber (Mes)", f_monto(tot_haber))
                            c4.metric("Total Saldo Final", f_monto(tot_final))
                            
                            if abs(tot_debe - tot_haber) < 0.01:
                                st.success("✨ ¡Partida Doble verificada! Los movimientos del mes cargaron perfectamente cuadrados.")
                            else:
                                st.error("⚠️ Alerta contable: Los movimientos cargados en el Debe y Haber del mes difieren.")
                        except Exception as inner_e:
                            st.error(f"Error interno al calcular el balance: {inner_e}")

    except Exception as e:
        st.error(f"❌ Ocurrió un error al procesar el Libro Diario o el Balance de Comprobación: {e}")

    # FILA 9 ..... NUEVO MÓDULO PREMIUM: AUDITORÍA FORENSE CON IA
    st.divider()
    st.markdown("## 📊 AUDITORÍA FORENSE CON IA")
    
    # --- VERIFICACIÓN DE CONEXIÓN VIVA ANTES DE USAR PANDAS ---
    try:
        if conn:
            conn.ping(reconnect=True)
        else:
            # Si no hay conexión o es None, puedes manejar la reconexión si tienes la función a la mano
            pass
    except Exception:
        pass

    query_completa = f"SELECT * FROM `{db_actual}`.asientos_contables"
    
    try:
        df_diario = ejecutar_consulta(query_completa, conn) 
        # 🛡️ BLINDAJE CRUCIAL: Forzamos la conversión de la fecha para evitar errores de tipo string (.year)
        if 'fecha' in df_diario.columns:
            df_diario['fecha'] = pd.to_datetime(df_diario['fecha'], errors='coerce')
    except Exception as db_err:
        st.error(f"Error de conexión con la base de datos: {db_err}")
        df_diario = pd.DataFrame()

    col_analisis = 'debe'
    simb = "Bs."
    st.divider()
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("🕵️‍♂️ Módulo de Auditoría Forense con IA (Antifraude)", expanded=False):
        st.markdown("### 🔍 Análisis de Patrones y Detección Automatizada de Anomalías")
        st.write("La IA analiza los asientos del mes buscando importes atípicos, desviaciones estadísticas y registros duplicados.")
        
        if st.button("🚀 Ejecutar Escáner Antifraude", width='stretch'):
            st.info("Procesando algoritmos estadísticos sobre el Libro Diario...")
            
            if df_diario.empty:
                st.warning("⚠️ El DataFrame del diario está vacío.")
            else:
                # 1. Preparación de datos
                df_diario['debe'] = pd.to_numeric(df_diario['debe'], errors='coerce').fillna(0)
                df_diario['haber'] = pd.to_numeric(df_diario['haber'], errors='coerce').fillna(0)
                
                # Cálculo de monto auditable
                if 'debe_usd' in df_diario.columns and 'haber_usd' in df_diario.columns and moneda_vista == "Dólares (USD)":
                    df_diario['debe_usd'] = pd.to_numeric(df_diario['debe_usd'], errors='coerce').fillna(0)
                    df_diario['haber_usd'] = pd.to_numeric(df_diario['haber_usd'], errors='coerce').fillna(0)
                    df_diario['monto_auditable'] = df_diario['debe_usd'] + df_diario['haber_usd']
                else:
                    df_diario['monto_auditable'] = df_diario['debe'] + df_diario['haber']
                
                # 2. Filtrado: Excluir saldos iniciales y montos cero
                # Nos aseguramos de manejar de forma segura si la descripción es nula o texto
                mask_saldo = df_diario['descripcion'].fillna('').astype(str).str.contains("SALDOS INICIALES", case=False, na=False)
                df_asientos = df_diario[
                    (~mask_saldo) & 
                    (df_diario['monto_auditable'] != 0)
                ].copy()
                
                if df_asientos.empty:
                    st.warning("⚠️ El escáner no encontró movimientos válidos tras aplicar los filtros.")
                else:
                    # -----------------------------------------------------------------
                    # ALGORITMO 1: DETECCIÓN DE DUPLICADOS
                    # -----------------------------------------------------------------
                    anomalies_found = False
                    alertas_duplicados = []
                    alertas_montos = []
                    
                    duplicados = df_asientos[df_asientos.duplicated(subset=['fecha', 'cuenta_contable', col_analisis], keep=False)]
                    if not duplicados.empty:
                        anomalies_found = True
                        for cuenta, gp in duplicados.groupby('cuenta_contable'):
                            monto_dup = gp[col_analisis].iloc[0]
                            alertas_duplicados.append(f"🚩 **Sospecha de Duplicidad:** Se encontraron {len(gp)} registros idénticos el mismo día en la cuenta **{cuenta}** por {simb} {monto_dup:,.2f}.")
                    
                    # -----------------------------------------------------------------
                    # ALGORITMO 2: Z-SCORE (DESVIACIÓN)
                    # -----------------------------------------------------------------
                    stats = df_asientos.groupby('cuenta_contable')[col_analisis].agg(['mean', 'std']).reset_index()
                    stats['std'] = stats['std'].fillna(0.0)
                    
                    df_audit = df_asientos.merge(stats, on='cuenta_contable', how='left')
                    df_audit['std_safe'] = df_audit['std'].replace(0.0, 1.0)
                    df_audit['z_score'] = (df_audit[col_analisis] - df_audit['mean']) / df_audit['std_safe']
                    
                    anomalas_std = df_audit[(df_audit['std'] > 0) & (df_audit['z_score'] > 2.0) & (df_audit[col_analisis] > df_audit['mean'] * 1.5)]
                    
                    if not anomalas_std.empty:
                        for idx, row in anomalas_std.iterrows():
                            porcentaje_desvio = ((row[col_analisis] - row['mean']) / row['mean']) * 100 if row['mean'] > 0 else 100
                            if porcentaje_desvio > 15:
                                anomalies_found = True
                                alertas_montos.append(f"🚨 **Monto Atípico:** Cuenta **{row['cuenta_contable']}**, registro *'{row['descripcion']}'* ({simb} {row[col_analisis]:,.2f}). ¡{porcentaje_desvio:.0f}% por encima del promedio!")

                    # -----------------------------------------------------------------
                    # RENDERIZADO
                    # -----------------------------------------------------------------
                    if anomalies_found:
                        st.error("❌ ¡Alerta del Sistema! Se detectaron inconsistencias.")
                        for a in alertas_montos: st.warning(a)
                        for a in alertas_duplicados: st.info(a)
                    else:
                        st.success("✨ ¡Análisis Completo! Data limpia y alineada.")


    # --- FILA 10: REPORTE DE CONTABLE ---
    st.divider()
    try:
        import datetime as dt
        import calendar

        # Usamos un respaldo numérico directo (2026) para el año
        año = int(st.session_state.get('año_seleccionado_contabilidad') or st.session_state.get('año_seleccionado') or 2026)
        mes_elegido_str = str(st.session_state.get('mes_seleccionado_contabilidad', 'Junio')).strip().capitalize()

        # Mapeo robusto de meses
        meses_map = {
            'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
            'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
        }
        
        num_mes = meses_map.get(mes_elegido_str, 6)

        # Construcción de fechas usando calendar para evitar errores en días máximos
        ultimo_dia = int(calendar.monthrange(año, num_mes)[1])
        
        # Creamos tanto los strings como los objetos date de forma limpia usando el alias dt
        f_i_str = f"{año}-{num_mes:02d}-01"
        f_f_str = f"{año}-{num_mes:02d}-{ultimo_dia:02d}"

        f_i_date = dt.date(año, num_mes, 1)
        f_f_date = dt.date(año, num_mes, ultimo_dia)

        # Cuadro informativo de depuración en tiempo real reflejando el período activo
        st.info(f"📅 Período Activo: **{mes_elegido_str} {año}** | Rango SQL: **{f_i_str} al {f_f_str}**")

        # Validar Base de Datos activa
        db = st.session_state.get('DB_ACTUAL')
        if db and db != "{db}" and db != "None" and str(db).strip() != "":
            try:
                # 🛠️ CORRECCIÓN: Pasamos los objetos date (f_i_date y f_f_date) en lugar de strings 
                # para evitar que falle si la función interna intenta usar .year o métodos de fecha.
                df_acc = obtener_analisis_accionista_detallado(db, f_i_date, f_f_date)
                utilidad = obtener_historico_utilidad(db, f_inicio=f_i_date, f_fin=f_f_date)
            except Exception as err:
                st.error(f"Error interno en la función de datos: {err}")
                st.stop()
        else:
            st.warning("⚠️ Selecciona una empresa.")
            st.stop()

        st.subheader(f"📊 Análisis Contable: {db}")
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "👥 Accionistas", 
            "📉 Gastos Operativos", 
            "📈 Resumen Utilidad", 
            "💳 Cuentas por Pagar Accionista", 
            "💰 Otros Ingresos"
        ])

        with tab1:
            st.markdown("### Clausula 4ta del Contrato")
            
            # 1. Procesamiento ultra-seguro de la utilidad devuelta
            utilidad_bruta = 0.0
            if utilidad is not None:
                if isinstance(utilidad, pd.DataFrame) and not utilidad.empty:
                    if 'utilidad_mensual' in utilidad.columns:
                        utilidad_bruta = float(utilidad['utilidad_mensual'].iloc[0])
                    else:
                        utilidad_bruta = float(utilidad.iloc[0, 0])
                elif isinstance(utilidad, (int, float)):
                    utilidad_bruta = float(utilidad)
                elif isinstance(utilidad, (list, tuple)) and len(utilidad) > 0:
                    try:
                        utilidad_bruta = float(utilidad[0])
                    except Exception:
                        utilidad_bruta = 0.0

            neto_disponible = utilidad_bruta * 0.66

            # 2. Obtenemos de forma segura el DataFrame detallado de asientos y accionistas del período
            df_config_accionistas = pd.DataFrame()

            # Abrimos una conexión local para este bloque
            conn_tab = conectar_db(db) 

            if conn_tab is None:
                st.error("❌ Error: No se pudo establecer conexión con la base de datos para los accionistas.")
            else:
                try:
                    cursor = conn_tab.cursor()
                    cursor.execute(f"USE `{db}`;")
                    
                    # Validación y creación de tabla
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS accionistas (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            nombre VARCHAR(255) NOT NULL,
                            porcentaje_accionario DECIMAL(5,2) NOT NULL,
                            codigo_cuenta_asociada VARCHAR(50) NOT NULL,
                            descripcion_cuenta VARCHAR(255)
                        );
                    """)
                    
                    # Lectura directa
                    df_config_accionistas = ejecutar_consulta(f"SELECT * FROM `{db}`.accionistas", conn_tab)
                    cursor.close()
                    
                except Exception as e:
                    st.error(f"⚠️ Error al procesar la configuración de accionistas: {e}")
                    df_config_accionistas = pd.DataFrame()
                    
                finally:
                    # CERRAMOS la conexión de forma directa sin usar .is_connected()
                    if conn_tab:
                        try:
                            conn_tab.close()
                        except:
                            pass


            nombres_grafico = []
            valores_grafico = []
            colores_grafico = []

            if df_config_accionistas is not None and not df_config_accionistas.empty:
                for _, row in df_config_accionistas.iterrows():
                    cuenta = str(row['codigo_cuenta_asociada']).strip()
                    nombre = str(row['nombre']).strip()
                    total_retiro = 0.0

                    if df_acc is not None and not df_acc.empty and 'plan_cuentas' in df_acc.columns:
                        df_acc['plan_cuentas'] = df_acc['plan_cuentas'].astype(str).str.strip()
                        filtro_acc = df_acc[df_acc['plan_cuentas'] == cuenta]
                        if not filtro_acc.empty:
                            total_retiro = float(filtro_acc['neto'].sum())

                    nombres_grafico.append(nombre)
                    valores_grafico.append(total_retiro)
                    colores_grafico.append('#1f77b4' if "Jean Marco" in nombre else '#33a02c')

            # Agregar métricas globales al final
            nombres_grafico.extend(['Utilidad Contable', 'Utilidad Neta'])
            valores_grafico.extend([utilidad_bruta, neto_disponible])
            colores_grafico.extend(['#ff7f0e', '#7f7f7f'])

            if len(valores_grafico) > 0:
                valores_grafico_limpios = [float(v) if pd.notnull(v) else 0.0 for v in valores_grafico]
                
                fig = go.Figure(go.Bar(
                    x=valores_grafico_limpios,
                    y=nombres_grafico,
                    orientation='h',
                    marker_color=colores_grafico,
                    texttemplate='%{x:,.2f}',
                    textposition='outside'
                ))

                # Configuración del Layout
                mes_titulo = st.session_state.get('mes_seleccionado_contabilidad', 'Junio')
                anio_titulo = st.session_state.get('año_seleccionado_contabilidad', 2026)

                fig.update_layout(
                    title=f"Comparativa: Retiros vs Utilidades ({mes_titulo} {anio_titulo})",
                    height=450,
                    xaxis=dict(title="Valor (Bs.)", zeroline=True, showgrid=True),
                    yaxis=dict(type='category', autorange="reversed"),
                    margin=dict(l=20, r=100, t=50, b=20)
                )
                
                st.plotly_chart(fig, width='stretch')
            else:
                st.warning("No hay datos disponibles para mostrar en el gráfico.")

        with tab2:
            st.markdown("### 📉 Detalle de Gastos Operativos")

            # --- 1. SECCIÓN CLASE 5 (Costos) ---
            st.subheader("Costos (Clase 5)")
            try:
                # Usamos f_i_str y f_f_str garantizando que existan y estén formateados correctamente
                df_gastos_c5 = obtener_analisis_gastos_clase5(db, f_i_str, f_f_str)
            except Exception as err:
                st.error(f"Error al obtener costos de Clase 5: {err}")
                df_gastos_c5 = pd.DataFrame()

            if df_gastos_c5 is not None and not df_gastos_c5.empty:
                df_gastos_c5.columns = [str(c).strip().lower() for c in df_gastos_c5.columns]
                
                col_cuenta = 'plan_cuentas' if 'plan_cuentas' in df_gastos_c5.columns else df_gastos_c5.columns[0]
                col_desc = 'descripcion' if 'descripcion' in df_gastos_c5.columns else df_gastos_c5.columns[1]
                col_total = 'total_gasto' if 'total_gasto' in df_gastos_c5.columns else df_gastos_c5.columns[2]

                # --- EXCLUIR CUENTAS QUE EMPIECEN POR '7' ---
                df_gastos_c5[col_cuenta] = df_gastos_c5[col_cuenta].astype(str).str.strip()
                df_gastos_c5 = df_gastos_c5[~df_gastos_c5[col_cuenta].str.startswith('7')]

            if df_gastos_c5 is not None and not df_gastos_c5.empty:
                st.markdown(f"**Resumen de Costos del Período ({mes_elegido_str} {año}):**")
                lineas_c5 = []
                for _, row in df_gastos_c5.iterrows():
                    cta = str(row[col_cuenta]).strip()
                    desc = str(row[col_desc]).strip()
                    monto = float(row[col_total]) if pd.notnull(row[col_total]) else 0.0
                    lineas_c5.append(f"- **{cta} - {desc}**: Bs. {monto:,.2f}")
                
                st.markdown("\n".join(lineas_c5))

                # Gráfico Clase 5
                df_gastos_c5['etiqueta'] = df_gastos_c5[col_cuenta].astype(str) + ' - ' + df_gastos_c5[col_desc].astype(str)
                import plotly.express as px
                fig5 = px.bar(
                    df_gastos_c5.sort_values(col_total, ascending=True), 
                    x=col_total, y='etiqueta', orientation='h',
                    title=f"Totalización: Cuentas Clase 5 ({mes_elegido_str} {año})",
                    color_discrete_sequence=['#d62728'], text=col_total
                )
                fig5.update_traces(texttemplate='%{text:,.2f}', textposition='outside')
                fig5.update_layout(height=300, margin=dict(l=20, r=40, t=40, b=20), xaxis=dict(title="Monto (Bs.)"), yaxis=dict(title=""))
                st.plotly_chart(fig5, width='stretch')
            else:
                st.info(f"No hay movimientos en cuentas de Clase 5 para el período del {f_i_str} al {f_f_str}.")

            st.divider()

            # --- 2. SECCIÓN CLASE 6 (Gastos Operativos) ---
            st.subheader("Gastos Operativos (Clase 6)")
            
            try:
                df_gastos_c6 = obtener_analisis_gastos_clase6(db, f_i_str, f_f_str)
            except Exception as err:
                st.error(f"Error al obtener gastos de Clase 6: {err}")
                df_gastos_c6 = pd.DataFrame()

            if df_gastos_c6 is not None and not df_gastos_c6.empty:
                df_gastos_c6.columns = [str(c).strip().lower() for c in df_gastos_c6.columns]
                
                c6_cuenta = 'plan_cuentas' if 'plan_cuentas' in df_gastos_c6.columns else df_gastos_c6.columns[0]
                c6_nombre = 'cuenta_contable' if 'cuenta_contable' in df_gastos_c6.columns else ('descripcion' if 'descripcion' in df_gastos_c6.columns else df_gastos_c6.columns[1])
                c6_total = 'total_gasto' if 'total_gasto' in df_gastos_c6.columns else df_gastos_c6.columns[2]

                st.markdown(f"**Totalizado por Cuenta - Gastos Operativos ({mes_elegido_str} {año}):**")
                lineas_c6 = []
                for _, row in df_gastos_c6.iterrows():
                    num_cta = str(row[c6_cuenta]).strip()
                    nom_cta = str(row[c6_nombre]).strip()
                    monto = float(row[c6_total]) if pd.notnull(row[c6_total]) else 0.0
                    lineas_c6.append(f"- **{num_cta} - {nom_cta}**: Bs. {monto:,.2f}")
                
                st.markdown("\n".join(lineas_c6))

                # Gráfico Clase 6
                df_gastos_c6['etiqueta'] = df_gastos_c6[c6_cuenta].astype(str) + ' - ' + df_gastos_c6[c6_nombre].astype(str)
                fig6 = px.bar(
                    df_gastos_c6.sort_values(c6_total, ascending=True), 
                    x=c6_total, y='etiqueta', orientation='h',
                    title=f"Total Gastos Operativos por Cuenta ({mes_elegido_str} {año})",
                    color_discrete_sequence=['#1f77b4'], text=c6_total
                )
                fig6.update_traces(texttemplate='%{text:,.2f}', textposition='outside')
                fig6.update_layout(height=350, margin=dict(l=20, r=40, t=40, b=20), xaxis=dict(title="Monto (Bs.)"), yaxis=dict(title=""))
                st.plotly_chart(fig6, width='stretch')
            else:
                st.info(f"No hay movimientos en cuentas de Clase 6 para el período del {f_i_str} al {f_f_str}.")


        with tab3:
            st.markdown("### 📊 Evolución de Saldo Neto Acumulado")
            
            df_utilidad = None
            
            # 1. Verificamos que la función realmente exista en memoria antes de llamarla
            if 'obtener_historico_utilidad_acumulada' not in globals() and 'obtener_historico_utilidad_acumulada' not in locals():
                st.error("❌ Error crítico: La función 'obtener_historico_utilidad_acumulada' no está definida o no se importó correctamente.")
            else:
                try:
                    df_utilidad = obtener_historico_utilidad_acumulada(db)
                except Exception as e:
                    st.error(f"Error al conectar con la base de datos para obtener el histórico: {e}")
                    df_utilidad = None

            # 2. Validación robusta del DataFrame resultante
            if isinstance(df_utilidad, pd.DataFrame) and not df_utilidad.empty:
                meses_nombres = {1:'Ene', 2:'Feb', 3:'Mar', 4:'Abr', 5:'May', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dic'}
                df_utilidad['nombre_mes'] = df_utilidad['mes'].map(meses_nombres)
                
                utilidad_acumulada_total = df_utilidad['utilidad_mensual'].sum()
                
                col_total, col_detalle = st.columns([1, 2])
                
                with col_total:
                    st.metric("Saldo Neto Acumulado al Periodo", f"Bs. {utilidad_acumulada_total:,.2f}")
                    
                with col_detalle:
                    st.markdown("**Utilidad por Mes del Periodo:**")
                    etiquetas_meses = [f"**{row['nombre_mes']}:** Bs. {row['utilidad_mensual']:,.2f}" for _, row in df_utilidad.iterrows()]
                    st.markdown(" | ".join(etiquetas_meses))
                
                # Gráfico de barras
                df_utilidad['color'] = df_utilidad['utilidad_mensual'].apply(lambda x: 'Ganancia' if x >= 0 else 'Pérdida')
                
                import plotly.express as px
                fig = px.bar(
                    df_utilidad, 
                    x='nombre_mes', 
                    y='utilidad_mensual', 
                    color='color',
                    color_discrete_map={'Ganancia': '#2ecc71', 'Pérdida': '#e74c3c'},
                    title="Desglose Mensual",
                    text_auto='.2s'
                )
                
                fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', showlegend=False)
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("No hay datos disponibles o error al recuperar el histórico para el periodo seleccionado.")

        with tab4:
            # --- SECCIÓN: ASIENTO CONTABLE COMPLETO POR COMPROBANTE ---
            st.divider()
            st.subheader("👥 Detalle de Comprobantes - Cuentas por Pagar Accionistas")

            db_name = locals().get('db') or st.session_state.get('DB_ACTUAL')

            if db_name and db_name != "{db}" and db_name != "None":
                
                # 1. OBTENER FECHAS DEL SIDEBAR USANDO LAS LLAVES CORRECTAS ('año_seleccionado' y 'mes_seleccionado')
                import datetime
                import calendar

                anio_sel = int(st.session_state.get('año_seleccionado', datetime.datetime.now().year))
                mes_nombre_sel = st.session_state.get('mes_seleccionado', "Enero")
                
                dic_meses = {
                    "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6, 
                    "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
                }
                mes_n = dic_meses.get(str(mes_nombre_sel).capitalize(), 1)
                
                # Calcular dinámicamente el último día real del mes seleccionado (evita errores en febrero o meses de 30 días)
                _, ultimo_dia_mes = calendar.monthrange(anio_sel, mes_n)
                
                f_i = f"{anio_sel}-{mes_n:02d}-01"
                f_f = f"{anio_sel}-{mes_n:02d}-{ultimo_dia_mes:02d}"
                
                df_comps = pd.DataFrame()
                seleccion_opcion = None

                # 2. Conectar de forma segura
                conn_tmp = conectar_db(db_name) if 'conectar_db' in globals() else None

                if conn_tmp:
                    try:
                        st.info(f"📅 **Filtrando datos para el período:** {f_i} al {f_f}")
                        
                        # Consulta optimizada usando parámetros seguros para las fechas
                        query_comps = f"""
                            SELECT DISTINCT n_comprobante, fecha 
                            FROM `{db_name}`.asientos_contables 
                            WHERE (plan_cuentas LIKE '%%2.2.1%%' OR cuenta_contable LIKE '%%Accionista%%')
                            AND fecha BETWEEN %s AND %s
                            ORDER BY fecha DESC, n_comprobante DESC
                        """
                        df_comps = ejecutar_consulta(query_comps, conn_tmp, params=(f_i, f_f))
                        
                    except Exception as e:
                        st.error(f"❌ Error al consultar: {e}")
                    finally:
                        try:
                            conn_tmp.close()
                        except:
                            pass

                # 3. MOSTRAR RESULTADOS FILTRADOS
                if not df_comps.empty:
                    def formato_latino(val):
                        try: return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        except: return val

                    df_comps['opcion'] = df_comps['n_comprobante'].astype(str) + " (Fecha: " + df_comps['fecha'].astype(str) + ")"
                    lista_opciones = df_comps['opcion'].tolist()
                    
                    seleccion_opcion = st.selectbox("📂 Selecciona el comprobante a visualizar:", lista_opciones, key="select_acc_final")
                else:
                    st.warning(f"⚠️ No se encontraron comprobantes con cuentas de Accionista para el período: {mes_nombre_sel} {anio_sel}.")

                # 4. Verificación segura del asiento seleccionado
                if seleccion_opcion:
                    comprobante_activo = seleccion_opcion.split(" ")[0]
                    df_asiento = obtener_asiento_por_comprobante(db_name, comprobante_activo)
                    
                    if df_asiento is not None and not df_asiento.empty:
                        st.markdown(f"**Asiento Contable Completo del Comprobante N°: `{comprobante_activo}`**")
                        
                        df_mostrar = df_asiento.copy()
                        df_mostrar['debe_num'] = pd.to_numeric(df_mostrar['debe'], errors='coerce').fillna(0)
                        df_mostrar['haber_num'] = pd.to_numeric(df_mostrar['haber'], errors='coerce').fillna(0)
                        
                        total_debe = df_mostrar['debe_num'].sum()
                        total_haber = df_mostrar['haber_num'].sum()
                        
                        df_mostrar['debe'] = df_mostrar['debe_num'].apply(formato_latino)
                        df_mostrar['haber'] = df_mostrar['haber_num'].apply(formato_latino)
                        df_mostrar = df_mostrar.drop(columns=['debe_num', 'haber_num'], errors='ignore')
                        
                        st.dataframe(
                            df_mostrar,
                            width='stretch',
                            height=350,
                            column_config={
                                "id": st.column_config.NumberColumn("id", format="%d"),
                                "n_comprobante": st.column_config.TextColumn("N° Comprobante"),
                                "descripcion": st.column_config.TextColumn("Descripción"),
                                "fecha": st.column_config.DateColumn("Fecha"),
                                "plan_cuentas": st.column_config.TextColumn("Plan de Cuentas"),
                                "cuenta_contable": st.column_config.TextColumn("Cuenta Contable"),
                                "referencia": st.column_config.TextColumn("Referencia"),
                                "debe": st.column_config.TextColumn("Debe"),
                                "haber": st.column_config.TextColumn("Haber")
                            }
                        )
                        
                        col1, col2 = st.columns(2)
                        col1.metric("Total Debe (Comprobante)", f"Bs. {formato_latino(total_debe)}")
                        col2.metric("Total Haber (Comprobante)", f"Bs. {formato_latino(total_haber)}")
                    else:
                        st.info("No se encontraron detalles para este comprobante.")
            else:
                st.warning("⚠️ Selecciona una empresa.")
                
        with tab5:
            st.divider()
            st.subheader("💰 Detalle de Comprobantes - Otros Ingresos (7.1.1.01.001)")

            db_actual = locals().get('db') or st.session_state.get('DB_ACTUAL')

            if db_actual and db_actual != "{db}" and db_actual != "None":
                
                import datetime
                import calendar

                # Lectura robusta corregida para evitar el error de datetime
                anio_actual = datetime.date.today().year
                anio_sel = int(st.session_state.get('año_seleccionado') or st.session_state.get('anio', anio_actual))
                mes_sel = st.session_state.get('mes_seleccionado') or st.session_state.get('mes') or st.session_state.get('Mes') or "Mayo"
                
                dic_meses = {
                    "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
                    "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
                    "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
                }
                
                # Conversión segura de mes (texto o número)
                if str(mes_sel).isdigit():
                    mes_n = int(mes_sel)
                else:
                    mes_n = dic_meses.get(str(mes_sel).capitalize(), 5)
                
                _, ultimo_dia = calendar.monthrange(anio_sel, mes_n)
                
                f_i_final = f"{anio_sel}-{mes_n:02d}-01"
                f_f_final = f"{anio_sel}-{mes_n:02d}-{ultimo_dia:02d}"

                st.info(f"🔄 **Período Activo Sincronizado:** Mes de **{mes_sel} {anio_sel}** (`{f_i_final}` al `{f_f_final}`)")

                # Consulta limpia a la base de datos con el rango correcto
                df_comps = obtener_comprobantes_ingresos(db_actual, f_i_final, f_f_final)

                if not df_comps.empty:
                    def formato_latino(val):
                        try:
                            s = f"{float(val):,.2f}"
                            return s.replace(",", "X").replace(".", ",").replace("X", ".")
                        except:
                            return val

                    total_debe_periodo = 0.0
                    total_haber_periodo = 0.0
                    
                    conn_totales = conectar_db(db_actual) if 'conectar_db' in globals() else None
                    if conn_totales and 'n_comprobante' in df_comps.columns:
                        try:
                            lista_n_comps = tuple(df_comps['n_comprobante'].astype(str).unique())
                            if lista_n_comps:
                                placeholders = ','.join(['%s'] * len(lista_n_comps))
                                query_totales = f"""
                                    SELECT SUM(CAST(debe AS DECIMAL(18,2))) as total_debe, SUM(CAST(haber AS DECIMAL(18,2))) as total_haber 
                                    FROM `{db_actual}`.asientos_contables 
                                    WHERE n_comprobante IN ({placeholders})
                                """
                                df_t = ejecutar_consulta(query_totales, conn_totales, params=lista_n_comps)
                                if not df_t.empty:
                                    total_debe_periodo = float(df_t['total_debe'].iloc[0] or 0.0)
                                    total_haber_periodo = float(df_t['total_haber'].iloc[0] or 0.0)
                        except Exception as e:
                            st.error(f"Error al calcular totales: {e}")
                        finally:
                            try:
                                conn_totales.close()
                            except:
                                pass

                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric("Comprobantes en el Periodo", len(df_comps))
                    col_m2.metric("Total Debe Global", f"Bs. {formato_latino(total_debe_periodo)}")
                    col_m3.metric("Total Haber Global", f"Bs. {formato_latino(total_haber_periodo)}")
                    
                    st.divider()

                    df_comps['opcion'] = df_comps['n_comprobante'].astype(str) + " (Fecha: " + df_comps['fecha'].astype(str) + ")"
                    lista_opciones = df_comps['opcion'].tolist()
                    
                    seleccion_opcion = st.selectbox("📂 Selecciona el comprobante de Ingreso a visualizar:", lista_opciones, key="select_ingresos_v3")
                    
                    if seleccion_opcion:
                        comprobante_activo = seleccion_opcion.split(" ")[0]
                        df_asiento = obtener_asiento_por_comprobante(db_actual, comprobante_activo)
                        
                        if df_asiento is not None and not df_asiento.empty:
                            st.markdown(f"**Asiento Contable Completo del Comprobante N°: `{comprobante_activo}`**")
                            
                            df_mostrar = df_asiento.copy()
                            df_mostrar['debe_num'] = pd.to_numeric(df_mostrar['debe'], errors='coerce').fillna(0)
                            df_mostrar['haber_num'] = pd.to_numeric(df_mostrar['haber'], errors='coerce').fillna(0)
                            
                            total_debe = df_mostrar['debe_num'].sum()
                            total_haber = df_mostrar['haber_num'].sum()
                            
                            df_mostrar['debe'] = df_mostrar['debe_num'].apply(formato_latino)
                            df_mostrar['haber'] = df_mostrar['haber_num'].apply(formato_latino)
                            df_mostrar = df_mostrar.drop(columns=['debe_num', 'haber_num'], errors='ignore')
                            
                            st.dataframe(
                                df_mostrar,
                                width='stretch',
                                height=350,
                                column_config={
                                    "id": st.column_config.NumberColumn("id", format="%d"),
                                    "n_comprobante": st.column_config.TextColumn("N° Comprobante"),
                                    "descripcion": st.column_config.TextColumn("Descripción"),
                                    "fecha": st.column_config.DateColumn("Fecha"),
                                    "plan_cuentas": st.column_config.TextColumn("Plan de Cuentas"),
                                    "cuenta_contable": st.column_config.TextColumn("Cuenta Contable"),
                                    "referencia": st.column_config.TextColumn("Referencia"),
                                    "debe": st.column_config.TextColumn("Debe"),
                                    "haber": st.column_config.TextColumn("Haber")
                                }
                            )
                            
                            col1, col2 = st.columns(2)
                            col1.metric("Total Debe (Comprobante)", f"Bs. {formato_latino(total_debe)}")
                            col2.metric("Total Haber (Comprobante)", f"Bs. {formato_latino(total_haber)}")
                        else:
                            st.info("No se encontraron detalles para este comprobante.")
                else:
                    st.warning(f"⚠️ No hay comprobantes de Otros Ingresos para el mes de **{mes_sel} {anio_sel}** ({f_i_final} al {f_f_final}).")
            else:
                st.warning("⚠️ Selecciona una empresa.")

    except Exception as e:
        st.error(f"Error procesando el reporte contable: {e}")
        import traceback
        st.code(traceback.format_exc())
    

    # --- FILA 11: CALENDARIO FISCAL AUTOMATIZADO ---
    db_actual = st.session_state.get('DB_ACTUAL')

    if db_actual:
        nombre_comercial = st.session_state.get('CLIENTE_NOMBRE', db_actual)
        st.markdown(f"### 📅 Calendario Fiscal SENIAT 2026 - {nombre_comercial}")

        # Ejecutamos tu función para asegurar la consistencia del contribuyente
        verificar_si_es_contribuyente_especial(db_actual)

        # Invocamos directamente tu función visual que dibuja las tablas y los días de pago según el RIF
        mostrar_calendario_cliente(db_actual)
        
    else:
        st.warning("⚠️ Por favor, seleccione una empresa en el menú lateral para visualizar el calendario fiscal.")

    

elif opcion_menu == "📂 Plan de Cuentas":
    st.subheader("Gestión de Plan de Cuentas")
    
    # 1. Recuperamos datos del estado
    db_actual = st.session_state.get('DB_ACTUAL')
    if not db_actual:
        st.error("No se ha seleccionado una base de datos.")
        st.stop()

    # 2. Conexión centralizada
    conn_empresa = conectar_db(db_actual)
    
    try:
        # Definición de las pestañas para un look consistente
        # Definición de las 4 pestañas
        tab1, tab2, tab3, tab4 = st.tabs([
            "📥 Cargar Plan", 
            "📋 Visualizar Plan", 
            "🗑️ Vaciar Plan", 
            "📥 Descargar Excel"
        ])
        
        
        with tab1:
            st.markdown("### Subir Archivo Excel")
            archivo_plan = st.file_uploader("Seleccione el archivo", type=["xlsx", "xls"], key="plan_up")
            
            if archivo_plan:
                df_plan = pd.read_excel(archivo_plan)
                df_plan.columns = df_plan.columns.str.strip().str.lower()
                df_plan = df_plan.rename(columns={'nombre de la cuenta': 'nombre'})
                
                st.write("Vista previa:")
                st.dataframe(df_plan.head(20), use_container_width=True)
                
                if st.button("🚀 Iniciar Importación a Base de Datos", type="primary"):
                    columnas_sql = ['id', 'codigo', 'nombre', 'nivel', 'tipo', 'padre']
                    
                    # Verificamos si al menos las columnas principales existen
                    if 'codigo' in df_plan.columns and 'nombre' in df_plan.columns:
                        try:
                            # Nos aseguramos de incluir las columnas necesarias (completando las faltantes con None si no vienen en el Excel)
                            for col in columnas_sql:
                                if col not in df_plan.columns:
                                    df_plan[col] = None
                                    
                            df_final = df_plan[columnas_sql]
                            
                            # Usamos tu función existente de actualización en lugar de crear un motor con DB_CONFIG
                            actualizar_tabla_completa_db(conn_empresa, 'plan_cuentas', df_final)
                            
                            st.success("✅ ¡Plan de cuentas sincronizado correctamente!")
                            st.balloons()
                        except Exception as e:
                            st.error(f"❌ Error al importar a la base de datos: {e}")
                    else:
                        st.error("❌ El archivo Excel debe contener al menos las columnas 'codigo' y 'nombre'.")

        with tab2:
            st.markdown("### 📋 Plan de Cuentas (Edición, Nuevos y Eliminación)")
            
            # 1. Cargamos los datos actuales de MySQL de forma limpia
            df_actual = consultar_tabla_db(conn_empresa, "plan_cuentas")
            
            if df_actual is None or df_actual.empty:
                df_actual = pd.DataFrame(columns=['id', 'codigo', 'nombre', 'nivel', 'tipo', 'padre'])
            else:
                # Limpiamos nulos para que Streamlit los muestre bien en texto
                for col in ['codigo', 'nombre', 'tipo', 'padre']:
                    if col in df_actual.columns:
                        df_actual[col] = df_actual[col].fillna("").astype(str).replace(['nan', 'None'], '')
            
            # 2. Editor interactivo de Streamlit
            df_editado = st.data_editor(
                df_actual, 
                key="editor_plan_cuentas", 
                num_rows="dynamic", 
                use_container_width=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True), 
                    "codigo": st.column_config.TextColumn("Código Contable", required=True),
                    "nombre": st.column_config.TextColumn("Nombre Cuenta", required=True),
                    "nivel": st.column_config.NumberColumn("Nivel", min_value=1, max_value=5),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Activo", "Pasivo", "Patrimonio", "Ingreso", "Egreso", "Grupo"]),
                    "padre": st.column_config.TextColumn("Cuenta Padre")
                }
            )
            
            # 3. Guardado inteligente corregido para MySQL
            if st.button("💾 Guardar Cambios en Plan de Cuentas", type="primary"):
                try:
                    # Copiamos para manipular
                    df_a_guardar = df_editado.copy()
                    
                    # Convertimos strings vacíos reales a None para que MySQL guarde NULL correctamente
                    df_a_guardar = df_a_guardar.replace(r'^\s*$', None, regex=True)
                    
                    # Aseguramos que los IDs vacíos o nuevos sean None (para que MySQL autogenere el ID)
                    if 'id' in df_a_guardar.columns:
                        df_a_guardar['id'] = pd.to_numeric(df_a_guardar['id'], errors='coerce')
                    
                    # Ejecutamos la actualización de la tabla completa
                    actualizar_tabla_completa_db(conn_empresa, "plan_cuentas", df_a_guardar)
                    
                    st.success("✅ ¡Modificaciones guardadas y plan de cuentas actualizado correctamente!")
                    st.balloons()
                    st.rerun() 
                except Exception as e:
                    st.error(f"❌ Error al guardar las modificaciones: {e}")

        with tab3:
            st.markdown("### ⚠️ Vaciar Plan de Cuentas")
            st.warning("Esta acción borrará TODA la información del plan de cuentas de esta empresa.")
            if st.checkbox("Estoy seguro de querer borrar todo"):
                if st.button("🗑️ ELIMINAR TODOS LOS DATOS", type="primary"):
                    cursor = conn_empresa.cursor()
                    cursor.execute("TRUNCATE TABLE plan_cuentas")
                    conn_empresa.commit()
                    st.success("✅ ¡Tabla vaciada exitosamente!")
                    st.balloons()
                    st.rerun()

        with tab4:
            st.markdown("### 📥 Descargar Respaldo")
            df_actual = consultar_tabla_db(conn_empresa, "plan_cuentas")
            if df_actual is not None and not df_actual.empty:
                import io
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_actual.to_excel(writer, index=False, sheet_name='PlanCuentas')
                st.download_button(
                    label="📥 Descargar Excel",
                    data=output.getvalue(),
                    file_name="Plan_de_Cuentas_Respaldo.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.info("No hay datos para descargar.")

    except Exception as e:
        st.error(f"❌ Error crítico: {e}")
    finally:
        if conn_empresa:
            try:
                conn_empresa.close()
            except Exception:
                pass


elif opcion_menu == "📝 Asientos Contables":
    st.write(f"DEBUG: Empresa actual en sesión: {st.session_state.get('DB_ACTUAL')}")
     # 1. Recuperamos contexto de seguridad
    # 1. Recuperamos contexto de seguridad
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')
    
    # 2. Validación centralizada
    if not db_actual:
        st.error("No se ha seleccionado una base de datos.")
        st.stop()

    # Filtro de acceso: Verificamos permiso de la empresa antes de cargar nada
    empresa_data = obtener_datos_agente_db(db_actual)
    if empresa_data and rol != 'admin':
        if empresa_data.get('id') != cliente_id:
            st.error("⚠️ Acceso denegado a esta empresa.")
            st.stop()

    # Mantenemos la lógica de sub_opcion
    if sub_opcion == "Subir Datos":
        st.markdown(f"## 📝 Gestión de Libro Diario: {EMPRESA}")
        
        # 1. Validación de Seguridad: ¿Hay base de datos?
        if 'DB_ACTUAL' in st.session_state and st.session_state['DB_ACTUAL']:
            db_nombre = st.session_state['DB_ACTUAL']
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "📖 Ver Libro Diario", 
                "📤 Importar Excel", 
                "🗑️ Vaciar Asiento de Diarios",
                "🤖 Asientos Costos Automatizados",
                "📈 Asientos Ingresos Automatizados"  # Icono cambiado aquí
            ])

            def exportar_a_excel(df):
                output = io.BytesIO()
                # Cambiamos 'xlsxwriter' por 'openpyxl'
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='LibroDiario')
                return output.getvalue()

            with tab1:
                # --- 1. Selector de fechas ---
                col1, col2 = st.columns(2)
                with col1:
                    f_inicio = st.date_input("Fecha Inicio") 
                with col2:
                    f_fin = st.date_input("Fecha Fin")

                # CORREGIDO: Usamos 'db_nombre' en lugar de 'db_actual' para evitar errores de variable no definida
                conn_temp = conectar_db(db_nombre)
                
                try:
                    # Pasamos la conexión (objeto), no el nombre (string)
                    df_diario = consultar_libro_diario_db(conn_activa=conn_temp, fecha_inicio=f_inicio, fecha_fin=f_fin)
                except Exception as e:
                    st.error(f"❌ Error al consultar el libro diario: {e}")
                    df_diario = None
                finally:
                    # CERRAMOS la conexión de forma segura en un bloque finally
                    if conn_temp:
                        conn_temp.close()
                
                # --- 3. Visualización limpia ---
                if df_diario is not None and not df_diario.empty:
                    # Normalización
                    df_diario.columns = [c.lower() for c in df_diario.columns]
                    
                    # 1. Definimos df_editado SIEMPRE. 
                    # El editor devuelve el dataframe actualizado.
                    df_editado = st.data_editor(
                        df_diario, 
                        width='stretch', 
                        hide_index=True,
                        key="editor_diario"
                    )

                    # 2. Botón de Guardar
                    # 2. Botón de Guardar Directo
                    if st.button("💾 Guardar Cambios"):
                        try:
                            # Enviamos directamente el DataFrame editado completo a la base de datos
                            exito = actualizar_libro_diario_en_db(db_nombre, df_editado)
                            if exito:
                                st.success("¡Registros actualizados correctamente en la base de datos!")
                                st.rerun()
                            else:
                                st.error("Error al guardar en la base de datos.")
                        except Exception as e:
                            st.error(f"Error técnico: {str(e)}")
                    
                    # 3. Descarga y Totales (ahora siempre tienen acceso a df_editado)
                    excel_data = exportar_a_excel(df_editado)
                    st.download_button(
                        label="📥 Descargar Libro Diario",
                        data=excel_data,
                        file_name=f"Libro_Diario_{f_inicio}_al_{f_fin}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    t_debe = df_editado['debe'].sum()
                    t_haber = df_editado['haber'].sum()
                    
                    st.divider()
                    c1, c2, c3 = st.columns(3)
                    c1.metric("TOTAL DEBE", formato_contable(t_debe))
                    c2.metric("TOTAL HABER", formato_contable(t_haber))
                    
                    dif = abs(t_debe - t_haber)
                    if dif < 0.01:
                        c3.success("✅ DIARIO CUADRADO")
                    else:
                        c3.error(f"❌ DESCUADRE: {formato_contable(t_debe - t_haber)}")
                        
                else:
                    st.info("No hay asientos registrados para este rango de fechas.")
                    
            with tab2:
                # --- PESTAÑA 2: IMPORTACIÓN ---
                st.markdown("### 📤 Cargar nuevos Asientos Contables")
                archivo_excel = st.file_uploader("Seleccione el archivo .xlsx", type=["xlsx", "xls"], key="up_diario_tabs")
                
                if archivo_excel:
                    try:
                        # 1. Lectura inicial
                        df_subido = pd.read_excel(archivo_excel, dtype=object)
                        df_subido.columns = df_subido.columns.astype(str).str.strip().str.lower()

                        if len(df_subido.columns) >= 8 and not all(col in df_subido.columns for col in ['n_comprobante', 'descripcion', 'fecha']):
                            df_subido = pd.read_excel(archivo_excel, header=None, dtype=object)
                            df_subido = df_subido.iloc[:, :8]
                            df_subido.columns = ['n_comprobante', 'descripcion', 'fecha', 'plan_de_cuentas', 'cuenta_contable', 'ref', 'debe', 'haber']

                        # 2. Procesar fecha PRIMERO (mientras conserva su formato original de Excel)
                        if 'fecha' in df_subido.columns:
                            df_subido['fecha'] = pd.to_datetime(df_subido['fecha'], errors='coerce').dt.date

                        # 3. Convertir el resto de columnas a texto para evitar el crash de Arrow en la UI
                        for col in df_subido.columns:
                            if col != 'fecha':  # Dejamos la fecha intacta para el manejo interno
                                df_subido[col] = df_subido[col].astype(str).replace(['nan', 'None', ''], '')

                        st.write("### ✅ Vista previa de la carga:")
                        st.dataframe(df_subido, hide_index=True, width='stretch')

                        # 4. Importación segura
                        if st.button("🚀 Confirmar e Importar al Diario", width='stretch'):
                            conn = conectar_db(db_actual) 
                            
                            if conn:
                                try:
                                    with st.spinner(f"Subiendo datos a la base: {db_actual}..."):
                                        if cargar_asientos_contables_db(df_subido, conn):
                                            st.balloons()
                                            st.success(f"✅ ¡Asientos procesados con éxito en {db_actual}!")
                                except Exception as e:
                                    st.error(f"Error crítico en la inserción: {e}")
                                finally:
                                    try:
                                        conn.close()
                                    except Exception:
                                        pass
                            else:
                                st.error("❌ No se pudo establecer conexión con la base de datos.")
                    
                    except Exception as e:
                        st.error(f"Error al procesar el archivo: {e}")

            with tab3:
                # --- PESTAÑA 3: ADMINISTRACIÓN (LIMPIEZA SELECTIVA) ---
                st.markdown("### ⚙️ Administración: Limpieza por Fechas")
                with st.container(border=True):
                    st.warning("⚠️ **BORRADO SELECTIVO DE ASIENTOS**")
                    
                    # 1. Selector de rango a eliminar
                    col_f1, col_f2 = st.columns(2)
                    f_eliminar_inicio = col_f1.date_input("Desde:", key="del_inicio")
                    f_eliminar_fin = col_f2.date_input("Hasta:", key="del_fin")
                    
                    st.write(f"Se eliminarán los asientos entre **{f_eliminar_inicio}** y **{f_eliminar_fin}**.")
                    
                    # 2. Confirmación doble
                    check_borrar = st.checkbox("Estoy seguro de borrar este periodo.", key="check_borrar_rango")
                    
                    if check_borrar:
                        if st.button("🧨 BORRAR RANGO SELECCIONADO", type="primary"):
                            conn = conectar_db(db_actual)
                            
                            if conn:
                                try:
                                    cursor = conn.cursor()
                                    # USAMOS DELETE EN LUGAR DE TRUNCATE
                                    query_delete = "DELETE FROM asientos_contables WHERE fecha BETWEEN %s AND %s"
                                    cursor.execute(query_delete, (f_eliminar_inicio, f_eliminar_fin))
                                    
                                    filas_afectadas = cursor.rowcount
                                    conn.commit()
                                    cursor.close()
                                    
                                    st.success(f"✅ Éxito: Se eliminaron {filas_afectadas} asientos del periodo.")
                                except Exception as e:
                                    st.error(f"Error al ejecutar la limpieza: {e}")
                                finally:
                                    # Ya no cerramos la conexión aquí para mantenerla viva
                                    pass
                            else:
                                st.error("❌ Error de conexión.")
            with tab4:
                # 1. Recuperamos de la sesión el nombre o ID de la base de datos de la empresa actual 
                # (Ajusta la clave 'empresa_actual' por la variable exacta que uses en tu app para el cliente)
                nombre_bd_cliente = st.session_state.get('empresa_actual') 
                
                # 2. Llamamos a la conexión inyectándole la base de datos del cliente
                conexion_actual = conectar_db(nombre_bd_cliente) 
                
                # 3. Validamos y renderizamos
                if conexion_actual:
                    renderizar_tab_asientos_automatizados(conexion_actual)
                else:
                    st.error("No se pudo establecer la conexión con la base de datos de la empresa para los asientos automatizados.")

            with tab5:
                # 1. Recuperamos de la sesión el nombre o ID de la base de datos de la empresa actual 
                nombre_bd_cliente = st.session_state.get('empresa_actual') 
                
                # 2. Llamamos a la conexión inyectándole la base de datos del cliente
                conexion_actual = conectar_db(nombre_bd_cliente) 
                
                # 3. Validamos y renderizamos
                if conexion_actual:
                    renderizar_tab_asientos_ventas(conexion_actual)
                else:
                    st.error("No se pudo establecer la conexión con la base de datos de la empresa para los asientos automatizados.")

        else:
            st.warning("⚠️ Por favor, seleccione una empresa en el panel lateral para gestionar sus asientos.")


    if sub_opcion == "Conciliación Bancaria":
        st.title("🏦 Conciliación Bancaria")
        st.markdown("---")

        # 1. Validación de Contexto Global
        db_actual = st.session_state.get('DB_ACTUAL')
        cliente_id = st.session_state.get('cliente_id')
        rol = st.session_state.get('rol')

        if not db_actual:
            st.error("No se ha seleccionado una base de datos.")
            st.stop()

        empresa_data = obtener_datos_agente_db(db_actual)
        if not empresa_data:
            st.error("⚠️ No se pudieron cargar los datos de la empresa.")
            st.stop()

        # 2. Conexión Maestra Segura (con reconexión automática si está caída)
        if 'conn_conciliacion' not in st.session_state or st.session_state.get('db_conexion_actual') != db_actual:
            st.session_state['conn_conciliacion'] = conectar_db(db_actual)
            st.session_state['db_conexion_actual'] = db_actual

        conn = st.session_state['conn_conciliacion']

        try:
            if conn:
                conn.ping(reconnect=True)
            else:
                conn = conectar_db(db_actual)
                st.session_state['conn_conciliacion'] = conn
        except Exception:
            conn = conectar_db(db_actual)
            st.session_state['conn_conciliacion'] = conn

        if not conn:
            st.error(f"❌ Error crítico: No se pudo conectar a la base de datos `{db_actual}`.")
            st.stop()

        # 3. Selectores Globales de Periodo
        try:
            col1, col2 = st.columns([1, 1])
            with col1:
                mes_sel = st.selectbox(
                    "Mes", 
                    ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                     "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"], 
                    index=2, 
                    key="mes_seleccionado_conciliacion"
                )
            with col2:
                ano_sel = st.selectbox("Año", [2025, 2026, 2027], index=1, key="ano_seleccionado")
        except Exception as e:
            st.error(f"Error al inicializar los selectores globales: {e}")
            st.stop()


        # Pestañas del Módulo
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "⚙️ Configuración Saldos", 
            "📂 Importar Movimientos", 
            "📜 Estado de Cuenta", 
            "📊 Conciliación Bancaria", 
            "🔒 Cierre de Mes"
        ])

        with tab1:
            st.subheader("⚙️ Gestión de Saldos Bancarios")

            # 1. SEGURIDAD Y CONTEXTO
            db_actual = st.session_state.get('DB_ACTUAL')
            cliente_id = st.session_state.get('cliente_id')
            rol = st.session_state.get('rol')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            empresa_data = obtener_datos_agente_db(db_actual)

            # 2. FILTRO DE ACCESO
            if empresa_data and rol != 'admin':
                if empresa_data.get('id') != cliente_id:
                    st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                    st.stop()

            if not empresa_data:
                st.error("⚠️ No se pudieron cargar los datos de la empresa.")
            else:
                # 3. CARGA DE DATOS DINÁMICA CON CONEXIÓN SEGURA LOCAL
                conn_tab1 = conectar_db(db_actual)
                if not conn_tab1:
                    st.error(f"❌ Error crítico: No se pudo conectar a la base de datos `{db_actual}`.")
                else:
                    try:
                        query_saldos = f"""
                            SELECT id, banco, mes, ano, saldo_inicial, saldo_final 
                            FROM `{db_actual}`.saldos_bancarios 
                            ORDER BY ano DESC, id DESC
                        """
                        
                        df_saldos = ejecutar_consulta(query_saldos, conn_tab1)
                        
                        if df_saldos is not None and not df_saldos.empty:
                            df_view = df_saldos.copy()
                            
                            def formatear_moneda(valor):
                                try:
                                    if pd.isna(valor) or valor is None:
                                        return "0,00"
                                    return "{:,.2f}".format(float(valor)).replace(",", "X").replace(".", ",").replace("X", ".")
                                except Exception:
                                    return "0,00"

                            df_view['saldo_inicial'] = df_view['saldo_inicial'].apply(formatear_moneda)
                            df_view['saldo_final'] = df_view['saldo_final'].apply(formatear_moneda)
                            
                            st.dataframe(df_view, use_container_width=True)
                        else:
                            nombre_emp = empresa_data.get('nombre_empresa', 'la empresa')
                            st.info(f"No hay saldos registrados para {nombre_emp}.")
                            
                    except Exception as e:
                        st.error(f"Error al cargar la tabla de saldos: {e}")

                # 4. FORMULARIO DE REGISTRO
                st.markdown("---")
                st.subheader("➕ Agregar / Editar Saldo")
                
                with st.form("form_saldos_main"):
                    c1, c2 = st.columns(2)
                    m_input = c1.selectbox("Mes", ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                                                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"])
                    a_input = c2.selectbox("Año", [2025, 2026, 2027])
                    
                    c4, c5 = st.columns(2)
                    val_ini = c4.number_input("Saldo Inicial", value=0.00, format="%.2f")
                    val_fin = c5.number_input("Saldo Final", value=0.00, format="%.2f")
                    
                    if st.form_submit_button("Guardar / Actualizar Registro"):
                        if guardar_saldo_mensual(conn_tab1, 'BDV', m_input, a_input, val_ini, val_fin, db_name=db_actual):
                            st.success(f"✅ Registro de {m_input} guardado.")
                            st.rerun()

                # 5. ELIMINACIÓN SEGURA Y DINÁMICA
                with st.expander("🗑️ Eliminar un registro"):
                    id_eliminar = st.number_input("ID del registro a eliminar", min_value=1, step=1, key="input_id_eliminar_tab1")
                    if st.button("Confirmar Eliminación", key="btn_confirmar_eliminar_tab1"):
                        try:
                            cursor = conn_tab1.cursor()
                            cursor.execute(f"DELETE FROM `{db_actual}`.saldos_bancarios WHERE id = %s", (id_eliminar,))
                            conn_tab1.commit()
                            cursor.close()
                            st.warning("Registro eliminado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar: {e}")
                
                try:
                    conn_tab1.close()
                except:
                    pass


        with tab2:
            st.subheader("📂 Importar nuevo estado de cuenta")

            db_actual = st.session_state.get('DB_ACTUAL')
            cliente_id = st.session_state.get('cliente_id')
            rol = st.session_state.get('rol')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            empresa_data = obtener_datos_agente_db(db_actual)

            if empresa_data and rol != 'admin':
                if empresa_data['id'] != cliente_id:
                    st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                    st.stop()

            if not empresa_data:
                st.error("⚠️ No se pudieron cargar los datos de la empresa.")
            else:
                banco_sel = st.selectbox("Seleccione el Banco", ["Banco de Venezuela (BDV)", "Banesco", "Mercantil"], key="banco_select")
                archivo_banco = st.file_uploader("Suba el archivo Excel (.xlsx) del banco", type=["xlsx"], key="file_banco")

                if archivo_banco:
                    if st.button("Procesar e Importar"):
                        with st.spinner(f"Procesando archivo de {banco_sel}..."):
                            try:
                                if conn:
                                    try:
                                        conn.ping(reconnect=True)
                                    except Exception:
                                        pass

                                resultado = False
                                
                                if banco_sel == "Banco de Venezuela (BDV)":
                                    resultado = cargar_estado_cuenta_bdv(archivo_banco, conn)
                                elif banco_sel == "Banesco":
                                    resultado = cargar_estado_cuenta_banesco(archivo_banco, conn)
                                elif banco_sel == "Mercantil":
                                    resultado = cargar_estado_cuenta_mercantil(archivo_banco, conn)
                                
                                if resultado:
                                    st.success(f"✅ Movimientos de {banco_sel} importados con éxito.")
                                    st.balloons()
                                    st.rerun()
                                else:
                                    st.error(f"❌ No se pudieron procesar los datos de {banco_sel}.")
                                    
                            except Exception as e:
                                st.error(f"Error crítico procesando {banco_sel}: {e}")
    

        # --- TAB 3: ESTADO DE CUENTA BANCARIO ---
        with tab3:
            st.subheader("📂 Estado de Cuenta Bancario")

            db_actual = st.session_state.get('DB_ACTUAL')
            cliente_id = st.session_state.get('cliente_id')
            rol = st.session_state.get('rol')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            empresa_data = obtener_datos_agente_db(db_actual)

            if empresa_data and rol != 'admin':
                if empresa_data['id'] != cliente_id:
                    st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                    st.stop()

            if not empresa_data:
                st.error("⚠️ No se pudieron cargar los datos de la empresa.")
            else:
                mes_map = {"Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                           "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12}
                mes_num = mes_map[mes_sel]

                df_cuenta = pd.DataFrame()

                try:
                    if conn is None:
                        st.warning("Reconectando a la base de datos...")
                        conn = conectar_db(db_actual)
                    else:
                        try:
                            conn.ping(reconnect=True)
                        except Exception:
                            conn = conectar_db(db_actual)
                            
                    if conn is None:
                        st.error("No se pudo establecer conexión con la base de datos.")
                        st.stop()

                    import calendar
                    fecha_inicio = f"{ano_sel}-{mes_num:02d}-01"
                    ultimo_dia = calendar.monthrange(int(ano_sel), int(mes_num))[1]
                    fecha_fin = f"{ano_sel}-{mes_num:02d}-{ultimo_dia}"

                    query = f"""
                        SELECT id, banco_nombre, cuenta_numero, fecha_movimiento, referencia, 
                               descripcion, monto, estado_conciliacion 
                        FROM `{db_actual}`.banco_movimientos 
                        WHERE fecha_movimiento >= %s AND fecha_movimiento <= %s
                        ORDER BY fecha_movimiento DESC
                    """
                    df_cuenta = ejecutar_consulta(query, conn, params=(fecha_inicio, fecha_fin))
                    
                    if not df_cuenta.empty:
                        st.dataframe(df_cuenta, use_container_width=True)
                        st.write(f"**Total movimientos encontrados:** {len(df_cuenta)}")
                    else:
                        st.info(f"No hay movimientos para {empresa_data['nombre_empresa']} en {mes_sel} {ano_sel}.")

                except Exception as e:
                    st.error(f"Error específico en la consulta: {e}")

                if rol == 'admin':
                    with st.expander("⚠️ Zona de Administración"):
                        if st.button("🗑️ Vaciar Todo (CUIDADO)"):
                            try:
                                cursor = conn.cursor()
                                cursor.execute(f"DELETE FROM `{db_actual}`.banco_movimientos WHERE empresa_id = %s", (cliente_id,))
                                conn.commit()
                                cursor.close()
                                st.success("Registros de esta empresa eliminados.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al vaciar registros: {e}")

    
        # ==========================================
        # --- TAB 4: CONCILIACIÓN BANCARIA (TABLERO) ---
        # ==========================================
        with tab4:
            st.subheader("📊 Resumen del Periodo")

            db_actual = st.session_state.get('DB_ACTUAL')
            cliente_id = st.session_state.get('cliente_id')
            rol = st.session_state.get('rol')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            empresa_data = obtener_datos_agente_db(db_actual)

            if empresa_data and rol != 'admin':
                if empresa_data['id'] != cliente_id:
                    st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                    st.stop()

            if not empresa_data:
                st.error("⚠️ No se pudieron cargar los datos de la empresa.")
            else:
                try:
                    # Verificación rápida de conexión sin bloquear
                    if conn:
                        try:
                            conn.ping(reconnect=True)
                        except Exception:
                            conn = conectar_db(db_actual)
                            st.session_state['conn_conciliacion'] = conn
                    
                    if conn:
                        # Usamos un contenedor por si el tablero es muy pesado
                        with st.spinner("Calculando tablero de conciliación..."):
                            mostrar_tablero_conciliacion(conn, mes_sel, ano_sel)
                    else:
                        st.error("❌ ERROR CRÍTICO: No se pudo establecer conexión con la base de datos.")
                        
                except Exception as e:
                    st.error(f"❌ Error al conectar con el tablero: {e}")


        # --- TAB 5: CIERRE DE MES (CANDADO DE SEGURIDAD) ---
        # ==========================================
        # --- TAB 5: CIERRE Y BLOQUEO DE MES ---
        # ==========================================
        with tab5:
            st.subheader("🔒 Cierre y Bloqueo de Mes")
            
            db_actual = st.session_state.get('DB_ACTUAL')
            cliente_id = st.session_state.get('cliente_id')
            rol = st.session_state.get('rol')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            empresa_data = obtener_datos_agente_db(db_actual)

            if empresa_data and rol != 'admin':
                if empresa_data['id'] != cliente_id:
                    st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                    st.stop()

            mes_map = {
                "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
            }
            mes_num = mes_map[mes_sel]

            try:
                if 'conn' in locals() and conn:
                    conn.ping(reconnect=True)
                else:
                    conn = conectar_db(db_actual)
            except Exception as e:
                st.error(f"Error de conexión con la base de datos: {e}")
                st.stop()

            try:
                # CORREGIDO: Se quitó 'buffered=True'
                cursor = conn.cursor()
                query_check = f"SELECT COUNT(*) FROM `{db_actual}`.banco_movimientos WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s AND estado_conciliacion = 'Cerrado'"
                cursor.execute(query_check, (mes_num, ano_sel))
                es_cerrado = cursor.fetchone()[0] > 0
            except Exception as e:
                st.error(f"Error al verificar el estado del mes: {e}")
                es_cerrado = False
            finally:
                if 'cursor' in locals() and cursor:
                    cursor.close()

            if es_cerrado:
                st.error(f"🔒 El mes de {mes_sel} {ano_sel} en {empresa_data.get('nombre_empresa', db_actual)} está CERRADO.")
            else:
                st.warning("⚠️ Acción irreversible: El cierre de mes bloquea ediciones.")
                if st.checkbox("✅ Entiendo las consecuencias, quiero cerrar el mes", key="chk_cierre"):
                    if st.button("Confirmar Cierre de Mes", type="primary"):
                        try:
                            cursor = conn.cursor()
                            query_update = f"""
                                UPDATE `{db_actual}`.banco_movimientos 
                                SET estado_conciliacion = 'Cerrado' 
                                WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s
                            """
                            cursor.execute(query_update, (mes_num, ano_sel))
                            conn.commit()
                            st.success("✅ Mes cerrado con éxito.")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(f"❌ Error al ejecutar el cierre de mes: {e}")
                        finally:
                            if 'cursor' in locals() and cursor:
                                cursor.close()


    elif sub_opcion == "Consultar Comprobante":
        st.subheader("🔍 Buscador de Comprobantes")

        # 1. SEGURIDAD Y CONTEXTO
        db_actual = st.session_state.get('DB_ACTUAL')
        cliente_id = st.session_state.get('cliente_id')
        rol = st.session_state.get('rol')

        if not db_actual:
            st.error("No se ha seleccionado una base de datos de empresa.")
            st.stop()

        empresa_data = obtener_datos_agente_db(db_actual)

        # 2. FILTRO DE ACCESO
        if empresa_data and rol != 'admin':
            if empresa_data['id'] != cliente_id:
                st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                st.stop()

        if not empresa_data:
            st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        else:
            # --- ASEGURAR QUE LAS VARIABLES DE FECHA EXISTEN ---
            mes_sel = st.session_state.get('mes_sel', 'Enero')
            ano_sel = st.session_state.get('ano_sel', pd.Timestamp.now().year)
            # --------------------------------------------------

            meses_dict = {
                "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04", 
                "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08", 
                "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
            }
            mes_num = meses_dict.get(mes_sel, "01")
            fecha_inicio = f"{ano_sel}-{mes_num}-01"
            ultimo_dia = calendar.monthrange(int(ano_sel), int(mes_num))[1]
            fecha_fin = f"{ano_sel}-{mes_num}-{ultimo_dia:02d}"

            # --- PARTE 1: CARGAR EL LISTADO FILTRADO POR FECHA ---
            df_listado = pd.DataFrame()
            conn_list = conectar_db(db_actual)
            
            if conn_list:
                try:
                    # Filtrado por el mes y año seleccionados en la barra superior para optimizar rendimiento
                    query_listado = f"""
                        SELECT n_comprobante as 'Nº', MAX(fecha) as 'Fecha', MAX(descripcion) as 'Concepto' 
                        FROM `{db_actual}`.asientos_contables 
                        WHERE fecha BETWEEN %s AND %s
                        GROUP BY n_comprobante ORDER BY fecha DESC
                    """
                    df_listado = pd.read_sql(query_listado, conn_list, params=(fecha_inicio, fecha_fin))
                except Exception as e:
                    st.error(f"Error al cargar el listado de comprobantes: {e}")
                finally:
                    conn_list.close()

            # --- PARTE 2: INTERFAZ DE SELECCIÓN Y TEXT INPUT SIN CONFLICTOS ---
            n_comp_seleccionado = ""
            if not df_listado.empty:
                with st.expander(f"📋 Listado de Comprobantes ({mes_sel} {ano_sel})", expanded=True):
                    event = st.dataframe(
                        df_listado, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )
                    if len(event.selection.rows) > 0:
                        idx = event.selection.rows[0]
                        n_comp_seleccionado = str(df_listado.iloc[idx]['Nº'])

            # Usar session_state para mantener la sincronización del input de texto de forma limpia
            if "busc_comp" not in st.session_state:
                st.session_state.busc_comp = ""

            if n_comp_seleccionado and n_comp_seleccionado != st.session_state.busc_comp:
                st.session_state.busc_comp = n_comp_seleccionado

            # --- PARTE 3: GENERAR REPORTE ---
            with st.expander("🔍 Generar Reporte", expanded=True):
                n_comp = st.text_input("Nº de Comprobante", key="busc_comp")
                btn_comp = st.button("🔎 Generar Reporte", type="primary", use_container_width=True)

            if btn_comp and n_comp:
                # Reporte visual
                disenar_reporte_asiento_contable(n_comp)
                
                # PDF (Conexión dinámica)
                conn_pdf = conectar_db(db_actual)
                if conn_pdf:
                    try:
                        query_pdf = f"SELECT * FROM `{db_actual}`.asientos_contables WHERE n_comprobante = %s"
                        df_asiento_pdf = pd.read_sql(query_pdf, conn_pdf, params=(n_comp,))
                        
                        if not df_asiento_pdf.empty:
                            st.divider()
                            pdf_bytes = generar_pdf_comprobante(df_asiento_pdf, n_comp, conn_pdf)
                            st.download_button(
                                label=f"📥 Descargar PDF {n_comp}",
                                data=pdf_bytes,
                                file_name=f"Comprobante_{n_comp}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                        else:
                            st.warning(f"No se encontraron registros para el comprobante {n_comp}.")
                    except Exception as e:
                        st.error(f"Error al generar el PDF del comprobante: {e}")
                    finally:
                        conn_pdf.close()

    elif sub_opcion == "Consultar Saldos Iniciales":
        st.subheader("🏁 Comprobante de Apertura")
        # 1. SEGURIDAD Y CONTEXTO
        db_actual = st.session_state.get('DB_ACTUAL')
        cliente_id = st.session_state.get('cliente_id')
        rol = st.session_state.get('rol')

        if not db_actual:
            st.error("No se ha seleccionado una base de datos de empresa.")
            st.stop()

        empresa_data = obtener_datos_agente_db(db_actual)

        # 2. FILTRO DE ACCESO
        if empresa_data and rol != 'admin':
            if empresa_data['id'] != cliente_id:
                st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                st.stop()

        if not empresa_data:
            st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        else:
            # --- MENÚ DE PESTAÑAS (Solo se muestra si la seguridad pasa) ---
            tab1, tab2, tab3 = st.tabs(["📖 Ver Comprobante", "📥 Importar Excel", "🗑️ Gestionar Data"])

            # ==========================================
    # PESTAÑA 1: VER COMPROBANTE
    # ==========================================
        with tab1:
            st.markdown(f"### Comprobante de Saldos Iniciales: **{empresa_data.get('nombre_empresa', db_actual)}**")
            
            df_apertura = consultar_saldos_iniciales_db(db_actual)
            
            if not df_apertura.empty:
                # Normalizamos nombres de columnas a minúsculas
                df_apertura.columns = [str(c).lower().strip() for c in df_apertura.columns]
                
                # BLINDAJE DE TIPOS DE DATOS (Evita el error de PyArrow en Streamlit moderno)
                if 'descripcion' in df_apertura.columns:
                    df_apertura['descripcion'] = df_apertura['descripcion'].astype(str)
                if 'codigo' in df_apertura.columns:
                    df_apertura['codigo'] = df_apertura['codigo'].astype(str)
                
                for col_num in ['debe', 'haber']:
                    if col_num in df_apertura.columns:
                        df_apertura[col_num] = pd.to_numeric(df_apertura[col_num], errors='coerce').fillna(0.0)

                # Renderizamos con la nueva sintaxis width='stretch'
                fmt = {'debe': formato_contable, 'haber': formato_contable}
                st.dataframe(df_apertura.style.format(fmt), width='stretch', hide_index=True)
                
                t_debe = df_apertura['debe'].astype(float).sum()
                t_haber = df_apertura['haber'].astype(float).sum()
                
                c1, c2 = st.columns(2)
                c1.metric("TOTAL DEBE", formato_contable(t_debe))
                c2.metric("TOTAL HABER", formato_contable(t_haber))
                
                if abs(t_debe - t_haber) < 0.01:
                    st.success("✅ La apertura está cuadrada correctamente.")
                else:
                    st.error(f"❌ Descuadre detectado: {formato_contable(t_debe - t_haber)}")
            else:
                st.warning(f"⚠️ No cargo por completo el archivo de saldos iniciales o la tabla está vacía para {empresa_data.get('nombre_empresa', db_actual)}. Ve a la pestaña 'Importar Excel'.")
                # Aquí iría el resto de la lógica para tab2 y tab3...

            with tab2:
                st.markdown("### 📤 Cargar nuevo Comprobante de Apertura")

                # 1. SEGURIDAD Y CONTEXTO
                db_actual = st.session_state.get('DB_ACTUAL')
                cliente_id = st.session_state.get('cliente_id')
                rol = st.session_state.get('rol')

                if not db_actual:
                    st.error("No se ha seleccionado una base de datos de empresa.")
                    st.stop()

                empresa_data = obtener_datos_agente_db(db_actual)

                # 2. FILTRO DE ACCESO
                if empresa_data and rol != 'admin':
                    if empresa_data['id'] != cliente_id:
                        st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                        st.stop()

                if not empresa_data:
                    st.error("⚠️ No se pudieron cargar los datos de la empresa.")
                else:
                    # 3. PROCESAMIENTO DEL ARCHIVO
                    archivo_excel = st.file_uploader("Seleccione el archivo .xlsx", type=["xlsx", "xls"], key="uploader_tab")
                    
                    if archivo_excel:
                        try:
                            df_subido = pd.read_excel(archivo_excel, header=None, skiprows=1, dtype=object)
                            df_subido.columns = ['id_ex', 'N_comprobante', 'Descripcion', 'Fecha', 
                                                 'plan_de_cuentas', 'cuenta_contable', 'Ref', 'Debe', 'Haber']
                            df_subido = df_subido.drop(columns=['id_ex'])
                            
                            if str(df_subido.iloc[0, 0]).lower() in ['n_comprobante', 'nan']:
                                df_subido = df_subido.iloc[1:].reset_index(drop=True)

                            df_subido['Fecha'] = pd.to_datetime(df_subido['Fecha'], errors='coerce').dt.date

                            # Limpiamos los montos numéricamente para calcular bien
                            df_subido['Debe_num'] = df_subido['Debe'].apply(limpiar_monto_contable)
                            df_subido['Haber_num'] = df_subido['Haber'].apply(limpiar_monto_contable)

                            st.write("### ✅ Vista previa del archivo:")
                            st.dataframe(
                                df_subido.style.format({
                                    'Debe': lambda x: formato_contable(limpiar_monto_contable(x)),
                                    'Haber': lambda x: formato_contable(limpiar_monto_contable(x))
                                }), 
                                hide_index=True, width='stretch'
                            )

                            # Validación por cada comprobante individual
                            resumen_comprobantes = df_subido.groupby('N_comprobante')[['Debe_num', 'Haber_num']].sum().reset_index()
                            
                            st.write("### 📊 Auditoría por Comprobante:")
                            todo_cuadrado = True
                            
                            for index, row in resumen_comprobantes.iterrows():
                                comp = row['N_comprobante']
                                t_debe = row['Debe_num']
                                t_haber = row['Haber_num']
                                diferencia = abs(t_debe - t_haber)
                                

                            # Totales globales del archivo
                            v_debe = df_subido['Debe_num'].sum()
                            v_haber = df_subido['Haber_num'].sum()

                            st.markdown("---")
                            c1, c2, c3 = st.columns(3)
                            c1.metric("TOTAL GENERAL DEBE", formato_contable(v_debe))
                            c2.metric("TOTAL GENERAL HABER", formato_contable(v_haber))
                            
                            if todo_cuadrado and abs(v_debe - v_haber) < 0.01:
                                c3.success("✅ TODO EL ARCHIVO CUADRA")
                                if st.button("🚀 Confirmar e Importar"):
                                    df_final_import = df_subido.drop(columns=['Debe_num', 'Haber_num'])
                                    if cargar_saldos_iniciales_db(df_final_import, nombre_db=db_actual):
                                        st.balloons()
                                        st.success("✅ ¡ASIENTOS GUARDADOS EXITOSAMENTE!")
                                        st.rerun()
                            else:
                                c3.error("❌ HAY COMPROBANTES DESCUADRADOS EN EL ARCHIVO")
                                st.warning("⚠️ Revisa las filas del comprobante 110002 en tu Excel, ya que tienen montos en el Debe pero les falta su contrapartida en el Haber.")

                        except Exception as e:
                            st.error(f"Error crítico: {e}")

            with tab3:
                st.markdown("### ⚙️ Administración de Datos")

                # 1. SEGURIDAD Y CONTEXTO
                db_actual = st.session_state.get('DB_ACTUAL')
                cliente_id = st.session_state.get('cliente_id')
                rol = st.session_state.get('rol')

                if not db_actual:
                    st.error("No se ha seleccionado una base de datos de empresa.")
                    st.stop()

                empresa_data = obtener_datos_agente_db(db_actual)

                # 2. FILTRO DE ACCESO
                if empresa_data and rol != 'admin':
                    if empresa_data['id'] != cliente_id:
                        st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                        st.stop()

                if not empresa_data:
                    st.error("⚠️ No se pudieron cargar los datos de la empresa.")
                else:
                    # 3. INTERFAZ DE BORRADO SEGURO
                    with st.container(border=True):
                        st.error("⚠️ **ADVERTENCIA CRÍTICA: BORRADO PERMANENTE**")
                        st.write(f"Estás operando sobre la base de datos: **{db_actual}**")
                        
                        confirmar_borrado = st.checkbox("He leído la advertencia y estoy de acuerdo en borrar toda la información de esta empresa.")

                        if confirmar_borrado:
                            if st.button("🧨 VACIAR TABLA DE SALDOS", type="primary", width='stretch'):
                                # Usamos la conexión dinámica
                                conn = conectar_db(db_actual)
                                if conn:
                                    try:
                                        cursor = conn.cursor()
                                        # ESPECIFICAMOS LA BASE DE DATOS DINÁMICAMENTE
                                        cursor.execute(f"TRUNCATE TABLE `{db_actual}`.saldos_iniciales")
                                        conn.commit()
                                        st.success("✅ La tabla ha sido vaciada exitosamente.")
                                        import time
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error al vaciar: {e}")
                                    finally:
                                        cursor.close()
                                        conn.close()
                        else:
                            st.info("💡 Debe marcar la casilla de arriba para habilitar el botón de borrado.")

    elif sub_opcion == "Gestor Documental":
        st.subheader("📁 Gestor Documental en la Nube")
        st.markdown("Sube y administra comprobantes, transferencias, PDFs o archivos de Office de forma organizada.")

        db_actual = st.session_state.get('DB_ACTUAL')
        if not db_actual or db_actual == 'none':
            st.warning("⚠️ Por favor, selecciona un Cliente/Empresa primero.")
            st.stop()

        import os
        from datetime import datetime

        # Directorio base para almacenar los archivos de forma local o persistente en el servidor
        DIRECTORIO_SUBIDAS = "documentos_clientes"
        dir_empresa = os.path.join(DIRECTORIO_SUBIDAS, str(db_actual))
        os.makedirs(dir_empresa, exist_ok=True)

        # --- FORMULARIO DE SUBIDA ---
        with st.expander("📤 Subir Nuevo Documento", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                categoria = st.selectbox(
                    "Categoría del Documento", 
                    ["Transferencia Bancaria", "Factura PDF", "Documento Legal", "Excel / Reporte", "Otro"]
                )
            with col2:
                archivos_subidos = st.file_uploader(
                    "Selecciona los archivos", 
                    type=["pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "txt"], 
                    accept_multiple_files=True
                )

            if st.button("💾 Guardar Documentos en la Nube", type="primary"):
                if archivos_subidos:
                    conn_doc = conectar_db(db_actual)
                    cursor = conn_doc.cursor() if conn_doc else None
                    
                    try:
                        for archivo in archivos_subidos:
                            # Evitar colisiones de nombres usando marca de tiempo
                            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                            nombre_limpio = f"{timestamp_str}_{archivo.name}"
                            ruta_completa = os.path.join(dir_empresa, nombre_limpio)
                            
                            # Guardar el archivo físicamente en el servidor
                            with open(ruta_completa, "wb") as f:
                                f.write(archivo.getbuffer())
                            
                            # Registrar en la base de datos MySQL
                            query_insert = """
                                INSERT INTO documentos_cloud (empresa_db, categoria, nombre_archivo, ruta_archivo) 
                                VALUES (%s, %s, %s, %s)
                            """
                            cursor.execute(query_insert, (str(db_actual), categoria, archivo.name, ruta_completa))
                        
                        conn_doc.commit()
                        st.success(f"✅ ¡{len(archivos_subidos)} archivo(s) subido(s) y guardado(s) con éxito!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar los documentos: {e}")
                    finally:
                        if conn_doc:
                            conn_doc.close()
                else:
                    st.warning("⚠️ Debes seleccionar al menos un archivo antes de guardar.")

        st.divider()

        # --- LISTADO, DESCARGA Y ELIMINACIÓN DE DOCUMENTOS EXISTENTES ---
        st.markdown("### 🗂️ Documentos Almacenados")
        
        conn_doc = conectar_db(db_actual)
        if conn_doc:
            try:
                query_select = "SELECT id, categoria, nombre_archivo, ruta_archivo, fecha_subida FROM documentos_cloud WHERE empresa_db = %s ORDER BY fecha_subida DESC"
                df_docs = ejecutar_consulta(query_select, conn_doc, params=(str(db_actual),))
                
                if df_docs is not None and not df_docs.empty:
                    for _, row in df_docs.iterrows():
                        cols = st.columns([3, 2, 2, 1, 1])
                        cols[0].text(f"📄 {row['nombre_archivo']}")
                        cols[1].text(f"📂 {row['categoria']}")
                        cols[2].text(str(row['fecha_subida'])[:10])
                        
                        # Botón de descarga directa
                        if os.path.exists(row['ruta_archivo']):
                            with open(row['ruta_archivo'], "rb") as file_to_download:
                                cols[3].download_button(
                                    label="⬇️",
                                    data=file_to_download,
                                    file_name=row['nombre_archivo'],
                                    mime="application/octet-stream",
                                    key=f"down_{row['id']}"
                                )
                        else:
                            cols[3].text("⚠️ No hallado")
                            
                        # Botón de eliminación
                        if cols[4].button("🗑️", key=f"del_{row['id']}"):
                            try:
                                # 1. Borrar archivo físico si existe
                                if os.path.exists(row['ruta_archivo']):
                                    os.remove(row['ruta_archivo'])
                                
                                # 2. Borrar registro de la base de datos MySQL
                                cursor_del = conn_doc.cursor()
                                cursor_del.execute("DELETE FROM documentos_cloud WHERE id = %s", (row['id'],))
                                conn_doc.commit()
                                cursor_del.close()
                                
                                st.success(f"🗑️ Archivo '{row['nombre_archivo']}' eliminado con éxito.")
                                st.rerun()
                            except Exception as ex_del:
                                st.error(f"❌ Error al eliminar el documento: {ex_del}")
                else:
                    st.info("ℹ️ No hay documentos subidos para esta empresa todavía.")
            except Exception as e:
                st.error(f"Error al cargar la lista de documentos: {e}")
            finally:
                conn_doc.close()



# D. MAYOR ANALÍTICO
# D. MAYOR ANALÍTICO
elif opcion_menu == "📖 Mayor Analítico":
    st.subheader("📖 Mayor Analítico")

    # 1. SEGURIDAD Y CONTEXTO
    db_actual = st.session_state.get("DB_ACTUAL")
    cliente_id = st.session_state.get("cliente_id")
    rol = st.session_state.get("rol")

    # Recuperamos las fechas ya calculadas arriba
    f_inicio_global = st.session_state.get("f_inicio_global")
    f_fin_global = st.session_state.get("f_fin_global")

    if not db_actual:
        st.error("No se ha seleccionado una base de datos de empresa.")
        st.stop()

    empresa_data = obtener_datos_agente_db(db_actual)

    # 2. FILTRO DE ACCESO
    if empresa_data and rol != "admin":
        if empresa_data["id"] != cliente_id:
            st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
            st.stop()

    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa.")
    else:
        # 3. EJECUCIÓN SEGURA (Ya las fechas existen garantizadas por el sidebar)
        mostrar_interfaz_mayor(f_inicio_global, f_fin_global, db_actual)



# E. ESTADOS FINANCIEROS -> BALANCE COMPROBACIÓN
elif sub_opcion == "Balance de Comprobación":
    
    # 1. PRIMERO: Asegurar que la sesión tenga los datos del cliente activo (si 'row' viene de una selección previa)
    # Nota: Asegúrate de que 'row' esté disponible en este scope (por ejemplo, si viene de un selectbox o tibbar lateral)
    if 'row' in locals() or 'row' in globals():
        if row and 'db_nombre' in row:
            st.session_state['DB_ACTUAL'] = row['db_nombre']
            st.session_state['cliente_id'] = row['cliente_id']
            st.session_state['CLIENTE_NOMBRE'] = row.get('nombre_empresa', 'Empresa')

    # 2. SEGUNDO: Obtener los datos de sesión ya actualizados
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE', 'Empresa')
    db_actual = st.session_state.get('DB_ACTUAL')
    sucursal = st.session_state.get('SUCURSAL_SELECCIONADA', 'Todas')
    
    # RECUPERAR LAS FECHAS GLOBALES DESDE EL SESSION_STATE de forma segura
    f_inicio_global = st.session_state.get('f_inicio_global', datetime.now().date())
    f_fin_global = st.session_state.get('f_fin_global', datetime.now().date())
    
    # 3. TERCERO: Validar si la base de datos existe ahora sí
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()
        
    st.subheader(f"⚖️ Balance de Comprobación: {EMPRESA}")
    
    # --- FILTROS DE FECHA ---
    col_f1, col_f2 = st.columns(2)
    f_bal_desde = col_f1.date_input("Desde", f_inicio_global, key="bal_desde")
    f_bal_hasta = col_f2.date_input("Hasta", f_fin_global, key="bal_hasta")

    # 2. CONEXIÓN EXCLUSIVA PARA EL BALANCE
    conn_temporal = conectar_db(db_actual)
    
    if conn_temporal:
        try:
            # Despertar conexión
            conn_temporal.ping(reconnect=True)
            
            # 3. Generar el reporte usando la conexión temporal
            df_bal = generar_balance_profesional(conn_temporal, f_bal_desde, f_bal_hasta, sucursal)
            
            # Validar que df_bal no sea None ni esté vacío
            if df_bal is None or not hasattr(df_bal, 'empty') or df_bal.empty:
                st.info("ℹ️ No hay datos o la función de balance retornó vacío para el rango seleccionado.")
            else:
                # Normalizar nombres de columnas por si la función externa usa mayúsculas o nombres alternativos
                renombres = {}
                if 'Código' in df_bal.columns: renombres['Código'] = 'codigo'
                if 'Plan' in df_bal.columns: renombres['Plan'] = 'nombre'
                if 'plan_cuentas' in df_bal.columns: renombres['plan_cuentas'] = 'nombre'
                if renombres:
                    df_bal = df_bal.rename(columns=renombres)

                # Asegurarnos de que las columnas requeridas existan antes de filtrar
                columnas_necesarias = ['codigo', 'nombre', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final', 'nivel']
                faltantes = [c for c in columnas_necesarias if c not in df_bal.columns]
                
                if faltantes:
                    st.error(f"❌ Error de estructura: Faltan las columnas {faltantes} en el resultado del balance.")
                else:
                    df_display = df_bal[columnas_necesarias].copy()
                    
                    # Preparar columna con sangría para la pantalla
                    df_display['Cuenta'] = df_display.apply(lambda x: f"{'    ' * (int(x['nivel'])-1)}{x['nombre']}", axis=1)
                    nombre_archivo_pdf = f"Balance_{EMPRESA}_{f_bal_hasta.strftime('%d_%m_%Y')}.pdf"

                    # --- VISUALIZACIÓN EN DATAFRAME ---
                    st.dataframe(
                        df_display.style.format({
                            'Saldo Inicial': formato_contable, 
                            'Debe': formato_contable, 
                            'Haber': formato_contable, 
                            'Saldo Final': formato_contable
                        }).apply(estilo_balance, axis=1),
                        column_order=['codigo', 'Cuenta', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final'],
                        use_container_width=True, height=500, hide_index=True
                    )

                    # --- OBTENER TOTALES DIRECTO DE LA FILA Σ ---
                    fila_sigma = df_display[df_display['codigo'] == 'Σ']

                    # Inicializamos y extraemos de forma segura para pantalla y PDF
                    if not fila_sigma.empty:
                        t = fila_sigma.iloc[0]
                        t_inicial = float(t['Saldo Inicial'])
                        t_debe = float(t['Debe'])
                        t_haber = float(t['Haber'])
                        t_final = float(t['Saldo Final'])
                    else:
                        t_inicial = t_debe = t_haber = t_final = 0.0

                    # --- VISUALIZACIÓN DEL RESUMEN PATRIMONIAL ---
                    st.markdown("### 📊 Resumen Patrimonial")

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Saldo Inicial", formato_contable(t_inicial))
                    c2.metric("Total Debe", formato_contable(t_debe))
                    c3.metric("Total Haber", formato_contable(t_haber))
                    c4.metric("Saldo Final", formato_contable(t_final))

                    # Mensaje de cuadre
                    if abs(abs(t_debe) - abs(t_haber)) < 0.01:
                        st.success("✅ La ecuación patrimonial está balanceada.")
                    else:
                        diferencia = t_debe - t_haber
                        st.error(f"❌ Descuadre detectado: {formato_contable(diferencia)}")

                    # --- BOTONES DE EXPORTACIÓN ---
                    st.divider()
                    col_btn1, col_btn2 = st.columns(2)

                    # 1. EXCEL
                    columnas_excel = {
                        'codigo': 'Código',
                        'nombre': 'Cuenta',
                        'Saldo Inicial': 'Saldo Inicial',
                        'Debe': 'Debe',
                        'Haber': 'Haber',
                        'Saldo Final': 'Saldo Final'
                    }
                    df_excel = df_bal[list(columnas_excel.keys())].copy()
                    df_excel = df_excel.rename(columns=columnas_excel)

                    output_ex = io.BytesIO()
                    with pd.ExcelWriter(output_ex, engine='xlsxwriter') as writer:
                        df_excel.to_excel(writer, index=False, sheet_name='Balance')
                        workbook  = writer.book
                        worksheet = writer.sheets['Balance']
                        format_num = workbook.add_format({'num_format': '#,##0.00'})
                        
                        worksheet.set_column('B:B', 40)
                        worksheet.set_column('C:F', 18, format_num)

                    col_btn1.download_button(
                        label="📥 Descargar Excel Limpio",
                        data=output_ex.getvalue(),
                        file_name=f"Balance_{EMPRESA}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                    # 2. PDF PROFESIONAL
                    if col_btn2.button("📄 Generar PDF Profesional", use_container_width=True, type="primary"):
                        try:
                            from fpdf import FPDF
                            
                            class PDF(FPDF):
                                def header(self):
                                    self.set_font('Arial', 'B', 10)
                                    self.cell(100, 5, f"{EMPRESA}", ln=0)
                                    self.set_font('Arial', '', 8)
                                    self.cell(0, 5, f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='R')
                                    self.ln(10)
                                    self.set_font('Arial', 'B', 12)
                                    self.cell(0, 5, "Balance de Comprobación", ln=1, align='C')
                                    self.set_font('Arial', '', 9)
                                    self.cell(0, 5, f"Periodo: {f_bal_desde.strftime('%d/%m/%Y')} al {f_bal_hasta.strftime('%d/%m/%Y')}", ln=1, align='C')
                                    self.ln(5)
                                    # Encabezados de tabla
                                    self.set_fill_color(230, 230, 230)
                                    self.set_font('Arial', 'B', 8)
                                    self.cell(25, 7, " Código", 1, 0, 'L', True)
                                    self.cell(70, 7, " Descripción", 1, 0, 'L', True)
                                    self.cell(24, 7, "S. Inicial", 1, 0, 'C', True)
                                    self.cell(24, 7, "Debe", 1, 0, 'C', True)
                                    self.cell(24, 7, "Haber", 1, 0, 'C', True)
                                    self.cell(24, 7, "S. Final", 1, 1, 'C', True)

                            pdf = PDF()
                            pdf.add_page()
                            for _, row in df_display.iterrows():
                                pdf.set_font("Arial", 'B' if row['nivel'] <= 2 else '', 7)
                                indent = "  " * (int(row['nivel']) - 1)
                                pdf.cell(25, 6, str(row['codigo']), 1)
                                pdf.cell(70, 6, f"{indent}{row['nombre']}"[:45], 1)
                                pdf.cell(24, 6, f"{row['Saldo Inicial']:,.2f}", 1, 0, 'R')
                                pdf.cell(24, 6, f"{row['Debe']:,.2f}", 1, 0, 'R')
                                pdf.cell(24, 6, f"{row['Haber']:,.2f}", 1, 0, 'R')
                                pdf.cell(24, 6, f"{row['Saldo Final']:,.2f}", 1, 1, 'R')

                            # Totales finales en el PDF
                            pdf.set_fill_color(0, 0, 0)
                            pdf.set_text_color(255, 255, 255)
                            pdf.set_font("Arial", 'B', 8)
                            pdf.cell(95, 8, "TOTALES GENERALES (NETO)", 1, 0, 'R', True)
                            pdf.cell(24, 8, f"{t_inicial:,.2f}", 1, 0, 'R', True)
                            pdf.cell(24, 8, f"{t_debe:,.2f}", 1, 0, 'R', True)
                            pdf.cell(24, 8, f"{t_haber:,.2f}", 1, 0, 'R', True)
                            pdf.cell(24, 8, f"{t_final:,.2f}", 1, 1, 'R', True)

                            pdf_bytes = pdf.output(dest='S').encode('latin-1')
                            st.download_button(
                                label="⬇️ Descargar PDF Ahora", 
                                data=pdf_bytes, 
                                file_name=nombre_archivo_pdf, 
                                mime="application/pdf", 
                                use_container_width=True
                            )
                        except Exception as e_pdf:
                            st.error(f"Error generando PDF: {e_pdf}")

        except Exception as e:
            st.error(f"Error procesando balance: {e}")
            
        finally:
            if conn_temporal:
                try:
                    conn_temporal.close()
                except Exception:
                    pass
    else:
        st.error("No se pudo establecer la conexión para el reporte.")



# F. ESTADOS FINANCIEROS -> BALANCE GENERAL
elif sub_opcion == "Balance General":
    # 1. Obtener datos de sesión
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE')
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')
    sucursal = st.session_state.get('SUCURSAL_ACTUAL', 'Todas')

    # 2. VALIDACIÓN DE SEGURIDAD
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()

    # Obtenemos los datos de la empresa
    empresa_data = obtener_datos_agente_db(db_actual)

    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        st.stop()

    # Filtro de acceso por rol
    if rol != 'admin':
        if empresa_data.get('id') != cliente_id:
            st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
            st.stop()

    # 3. INTERFAZ Y PROCESAMIENTO
    st.subheader(f"📊 Balance General: {empresa_data.get('nombre', EMPRESA)}")
    
    # --- BLINDAJE LOCAL DE FECHA (Evita conflictos con 'from datetime import datetime') ---
    from datetime import date as d_type, datetime as dt_type

    fecha_inicial_input = d_type.today()
    val_global = st.session_state.get('f_fin_global')
    
    if val_global is not None:
        try:
            if hasattr(val_global, 'year') and hasattr(val_global, 'month'):
                fecha_inicial_input = val_global
            elif isinstance(val_global, str):
                fecha_inicial_input = dt_type.strptime(val_global, "%Y-%m-%d").date()
        except Exception:
            fecha_inicial_input = d_type.today()

    f_corte = st.date_input("Fecha de Corte", value=fecha_inicial_input, key="bg_corte")
    
    # --- CONEXIÓN TEMPORAL BLINDADA ---
    conn_temporal = conectar_db(db_actual)
    
    if conn_temporal:
        try:
            conn_temporal.ping(reconnect=True)
            
            # Generar datos
            # 1. Generar datos desde el inicio hasta el corte
            df_datos = generar_balance_profesional(conn_temporal, "2000-01-01", f_corte, sucursal)
            
            if not df_datos.empty:
                # 1. Preparación y Agrupación inicial de los datos
                df_bg = df_datos[df_datos['codigo'].astype(str).str.startswith(('1', '2', '3'))].copy()
                df_bg = df_bg.groupby(['codigo', 'nombre', 'nivel'])['Saldo Final'].sum().reset_index()
                
                # Creamos la columna 'Cuenta' con sangría visual para el reporte
                df_bg['Cuenta'] = df_bg.apply(lambda x: f"{'    ' * (int(x['nivel'])-1)}{x['nombre']}", axis=1)

                # 2. Lógica para identificar cuentas finales (hojas) y obtener totales reales
                todos_los_codigos = df_bg['codigo'].astype(str).unique()
                
                def es_hoja(codigo):
                    # Es hoja si ningún otro código del DF empieza por el código actual + punto
                    return not any(c.startswith(str(codigo) + '.') for c in todos_los_codigos)

                df_bg['es_hoja'] = df_bg['codigo'].apply(es_hoja)

                # 3. Cálculo de Totales (usando solo las cuentas hoja y valor absoluto)
                # Esto evita la duplicación al sumar padres e hijos
                act = df_bg[df_bg['es_hoja'] & df_bg['codigo'].astype(str).str.startswith('1')]['Saldo Final'].abs().sum()
                pas = df_bg[df_bg['es_hoja'] & df_bg['codigo'].astype(str).str.startswith('2')]['Saldo Final'].abs().sum()
                pat = df_bg[df_bg['es_hoja'] & df_bg['codigo'].astype(str).str.startswith('3')]['Saldo Final'].abs().sum()

                # 4. Renderizado del Reporte
                st.dataframe(
                    df_bg.style.format({'Saldo Final': formato_contable}).apply(estilo_balance, axis=1),
                    column_order=['codigo', 'Cuenta', 'Saldo Final'],
                    width='stretch', height=500, hide_index=True
                )
                
                # 5. Obtención de utilidad y cierre de balance
                utilidad_ejercicio = st.session_state.get('utilidad_ejercicio', 0.0)
                patrimonio_total = pat + utilidad_ejercicio
                

                if utilidad_ejercicio == 0.0:
                    st.sidebar.warning("⚠️ Nota: La utilidad del ejercicio no está cargada. El balance podría mostrar descuadre.")
                
                # Ecuación ajustada para visualización: Patrimonio + Utilidad
                patrimonio_ajustado = abs(pat) + utilidad_ejercicio
                descuadre = act - (abs(pas) + patrimonio_ajustado)
                
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("ACTIVOS", formato_contable(act))
                c2.metric("PASIVOS", formato_contable(abs(pas)))
                # Mostramos el patrimonio ajustado
                c3.metric("PATRIMONIO + UTILIDAD", formato_contable(patrimonio_ajustado))
                
                # VALIDACIÓN INTELIGENTE
                st.subheader("Estado de Validación")
                if abs(descuadre) < 100: # Margen por redondeos
                    st.success("✅ ¡Balance Cuadrado!")
                else:
                    st.error(f"❌ Descuadre contable detectado: {formato_contable(descuadre)}")

                # --- ÁREA DE DESCARGAS (Excel/PDF) ---
                # ÁREA DE DESCARGAS
                st.write("### 📥 Exportar Reporte")
                col_ex, col_pdf = st.columns(2)

                # --- EXCEL ---
                output_bg = io.BytesIO()
                with pd.ExcelWriter(output_bg, engine='xlsxwriter') as writer:
                    df_bg.to_excel(writer, index=False, sheet_name='Balance_General')
                
                col_ex.download_button(
                    label="📥 Descargar Excel",
                    data=output_bg.getvalue(),
                    file_name=f"Balance_General_{EMPRESA}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width='stretch'
                )

                # --- PDF ---
                if col_pdf.button("📄 Generar PDF Profesional", width='stretch', type="primary"):
                    try:
                        from fpdf import FPDF
                        from datetime import datetime

                        class PDF(FPDF):
                            def header(self):
                                self.set_font('Arial', 'B', 10)
                                self.cell(100, 5, f"{EMPRESA}", ln=0)
                                self.set_font('Arial', '', 8)
                                self.cell(0, 5, f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='R')
                                self.ln(10)
                                self.set_font('Arial', 'B', 12)
                                self.cell(0, 5, "BALANCE GENERAL", ln=1, align='C')
                                self.set_font('Arial', '', 9)
                                self.cell(0, 5, f"Al Corte: {f_corte.strftime('%d/%m/%Y')}", ln=1, align='C')
                                self.ln(5)
                                self.set_fill_color(230, 230, 230)
                                self.set_font('Arial', 'B', 9)
                                self.cell(30, 8, " Código", 1, 0, 'L', True)
                                self.cell(110, 8, " Cuenta / Descripción", 1, 0, 'L', True)
                                self.cell(50, 8, "Monto (Bs.)", 1, 1, 'C', True)

                        pdf = PDF()
                        pdf.add_page()
                        for _, row in df_bg.iterrows():
                            pdf.set_font("Arial", 'B' if row['nivel'] <= 2 else '', 8)
                            indent = "  " * (int(row['nivel']) - 1)
                            pdf.cell(30, 7, str(row['codigo']), 1)
                            pdf.cell(110, 7, f"{indent}{row['nombre']}"[:60], 1)
                            pdf.cell(50, 7, f"{abs(row['Saldo Final']):,.2f}", 1, 1, 'R')

                        # Franja de validación en PDF
                        pdf.set_fill_color(0, 0, 0)
                        pdf.set_text_color(255, 255, 255)
                        pdf.set_font("Arial", 'B', 9)
                        total_verificacion = act - (abs(pas) + abs(pat))
                        pdf.cell(140, 10, "TOTAL ECUACIÓN PATRIMONIAL (ACT - PAS - PAT)", 1, 0, 'R', True)
                        pdf.cell(50, 10, f"{total_verificacion:,.2f}", 1, 1, 'R', True)

                        pdf_bytes = pdf.output(dest='S').encode('latin-1')
                        st.download_button(
                            label="⬇️ Descargar PDF Ahora",
                            data=pdf_bytes,
                            file_name=f"Balance_General_{EMPRESA}.pdf",
                            mime="application/pdf",
                            width='stretch'
                        )
                    except Exception as e_pdf:
                        st.error(f"Error al generar el PDF: {e_pdf}")

                # VALIDACIÓN EN PANTALLA
                if abs(act - (abs(pas) + abs(pat))) < 0.01:
                    st.success("✅ Ecuación Patrimonial Cuadrada")
                else:
                    st.error(f"❌ Ecuación Patrimonial Descuadrada: {formato_contable(act - (abs(pas) + abs(pat)))}")
            else:
                st.info("No se encontraron datos para generar el balance.")

        except Exception as e:
            st.error(f"Error procesando el Balance General: {e}")
        finally:
            if conn_temporal:
                try:
                    conn_temporal.close()
                except Exception:
                    pass
    else:
        st.error("No se pudo conectar a la base de datos del cliente.")


# G. ESTADOS FINANCIEROS -> ESTADO DE RESULTADOS
elif sub_opcion == "Estado de Resultados":
    # 1. OBTENCIÓN DE DATOS DE SESIÓN Y SEGURIDAD
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE')
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')
    sucursal = st.session_state.get('SUCURSAL_ACTUAL', 'Todas')

    # 2. VALIDACIÓN DE SEGURIDAD
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()

    empresa_data = obtener_datos_agente_db(db_actual)
    
    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        st.stop()

    # Bloqueo de acceso por rol
    if rol != 'admin' and empresa_data.get('id') != cliente_id:
        st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
        st.stop()

    # 3. INTERFAZ DEL REPORTE
    st.subheader(f"📈 Estado de Resultados: {EMPRESA}")
    
    # --- BLINDAJE LOCAL DE FECHAS (Evita conflicto con from datetime import datetime) ---
    from datetime import date as d_type, datetime as dt_type

    def obtener_fecha_segura(key_sesion):
        val = st.session_state.get(key_sesion)
        if val is not None:
            try:
                if hasattr(val, 'year') and hasattr(val, 'month'):
                    return val
                elif isinstance(val, str):
                    return dt_type.strptime(val, "%Y-%m-%d").date()
            except Exception:
                pass
        return d_type.today()

    col_f1, col_f2 = st.columns(2)
    f_er_desde = col_f1.date_input("Desde", obtener_fecha_segura('f_inicio_global'), key="er_desde")
    f_er_hasta = col_f2.date_input("Hasta", obtener_fecha_segura('f_fin_global'), key="er_hasta")
    
    # 4. CONEXIÓN Y PROCESAMIENTO
    conn_er = conectar_db(db_actual)
    
    if conn_er:
        try:
            conn_er.ping(reconnect=True)
            df_datos = generar_balance_profesional(conn_er, f_er_desde, f_er_hasta, sucursal)
            
            if not df_datos.empty:
                # 1. Filtramos cuentas de resultados (4 al 8)
                df_er = df_datos[df_datos['codigo'].astype(str).str.startswith(('4', '5', '6', '7', '8'))].copy()
                df_er['Cuenta'] = df_er.apply(lambda x: f"{'    ' * (int(x['nivel'])-1)}{x['nombre']}", axis=1)
                
                # 2. RENDERIZADO EN PANTALLA
                st.dataframe(
                    df_er.style.format({'Saldo Final': formato_contable}).apply(estilo_balance, axis=1),
                    column_order=['codigo', 'Cuenta', 'Saldo Final'],
                    width='stretch', 
                    height=400, 
                    hide_index=True
                )
                
                # 3. CÁLCULO DE UTILIDAD (Usando Nivel 1)
                df_n1 = df_er[df_er['nivel'] == 1]
                ing = df_n1[df_n1['codigo'].astype(str).str.startswith('4')]['Saldo Final'].sum()
                cos = df_n1[df_n1['codigo'].astype(str).str.startswith('5')]['Saldo Final'].sum()
                gas = df_n1[df_n1['codigo'].astype(str).str.startswith('6')]['Saldo Final'].sum()
                # Utilidad = Ingresos (abs porque suelen ser acreedores) - Costos - Gastos
                utilidad = abs(ing) - (abs(cos) + abs(gas))
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("Ingresos Totales", f"Bs. {ing:,.2f}")

                with col2:
                    st.metric("Costos Totales", f"Bs. {cos:,.2f}") # <--- AQUÍ LA NUEVA MÉTRICA

                with col3:
                    st.metric("Utilidad / Pérdida", f"Bs. {formato_contable(utilidad)}", 
                          delta=f"{formato_contable(utilidad)}",
                          delta_color="normal" if utilidad >= 0 else "inverse")


                # 1. GESTIÓN DE TASA BCV
                if 'tasa_bcv' not in st.session_state:
                    tasa, _ = obtener_tasa_bcv_hoy(conn_er) # Cambiado a conn_er
                    st.session_state.tasa_bcv = tasa

                if st.button("🔄 Actualizar Tasa BCV"):
                    tasa, _ = obtener_tasa_bcv_hoy(conn_er) # Cambiado a conn_er
                    st.session_state.tasa_bcv = tasa
                    st.rerun()

                tasa = st.session_state.tasa_bcv if st.session_state.tasa_bcv > 0 else 1.0

                # 2. CÁLCULO UNIFICADO (Usando df_er, la misma fuente que tu tabla)
                # Asegúrate de que df_er sea la variable que contiene tu reporte completo
                if 'df_er' in locals() and not df_er.empty:
                    df_n1 = df_er[df_er['nivel'] == 1]
                    
                    # Cálculos en Bolívares
                    ing = df_n1[df_n1['codigo'].astype(str).str.startswith('4')]['Saldo Final'].sum()
                    cos = df_n1[df_n1['codigo'].astype(str).str.startswith('5')]['Saldo Final'].sum()
                    gas = df_n1[df_n1['codigo'].astype(str).str.startswith('6')]['Saldo Final'].sum()
                    utilidad = abs(ing) - (abs(cos) + abs(gas))
                    
                    # Cálculos en USD
                    ing_usd, cos_usd, gas_usd, util_usd = [x / tasa for x in [abs(ing), abs(cos), abs(gas), utilidad]]
                    costos_gastos_usd = cos_usd + gas_usd
                else:
                    # Si df_er no existe aquí, significa que el cálculo debe ir DENTRO del bloque que genera el reporte
                    st.warning("El reporte principal aún no se ha generado.")
                    ing, cos, gas, utilidad, ing_usd, costos_gastos_usd, util_usd = [0.0]*7

                # 3. VISUALIZACIÓN
                c1, c2, c3 = st.columns(3)

                with c1:
                    st.metric("Ingresos (USD)", f"$ {formato_contable(ing_usd)}")

                with c2:
                    st.metric("Costos/Gastos (USD)", f"$ {formato_contable(costos_gastos_usd)}")

                with c3:
                    st.metric("Utilidad (USD)", f"$ {formato_contable(util_usd)}", 
                              delta=f"{formato_contable(util_usd)} USD",
                              delta_color="normal" if utilidad >= 0 else "inverse")

                # Contenedor estético para la Tasa BCV
                with st.container():
                    st.markdown(
                        f"""
                        <div style="
                            background-color: #f0f2f6; 
                            padding: 10px; 
                            border-radius: 10px; 
                            border-left: 5px solid #0081C9;
                            max-width: 300px;  /* <--- ESTA ES LA CLAVE */ 
                            display: flex; 
                            justify-content: space-between; 
                            align-items: center;
                        ">
                            <span style="color: #31333F; font-weight: bold; font-size: 14px;">
                                🔄 Tasa de Referencia BCV
                            </span>
                            <span style="color: #0081C9; font-weight: 900; font-size: 16px;">
                                {tasa:,.2f} <span style="font-size: 12px; color: #808495;">Bs/USD</span>
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                
                st.divider()

                # 4. ÁREA DE EXPORTACIÓN
                st.write("### 📥 Exportar Reporte")
                col_ex, col_pdf = st.columns(2)

                # --- EXCEL ---
                output_er = io.BytesIO()
                with pd.ExcelWriter(output_er, engine='xlsxwriter') as writer:
                    df_er.to_excel(writer, index=False, sheet_name='Estado_Resultados')
                
                col_ex.download_button(
                    label="📥 Descargar Excel",
                    data=output_er.getvalue(),
                    file_name=f"Estado_Resultados_{EMPRESA}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width='stretch'
                )

                # --- PDF ---
                if col_pdf.button("📄 Generar PDF Profesional", width='stretch', type="primary"):
                    try:
                        from fpdf import FPDF
                        from datetime import datetime

                        class PDF(FPDF):
                            def header(self):
                                self.set_font('Arial', 'B', 10)
                                self.cell(100, 5, f"{EMPRESA}", ln=0)
                                self.set_font('Arial', '', 8)
                                self.cell(0, 5, f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align='R')
                                self.ln(10)
                                self.set_font('Arial', 'B', 12)
                                self.cell(0, 5, "ESTADO DE RESULTADOS", ln=1, align='C')
                                self.set_font('Arial', '', 9)
                                self.cell(0, 5, f"Periodo: {f_er_desde.strftime('%d/%m/%Y')} al {f_er_hasta.strftime('%d/%m/%Y')}", ln=1, align='C')
                                self.ln(5)
                                self.set_fill_color(230, 230, 230)
                                self.set_font('Arial', 'B', 9)
                                self.cell(30, 8, " Código", 1, 0, 'L', True)
                                self.cell(110, 8, " Cuenta / Descripción", 1, 0, 'L', True)
                                self.cell(50, 8, "Monto (Bs.)", 1, 1, 'C', True)

                        pdf = PDF()
                        pdf.add_page()
                        for _, row in df_er.iterrows():
                            pdf.set_font("Arial", 'B' if row['nivel'] <= 2 else '', 8)
                            indent = "  " * (int(row['nivel']) - 1)
                            pdf.cell(30, 7, str(row['codigo']), 1)
                            pdf.cell(110, 7, f"{indent}{row['nombre']}"[:60], 1)
                            pdf.cell(50, 7, f"{abs(row['Saldo Final']):,.2f}", 1, 1, 'R')

                        # TOTALES EN PDF
                        pdf.set_fill_color(0, 0, 0)
                        pdf.set_text_color(255, 255, 255)
                        pdf.set_font("Arial", 'B', 10)
                        texto_res = "UTILIDAD NETA DEL EJERCICIO" if utilidad >= 0 else "PÉRDIDA NETA DEL EJERCICIO"
                        pdf.cell(140, 10, texto_res, 1, 0, 'R', True)
                        pdf.cell(50, 10, f"{utilidad:,.2f}", 1, 1, 'R', True)

                        pdf_bytes = pdf.output(dest='S').encode('latin-1')
                        st.download_button(
                            label="⬇️ Descargar PDF Ahora",
                            data=pdf_bytes,
                            file_name=f"Estado_Resultados_{EMPRESA}.pdf",
                            mime="application/pdf",
                            width='stretch'
                        )
                    except Exception as e_pdf:
                        st.error(f"Error PDF: {e_pdf}")

            else:
                st.info("No se encontraron movimientos de resultados en este periodo.")

        
        except Exception as e:
            st.error(f"Error en Estado de Resultados: {e}")
        finally:
            if conn_er:
                try:
                    conn_er.close()
                except Exception:
                    pass
    else:
        st.error("Error al conectar con la base de datos.")

# F. LIBROS FISCALES
# --- B. MÓDULO DE LIBROS FISCALES (CARGA Y CONSULTA UNIFICADA) ---

elif opcion_menu == "📚 Libros Fiscales":
    st.markdown(f"## 📚 Libros Fiscales: {EMPRESA}")

        # --- LÓGICA DEL LIBRO DE VENTAS (INDENTADO CORRECTAMENTE) ---
    if sub_opcion == "Libro de Ventas":
        # 0. Validación inicial
        db_actual = st.session_state.get('DB_ACTUAL')
        if not db_actual or db_actual == 'none':
            st.warning("⚠️ Selecciona una empresa en el menú lateral.")
            st.stop()
            
        # --- INICIALIZACIÓN DE ESTADO ---
        if 'active_tab' not in st.session_state:
            st.session_state.active_tab = "🔍 Consultar y Editar"

        # --- ESTRUCTURA DE TABS ---
        tab_titles = ["📊 Cargar desde Excel", "🔍 Consultar y Editar", "🚨 Vaciado de Rango"]
        
        # Mapeamos los índices para asegurar que la pestaña activa se mantenga
        tab1, tab2, tab3 = st.tabs(tab_titles)


        # --- EN TU PESTAÑA 1 ---
        with tab1:
            st.subheader("📊 Cargar desde Excel")
            with st.expander("📥 Importar Libro de Ventas desde Excel", expanded=True):
                # 1. Definimos el archivo
                archivo_v = st.file_uploader("Seleccionar archivo Excel", type=['xlsx'], key="v_up_directo")
                
                # 2. PROCESAMOS SOLO SI HAY ARCHIVO
                if archivo_v:
                    # Leemos el archivo
                    df_preview = pd.read_excel(archivo_v, header=0)

                    # 3. RENOMBRAMOS las columnas para que coincidan con tu base de datos
                    df_preview = df_preview.rename(columns={
                        "Fecha de Factura": "fecha_factura",
                        "Nombre y Apellido o Razón Social": "nombre_razon_social",
                        "R.I.F.": "rif",
                        "Número de Factura": "n_factura",
                        "Num. Control de": "n_control",
                        "Total Ventas Incluyendo el IVA": "total_ventas_con_iva",
                        "Ventas Exentas": "ventas_exentas",
                        "Base Imponible": "base_imponible",
                        "% Alícuota": "porcentaje_alicuota",
                        "Débito Fiscal": "debito_fiscal"
                    })

                    # 4. CORRECCIÓN DE FECHA (Formato YYYY-MM-DD)
                    if 'fecha_factura' in df_preview.columns:
                        df_preview['fecha_factura'] = pd.to_datetime(df_preview['fecha_factura'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('2026-06-13')
                    column_config = {
                        "fecha_factura": st.column_config.TextColumn("fecha_factura")
                    }
                    # 5. UNICO EDITOR
                    resultado = st.data_editor(df_preview, key=f"editor_{archivo_v.name}", width='stretch',column_config=column_config)
                    
                    st.markdown("### 📊 Totales")
                    def f_bs(v): return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                    # 6. Cálculo y limpieza
                    cols_a_sumar = ['total_ventas_con_iva', 'ventas_exentas', 'base_imponible', 'debito_fiscal']
                    df_limpio = resultado.copy()
                    
                    # Verificamos qué columnas llegaron realmente
                    for col in cols_a_sumar:
                        if col in df_limpio.columns:
                            df_limpio[col] = pd.to_numeric(df_limpio[col], errors='coerce').fillna(0.0)
                        else:
                            # Si la columna no existe, la creamos con 0 para que no falle el .sum()
                            df_limpio[col] = 0.0
                            st.warning(f"⚠️ La columna esperada '{col}' no se encontró en el archivo. Verifique el encabezado del Excel.")

                    # 7. Métricas (ahora son seguras)
                    t1, t2, t3, t4 = st.columns(4)
                    t1.metric("Total Ventas", f_bs(df_limpio['total_ventas_con_iva'].sum()))
                    t2.metric("Ventas Exentas", f_bs(df_limpio['ventas_exentas'].sum()))
                    t3.metric("Total Base", f_bs(df_limpio['base_imponible'].sum()))
                    t4.metric("Débito Fiscal", f_bs(df_limpio['debito_fiscal'].sum()))
                    
                    # 8. BOTÓN PROCESAR
                    if st.button("🚀 Procesar e Importar", type="primary"):
                        with st.spinner("⏳ Procesando..."):
                            try:
                                conn_upload = conectar_db(db_actual)
                                if conn_upload:
                                    cargar_libro_ventas_db(resultado, conn_upload)
                                    conn_upload.close()
                                    st.success("✅ Archivo procesado correctamente.")
                                    st.balloons()
                            except Exception as e:
                                st.error(f"❌ Error crítico: {e}")
                    # --- PESTAÑA 2: CONSULTAR Y EDITAR ---
        with tab2:
            st.subheader("🔍 Consultar y Editar")
            
            # Filtros de búsqueda
            col_v1, col_v2, col_v3 = st.columns([1, 1, 1])
            with col_v3:
                ver_todo_v = st.checkbox("📂 Ver historial completo", key="todo_ventas")
            
            # --- BLINDAJE DE FECHAS SEGURO ---
            from datetime import date as d_tipo, datetime as dt_tipo

            def _obtener_f_segura(key_s):
                val = st.session_state.get(key_s)
                if val is not None:
                    try:
                        if hasattr(val, 'year') and hasattr(val, 'month'):
                            return val
                        elif isinstance(val, str):
                            return dt_tipo.strptime(val, "%Y-%m-%d").date()
                    except Exception:
                        pass
                return d_tipo.today()

            with col_v1:
                desde_v = st.date_input("Desde", _obtener_f_segura('f_inicio_global'), key="f_desde_v", disabled=ver_todo_v)
            with col_v2:
                hasta_v = st.date_input("Hasta", _obtener_f_segura('f_fin_global'), key="f_hasta_v", disabled=ver_todo_v)

            if st.button("📊 Consultar Ventas"):
                conn_query = conectar_db(db_actual)
                if conn_query:
                    try:
                        if ver_todo_v: 
                            query = "SELECT * FROM libro_ventas ORDER BY fecha_factura DESC"
                        else:
                            query = f"SELECT * FROM libro_ventas WHERE fecha_factura BETWEEN '{desde_v}' AND '{hasta_v}' ORDER BY fecha_factura ASC"
                        st.session_state.df_ventas_editor = ejecutar_consulta(query, conn_query)
                    finally:
                        conn_query.close()

            # Editor
            if "df_ventas_editor" in st.session_state:
                df_mostrar = st.session_state.df_ventas_editor.copy()
                
                # --- 1. TABLA DE CONSULTA (Visualización con formato contable) ---
                df_visual = df_mostrar.copy()
                cols_moneda = ['total_ventas_con_iva', 'ventas_exentas', 'base_imponible', 'debito_fiscal']
                for col in cols_moneda:
                    # Formateo visual: 1.234,56
                    df_visual[col] = df_visual[col].apply(
                        lambda x: "{:,.2f}".format(x).replace(",", "X").replace(".", ",").replace("X", ".")
                    )
                
                st.subheader("👁️ Vista de Consulta")
                st.dataframe(df_visual, width='stretch', hide_index=True)

                # --- 2. EDITOR DE REGISTROS (Edición funcional) ---
                with st.expander("✏️ Editar Registros (Edición de datos)"):
                    st.info("⚠️ Edita los números aquí (usa punto para decimales, ej: 123.45)")
                    
                    # KEY DINÁMICO para evitar el error de duplicados
                    key_editor = f"editor_ventas_{db_actual}"
                    
                    # Dentro del st.expander...
                    editado_v = st.data_editor(
                        df_mostrar,
                        key=key_editor,
                        num_rows="dynamic",
                        width='stretch',
                        hide_index=True,
                        column_config={
                            "id": st.column_config.NumberColumn("ID", disabled=True),
                            "fecha_factura": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"),
                            "nombre_razon_social": st.column_config.TextColumn("Razón Social", required=True),
                            "rif": st.column_config.TextColumn("RIF"),
                            "n_factura": st.column_config.TextColumn("Nº Factura"),
                            "n_control": st.column_config.TextColumn("Nº Control"),
                            "total_ventas_con_iva": st.column_config.NumberColumn("Total Bs.", format="%.2f"),
                            "ventas_exentas": st.column_config.NumberColumn("Exento Bs.", format="%.2f"),
                            "base_imponible": st.column_config.NumberColumn("Base Bs.", format="%.2f"),
                            "debito_fiscal": st.column_config.NumberColumn("IVA Bs.", format="%.2f"),
                            "porcentaje_alicuota": st.column_config.NumberColumn("%", format="%.1f"),
                        }
                    )

                # --- 3. IMPORTANTE: USAR EL KEY DINÁMICO PARA GUARDAR ---
                # Cuando guardes abajo, recuerda que ahora el key es key_editor
                # Ejemplo: cambios = st.session_state[key_editor]

                # --- 5. SECCIÓN DE TOTALES ---
                st.markdown("---")
                t_ventas = df_mostrar['total_ventas_con_iva'].sum()
                t_exento = df_mostrar['ventas_exentas'].sum()
                t_base = df_mostrar['base_imponible'].sum()
                t_iva = df_mostrar['debito_fiscal'].sum()

                def f_moneda(v): return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("TOTAL VENTAS", f_moneda(t_ventas))
                m2.metric("TOTAL EXENTO", f_moneda(t_exento))
                m3.metric("TOTAL BASE", f_moneda(t_base))
                m4.metric("TOTAL IVA (16%)", f_moneda(t_iva))
                
                st.markdown("---")

                # --- 6. ACCIONES: DESCARGA Y GUARDADO ---
                # --- 6. ACCIONES: DESCARGA Y GUARDADO ---
                col_btn1, col_btn2 = st.columns([1, 1])

                with col_btn1:
                    if "df_ventas_editor" in st.session_state:
                        # Papi, en vez de usar conn_query, abrimos una conexión nueva solo para la descarga
                        # Esto elimina el NameError por completo.
                        conn_temp = conectar_db(db_actual)
                        
                        try:
                            datos_excel = preparar_excel_descarga(df_mostrar, conn_temp)
                            st.download_button(
                                label="📥 Descargar Respaldo Excel",
                                data=datos_excel,
                                file_name=f"Libro_Ventas_{desde_v}_al_{hasta_v}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                width='stretch'
                            )
                        finally:
                            # Cerramos la conexión temp inmediatamente después de generar los datos
                            conn_temp.close()

                with col_btn2:
                    if st.button("💾 Guardar Cambios en Ventas", type="primary", width='stretch'):
                        # Usamos la variable key_editor correctamente
                        if key_editor in st.session_state:
                            cambios = st.session_state[key_editor]
                            conn_save = conectar_db(db_actual)
                            
                            if conn_save:
                                cursor = conn_save.cursor()
                                try:
                                    # A. Eliminar filas
                                    for row_idx in cambios.get("deleted_rows", []):
                                        id_del = int(df_mostrar.iloc[row_idx]["id"])
                                        cursor.execute("DELETE FROM libro_ventas WHERE id = %s", (id_del,))

                                    # B. Editar filas
                                    for row_idx, dict_cambios in cambios.get("edited_rows", {}).items():
                                        id_edit = int(df_mostrar.iloc[int(row_idx)]["id"])
                                        if "n_factura" in dict_cambios: dict_cambios["n_factura"] = str(dict_cambios["n_factura"]).zfill(5)
                                        if "n_control" in dict_cambios: dict_cambios["n_control"] = str(dict_cambios["n_control"]).zfill(5)
                                        if "fecha_factura" in dict_cambios and dict_cambios["fecha_factura"]:
                                            f = dict_cambios["fecha_factura"]
                                            dict_cambios["fecha_factura"] = f.strftime('%Y-%m-%d') if hasattr(f, 'strftime') else str(f)
                                        
                                        if dict_cambios:
                                            sql_upd = ", ".join([f"{k} = %s" for k in dict_cambios.keys()])
                                            cursor.execute(f"UPDATE libro_ventas SET {sql_upd} WHERE id = %s", list(dict_cambios.values()) + [id_edit])

                                    # C. Agregar nuevas filas
                                    for row_dict in cambios.get("added_rows", []):
                                        if not row_dict or not any(row_dict.values()): continue
                                        f_raw = row_dict.get("fecha_factura") or desde_v
                                        fecha_final = f_raw.strftime('%Y-%m-%d') if hasattr(f_raw, 'strftime') else str(f_raw)

                                        datos_finales = {
                                            "fecha_factura": fecha_final,
                                            "nombre_razon_social": row_dict.get("nombre_razon_social", "VARIOS"),
                                            "rif": row_dict.get("rif", "V000000000"),
                                            "n_factura": str(row_dict.get("n_factura", "0")).zfill(5),
                                            "n_control": str(row_dict.get("n_control", "0")).zfill(5),
                                            "total_ventas_con_iva": row_dict.get("total_ventas_con_iva", 0.00),
                                            "ventas_exentas": row_dict.get("ventas_exentas", 0.00),
                                            "base_imponible": row_dict.get("base_imponible", 0.00),
                                            "porcentaje_alicuota": row_dict.get("porcentaje_alicuota", 16.00),
                                            "debito_fiscal": row_dict.get("debito_fiscal", 0.00)
                                        }
                                        columnas = ", ".join(datos_finales.keys())
                                        placeholders = ", ".join(["%s"] * len(datos_finales))
                                        cursor.execute(f"INSERT INTO libro_ventas ({columnas}) VALUES ({placeholders})", list(datos_finales.values()))

                                    conn_save.commit()
                                    st.success("✅ ¡Libro de Ventas actualizado con éxito!")
                                    st.rerun()
                                except Exception as e:
                                    conn_save.rollback()
                                    st.error(f"❌ Error: {e}")
                                finally:
                                    cursor.close()  # Recomendado cerrar cursor también
                                    conn_save.close()
                        else:
                            st.warning("⚠️ No hay registro de cambios activos en la sesión.")

        # --- PESTAÑA 3: VACIADO DE RANGO ---
        with tab3:
            st.subheader("🚨 Vaciado de Rango")
            
            # 1. Definimos el rango de fechas
            col1, col2 = st.columns(2)
            with col1:
                # Quitamos el 'value=' para que el usuario elija desde cero
                fecha_inicio = st.date_input("📅 Fecha de inicio")
            with col2:
                # Quitamos el 'value='
                fecha_fin = st.date_input("📅 Fecha de fin")

            st.error("⚠️ **Atención:** El borrado masivo es irreversible.")
            
            # 2. Popover de confirmación
            with st.popover("🚨 VACIAR VENTAS (RANGO SELECCIONADO)", width='stretch'):
                st.subheader("Confirmar Borrado de Ventas")
                st.info(f"Se borrará el rango: {fecha_inicio} hasta {fecha_fin}")
                
                confirmar_v = st.checkbox("Confirmo que deseo borrar las VENTAS", key="check_borrar_ventas_key")
                
                if st.button("EJECUTAR BORRADO VENTAS", type="primary", disabled=not confirmar_v):
                    borrar_ventas_por_rango(fecha_inicio, fecha_fin)
                    st.rerun()

            st.divider()

            # 3. BLOQUE DE INSPECCIÓN: Para que salgas de dudas
            with st.expander("🕵️ Inspeccionar datos antes de borrar"):
                try:
                    db_actual = st.session_state.get('DB_ACTUAL')
                    conexion = conectar_db(db_actual)
                    cursor = conexion.cursor()
                    
                    cursor.execute("SELECT DISTINCT fecha_factura FROM libro_ventas ORDER BY fecha_factura DESC LIMIT 10")
                    fechas_existentes = cursor.fetchall()
                    
                    st.write("Las 10 fechas más recientes encontradas en tu tabla son:")
                    for f in fechas_existentes:
                        st.write(f"- {f[0]}")
                    
                    cursor.close()
                    conexion.close()
                except Exception as e:
                    st.error("No se pudieron cargar las fechas de inspección.")

    elif sub_opcion == "Libro de Compras":
        # 0. Validación inicial
        db_actual = st.session_state.get('DB_ACTUAL')
        if not db_actual or db_actual == 'none':
            st.warning("⚠️ Selecciona una empresa en el menú lateral.")
            st.stop()

        # --- CONTROL DE SESIÓN ACTIVA ---
        # Inicializamos la pestaña activa si no existe
        if 'active_tab' not in st.session_state:
            st.session_state.active_tab = "🔍 Consultar y Editar"

        # --- ESTRUCTURA DE TABS ---
        tab_titles = ["🔍 Consultar y Editar", "📸 Escaneo Inteligente", "🚨 Vaciado de Rango", "📊 Cargar desde Excel"]
        
        # Creamos las pestañas
        tabs = st.tabs(tab_titles)

        # --- LÓGICA DE PERSISTENCIA ---
        # Si el usuario hace clic en una tab, actualizamos el estado
        # Nota: Streamlit maneja el click de las tabs internamente, 
        # pero para forzar el foco, validamos el estado:
        
        tab1, tab2, tab3, tab4 = tabs

        # --- LÓGICA DE NAVEGACIÓN ---

        with tab1: # Consultar y Editar
            st.subheader("🔍 Consulta y Edición: Libro de Compras")
            
            # 1. Filtros de fecha
            col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
            with col_c3:
                ver_todo = st.checkbox("📂 Ver todo", key="todo_compras")
            
            # --- BLINDAJE DE FECHAS SEGURO ---
            from datetime import date as d_tipo, datetime as dt_tipo

            def _obtener_f_segura(key_s):
                val = st.session_state.get(key_s)
                if val is not None:
                    try:
                        if hasattr(val, 'year') and hasattr(val, 'month'):
                            return val
                        elif isinstance(val, str):
                            return dt_tipo.strptime(val, "%Y-%m-%d").date()
                    except Exception:
                        pass
                return d_tipo.today()

            with col_c1:
                desde_c = st.date_input("Desde", _obtener_f_segura('f_inicio_global'), key="desde_c", disabled=ver_todo)
            with col_c2:
                hasta_c = st.date_input("Hasta", _obtener_f_segura('f_fin_global'), key="hasta_c", disabled=ver_todo)

            st.error("⚠️ **Atención:** Las acciones aquí solo afectan al Libro de Compras.")
            # 2. CARGA AUTOMÁTICA
            try:
                conn = conectar_db(db_actual)
                query = "SELECT * FROM libro_compras ORDER BY fecha_operacion DESC" if ver_todo else \
                        "SELECT * FROM libro_compras WHERE fecha_operacion BETWEEN %s AND %s"
                params = None if ver_todo else (desde_c, hasta_c)
                
                df_recuperado = ejecutar_consulta(query, conn, params=params)
            except Exception as e:
                st.error(f"❌ Error al consultar la base de datos: {e}")
                df_recuperado = pd.DataFrame()
            finally:
                if 'conn' in locals() and conn:
                    conn.close() # Cierre garantizado para evitar fugas de memoria

            if not df_recuperado.empty:
                st.session_state.df_compras_editor = df_recuperado
            else:
                st.warning("No se encontraron registros en el rango seleccionado.")
                if "df_compras_editor" in st.session_state:
                    del st.session_state.df_compras_editor

            def formato_ve(n):
                try:
                    # Convierte 5798.38 a "5.897,58"
                    s = f"{float(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    return s
                except:
                    return "0,00"

            # 3. RENDERIZADO DEL EDITOR Y TOTALES
            if "df_compras_editor" in st.session_state:
                st.info("💡 Tip: Edita los datos directamente en la tabla.")
                
                # Editor de datos
                # --- EDITOR DE DATOS (Entrada de números puros) ---
                st.subheader("✏️ Edición de Libro de Compras")

                cambios_df = st.data_editor(
                    st.session_state.df_compras_editor,
                    key="editor_consulta_final", 
                    num_rows="dynamic",
                    width='stretch',
                    hide_index=False,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "total_compras": st.column_config.NumberColumn("Total Compras", format="%.2f"),
                        "importe_exento": st.column_config.NumberColumn("Importe Exento", format="%.2f"),
                        "base_imponible": st.column_config.NumberColumn("Base Imponible", format="%.2f"),
                        "iva_monto": st.column_config.NumberColumn("IVA Monto", format="%.2f")
                    }
                )

                st.session_state.df_compras_editor = cambios_df

                
                # --- CÁLCULO DE TOTALES ---
                st.markdown("### 📊 Totales")
                def f_bs(v): return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                
                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Total Compras", f_bs(cambios_df['total_compras'].sum()))
                t2.metric("Total Exento", f_bs(cambios_df['importe_exento'].sum()))
                t3.metric("Total Base", f_bs(cambios_df['base_imponible'].sum()))
                t4.metric("Total IVA", f_bs(cambios_df['iva_monto'].sum()))
                st.markdown("---")
                
                # BOTÓN ÚNICO DE GUARDAR
                if st.button("💾 Guardar todos los cambios en DB", type="primary", key="btn_guardar_final"):
                    db_actual = st.session_state.get('DB_ACTUAL')
                    
                    if db_actual:
                        conn = conectar_db(db_actual)
                        if conn:
                            try:
                                cursor = conn.cursor()
                                cursor.execute("DESCRIBE libro_compras")
                                columnas_db = [fila[0] for fila in cursor.fetchall()]
                                
                                # Función de limpieza necesaria
                                def limpiar_dato(val):
                                    if val is None or (isinstance(val, float) and np.isnan(val)): return None
                                    if isinstance(val, (pd.Timestamp, pd.Timedelta)): return str(val.date())
                                    if isinstance(val, (np.integer, np.int64)): return int(val)
                                    if isinstance(val, (np.floating, np.float64)): return float(val)
                                    return str(val)
                                
                                # 1. Preparar datos
                                df_a_guardar = st.session_state.df_compras_editor.dropna(how='all')
                                df_a_guardar = df_a_guardar[[c for c in df_a_guardar.columns if c in columnas_db]]
                                
                                # 2. Definir quién se actualiza y quién se inserta
                                df_update = df_a_guardar[df_a_guardar['id'].notnull()]
                                df_insert = df_a_guardar[df_a_guardar['id'].isnull()]
                                
                                cursor.execute("START TRANSACTION")
                                
                                # 3. ACTUALIZAR filas existentes (por ID)
                                if not df_update.empty:
                                    cols_update = [c for c in df_update.columns if c != 'id']
                                    set_clause = ", ".join([f"{c} = %s" for c in cols_update])
                                    query_update = f"UPDATE libro_compras SET {set_clause} WHERE id = %s"
                                    
                                    for _, row in df_update.iterrows():
                                        # Aquí aplicamos limpiar_dato a cada campo
                                        valores = [limpiar_dato(row[c]) for c in cols_update] + [int(row['id'])]
                                        cursor.execute(query_update, tuple(valores))

                                # 4. INSERTAR filas nuevas
                                if not df_insert.empty:
                                    df_insert_final = df_insert.drop(columns=['id'])
                                    cols_insert = ", ".join(df_insert_final.columns)
                                    placeholders = ", ".join(["%s"] * len(df_insert_final.columns))
                                    query_insert = f"INSERT INTO libro_compras ({cols_insert}) VALUES ({placeholders})"
                                    
                                    # Aplicamos limpiar_dato a todos los datos de inserción
                                    datos_nuevos = [tuple(limpiar_dato(x) for x in row) for _, row in df_insert_final.iterrows()]
                                    cursor.executemany(query_insert, datos_nuevos)
                                
                                conn.commit()
                                st.balloons()
                                st.success("✅ ¡Cambios sincronizados correctamente con MySQL!")
                                st.rerun() # <--- Añade esto para refrescar los datos recién guardados
                                
                            except Exception as e:
                                if conn: conn.rollback()
                                st.error(f"❌ Error al guardar en MySQL: {e}")
                            finally:
                                cursor.close()
                                conn.close()
                                
        with tab2: # Escaneo Inteligente
            st.subheader("📸 Escaneo Inteligente (OCR)")
            archivo = st.file_uploader("Sube factura", type=['jpg', 'png', 'jpeg'], key="uploader_factura")
            
            # Inicializar el buffer
            if "df_buffer_escaneo" not in st.session_state:
                st.session_state.df_buffer_escaneo = pd.DataFrame()

            if archivo:
                st.divider()
                
                # --- BLOQUE 1: PROCESAMIENTO INDIVIDUAL ---
                if st.button("Procesar Factura (Individual)", key="btn_procesar_individual"):
                    with st.spinner('La IA está analizando la factura...'):
                        exito = False
                        intentos = 0
                        resultados = None
                        
                        while intentos < 3 and not exito:
                            try:
                                print("Iniciando procesamiento de factura...")
                                resultados = extraer_datos_factura(archivo)
                                exito = True
                                
                            except Exception as e:
                                error_str = str(e)
                                if "429" in error_str:
                                    intentos += 1
                                    st.warning(f"⚠️ Límite de cuota, reintentando en 15s... (Intento {intentos}/3)")
                                    time.sleep(15)
                                else:
                                    st.error(f"❌ Error crítico durante el análisis: {error_str}")
                                    break
                        
                        if resultados:
                            nueva_fila = pd.DataFrame([resultados])
                            
                            # --- LIMPIEZA ---
                            for col in ['n_factura', 'n_control']:
                                if col in nueva_fila.columns:
                                    nueva_fila[col] = nueva_fila[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                                    nueva_fila[col] = nueva_fila[col].replace(['nan', 'None', '', 'null'], 'SIN_NUMERO' if col == 'n_factura' else 'SIN_CONTROL')
                                else:
                                    nueva_fila[col] = 'SIN_NUMERO' if col == 'n_factura' else 'SIN_CONTROL'
                            
                            nueva_fila['Seleccionar Proveedor'] = ""
                            if 'proveedor' in nueva_fila.columns:
                                nueva_fila = nueva_fila.drop(columns=['proveedor'])
                            
                            if 'df_buffer_escaneo' not in st.session_state:
                                st.session_state.df_buffer_escaneo = pd.DataFrame()
                            
                            st.session_state.df_buffer_escaneo = pd.concat([st.session_state.df_buffer_escaneo, nueva_fila], ignore_index=True)
                            st.success("✅ Factura agregada al buffer.")
                            
                        elif not exito:
                            st.error("No se pudo obtener respuesta de la IA tras varios intentos.")
                        else:
                            st.error("La IA devolvió un resultado vacío.")

            # --- ÁREA DE EDICIÓN Y REVISIÓN ---
        if not st.session_state.df_buffer_escaneo.empty:
            st.info(f"💡 Revisando {len(st.session_state.df_buffer_escaneo)} facturas en espera.")
            
            # 1. FORZAR ESTRUCTURA
            df_a_editar = st.session_state.df_buffer_escaneo.copy()
            
            if "Seleccionar Proveedor" not in df_a_editar.columns:
                df_a_editar["Seleccionar Proveedor"] = ""
            
            for col in ["n_factura", "n_control"]:
                if col not in df_a_editar.columns:
                    df_a_editar[col] = "SIN_VALOR"
                else:
                    # Convertimos a string y normalizamos vacíos
                    df_a_editar[col] = df_a_editar[col].astype(str).replace(['nan', 'None', '', 'nan'], 'SIN_VALOR')

            # 2. Dibujamos el editor con configuración explícita
            lista_proveedores = obtener_lista_proveedores()
            
            buffer_editado = st.data_editor(
                df_a_editar,
                column_config={
                    "Seleccionar Proveedor": st.column_config.SelectboxColumn(
                        "Seleccionar Proveedor",
                        help="Selecciona el proveedor de la lista",
                        options=lista_proveedores,
                        required=True,
                    ),
                    "n_factura": st.column_config.TextColumn("Nº Factura", required=True),
                    "n_control": st.column_config.TextColumn("Nº Control", required=True),
                },
                key="editor_buffer_ocr",
                num_rows="dynamic",
                width='stretch'
            )
            
            # Actualizamos el estado con lo que el usuario editó
            st.session_state.df_buffer_escaneo = buffer_editado

            # 3. Acción de guardado en DB
            if st.button("🚀 Guardar en DB", type="primary"):
                df_final = st.session_state.df_buffer_escaneo.copy()
                
                # VALIDACIÓN FINAL: Asegurar que los datos limpios se envíen a la base de datos
                df_final['n_factura'] = df_final['n_factura'].replace(['', 'None', 'nan', 'SIN_VALOR'], 'SIN_NUMERO')
                df_final['n_control'] = df_final['n_control'].replace(['', 'None', 'nan', 'SIN_VALOR'], 'SIN_CONTROL')
                
                # Aquí continúa tu lógica de mapeo y to_sql
                try:
                    # ... tu código de conexión y guardado ...
                    st.success(f"✅ Se procesaron {len(df_final)} filas correctamente.")
                    # st.session_state.df_buffer_escaneo = pd.DataFrame() # Opcional: limpiar al guardar
                    # st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

                # Columnas para acciones finales
                col_b1, col_b2 = st.columns(2)
                
                with col_b1:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        st.session_state.df_buffer_escaneo.to_excel(writer, index=False, sheet_name='Buffer_OCR')
                    
                    st.download_button(
                        label="📥 Descargar Buffer a Excel",
                        data=output.getvalue(),
                        file_name=f"Backup_OCR_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width='stretch'
                    )

                with col_b2:
                    if st.button("🚀 Guardar TODAS en DB (Modo Seguro)", type="primary"):
                        # 1. Validación inicial
                        if st.session_state.df_buffer_escaneo['Seleccionar Proveedor'].isin(['', None]).any():
                            st.warning("⚠️ ¡Faltan proveedores por seleccionar!")
                        else:
                            df_a_procesar = st.session_state.df_buffer_escaneo.copy()
                            
                            # --- PREPARACIÓN PREVIA ---
                            dict_proveedores = obtener_lista_proveedores_mapeo()
                            dict_nombre_por_rif = {v: k for k, v in dict_proveedores.items()}
                            
                            # Crear engine UNA SOLA VEZ fuera del bucle
                            engine = create_engine(f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}/{db_actual}")
                            
                            # Asegurar columnas obligatorias
                            for col in ['n_factura', 'n_control']:
                                if col not in df_a_procesar.columns:
                                    df_a_procesar[col] = 'SIN_DATOS'
                                df_a_procesar[col] = df_a_procesar[col].fillna('SIN_DATOS').astype(str)

                            bar = st.progress(0)
                            facturas_exitosas = 0
                            
                            # --- PROCESAMIENTO FILA A FILA ---
                            for index, row in df_a_procesar.iterrows():
                                try:
                                    # 1. Creamos la fila y limpiamos datos
                                    fila = row.to_frame().T.copy()
                                    
                                    fila['rif'] = fila['Seleccionar Proveedor'].map(dict_proveedores)
                                    fila['rif'] = fila['rif'].astype(str).str.replace('-', '', regex=False).str.replace(' ', '', regex=False).str.strip().str.upper()
                                    fila['n_factura'] = fila['n_factura'].astype(str).str.strip().str.upper()
                                    fila['n_control'] = fila['n_control'].astype(str).str.strip().str.upper()
                                    fila['proveedor'] = fila['rif'].map(dict_nombre_por_rif)
                                    fila['tipo_documento'] = '01'
                                    fila['tipo_transaccion'] = '01'

                                    # Limpieza de columnas extra
                                    cols_drop = ['Seleccionar Proveedor']
                                    if 'proveedor_nombre' in fila.columns:
                                        cols_drop.append('proveedor_nombre')
                                    fila = fila.drop(columns=cols_drop, errors='ignore')

                                    # 2. VERIFICACIÓN DE DUPLICADOS
                                    rif_val = fila['rif'].iloc[0]
                                    nfac_val = fila['n_factura'].iloc[0]
                                    
                                    query_check = "SELECT COUNT(*) FROM libro_compras WHERE rif = %s AND n_factura = %s"
                                    
                                    with engine.connect() as conn:
                                        # Usamos text() para la consulta
                                        resultado = conn.execute(text(query_check), (rif_val, nfac_val)).scalar()
                                    
                                    if resultado > 0:
                                        st.warning(f"⚠️ Factura {nfac_val} (RIF {rif_val}) ya registrada. Saltando...")
                                    else:
                                        # 3. SI NO ES DUPLICADA, GUARDAMOS
                                        fila.to_sql('libro_compras', con=engine, if_exists='append', index=False)
                                        facturas_exitosas += 1
                                        st.write(f"✅ Factura {nfac_val} guardada correctamente.")

                                except Exception as e:
                                    st.error(f"❌ Error al guardar fila {index + 1}: {e}")

                                # Actualizar barra de progreso
                                bar.progress((index + 1) / len(df_a_procesar))
                            
                            # Finalización
                            st.success(f"✅ Proceso finalizado. Total guardadas: {facturas_exitosas} de {len(df_a_procesar)}")
                            
                            if facturas_exitosas > 0:
                                st.session_state.df_buffer_escaneo = pd.DataFrame()
                               
        with tab3: # Vaciado de Rango
            st.subheader("🚨 Vaciado de Compras")
            
            with st.popover("🚨 VACIAR COMPRAS (RANGO SELECCIONADO)", width='stretch'):
                st.subheader("Seleccionar Rango a Borrar")
                
                # 1. Selectores de fecha dentro del popover
                fecha_d = st.date_input("Desde:", key="rango_desde_borrar")
                fecha_h = st.date_input("Hasta:", key="rango_hasta_borrar")
                
                st.markdown("---")
                st.subheader("Confirmar Borrado")
                st.warning(f"Se eliminarán los registros desde {fecha_d} hasta {fecha_h}") 
                
                confirmar_check = st.checkbox("Confirmo que deseo borrar", key="check_borrar_final")
                
                # 2. Ejecutar con las fechas seleccionadas en este mismo scope
                if st.button("EJECUTAR BORRADO", type="primary", disabled=not confirmar_check):
                    f_d_str = fecha_d.strftime('%Y-%m-%d')
                    f_h_str = fecha_h.strftime('%Y-%m-%d')
                    
                    borrar_compras_por_rango(f_d_str, f_h_str)
                    st.success("✅ Rango eliminado.")
                    #st.rerun()

        with tab4: # Cargar desde Excel y Editor de Tabla
            st.subheader("📊 Carga Masiva desde Excel")
            archivo_ex = st.file_uploader("Sube tu archivo Excel", type=['xlsx'])
            
            # 1. CARGA Y LIMPIEZA INICIAL
            if archivo_ex is not None:
                df_excel = pd.read_excel(archivo_ex)
                df_excel.columns = df_excel.columns.str.strip().str.lower().str.replace(" ", "_")
                
                # --- BLINDAJE ANTI-ERROR DE PYARROW ---
                # Forzamos a que TODAS las columnas de texto/identificadores sean string puro
                for col in df_excel.columns:
                    # Si la columna contiene números de control, facturas, RIF, etc., los pasamos a texto
                    if any(k in col for k in ['control', 'factura', 'rif', 'documento', 'proveedor']):
                        df_excel[col] = df_excel[col].astype(str).replace({'nan': '', 'None': ''})
            # -------------------------------------
                        
                st.session_state.df_carga_excel = df_excel

            # 2. VISUALIZACIÓN Y EDICIÓN
            if "df_carga_excel" in st.session_state:
                df_temp = st.session_state.df_carga_excel
                
                # A. Limpieza de fecha inteligente
                col_fecha = next((c for c in df_temp.columns if 'fecha' in c.lower()), None)
                if col_fecha:
                    # Renombramos si es necesario
                    if col_fecha != 'fecha_de_operación':
                        df_temp = df_temp.rename(columns={col_fecha: 'fecha_de_operación'})
                    
                    # --- LIMPIEZA DE FECHA (EL BLINDAJE FINAL) ---
                    # Forzamos formato YYYY-MM-DD y eliminamos horas. Si falla, ponemos la fecha de hoy.
                    df_temp['fecha_de_operación'] = pd.to_datetime(df_temp['fecha_de_operación'], errors='coerce')\
                                                        .dt.strftime('%Y-%m-%d')\
                                                        .fillna(pd.Timestamp.now().strftime('%Y-%m-%d'))
                    
                    st.session_state.df_carga_excel = df_temp

                # B. Preparación de Vista (Solo para mostrar, no para cálculos)
                df_visual = st.session_state.df_carga_excel.copy()
                
                # Formateo contable para la vista
                cols_para_formatear = ['total_compras', 'compras_exentas', 'base_imponible', 'credito_fiscales']
                for col in cols_para_formatear:
                    if col in df_visual.columns:
                        df_visual[col] = df_visual[col].apply(
                            lambda x: "{:,.2f}".format(float(x)).replace(",", "X").replace(".", ",").replace("X", ".") 
                            if pd.notnull(x) else "0,00"
                        )
                        
                st.subheader("👁️ Vista de los datos cargados")
                st.dataframe(df_visual, width='stretch', hide_index=True)


                # D. Totales
                st.markdown("---")
                def f_bs(v): return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                # USAMOS st.session_state.df_carga_excel (que es donde realmente tienes los datos)
                if "df_carga_excel" in st.session_state:
                    # Creamos una copia para trabajar en los cálculos sin alterar la original
                    df_calc = st.session_state.df_carga_excel.copy()
                    
                    # Renombramos columnas para los cálculos (usando el diccionario que definiste)
                    renombres = {
                        'importe_exento': 'compras_exentas',
                        'iva_monto': 'credito_fiscales',
                        'total_exento': 'compras_exentas'
                    }
                    df_calc = df_calc.rename(columns=renombres)

                    # Asegurar que las columnas existan numéricamente
                    for col in ['total_compras', 'compras_exentas', 'base_imponible', 'credito_fiscales']:
                        if col not in df_calc.columns:
                            df_calc[col] = 0.0
                        else:
                            # Forzamos conversión a número, limpiando errores
                            df_calc[col] = pd.to_numeric(df_calc[col], errors='coerce').fillna(0.0)

                    # --- MÉTRICAS ---
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("TOTAL COMPRAS", f_bs(df_calc['total_compras'].sum()))
                    m2.metric("TOTAL EXENTO", f_bs(df_calc['compras_exentas'].sum()))
                    m3.metric("TOTAL BASE", f_bs(df_calc['base_imponible'].sum()))
                    m4.metric("TOTAL IVA", f_bs(df_calc['credito_fiscales'].sum()))

            # E. BOTÓN DE GUARDADO FINAL (Llamando a tu función con los datos ya limpios)
            if st.button("🚀 Guardar carga masiva en DB", type="primary"):
                if "df_carga_excel" in st.session_state and not st.session_state.df_carga_excel.empty:
                    with st.spinner("⏳ Guardando registros..."):
                        try:
                            # Copiamos para no alterar la sesión visual
                            df_to_save = st.session_state.df_carga_excel.copy()
                            
                            # BLINDAJE: Si la columna 'retencion_iva_realizada' no viene en el Excel, 
                            # la creamos en 0.0 para que MySQL no lance el error de columna desconocida.
                            if 'retencion_iva_realizada' not in df_to_save.columns:
                                df_to_save['retencion_iva_realizada'] = 0.0
                            else:
                                df_to_save['retencion_iva_realizada'] = pd.to_numeric(
                                    df_to_save['retencion_iva_realizada'], errors='coerce'
                                ).fillna(0.0)

                            # PASAMOS EL DATAFRAME BLINDADO A TU FUNCIÓN
                            cargar_libro_compras_db(df_to_save, db_actual)
                            st.success("✅ ¡Proceso finalizado correctamente!")
                            
                        except Exception as e:
                            st.error(f"❌ Error al guardar en DB: {e}")
                else:
                    st.warning("⚠️ No hay datos cargados para guardar.")



    # 2. El sub-menú DINÁMICO
    if sub_opcion == "Comprobante de Retención ISLR":
        db_actual = st.session_state.get('DB_ACTUAL')
        # IMPORTANTE: Todo lo que quieras que salga en la barra lateral DEBE llevar st.sidebar
        st.sidebar.markdown("---") 
        st.sidebar.markdown("### ⚙️ Tareas de ISLR")
        
        # --- CONFIGURACIÓN TRIBUTARIA (UT 2026) ---
        VALOR_UT = 43.00
        FACTOR = 83.333333
        
        def calcular_sustraendo(porcentaje_retencion):
            sustraendos = {
                1.0: (FACTOR * 0.01) * VALOR_UT,
                2.0: (FACTOR * 0.02) * VALOR_UT,
                3.0: (FACTOR * 0.03) * VALOR_UT,
                5.0: (FACTOR * 0.05) * VALOR_UT
            }
            
            # Obtenemos el valor, si no existe devolvemos 0.00
            resultado = sustraendos.get(float(porcentaje_retencion), 0.00)
            
            # Redondeamos a 2 decimales para el formato Bs. XX.XX
            return round(resultado, 2)

        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        def generar_xml_seniat(df, rif_agente, periodo):
            root = ET.Element("RelacionRetencionesISLR")
            root.set("RifAgente", rif_agente)
            root.set("Periodo", periodo)

            for _, row in df.iterrows():
                detalle = ET.SubElement(root, "DetalleRetencion")
                
                # 1. RIF Retenido
                ET.SubElement(detalle, "RifRetenido").text = "".join(filter(str.isalnum, str(row['rif_retenido'])))
                
                # 2. Número Factura y Control
                ET.SubElement(detalle, "NumeroFactura").text = "".join(filter(str.isalnum, str(row['numero_factura'])))
                ET.SubElement(detalle, "NumeroControl").text = "".join(filter(str.isalnum, str(row['numero_control'])))
                
                # 3. Fecha Operación
                fecha_obj = row['fecha_operacion']
                fecha_str = fecha_obj.strftime("%d/%m/%Y") 
                ET.SubElement(detalle, "FechaOperacion").text = fecha_str
                
                # 4. Concepto y Montos (SIN EL SUSTRAENDO)
                ET.SubElement(detalle, "CodigoConcepto").text = str(row['codigo_concepto']).zfill(3)
                ET.SubElement(detalle, "MontoOperacion").text = f"{float(row['monto_operacion']):.2f}"
                ET.SubElement(detalle, "PorcentajeRetencion").text = f"{float(row['porcentaje_retencion']):.2f}"

                # ELIMINA O COMENTA ESTA LÍNEA QUE TE ESTÁ DANDO EL ERROR:
                # ET.SubElement(detalle, "Sustraendo").text = f"{float(sustraendo_val):.2f}"
                
                # NOTA: He eliminado Sustraendo, MontoRetenido y NumeroComprobante 
                # porque el SENIAT dio "Elemento no esperado" para esos campos.
                    
            xml_str = ET.tostring(root, encoding='utf-8')
            parsed = minidom.parseString(xml_str)
            return parsed.toprettyxml(indent="  ")

        # --- 🔘 TABLA DE REFERENCIA ---#
        with st.expander("📊 Ver Tabla de Referencia de Sustraendos (Manual SENIAT)", expanded=False):
            
            # Calculamos el umbral legal para PNR (83.33 UT)
            umbral_pnr = VALOR_UT * FACTOR 
            
            # 1. Definimos los datos con los valores técnicos reales
            datos_sust = [
                {"Cod": "001", "Actividad": "Sueldos y Salarios", "Tipo": "PNR", "Mayores a": "Variable", "% Ret.": None, "Sustraendo Bs.": "-"},
                {"Cod": "003", "Actividad": "Honorarios Prof. No Mercantiles", "Tipo": "PNR", "Mayores a": f"{umbral_pnr:,.2f}", "% Ret.": 3.0, "Sustraendo Bs.": calcular_sustraendo(3)},
                {"Cod": "004", "Actividad": "Honorarios Prof. No Mercantiles", "Tipo": "PJD", "Mayores a": "0,01", "% Ret.": 5.0, "Sustraendo Bs.": 0.00},
                {"Cod": "019", "Actividad": "Comisiones Varias", "Tipo": "PNR", "Mayores a": f"{umbral_pnr:,.2f}", "% Ret.": 3.0, "Sustraendo Bs.": calcular_sustraendo(3)},
                {"Cod": "020", "Actividad": "Comisiones Varias", "Tipo": "PJD", "Mayores a": "0,01", "% Ret.": 5.0, "Sustraendo Bs.": 0.00},
                {"Cod": "053", "Actividad": "Empresas Contratistas / Servicios", "Tipo": "PNR", "Mayores a": f"{umbral_pnr:,.2f}", "% Ret.": 1.0, "Sustraendo Bs.": calcular_sustraendo(1)},
                {"Cod": "055", "Actividad": "Empresas Contratistas / Servicios", "Tipo": "PJD", "Mayores a": "0,01", "% Ret.": 2.0, "Sustraendo Bs.": 0.00},
                {"Cod": "071", "Actividad": "Gastos de Transporte (Fletes)", "Tipo": "PNR", "Mayores a": "0,01", "% Ret.": 1.0, "Sustraendo Bs.": calcular_sustraendo(1)},
                {"Cod": "072", "Actividad": "Gastos de Transporte (Fletes)", "Tipo": "PJD", "Mayores a": "0,01", "% Ret.": 3.0, "Sustraendo Bs.": 0.00},
            ]

            df_referencia = pd.DataFrame(datos_sust)

            st.info(f"📍 **Base Legal:** Unidad Tributaria: **Bs. {VALOR_UT:,.2f}** | Umbral PNR (83.33 UT): **Bs. {umbral_pnr:,.2f}**")

            # 2. Configuración de la tabla profesional
            st.dataframe(
                df_referencia,
                width='stretch',
                hide_index=True,
                column_config={
                    "Cod": st.column_config.TextColumn("Código", width="small"),
                    "Actividad": st.column_config.TextColumn("Actividad / Concepto Según Manual", width="large"),
                    "Tipo": st.column_config.TextColumn("Persona"),
                    "Mayores a": st.column_config.TextColumn("Mayores a... (Bs.)"),
                    "% Ret.": st.column_config.NumberColumn("Alícuota", format="%.1f%%"),
                    "Sustraendo Bs.": st.column_config.NumberColumn("Sustraendo", format="Bs. %.2f"),
                }
            )

        DATOS_EMPRESA = {
            "nombre": "KING DRIVER, C.A.",
            "rif": "J507757188",
            "direccion": "AV. JOSE ANTONIO PAEZ EDIF RESIDENCIAS 2000 RESIDENCIAS CECILIA PISO PH APT 43 URB EL PARAISO CARACAS DISTRITO CAPITAL"
        }

        # Inicializar el índice de la pestaña si no existe
        if 'active_tab' not in st.session_state:
            st.session_state.active_tab = 0

        # Definir las pestañas y capturar el índice seleccionado
        # 1. Definimos la lista de nombres
        tab_names = ["➕ Generar Nueva", "🔍 Editor/Historial", "🖨️ Reimpresión", "⚙️ Gestión Facturas", "🚀 XML SENIAT"]
        tab2, tab3, tab4, tab5, tab6 = st.tabs(tab_names)


        with tab2:
            st.markdown("### 🆕 Generar Nueva Retención de ISLR")

            # --- BLINDAJE LOCAL DE FECHAS ---
            from datetime import date as d_tipo, datetime as dt_tipo

            col_fecha1, col_fecha2 = st.columns(2)
            f_xml_desde_n = col_fecha1.date_input("Desde", value=d_tipo(2026, 10, 1), key="nueva_desde")
            f_xml_hasta_n = col_fecha2.date_input("Hasta", value=d_tipo(2026, 10, 31), key="nueva_hasta")

            col_c1, col_c2 = st.columns(2)
            with col_c1:
                if st.button("🔍 Consultar Facturas y Proveedores", use_container_width=True):
                    conn = conectar_db(db_actual)
                    if conn:
                        try:
                            # 1. Cargamos el directorio fiscal en session_state de una vez
                            st.session_state.df_prov_fiscal = ejecutar_consulta(
                                "SELECT rif, razon_social, direccion_fiscal FROM proveedores", conn
                            )

                            # 2. Consulta optimizada de facturas pendientes
                            query = """
                            SELECT 
                                lc.id AS id, 
                                lc.fecha_operacion AS fecha_operacion,
                                NULL AS id_sec, 
                                lc.rif AS rif_retenido, 
                                COALESCE(p.razon_social, 'PROVEEDOR NO ENCONTRADO') AS proveedor_nombre, 
                                COALESCE(p.direccion_fiscal, 'DIRECCIÓN NO REGISTRADA') AS proveedor_direccion,
                                lc.n_factura AS numero_factura, 
                                lc.n_control AS numero_control, 
                                NULL AS codigo_concepto, 
                                lc.base_imponible AS monto_operacion, 
                                0.00 AS porcentaje_retencion, 
                                0.00 AS monto_retenido, 
                                NULL AS periodo_retenido, 
                                0.00 AS sustraendo, 
                                NULL AS n_comprob_islr
                            FROM libro_compras lc
                            LEFT JOIN proveedores p ON 
                                TRIM(REGEXP_REPLACE(lc.rif, '[^a-zA-Z0-9]', '')) = TRIM(REGEXP_REPLACE(p.rif, '[^a-zA-Z0-9]', ''))
                            WHERE (lc.retencion_realizada = 0 OR lc.retencion_realizada IS NULL)
                            AND lc.fecha_operacion BETWEEN %s AND %s
                            ORDER BY lc.fecha_operacion ASC
                            """

                            st.session_state.df_retencion = ejecutar_consulta(
                                query, 
                                conn, 
                                params=(f_xml_desde_n, f_xml_hasta_n)
                            )
                            st.success("✅ Facturas y Directorio de Proveedores cargados con éxito.")
                        except Exception as e:
                            st.error(f"❌ Error al consultar la base de datos: {e}")
                        finally:
                            conn.close()

            with col_c2:
                # Botón de respaldo manual por si desean refrescarlo por separado
                if st.button("🔄 Refrescar Directorio Manualmente", use_container_width=True):
                    conn = conectar_db(db_actual)
                    if conn:
                        st.session_state.df_prov_fiscal = ejecutar_consulta("SELECT rif, razon_social, direccion_fiscal FROM proveedores", conn)
                        conn.close()
                        st.info("📂 Directorio actualizado manualmente.")

            # Inicialización de estados
            if "pdf_listo" not in st.session_state:
                st.session_state.pdf_listo = False
            if "datos_pdf" not in st.session_state:
                st.session_state.datos_pdf = None

            if "df_retencion" in st.session_state and not st.session_state.df_retencion.empty:
                columnas_a_mostrar = [
                    "fecha_operacion", "rif_retenido", "proveedor_nombre", 
                    "numero_factura", "numero_control", "monto_operacion"
                ]
                
                sel_f = st.dataframe(
                    st.session_state.df_retencion[columnas_a_mostrar], 
                    on_select="rerun", 
                    selection_mode="single-row", 
                    hide_index=True, 
                    use_container_width=True
                )
                
                if sel_f.selection.rows:
                    f_data = st.session_state.df_retencion.iloc[sel_f.selection.rows[0]]
                    
                    with st.form(key=f"form_final_islr_{f_data['id']}"): 

                        st.markdown("#### 🛠️ Datos del Comprobante")
                        c1, c2, c3 = st.columns([3, 4, 5])
                        
                        rif_r = c1.text_input("RIF", value=str(f_data['rif_retenido']))
                        id_seguro = f_data.get('id') or 0
                        val_sugerido = f_data['fecha_operacion'].strftime("%Y%m") + str(id_seguro).zfill(8)
                        n_comprob_manual = c2.text_input("N° Comprobante (Manual)", value=val_sugerido)
                        
                        dir_bd = str(f_data.get('proveedor_direccion') or "")
                        nombre_raw = str(f_data.get('proveedor_nombre') or "")
                        
                        valor_razon = nombre_raw if nombre_raw != 'PROVEEDOR NO ENCONTRADO' else ""
                        valor_dir = dir_bd if dir_bd not in ["DIRECCIÓN NO REGISTRADA", "NONE", ""] else ""


                        # 1. Recuperamos los valores iniciales de la factura (asegúrate de que existan antes)
                        valor_razon = str(f_data.get('proveedor_nombre', ''))
                        valor_dir = str(f_data.get('proveedor_direccion', ''))

                        # 2. Si no se encontró en la BD, limpiamos para que los inputs queden listos para escribir
                        if valor_razon == 'PROVEEDOR NO ENCONTRADO':
                            st.warning("⚠️ Proveedor no encontrado en el directorio. Por favor ingrese los datos manualmente:")
                            valor_razon = ""
                            valor_dir = ""

                        if valor_dir in ["DIRECCIÓN NO REGISTRADA", "NONE", ""]:
                            valor_dir = ""

                        # 3. Campos de texto directos
                        razon_r = st.text_input("Razón Social", value=valor_razon, key=f"razon_{id_seguro}")
                        
                        if valor_dir.strip() != "":
                            dir_r = st.text_input("Dirección", value=valor_dir, key=f"dir_{id_seguro}")
                        else:
                            st.warning("⚠️ PROVEEDOR SIN DIRECCIÓN REGISTRADA")
                            dir_r = st.text_input("Dirección", value="", placeholder="Escriba la dirección fiscal aquí...", key=f"dir_{id_seguro}")

                        c7, c8, c9 = st.columns(3)
                        base_r = c7.number_input("Base Imponible", value=float(f_data['monto_operacion']))
                        porc_r = c8.number_input("% Retención", value=3.0)
                        codigo_r = c9.text_input("Código Concepto", value="001", help="Ingresa el código del SENIAT (ej. 001, 002)")
                        
                        try:
                            porc_actual = float(porc_r) if porc_r is not None else 0.0
                        except ValueError:
                            porc_actual = 0.0

                        if rif_r.upper().startswith(('V', 'E')) and porc_actual > 0:
                            val_sust = calcular_sustraendo(porc_actual)
                        else:
                            val_sust = 0.00 

                        sust_r = c9.number_input(
                            "Sustraendo", 
                            value=float(val_sust), 
                            format="%.2f", 
                            key=f"sust_{id_seguro}"
                        )
                        
                        btn_procesar = st.form_submit_button("🚀 Procesar y Guardar")
                        
                        if btn_procesar:
                            conn = conectar_db(st.session_state.get('DB_ACTUAL'))
                            m_final = round(float((float(base_r) * (float(porc_r) / 100)) - float(sust_r)), 2)
                            
                            if comprobar_existencia_comprobante(n_comprob_manual):
                                st.error(f"⚠️ El comprobante **{n_comprob_manual}** ya existe.")
                            else:
                                exito, valor = registrar_retencion_islr_db(
                                    int(id_seguro), rif_r, razon_r, dir_r, 
                                    str(f_data['numero_factura']), str(f_data['numero_control']), 
                                    f_data['fecha_operacion'], codigo_r, base_r, porc_r, 
                                    sust_r, f_data['fecha_operacion'].strftime("%Y%m"), 
                                    m_final, n_comprob_manual
                                )
                                
                                if exito:
                                    # --- BLOQUEO DE LA FACTURA EN BASE DE DATOS ---
                                    # Abrimos una conexión independiente y segura solo para este UPDATE del libro
                                    conn_bloqueo = conectar_db(st.session_state.get('DB_ACTUAL'))
                                    if conn_bloqueo:
                                        try:
                                            cursor = conn_bloqueo.cursor()
                                            # Se elimina n_comprob_islr de la consulta para evitar el error de columna desconocida
                                            query_bloqueo = "UPDATE libro_compras SET retencion_realizada = 1 WHERE id = %s"
                                            cursor.execute(query_bloqueo, (int(id_seguro),))
                                            conn_bloqueo.commit()
                                            cursor.close()
                                        except Exception as err_b:
                                            st.warning(f"⚠️ La retención se guardó, pero hubo un detalle al bloquear la factura en el libro: {err_b}")
                                        finally:
                                            # Cierre seguro condicional para evitar el error "Already closed"
                                            try:
                                                if hasattr(conn_bloqueo, 'open') and conn_bloqueo.open:
                                                    conn_bloqueo.close()
                                                elif not hasattr(conn_bloqueo, 'open'):
                                                    conn_bloqueo.close()
                                            except Exception:
                                                pass

                                    st.session_state.datos_pdf = {
                                        "agente": DATOS_EMPRESA,
                                        "sujeto": {"rif": rif_r, "nombre": razon_r, "direccion": dir_r},
                                        "factura": str(f_data['numero_factura']),
                                        "control": str(f_data['numero_control']),
                                        "base": base_r,
                                        "porcentaje": porc_r,
                                        "sustraendo": sust_r,
                                        "total_retenido": m_final,
                                        "fecha_emision": f_data['fecha_operacion'].strftime("%d/%m/%Y"),
                                        "fecha_operacion": f_data['fecha_operacion'],
                                        "n_comprobante": n_comprob_manual
                                    }
                                    st.session_state.pdf_listo = True
                                    
                                    # --- REMOVER LA FACTURA DEL DATAFRAME LOCAL DE LA SESIÓN ---
                                    st.session_state.df_retencion = st.session_state.df_retencion[
                                        st.session_state.df_retencion['id'] != id_seguro
                                    ]

                                    # --- EFECTOS VISUALES Y NOTIFICACIONES DE ÉXITO ---
                                    st.balloons()  # Lanza los globos 🎈
                                    
                                    # Notificación grande y llamativa tipo éxito total
                                    st.success(f"🎉 ¡FELICIDADES! Comprobante N° {n_comprob_manual} registrado y factura bloqueada con éxito.")
                                    st.toast("🚀 ¡Todo procesado correctamente!", icon="✅")
                                    
                                    # Pequeño respiro visual para que el usuario alcance a disfrutar la animación antes del rerun
                                    import time
                                    time.sleep(1.5)
                                    
                                    #st.rerun()

            # Bloque de descarga
            if st.session_state.pdf_listo and st.session_state.datos_pdf:
                st.write("---")
                st.info("💡 El comprobante está listo para descargar.")
                conn_pdf = conectar_db(st.session_state.get('DB_ACTUAL'))
                pdf_bytes = generar_comprobante_pdf(st.session_state.datos_pdf, conn_pdf)
                if conn_pdf:
                    conn_pdf.close()
                    
                st.download_button(
                    label="📥 DESCARGAR COMPROBANTE PDF AHORA",
                    data=pdf_bytes,
                    file_name=f"Retencion_{st.session_state.datos_pdf['n_comprobante']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="btn_download_final"
                )
                
                if st.button("➕ Registrar otra retención"):
                    st.session_state.pdf_listo = False
                    st.session_state.datos_pdf = None
                    #st.rerun()

            with tab3:
                # --- SECCIÓN: EDITOR DE HISTORIAL ---
                st.divider()
                st.markdown("### 🔎 Editor y Filtros de Historial")

                with st.expander("📅 Filtros de Consulta para Editar", expanded=True):
                    col_f1, col_f2 = st.columns(2)
                    
                    # --- BLINDAJE LOCAL DE FECHAS (Uso de d_tipo.date) ---
                    from datetime import date as d_tipo

                    # Keys únicas para evitar conflictos
                    f_inicio_h = col_f1.date_input("Desde", d_tipo(2026, 8, 1), key="h_desde_editor")
                    f_fin_h = col_f2.date_input("Hasta", d_tipo(2026, 8, 31), key="h_hasta_editor")
                    st.write("") 
                    btn_cargar = st.button("📂 Cargar Historial para Editar", width='stretch', type="primary")

                # --- 1. Lógica de carga (DENTRO DEL TAB) ---
                if btn_cargar:
                    conn = conectar_db()
                    db_actual = st.session_state.get('DB_ACTUAL')
                    if conn and db_actual:
                        try:
                            cursor = conn.cursor()
                            # SELECCIONAR LA BASE DE DATOS CORRECTA ANTES DE CONSULTAR
                            cursor.execute(f"USE {db_actual}")
                            # Esta es tu consulta exacta
                            query = """
                                SELECT id, rif_retenido, numero_factura, numero_control, fecha_operacion, 
                                       codigo_concepto, monto_operacion, porcentaje_retencion, 
                                       monto_retenido, periodo_retenido, n_comprob_islr 
                                FROM retenciones_islr 
                                WHERE fecha_operacion BETWEEN %s AND %s 
                                ORDER BY fecha_operacion DESC
                            """
                            
                            # Definimos los parámetros basándonos en tus date_input
                            parametros = (f_inicio_h.strftime('%Y-%m-%d'), f_fin_h.strftime('%Y-%m-%d'))
                            
                            # Ejecutamos pasando los parámetros por separado
                            st.session_state.df_retenciones_editor = ejecutar_consulta(query, conn, params=parametros)
                            
                            st.success(f"✅ Registros cargados: {len(st.session_state.df_retenciones_editor)}")
                            
                        except Exception as e:
                            st.error(f"Error en la base de datos: {e}")
                        finally:
                            conn.close()

                # --- 2. Visualización y Edición (DENTRO DEL TAB) ---
                # --- 2. Visualización y Edición ---
                if "df_retenciones_editor" in st.session_state:
                    st.info("📝 Puedes editar los montos o eliminar filas.")
                    
                    # Asegúrate de que las columnas coincidan con las de tu DataFrame real
                    edit_ret_df = st.data_editor(
                        st.session_state.df_retenciones_editor,
                        key="editor_tabla_retenciones",
                        hide_index=True,
                        column_config={
                            "id": st.column_config.NumberColumn("ID", disabled=True),
                            "rif_retenido": "RIF",
                            "numero_factura": "N° Factura",
                            "monto_operacion": st.column_config.NumberColumn("Base", format="Bs %.2f"),
                            "monto_retenido": st.column_config.NumberColumn("Monto Retenido", format="Bs %.2f"),
                            # Asegúrate de que los nombres aquí coincidan con los del SELECT
                        }
                    )

                    # --- 3. Sincronización ---
                    if st.button("💾 Sincronizar Historial con DB", type="primary", width='stretch'):
                        estado = st.session_state.get("editor_tabla_retenciones", None)
                        db_actual = st.session_state.get('DB_ACTUAL')
                        conn = conectar_db()
                        
                        if conn and db_actual:
                            try:
                                cursor = conn.cursor()
                                cursor.execute(f"USE {db_actual}")
                                
                                total_eliminados = 0
                                total_editados = 0
                                
                                # PROCESAR ELIMINACIONES
                                if estado and "deleted_rows" in estado:
                                    for row_idx in estado["deleted_rows"]:
                                        id_real = int(st.session_state.df_retenciones_editor.iloc[row_idx]["id"]) 
                                        cursor.execute("DELETE FROM retenciones_islr WHERE id = %s", (id_real,))
                                        total_eliminados += 1

                                # PROCESAR EDICIONES
                                if estado and "edited_rows" in estado and estado["edited_rows"]:
                                    for row_idx, cambios in estado["edited_rows"].items():
                                        fila = st.session_state.df_retenciones_editor.iloc[int(row_idx)]
                                        id_real = int(fila["id"])
                                        
                                        for campo_display, valor in cambios.items():
                                            mapa = {
                                                "Monto Retenido": "monto_retenido",
                                                "Base": "monto_operacion",
                                                "N° Factura": "numero_factura",
                                                "RIF": "rif_retenido"
                                            }
                                            columna_db = mapa.get(campo_display, campo_display)
                                            valor_final = valor.item() if hasattr(valor, 'item') else valor
                                            
                                            query_upd = f"UPDATE retenciones_islr SET {columna_db} = %s WHERE id = %s"
                                            cursor.execute(query_upd, (valor_final, id_real))
                                            total_editados += 1

                                conn.commit()
                                
                                if total_eliminados > 0 or total_editados > 0:
                                    # --- NOTIFICACIÓN MEJORADA ---
                                    mensaje = f"✅ Cambios guardados: {total_eliminados} eliminados, {total_editados} editados."
                                    st.success(mensaje)
                                    st.toast(mensaje, icon="💾") # Notificación flotante
                                    
                                    import time
                                    time.sleep(1.5) # Pausa breve para que el usuario lea el mensaje
                                    
                                    if "df_retenciones_editor" in st.session_state:
                                        del st.session_state.df_retenciones_editor
                                    st.rerun()
                                else:
                                    st.info("ℹ️ No se detectaron cambios para guardar.")
                                    
                            except Exception as e:
                                conn.rollback()
                                st.error(f"❌ Error al sincronizar: {e}")
                            finally:
                                conn.close()
                        elif not db_actual:
                            st.warning("⚠️ No se ha seleccionado una base de datos activa.")


            # --- TAB 4: REIMPRESIÓN ---
            with tab4:
                st.divider()
                st.markdown("### 🖨️ Reimpresión de Comprobantes")
                
                # 1. Botón para cargar historial
                # Bloque de carga corregido dentro de tab4
                # 1. Botón para cargar historial
                if st.button("📂 Cargar/Actualizar Historial", width='stretch'):
                    db_actual = st.session_state.get('DB_ACTUAL')
                    conn = conectar_db()
                    
                    if conn and db_actual:
                        try:
                            cursor = conn.cursor()
                            # Aseguramos el contexto de la base de datos correcta
                            cursor.execute(f"USE {db_actual}")
                            
                            query_historial = """
                                SELECT r.*, 
                                       COALESCE(p.razon_social, r.rif_retenido) AS nombre_completo, 
                                       COALESCE(p.direccion_fiscal, 'CARACAS, VENEZUELA') AS direccion_completa
                                FROM retenciones_islr r
                                LEFT JOIN proveedores p ON r.rif_retenido = p.rif
                                ORDER BY r.id DESC
                            """
                            # Cargar datos al session_state
                            st.session_state.df_historial_islr = ejecutar_consulta(query_historial, conn)
                            
                        except Exception as e:
                            st.error(f"Error al cargar historial: {e}")
                        finally:
                            conn.close()
                            # Forzar recarga para que el if inferior detecte los datos
                            st.rerun()
                    elif not db_actual:
                        st.warning("⚠️ Por favor, selecciona una base de datos primero.")


                # 2. Visualización y Selección
                # 2. Visualización y Selección
                if "df_historial_islr" in st.session_state and not st.session_state.df_historial_islr.empty:
                    sel_hist = st.dataframe(
                        st.session_state.df_historial_islr, 
                        key="tabla_historial",
                        on_select="rerun", 
                        selection_mode="single-row", 
                        hide_index=True, 
                        width='stretch'
                    )

                    seleccion = st.session_state.tabla_historial.selection.rows
                    
                    if seleccion:
                        idx = seleccion[0]
                        h = st.session_state.df_historial_islr.iloc[idx]
                        
                        # Procesamiento de datos...
                        with st.status("🛠️ Procesando datos...", expanded=False):
                            # ... (tu lógica de limpieza de factura y control aquí) ...
                            factura_sucia = str(h['numero_factura']).split("/")[0]
                            solo_numeros_f = re.findall(r'\d+', factura_sucia)
                            factura_limpia = solo_numeros_f[0].zfill(5) if solo_numeros_f else "00001"

                            control_sucio = str(h['numero_control']).split("/")[-1]
                            solo_numeros_c = re.findall(r'\d+', control_sucio)
                            control_limpio = solo_numeros_c[0] if solo_numeros_c else "00001"

                            datos_reimp = {
                                "agente": DATOS_EMPRESA,
                                "sujeto": {
                                    "rif": h['rif_retenido'], 
                                    "nombre": h['nombre_completo'], 
                                    "direccion": h['direccion_completa']
                                },
                                "factura": factura_limpia, 
                                "control": control_limpio, 
                                "base": float(h['monto_operacion']), 
                                "porcentaje": float(h['porcentaje_retencion']), 
                                "sustraendo": float(h['sustraendo']), 
                                "total_retenido": float(h['monto_retenido']),
                                "fecha_operacion": h['fecha_operacion'],
                                "n_comprobante": h.get('n_comprob_islr', "S/N") 
                            }

                        # 3. Botón de descarga con conexión abierta
                        st.write(f"✅ Factura seleccionada: **{factura_limpia}**")
                        
                        conn = conectar_db() # Abrimos conexión para el log
                        if conn:
                            try:
                                # PASAMOS EL SEGUNDO ARGUMENTO (conn)
                                pdf_bytes_re = generar_comprobante_pdf(datos_reimp, conn)
                                
                                if pdf_bytes_re:
                                    st.download_button(
                                        label=f"📥 Descargar PDF: {h['nombre_completo'][:20]}...", 
                                        data=pdf_bytes_re, 
                                        # Aquí hacemos el cambio para usar el número de comprobante directamente
                                        file_name=f"Retencion_{h['n_comprob_islr']}.pdf", 
                                        mime="application/pdf", 
                                        width='stretch',
                                        key=f"btn_reimp_{h['id']}"
                                    )
                            except Exception as e:
                                st.error(f"Error al generar el archivo: {e}")
                            finally:
                                conn.close() # Cerramos conexión para liberar recursos

            # --- TAB 5: GESTIÓN DE FACTURAS ---
            with tab5:
                st.divider()
                st.subheader("⚙️ Gestión y Desbloqueo de Facturas")
                st.info("Utiliza esta opción si marcaste una factura como 'Retenida' por error.")

                # --- COMUNICACIÓN DINÁMICA MULTI-CLIENTE ---
                with st.expander("🔍 Listado de Facturas en la BD"):
                    try:
                        # Usamos la conexión dinámica según el cliente en sesión
                        db_actual = st.session_state.get('DB_ACTUAL')
                        if db_actual:
                            conn = conectar_db(db_actual)
                            df = ejecutar_consulta("SELECT rif_retenido, numero_factura FROM retenciones_islr", conn)
                            st.dataframe(df, width='stretch')
                            conn.close()
                        else:
                            st.error("No se detectó una base de datos activa en la sesión.")
                    except Exception as e:
                        st.error(f"Error de conexión: {e}")

                # --- FORMULARIO DE DESBLOQUEO ---
                with st.form("form_desbloqueo", clear_on_submit=True):
                    col1, col2 = st.columns(2)
                    rif_input = col1.text_input("RIF del Proveedor:")
                    factura_input = col2.text_input("Número de factura:")
                    
                    btn_habilitar = st.form_submit_button("🔓 Habilitar Factura para Retención", type="primary")

                    if btn_habilitar:
                        if factura_input:
                            # Importante: Asegúrate de que resetear_estado_retencion también 
                            # use la DB_ACTUAL internamente o reciba el parámetro
                            resultado = resetear_estado_retencion(factura_input)
                            if resultado is True:
                                st.success(f"✅ Factura {factura_input} habilitada correctamente.")
                            else:
                                st.error("❌ No se pudo habilitar. Verifica el número.")
                        else:
                            st.warning("💡 Debes ingresar el número de factura.")

            # --- TAB 6: XML SENIAT ---
            with tab6:
                # --- SECCIÓN C: GENERAR ARCHIVO XML SENIAT ---
                st.divider()
                st.markdown("### 📡 Generar Archivo XML para Declaración SENIAT")
                
                # --- BLINDAJE LOCAL DE FECHAS ---
                from datetime import date as d_tipo

                with st.container(border=True):
                    col_xml1, col_xml2 = st.columns(2)
                    f_xml_desde = col_xml1.date_input("Desde", value=d_tipo(2026, 4, 1), key="xml_desde")
                    f_xml_hasta = col_xml2.date_input("Hasta", value=d_tipo(2026, 4, 30), key="xml_hasta")
                    
                    # Botón de procesamiento (usando width='content' en lugar de width='content')
                    if st.button("🚀 Procesar Datos XML", width='content'):
                        db_actual = st.session_state.get('DB_ACTUAL') 
                        conn = conectar_db(db_actual) # Pasa explícitamente el nombre de la DB
                        if conn:

                            # Usamos parámetros para evitar inyecciones SQL aunque sea uso interno
                            query_xml = """
                                SELECT 
                                    rif_retenido, 
                                    numero_factura, 
                                    numero_control, 
                                    fecha_operacion,
                                    codigo_concepto, 
                                    monto_operacion, 
                                    porcentaje_retencion,
                                    sustraendo, 
                                    monto_retenido, 
                                    n_comprob_islr
                                FROM retenciones_islr 
                                WHERE fecha_operacion BETWEEN %s AND %s
                            """
                            df_xml = ejecutar_consulta(query_xml, conn, params=(f_xml_desde, f_xml_hasta))
                            conn.close()
                            
                            if not df_xml.empty:
                                periodo_xml = f_xml_hasta.strftime("%Y%m")
                                # Guardamos el resultado en session_state
                                st.session_state['xml_data'] = generar_xml_seniat(df_xml, DATOS_EMPRESA['rif'], periodo_xml)
                                st.session_state['xml_filename'] = f"RET_ISLR_{periodo_xml}.xml"
                                st.success(f"✅ Datos procesados ({len(df_xml)} retenciones). Listo para descargar.")
                            else:
                                st.warning("⚠️ No se encontraron retenciones en el rango seleccionado.")
                                st.session_state['xml_data'] = None

                    # Botón de descarga (se muestra solo si hay datos en el estado de la sesión)
                    if st.session_state.get('xml_data'):
                        st.download_button(
                            label="📥 Descargar XML para el Portal SENIAT",
                            data=st.session_state['xml_data'],
                            file_name=st.session_state['xml_filename'],
                            mime="application/xml",
                            width='content' # Actualizado de width='content'
                        )


    elif sub_opcion == "Comprobante de Retención IVA":
        # 1. Aseguramos que el módulo datetime esté disponible sin conflictos
        import datetime as dt 
        
        # 🟢 2. Validación de tipo de usuario
        tipo_usuario = st.session_state.get('tipo_contribuyente', 'Contribuyente Ordinario')

        if tipo_usuario == "Contribuyente Especial":
            # 3. Validamos la conexión antes de entrar a la interfaz pesada
            db_actual = st.session_state.get('DB_ACTUAL', 'control_central')
            conn_valida = conectar_db(db_actual)
            
            if conn_valida:
                conn_valida.close()
                
                # Obtenemos las fechas de manera segura desde el session_state
                f_ini = st.session_state.get('f_inicio_global', dt.date.today())
                f_fin = st.session_state.get('f_fin_global', dt.date.today())
                
                # Llamamos a la función con las variables seguras
                mostrar_interfaz_retencion_iva(EMPRESA, f_ini, f_fin)
            else:
                st.error("No se pudo restablecer la conexión para el módulo de IVA.")
        else:
            # Bloqueamos el acceso para los contribuyentes ordinarios
            st.warning("⚠️ Este módulo es exclusivo para **Contribuyentes Especiales**.")
            st.info("Si cree que esto es un error, contacte a soporte para actualizar su clasificación fiscal.")

# --- USAMOS "IN" PARA QUE NO IMPORTE EL EMOJI QUE PONGAS EN EL SIDEBAR ---
elif "Proveedores" in opcion_menu:
    st.title("👤 Gestión de Directorio de Proveedores")
    
    # 0. ASEGURAR QUE db_actual ESTÉ DEFINIDA
    db_actual = st.session_state.get('DB_ACTUAL')
    
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()

    # 1. Obtenemos la conexión
    conn_empresa = conectar_db(db_actual)
    
    # 🆕 1.1 OBTENER PLAN DE CUENTAS PARA LOS SELECTORES DE LA TABLA PROVEEDORES
    opciones_cuentas_prov = [""]
    try:
        cursor_pc = conn_empresa.cursor(pymysql.cursors.DictCursor)
        cursor_pc.execute(f"SELECT codigo, nombre FROM `{db_actual}`.plan_cuentas ORDER BY codigo ASC")
        cuentas_db = cursor_pc.fetchall()
        cursor_pc.close()
        for c in cuentas_db:
            opciones_cuentas_prov.append(f"{str(c.get('codigo')).strip()} - {str(c.get('nombre')).strip()}")
    except Exception:
        pass # Si falla o la tabla no existe aún, se mantiene vacío para permitir texto libre
    
    try:
        # 2. Definición estricta de tabs
        tab1, tab2 = st.tabs(["📥 Cargar desde Excel", "📋 Directorio Actual"])
        
        # 3. Lógica de Pestaña 1
        with tab1:
            st.markdown("### Subir Archivo Masivo")
            st.markdown("Asegúrate de que tu Excel contenga las columnas de identificación fiscal, razón social y opcionalmente los campos de parametrización contable (`codigo_cuenta`).")
            file_p = st.file_uploader("Seleccione el archivo Excel", type=["xlsx"], key="file_prov_up")
                
            if file_p:
                df_subida = pd.read_excel(file_p)
                st.write("Vista previa:")
                st.dataframe(df_subida.head())
                if st.button("🚀 Procesar y Guardar", type="primary"):
                    procesar_excel_proveedores_db(conn_empresa, df_subida)
                    st.success("✅ ¡Actualizado!")
                    st.balloons()

        # 4. Lógica de Pestaña 2
        with tab2:
            st.markdown("### 📋 Directorio Actual y Parametrización Contable")
            
            # 1. Inicializamos los datos en session_state asegurando las columnas nuevas de cuentas
            if "df_proveedores_cache" not in st.session_state:
                df_temp = consultar_tabla_db(conn_empresa, "proveedores")
                
                columnas_necesarias = ["rif", "tipo_persona", "razon_social", "direccion_fiscal", "codigo_cuenta", "descripcion_cuenta"]
                
                if df_temp is None or not isinstance(df_temp, pd.DataFrame) or df_temp.empty:
                    df_temp = pd.DataFrame(columns=columnas_necesarias)
                else:
                    # Garantizar que existan las columnas nuevas si la tabla en BD es antigua
                    for col in columnas_necesarias:
                        if col not in df_temp.columns:
                            df_temp[col] = ""
                
                for col in df_temp.columns:
                    df_temp[col] = df_temp[col].astype(str).replace(['None', 'nan', 'NAT'], '')
                
                st.session_state.df_proveedores_cache = df_temp

            # 2. El data_editor con las columnas de cuentas integradas
            df_editado = st.data_editor(
                st.session_state.df_proveedores_cache, 
                key="editor_proveedores_dinamico", 
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "rif": st.column_config.TextColumn("RIF (Llave Primaria)", required=True),
                    "tipo_persona": st.column_config.SelectboxColumn("Tipo", options=["PN", "PJ"], required=True),
                    "razon_social": st.column_config.TextColumn("Razón Social", required=True),
                    "direccion_fiscal": st.column_config.TextColumn("Dirección Fiscal", required=True),
                    "codigo_cuenta": st.column_config.TextColumn(
                        "Código Cuenta por Defecto", 
                        help="Código contable predeterminado para este proveedor al procesar compras"
                    ),
                    "descripcion_cuenta": st.column_config.TextColumn(
                        "Descripción Cuenta", 
                        help="Nombre o descripción asociada a la cuenta contable",
                        disabled=False
                    )
                }
            )
            
            # 3. Actualizamos el caché local con lo que el usuario modificó/agregó visualmente
            st.session_state.df_proveedores_cache = df_editado

            col_b1, col_b2 = st.columns(2)
            
            with col_b1:
                if st.button("💾 Guardar Todo en BD", key="btn_guardar_proveedores", use_container_width=True):
                    try:
                        # Enviamos a la base de datos lo que está en el editor
                        actualizar_tabla_completa_db(conn_empresa, "proveedores", df_editado)
                        st.success("¡Directorio actualizado con éxito!")
                        # Forzamos una recarga limpia desde la BD para sincronizar
                        del st.session_state.df_proveedores_cache
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar los cambios en la base de datos: {e}")

            with col_b2:
                if st.button("🔄 Recargar desde BD", key="btn_recargar_proveedores", use_container_width=True):
                    if "df_proveedores_cache" in st.session_state:
                        del st.session_state.df_proveedores_cache
                    st.rerun()

        # 4. Zona de respaldo usando el caché actual
        st.markdown("---") 
        df_para_respaldo = st.session_state.get("df_proveedores_cache", pd.DataFrame())
        if not df_para_respaldo.empty:
            import io
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_para_respaldo.to_excel(writer, index=False, sheet_name='Proveedores')
            st.download_button(
                "📥 Descargar Respaldo de Proveedores", 
                data=output.getvalue(), 
                file_name="Respaldo_Proveedores.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
    finally:
        # 6. Cierre de conexión garantizado
        if conn_empresa:
            try:
                conn_empresa.close()
            except Exception:
                pass


elif "Inventarios" in opcion_menu:
    # Invocamos el módulo exclusivo pasando la conexión a la base de datos
    modulo_inventario_pedacito_cielo(conn)  
