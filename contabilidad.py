#contabilidad.py
import os
import pytesseract

# --- CONFIGURACIÓN DE TESSERACT PARA MULTI-PLATAFORMA ---
if os.name == 'nt':
    # Ruta en tu Windows local
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
else:
    # Ruta en los servidores de la nube (Linux)
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from fpdf import FPDF
import mysql.connector
from mysql.connector import Error
from datetime import datetime, date, timedelta # Limpiamos los imports de fecha
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io
import os
import numpy as np
import re 
import plotly.graph_objects as go
import plotly.express as px
import calendar
import base64
import plotly.express as px
from datetime import date # IMPORTA LA CLASE DATE DIRECTAMENTE
from PIL import Image, ImageEnhance
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
import json
import base64
from openai import OpenAI
from sqlalchemy import create_engine
import warnings
import pandas as pd
import bcrypt
import time
import datetime

def conectar_db(nombre_db=None):
    db_a_usar = nombre_db if nombre_db else "control_central"
    
    try:
        # 1. VERIFICAR Y CREAR LA BASE DE DATOS SI NO EXISTE (Multicliente Cloud)
        if db_a_usar != "control_central":
            try:
                conn_temp = mysql.connector.connect(
                    host="gateway01.us-east-1.prod.aws.tidbcloud.com",
                    port=4000,
                    user="4K4VAw4t4ZPFUTF.root",
                    password="OhAcM2lizBMDXDgD",
                    database="control_central",
                    use_pure=True,
                    connect_timeout=10,
                    ssl_verify_cert=False,
                    ssl_disabled=False
                )
                cursor_temp = conn_temp.cursor()
                cursor_temp.execute(f"CREATE DATABASE IF NOT EXISTS `{db_a_usar}`;")
                cursor_temp.close()
                conn_temp.close()
            except Exception as ex:
                print(f"Aviso al asegurar BD de cliente: {ex}")

        # 2. VALIDAR CONEXIÓN EXISTENTE EN SESSION_STATE Y FORZAR EL CAMBIO DE ESQUEMA SI ES NECESARIO
        # 2. VALIDAR CONEXIÓN EXISTENTE EN SESSION_STATE
        if "conn" in st.session_state and st.session_state.conn is not None:
            try:
                if st.session_state.conn.is_connected():
                    cursor_test = st.session_state.conn.cursor()
                    cursor_test.execute("SELECT DATABASE()")
                    res = cursor_test.fetchone()
                    db_actual_en_servidor = res[0] if res else None
                    cursor_test.close()
                    
                    # Si la base de datos es exactamente la misma, la reutilizamos sin miedo
                    if db_actual_en_servidor == db_a_usar:
                        return st.session_state.conn
                    else:
                        # Si cambió de cliente, cerramos la vieja para obligar a abrir una limpia abajo
                        st.session_state.conn.close()
                        st.session_state.conn = None
            except Exception:
                st.session_state.conn = None
      
        # 3. CONEXIÓN OFICIAL A LA BASE DE DATOS REQUERIDA
        st.session_state.conn = mysql.connector.connect(
            host="gateway01.us-east-1.prod.aws.tidbcloud.com",
            port=4000,
            user="4K4VAw4t4ZPFUTF.root",
            password="OhAcM2lizBMDXDgD",
            database=db_a_usar,
            use_pure=True,
            connect_timeout=10,
            ssl_verify_cert=False,
            ssl_disabled=False
        )
        return st.session_state.conn
        
    except Exception as e:
        st.error(f"❌ Error al conectar a la base de datos '{db_a_usar}': {e}")
        print(f"ERROR REAL DE CONEXIÓN: {e}")
        st.session_state.conn = None
        return None


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
            if not conn.is_connected():
                conn = conectar_db()
                
            cursor = conn.cursor(dictionary=True)
            # Buscamos al usuario en la base de datos
            cursor.execute("SELECT * FROM usuarios WHERE usuario = %s", (user,))
            user_data = cursor.fetchone()
            break 
        except Exception as e:
            if intento == 0:
                try:
                    conn.reconnect(attempts=3, delay=2)
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
    
    # Obtenemos la clave de la base de datos de forma segura
    clave_en_bd = user_data.get('clave_hash') or user_data.get('password')
    login_exitoso = False
    
    if clave_en_bd:
        password_bytes = password.encode('utf-8')
        # Verificamos si es un hash de bcrypt
        if str(clave_en_bd).startswith('$2b$'):
            try:
                if bcrypt.checkpw(password_bytes, str(clave_en_bd).encode('utf-8')):
                    login_exitoso = True
            except Exception as ex:
                st.error(f"Error al validar hash: {ex}")
        else:
            # Si está en texto plano
            if password == str(clave_en_bd):
                login_exitoso = True
                # Intentamos actualizar a hash de forma silenciosa para mejorar seguridad
                try:
                    salt = bcrypt.gensalt()
                    nuevo_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
                    cursor.execute("UPDATE usuarios SET clave_hash = %s WHERE id = %s", (nuevo_hash, user_data['id']))
                    conn.commit()
                except:
                    pass
    
    try:
        if cursor:
            cursor.close()
    except:
        pass
    
    if login_exitoso:
        # Aseguramos llaves por defecto para que la sesión no explote
        if 'rol' not in user_data or not user_data['rol']:
            user_data['rol'] = 'admin'
        if 'cliente_id' not in user_data:
            user_data['cliente_id'] = None
        return user_data
    else:
        return None


def login_screen():
    # --- ESTILOS CSS PROFESIONALES ---
    st.markdown("""
        <style>
        /* Contenedor principal */
        .stApp {
            background-color: #f8fafc;
        }
        /* Tarjeta de Login */
        .login-box {
            background-color: white;
            padding: 2rem;
            border-radius: 15px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
            border: 1px solid #e2e8f0;
            margin-bottom: 20px;
        }
        /* Botón estilo corporativo */
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
        /* Ajuste de etiquetas de inputs */
        label {
            font-weight: 500 !important;
            color: #475569 !important;
        }
        </style>
    """, unsafe_allow_html=True) # <-- CORREGIDO AQUÍ

    def play_success_sound():
        # Usamos un sonido de "Ding" corto y profesional
        # Este link es directo a un archivo pequeño
        audio_url = "https://www.myinstants.com/media/sounds/ding-sound-effect_1.mp3"
        
        # El truco: Inyectamos un iframe invisible que fuerza el play
        sound_html = f"""
            <iframe src="{audio_url}" allow="autoplay" style="display:none"></iframe>
            <audio autoplay>
                <source src="{audio_url}" type="audio/mpeg">
            </audio>
        """
        st.markdown(sound_html, unsafe_allow_html=True)

    # --- DISEÑO DEL FRAME ---
    _, col_center, _ = st.columns([1, 1.5, 1])

    with col_center:
        st.write("") # Espaciado superior
        st.write("")
        
        with st.container():
            st.markdown('<div class="login-box">', unsafe_allow_html=True)
            
            # Encabezado con Marketing
            st.image("https://cdn-icons-png.flaticon.com/512/5164/5164023.png", width=60)
            st.subheader("Auditoría Inteligente")
            st.caption("Bienvenido al ecosistema contable de Carlos Rodriguez")
            
            # Inputs limpios
            user = st.text_input("Usuario", placeholder="ej: admin_kd", key="user_input")
            password = st.text_input("Contraseña", type="password", placeholder="••••••••", key="pass_input")
            
            if st.button("Ingresar al Portal"):
                # Llamamos a tu función de base de datos
                conexion_activa = conectar_db()
                res = verificar_usuario(conexion_activa, user, password)
                
                if res:
                    play_success_sound()
                    # Mensaje Pro
                    st.toast(f"¡Acceso Concedido!", icon="🔒")
                    st.success(f"🚀 Has hecho login como **{res['rol'].upper()}**")
                    
                    # --- GUARDAMOS EL ESTADO CORRECTAMENTE ---
                    st.session_state['logueado'] = True
                    st.session_state['usuario'] = user
                    st.session_state['rol'] = res['rol']
                    
                    # AQUÍ ESTÁ LA CLAVE: Guardamos el ID real de la tabla usuarios (res['id'])
                    # y dejamos cliente_id por si lo necesitas para otra cosa
                    st.session_state['user_id'] = res['id']          
                    st.session_state['cliente_id'] = res.get('cliente_id') 
                    
                    time.sleep(1.5) # Pausa para que se vea el mensaje y suene la música
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas")
            
            st.markdown('</div>', unsafe_allow_html=True)

# Lógica de arranque
if 'logueado' not in st.session_state:
    login_screen()
    st.stop()


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
                    df_cli = pd.read_sql(query_cli, conn)
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
        df_usuarios = pd.read_sql(query_view, conn)
        st.dataframe(df_usuarios, use_container_width=True)
    except Exception:
        st.info("No hay usuarios registrados todavía.")

    # 3. VISOR DE AUDITORÍA INTEGRADO
    st.divider()
    st.subheader("🕵️‍♂️ Monitoreo de Interacciones (Logs)")
    
    if st.button("🔄 Refrescar Bitácora"):
        st.rerun()
        
    try:
        query_logs = "SELECT * FROM logs_auditoria ORDER BY fecha DESC LIMIT 100"
        df_logs = pd.read_sql(query_logs, conn)
        
        if not df_logs.empty:
            st.dataframe(df_logs, use_container_width=True)
        else:
            st.info("No se han detectado interacciones todavía.")
    except Exception as e:
        st.error(f"Error cargando logs: {e}")


@st.cache_data(ttl=300)
def obtener_historico_utilidad(db, f_inicio=None, f_fin=None):
    # Nota: Como usa caché, la conexión la abrimos y cerramos de forma local y segura aquí dentro
    conn = conectar_db(db)
    df_default = pd.DataFrame({'utilidad_mensual': [0.0]})
    
    if not conn:
        return df_default
    
    if f_inicio is not None and f_fin is None:
        f_fin = f_inicio
        f_inicio = None

    if f_fin is None:
        import datetime
        f_fin = datetime.date.today()
    
    fecha_fin_str = f_fin.strftime('%Y-%m-%d') if hasattr(f_fin, 'strftime') else str(f_fin).split()[0]

    if f_inicio is not None:
        fecha_inicio_str = f_inicio.strftime('%Y-%m-%d') if hasattr(f_inicio, 'strftime') else str(f_inicio).split()[0]
    else:
        partes = fecha_fin_str.split('-')
        fecha_inicio_str = f"{partes[0]}-{partes[1]}-01"
    
    # Optimizamos la consulta quitando DATE() para que use índices de fecha en MySQL
    query = f"""
        SELECT 
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '4%' THEN haber ELSE 0 END), 0) as ing_haber,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '4%' THEN debe ELSE 0 END), 0) as ing_debe,
            
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '5%' THEN debe ELSE 0 END), 0) as cos_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '5%' THEN haber ELSE 0 END), 0) as cos_haber,
            
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '6%' THEN debe ELSE 0 END), 0) as gas_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '6%' THEN haber ELSE 0 END), 0) as gas_haber,

            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '7%' THEN haber ELSE 0 END), 0) as oing_haber,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '7%' THEN debe ELSE 0 END), 0) as oing_debe,
            
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '8%' THEN debe ELSE 0 END), 0) as oeg_debe,
            COALESCE(SUM(CASE WHEN plan_cuentas LIKE '8%' THEN haber ELSE 0 END), 0) as oeg_haber
        FROM `{db}`.asientos_contables 
        WHERE fecha >= %s AND fecha <= %s
    """
    
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, (fecha_inicio_str, fecha_fin_str))
        resultados = cursor.fetchall()

        if not resultados:
            return df_default
            
        df = pd.DataFrame(resultados)
        
        if df.empty or df.isnull().all().all():
            return df_default
            
        df = df.fillna(0)

        ingresos = float(df['ing_haber'].iloc[0]) - float(df['ing_debe'].iloc[0])
        costos = float(df['cos_debe'].iloc[0]) - float(df['cos_haber'].iloc[0])
        gastos = abs(float(df['gas_debe'].iloc[0]) - float(df['gas_haber'].iloc[0]))
        otros_ingresos = float(df['oing_haber'].iloc[0]) - float(df['oing_debe'].iloc[0])
        otros_egresos = abs(float(df['oeg_debe'].iloc[0]) - float(df['oeg_haber'].iloc[0]))

        utilidad_neta = ingresos - costos - gastos + otros_ingresos - otros_egresos
        
        df['utilidad_mensual'] = utilidad_neta
        return df
        
    except Exception as e:
        print(f"❌ Error al calcular la utilidad para {fecha_inicio_str} al {fecha_fin_str}: {e}")
        return df_default
        
    finally:
        cursor.close()
        conn.close()



@st.cache_data(ttl=300)
def _obtener_datos_sidebar_cache():
    """Consulta optimizada y cacheada para evitar latencia en la nube"""
    try:
        conn_debug = conectar_db()
        if conn_debug:
            df_sidebar = pd.read_sql(
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
            df = pd.read_sql(query, conn)
            if df.empty or 'db_nombre' not in df.columns:
                return []
            return df['db_nombre'].dropna().astype(str).tolist()
            
        # 2. Si es cliente, buscamos su db_nombre en la tabla usuarios
        else:
            query = """
                SELECT db_nombre FROM usuarios 
                WHERE id = %s OR cliente_id = %s
            """
            df = pd.read_sql(query, conn, params=(user_id, user_id))
            
            # Si viene vacío, intentamos buscar por el nombre de usuario de la sesión
            if df.empty or 'db_nombre' not in df.columns or pd.isna(df['db_nombre'].iloc[0]):
                usuario_actual = st.session_state.get('usuario')
                if usuario_actual:
                    conn_res = conectar_db()
                    if conn_res:
                        df = pd.read_sql("SELECT db_nombre FROM usuarios WHERE usuario = %s", conn_res, params=(usuario_actual,))
            
            if df.empty or 'db_nombre' not in df.columns or pd.isna(df['db_nombre'].iloc[0]):
                return []
                
            db_asignada = str(df['db_nombre'].iloc[0])
            return [db_asignada]
            
    except Exception as e:
        st.sidebar.error(f"❌ Error al obtener la empresa del usuario: {e}")
        return []
        
    finally:
        # Garantizamos que ambas conexiones se cierren siempre, evitando fugas de memoria
        if conn and conn.is_connected():
            conn.close()
        if conn_res and conn_res.is_connected():
            conn_res.close()



def obtener_saldos_acumulados(conexion, fecha_corte, nombre_db):
    if not conexion:
        print("❌ Error: No hay conexión activa en obtener_saldos_acumulados")
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    
    cur = conexion.cursor(dictionary=True)
    
    try:
        # Consulta unificada para traer todo en un solo viaje a MySQL y aligerar la carga
        query = """
            SELECT 
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '1%' THEN (debe - haber) ELSE 0 END), 0) as activo,
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '2%' THEN (haber - debe) ELSE 0 END), 0) as pasivo,
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '3%' THEN (haber - debe) ELSE 0 END), 0) as patrimonio
            FROM (
                SELECT plan_cuentas, debe, haber FROM saldos_iniciales
                UNION ALL
                SELECT plan_cuentas, debe, haber FROM asientos_contables WHERE fecha <= %s
            ) as todo_el_acumulado
        """
        
        cur.execute(query, (fecha_corte,))
        resultado = cur.fetchone()
        
        if resultado:
            return {
                "activo": float(resultado.get('activo', 0) or 0),
                "pasivo": float(resultado.get('pasivo', 0) or 0),
                "patrimonio": float(resultado.get('patrimonio', 0) or 0)
            }
            
    except Exception as e:
        print(f"⚠️ Error al calcular saldos acumulados en {nombre_db}: {e}")
        
    finally:
        # Nos aseguramos de cerrar el cursor siempre para liberar memoria y evitar lentitud al cerrar sesión
        cur.close()
        
    return {"activo": 0, "pasivo": 0, "patrimonio": 0}


def gestionar_sidebar():
    # 1. Recuperar rol e identificador de sesión
    user_rol = str(st.session_state.get('rol', 'admin')).strip().lower()
    user_id = st.session_state.get('user_id', st.session_state.get('cliente_id', 'N/A'))

    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=100)
        st.header("Panel de Auditoría")

        # --- INSIGNIA DE DUEÑO Y ADMINISTRADOR ---
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

        st.markdown("---")
        
        # Generar un identificador de sesión único la primera vez si no existe
        if "logout_key_counter" not in st.session_state:
            st.session_state["logout_key_counter"] = 0

        # Usar un key completamente dinámico e irrepetible en cada render
        dynamic_key = f"btn_logout_{st.session_state['logout_key_counter']}"
        
        if st.button("🚪 Cerrar Sesión", key=dynamic_key):
            # Incrementar contador para invalidar el ID actual en el siguiente ciclo
            st.session_state["logout_key_counter"] += 1
            for key in list(st.session_state.keys()):
                if key != "logout_key_counter":
                    del st.session_state[key]
            st.rerun()

        # --- Navegación ---
        if user_rol == 'admin':
            menu = st.radio("Navegación", ["📊 Auditoría Contable", "⚙️ Gestión de Usuarios"], key="menu_nav")
        else:
            menu = "📊 Auditoría Contable"

        st.divider()

        # --- Selección de Empresa ---
        if menu == "📊 Auditoría Contable":
            df_sidebar = _obtener_datos_sidebar_cache() if '_obtener_datos_sidebar_cache' in globals() else pd.DataFrame()

            lista_db_permitidas = []
            if 'obtener_todas_las_empresas' in globals() and callable(globals()['obtener_todas_las_empresas']):
                try:
                    lista_db_permitidas = obtener_todas_las_empresas(user_rol=user_rol, user_id=user_id) or []
                except Exception as e:
                    st.error(f"❌ Error al consultar el listado de empresas: {e}")

            if not lista_db_permitidas:
                db_en_sesion = st.session_state.get('db_a_conectar')
                if db_en_sesion:
                    lista_db_permitidas = [db_en_sesion]
                else:
                    lista_db_permitidas = ['pedacito_de_cielo_ca']
                    st.session_state['db_a_conectar'] = 'pedacito_de_cielo_ca'

            if user_rol == 'admin' and not df_sidebar.empty:
                df_filtrado = df_sidebar
            else:
                if not df_sidebar.empty and 'db_nombre' in df_sidebar.columns:
                    df_filtrado = df_sidebar[df_sidebar['db_nombre'].isin(lista_db_permitidas)]
                else:
                    df_filtrado = pd.DataFrame()

            if df_filtrado.empty:
                db_actual_emergencia = lista_db_permitidas[0]
                df_filtrado = pd.DataFrame({
                    'id': [1],
                    'nombre_empresa': ['REPRESENTACIONES PEDACITO DE CIELO, C.A.' if db_actual_emergencia == 'pedacito_de_cielo_ca' else db_actual_emergencia],
                    'db_nombre': [db_actual_emergencia],
                    'nombre_usuario': ['No asignado']
                })

            nombres_empresas = df_filtrado['nombre_empresa'].tolist()
            db_nombres = df_filtrado['db_nombre'].tolist()

            if 'db_a_conectar' not in st.session_state or st.session_state['db_a_conectar'] not in db_nombres:
                st.session_state['db_a_conectar'] = db_nombres[0]

            empresa_previa_db = st.session_state.get('db_a_conectar')
            nombre_inicial = nombres_empresas[0]
            
            if empresa_previa_db in db_nombres:
                idx = db_nombres.index(empresa_previa_db)
                nombre_inicial = nombres_empresas[idx]

            if user_rol == 'admin':
                nombre_seleccionado = st.selectbox(
                    "Seleccione Empresa", 
                    options=nombres_empresas, 
                    index=nombres_empresas.index(nombre_inicial) if nombre_inicial in nombres_empresas else 0,
                    key="selector_empresa"
                )
            else:
                nombre_seleccionado = nombre_inicial
                st.markdown(f"**🏢 Empresa Asignada:**")
                st.info(f"{str(nombre_seleccionado).upper()}")

            fila_seleccionada = df_filtrado[df_filtrado['nombre_empresa'] == nombre_seleccionado]
            if fila_seleccionada.empty:
                fila_seleccionada = df_filtrado.iloc[[0]]

            datos_sel = fila_seleccionada.iloc[0]
            db_seleccionada = str(datos_sel['db_nombre']).strip()
            
            st.session_state['DB_ACTUAL'] = db_seleccionada
            st.session_state['db_a_conectar'] = db_seleccionada
            st.session_state['CLIENTE_NOMBRE'] = nombre_seleccionado
            if 'id' in datos_sel:
                st.session_state['cliente_id_seleccionado'] = int(datos_sel['id'])

    return menu

# ==========================================
# EJECUCIÓN PRINCIPAL EN EL SCRIPT
# ==========================================
menu_lateral = gestionar_sidebar()

# 2. A partir de aquí, evalúas las opciones basándote en 'menu_lateral' o 'st.session_state'
if menu_lateral == "⚙️ Gestión de Usuarios":    
    try:
        conn = conectar_db() 
        if conn and conn.is_connected():
            panel_administracion(conn)
            conn.close()
        else:
            st.error("🔌 No se pudo establecer conexión con el servidor MySQL.")
    except Exception as e:
        st.error(f"Error al acceder a la gestión central: {e}")
    st.stop()

if menu_lateral == "📊 Auditoría Contable":
    with st.sidebar:
        st.divider()
        st.subheader("Módulos")
        
        nombre_sel = st.session_state.get('CLIENTE_NOMBRE', '')
        modulos_disponibles = [
            "🏠 Inicio", "📂 Plan de Cuentas", "📝 Asientos Contables", 
            "📖 Mayor Analítico", "📊 Estados Financieros", "📚 Libros Fiscales", "👤 Proveedores"
        ]

        if "PEDACITO" in str(nombre_sel).upper() and "CLIELO" in str(nombre_sel).upper():
            modulos_disponibles.append("🧁 Inventarios")

        opcion_menu = st.selectbox("📂 SELECCIONE UN MÓDULO", modulos_disponibles, key="opcion_menu_auditoria")

        # Filtros de fecha en la barra lateral
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


if "🏠 Inicio" in opcion_menu:
    
    gestionar_sidebar()

    # --- 2. GESTIÓN DE ROL Y BASE DE DATOS OBJETIVO ---
    user_rol = st.session_state.get('rol')
    user_cliente_id = st.session_state.get('cliente_id')

    conn_ctrl = conectar_db()
    db_objetivo = None
    
    if conn_ctrl:
        try:
            if user_rol == 'admin':
                db_objetivo = st.session_state.get('DB_ACTUAL')
                if not db_objetivo or db_objetivo == 'No seleccionada':
                    query = "SELECT * FROM clientes LIMIT 1"
                    df_temp = pd.read_sql(query, conn_ctrl)
                    if not df_temp.empty:
                        col_bd = next((c for c in df_temp.columns if 'bd' in c.lower() or 'base' in c.lower() or 'schema' in c.lower()), df_temp.columns[-1])
                        db_objetivo = str(df_temp[col_bd].iloc[0])
            else:
                query = f"SELECT * FROM clientes WHERE id = {user_cliente_id}"
                df_temp = pd.read_sql(query, conn_ctrl)
                if not df_temp.empty:
                    col_bd = next((c for c in df_temp.columns if 'bd' in c.lower() or 'base' in c.lower() or 'schema' in c.lower()), df_temp.columns[-1])
                    db_objetivo = str(df_temp[col_bd].iloc[0])
        except Exception as e:
            st.error(f"❌ Error al resolver la base de datos del usuario: {e}")
            st.stop()
        finally:
            conn_ctrl.close()

    if not db_objetivo:
        st.error("❌ No se encontró una base de datos asignada o válida.")
        st.stop()

    st.session_state['DB_ACTUAL'] = db_objetivo
    st.session_state['db_a_conectar'] = db_objetivo

    # --- 3. CONEXIÓN ESTRICTA A LA BD DEL CLIENTE ---
    if 'conn' not in st.session_state or st.session_state.get('ultima_db_conectada') != db_objetivo or st.session_state.conn is None:
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

    # Verificación de estado y ping de la conexión
    conn = st.session_state.conn
    try:
        conn.ping(reconnect=True, attempts=3, delay=1)
        if db_objetivo and db_objetivo != "control_central":
            with conn.cursor() as cursor:
                cursor.execute(f"USE `{db_objetivo}`")
    except Exception as e:
        st.warning(f"La conexión se perdió o la BD {db_objetivo} no es accesible. Reconectando...")
        st.session_state.conn = None 
        st.rerun()

    # --- 4. CÁLCULO DE FECHAS REACTIVO Y SEGURO ---
    # Al ejecutarse después del sidebar, ya lee correctamente el mes seleccionado por ti.
    dic_meses = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
        "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
        "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
    }
    meses_lista = list(dic_meses.keys())
    
    anio_f = int(st.session_state.get('año_seleccionado', datetime.datetime.now().year))
    mes_nombre_f = st.session_state.get('mes_seleccionado', meses_lista[datetime.datetime.now().month - 1])
    
    m_idx = dic_meses.get(mes_nombre_f, 1)
    
    # Cálculo exacto del último día del mes (ej. 28 para febrero)
    ultimo_dia = calendar.monthrange(anio_f, m_idx)[1]

    f_inicio_global = datetime.date(anio_f, m_idx, 1)
    f_fin_global = datetime.date(anio_f, m_idx, ultimo_dia)

    fecha_inicio_str = f_inicio_global.strftime('%Y-%m-%d')
    fecha_fin_str = f_fin_global.strftime('%Y-%m-%d')

    # --- 5. RENDERIZADO VISUAL Y DE KPIS ---
    st.title(f"📊 Auditoría Profesional: {db_objetivo}")
    st.markdown(f"**Período de Análisis:** {f_inicio_global.strftime('%d/%m/%Y')} al {f_fin_global.strftime('%d/%m/%Y')}")
    st.divider()

    col_kpi, col_btn = st.columns([0.8, 0.2])
    with col_kpi:
        st.subheader("Indicadores Financieros en Tiempo Real")

    with st.spinner(f'Comunicando con MySQL para {db_objetivo}...'):
        if conn and conn.is_connected():
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
    if not df_utilidad.empty and 'utilidad_mensual' in df_utilidad.columns:
        u_v = df_utilidad['utilidad_mensual'].iloc[0]

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
