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


# 1. ESTO VA AQUÍ, AL PURO PRINCIPIO
st.set_page_config(
    page_title="Mi App Contable",
    layout="wide",
    initial_sidebar_state="expanded"
)


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
                    connect_timeout=30,  # Aumentado para evitar timeouts de red inicial
                    read_timeout=60,     # Límite de lectura extendido
                    write_timeout=60,
                    ssl_verify_cert=False,
                    ssl_disabled=False
                )
                cursor_temp = conn_temp.cursor()
                cursor_temp.execute(f"CREATE DATABASE IF NOT EXISTS `{db_a_usar}`;")
                cursor_temp.close()
                conn_temp.close()
            except Exception as ex:
                print(f"Aviso al asegurar BD de cliente: {ex}")

        # 2. VALIDAR CONEXIÓN EXISTENTE EN SESSION_STATE
        if "conn" in st.session_state and st.session_state.conn is not None:
            try:
                # Forzar verificación de salud con ping y auto-reconexión si expiró
                st.session_state.conn.ping(reconnect=True, attempts=3, delay=1)
                
                if st.session_state.conn.is_connected():
                    cursor_test = st.session_state.conn.cursor()
                    cursor_test.execute("SELECT DATABASE()")
                    res = cursor_test.fetchone()
                    db_actual_en_servidor = res[0] if res else None
                    cursor_test.close()
                    
                    # Si la base de datos es la misma, la reutilizamos con seguridad
                    if db_actual_en_servidor == db_a_usar:
                        return st.session_state.conn
                    else:
                        st.session_state.conn.close()
                        st.session_state.conn = None
            except Exception:
                st.session_state.conn = None
    
        # 3. CONEXIÓN OFICIAL CON PARÁMETROS ANTITIMEOUT AMPLIADOS
        st.session_state.conn = mysql.connector.connect(
            host="gateway01.us-east-1.prod.aws.tidbcloud.com",
            port=4000,
            user="4K4VAw4t4ZPFUTF.root",
            password="OhAcM2lizBMDXDgD",
            database=db_a_usar,
            use_pure=True,
            connect_timeout=30,  # Tiempo de espera ampliado para conexiones lentas
            read_timeout=60,     # Evita el error 3024 en consultas largas
            write_timeout=60,    # Evita cortes en escrituras masivas
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
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    
    db_segura = str(nombre_db).strip()
    cur = conexion.cursor(dictionary=True)
    
    try:
        cur.execute(f"USE `{db_segura}`")
        
        # Query limpio y directo tal como lo tenías funcionando
        cur.execute(f"""
            SELECT 
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '1%' THEN (debe - haber) ELSE 0 END), 0) as activo,
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '2%' THEN (haber - debe) ELSE 0 END), 0) as pasivo,
                COALESCE(SUM(CASE WHEN plan_cuentas LIKE '3%' THEN (haber - debe) ELSE 0 END), 0) as patrimonio
            FROM asientos_contables 
            WHERE fecha <= %s
        """, (fecha_corte,))
        
        resultado = cur.fetchone()
        return resultado if resultado else {"activo": 0, "pasivo": 0, "patrimonio": 0}

    except Exception as e:
        print(f"Error: {e}")
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    finally:
        cur.close()


@st.cache_data(ttl=300)
def obtener_salud_fiscal(f_inicio, f_fin, db):
    conn = conectar_db(db)
    
    default_res = {
        "ingresos_exentas": 0, "ingresos_gravados": 0, "compras_exentas": 0,
        "compras_16": 0, "DPP1": 0, "comisiones_bancarias1": 0, "gastos_personales1": 0,
        "otros_ingresos": 0, "otros_egresos": 0,
        "iva_debito_fiscal": 0, "iva_por_pagar": 0, "retencion_iva_compras": 0, 
        "pagos_anticipados_islr": 0, "retencion_islr_proveedores": 0, "islr_pagar": 0
    }
    
    if not conn:
        return default_res

    if hasattr(f_inicio, 'strftime'):
        f_inicio_str = f_inicio.strftime('%Y-%m-%d') + " 00:00:00"
    else:
        f_inicio_str = str(f_inicio).split()[0] + " 00:00:00"

    if hasattr(f_fin, 'strftime'):
        fecha_str = f_fin.strftime('%Y-%m-%d') + " 23:59:59"
    else:
        fecha_str = str(f_fin).split()[0] + " 23:59:59"

    if db == 'kingdirver_ca':
        dpp_query = """
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.020%' THEN haber ELSE 0 END) as DPP_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.020%' THEN debe ELSE 0 END) as DPP_debe
        """
    else:
        dpp_query = """
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03%' 
                     AND plan_cuentas NOT LIKE '6.1.1.03.013%' 
                     AND plan_cuentas NOT LIKE '6.1.1.03.021%' 
                     AND plan_cuentas NOT LIKE '6.1.1.03.022%' 
                THEN haber ELSE 0 END) as DPP_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03%' 
                     AND plan_cuentas NOT LIKE '6.1.1.03.013%' 
                     AND plan_cuentas NOT LIKE '6.1.1.03.021%' 
                     AND plan_cuentas NOT LIKE '6.1.1.03.022%' 
                THEN debe ELSE 0 END) as DPP_debe
        """

    query = f"""
        SELECT 
            COUNT(*) as total_registros_rango,
            SUM(CASE WHEN plan_cuentas LIKE '4.1.1.01.001%' THEN haber ELSE 0 END) as ex_haber,
            SUM(CASE WHEN plan_cuentas LIKE '4.1.1.01.001%' THEN debe ELSE 0 END) as ex_debe,
            SUM(CASE WHEN plan_cuentas LIKE '4.1.1.01.002%' THEN haber ELSE 0 END) as gr_haber,
            SUM(CASE WHEN plan_cuentas LIKE '4.1.1.01.002%' THEN debe ELSE 0 END) as gr_debe,
            SUM(CASE WHEN plan_cuentas LIKE '5.1.1.01.001%' THEN debe ELSE 0 END) as compras_exentas,
            SUM(CASE WHEN plan_cuentas LIKE '5.1.1.01.002%' THEN debe ELSE 0 END) as compras_16,
            {dpp_query},
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.013%' THEN haber ELSE 0 END) as comisiones_bancarias_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.013%' THEN debe ELSE 0 END) as comisiones_bancarias_debe,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.021%' THEN haber ELSE 0 END) as refrigerios_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.021%' THEN debe ELSE 0 END) as refrigerios_debe,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.022%' THEN haber ELSE 0 END) as representacion_haber,
            SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.022%' THEN debe ELSE 0 END) as representacion_debe,
            SUM(CASE WHEN plan_cuentas LIKE '7.1.1.01%' THEN haber ELSE 0 END) as otros_ingresos_haber,
            SUM(CASE WHEN plan_cuentas LIKE '7.1.1.07%' THEN debe ELSE 0 END) as otros_ingresos_debe,
            SUM(CASE WHEN plan_cuentas LIKE '8.1.1.01%' THEN haber ELSE 0 END) as otros_egresos_haber,
            SUM(CASE WHEN plan_cuentas LIKE '8.1.1.01%' THEN debe ELSE 0 END) as otros_egresos_debe,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.001%' THEN haber ELSE 0 END) as iva_debito_fiscal,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.002%' THEN haber ELSE 0 END) as iva_por_pagar,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.003%' THEN haber ELSE 0 END) as retencion_iva_compras,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.004%' THEN haber ELSE 0 END) as pagos_anticipados_islr,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.005%' THEN haber ELSE 0 END) as retencion_islr_hab,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.005%' THEN debe ELSE 0 END) as retencion_islr_deb,
            SUM(CASE WHEN plan_cuentas LIKE '2.1.2.01.006%' THEN haber ELSE 0 END) as islr_pagar
        FROM `{db}`.asientos_contables
        WHERE fecha >= %s AND fecha <= %s
    """

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (f_inicio_str, fecha_str))
        res = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if res and res.get('total_registros_rango', 0) > 0:
            DPP = abs(float(res['DPP_haber'] or 0) - float(res['DPP_debe'] or 0))
            comisiones_bancarias = abs(float(res['comisiones_bancarias_haber'] or 0) - float(res['comisiones_bancarias_debe'] or 0))
            refrigerios_neto = abs(float(res['refrigerios_haber'] or 0) - float(res['refrigerios_debe'] or 0))
            representacion_neto = abs(float(res['representacion_haber'] or 0) - float(res['representacion_debe'] or 0))
            gastos_personales = refrigerios_neto + representacion_neto
            otros_ingresos_neto = float(res['otros_ingresos_haber'] or 0) - float(res['otros_ingresos_debe'] or 0)
            otros_egresos_neto = float(res['otros_egresos_haber'] or 0) - float(res['otros_egresos_debe'] or 0)
            retencion_islr_proveedores = float(res['retencion_islr_hab'] or 0) - float(res['retencion_islr_deb'] or 0)
            
            return {
                "ingresos_exentas": float(res['ex_haber'] if res['ex_haber'] is not None else 0) - float(res['ex_debe'] if res['ex_debe'] is not None else 0),
                "ingresos_gravados": float(res['gr_haber'] or 0) - float(res['gr_debe'] or 0),
                "compras_exentas": float(res['compras_exentas'] or 0),
                "compras_16": float(res['compras_16'] or 0),
                "DPP1": DPP, 
                "comisiones_bancarias1": comisiones_bancarias, 
                "gastos_personales1": gastos_personales,
                "otros_ingresos": otros_ingresos_neto, 
                "otros_egresos": otros_egresos_neto,
                "iva_debito_fiscal": float(res['iva_debito_fiscal'] or 0),
                "iva_por_pagar": float(res['iva_por_pagar'] or 0),
                "retencion_iva_compras": float(res['retencion_iva_compras'] or 0),
                "pagos_anticipados_islr": float(res['pagos_anticipados_islr'] or 0),
                "retencion_islr_proveedores": retencion_islr_proveedores,
                "islr_pagar": float(res['islr_pagar'] or 0)
            }
            
    except Exception as e:
        print(f"Error en SQL: {e}")
    
    return default_res



@st.cache_data(ttl=300)
def obtener_datos_pie(db, fecha_inicio, fecha_fin):
    df_vacio = pd.DataFrame(columns=['nombre', 'Saldo Final'])
    
    conn = conectar_db(db)
    if not conn:
        return df_vacio
        
    query = f"""
        SELECT 
            descripcion as nombre,
            SUM(debe) as "Saldo Final"
        FROM `{db}`.asientos_contables 
        WHERE plan_cuentas LIKE '6%'
        AND fecha >= %s AND fecha <= %s
        GROUP BY descripcion
        HAVING SUM(debe) > 0
        ORDER BY 2 DESC
        LIMIT 10
    """
    
    try:
        with conn.cursor() as cursor:
            df = pd.read_sql(query, conn, params=(fecha_inicio, fecha_fin))
        return df if not df.empty else df_vacio
    except Exception as e:
        print(f"Error en obtener_datos_pie: {e}")
        return df_vacio
    finally:
        if conn and conn.is_connected():
            conn.close()


@st.cache_data(ttl=300)
def obtener_datos_barras(db, fecha_inicio, fecha_fin):
    df_vacio = pd.DataFrame(columns=['Categoría', 'Monto'])
    
    conn = conectar_db(db)
    if not conn:
        return df_vacio
        
    query = f"""
        SELECT 
            CASE 
                WHEN plan_cuentas LIKE '4%' THEN 'Ingresos' 
                WHEN plan_cuentas LIKE '5%' THEN 'Egresos' 
                ELSE 'Otros' 
            END as Categoría, 
            SUM(haber - debe) as Monto 
        FROM `{db}`.asientos_contables 
        WHERE fecha >= %s AND fecha <= %s
        GROUP BY 1
    """
    
    try:
        # Ejecutamos la lectura asegurando parámetros seguros
        df = pd.read_sql(query, conn, params=(fecha_inicio, fecha_fin))
        return df if not df.empty else df_vacio
    except Exception as e:
        print(f"Error en obtener_datos_barras: {e}")
        return df_vacio
    finally:
        # Garantía absoluta de cierre de conexión para proteger el rendimiento de MySQL
        if conn and conn.is_connected():
            conn.close()


@st.cache_data(ttl=300)
def obtener_historico_utilidad(db, f_inicio=None, f_fin=None):
    df_default = pd.DataFrame({'utilidad_mensual': [0.0]})
    
    # Manejo de fechas por defecto antes de conectar
    if f_inicio is not None and f_fin is None:
        f_fin = f_inicio
        f_inicio = None

    if f_fin is None:
        import datetime
        f_fin = datetime.date.today()
    
    if hasattr(f_fin, 'strftime'):
        fecha_fin_str = f_fin.strftime('%Y-%m-%d')
    else:
        fecha_fin_str = str(f_fin).split()[0]

    if f_inicio is not None:
        if hasattr(f_inicio, 'strftime'):
            fecha_inicio_str = f_inicio.strftime('%Y-%m-%d')
        else:
            fecha_inicio_str = str(f_inicio).split()[0]
    else:
        partes = fecha_fin_str.split('-')
        fecha_inicio_str = f"{partes[0]}-{partes[1]}-01"

    # Conectamos de forma segura y local para la función cacheada
    conn = conectar_db(db)
    if not conn:
        return df_default
    
    # Consulta optimizada (Sin DATE(fecha) para aprovechar los índices de MySQL)
    query = f"""
        SELECT 
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%' THEN haber ELSE 0 END), 0) as ing_haber,
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%' THEN debe ELSE 0 END), 0) as ing_debe,
            
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%' THEN debe ELSE 0 END), 0) as cos_debe,
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%' THEN haber ELSE 0 END), 0) as cos_haber,
            
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%' THEN debe ELSE 0 END), 0) as gas_debe,
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%' THEN haber ELSE 0 END), 0) as gas_haber,

            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%' THEN haber ELSE 0 END), 0) as oing_haber,
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%' THEN debe ELSE 0 END), 0) as oing_debe,
            
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%' THEN debe ELSE 0 END), 0) as oeg_debe,
            COALESCE(SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%' THEN haber ELSE 0 END), 0) as oeg_haber
        FROM `{db}`.asientos_contables 
        WHERE fecha >= %s AND fecha <= %s
    """
    
    try:
        with conn.cursor(dictionary=True) as cursor:
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
        if conn and conn.is_connected():
            conn.close()


@st.cache_data(ttl=300)
def obtener_detalle_movimientos_banco(db, f_i, f_f):
    """
    Función para obtener el detalle de movimientos de la cuenta 1.1.1.02 de forma segura y cacheada.
    """
    df_vacio = pd.DataFrame(columns=['fecha', 'descripcion', 'debe', 'haber'])
    
    conn = conectar_db(db)
    if not conn:
        return df_vacio
        
    query = f"""
        SELECT 
            fecha, 
            descripcion, 
            debe, 
            haber
        FROM `{db}`.asientos_contables
        WHERE plan_cuentas LIKE '1.1.1.02%'
        AND fecha >= %s AND fecha <= %s
        ORDER BY fecha ASC
    """
    
    try:
        df = pd.read_sql(query, conn, params=(f_i, f_f))
        return df if not df.empty else df_vacio
    except Exception as e:
        print(f"Error en obtener_detalle_movimientos_banco para {db}: {e}")
        return df_vacio
    finally:
        if conn and conn.is_connected():
            conn.close()


@st.cache_data(ttl=60) # ttl reducido para evitar saldos desactualizados
def obtener_detalle_cashea(db, f_inicio, f_fin):
    df_vacio = pd.DataFrame(columns=['fecha', 'descripcion', 'referencia', 'debe', 'haber', 'saldo'])
    conn = conectar_db(db)
    
    if not conn:
        return df_vacio
        
    try:
        # A. Saldo inicial
        query_saldo_inicial = f"SELECT SUM(haber - debe) as saldo_ant FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '2.1.3.01.001%' AND fecha < %s"
        df_ini = pd.read_sql(query_saldo_inicial, conn, params=(f_inicio,))
        saldo_inicial = float(df_ini['saldo_ant'].iloc[0] or 0.0)
        
        # B. Movimientos
        query = f"SELECT fecha, descripcion, referencia, debe, haber FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '2.1.3.01.001%' AND fecha BETWEEN %s AND %s ORDER BY fecha ASC, id ASC"
        df = pd.read_sql(query, conn, params=(f_inicio, f_fin))
        
        if df.empty:
            return df_vacio
            
        # Limpieza
        df['debe'] = pd.to_numeric(df['debe'], errors='coerce').fillna(0)
        df['haber'] = pd.to_numeric(df['haber'], errors='coerce').fillna(0)
        df['saldo'] = saldo_inicial + (df['haber'] - df['debe']).cumsum()
        return df

    except Exception as e:
        st.error(f"Error técnico al cargar movimientos: {e}") # Feedback visual para el dev
        return df_vacio
        
    finally:
        # La forma más segura de cerrar, garantizada incluso si hay errores
        if conn and conn.is_connected():
            conn.close()

def consultar_bcv_directo_sin_bd(conn=None):
    """Realiza el scraping web directo sin bucles recursivos."""
    tasa, fuente = _obtener_tasa_web_directa()
    
    # Gestionamos los logs de forma independiente si hay conexión
    if conn and conn.is_connected():
        try:
            usuario = st.session_state.get('usuario', 'Desconocido')
            registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"Usuario {usuario} consultando BCV directo. Tasa: {tasa}")
        except Exception as log_err:
            print(f"Error registrando log de BCV: {log_err}")
        finally:
            try:
                conn.ping(reconnect=True, attempts=2, delay=1)
            except Exception:
                pass
                
    return tasa, fuente


def obtener_tasa_bcv_hoy(conn=None):
    """
    Busca la tasa en la BD. Si no existe para hoy, va a la web del BCV, 
    la guarda en la BD y la retorna.
    """
    # 1. VERIFICACIÓN DE SEGURIDAD: Reconexión automática
    try:
        if conn and not conn.is_connected():
            conn.reconnect(attempts=3, delay=2)
    except Exception:
        pass 

    # Si no hay conexión válida, pasamos directo a la web
    if not conn:
        return _obtener_tasa_web_directa()

    hoy = date.today()
    cursor = None
    
    try:
        # A. Intentar abrir el cursor y verificar en BD
        cursor = conn.cursor(buffered=True)
        cursor.execute("SELECT tasa_valor FROM kingdirver_ca.tasas_diarias WHERE fecha = %s", (hoy,))
        resultado = cursor.fetchone()
        
        if resultado:
            cursor.close()
            return float(resultado[0]), "Base de Datos"
        
        cursor.close()
    except Exception:
        if cursor:
            try:
                cursor.close()
            except:
                pass

    # B. Si no está en la BD (o falló la consulta), consultamos la web directamente
    tasa_float, fuente_web = _obtener_tasa_web_directa()
    
    if tasa_float > 0 and conn:
        try:
            # Registrar log
            usuario = st.session_state.get('usuario', 'Desconocido')
            registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"El usuario {usuario} consultó la tasa del BCV")
        except Exception:
            pass 
        
        # Guardar en BD de forma segura
        try:
            cursor_ins = conn.cursor(buffered=True)
            cursor_ins.execute("""
                INSERT INTO kingdirver_ca.tasas_diarias (fecha, tasa_valor) 
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE tasa_valor = %s
            """, (hoy, tasa_float, tasa_float))
            conn.commit()
            cursor_ins.close()
        except Exception:
            pass
            
    return tasa_float, fuente_web


def _obtener_tasa_web_directa():
    """Función de scraping puro y aislado (cero recursión)."""
    url = "https://www.bcv.org.ve/"
    headers = {"User-Agent": "Mozilla/5.0..."}
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_container = soup.find('div', id='dolar')
            
            if dolar_container:
                tasa_texto = dolar_container.find('strong').text.strip()
                tasa_float = float(tasa_texto.replace(',', '.'))
                return tasa_float, "Web BCV"
    except Exception:
        pass
        
    return 0.0, "Error Web BCV"


def generar_reporte_multimoneda(conn, mes, ano, db):
    """
    Consolida saldos iniciales con los asientos contables del mes seleccionado, 
    aplicando la conversión a USD de forma segura y eficiente para cualquier empresa.
    """
    if not conn:
        return pd.DataFrame()  # Retornar un DataFrame vacío por consistencia de tipos
        
    # Validar que se haya proporcionado el nombre de la base de datos
    if not db:
        raise ValueError("Se requiere especificar el nombre de la base de datos de la empresa.")

    # Validar el nombre de la base de datos para prevenir Inyección SQL (permite letras, números y guiones bajos)
    if not db.replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos inválido: {db}")

    cursor = conn.cursor(dictionary=True)
    
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
    except Exception as e:
        print(f"Error en consulta contable para la empresa {db}: {e}")
        datos = []
    finally:
        try:
            cursor.close()
        except Exception:
            pass
            
    # Procesamiento con Pandas
    if not datos:
        return pd.DataFrame()
        
    df = pd.DataFrame(datos)
    
    # Aseguramos que los tipos de datos sean numéricos puros
    df['debe'] = pd.to_numeric(df['debe'], errors='coerce').fillna(0.0)
    df['haber'] = pd.to_numeric(df['haber'], errors='coerce').fillna(0.0)
    df['tasa_bcv'] = pd.to_numeric(df['tasa_bcv'], errors='coerce').fillna(1.0)
    
    # 🔥 Operación matemática en memoria de Python
    df['debe_usd'] = df['debe'] / df['tasa_bcv']
    df['haber_usd'] = df['haber'] / df['tasa_bcv']
    
    return df


import pandas as pd
import streamlit as st

@st.cache_data(ttl=300)
def obtener_analisis_gastos_clase5(db, f_i, f_f):
    """
    Obtiene el análisis de gastos de Clase 5 de forma segura y cacheada.
    Nota: El caché durará 5 minutos; si necesitas datos en tiempo real estricto, 
    considera quitar el decorador @st.cache_data.
    """
    # 1. Validar nombre de la base de datos para prevenir Inyección SQL
    if not db or not db.replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos inválido: {db}")

    # 2. Validar que conectar_db exista realmente
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
        df = pd.read_sql(query, conn, params=(f_i_str, f_f_str))
    except Exception as e:
        print(f"❌ Error en Clase 5: {e}")
        df = pd.DataFrame()
    finally:
        try:
            conn.close()
        except Exception:
            pass
        
    return df




@st.cache_data(ttl=300)
def obtener_analisis_gastos_clase6(db, f_i, f_f):
    """
    Obtiene gastos de Clase 6 con validación de seguridad para multi-empresa.
    """
    # 1. Validación de Seguridad (CRÍTICA)
    if not db or not db.replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos no seguro: {db}")

    conn = conectar_db(db)
    if not conn:
        return pd.DataFrame()
    
    # Asegurar hora final para que tome todo el día
    f_i_str = str(f_i).split()[0] + " 00:00:00"
    f_f_str = str(f_f).split()[0] + " 23:59:59"

    # La estructura de la query es segura gracias a los parámetros %s
    query = f"""
        SELECT 
            plan_cuentas, 
            MAX(cuenta_contable) as cuenta_contable, 
            (SUM(debe) - SUM(haber)) as total_gasto
        FROM `{db}`.asientos_contables 
        WHERE plan_cuentas LIKE '6%'
          AND fecha >= %s AND fecha <= %s
        GROUP BY plan_cuentas
        HAVING total_gasto != 0
        ORDER BY total_gasto DESC
    """
    
    try:
        df = pd.read_sql(query, conn, params=(f_i_str, f_f_str))
    except Exception as e:
        print(f"❌ Error en Clase 6 para {db}: {e}")
        df = pd.DataFrame()
    finally:
        if conn:
            conn.close()
        
    return df



@st.cache_data(ttl=300)
def obtener_historico_utilidad_acumulada(db, año, mes_limite):
    df_default = pd.DataFrame({'mes': [], 'utilidad_mensual': []})
    
    # 1. Validación de Seguridad Estricta para el nombre de la BD
    if not db or not db.replace("_", "").isalnum():
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

    # 3. Consulta 100% Segura usando Parámetros (%s)
    query = f"""
        SELECT 
            MONTH(STR_TO_DATE(fecha, '%Y-%m-%d')) as mes,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%' THEN haber ELSE 0 END) as ingresos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '4%' THEN debe ELSE 0 END) as ingresos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%' THEN haber ELSE 0 END) as costos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '5%' THEN debe ELSE 0 END) as costos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%' THEN haber ELSE 0 END) as gastos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '6%' THEN debe ELSE 0 END) as gastos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%' THEN haber ELSE 0 END) as otros_ingresos_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '7%' THEN debe ELSE 0 END) as otros_ingresos_debe,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%' THEN haber ELSE 0 END) as otros_haber,
            SUM(CASE WHEN TRIM(plan_cuentas) LIKE '8%' THEN debe ELSE 0 END) as oitros_debe
        FROM `{db}`.asientos_contables 
        WHERE YEAR(STR_TO_DATE(fecha, '%Y-%m-%d')) = %s 
          AND MONTH(STR_TO_DATE(fecha, '%Y-%m-%d')) <= %s
        GROUP BY MONTH(STR_TO_DATE(fecha, '%Y-%m-%d'))
        ORDER BY mes ASC
    """
    
    try:
        # Pasamos año y mes como parámetros seguros
        df = pd.read_sql(query, conn, params=(año, mes_limite))
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
        df = pd.read_sql(query, conn, params=(str(n_comprobante),))
        
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
    # 1. Validación estricta de seguridad para el esquema
    if not db or not str(db).strip().replace("_", "").isalnum():
        return pd.DataFrame()

    db_clean = str(db).strip().lower()

    # Validación de existencia de función conectar_db
    if 'conectar_db' not in globals() and 'conectar_db' not in locals():
        return pd.DataFrame()

    conn = conectar_db(db)
    if not conn or not conn.is_connected():
        return pd.DataFrame()

    s_fi = str(f_i).split()[0]
    s_ff = str(f_f).split()[0]
    
    df = pd.DataFrame()
    try:
        cursor = conn.cursor()
        
        # Validación segura mediante information_schema parametrizado
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
            # Query blindada con parámetros seguros
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
            df = pd.read_sql(query, conn, params=(s_fi, s_ff))
        else:
            st.warning(f"⚠️ Verificación fallida: tablas no encontradas en '{db}'.")
            
    except Exception as e:
        st.error(f"Error en la consulta de accionistas: {e}")
        df = pd.DataFrame()
    finally:
        if conn and conn.is_connected():
            try:
                conn.close()
            except:
                pass
                
    return df


@st.cache_data(ttl=300)
def obtener_comprobantes_ingresos(db, f_inicio, f_fin):
    conn = conectar_db(db)
    if not conn:
        return pd.DataFrame()
    
    try:
        query = f"""
            SELECT DISTINCT n_comprobante, fecha 
            FROM `{db}`.asientos_contables 
            WHERE plan_cuentas LIKE '7.1.1.01.001%'
            AND fecha BETWEEN %s AND %s
            ORDER BY fecha DESC, n_comprobante DESC
        """
        df = pd.read_sql(query, conn, params=(f_inicio, f_fin))
        conn.close()
        return df
    except Exception as e:
        print(f"Error al obtener comprobantes de ingresos: {e}")
        if conn:
            conn.close()
        return pd.DataFrame()


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
    """
    Consulta registros de forma segura utilizando la conexión activa.
    """
    df = pd.DataFrame()
    cursor = None
    
    # 🛡️ SEGURIDAD: Validar estrictamente el nombre de la tabla para evitar Inyección SQL
    if not re.match(r"^[a-zA-Z0-9_]+$", str(nombre_tabla)):
        raise ValueError(f"Nombre de tabla inválido o inseguro: {nombre_tabla}")

    if not conn or not conn.is_connected():
        raise Exception("No hay conexión activa a la base de datos.")

    try:
        usuario = st.session_state.get('usuario', 'Desconocido')
        cliente = st.session_state.get('cliente_id', 'N/A')
        
        # Registrar log de forma segura
        if 'registrar_log_automatico' in globals():
            registrar_log_automatico(conn, "CONSULTA_TABLA", f"Usuario {usuario} consultó {nombre_tabla} para cliente {cliente}")
        
        cursor = conn.cursor()
        
        # Construcción segura utilizando backticks
        query = f"SELECT * FROM `{nombre_tabla}`"
        if limite and isinstance(limite, int):
            query += f" LIMIT {limite}"
            
        df = pd.read_sql(query, conn)
        
    except Exception as e:
        st.error(f"Error al consultar la tabla {nombre_tabla}: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            try:
                conn.ping(reconnect=True)
            except:
                pass
                
    return df


# 1. Función interna que maneja la conexión y la consulta a la BD
def _obtener_datos_agente_db_real(valor_busqueda):
    conn_central = conectar_db() 
    if not conn_central: 
        return None

    try:
        cursor = conn_central.cursor(dictionary=True)
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        cursor.close()
        return datos
    except Exception as e:
        st.error(f"Error en consulta DB: {e} | Valor buscado: {valor_busqueda}")
        return None
    finally:
        if conn_central and conn_central.is_connected():
            conn_central.close()

# 2. Función pública con caché (esta es la que llamas en tu app)
@st.cache_data(ttl=3600)
def obtener_datos_agente_db(valor_busqueda):
    return _obtener_datos_agente_db_real(valor_busqueda)



def consultar_libro_diario_db(conn_activa=None, fecha_inicio=None, fecha_fin=None):
    # 1. Seguridad y Contexto
    usuario = st.session_state.get('usuario', 'Desconocido')
    cliente = st.session_state.get('cliente_id', 'N/A')
    db_a_usar = st.session_state.get('DB_ACTUAL')
    
    if not db_a_usar:
        return pd.DataFrame()

    # 2. Conexión Inteligente (Se define primero la conexión antes del log)
    es_conexion_interna = False
    if conn_activa:
        conn = conn_activa
    else:
        conn = conectar_db(db_a_usar)
        es_conexion_interna = True
    
    if not conn or not hasattr(conn, 'is_connected') or not conn.is_connected():
        return pd.DataFrame()

    # 3. Registrar el log pasando la conexión real ('conn') en lugar de None
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
        
        # 5. Ejecución con pandas
        df = pd.read_sql(query, conn, params=params)
        
        # 6. Normalización Universal
        if not df.empty:
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
        # Solo cerramos si la creamos nosotros y la conexión sigue abierta
        if es_conexion_interna and conn and hasattr(conn, 'is_connected') and conn.is_connected():
            conn.close()


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
        if conn and conn.is_connected():
            conn.close()



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
        if conn and conn.is_connected():
            try:
                conn.ping(reconnect=True)
            except:
                pass



def mostrar_tablero_conciliacion(conn, mes_sel, ano_sel):
    st.title("⚖️ Conciliación Bancaria")

    # INICIALIZA AQUÍ
    saldo_final_libros = 0.0

    # --- 1. SELECCIÓN DE EMPRESA ---
    cursor_menu = conn.cursor()
    try:
        cursor_menu.execute("SELECT db_nombre FROM control_central.clientes WHERE estado = 'Activo'")
        empresas_db = [row[0] for row in cursor_menu.fetchall()]
    finally:
        cursor_menu.close()

    if not empresas_db:
        st.warning("No se encontraron empresas activas.")
        return

    empresa_seleccionada = st.sidebar.selectbox("Seleccione Empresa", empresas_db)
    
    if st.session_state.get('DB_ACTUAL') != empresa_seleccionada:
        st.session_state['DB_ACTUAL'] = empresa_seleccionada
        st.rerun()

    db = st.session_state.get('DB_ACTUAL')
    if not db: 
        return

    # --- 2. PREPARACIÓN DE FECHAS ---
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

    # --- 3. CARGA DE BANCOS (Usando la DB seleccionada) ---
    cursor = conn.cursor(buffered=True)
    try:
        query_bancos = f"SELECT nombre, codigo FROM `{db}`.plan_cuentas WHERE nombre LIKE '%BANCO%' AND tipo = 'Detalle'"
        cursor.execute(query_bancos)
        bancos_dict = {b[0]: b[1] for b in cursor.fetchall()}
        
        if not bancos_dict:
            st.warning("No se encontraron cuentas bancarias.")
            return

        # Seleccion de Banco
        nombre_banco_sel = st.sidebar.selectbox("Seleccione Banco", list(bancos_dict.keys()))
        cuenta_codigo = bancos_dict[nombre_banco_sel]
        
        # Transformación de nombre para la BD (Alias)
        banco_db = obtener_alias_banco(nombre_banco_sel)

        # --- 4. CONSULTAS PRINCIPALES ---
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

        # C. Movimientos de Banco (Pendientes y Conciliados) usando consultas seguras con parámetros
        query_mov_pendientes = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = 'Pendiente' AND fecha_movimiento BETWEEN %s AND %s"
        df_banco = pd.read_sql(query_mov_pendientes, conn, params=(fecha_inicio, fecha_fin))

        query_mov_conciliados = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = 'Conciliado' AND fecha_movimiento BETWEEN %s AND %s"
        df_conciliado = pd.read_sql(query_mov_conciliados, conn, params=(fecha_inicio, fecha_fin))

    except Exception as e:
        st.error(f"Error en la consulta para {db}: {e}")
        df_banco = pd.DataFrame()
        df_conciliado = pd.DataFrame()
    finally:
        cursor.close()

    # --- 5. VISUALIZACIÓN ---
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
    col_p1.dataframe(df_banco[df_banco['monto'] > 0] if not df_banco.empty else pd.DataFrame())
    col_p2.write("📤 Egresos Pendientes")
    col_p2.dataframe(df_banco[df_banco['monto'] < 0] if not df_banco.empty else pd.DataFrame())
        
    if 'saldo_final_libros' not in st.session_state:
        st.session_state.saldo_final_libros = 0.0

    if st.button("🚀 Ejecutar Conciliación"):
        resultado = conciliar_datos(conn, fecha_inicio, fecha_fin, db)
        st.session_state.saldo_final_libros = resultado
        st.rerun()

    # --- 6. LÓGICA DE PDF CENTRALIZADA ---
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
            conn,
            df_conciliado, 
            saldo_inicial, 
            saldo_final_banco, 
            saldo_final_libros, 
            lista_ingresos, 
            lista_egresos
        )
        
        st.download_button(
            label="📄 Descargar Conciliación PDF", 
            data=pdf_data, 
            file_name=f"conciliacion_{mes_sel}_{ano_sel}.pdf", 
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Error generando el PDF: {e}")

    # --- 7. MOVIMIENTOS CONCILIADOS ---
    if not df_conciliado.empty:
        st.subheader("✅ Movimientos Conciliados")
        col_d, col_h = st.columns(2)
        col_d.write("Ingresos")
        col_d.dataframe(df_conciliado[df_conciliado['monto'] > 0])
        col_h.write("Egresos")
        col_h.dataframe(df_conciliado[df_conciliado['monto'] < 0])
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

# 1. Función de datos (Pura y cacheada para acelerar TiDB Cloud)
@st.cache_data(ttl=600)  # Guarda en caché por 10 minutos
def _obtener_datos_asiento(db_nombre, numero_comprobante):
    conn = conectar_db(db_nombre)
    if not conn:
        return None
    try:
        query = f"""
            SELECT 
                fecha, 
                descripcion, 
                n_comprobante,
                cuenta_contable AS codigo, 
                plan_cuentas AS nombre, 
                debe, 
                haber
            FROM asientos_contables 
            WHERE n_comprobante = '{numero_comprobante}'
        """
        return pd.read_sql(query, conn)
    except Exception as e:
        print(f"Error en consulta: {e}")
        return None
    finally:
        if conn and conn.is_connected():
            conn.close()

# 2. Función visual (Sin caché, encargada de renderizar la UI de Streamlit)
def disenar_reporte_asiento_contable(numero_comprobante):
    db_nombre = st.session_state.get('DB_ACTUAL', 'kingdirver_ca')
    
    # Llamamos a la función de datos cacheada
    df_asiento = _obtener_datos_asiento(db_nombre, numero_comprobante)

    if df_asiento is None or df_asiento.empty:
        st.warning(f"⚠️ No se encontró data para el comprobante Nº: {numero_comprobante}")
        return

    # --- TODO TU DISEÑO E INTERFAZ SE MANTIENE IGUAL AQUÍ ---
    st.markdown("---")
    col_logo, col_info = st.columns([1, 3])
    with col_logo:
        st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=80)
    with col_info:
        st.markdown(f"## {EMPRESA}")
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


@st.cache_data(ttl=60)
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
        
        if conn and conn.is_connected():
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
            df_cuentas = pd.read_sql(query_cuentas, conn)
            
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
                            use_container_width=True, 
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

    registrar_log_automatico(conn, "CONSULTA_BALANCE_GENERAL", f"Usuario {st.session_state.usuario} consultó balance para {st.session_state.cliente_id}")

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"USE `{db}`")
        
        # 1. Obtener datos
        df_saldos = generar_balance_comprobacion(conn, f_i, f_f, sucursal)
        query_plan = f"SELECT codigo, nombre, nivel, padre FROM `{db}`.plan_cuentas ORDER BY codigo"
        df_plan = pd.read_sql(query_plan, conn)
        
        # --- AQUÍ ESTÁ LA SOLUCIÓN ---
        # Eliminamos cualquier columna que no sea la llave o la necesaria para evitar colisiones
        # Nos quedamos solo con las columnas que el merge necesita
        cols_plan = ['codigo', 'nombre', 'nivel', 'padre']
        cols_saldos = ['Código', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        
        df_plan = df_plan[cols_plan]
        df_saldos = df_saldos[cols_saldos]
        
        # Merge limpio
        df = pd.merge(df_plan, df_saldos, left_on='codigo', right_on='Código', how='left')
        
        # --- CONTINUACIÓN DEL CÁLCULO ---
        cols_numericas = ['Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        df[cols_numericas] = df[cols_numericas].fillna(0).astype(float)
        
        # 1. Limpieza inicial: Ponemos a cero los padres para empezar la suma desde abajo
        padres_codigos = df['padre'].unique()
        df.loc[df['codigo'].isin(padres_codigos), cols_numericas] = 0.0

        # 1. Asegurar tipos y valores (nada de NaN)
        df[cols_numericas] = df[cols_numericas].fillna(0.0).astype(float)
        
        # 2. CALCULAR SALDO FINAL PRIMERO (La base real de datos)
        df['Saldo Final'] = df['Saldo Inicial'] + df['Debe'] - df['Haber']
        
        # 3. Limpiar saldos de los padres (Nivel 5 a 2) para que inicien en 0 y solo contengan la suma de hijos
        # Esto asegura que el roll-up sea puro.
        padres_codigos = df['padre'].dropna().unique()
        df.loc[df['codigo'].isin(padres_codigos), cols_numericas] = 0.0


        # Identifica quién está descuadrado:

        
        # 4. Roll-up jerárquico
        niveles = sorted(df['nivel'].unique(), reverse=True)
        
        for n in niveles:
            if n <= 1: continue 
            
            resumen = df[df['nivel'] == n].groupby('padre')[cols_numericas].sum()
            
            for p_codigo, fila_suma in resumen.iterrows():
                p_codigo_str = str(p_codigo).strip()
                # Usamos .loc para actualizar de forma segura
                mask = df['codigo'].astype(str).str.strip() == p_codigo_str
                
                if mask.any():
                    # Sumamos los valores del nivel N al nivel N-1
                    df.loc[mask, cols_numericas] += fila_suma
                else:
                    print(f"⚠️ Alerta: El padre '{p_codigo_str}' no existe en el plan.")
        # 1. Asegurar que df no sea nulo antes de procesar
        if df is None or df.empty:
            st.error("⚠️ Error: El DataFrame está vacío o no se pudo generar.")
            return df  # Retornamos el df vacío para que la app no colapse


        # --- BLOQUE SEGURO DE PROCESAMIENTO ---

        # 1. Filtramos solo los registros con movimiento real
        # Suma limpia, sin restas.
        # Definimos la función genérica para obtener el valor de cualquier columna
        # 1. Definimos tu función para extraer cualquier columna por código
        def get_columna(cod, col):
            fila = df[df['codigo'].astype(str) == str(cod)]
            return fila[col].sum() if not fila.empty else 0

        # 2. Aplicamos la lógica específica que pediste para los totales
        # Ajusta los signos (+ o -) según la naturaleza de tus cuentas
        saldo_inicial = get_columna('1', 'Saldo Inicial') +get_columna('2', 'Saldo Inicial') +get_columna('3', 'Saldo Inicial')+get_columna('4', 'Saldo Inicial')+get_columna('5', 'Saldo Inicial')+get_columna('6', 'Saldo Inicial')+get_columna('7', 'Saldo Inicial')+get_columna('8', 'Saldo Inicial')
        total_debe = get_columna('1', 'Debe') -get_columna('2', 'Debe') -get_columna('3', 'Debe')-get_columna('4', 'Debe')-get_columna('5', 'Debe')-get_columna('6', 'Debe')-get_columna('7', 'Debe')-get_columna('8', 'Debe')
        total_haber = get_columna('1', 'Haber') - get_columna('2', 'Haber') - get_columna('4', 'Haber')- get_columna('5', 'Haber')- get_columna('6', 'Haber')- get_columna('7', 'Haber')- get_columna('8', 'Haber')
        saldo_final_resumen = get_columna('4', 'Saldo Final')+get_columna('5', 'Saldo Final')+get_columna('6', 'Saldo Final')+get_columna('7', 'Saldo Final')+get_columna('8', 'Saldo Final')
        # 3. Creamos la fila resumen
        fila_total = pd.DataFrame([{
            'codigo': 'Σ',
            'nombre': 'RESUMEN MOVIMIENTOS',
            'nivel': 0,
            'padre': None,
            'Saldo Inicial': saldo_inicial,
            'Debe': total_debe,
            'Haber': total_haber,
            'Saldo Final': saldo_final_resumen
        }])

        # 4. Concatenamos
        df = pd.concat([df, fila_total], ignore_index=True)
        return df

    except Exception as e:
        st.error(f"Error procesando la base de datos: {e}")
        return None
    finally:
        if cursor: cursor.close()


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

        # --- Navegación ---
        if user_rol == 'admin':
            menu = st.radio("Navegación", ["📊 Auditoría Contable", "⚙️ Gestión de Usuarios"], key="menu_nav")
        else:
            menu = "📊 Auditoría Contable"

        st.divider()

        # --- Selección de Empresa ---
        if menu == "📊 Auditoría Contable":
            conn_sidebar = conectar_db()
            df_sidebar = pd.DataFrame()

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

                    queries_a_probar = [
                        "SELECT * FROM control_central.clientes",
                        "SELECT * FROM clientes"
                    ]
                    
                    for q in queries_a_probar:
                        try:
                            df_temp = pd.read_sql(q, conn_sidebar)
                            if not df_temp.empty:
                                df_sidebar = df_temp
                                break
                        except Exception:
                            continue
                except Exception as e:
                    st.error(f"❌ Error de conexión en la barra lateral: {e}")
                finally:
                    try:
                        if conn_sidebar and hasattr(conn_sidebar, 'close'):
                            conn_sidebar.close()
                    except:
                        pass

            if not df_sidebar.empty:
                df_sidebar = df_sidebar.fillna("")

                # 🛠️ FILTRADO ESTRICTO POR USUARIO LOGUEADO (SI NO ES ADMIN)
                if user_rol != 'admin':
                    filtrado_exitoso = False
                    
                    # 1. Filtrar por ID de usuario o cliente en sesión
                    c_id = st.session_state.get('cliente_id') or st.session_state.get('user_id')
                    if c_id and any(col in df_sidebar.columns for col in ['id', 'cliente_id', 'usuario_id']):
                        col_encontrada = next(c for c in ['id', 'cliente_id', 'usuario_id'] if c in df_sidebar.columns)
                        match_id = df_sidebar[df_sidebar[col_encontrada].astype(str) == str(c_id)]
                        if not match_id.empty:
                            df_sidebar = match_id
                            filtrado_exitoso = True

                    # 2. Filtrar por coincidencia exacta del nombre de usuario en las columnas de la tabla
                    if not filtrado_exitoso:
                        limpiar_nombre = str(nombre_usuario_actual).strip().lower()
                        for col_u in ['nombre_usuario', 'usuario', 'username', 'user', 'login']:
                            if col_u in df_sidebar.columns:
                                match_user = df_sidebar[df_sidebar[col_u].astype(str).str.strip().str.lower() == limpiar_nombre]
                                if not match_user.empty:
                                    df_sidebar = match_user
                                    filtrado_exitoso = True
                                    break
                    
                    # 3. Si aun así no encuentra por campos exactos, busca por coincidencia parcial del nombre (Ej. Ejan Maroc)
                    if not filtrado_exitoso:
                        limpiar_nombre = str(nombre_usuario_actual).strip().lower()
                        for col_c in df_sidebar.columns:
                            match_parcial = df_sidebar[df_sidebar[col_c].astype(str).str.lower().str.contains(limpiar_nombre, na=False)]
                            if not match_parcial.empty:
                                df_sidebar = match_parcial
                                filtrado_exitoso = True
                                break

            df_filtrado = df_sidebar

            # Si es usuario normal y no se encontró registro, se muestra advertencia clara en lugar de inventar otra empresa
            if user_rol != 'admin' and df_filtrado.empty:
                st.error(f"❌ El usuario '{nombre_usuario_actual}' no tiene una empresa asignada en la base de datos.")
                st.stop()

            # Resguardo absoluto solo si es admin y la tabla está totalmente vacía
            if df_filtrado.empty:
                df_filtrado = pd.DataFrame({
                    'id': [1],
                    'nombre_empresa': ['EMPRESA DEFAULT'],
                    'db_nombre': ['pedacito_de_cielo_ca'],
                    'nombre_usuario': [nombre_usuario_actual]
                })

            nombres_empresas = df_filtrado['nombre_empresa'].tolist()
            
            # Aseguramos que el selectbox recuerde la opción seleccionada previamente
            index_actual = 0
            if 'cliente_seleccionado_previo' in st.session_state and st.session_state['cliente_seleccionado_previo'] in nombres_empresas:
                index_actual = nombres_empresas.index(st.session_state['cliente_seleccionado_previo'])

            if user_rol == 'admin':
                nombre_seleccionado = st.selectbox(
                    "Seleccione Empresa", 
                    options=nombres_empresas,
                    index=index_actual,
                    key="selector_empresa"
                )
            else:
                nombre_seleccionado = nombres_empresas[0]
                st.markdown(f"**🏢 Empresa Asignada:**")
                st.info(f"{str(nombre_seleccionado).upper()}")

            st.session_state['cliente_seleccionado_previo'] = nombre_seleccionado

            fila_seleccionada = df_filtrado[df_filtrado['nombre_empresa'] == nombre_seleccionado]
            if fila_seleccionada.empty:
                fila_seleccionada = df_filtrado.iloc[[0]]

            datos_sel = fila_seleccionada.iloc[0]
            db_seleccionada = str(datos_sel['db_nombre']).strip()
            
            # --- VALIDACIÓN Y REINICIO DE CONEXIÓN LIMPIO ---
            if st.session_state.get('DB_ACTUAL') != db_seleccionada:
                st.session_state['DB_ACTUAL'] = db_seleccionada
                st.session_state['db_a_conectar'] = db_seleccionada
                st.session_state['conn'] = None  # Limpiamos conexión vieja de forma segura
                st.rerun()

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

# Sacamos los datos directamente de lo que ya se seleccionó en el Sidebar
if 'DB_ACTUAL' in st.session_state and st.session_state.get('DB_ACTUAL'):
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE', "Empresa Seleccionada")
    # Si también guardas el RIF en el session_state, lo buscas aquí:
    RIF = st.session_state.get('rif_empresa_seleccionada', "J-00000000-0")
else:
    EMPRESA = "Seleccione Cliente"
    RIF = "J-00000000-0"

DATOS_EMPRESA = {"nombre": EMPRESA, "rif": RIF}

if menu_lateral == "📊 Auditoría Contable":
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
            sub_opcion = st.radio("Acciones:", ["Subir Datos", "Conciliación Bancaria", "Consultar Comprobante", "Consultar Saldos Iniciales", "Consultar Cierre Contable"], key="sub_asientos")
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
                        # Admin por defecto toma la primera del sistema
                        df_temp = pd.read_sql("SELECT db_nombre FROM clientes LIMIT 1", conn_ctrl)
                        if not df_temp.empty: db_objetivo = str(df_temp['db_nombre'].iloc[0])
                else:
                    # --- BÚSQUEDA DIRECTA Y SEGURA ---
                    # Buscamos directamente en la tabla usuarios usando el nombre de usuario
                    query = f"SELECT db_nombre FROM usuarios WHERE LOWER(TRIM(usuario)) = '{nombre_usuario_actual}'"
                    df_temp = pd.read_sql(query, conn_ctrl)
                    
                    if not df_temp.empty and df_temp['db_nombre'].iloc[0]:
                        db_objetivo = str(df_temp['db_nombre'].iloc[0]).strip()
                    else:
                        st.error(f"❌ Acceso denegado: El usuario '{nombre_usuario_actual}' no tiene una empresa (DB) asociada.")
                        st.stop()
            except Exception as e:
                st.error(f"❌ Error al resolver la base de datos: {e}")
                st.stop()
            finally:
                conn_ctrl.close()

        if not db_objetivo:
            st.error("❌ No se pudo determinar la base de datos de trabajo.")
            st.stop()

        st.session_state['DB_ACTUAL'] = db_objetivo
        st.session_state['db_a_conectar'] = db_objetivo

        # --- LÓGICA DE CONEXIÓN ---
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

        dic_meses = {
            "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
            "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
            "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
        }
        meses_lista = list(dic_meses.keys())
        
        anio_f = int(st.session_state.get('año_seleccionado', datetime.datetime.now().year))
        mes_nombre_f = st.session_state.get('mes_seleccionado', meses_lista[datetime.datetime.now().month - 1])
        
        m_idx = dic_meses.get(mes_nombre_f, 1)
        
        ultimo_dia = calendar.monthrange(anio_f, m_idx)[1]

        # CAMBIO: El inicio siempre es el 1 de enero del año seleccionado (Acumulado Anual)
        f_inicio_global = datetime.date(anio_f, 1, 1)
        f_fin_global = datetime.date(anio_f, m_idx, ultimo_dia)

        fecha_inicio_str = f_inicio_global.strftime('%Y-%m-%d')
        fecha_fin_str = f_fin_global.strftime('%Y-%m-%d')

        st.title(f"📊 Auditoría Profesional: {db_objetivo}")
        st.markdown(f"**Período de Análisis (Acumulado):** {f_inicio_global.strftime('%d/%m/%Y')} al {f_fin_global.strftime('%d/%m/%Y')}")
        st.divider()
        
        # --- FILA 1: INDICADORES FINANCIEROS ---
        col_titulo, col_vacia, col_btn = st.columns([0.5, 0.3, 0.2])
        with col_titulo:
            st.subheader("Indicadores Financieros en Tiempo Real")

        with col_btn:
            if st.button("🔄 Actualizar Datos", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

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
        
        # --- FILA 2: SALUD FISCAL (SENIAT) ---
        kpis_fiscales = obtener_salud_fiscal(f_inicio_global, f_fin_global, db_objetivo)

        # Función actualizada con diseño de frame horizontal expandido
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
        mini_kpi(i1, "Ingresos Exentos", kpis_fiscales.get('ingresos_exentas', 0), "#1f77b4")
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


        # --- FILA 4: ANÁLISIS VISUAL ---
        st.divider()
        col_izq, col_der = st.columns(2)

        # 1. Recuperamos y blindamos los valores usando las keys oficiales del sidebar
        año_val = st.session_state.get('año_seleccionado_contabilidad', 2026)
        mes_val = st.session_state.get('mes_seleccionado_contabilidad', 'Mayo')

        try:
            año = int(str(año_val).strip())
        except:
            año = 2026

        meses_map = {
            'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 
            'Mayo': 5, 'Junio': 6, 'Julio': 7, 'Agosto': 8, 
            'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
        }

        if isinstance(mes_val, str):
            mes = meses_map.get(mes_val.strip(), 5)
        else:
            try:
                mes = int(mes_val)
            except:
                mes = 5

       # 1. Obtenemos el valor de mes actual de donde lo guardes (session_state o tu variable global)
        # Asegúrate de capturar el valor real de tu selectbox de meses aquí:
        mes_crudo = st.session_state.get('mes_seleccionado') or st.session_state.get('mes') or mes

        # 2. Diccionario de traducción de texto a número (por si viene como nombre de mes)
        dic_meses = {
            "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
            "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
            "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
        }

        # 3. Conversión blindada: si es texto lo busca en el diccionario, si es número lo convierte
        try:
            año_int = int(año)
        except (ValueError, TypeError):
            año_int = datetime.datetime.now().year

        if str(mes_crudo).isdigit():
            mes_int = int(mes_crudo)
        else:
            # Si es texto (ej. "Junio"), lo busca; si no lo encuentra, por defecto usa 6 (o el actual)
            mes_int = dic_meses.get(str(mes_crudo).capitalize(), 6)

        # 4. Calcular el último día del mes de forma segura
        _, ultimo_dia = calendar.monthrange(año_int, mes_int)

        # 5. Generar los strings para las consultas SQL
        f_i = f"{año_int:04d}-{mes_int:02d}-01"
        f_f = f"{año_int:04d}-{mes_int:02d}-{ultimo_dia:02d}"

        # 6. Variables tipo date
        f_inicio_global = datetime.date(año_int, mes_int, 1)
        f_fin_global = datetime.date(año_int, mes_int, ultimo_dia)

        # 7. DEBUG VISUAL (Asegúrate de mostrar también el mes en texto para validar visualmente)
        st.sidebar.info(f"📅 Rango activo ({mes_crudo}): {f_i} al {f_f}")  

        db = st.session_state.get('DB_ACTUAL')

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
                    st.plotly_chart(fig, use_container_width=True)
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
                        
                        st.plotly_chart(fig_pie, use_container_width=True)
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
            try:
                conn = conectar_db(db)
                cursor = conn.cursor(dictionary=True)
                
                # A. Saldo Inicial Fijo (Protegido por si la tabla no existe)
                debe_s_ini, haber_s_ini = 0.0, 0.0
                try:
                    cursor.execute(f"SELECT COALESCE(SUM(debe), 0) as d, COALESCE(SUM(haber), 0) as h FROM `{db}`.saldos_iniciales WHERE plan_cuentas LIKE '1.1.1.02%'")
                    res_s_ini = cursor.fetchone()
                    if res_s_ini:
                        debe_s_ini = float(res_s_ini['d'] or 0.0)
                        haber_s_ini = float(res_s_ini['h'] or 0.0)
                except Exception:
                    # Si la tabla saldos_iniciales no existe, continúa sin interrumpir
                    pass

                # B. Movimientos históricos anteriores a f_i
                debe_hist, haber_hist = 0.0, 0.0
                try:
                    cursor.execute(f"SELECT COALESCE(SUM(debe), 0) as d, COALESCE(SUM(haber), 0) as h FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '1.1.1.02%' AND fecha < %s", (f_i,))
                    res_hist = cursor.fetchone()
                    if res_hist:
                        debe_hist = float(res_hist['d'] or 0.0)
                        haber_hist = float(res_hist['h'] or 0.0)
                except Exception:
                    pass

                saldo_inicial_neto = (debe_s_ini + debe_hist) - (haber_s_ini + haber_hist)

                # C. Movimientos del Periodo (f_i a f_f)
                entradas_mes, salidas_mes = 0.0, 0.0
                try:
                    query_mes = f"""
                        SELECT COALESCE(SUM(debe), 0) as ent, COALESCE(SUM(haber), 0) as sal 
                        FROM `{db}`.asientos_contables
                        WHERE plan_cuentas LIKE '1.1.1.02%' AND fecha BETWEEN %s AND %s
                    """
                    cursor.execute(query_mes, (f_i, f_f))
                    res_mes = cursor.fetchone()
                    if res_mes:
                        entradas_mes = float(res_mes['ent'] or 0.0)
                        salidas_mes = float(res_mes['sal'] or 0.0)
                except Exception:
                    pass

                saldo_real = saldo_inicial_neto + entradas_mes - salidas_mes

                # D. INTENTO AUTOMÁTICO DE CUENTAS POR COBRAR DESDE LA DB
                cxc_db = 0.0
                try:
                    cursor.execute(f"SELECT COALESCE(SUM(debe - haber), 0) as cxc FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '1.1.2%'")
                    res_cxc = cursor.fetchone()
                    if res_cxc and res_cxc['cxc']:
                        cxc_db = float(res_cxc['cxc'])
                except Exception:
                    cxc_db = 0.0

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

                # 3. CONTROLES DE SIMULACIÓN (Toma el valor detectado o permite ajustarlo)
                st.sidebar.header("⚙️ Simulación de Escenarios (Stress Testing)")
                
                cuentas_por_cobrar = st.sidebar.number_input(
                    "Cuentas por Cobrar (Detectadas / Manual):", 
                    value=max(cxc_db, 0.0), 
                    step=10000.0,
                    help="Si la empresa tiene saldo en cuentas por cobrar (ej. cuenta 1.1.2), aparecerá aquí automáticamente."
                )

                pct_retraso = st.sidebar.slider(
                    "% de Facturas que se retrasan a 60 días:", 
                    min_value=0, 
                    max_value=100, 
                    value=0, 
                    step=5
                )

                impacto_retraso = cuentas_por_cobrar * (pct_retraso / 100.0)

                # 4. PROYECCIÓN DE FLUJO DE CAJA Y ANÁLISIS DE DESVIACIONES
                st.markdown("---")
                st.subheader("📈 Proyección de Liquidez y Análisis de Estrés")
                st.caption("Estimación basada en el flujo neto diario con simulación a 30, 60 y 90 días.")

                import datetime as dt

                if isinstance(f_i, str):
                    d1 = dt.datetime.strptime(f_i, "%Y-%m-%d")
                else:
                    d1 = f_i

                if isinstance(f_f, str):
                    d2 = dt.datetime.strptime(f_f, "%Y-%m-%d")
                else:
                    d2 = f_f

                dias_rango = max((d2 - d1).days + 1, 1)

                flujo_neto_periodo = entradas_mes - salidas_mes
                promedio_diario_neto = flujo_neto_periodo / dias_rango

                # Proyecciones Meta (30, 60 y 90 días)
                proj_30_meta = saldo_real + (promedio_diario_neto * 30)
                proj_60_meta = saldo_real + (promedio_diario_neto * 60)
                proj_90_meta = saldo_real + (promedio_diario_neto * 90)

                proj_30_ajustada = proj_30_meta - impacto_retraso

                if proj_30_meta != 0:
                    desviacion_absoluta = proj_30_ajustada - proj_30_meta
                    desviacion_pct = (desviacion_absoluta / abs(proj_30_meta)) * 100
                else:
                    desviacion_absoluta, desviacion_pct = 0.0, 0.0

                # Bloque 1: Proyecciones Temporales (30, 60 y 90 Días)
                st.write("##### 🗓️ HORIZONTE DE LIQUIDEZ PROYECTADO")
                m1, m2, m3 = st.columns(3)
                m1.metric("Proyección 30 Días", f"Bs. {proj_30_meta:,.2f}", delta=f"{promedio_diario_neto * 30:,.2f} Bs est.")
                m2.metric("Proyección 60 Días", f"Bs. {proj_60_meta:,.2f}", delta=f"{promedio_diario_neto * 60:,.2f} Bs est.")
                m3.metric("Proyección 90 Días", f"Bs. {proj_90_meta:,.2f}", delta=f"{promedio_diario_neto * 90:,.2f} Bs est.")

                st.info(f"🤖 **Resumen de Proyección:** Con base en un promedio diario de Bs. {promedio_diario_neto:,.2f}, se proyecta una disponibilidad de Bs. {proj_30_meta:,.2f} a 30 días, alcanzando Bs. {proj_60_meta:,.2f} a 60 días y Bs. {proj_90_meta:,.2f} al cierre de los 90 días.")

                # Bloque 2: Escenario de Estrés
                st.write("##### ⚡ ESCENARIO DE SIMULACIÓN Y MORA")
                p1, p2, p3 = st.columns(3)
                p1.metric("30 Días Ajustado", f"Bs. {proj_30_ajustada:,.2f}", delta=f"{desviacion_pct:.2f}%")
                p2.metric("Impacto por Retraso", f"Bs. {impacto_retraso:,.2f}")
                p3.metric("Desviación Absoluta", f"Bs. {desviacion_absoluta:,.2f}")

                st.info(f"🤖 **Resumen de Stress Testing:** Con un monto bajo análisis de Bs. {cuentas_por_cobrar:,.2f} y un retraso simulado del {pct_retraso}%, el impacto en caja es de Bs. {impacto_retraso:,.2f}, dejando la liquidez proyectada en Bs. {proj_30_ajustada:,.2f}.")

                # 5. SEMÁFORO DE RIESGO INTELIGENTE
                if proj_30_ajustada < 0 or desviacion_pct <= -15.0:
                    st.error(f"🚨 **ALERTA DE ILIQUIDEZ POTENCIAL ({desviacion_pct:.1f}%):** El escenario de retraso genera un déficit crítico en la disponibilidad a 30 días.")
                elif -15.0 < desviacion_pct < 0:
                    st.warning(f"⚠️ **Advertencia de Riesgo Leve ({desviacion_pct:.1f}%):** Existe una desviación negativa frente a la meta proyectada.")
                else:
                    st.success("✅ **Salud de Caja Estable:** Las proyecciones se mantienen en niveles seguros de liquidez.")

                # 6. DETALLE DE MOVIMIENTOS
                st.markdown("---")
                st.write("### Detalle de Movimientos")
                try:
                    df_flujo = obtener_detalle_movimientos_banco(db, f_i, f_f) 
                except Exception:
                    df_flujo = None

                if df_flujo is not None and not df_flujo.empty:
                    st.dataframe(df_flujo, use_container_width=True, hide_index=True, column_config={
                        "fecha": st.column_config.DateColumn("Fecha"),
                        "descripcion": "Concepto",
                        "debe": st.column_config.NumberColumn("Entradas", format="Bs. %.2f"),
                        "haber": st.column_config.NumberColumn("Salidas", format="Bs. %.2f")
                    })
                else:
                    st.info(f"No hay movimientos en este rango del {f_i} al {f_f}.")

            except Exception as e:
                st.error(f"Error en consulta contable para `{db}`: {e}")
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
                    use_container_width=True,  # Ocupa todo el ancho de la pantalla correctamente
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
                                if conn_bcv.is_connected():
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
            # 1. Abrimos una conexión fresca y exclusiva para este reporte
            conn_local = conectar_db(db_actual)
            
            if not conn_local or not conn_local.is_connected():
                st.error("⚠️ No se pudo establecer una conexión activa con la base de datos para generar el reporte.")
                st.stop()

            # 2. Ejecutamos la función asegurándonos de que devuelva un DataFrame
            resultado_bruto = generar_reporte_multimoneda(conn_local, mes_seleccionado, ano_seleccionado, db_actual)
            
            # 3. Cerramos la conexión local de forma limpia
            if conn_local.is_connected():
                conn_local.close()
             
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
                        use_container_width=True
                    )

                # 2. Renderizar la tabla principal en la app abajo de los filtros
                st.dataframe(df_visual, use_container_width=True, hide_index=True)
                
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
                    
                    if st.button("🧮 Generar Balance de Comprobación", use_container_width=True):
                        
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
                                
                                st.dataframe(df_balance_visual, use_container_width=True, hide_index=True)
                                
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
            if conn and not conn.is_connected():
                conn.reconnect(attempts=3, delay=2)
            else:
                conn.ping(reconnect=True, attempts=3, delay=2)
        except Exception:
            pass

        # Usamos la base de datos activa que corresponda (reemplaza 'db_actual' por la variable de tu empresa)
        query_completa = f"SELECT * FROM `{db_actual}`.asientos_contables"
        
        try:
            df_diario = pd.read_sql(query_completa, conn) 
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
            
            if st.button("🚀 Ejecutar Escáner Antifraude", use_container_width=True):
                st.info("Procesando algoritmos estadísticos sobre el Libro Diario...")
                
                # 1. Preparación de datos
                # Limpieza de columnas numéricas
                df_diario['debe'] = pd.to_numeric(df_diario['debe'], errors='coerce').fillna(0)
                df_diario['haber'] = pd.to_numeric(df_diario['haber'], errors='coerce').fillna(0)
                
                # Cálculo de monto auditable (ajustado por moneda)
                if moneda_vista == "Dólares (USD)":
                    # Asegúrate que las columnas debe_usd/haber_usd existan en tu tabla
                    df_diario['monto_auditable'] = df_diario['debe_usd'] + df_diario['haber_usd']
                else:
                    df_diario['monto_auditable'] = df_diario['debe'] + df_diario['haber']
                
                # 2. Filtrado: Excluir saldos iniciales y montos cero
                df_asientos = df_diario[
                    (~df_diario['descripcion'].str.contains("SALDOS INICIALES", case=False, na=False)) & 
                    (df_diario['monto_auditable'] != 0)
                ].copy()
                
                # --- BLOQUE DE DEPURACIÓN (AUTOPSIA DE DATOS) ---
                if df_asientos.empty:
                    st.warning("⚠️ El escáner no encontró movimientos. Ejecutando diagnóstico de integridad:")
                    st.write(f"Total registros en diario: {len(df_diario)}")
                    # --- DEPURACIÓN PREVIA ---
                    st.write("Registros disponibles en el objeto df_diario:", len(df_diario))
                    st.write(df_diario.head(5)) # Esto te confirmará si los gastos de mayo están presentes
                                            
                    # Ver qué descartó el filtro
                    ejemplo_descartados = df_diario[df_diario['descripcion'].str.contains("SALDO", case=False, na=False)].head(3)
                    if not ejemplo_descartados.empty:
                        st.write("Registros descartados por coincidir con 'SALDO':")
                        st.dataframe(ejemplo_descartados[['fecha', 'descripcion', 'monto_auditable']])
                    
                    st.error("📊 Ninguna fila superó los filtros. Revisa si tus gastos reales contienen la palabra 'SALDO' o si el monto es 0.")
                    
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
                    # ALGORITMO 2: Z-SCORE (DESVIACIÓN) - SEGURO CONTRA Nulos
                    # -----------------------------------------------------------------
                    # Calculamos la media y la desviación estándar de forma segura
                    stats = df_asientos.groupby('cuenta_contable')[col_analisis].agg(['mean', 'std']).reset_index()
                    
                    # Si hay un solo registro por cuenta, la std es NaN. La rellenamos con 0.
                    stats['std'] = stats['std'].fillna(0.0)
                    
                    df_audit = df_asientos.merge(stats, on='cuenta_contable', how='left')
                    
                    # Si la desviación estándar es 0 (porque la cuenta solo tiene 1 registro o todos valen igual), 
                    # asignamos un valor artificial seguro para evitar divisiones por cero, pero marcando que no hay dispersión real.
                    df_audit['std_safe'] = df_audit['std'].replace(0.0, 1.0)
                    
                    df_audit['z_score'] = (df_audit[col_analisis] - df_audit['mean']) / df_audit['std_safe']
                    
                    # Solo evaluamos Z-score en cuentas donde realmente hubo variación (std > 0)
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
            # Usamos las llaves exactas definidas en el sidebar de contabilidad
            año = int(st.session_state.get('año_seleccionado_contabilidad', datetime.datetime.now().year))
            mes_elegido_str = str(st.session_state.get('mes_seleccionado_contabilidad', 'Junio')).strip().capitalize()

            # Mapeo robusto de meses
            meses_map = {
                'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
                'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
            }
            
            num_mes = meses_map.get(mes_elegido_str, 6)

            # Construcción de fechas usando calendar para evitar errores en días máximos
            ultimo_dia = int(calendar.monthrange(año, num_mes)[1])
            
            # Creamos tanto los strings como los objetos date de forma limpia
            f_i_str = f"{año}-{num_mes:02d}-01"
            f_f_str = f"{año}-{num_mes:02d}-{ultimo_dia:02d}"

            f_i_date = datetime.date(año, num_mes, 1)
            f_f_date = datetime.date(año, num_mes, ultimo_dia)

            # Cuadro informativo de depuración en tiempo real reflejando el período activo
            st.info(f"📅 Período Activo: **{mes_elegido_str} {año}** | Rango SQL: **{f_i_str} al {f_f_str}**")

            # Validar Base de Datos activa
            db = st.session_state.get('DB_ACTUAL')
            if db and db != "{db}" and db != "None" and str(db).strip() != "":
                try:
                    # Pasamos los objetos date unificados a tus funciones
                    df_acc = obtener_analisis_accionista_detallado(db, f_i_date, f_f_date)
                    utilidad = obtener_historico_utilidad(db, f_inicio=f_i_str, f_fin=f_f_str)
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

                if conn_tab is None or not conn_tab.is_connected():
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
                        df_config_accionistas = pd.read_sql(f"SELECT * FROM `{db}`.accionistas", conn_tab)
                        cursor.close()
                        
                    except Exception as e:
                        st.error(f"⚠️ Error al procesar la configuración de accionistas: {e}")
                        df_config_accionistas = pd.DataFrame()
                        
                    finally:
                        # CERRAMOS la conexión aquí mismo para evitar que se quede 'colgada'
                        if conn_tab and conn_tab.is_connected():
                            conn_tab.close()


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
                    
                    # IMPORTANTE: st.plotly_chart debe estar identado dentro del 'with tab1:'
                    st.plotly_chart(fig, use_container_width=True)
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
                    st.plotly_chart(fig5, use_container_width=True)
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
                    st.plotly_chart(fig6, use_container_width=True)
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
                    st.plotly_chart(fig, use_container_width=True)
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
                            df_comps = pd.read_sql(query_comps, conn_tmp, params=(f_i, f_f))
                            
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
                                use_container_width=True,
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

                    # Lectura robusta compatible con ambas nomenclaturas de sesión
                    anio_sel = int(st.session_state.get('año_seleccionado') or st.session_state.get('anio', datetime.datetime.now().year))
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
                                    df_t = pd.read_sql(query_totales, conn_totales, params=lista_n_comps)
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
                                    use_container_width=True,
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
            st.code(traceback.format_exc())  # Es
        

        # --- FILA 11: CALENDARIO ESPECIAL PEDACITO DE CIELO ---
        # CALENDARIO FSICAL DE CONTRIBUYENTE ESPECIAL
        # FORZAMOS el nombre correcto de tu BD en TiDB Cloud
        db_objetivo = "pedacito_de_cielo_ca"

        if db == db_objetivo or "pedacito" in str(db).lower():
            
            # 1. Conexión segura a TiDB Cloud
            conexion_activa = conectar_db(db_objetivo)
            
            if conexion_activa is not None:
                try:
                    # Solución al error 'Unread result found': consumimos o cerramos limpiamente
                    cursor = conexion_activa.cursor()
                    cursor.execute("SELECT 1") 
                    cursor.fetchall() # Consumimos los resultados pendientes del buffer
                    cursor.close()
                except Exception as e:
                    st.error(f"❌ Error al ejecutar en la base de datos: {e}")
                    st.stop()
            else:
                st.error(f"❌ No se pudo establecer la conexión con '{db_objetivo}'.")
                st.stop()
                    
            with tab1:
                # ==========================================
                # 1. LÍNEA DIVISORIA ANTES DE LAS ALERTAS
                # ==========================================
                st.divider()

                # ==========================================
                # 2. SISTEMA DE ALERTAS Y CONTROL DE PAGOS
                # ==========================================
                st.markdown("### 🔔 Estado de Alertas Fiscales Próximas")

                hoy = date.today()
                
                eventos_fiscales = [
                    {"id": "iva_1", "concepto": "IVA / Anticipos (1era Quincena)", "fecha": date(2026, 8, 31), "mes_idx": 7},
                    {"id": "iva_2", "concepto": "IVA / Anticipos (2da Quincena)", "fecha": date(2026, 8, 14), "mes_idx": 7},
                    {"id": "islr", "concepto": "Retenciones de ISLR", "fecha": date(2026, 8, 7), "mes_idx": 7},
                    {"id": "pensiones", "concepto": "Ley de Protección de Pensiones", "fecha": date(2026, 8, 17), "mes_idx": 7},
                ]

                # Archivo local para persistencia de pagos
                archivo_pagos = "pagos_pedacito.json"

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

                # Inicializamos en session_state cargando desde el archivo si no existe
                if 'pagos_realizados_pedacito' not in st.session_state:
                    st.session_state['pagos_realizados_pedacito'] = cargar_pagos_disco()

                # Contenedor para que el cliente pueda marcar si ya pagó
                st.markdown("##### 📝 Control de Pagos Realizados:")
                
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    val_iva_2 = st.checkbox("✅ IVA 2da Quincena Pagado", value=st.session_state['pagos_realizados_pedacito'].get("iva_2", False), key="chk_iva_2")
                    val_islr = st.checkbox("✅ Retenciones ISLR Pagadas", value=st.session_state['pagos_realizados_pedacito'].get("islr", False), key="chk_islr")
                with col_c2:
                    val_pensiones = st.checkbox("✅ Ley de Pensiones Pagada", value=st.session_state['pagos_realizados_pedacito'].get("pensiones", False), key="chk_pensiones")
                    val_iva_1 = st.checkbox("✅ IVA 1era Quincena Pagado", value=st.session_state['pagos_realizados_pedacito'].get("iva_1", False), key="chk_iva_1")

                # Actualizar diccionario y guardar en disco si hubo cambios
                nuevos_pagos = {
                    "iva_1": val_iva_1,
                    "iva_2": val_iva_2,
                    "islr": val_islr,
                    "pensiones": val_pensiones
                }

                if nuevos_pagos != st.session_state['pagos_realizados_pedacito']:
                    st.session_state['pagos_realizados_pedacito'] = nuevos_pagos
                    guardar_pagos_disco(nuevos_pagos)

                pagos_realizados = st.session_state['pagos_realizados_pedacito']

                # Evaluador de Alertas y Sonido
                alerta_activa = False
                mensajes_urgentes = []
                
                for evento in eventos_fiscales:
                    dias_restantes = (evento["fecha"] - hoy).days
                    pagado = pagos_realizados.get(evento["id"], False)
                    
                    if pagado:
                        st.info(f"✔️ **{evento['concepto']}**: Declarado y pagado a tiempo. ¡Sin deudas pendientes para esta fecha!")
                    elif 0 <= dias_restantes <= 3:
                        alerta_activa = True
                        mensaje_alerta = f"⚠️ **¡ATENCIÓN!** Se acerca la declaración y pago de **{evento['concepto']}** programada para la fecha **{evento['fecha'].strftime('%d/%m/%Y')}** (Faltan {dias_restantes} días)."
                        mensajes_urgentes.append(mensaje_alerta)

                if alerta_activa:
                    # Reproductor de audio oculto
                    audio_html = """
                        <audio autoplay style="display:none;">
                          <source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg">
                        </audio>
                    """
                    st.markdown(audio_html, unsafe_allow_html=True)

                    # Notificación flotante estilo bancario (toast superior) que desaparece en 5 segundos
                    texto_notificacion = "<br>".join(mensajes_urgentes)
                    banco_notif_html = f"""
                        <div id="banco-toast-alerta" style="
                            position: fixed;
                            top: 20px;
                            right: 20px;
                            z-index: 999999;
                            background-color: #fff3cd;
                            color: #856404;
                            padding: 16px 20px;
                            border-radius: 8px;
                            border-left: 6px solid #ffeeba;
                            border: 1px solid #ffeeba;
                            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                            font-family: sans-serif;
                            max-width: 400px;
                            animation: slideIn 0.5s ease-out;
                        ">
                            <div style="font-weight: bold; margin-bottom: 5px; font-size: 15px;">🔔 Notificación Fiscal Urgente</div>
                            <div style="font-size: 13px; line-height: 1.4;">{texto_notificacion}</div>
                        </div>

                        <style>
                        @keyframes slideIn {{
                            from {{ transform: translateX(100%); opacity: 0; }}
                            to {{ transform: translateX(0); opacity: 1; }}
                        }}
                        @keyframes fadeOut {{
                            from {{ opacity: 1; }}
                            to {{ opacity: 0; }}
                        }}
                        </style>

                        <script>
                            setTimeout(function() {{
                                var toast = document.getElementById('banco-toast-alerta');
                                if (toast) {{
                                    toast.style.animation = 'fadeOut 0.5s ease-out forwards';
                                    setTimeout(function() {{
                                        toast.remove();
                                    }}, 500);
                                }}
                            }}, 5000);
                        </script>
                    """
                    st.markdown(banco_notif_html, unsafe_allow_html=True)
                    
                else:
                    if not any(pagos_realizados.values()) and not any(0 <= (e["fecha"] - hoy).days <= 3 for e in eventos_fiscales):
                        st.success("✅ No hay obligaciones fiscales críticas a menos de 3 días de vencimiento en este momento.")

                # ==========================================
                # 3. LÍNEA DIVISORIA ANTES DEL CALENDARIO FISCAL
                # ==========================================
                st.divider()

                # ==========================================
                # 4. TÍTULOS Y TABLAS DEL CALENDARIO FISCAL
                # ==========================================
                st.subheader("📊 Calendario Fiscal 2026 - Sujeto Especial (SENIAT)")
                st.markdown("### 🗓️ Cronograma de Declaraciones y Pagos")
                
                # Estilo visual moderno para las tablas
                st.markdown("""
                <style>
                    .fiscal-table {
                        width: 100%;
                        border-collapse: collapse;
                        margin-bottom: 20px;
                        font-family: sans-serif;
                        font-size: 14px;
                    }
                    .fiscal-table th {
                        background-color: #2b313e;
                        color: white;
                        text-align: center;
                        padding: 8px;
                        border: 1px solid #ddd;
                    }
                    .fiscal-table td {
                        text-align: center;
                        padding: 8px;
                        border: 1px solid #ddd;
                    }
                    .header-iva { background-color: #d4edda; color: #155724; font-weight: bold; text-align: left; padding: 8px; }
                    .header-islr { background-color: #fff3cd; color: #856404; font-weight: bold; text-align: left; padding: 8px; }
                    .header-pensiones { background-color: #cce5ff; color: #004085; font-weight: bold; text-align: left; padding: 8px; }
                </style>
                """, unsafe_allow_html=True)

                meses = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEPT", "OCT", "NOV", "DIC"]
                
                q1_vals = ["❌", "❌", "❌", "❌", "❌", "❌", "❌", "31", "29", "20", "27", "16"]
                q2_vals = ["❌", "❌", "❌", "❌", "❌", "❌", "❌", "14", "14", "05", "13", "03"]
                islr_vals = ["❌", "❌", "❌", "❌", "❌", "❌", "❌", "07", "08", "09", "06", "09"]
                pensiones_vals = ["❌", "❌", "❌", "❌", "❌", "❌", "❌", "17", "29", "20", "27", "16"]

                if pagos_realizados["iva_1"]:
                    q1_vals[7] = "✅ Pagado"
                if pagos_realizados["iva_2"]:
                    q2_vals[7] = "✅ Pagado"
                if pagos_realizados["islr"]:
                    islr_vals[7] = "✅ Pagado"
                if pagos_realizados["pensiones"]:
                    pensiones_vals[7] = "✅ Pagado"

                # Renderizar Tabla 1: IVA 1era Quincena
                st.markdown("#### 1. IVA, Anticipos de ISLR, IGTF y Retenciones de IVA")
                html_iva_1 = f"""
                <table class="fiscal-table">
                    <tr><th colspan="13" class="header-iva">Primera Quincena (01 al 15) - R.I.F. Terminado en 0</th></tr>
                    <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
                    <tr><td><b>0</b></td>{"".join([f"<td>{val}</td>" for val in q1_vals])}</tr>
                </table>
                """
                st.markdown(html_iva_1, unsafe_allow_html=True)

                # Renderizar Tabla 2: IVA 2da Quincena
                html_iva_2 = f"""
                <table class="fiscal-table">
                    <tr><th colspan="13" class="header-iva" style="background-color: #e2f0d9;">Segunda Quincena (16 al último) - R.I.F. Terminado en 0</th></tr>
                    <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
                    <tr><td><b>0</b></td>{"".join([f"<td>{val}</td>" for val in q2_vals])}</tr>
                </table>
                """
                st.markdown(html_iva_2, unsafe_allow_html=True)

                # Renderizar Retenciones ISLR
                st.markdown("#### 2. Retenciones de Impuesto Sobre la Renta")
                html_islr = f"""
                <table class="fiscal-table">
                    <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
                    <tr><td><b>0</b></td>{"".join([f"<td>{val}</td>" for val in islr_vals])}</tr>
                </table>
                """
                st.markdown(html_islr, unsafe_allow_html=True)

                # Renderizar Ley de Pensiones
                st.markdown("#### 3. Ley de Protección de las Pensiones de Seguridad Social")
                html_pensiones = f"""
                <table class="fiscal-table">
                    <tr><th>R.I.F.</th>{"".join([f"<th>{m}</th>" for m in meses])}</tr>
                    <tr><td><b>0</b></td>{"".join([f"<td>{val}</td>" for val in pensiones_vals])}</tr>
                </table>
                """
                st.markdown(html_pensiones, unsafe_allow_html=True)

        else:
            pass


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
                st.dataframe(df_plan.head(20), use_container_width=True, height=500)
                
                if st.button("🚀 Iniciar Importación a Base de Datos", type="primary"):
                    columnas_sql = ['id', 'codigo', 'nombre', 'nivel', 'tipo', 'padre']
                    if all(col in df_plan.columns for col in columnas_sql):
                        from sqlalchemy import create_engine
                        engine = create_engine(f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{db_actual}")
                        
                        df_final = df_plan[columnas_sql]
                        df_final.to_sql('plan_cuentas', con=engine, if_exists='append', index=False)
                        st.success(f"✅ ¡Plan de cuentas sincronizado con {db_actual}!")
                        st.balloons()
                    else:
                        st.error("❌ Faltan columnas en el archivo.")

        with tab2:
            st.markdown("### 📋 Plan de Cuentas (Edición, Nuevos y Eliminación)")
            
            # 1. Cargamos los datos actuales
            df_actual = consultar_tabla_db(conn_empresa, "plan_cuentas")
            
            if df_actual is None or df_actual.empty:
                df_actual = pd.DataFrame(columns=['id', 'codigo', 'nombre', 'nivel', 'tipo', 'padre'])
            
            # 2. Editor interactivo
            # num_rows="dynamic" habilita el botón de eliminar (icono de basura) y agregar fila
            df_editado = st.data_editor(
                df_actual, 
                key="editor_plan_cuentas", 
                num_rows="dynamic", 
                use_container_width=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True), # ID inalterable
                    "codigo": st.column_config.TextColumn("Código Contable", required=True),
                    "nombre": st.column_config.TextColumn("Nombre Cuenta", required=True),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Activo", "Pasivo", "Patrimonio", "Ingreso", "Egreso"]),
                }
            )
            
            # 3. Guardado inteligente
            if st.button("💾 Guardar Cambios en Plan de Cuentas", type="primary"):
                try:
                    # Usamos tu función de actualización completa
                    actualizar_tabla_completa_db(conn_empresa, "plan_cuentas", df_editado)
                    st.success("✅ ¡Plan de cuentas actualizado correctamente!")
                    st.balloons()
                    st.rerun() # Recargamos para refrescar IDs si hubo nuevos
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

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
        if conn_empresa and conn_empresa.is_connected():
            conn_empresa.close()


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
            tab1, tab2, tab3 = st.tabs(["📖 Ver Libro Diario", "📤 Importar Excel", "🗑️ Vaciar Asiento de Diarios"])

            def exportar_a_excel(df):
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False, sheet_name='LibroDiario')
                return output.getvalue()

            with tab1:
                # --- 1. Selector de fechas ---
                col1, col2 = st.columns(2)
                with col1:
                    f_inicio = st.date_input("Fecha Inicio") 
                with col2:
                    f_fin = st.date_input("Fecha Fin")

                # ABRIMOS la conexión primero
                conn_temp = conectar_db(db_actual)
                
                # Pasamos la conexión (objeto), no el nombre (string)
                df_diario = consultar_libro_diario_db(conn_activa=conn_temp, fecha_inicio=f_inicio, fecha_fin=f_fin)
                
                # CERRAMOS la conexión después de usarla
                conn_temp.close()
                
                # --- 3. Visualización limpia ---
                if df_diario is not None and not df_diario.empty:
                    # Normalización
                    df_diario.columns = [c.lower() for c in df_diario.columns]
                    
                    # 1. Definimos df_editado SIEMPRE. 
                    # El editor devuelve el dataframe actualizado.
                    df_editado = st.data_editor(
                        df_diario, 
                        use_container_width=True, 
                        hide_index=True,
                        key="editor_diario"
                    )

                    # 2. Botón de Guardar
                    if st.button("💾 Guardar Cambios"):
                        # Alinear tipos de datos antes de comparar
                        # Esto asegura que estamos comparando manzanas con manzanas
                        df_editado_limpio = df_editado.astype(df_diario.dtypes)
                        
                        # Comparamos
                        if not df_editado_limpio.equals(df_diario):
                            # Filtramos las diferencias usando el df_editado limpio
                            cambios = df_editado_limpio[df_editado_limpio.ne(df_diario).any(axis=1)]
                            
                            try:
                                exito = actualizar_libro_diario_en_db(db_actual, cambios)
                                if exito:
                                    st.success(f"Se actualizaron {len(cambios)} registros.")
                                    st.rerun()
                                else:
                                    st.error("Error al guardar en la base de datos.")
                            except Exception as e:
                                st.error(f"Error técnico: {str(e)}")
                        else:
                            st.warning("No se detectaron cambios para guardar.")
                    
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
                        # 1. Lectura segura
                        df_subido = pd.read_excel(archivo_excel, header=None, skiprows=1, dtype=object)
                        
                        # Si el Excel trae más de 9 columnas, recortamos o ajustamos para evitar el error de tamaño
                        columnas_esperadas = ['id_ex', 'N_comprobante', 'Descripcion', 'Fecha', 'plan_de_cuentas', 'cuenta_contable', 'Ref', 'Debe', 'Haber']
                        
                        if len(df_subido.columns) > len(columnas_esperadas):
                            # Si sobra una columna (ej. la primera es un índice de Excel), nos quedamos con las necesarias desde la 0 o desde la 1
                            # Aquí asumimos que tomamos las columnas que coinciden con el total esperado
                            df_subido = df_subido.iloc[:, :len(columnas_esperadas)]
                        
                        df_subido.columns = columnas_esperadas
                        df_subido = df_subido.drop(columns=['id_ex'])
                        
                        # Limpieza
                        if str(df_subido.iloc[0, 1]).lower() in ['n_comprobante', 'nan']:
                            df_subido = df_subido.iloc[1:].reset_index(drop=True)
                        df_subido['Fecha'] = pd.to_datetime(df_subido['Fecha'], errors='coerce').dt.date

                        st.write("### ✅ Vista previa de la carga:")
                        st.dataframe(df_subido, hide_index=True, use_container_width=True)

                        # 2. Importación segura
                        if st.button("🚀 Confirmar e Importar al Diario"):
                            conn = conectar_db(db_actual) 
                            
                            if conn and conn.is_connected():
                                try:
                                    with st.spinner(f"Subiendo datos a la base: {db_actual}..."):
                                        if cargar_asientos_contables_db(df_subido, conn):
                                            st.balloons()
                                            st.success(f"✅ ¡Asientos procesados con éxito en {db_actual}!")
                                except Exception as e:
                                    st.error(f"Error crítico en la inserción: {e}")
                                finally:
                                    conn.close()
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
                            
                            if conn and conn.is_connected():
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
                                    conn.close()
                            else:
                                st.error("❌ Error de conexión.")
        else:
            st.warning("⚠️ Por favor, seleccione una empresa en el panel lateral para gestionar sus asientos.")


    if sub_opcion == "Conciliación Bancaria":
        st.title("🏦 Conciliación Bancaria")
        st.markdown("---")

        # 1. Recuperamos contexto y validamos
        db_actual = st.session_state.get('DB_ACTUAL')
        if not db_actual:
            st.error("No se ha seleccionado una base de datos.")
            st.stop()

        # 2. Abrimos la conexión de forma segura
        conn = conectar_db(db_actual)
        
        if not conn or not conn.is_connected():
            st.error(f"❌ Error: No se pudo conectar a la base de datos {db_actual}")
            st.stop()

        # 3. Selectores Globales (Aquí nacen los keys únicos)
        col1, col2 = st.columns([1, 1])
        with col1:
            mes_sel = st.selectbox(
                "Mes", 
                ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"], 
                index=2, 
                key="mes_seleccionado_conciliacion"  # <--- Cambia el key aquí por uno único
            )
        with col2:
            ano_sel = st.selectbox("Año", [2025, 2026, 2027], index=1, key="ano_seleccionado")

        # Tabs: Orden Lógico de trabajo
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
                if empresa_data['id'] != cliente_id:
                    st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                    st.stop()

            if not empresa_data:
                st.error("⚠️ No se pudieron cargar los datos de la empresa.")
            else:
                # 3. CARGA DE DATOS DINÁMICA
                try:
                    if conn and not conn.is_connected():
                        conn.reconnect(attempts=3, delay=1)

                    query_saldos = f"""
                        SELECT id, banco, mes, ano, saldo_inicial, saldo_final 
                        FROM `{db_actual}`.saldos_bancarios 
                        ORDER BY ano DESC, id DESC
                    """
                    
                    df_saldos = pd.read_sql(query_saldos, conn)
                    
                    if not df_saldos.empty:
                        df_view = df_saldos.copy()
                        def formatear_moneda(valor):
                            return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")

                        df_view['saldo_inicial'] = df_view['saldo_inicial'].apply(formatear_moneda)
                        df_view['saldo_final'] = df_view['saldo_final'].apply(formatear_moneda)
                        st.dataframe(df_view, use_container_width=True)
                    else:
                        st.info(f"No hay saldos registrados para {empresa_data['nombre_empresa']}.")
                        
                except Exception as e:
                    st.error(f"Error al cargar la tabla de saldos: {e}")

                # 4. FORMULARIO DE REGISTRO
                st.markdown("---")
                st.subheader("➕ Agregar / Editar Saldo")
                with st.form("form_saldos_main", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    m_input = c1.selectbox("Mes", ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                                                   "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"])
                    a_input = c2.selectbox("Año", [2025, 2026, 2027])
                    
                    c4, c5 = st.columns(2)
                    val_ini = c4.number_input("Saldo Inicial", value=0.00, format="%.2f")
                    val_fin = c5.number_input("Saldo Final", value=0.00, format="%.2f")
                    
                    if st.form_submit_button("Guardar / Actualizar Registro"):
                        # Asegúrate que tu función guardar_saldo_mensual también use db_actual internamente
                        if guardar_saldo_mensual(conn, 'BDV', m_input, a_input, val_ini, val_fin, db_name=db_actual):
                            st.success(f"✅ Registro de {m_input} guardado.")
                            st.rerun()

                # 5. ELIMINACIÓN SEGURA Y DINÁMICA
                with st.expander("🗑️ Eliminar un registro"):
                    id_eliminar = st.number_input("ID del registro a eliminar", min_value=1, step=1)
                    if st.button("Confirmar Eliminación"):
                        try:
                            cursor = conn.cursor()
                            # USAMOS db_actual PARA QUE CADA CLIENTE SOLO BORRE SUS DATOS
                            cursor.execute(f"DELETE FROM `{db_actual}`.saldos_bancarios WHERE id = %s", (id_eliminar,))
                            conn.commit()
                            cursor.close()
                            st.warning("Registro eliminado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar: {e}")

        # --- TAB 3: IMPORTACIÓN DE MOVIMIENTOS ---
        with tab2:
            st.subheader("📂 Importar nuevo estado de cuenta")

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
                # 3. INTERFAZ DE CARGA
                banco_sel = st.selectbox("Seleccione el Banco", ["Banco de Venezuela (BDV)", "Banesco", "Mercantil"], key="banco_select")
                archivo_banco = st.file_uploader("Suba el archivo Excel (.xlsx) del banco", type=["xlsx"], key="file_banco")

                if archivo_banco:
                    if st.button("Procesar e Importar"):
                        with st.spinner(f"Procesando archivo de {banco_sel}..."):
                            try:
                                # 4. ASEGURAR CONEXIÓN (Protocolo anti-socket roto)
                                if not conn.is_connected():
                                    conn.reconnect(attempts=3, delay=1)

                                resultado = False
                                
                                # Llamada a funciones, pasando la base de datos dinámica si fuera necesario
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

            # 1. SEGURIDAD Y CONTEXTO (Integración 15/06/2026)
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
                # 3. LÓGICA DE CONSULTA
                # 3. LÓGICA DE CONSULTA
                mes_map = {"Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                           "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12}
                mes_num = mes_map[mes_sel]

                # Inicializamos df_cuenta como vacío por seguridad
                df_cuenta = pd.DataFrame()

                try:
                    # 1. BLINDAJE DE CONEXIÓN: Verificar si está activa antes de usarla
                    if conn is None or not conn.is_connected():
                        st.warning("Reconectando a la base de datos...")
                        conn = conectar_db(db_actual) # Asumiendo que esta función crea la conexión
                        
                    # Si después de intentar reconectar sigue sin haber conexión, abortamos
                    if conn is None or not conn.is_connected():
                        st.error("No se pudo establecer conexión con la base de datos.")
                        st.stop()

                    # DEBUG: Verificamos qué base de datos estamos atacando
                    st.write(f"Conectando a base de datos: `{db_actual}`")

                    # Consulta de prueba para ver si la tabla tiene algo
                    query_check = f"SELECT COUNT(*) as total FROM `{db_actual}`.banco_movimientos"
                    res_check = pd.read_sql(query_check, conn)
                    st.write(f"Total de registros totales en la tabla: {res_check['total'][0]}")

                    # Consulta real por rango
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
                    df_cuenta = pd.read_sql(query, conn, params=(fecha_inicio, fecha_fin))
                    
                    # Mostrar resultados
                    if not df_cuenta.empty:
                        st.dataframe(df_cuenta, use_container_width=True)
                        st.write(f"**Total movimientos encontrados:** {len(df_cuenta)}")
                    else:
                        st.info(f"No hay movimientos para {empresa_data['nombre_empresa']} en {mes_sel} {ano_sel}.")

                except Exception as e:
                    st.error(f"Error específico en la consulta: {e}")

                # 4. ZONA ADMINISTRATIVA (Corregida: Dinámica y Segura)
                if rol == 'admin':
                    with st.expander("⚠️ Zona de Administración"):
                        if st.button("🗑️ Vaciar Todo (CUIDADO)"):
                            try:
                                cursor = conn.cursor()
                                # USAMOS LA VARIABLE DINÁMICA {db_actual}
                                cursor.execute(f"DELETE FROM `{db_actual}`.banco_movimientos WHERE empresa_id = %s", (cliente_id,))
                                conn.commit()
                                cursor.close()
                                st.success("Registros de esta empresa eliminados.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al vaciar registros: {e}")

        with tab4:
            st.subheader("📊 Resumen del Periodo")

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
                # 3. VERIFICACIÓN DE CONEXIÓN Y LANZAMIENTO
                # Intentamos asegurar la conexión antes de llamar a la función del tablero
                try:
                    if conn and not conn.is_connected():
                        conn.reconnect(attempts=3, delay=1)
                    
                    # Ahora que la seguridad y la conexión están blindadas, lanzamos el tablero
                    if conn and conn.is_connected():
                        mostrar_tablero_conciliacion(conn, mes_sel, ano_sel)
                    else:
                        st.error("❌ ERROR CRÍTICO: No se pudo establecer conexión con la base de datos.")
                        
                except Exception as e:
                    st.error(f"❌ Error al conectar con el tablero: {e}")

        # --- TAB 5: CIERRE DE MES (CANDADO DE SEGURIDAD) ---
        with tab5:
            st.subheader("🔒 Cierre y Bloqueo de Mes")
            # 1. SEGURIDAD INTEGRADA (Igual que en tus otras funciones)
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

            # 2. LÓGICA DE CIERRE (Uso dinámico de db_actual)
            mes_map = {"Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                       "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12}
            mes_num = mes_map[mes_sel]

            # Asegurar conexión antes de consultar
            try:
                if not conn.is_connected():
                    conn.reconnect(attempts=3, delay=1)
            except:
                pass 

            cursor = conn.cursor(buffered=True)

            # 3. CONSULTA DINÁMICA (Usamos f-string para la base de datos)
            query_check = f"SELECT COUNT(*) FROM `{db_actual}`.banco_movimientos WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s AND estado_conciliacion = 'Cerrado'"
            cursor.execute(query_check, (mes_num, ano_sel))
            es_cerrado = cursor.fetchone()[0] > 0
            cursor.close()

            if es_cerrado:
                st.error(f"🔒 El mes de {mes_sel} {ano_sel} en {empresa_data['nombre_empresa']} está CERRADO.")
            else:
                st.warning("⚠️ Acción irreversible: El cierre de mes bloquea ediciones.")
                if st.checkbox("✅ Entiendo las consecuencias, quiero cerrar el mes"):
                    if st.button("Confirmar Cierre de Mes"):
                        cursor = conn.cursor()
                        # 4. UPDATE DINÁMICO
                        query_update = f"""
                            UPDATE `{db_actual}`.banco_movimientos 
                            SET estado_conciliacion = 'Cerrado' 
                            WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s
                        """
                        cursor.execute(query_update, (mes_num, ano_sel))
                        conn.commit()
                        cursor.close()
                        st.success("✅ Mes cerrado con éxito.")
                        st.rerun()


    elif sub_opcion == "Consultar Comprobante":
        st.subheader("🔍 Buscador de Comprobantes")

        # 1. SEGURIDAD Y CONTEXTO (Integración 15/06/2026)
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
            # --- PARTE 1: CARGAR EL LISTADO (DINÁMICO) ---
            df_listado = pd.DataFrame()
            conn_list = conectar_db(db_actual) # Usamos db_actual, no una fija
            
            if conn_list:
                try:
                    # Consulta dinámica a la base de datos de la empresa activa
                    query_listado = f"""
                        SELECT n_comprobante as 'Nº', MAX(fecha) as 'Fecha', MAX(descripcion) as 'Concepto' 
                        FROM `{db_actual}`.asientos_contables 
                        GROUP BY n_comprobante ORDER BY fecha DESC
                    """
                    df_listado = pd.read_sql(query_listado, conn_list)
                finally:
                    conn_list.close()

            # --- PARTE 2: INTERFAZ DE SELECCIÓN ---
            n_comp_seleccionado = ""
            if not df_listado.empty:
                with st.expander("📋 Listado de Comprobantes", expanded=True):
                    event = st.dataframe(
                        df_listado, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )
                    if len(event.selection.rows) > 0:
                        idx = event.selection.rows[0]
                        n_comp_seleccionado = str(df_listado.iloc[idx]['Nº'])

            # --- PARTE 3: GENERAR REPORTE ---
            with st.expander("🔍 Generar Reporte", expanded=True):
                n_comp = st.text_input("Nº de Comprobante", value=n_comp_seleccionado, key="busc_comp")
                btn_comp = st.button("🔎 Generar Reporte", type="primary", use_container_width=True)

            if (btn_comp or n_comp_seleccionado) and n_comp:
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

            with tab1:
                # IMPORTANTE: Asegúrate de que consultar_saldos_iniciales_db() 
                # acepte 'db_actual' como argumento para ser dinámico.
                df_apertura = consultar_saldos_iniciales_db(db_actual)
                
                if not df_apertura.empty:
                    df_apertura.columns = [c.lower() for c in df_apertura.columns]
                    
                    fmt = {'debe': formato_contable, 'haber': formato_contable}
                    st.dataframe(df_apertura.style.format(fmt), use_container_width=True, hide_index=True)
                    
                    t_debe = df_apertura['debe'].astype(float).sum()
                    t_haber = df_apertura['haber'].astype(float).sum()
                    
                    c1, c2 = st.columns(2)
                    c1.metric("TOTAL DEBE", formato_contable(t_debe))
                    c2.metric("TOTAL HABER", formato_contable(t_haber))
                    
                    if abs(t_debe - t_haber) < 0.01:
                        st.success("✅ La apertura está cuadrada.")
                    else:
                        st.error(f"❌ Descuadre: {formato_contable(t_debe - t_haber)}")
                else:
                    st.warning(f"⚠️ No hay datos cargados para {empresa_data['nombre_empresa']}. Ve a la pestaña 'Importar Excel'.")
            
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
                                hide_index=True, use_container_width=True
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
                            if st.button("🧨 VACIAR TABLA DE SALDOS", type="primary", use_container_width=True):
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

    elif sub_opcion == "Consultar Cierre Contable":
        st.subheader("🔒 Asientos de Cierre")
        st.info("Aquí puedes programar la consulta a la tabla de cierres (similar a la de apertura).")


# D. MAYOR ANALÍTICO
# D. MAYOR ANALÍTICO
elif opcion_menu == "📖 Mayor Analítico":
    st.subheader("📖 Mayor Analítico")

    # 1. SEGURIDAD Y CONTEXTO
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')
    
    # Recuperamos las fechas del session_state para evitar el NameError
    f_inicio_global = st.session_state.get('f_inicio_global')
    f_fin_global = st.session_state.get('f_fin_global')

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
    
    # 3. EJECUCIÓN SEGURA
    elif not f_inicio_global or not f_fin_global:
        st.warning("⚠️ Debes seleccionar un periodo de fechas en el menú principal antes de continuar.")
    
    else:
        # Se pasan las fechas recuperadas de session_state
        mostrar_interfaz_mayor(f_inicio_global, f_fin_global, db_actual)



# E. ESTADOS FINANCIEROS -> BALANCE COMPROBACIÓN
elif sub_opcion == "Balance de Comprobación":
    # 1. Obtener datos de sesión
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE')
    db_actual = st.session_state.get('DB_ACTUAL')
    sucursal = st.session_state.get('SUCURSAL_SELECCIONADA', 'Todas')
    
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
            
            if not df_bal.empty:
                columnas_finales = ['codigo', 'nombre', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final', 'nivel']
                df_display = df_bal[columnas_finales].copy()
                
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

                        # Totales finales en el PDF (Usando las variables correctamente asignadas)
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

            else:
                st.info("No hay datos para el rango seleccionado.")

        except Exception as e:
            st.error(f"Error procesando balance: {e}")
        
        finally:
            if conn_temporal.is_connected():
                conn_temporal.close()
    else:
        st.error("No se pudo establecer la conexión para el reporte.")
