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
def obtener_datos_pie(db, f_fin):
    df_vacio = pd.DataFrame(columns=['nombre', 'Saldo Final'])
    
    conn = conectar_db(db)
    if not conn:
        return df_vacio
        
    # Consulta optimizada (Quitamos el CAST para que use índices de MySQL)
    query = f"""
        SELECT 
            descripcion as nombre,
            SUM(debe) as "Saldo Final"
        FROM `{db}`.asientos_contables 
        WHERE plan_cuentas LIKE '6%'
        AND fecha <= %s
        GROUP BY descripcion
        ORDER BY 2 DESC
        LIMIT 10
    """
    
    try:
        # Usamos context manager with para asegurar que el cursor se cierre siempre
        with conn.cursor() as cursor:
            df = pd.read_sql(query, conn, params=(f_fin,))
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

        opcion_menu = st.selectbox("📂 SELECCIONE UN MÓDULO", modulos_disponibles, key="opcion_menu_auditoria")

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

        # Calculamos también el último día del mes de forma segura con calendar
        import calendar
        ultimo_dia = int(calendar.monthrange(año, mes)[1])

        f_i = f"{año}-{mes:02d}-01"
        f_f = f"{año}-{mes:02d}-{ultimo_dia:02d}"

        # Variables de compatibilidad tipo date para consultas SQL
        f_inicio_global = datetime.date(año, mes, 1)
        f_fin_global = datetime.date(año, mes, ultimo_dia)

        # 2. DEBUG VISUAL (Para verificar la fecha real en curso)
        st.sidebar.info(f"Fecha en uso: {f_i} al {f_f}")  

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
                    df_pie = obtener_datos_pie(db, f_i) 
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
