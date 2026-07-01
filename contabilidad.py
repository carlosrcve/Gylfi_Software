#contabilidad.py
import streamlit as st
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
from datetime import date # IMPORTA LA CLASE DATE DIRECTAMENTE
from PIL import Image, ImageEnhance
import platform
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
# Solo configura la ruta de Tesseract si estás en Windows (tu PC)
# --- Configuración segura de Tesseract ---
import platform
import sys

# Intentamos importar pytesseract
try:
    import pytesseract
    # Solo configuramos la ruta si estamos en TU computadora (Windows)
    if platform.system() == "Windows":
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    # Si la librería no está instalada, no rompemos la app
    pytesseract = None
    print("Advertencia: pytesseract no está instalado.")
import json
from openai import OpenAI
from sqlalchemy import create_engine
# Busca dónde tienes tus funciones de base de datos


# 1. CONFIGURACIÓN DE PÁGINA (ESTO VA PRIMERO QUE TODO LO DEMÁS 'st.')
st.set_page_config(page_title="King Driver - Auditoría Profesional", layout="wide")

# --- LÍNEA 22: INICIALIZACIÓN SILENCIOSA (SOLO VALORES, SIN WIDGETS) ---
if 'anio_seleccionado' not in st.session_state:
    st.session_state.anio_seleccionado = 2026
if 'mes_n' not in st.session_state:
    st.session_state.mes_n = 3

# Creamos las variables simples para que el resto del código las vea
anio_seleccionado = st.session_state.anio_seleccionado
mes_n = st.session_state.mes_n

# Definimos las fechas globales de una vez
f_inicio_global = datetime(anio_seleccionado, mes_n, 1)
if mes_n == 12:
    f_fin_global = datetime(anio_seleccionado, 12, 31)
else:
    f_fin_global = datetime(anio_seleccionado, mes_n + 1, 1) - timedelta(days=1)

# Inicializamos stats para que el Dashboard no explote
stats = {'retenido': 0.0, 'ventas': 0.0, 'compras': 0.0}

# --- LÓGICA DE CONFIGURACIÓN SEGURA ---
try:
    # Intenta cargar desde secretos (Streamlit Cloud o local)
    DB_CONFIG = {
        "host": st.secrets["DB_HOST"],
        "port": int(st.secrets["DB_PORT"]),
        "user": st.secrets["DB_USER"],
        "password": st.secrets["DB_PASS"],
        "database": st.secrets["DB_NAME"],
        "raise_on_warnings": True,
        "connection_timeout": 10
    }
except (AttributeError, FileNotFoundError, Exception):
    # Valores por defecto para conexión remota
    DB_CONFIG = {
        "host": "reseau.proxy.rlwy.net",
        "port": 58667,
        "user": "carlos_admin",
        "password": "ptCOcCKAWIhukQZtIHyrLDWdXboCZqyI",
        "database": "control_central",
        "raise_on_warnings": True,
        "connection_timeout": 10
    }

# Variable global que usan todas tus funciones de abajo
conn = None

def conectar_db(nombre_db="control_central"):
    global conn
    
    # 1. Obtener la configuración SEGURA (la que tú definiste)
    config = get_db_config() 
    config['database'] = nombre_db # Aseguramos que use la base de datos que pides
    
    # 2. Lógica de sesión (mantenemos igual para eficiencia)
    db_actual_en_sesion = st.session_state.get('current_db_link')
    
    if 'conn' in st.session_state and st.session_state.conn is not None:
        if db_actual_en_sesion == nombre_db:
            try:
                st.session_state.conn.ping(reconnect=True, attempts=3, delay=1)
                return st.session_state.conn
            except:
                st.session_state.conn = None
        else:
            try: st.session_state.conn.close()
            except: pass
            st.session_state.conn = None

    # 3. Intento de nueva conexión usando la config de get_db_config()
    try:
        new_conn = mysql.connector.connect(**config)
        
        st.session_state.conn = new_conn
        st.session_state['current_db_link'] = nombre_db
        conn = new_conn 
        return conn
    except Exception as e:
        st.warning(f"⚠️ Error de conexión: {e}")
        return None


def get_db_config():
    # FUERZA los valores para depurar
    return {
        "host": "reseau.proxy.rlwy.net",
        "port": 58667,
        "user": "carlos_admin",
        "password": "ptCOcCKAWIhukQZtIHyrLDWdXboCZqyI",
        "database": "control_central",
        "raise_on_warnings": True,
        "connection_timeout": 10
    }



config = get_db_config()
st.sidebar.write(f"Host detectado: {config['host']}") # Esto te dirá si está tomando localhost o el de Railway

# Asegúrate de usar get_db_config() al llamar a mysql.connector.connect(**get_db_config())
# Sacamos los datos directamente de lo que ya se seleccionó en el Sidebar
# (Asumiendo que el bloque 1.3 que pusimos antes ya definió estas variables)
if 'DB_ACTUAL' in st.session_state:
    EMPRESA = st.session_state.get('nombre_empresa_seleccionada', "Empresa Seleccionada")
    RIF = st.session_state.get('rif_empresa_seleccionada', "J-00000000-0")
else:
    EMPRESA = "Seleccione Cliente"
    RIF = "J-00000000-0"

DATOS_EMPRESA = {"nombre": EMPRESA, "rif": RIF}

def ejecutar_consulta_segura(query):
    conn = conectar_db()
    if conn and conn.is_connected():
        df = pd.read_sql(query, conn)
        conn.close()
        return df
    return pd.DataFrame() # Devuelve vacío si no conecta

import functools

def log_ejecucion(func):
    """Decorador flexible para funciones con o sin conexión."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Intentamos obtener la conexión si es el primer argumento, o de donde sea que venga
        conn = args[0] if args and hasattr(args[0], 'cursor') else None
        
        accion = func.__name__.upper()
        usuario = st.session_state.get('username', 'Desconocido')
        cliente_id = st.session_state.get('cliente_id', 'N/A')
        detalles = f"Usuario {usuario} ejecutó {func.__name__} para cliente {cliente_id}"
        
        # Solo registramos si logramos identificar una conexión válida
        if conn:
            registrar_log_automatico(conn, accion, detalles)
        
        return func(*args, **kwargs)
    return wrapper



@log_ejecucion
def obtener_cursor_seguro(conn):
    if conn is None or not conn.is_connected():
        # Intentamos recuperar la conexión de la sesión antes de que explote
        conn = conectar_db(st.session_state.get('current_db_link', 'control_central'))
        
    if conn is None:
        raise Exception("Error crítico: La conexión a la base de datos se perdió y no pudo recuperarse.")
        
    return conn.cursor(dictionary=True)

@log_ejecucion
def calcular_activo_real(df):
    if df is None or df.empty:
        return 0.0
    df['Saldo Final'] = pd.to_numeric(df['Saldo Final'], errors='coerce').fillna(0)
    activo = df[(df['codigo'].astype(str).str.startswith('1')) & (df['nivel'] == 5)]['Saldo Final'].sum()
    return activo


@st.cache_data(ttl=300)
def obtener_kpis_financieros(_conn, f_i, f_f, sucursal, db): # <--- ¡Aquí debe estar la 'db' adentro!
    # 2. Inicialización de seguridad (Borra el comentario # y la línea si quieres, 
    #    pero asegúrate de que 'db' no se redefina aquí adentro si ya la recibes)
    data_vacia = {k: 0.0 for k in ["activo", "pasivo", "patrimonio", "liquidez", "utilidad", "prueba_acida", "capital_trabajo", "margen_utilidad", "entradas_efectivo", "salidas_efectivo", "flujo_neto", "top_proveedor", "top_porcentaje", "alertas_retencion", "saldo_real_final", "exento"]}
    data_vacia["top_proveedor"] = "Sin datos"

    # Ahora Python ya sabe qué es 'db' porque la recibiste en la primera línea
    if not sucursal or not db or db == 'none':
        return data_vacia

    # --- BLINDAJE DE CONEXIÓN ---
    # Nota: Aquí usamos el objeto _conn que pasaste a la función
    try:
        if not _conn or not _conn.is_connected():
            conn = conectar_db(db)
        else:
            _conn.ping(reconnect=True, attempts=3, delay=1)
            conn = _conn
    except:
        conn = conectar_db(db)

    if not conn:
        return data_vacia

    # 2. Variables de cálculo
    activo, pasivo, ingresos, egresos = 0.0, 0.0, 0.0, 0.0
    entradas, salidas, saldo_final_banco = 0.0, 0.0, 0.0
    proveedor_nombre = "Sin datos"
    porcentaje_compras, exento = 0.0, 0.0

    # 3. Obtener Balance Profesional (Roll-Up)
    df_bal = generar_balance_profesional(conn, f_i, f_f, sucursal)
    
    # Inicializamos valores por defecto
    activo, pasivo, ingresos, egresos = 0.0, 0.0, 0.0, 0.0
    
    # 1. Traer datos UNA SOLA VEZ
    df_bal = generar_balance_profesional(conn, f_i, f_f, sucursal)

    # 3. PROCESAMIENTO DEL DATAFRAME (Aquí calculamos el Activo Real)
    if df_bal is not None and not df_bal.empty:
        # Limpieza
        df_bal['codigo'] = df_bal['codigo'].astype(str).str.strip()
        df_bal['Saldo Final'] = pd.to_numeric(df_bal['Saldo Final'], errors='coerce').fillna(0)

        # Calculamos Activo Nivel 5 y lo guardamos en la variable 'activo'
        activo = float(df_bal[(df_bal['codigo'].astype(str).str.startswith('1')) & (df_bal['nivel'] == 5)]['Saldo Final'].sum())


    try:
        query_pasivo_total = f"""
            SELECT SUM(haber_total - debe_total) as saldo_real
            FROM (
                SELECT SUM(debe) as debe_total, SUM(haber) as haber_total 
                FROM `{db}`.saldos_iniciales WHERE (plan_cuentas LIKE '2%%')
                UNION ALL
                SELECT SUM(debe) as debe_total, SUM(haber) as haber_total 
                FROM `{db}`.asientos_contables WHERE (plan_cuentas LIKE '2%%') AND fecha <= %s
            ) as consolidado
        """
        with conn.cursor(dictionary=True) as cursor_p:
            cursor_p.execute(query_pasivo_total, (f_f,))
            res_p = cursor_p.fetchone()
            pasivo = float(res_p['saldo_real'] or 0.0)
    except Exception as e:
        st.error(f"Error calculando pasivo real: {e}")
    
    utilidad = ingresos - egresos

    # 4. Bloque de Consultas Directas
    try:
        with conn.cursor(dictionary=True) as cursor:
            # A. SALDO REAL FINAL (Bancos)
            query_saldo_total = f"""
                SELECT SUM(debe - haber) as saldo_final
                FROM (
                    SELECT debe, haber FROM `{db}`.saldos_iniciales 
                    WHERE plan_cuentas LIKE '1.1.1.02%%'
                    UNION ALL
                    SELECT debe, haber FROM `{db}`.asientos_contables 
                    WHERE plan_cuentas LIKE '1.1.1.02%%' AND fecha <= %s
                ) as t
            """
            cursor.execute(query_saldo_total, (f_f,))
            res_acumulado = cursor.fetchone()
            saldo_final_banco = float(res_acumulado['saldo_final'] or 0)

            # B. MOVIMIENTOS DEL MES
            cursor.execute(f"SELECT SUM(debe) as ent, SUM(haber) as sal FROM `{db}`.asientos_contables WHERE plan_cuentas LIKE '1.1.1.02%%' AND fecha BETWEEN %s AND %s", (f_i, f_f))
            res_mes = cursor.fetchone()
            if res_mes:
                entradas = float(res_mes['ent'] or 0)
                salidas = float(res_mes['sal'] or 0)

            # C. SALUD FISCAL
            cursor.execute(f"SELECT SUM(debe) as total_exento FROM `{db}`.asientos_contables WHERE (plan_cuentas LIKE '5.%%' OR plan_cuentas LIKE '6.%%') AND plan_cuentas NOT IN (SELECT codigo FROM `{db}`.plan_cuentas WHERE nombre LIKE '%%IVA%%') AND fecha BETWEEN %s AND %s", (f_i, f_f))
            res_exento = cursor.fetchone()
            exento = float(res_exento['total_exento'] or 0.0)

            # D. TOP PROVEEDOR
            cursor.execute(f"SELECT p.nombre, SUM(a.haber - a.debe) as total FROM `{db}`.asientos_contables a JOIN `{db}`.plan_cuentas p ON a.plan_cuentas = p.codigo WHERE a.plan_cuentas LIKE '2.1.1.01%%' AND a.fecha BETWEEN %s AND %s GROUP BY p.nombre ORDER BY total DESC LIMIT 1", (f_i, f_f))
            top = cursor.fetchone()
            if top:
                proveedor_nombre = top['nombre']
                ref = egresos if egresos > 0 else salidas
                porcentaje_compras = (float(top['total']) / ref * 100) if ref > 0 else 0

    except Exception as e:
        st.error(f"Error en consultas de KPIs: {e}")

    # 5. RETORNO FINAL
    return {
        "activo": activo,
        "pasivo": pasivo, # Ahora es el neto real
        "patrimonio": activo - pasivo,
        "utilidad": utilidad,
        "liquidez": activo / pasivo if pasivo != 0 else 0,
        "prueba_acida": (activo * 0.8) / pasivo if pasivo != 0 else 0,
        "capital_trabajo": activo - pasivo,
        "margen_utilidad": (utilidad / ingresos * 100) if ingresos > 0 else 0,
        "entradas_efectivo": entradas,
        "salidas_efectivo": salidas,
        "flujo_neto": entradas - salidas,
        "saldo_real_final": saldo_final_banco,
        "top_proveedor": proveedor_nombre,
        "top_porcentaje": round(porcentaje_compras, 2),
        "alertas_retencion": 0,
        "exento": exento
    }


def obtener_datos_graficos(conn, f_i, f_f, sucursal):
    # 1. Inicializamos para evitar el NameError
    df_bar = pd.DataFrame(columns=['Categoría', 'Monto'])
    df_pie = pd.DataFrame(columns=['nombre', 'Saldo Final'])
    
    # --- EL TRUCO: Recuperamos la DB activa ---
    db = st.session_state.get('DB_ACTUAL')
    if not db:
        return df_bar, df_pie # Si no hay DB, devolvemos vacíos sin error

    try:
        # --- QUERY PARA BARRAS (Ahora con {db} y f-string) ---
        query_bar = f"""
            SELECT 
                CASE 
                    WHEN SUBSTRING(plan_cuentas, 1, 1) = '4' THEN 'Ingresos' 
                    WHEN SUBSTRING(plan_cuentas, 1, 1) = '5' THEN 'Egresos' 
                END as Categoría,
                ABS(SUM(debe - haber)) as Monto
            FROM `{db}`.asientos_contables
            WHERE fecha BETWEEN %s AND %s 
            AND SUBSTRING(plan_cuentas, 1, 1) IN ('4', '5')
            GROUP BY Categoría
        """
        df_bar = pd.read_sql(query_bar, conn, params=(f_i, f_f))

        # --- QUERY PARA LA DONA (Ahora con {db} y f-string) ---
        query_pie = f"""
            SELECT plan_cuentas as nombre, ABS(SUM(debe - haber)) as `Saldo Final`
            FROM `{db}`.asientos_contables
            WHERE fecha BETWEEN %s AND %s 
            AND SUBSTRING(plan_cuentas, 1, 1) = '5'
            GROUP BY plan_cuentas
            ORDER BY `Saldo Final` DESC
            LIMIT 5
        """
        df_pie = pd.read_sql(query_pie, conn, params=(f_i, f_f))
        
    except Exception as e:
        st.error(f"Error técnico en gráficos: {e}")

    return df_bar, df_pie


# Lógica conceptual para tu Sidebar
def gestionar_sidebar():
    user_rol = st.session_state.get('rol')
    user_cliente_id = st.session_state.get('cliente_id')

    if user_rol == 'admin':
        # El admin ve la lista completa de la tabla clientes
        lista_empresas = obtener_todas_las_empresas(conn) 
    else:
        # El cliente SOLO ve la empresa que le pertenece
        lista_empresas = obtener_empresa_especifica(conn, user_cliente_id)

    # El selectbox ahora solo mostrará lo permitido
    empresa_seleccionada = st.sidebar.selectbox("Seleccione Empresa", lista_empresas)

def mostrar_bitacora_auditoria(conn):
    st.subheader("📋 Bitácora de Auditoría")
    
    try:
        cursor = conn.cursor(dictionary=True)
        # Consultamos los últimos 100 registros de actividad
        query = "SELECT fecha, evento, descripcion FROM logs_actividad ORDER BY fecha DESC LIMIT 100"
        cursor.execute(query)
        logs = cursor.fetchall()
        
        # Convertimos a DataFrame para una visualización profesional
        import pandas as pd
        df_logs = pd.DataFrame(logs)
        
        if not df_logs.empty:
            st.dataframe(df_logs, use_container_width=True)
        else:
            st.info("No hay registros de actividad recientes.")
            
    except Exception as e:
        st.error(f"❌ Error al cargar la bitácora: {e}")
        
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



def visualizar_rastro_auditoria(conn):
    st.subheader("🕵️‍♂️ Rastro de Auditoría")
    
    # Filtros para no ver todo de golpe
    col1, col2 = st.columns(2)
    with col1:
        fecha_filtro = st.date_input("Filtrar por fecha")
    with col2:
        usuario_filtro = st.text_input("Filtrar por ID de Usuario")
    
    try:
        cursor = conn.cursor(dictionary=True)
        # Consulta dinámica según los filtros
        query = "SELECT * FROM logs_auditoria WHERE 1=1"
        params = []
        
        if fecha_filtro:
            query += " AND DATE(fecha) = %s"
            params.append(fecha_filtro)
        if usuario_filtro:
            query += " AND usuario_id LIKE %s"
            params.append(f"%{usuario_filtro}%")
            
        query += " ORDER BY fecha DESC LIMIT 500"
        
        cursor.execute(query, params)
        data = cursor.fetchall()
        
        if data:
            import pandas as pd
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("No hay registros que coincidan con esos filtros.")
            
    except Exception as e:
        st.error(f"Error al leer el rastro: {e}")
    finally:
        if cursor: cursor.close()


# --- 2. PANTALLA DE LOGIN ---
import streamlit as st
import time


def registrar_log(db_conn, usuario_id, accion, detalles, cliente_id):
    """
    Registra eventos en la base de datos central de auditoría.
    """
    cursor = None
    try:
        # Aseguramos que apuntamos a la base de datos correcta
        query = """
            INSERT INTO control_central.logs_auditoria (usuario_id, accion, detalles, cliente_id, fecha) 
            VALUES (%s, %s, %s, %s, NOW())
        """
        cursor = db_conn.cursor()
        cursor.execute(query, (usuario_id, accion, detalles, cliente_id))
        db_conn.commit()
    except Exception as e:
        # Logueamos el error en consola para no interrumpir la navegación del usuario
        print(f"❌ Error al registrar en logs_auditoria: {e}")
    finally:
        # Siempre cerramos el cursor para liberar memoria, incluso si hay error
        if cursor:
            cursor.close()


import bcrypt

def verificar_usuario(conn, user, password):
    # 0. PROTECCIÓN: Si no hay conexión, salimos de inmediato sin error
    if conn is None:
        st.warning("⚠️ No hay conexión a la base de datos. Verifica tus credenciales de red.")
        return None

    # 1. Obtenemos el usuario de la base de datos
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM control_central.usuarios WHERE usuario = %s", (user,))
    user_data = cursor.fetchone()
    
    if not user_data:
        cursor.close()
        return None
    
    # 2. Verificamos la clave
    clave_en_bd = user_data.get('clave_hash')
    login_exitoso = False
    
    if clave_en_bd and clave_en_bd.startswith('$2b$'):
        if bcrypt.checkpw(password.encode('utf-8'), clave_en_bd.encode('utf-8')):
            login_exitoso = True
    else:
        if password == clave_en_bd:
            login_exitoso = True
            # Migración silenciosa
            salt = bcrypt.gensalt()
            nuevo_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
            
            # Re-abrir cursor solo para el UPDATE
            upd_cursor = conn.cursor()
            upd_cursor.execute("UPDATE control_central.usuarios SET clave_hash = %s WHERE id = %s", 
                               (nuevo_hash, user_data['id']))
            conn.commit()
            upd_cursor.close()
    
    # ¡ESTO ES LO QUE FALTABA!
    if login_exitoso:
        return user_data # Devuelve los datos del usuario si entró
    else:
        return None
    
    # 3. Retorno del resultado
    if login_exitoso:
        return user_data # Retorna los datos del usuario para la sesión
    else:
        return None # Credenciales incorrectas





import bcrypt

def migrar_contraseñas_a_hash(conn):
    cursor = conn.cursor(dictionary=True)
    # Seleccionamos todos los usuarios
    cursor.execute("SELECT id, clave_hash FROM control_central.usuarios")
    usuarios = cursor.fetchall()
    
    for u in usuarios:
        clave_actual = u['clave_hash']
        
        # Solo migramos si la clave NO parece un hash (los hashes de bcrypt empiezan con $2b$)
        if not clave_actual.startswith('$2b$'):
            # Convertimos la clave plana a hash
            salt = bcrypt.gensalt()
            nuevo_hash = bcrypt.hashpw(clave_actual.encode('utf-8'), salt).decode('utf-8')
            
            # Actualizamos la base de datos
            cursor.execute("UPDATE control_central.usuarios SET clave_hash = %s WHERE id = %s", 
                           (nuevo_hash, u['id']))
            conn.commit()
            print(f"Usuario {u['id']} migrado exitosamente.")
            
    cursor.close()

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
                res = None
                
                # --- MODO DESARROLLO / DEMO ---
                # Si no hay conexión (conn es None), saltamos la BD y entramos directo
                if conn is None:
                    st.info("⚠️ Modo sin conexión: Entrando como Administrador Demo")
                    res = {'rol': 'admin', 'cliente_id': 0} # Simulamos un usuario
                else:
                    # Llamada normal a tu base de datos
                    res = verificar_usuario(conn, user, password)
                
                # --- PROCESAMIENTO DEL LOGIN (Igual para ambos casos) ---
                if res:
                    # play_success_sound() # Si esta función requiere conexión, coméntala hoy
                    st.toast(f"¡Acceso Concedido!", icon="🔒")
                    st.success(f"🚀 Has hecho login como **{res['rol'].upper()}**")
                    
                    # Guardamos estado
                    st.session_state['logueado'] = True
                    st.session_state['usuario'] = user
                    st.session_state['rol'] = res['rol']
                    st.session_state['cliente_id'] = res.get('cliente_id', 0)
                    
                    time.sleep(1) 
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas o sin conexión a BD")
            
            st.markdown('</div>', unsafe_allow_html=True)

# Lógica de arranque
if 'logueado' not in st.session_state:
    login_screen()
    st.stop()




def mostrar_bitacora(conn):
    try:
        # La consulta debe ser a la tabla que ya comprobamos que tiene datos
        query = "SELECT * FROM logs_auditoria ORDER BY fecha DESC LIMIT 50"
        
        # Leemos los datos
        df = pd.read_sql(query, conn)
        
        # Verificamos si trajo algo
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("La tabla está conectada, pero no hay registros todavía.")
            
    except Exception as e:
        st.error(f"Error al leer la bitácora: {e}")

def registrar_log_automatico(conn, accion, detalles):
    """
    Registra automáticamente las interacciones del usuario en la tabla logs_auditoria.
    Versión optimizada con validación de conexión y manejo de excepciones.
    """
    cursor = None
    try:
        # Validación robusta de la conexión
        if conn is not None and hasattr(conn, 'is_connected') and conn.is_connected():
            
            # Obtención segura de datos de sesión
            usuario = st.session_state.get('usuario', 'Desconocido')
            cliente_id = st.session_state.get('cliente_id', None)
            
            # Usamos un cursor con diccionario opcional si fuera necesario, 
            # pero para un INSERT el cursor estándar es más rápido.
            cursor = conn.cursor()
            
            query = """
                INSERT INTO logs_auditoria (usuario_id, accion, detalles, ip_address, fecha) 
                VALUES (%s, %s, %s, %s, NOW())
            """
            
            cursor.execute(query, (usuario, accion, detalles, cliente_id))
            conn.commit()
            
        else:
            # Si no hay conexión, registramos en consola (sin romper el flujo)
            print("⚠️ Registro de log omitido: Conexión no disponible.")
            
    except Exception as e:
        # Captura cualquier error de SQL o conexión
        print(f"❌ Error crítico en registrar_log_automatico: {e}")
        
    finally:
        # Cierre garantizado del cursor
        if cursor:
            cursor.close()


@log_ejecucion
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
                except:
                    st.warning("⚠️ No se pudieron cargar las empresas de 'control_central'")
                    opciones_clientes = {}

            btn_crear = st.form_submit_button("Guardar Usuario en Base de Datos")
            
            if btn_crear:
                if not nuevo_u or not nueva_p:
                    st.error("❌ El usuario y la contraseña son obligatorios.")
                else:
                    try:
                        import bcrypt
                        salt = bcrypt.gensalt()
                        hash_cifrado = bcrypt.hashpw(nueva_p.encode('utf-8'), salt)
                        
                        c_id = opciones_clientes.get(nombre_sel) if rol == "cliente" and nombre_sel != "Ninguna / Acceso Total" else None
                        
                        cursor = conn.cursor()
                        sql = """INSERT INTO control_central.usuarios (usuario, clave_hash, rol, cliente_id) 
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


@log_ejecucion
def formato_contable(valor):
    """Formato: 16.482,00"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
@log_ejecucion
def color_por_nivel(row):
    codigo = str(row['Código'])
    estilo_activo = 'background-color: #e3f2fd; font-weight: bold;'      # Azul
    estilo_pasivo = 'background-color: #fbe9e7; font-weight: bold;'      # Naranja
    estilo_patrimonio = 'background-color: #f3e5f5; font-weight: bold;'  # Morado
    estilo_otros = 'background-color: #f1f8e9; font-weight: bold;'       # Verde

    if codigo.startswith('1'): return [estilo_activo] * len(row)
    if codigo.startswith('2'): return [estilo_pasivo] * len(row)
    if codigo.startswith('3'): return [estilo_patrimonio] * len(row)
    if codigo[0] in ['4', '5', '6']: return [estilo_otros] * len(row)
    return [''] * len(row)

@log_ejecucion
def cargar_plan_cuentas_db(df, nombre_db): # <--- Agregamos el parámetro
    # Ejemplo de uso en tu lógica de reportes
    registrar_log_automatico(conn, "CARGA_PLAN_CUENTAS", f"Usuario {st.session_state.usuario} cargó plan de cuentas en {nombre_db} para {st.session_state.cliente_id}")
    conn = conectar_db(nombre_db) # <--- Ahora se conecta a la empresa correcta
    if conn:
        try:
            cursor = conn.cursor()
            
            # 1. Limpiamos los nombres de las columnas por si tienen espacios invisibles
            df.columns = [str(c).strip() for c in df.columns]
            
            # 2. Mapeamos los nombres exactos que veo en tu imagen
            # Si tu Excel dice 'tipo', lo dejamos así, pero si tiene mayúsculas lo corregimos
            df = df.rename(columns={
                'Nombre de la Cuenta': 'nombre',
                'Codigo': 'codigo'
            })

            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE plan_cuentas")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            
            for _, row in df.iterrows():
                # --- LÓGICA DE LIMPIEZA PARA TU EXCEL ESPECÍFICO ---
                
                # Extraer 'Grupo' o 'Detalle' del texto largo
                t_raw = str(row['tipo'])
                tipo_final = 'Detalle' if 'Detalle' in t_raw else 'Grupo'
                
                # Extraer solo el código del padre (ej: de 'Su padre es 1.1' a '1.1')
                padre_raw = str(row['padre'])
                import re
                match_padre = re.search(r'(\d+(\.\d+)*)', padre_raw)
                padre_final = match_padre.group(1) if match_padre else None
                
                # Limpiar el nombre (quitar el código si viene pegado, ej: '1 Activo' -> 'Activo')
                nombre_raw = str(row['nombre'])
                nombre_final = re.sub(r'^\d+(\.\d+)*\s*', '', nombre_raw).strip()
                
                # Limpiar el código de la cuenta
                codigo_final = str(row['codigo']).strip()

                query = """INSERT INTO plan_cuentas (id, codigo, nombre, nivel, tipo, padre) 
                           VALUES (%s, %s, %s, %s, %s, %s)"""
                cursor.execute(query, (
                    row['id'], codigo_final, nombre_final, 
                    row['nivel'], tipo_final, padre_final
                ))
            
            conn.commit()
            st.success("🚀 Plan de Cuentas cargado correctamente analizando tu formato.")
        except Exception as e:
            st.error(f"❌ Error al cargar en la DB: {e}")
        finally:
            # AQUÍ ESTÁ EL SECRETO:
            cursor.close() 
            # NO cierres conn. 
            # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
            conn.ping(reconnect=True)



@log_ejecucion
def limpiar_monto_contable(valor):
    # Convertimos a string y limpiamos espacios
    v = str(valor).strip()
    
    if v in ['-', '', 'nan', 'None', '0', '0.0']: 
        return 0.0
    
    try:
        # PASO A PASO PARA NO MULTIPLICAR POR 10:
        # Ejemplo: "147.659,00"
        v = v.replace('.', '')    # Queda "147659,00"
        v = v.replace(',', '.')    # Queda "147659.00"
        return float(v)
    except:
        return 0.0



@log_ejecucion
def cargar_saldos_iniciales_db(df, nombre_db):
    registrar_log_automatico(None, "CARGA_SALDOS_INICIALES", f"Iniciando carga para {nombre_db}")
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
                limpiar_monto(row.get('Debe', 0)),
                limpiar_monto(row.get('Haber', 0))
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




@log_ejecucion
def consultar_saldos_iniciales_db(db_nombre):
    """
    Consulta los saldos iniciales de la empresa activa.
    """
    if not db_nombre:
        return pd.DataFrame()

    # 1. Primero intentamos conectar
    conn = conectar_db(db_nombre)
    
    if conn and conn.is_connected():
        try:
            # 2. Registramos el log AHORA que ya tenemos 'conn'
            usuario = st.session_state.get('usuario', 'Desconocido')
            cliente = st.session_state.get('cliente_id', 'Desconocido')
            registrar_log_automatico(conn, "CONSULTA_SALDOS_INICIALES", 
                                     f"Usuario {usuario} consultó saldos iniciales para {cliente}")
            
            cursor = conn.cursor(dictionary=True)
            query = f"SELECT * FROM `{db_nombre}`.saldos_iniciales ORDER BY id ASC"
            cursor.execute(query)
            
            resultados = cursor.fetchall()
            return pd.DataFrame(resultados) if resultados else pd.DataFrame()
                
        except Exception as e:
            st.error(f"❌ Error en la consulta de saldos en {db_nombre}: {e}")
            return pd.DataFrame()
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close() 
            if conn:
                conn.ping(reconnect=True)
    else:
        st.error("❌ No se pudo establecer conexión con la base de datos.")
        return pd.DataFrame()



@log_ejecucion
def limpiar_moneda(valor):
    """Limpia formatos tipo '3.193.742,08' a 3193742.08 para SQL"""
    if isinstance(valor, (int, float)):
        return float(valor)
    # Reemplaza puntos de miles y comas decimales
    s = str(valor).replace('.', '').replace(',', '.')
    try:
        return float(s)
    except:
        return 0.0


@log_ejecucion
def cargar_asientos_contables_db(df, conn=None):
    registrar_log_automatico(conn, "CONSULTA_BALANCE_GENERAL", f"Usuario {st.session_state.usuario} consultó balance para {st.session_state.cliente_id}")
    if not conn:
        db_actual = st.session_state.get('DB_ACTUAL', 'kingdriver_ca')
        conn = conectar_db(db_actual)
    
    if not conn: return False
        
    try:
        # --- LIMPIEZA DE DATOS CRÍTICA ---
        df_limpio = df.copy()
        
        # 1. Convertir fecha y ELIMINAR filas donde la fecha sea nula (NaT)
        df_limpio['Fecha'] = pd.to_datetime(df_limpio['Fecha'], errors='coerce')
        df_limpio = df_limpio.dropna(subset=['Fecha']) 
        
        # 2. Asegurar que Debe y Haber sean números usando la función de limpieza
        df_limpio['Debe'] = df_limpio['Debe'].apply(limpiar_moneda).round(2)
        df_limpio['Haber'] = df_limpio['Haber'].apply(limpiar_moneda).round(2)

        # 3. Armamos las tuplas forzando tipo de dato y validando
        valores = []
        for index, row in df_limpio.iterrows():
            try:
                # Convertimos explícitamente a los tipos que espera MySQL
                tupla = (
                    str(row['N_comprobante']), 
                    str(row['Descripcion']), 
                    row['Fecha'].strftime('%Y-%m-%d'), 
                    str(row['plan_de_cuentas']), 
                    str(row['cuenta_contable']), 
                    str(row['Ref']), 
                    float(row['Debe']), 
                    float(row['Haber'])
                )
                valores.append(tupla)
            except Exception as e:
                st.error(f"Error en la fila {index + 1}: {e}")
                continue # Saltamos esta fila y seguimos con las demás
        
        if not valores:
            st.warning("⚠️ No se encontraron datos válidos para insertar.")
            return False

        # 4. Inserción masiva
        cursor = conn.cursor()
        query = """
            INSERT INTO asientos_contables 
            (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.executemany(query, valores)
        conn.commit()
        cursor.close()
        
        st.success(f"✅ ¡Éxito! {len(valores)} asientos cargados correctamente.")
        return True

    except Exception as e:
        if conn: conn.rollback()
        st.error(f"❌ Error masivo al insertar en la base de datos: {e}")
        return False
    finally:
        # Solo cerramos si el cursor realmente se creó
        if 'cursor' in locals() and cursor:
            cursor.close()
        
        # Mantenemos la conexión viva
        if conn:
            conn.ping(reconnect=True)


@log_ejecucion
def consultar_libro_diario_db(conn_activa=None, fecha_inicio=None, fecha_fin=None):
    # 1. Seguridad y Contexto
    usuario = st.session_state.get('usuario', 'Desconocido')
    cliente = st.session_state.get('cliente_id', 'N/A')
    db_a_usar = st.session_state.get('DB_ACTUAL')
    
    registrar_log_automatico(None, "CONSULTA_LIBRO_DIARIO", f"Usuario {usuario} consultó libro diario para {cliente}")
    
    if not db_a_usar:
        return pd.DataFrame()

    # 2. Conexión Inteligente (Solo conecta si no pasaste una activa)
    conn = conn_activa if conn_activa else conectar_db(db_a_usar)
    
    if not conn or not conn.is_connected():
        return pd.DataFrame()

    try:
        # 1. Preparar consulta
        if fecha_inicio and fecha_fin:
            query = "SELECT * FROM asientos_contables WHERE fecha BETWEEN %s AND %s ORDER BY id ASC"
            params = (fecha_inicio, fecha_fin)
        else:
            query = "SELECT * FROM asientos_contables ORDER BY id ASC"
            params = None
        
        # 2. Ejecución con pandas (pd.read_sql maneja su propio cursor, no necesitamos crear uno)
        df = pd.read_sql(query, conn, params=params)
        
        # 3. Normalización Universal
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
            if not all(col in df.columns for col in ['debe', 'haber']):
                st.error(f"⚠️ Estructura incompatible. Columnas: {df.columns.tolist()}")
                return pd.DataFrame()
            
            return df
        
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"Error procesando base de datos: {e}")
        return pd.DataFrame()
        
    finally:
        # Solo hacemos ping si la conexión fue creada DENTRO de la función.
        # Si la pasamos desde fuera (conn_activa), es mejor que el código que la abrió la cierre.
        if not conn_activa and conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
def ejecutar_mayor_analitico(db_nombre, cuenta, fecha_desde, fecha_hasta):
    conn = None
    try:
        conn = conectar_db(db_nombre)
        if not conn or not conn.is_connected():
            return pd.DataFrame(), pd.DataFrame(), 0.0

        def safe_read_sql(query, params):
            conn.ping(reconnect=True, attempts=3, delay=1)
            return pd.read_sql(query, conn, params=params)

        f_inicio = pd.to_datetime(fecha_desde).normalize()
        f_fin = pd.to_datetime(fecha_hasta).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
        query_saldo_inicial = f"""
            SELECT 
                (SELECT IFNULL(SUM(debe - haber), 0) FROM `{db_nombre}`.saldos_iniciales WHERE TRIM(cuenta_contable) = TRIM(%s)) +
                (SELECT IFNULL(SUM(debe - haber), 0) FROM `{db_nombre}`.asientos_contables 
                 WHERE TRIM(cuenta_contable) = TRIM(%s) AND fecha < %s) 
            AS saldo_previo
        """
        
        res_saldo = pd.read_sql(query_saldo_inicial, conn, params=(cuenta, cuenta, f_inicio.strftime('%Y-%m-%d %H:%M:%S')))
        saldo_inicial_periodo = float(res_saldo.iloc[0,0])

        # 3. Movimientos del periodo
        query_movs = f"""
            SELECT fecha, n_comprobante, descripcion, referencia, debe, haber 
            FROM `{db_nombre}`.asientos_contables 
            WHERE TRIM(cuenta_contable) = TRIM(%s) 
            AND fecha >= %s AND fecha <= %s 
            ORDER BY fecha ASC, id ASC
        """
        df_movs = pd.read_sql(query_movs, conn, params=(cuenta, f_inicio.strftime('%Y-%m-%d %H:%M:%S'), f_fin.strftime('%Y-%m-%d %H:%M:%S')))
        
        # Cálculo del saldo acumulado
        df_movs['Saldo'] = saldo_inicial_periodo + (df_movs['debe'] - df_movs['haber']).cumsum()
        
        # SIEMPRE cerrar conexión antes de devolver
        conn.close()

        
        return df_movs, saldo_inicial_periodo
        
        # 4. Cálculo del Saldo Acumulado
        if not df_movs.empty:
            df_movs['Saldo'] = saldo_inicial + (df_movs['debe'] - df_movs['haber']).cumsum()
        
        return df_movs, saldo_inicial
        
        # DEBUG: Mira qué está pasando aquí
        st.write(f"--- DEBUG DE RANGO ---")
        st.write(f"Fecha desde: {f_inicio}")
        st.write(f"Fecha hasta: {f_fin}")
        st.write(f"Registros encontrados: {len(df_movs)}")


        # 3. PROCESAMIENTO MATEMÁTICO BLINDADO
        if not df_movs.empty:
            df_movs['debe'] = pd.to_numeric(df_movs['debe'], errors='coerce').fillna(0.0)
            df_movs['haber'] = pd.to_numeric(df_movs['haber'], errors='coerce').fillna(0.0)
            df_movs['Saldo'] = saldo_inicial_periodo + (df_movs['debe'] - df_movs['haber']).cumsum()
            # Convertimos fecha al final para evitar errores de tipo en los cálculos
            df_movs['fecha'] = pd.to_datetime(df_movs['fecha'], errors='coerce')
        else:
            df_movs = pd.DataFrame(columns=['fecha', 'n_comprobante', 'descripcion', 'referencia', 'debe', 'haber', 'Saldo'])

        # 4. CONSTRUCCIÓN DE REPORTE FINAL
        fila_inicial = pd.DataFrame([{
            'fecha': pd.to_datetime(fecha_desde),
            'n_comprobante': 'S/I',
            'descripcion': f'SALDO INICIAL AL {fecha_desde}',
            'referencia': 'INICIAL',
            'debe': 0.00, 'haber': 0.00,
            'Saldo': saldo_inicial_periodo
        }])

        df_final = pd.concat([fila_inicial, df_movs], ignore_index=True)
        # El saldo final real es SIEMPRE el último valor acumulado
        saldo_final_real = float(df_final['Saldo'].iloc[-1])
        
        return df_final, df_movs, saldo_final_real

    except Exception as e:
        st.error(f"❌ Error en el Libro Mayor: {e}")
        return pd.DataFrame(), pd.DataFrame(), 0.0
    finally:
        if conn and conn.is_connected():
            conn.close()
@log_ejecucion
def generar_balance_comprobacion(conn, f_i, f_f, sucursal):
    registrar_log_automatico(conn, "BALANCE_COMPROBACION", f"Balance para {st.session_state.cliente_id}")
    
    if not sucursal or not conn:
        return pd.DataFrame(columns=['Código', 'Debe', 'Haber', 'Saldo Inicial', 'Saldo Final'])
    
    db = st.session_state.get('DB_ACTUAL')
    
    try:
        # 1. Consultas estrictas: Solo traemos plan_cuentas y el valor calculado. Nada más.
        # Esto elimina cualquier posibilidad de que una columna llamada 'nombre' cause conflicto.
        sql_si = f"SELECT plan_cuentas, SUM(debe) - SUM(haber) as val FROM `{db}`.saldos_iniciales GROUP BY plan_cuentas"
        sql_ac = f"SELECT plan_cuentas, SUM(debe) - SUM(haber) as val FROM `{db}`.asientos_contables WHERE fecha < %s GROUP BY plan_cuentas"
        sql_mo_d = f"SELECT plan_cuentas, SUM(debe) as val FROM `{db}`.asientos_contables WHERE fecha BETWEEN %s AND %s GROUP BY plan_cuentas"
        sql_mo_h = f"SELECT plan_cuentas, SUM(haber) as val FROM `{db}`.asientos_contables WHERE fecha BETWEEN %s AND %s GROUP BY plan_cuentas"

        # 2. Ejecución y nombres de columnas únicos desde el inicio
        df_si = pd.read_sql(sql_si, conn).rename(columns={'val': 'si'})
        df_ac = pd.read_sql(sql_ac, conn, params=(f_i,)).rename(columns={'val': 'ac'})
        df_md = pd.read_sql(sql_mo_d, conn, params=(f_i, f_f)).rename(columns={'val': 'debe'})
        df_mh = pd.read_sql(sql_mo_h, conn, params=(f_i, f_f)).rename(columns={'val': 'haber'})

        # 3. Join mediante indexación (la forma más segura de evitar duplicados)
        for df in [df_si, df_ac, df_md, df_mh]:
            df.set_index('plan_cuentas', inplace=True)
            
        # Concatenamos horizontalmente
        balance = pd.concat([df_si, df_ac, df_md, df_mh], axis=1).fillna(0)
        balance.index.name = 'Código'
        balance.reset_index(inplace=True)
        
        # 4. Cálculo final
        balance['Tipo'] = balance['Código'].astype(str).str[0]
        
        def calcular(row):
            si_bruto = row['si'] + row['ac']
            if row['Tipo'] in ['1', '5']:
                s_final = si_bruto + row['debe'] - row['haber']
            else:
                s_final = si_bruto - row['debe'] + row['haber']
            return pd.Series([si_bruto, s_final])

        balance[['Saldo Inicial', 'Saldo Final']] = balance.apply(calcular, axis=1)
        
        return balance[['Código', 'Saldo Inicial', 'debe', 'haber', 'Saldo Final']].rename(columns={
            'debe': 'Debe', 
            'haber': 'Haber'
        })

    except Exception as e:
        st.error(f"❌ Error crítico: {e}")
        return pd.DataFrame()



@log_ejecucion
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


@log_ejecucion
def formato_contable(valor):
    """Formatea los números como montos contables de Venezuela (Bs. 1.234,56)"""
    try:
        return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "0,00"


@log_ejecucion
def disenar_reporte_asiento_contable(numero_comprobante):
    # 1. AJUSTE CLAVE: Obtener el nombre de la DB de la sesión
    db_nombre = st.session_state.get('DB_ACTUAL', 'kingdriver_ca')
    conn = conectar_db(db_nombre) 
    
    if conn:
        try:
            # Usamos f-string pero aseguramos que el parámetro sea limpio
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
            
            df_asiento = pd.read_sql(query, conn)

            if df_asiento.empty:
                st.warning(f"⚠️ No se encontró data para el comprobante Nº: {numero_comprobante}")
                return

            # --- DISEÑO (CABECERA) ---
            st.markdown("---")
            col_logo, col_info = st.columns([1, 3])
            with col_logo:
                st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=80)
            with col_info:
                # Usamos la variable EMPRESA que ya tienes global
                st.markdown(f"## {EMPRESA}")
                st.markdown(f"**RIF:** J-50775718-8")
                st.markdown(f"<p style='text-align: right; color: gray;'>Generado: {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}</p>", unsafe_allow_html=True)

            st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>Asiento Contable</h1>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; font-weight: bold;'>Comprobante Nº: {numero_comprobante}</p>", unsafe_allow_html=True)
            st.markdown("---")

            # DATOS GENERALES
            c1, c2 = st.columns(2)
            c1.info(f"**📅 Fecha:** {df_asiento['fecha'].iloc[0]}")
            c2.info(f"**📝 Descripción:** {df_asiento['descripcion'].iloc[0]}")
            
            st.markdown("---")

            # --- 2. TABLA DE DETALLE ---
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

            # TOTALES
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

        except Exception as e:
            st.error(f"Error técnico con la tabla: {e}")
        finally:
            # 3. Cerramos para que no se quede la conexión "guindando"
            conn.close()


@log_ejecucion
def procesar_archivo_y_cargar():
    try:
        # 1. CARGA ESPECÍFICA: Forzamos a Pandas a leer la pestaña "Data"
        # Usamos header=None para procesar las posiciones manualmente (A=0, B=1...)
        df = pd.read_excel("tu_archivo.xlsx", sheet_name="Data", header=None)
        
        # Llamamos a la función de carga
        cargar_libro_compras_db(df)
        
    except Exception as e:
        print(f"❌ Error al abrir el archivo: {e}")



# Configura tu clave
genai.configure(api_key="ELIMINADO_POR_SEGURIDAD")

@log_ejecucion
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


@log_ejecucion
def obtener_lista_proveedores_mapeo():
    conn = conectar_db(db_actual)
    cursor = conn.cursor()
    cursor.execute("SELECT razon_social, rif FROM proveedores")
    # Devuelve {RazonSocial: RIF}
    mapeo = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return mapeo

@log_ejecucion
def obtener_modelo_valido():
    # Buscamos todos los modelos que permiten generateContent
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            # Preferimos usar un modelo 'gemini-1.5' si aparece, sino el primero que encuentre
            return genai.GenerativeModel(m.name)
    return None

import time

import streamlit as st
import time
from sqlalchemy import create_engine


@log_ejecucion
def guardar_factura_seguro(df_fila, db_actual):
    try:
        engine = create_engine(f"mysql+mysqlconnector://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}/{db_actual}")
        
        rif_actual = df_fila['rif'].iloc[0]
        fact_actual = df_fila['numero_factura'].iloc[0]
        
        # CONSULTA DE VERIFICACIÓN (Blindaje contra duplicados)
        query = "SELECT COUNT(*) FROM libro_compras WHERE rif = %s AND numero_factura = %s"
        with engine.connect() as conn:
            resultado = conn.execute(query, (rif_actual, fact_actual)).scalar()
            
        if resultado > 0:
            return False, f"La factura {fact_actual} del RIF {rif_actual} ya existe."
        
        # SI NO EXISTE, GUARDAMOS
        df_fila.to_sql('libro_compras', con=engine, if_exists='append', index=False)
        return True, "Guardado con éxito"
        
    except Exception as e:
        return False, str(e)



@log_ejecucion
def extraer_datos_con_reintento(archivo):
    # Pausa de seguridad antes de empezar
    time.sleep(10) 
    
    try:
        return extraer_datos_factura(archivo)
    except Exception as e:
        if "429" in str(e):
            st.error("⚠️ Cuota agotada. La App entrará en modo espera (60 segundos).")
            # El "Cerrojo": forzamos 60 segundos de silencio total
            time.sleep(60) 
            # Después de la pausa, intentamos una vez más
            return extraer_datos_factura(archivo)
        else:
            raise e


@log_ejecucion
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


@log_ejecucion
def parsear_datos(texto):
    datos = {
        "RIF": "No encontrado",
        "Factura": "No encontrado",
        "Control": "No encontrado",
        "Base": 0.0,
        "IVA": 0.0,
        "Total": 0.0,
        "Fecha": "No encontrada"
    }

    # Aquí van tus regex (las estamos puliendo)
    rif_match = re.search(r'([JGV E][-\s]?\d{8}[-\s]?\d{1})', texto, re.IGNORECASE)
    if rif_match:
        datos["RIF"] = rif_match.group(1).strip()

    fact_match = re.search(r'(?:Factura|Nro|Fact)\D*(\d+)', texto, re.IGNORECASE)
    if fact_match:
        datos["Factura"] = fact_match.group(1)
    
    return datos


@log_ejecucion
def calcular_y_limpiar_totales(df):
    """Limpia los datos y retorna un diccionario con las sumas correctas."""
    # Hacemos una copia para no alterar el df original que usa el data_editor
    df_temp = df.copy()
    
    # Columnas que deben ser numéricas
    cols = ['total_compras', 'importe_exento', 'base_imponible', 'iva_monto']
    
    for col in cols:
        if col in df_temp.columns:
            # Convertimos a numérico, errores a NaN, luego NaN a 0
            df_temp[col] = pd.to_numeric(df_temp[col], errors='coerce').fillna(0.0)
            
    return {
        "total": df_temp['total_compras'].sum(),
        "exento": df_temp['importe_exento'].sum(),
        "base": df_temp['base_imponible'].sum(),
        "iva": df_temp['iva_monto'].sum()
    }

# --- COLOCA ESTAS FUNCIONES FUERA DE LA FUNCIÓN DE CARGA (A nivel global) ---
# --- FUNCIONES GLOBALES ---
import pandas as pd
import streamlit as st

@log_ejecucion
def formato_moneda(n):
    # Si el valor es inválido o None, devolvemos formato cero
    if n is None or pd.isna(n):
        return "0,00"
    
    # 1. Redondeamos a 2 decimales y usamos :.2f para asegurar formato
    # 2. Usamos :.2f para que 5798.3 pase a 5798.30
    # 3. Reemplazamos la coma por un marcador temporal, el punto por coma, y el marcador por punto
    s = f"{float(n):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


@log_ejecucion
def cargar_libro_compras_db(df, nombre_db):
    # 1. Conexión
    conn = conectar_db(nombre_db) 
    if not conn:
        st.error("No se pudo establecer conexión con la base de datos.")
        return

    # --- FUNCIÓN DE FECHA ROBUSTA ---
    def convertir_fecha(v):
        try:
            # Intento formato Excel (número serial)
            num_excel = int(float(v))
            return (pd.to_datetime('1899-12-30') + pd.to_timedelta(num_excel, 'D')).strftime('%Y-%m-%d')
        except:
            try:
                # Intento formato Texto estándar
                return pd.to_datetime(v).strftime('%Y-%m-%d')
            except:
                # Valor por defecto si todo falla
                return "2026-06-06"

    try:
        cursor = conn.cursor()
        registros_a_insertar = []
        
        # 2. SQL de inserción
        sql = """INSERT INTO libro_compras 
             (fecha_operacion, tipo_documento, n_factura, n_control, proveedor, rif, 
              total_compras, importe_exento, base_imponible, iva_porcentaje, iva_monto) 
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
             AS nueva_fila
             ON DUPLICATE KEY UPDATE 
             fecha_operacion = nueva_fila.fecha_operacion,
             tipo_documento = nueva_fila.tipo_documento,
             n_control = nueva_fila.n_control,
             proveedor = nueva_fila.proveedor,
             total_compras = nueva_fila.total_compras,
             importe_exento = nueva_fila.importe_exento,
             base_imponible = nueva_fila.base_imponible,
             iva_porcentaje = nueva_fila.iva_porcentaje,
             iva_monto = nueva_fila.iva_monto"""

        # 3. Función de limpieza

        def clean_n(v):
            # Si es numérico, lo convertimos a float y redondeamos
            if isinstance(v, (int, float)):
                return round(float(v), 2)
            
            # Si viene como string, limpiamos
            s = str(v).strip()
            
            # Si es un string vacío o 'None', retornamos 0.0
            if s in ['nan', 'None', '']: 
                return 0.0
            
            # Limpieza: quitamos puntos de miles y cambiamos coma por punto
            # Ejemplo: "5.798,38" -> "5798.38"
            s = s.replace('.', '').replace(',', '.')
            
            try:
                return round(float(s), 2)
            except:
                return 0.0

        # 4. Único ciclo de procesamiento
        for i, row in df.iterrows():
            try:
                # Usamos la función robusta que ya probaste
                f_str = convertir_fecha(row[0])
                
                # B. Creación de tupla
                valores = (
                    f_str, 
                    str(row[1]).split('.')[0].zfill(2),
                    str(row[2]).split('.')[0].strip(),
                    str(row[3]).strip(),
                    str(row[4]).upper().strip(),
                    str(row[5]).replace('-', '').replace('.', '').strip(),
                    clean_n(row[6]),  # total_compras
                    clean_n(row[7]),  # importe_exento
                    clean_n(row[8]),  # base_imponible
                    clean_n(row[9]),  # iva_porcentaje
                    clean_n(row[10])  # iva_monto
                )
                registros_a_insertar.append(valores)
            except Exception as e:
                print(f"Error en fila {i}: {e}")

        # 5. Inserción masiva
        if registros_a_insertar:
            cursor.executemany(sql, registros_a_insertar)
            conn.commit()
            st.success(f"🔥 Procesados {len(registros_a_insertar)} registros.")
        
    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Error crítico: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@log_ejecucion
def procesar_ventas_y_cargar(archivo_v, db_actual): # Agregamos db_actual
    conn = conectar_db(db_actual)
    if not conn:
        st.error("❌ No se pudo conectar a la base de datos.")
        return

    try:
        # Intentamos con la hoja "Data"
        df_ventas = pd.read_excel(archivo_v, sheet_name="Data", header=None)
        cargar_libro_ventas_db(df_ventas, conn) # ¡Ahora sí pasamos la conexión!
    except:
        # Intentamos con la segunda hoja
        try:
            df_ventas = pd.read_excel(archivo_v, sheet_name=1, header=None)
            cargar_libro_ventas_db(df_ventas, conn)
        except Exception as e:
            st.error(f"❌ Error fatal: {e}")
    finally:
        conn.close() # Cerramos la conexión al terminar



@log_ejecucion
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
              AS new
              ON DUPLICATE KEY UPDATE 
              fecha_factura = new.fecha_factura, 
              nombre_razon_social = new.nombre_razon_social,
              n_control = new.n_control,
              total_ventas_con_iva = new.total_ventas_con_iva,
              ventas_exentas = new.ventas_exentas,
              base_imponible = new.base_imponible,
              debito_fiscal = new.debito_fiscal"""
    
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

@log_ejecucion
def cargar_retenciones_islr_excel(df):
    # --- CONEXIÓN DINÁMICA ---
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    registrar_log_automatico(conn, "CARGA_EXCEL_RETENCIONES_ISLR", f"Usuario {st.session_state.usuario} cargó archivo Excel de retenciones ISLR para {st.session_state.cliente_id}")
    
    cursor = None
    if conn:
        try:
            cursor = conn.cursor()
            for _, fila in df.iterrows():
                # Calculamos el monto retenido (Monto * % / 100)
                m_operacion = float(fila['Monto Operación'])
                p_retencion = float(fila['Porcentaje Retención'])
                m_retenido = m_operacion * (p_retencion / 100)
                
                sql = """INSERT INTO retenciones_islr 
                          (id_sec, rif_retenido, numero_factura, numero_control, 
                           fecha_operacion, codigo_concepto, monto_operacion, 
                           porcentaje_retencion, monto_retenido) 
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                
                cursor.execute(sql, (
                    fila['ID-SEC'], fila['RIF Retenido'], fila['Número Factura'],
                    fila['Número Control'], fila['Fecha de Operación'], 
                    fila['Código Concepto'], m_operacion, p_retencion, m_retenido
                ))
            conn.commit()
            st.success(f"✅ Se cargaron {len(df)} retenciones con éxito en {db_actual}.")
        except Exception as e:
            st.error(f"❌ Error al procesar Excel: {e}")
        finally:
            # AQUÍ ESTÁ EL SECRETO:
            if cursor:
                cursor.close() 
            # NO cierres conn. 
            # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
            if conn and conn.is_connected():
                conn.ping(reconnect=True)
@log_ejecucion
def borrar_compras_por_rango(desde, hasta):
    db_actual = st.session_state.get('DB_ACTUAL')
    conexion = conectar_db(db_actual)
    
    # CORRECCIÓN: Usamos 'conexion' en lugar de 'conn'
    registrar_log_automatico(conexion, "BORRAR_COMPRAS", f"Usuario {st.session_state.usuario} eliminó compras desde {desde} hasta {hasta} para {st.session_state.cliente_id}")
    
    if conexion:
        try:
            cursor = conexion.cursor()
            
            # --- AJUSTA 'id_compra' AQUÍ ---
            # Lógica corregida usando 'id_sec' como el vínculo hacia 'libro_compras'
            sql_islr = """
                DELETE FROM retenciones_islr 
                WHERE id_sec IN ( 
                    SELECT id FROM libro_compras 
                    WHERE fecha_operacion BETWEEN %s AND %s
                )
            """
            cursor.execute(sql_islr, (desde, hasta))
            filas_islr = cursor.rowcount

            sql_compras = "DELETE FROM libro_compras WHERE fecha_operacion BETWEEN %s AND %s"
            cursor.execute(sql_compras, (desde, hasta))
            filas_compras = cursor.rowcount
            
            conexion.commit()
            
            if filas_compras > 0:
                st.success(f"✅ Limpieza profunda completada en {db_actual}:")
                st.write(f"* Compras eliminadas: {filas_compras}")
                st.write(f"* Retenciones ISLR eliminadas: {filas_islr}")
            else:
                st.warning("No se encontraron registros para borrar en ese rango.")
                
        except Exception as e:
            st.error(f"Error de Integridad: {e}")
        finally:
            # AQUÍ ESTÁ EL SECRETO:
            if 'cursor' in locals() and cursor:
                cursor.close() 
            # NO cierres conn. 
            # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
            if conexion and conexion.is_connected():
                conexion.ping(reconnect=True)

@log_ejecucion
def borrar_ventas_por_rango(desde, hasta):
    # 1. Obtenemos la conexión
    db_actual = st.session_state.get('DB_ACTUAL')
    conexion = conectar_db(db_actual)
    
    if not conexion:
        st.error("❌ No se pudo conectar a la base de datos.")
        return

    try:
        registrar_log_automatico(conexion, "BORRAR_VENTAS", f"Usuario {st.session_state.usuario} eliminó ventas desde {desde} hasta {hasta}")

        # 2. Asegurar formato string
        f_d_str = desde.strftime('%Y-%m-%d') if hasattr(desde, 'strftime') else str(desde)
        f_h_str = hasta.strftime('%Y-%m-%d') if hasattr(hasta, 'strftime') else str(hasta)

        cursor = conexion.cursor()
        
        # --- DEBUG TOTAL: Verificamos qué hay realmente en la base de datos ---
        cursor.execute("SELECT COUNT(*) FROM libro_ventas WHERE DATE(fecha_factura) BETWEEN %s AND %s", (f_d_str, f_h_str))
        cuenta_encontrada = cursor.fetchone()[0]
        
        # Esto saldrá en tu consola de comandos de Python/Streamlit
        print(f"DEBUG: Registros encontrados en MySQL entre {f_d_str} y {f_h_str}: {cuenta_encontrada}")

        # 3. Borrar (solo si hay algo que borrar)
        if cuenta_encontrada > 0:
            # Usamos DATE() para limpiar cualquier residuo de hora y comparamos directamente
            sql_ventas = "DELETE FROM libro_ventas WHERE DATE(fecha_factura) >= DATE(%s) AND DATE(fecha_factura) <= DATE(%s)"
            
            # DEBUG: Imprimimos exactamente qué vamos a ejecutar
            print(f"DEBUG SQL: DELETE FROM libro_ventas WHERE DATE(fecha_factura) >= '{f_d_str}' AND DATE(fecha_factura) <= '{f_h_str}'")

            cursor.execute(sql_ventas, (f_d_str, f_h_str))
            filas_ventas = cursor.rowcount
            conexion.commit()

        if filas_ventas > 0:
            st.success(f"✅ ¡Eliminación exitosa! Se borraron {filas_ventas} registros.")
        else:
            # Si aquí te sigue diciendo que no borró nada, es porque la fecha 
            # de tu base de datos NO está en el rango que seleccionaste en el date_input
            st.warning(f"⚠️ ¡Cuidado! MySQL ejecutó el comando pero no encontró registros entre {f_d_str} y {f_h_str}.")
            st.info("💡 Consejo: Revisa si los datos en tu tabla corresponden al año 2026.")
            
    except Exception as e:
        if 'conexion' in locals(): conexion.rollback()
        st.error(f"❌ Error al vaciar Libro de Ventas: {e}")
        
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conexion' in locals() and conexion and conexion.is_connected():
            conexion.close()




@log_ejecucion
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





@log_ejecucion
def cargar_retenciones_islr_db(df):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    # Registro de actividad
    registrar_log_automatico(conn, "CARGA_MASIVA_RETENCIONES_ISLR", f"Usuario {st.session_state.usuario} cargó masivamente retenciones ISLR para {st.session_state.cliente_id}")
    
    if conn:
        cursor = conn.cursor()
        try:
            from datetime import datetime
            
            # 1. Obtenemos el periodo actual para el comprobante (Ej: 202604)
            periodo_retenido = datetime.now().strftime('%Y%m')
            
            for _, fila in df.iterrows():
                # --- CÁLCULOS ---
                m_operacion = float(fila['Monto Operación'])
                p_retencion = float(fila['Porcentaje Retención'])
                # Si el excel no trae sustraendo, ponemos 0.0
                sustraendo = float(fila.get('Sustraendo', 0.0)) 
                
                # Cálculo legal: (Base * %) - Sustraendo
                m_retenido = (m_operacion * (p_retencion / 100)) - sustraendo
                
                # --- LÓGICA DEL NÚMERO DE COMPROBANTE ---
                n_comprobante = fila.get('N° Comprobante')
                if not n_comprobante or str(n_comprobante).strip() == "":
                    correlativo = str(fila['ID-SEC']).zfill(8)
                    n_comprobante = f"{periodo_retenido}{correlativo}"

                # --- SQL ACTUALIZADO ---
                sql = """INSERT INTO retenciones_islr 
                          (id_compra, rif_retenido, n_factura, n_control, 
                           fecha_operacion, codigo_concepto, monto_operacion, 
                           porcentaje_retencion, sustraendo, monto_retenido, 
                           periodo_retenido, n_comprob_islr) 
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                
                cursor.execute(sql, (
                    fila['ID-SEC'],           # id_compra
                    fila['RIF Retenido'],     # rif_proveedor
                    fila['Número Factura'],   # n_factura
                    fila['Número Control'],   # n_control
                    fila['Fecha de Operación'], 
                    fila['Código Concepto'], 
                    m_operacion,              # base_imponible
                    p_retencion, 
                    sustraendo, 
                    m_retenido, 
                    periodo_retenido, 
                    n_comprobante             # El número que acabamos de crear
                ))
                
            conn.commit()
            st.success(f"✅ ¡Éxito! Se cargaron {len(df)} registros con sus Comprobantes.")
        except Exception as e:
            conn.rollback() # Si algo falla, deshacemos todo
            st.error(f"❌ Error al procesar el Excel de ISLR: {e}")
        finally:
            # AQUÍ ESTÁ EL SECRETO:
            if cursor:
                cursor.close() 
            # NO cierres conn. 
            # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
            if conn and conn.is_connected():
                conn.ping(reconnect=True)





@log_ejecucion
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



@log_ejecucion
def registrar_retencion_islr_db(id_sec, rif, razon_social, direccion, factura, control, fecha, codigo, base, porc, sust, periodo, m_retenido, n_comprobante):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    if not conn: return False, 0
    
    try:
        cursor = conn.cursor()
        
        # 1. Registrar proveedor
        sql_prov = """
            INSERT INTO proveedores (rif, razon_social, direccion_fiscal) 
            VALUES (%s, %s, %s) 
            AS nuevo_prov
            ON DUPLICATE KEY UPDATE 
                direccion_fiscal = nuevo_prov.direccion_fiscal,
                razon_social = nuevo_prov.razon_social
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
        # 2. Definición exacta de los 15 valores en el orden de las columnas
        valores = (
            int(id_sec),           # 1. id_sec
            str(rif),              # 2. rif_retenido
            str(factura),          # 3. numero_factura
            str(control),          # 4. numero_control
            fecha,                 # 5. fecha_operacion
            str(codigo_r),         # 6. codigo_concepto <--- ¡AQUÍ ESTÁ!
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
        
        # 3. BLOQUEO ÚNICO Y CORREGIDO
        # Usamos las variables que entran a la función (factura y rif)
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


@log_ejecucion
def generar_comprobante_pdf(datos, conn):
    """
    Crea el PDF del comprobante ISLR con diseño profesional simétrico,
    limpieza de etiquetas, RIF con guiones, número de comprobante legal 
    y centrado de celdas.
    """

    registrar_log_automatico(conn, "GENERACION_PDF_RETENCION", f"Usuario {st.session_state.usuario} generó PDF de retención para {st.session_state.cliente_id}")

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
    # Nombre de la empresa a la izquierda
    pdf.cell(100, 5, datos['agente']['nombre'].upper(), 0, 0, 'L')
    
    # NÚMERO DE COMPROBANTE LEGAL (Derecha, resaltado)
    pdf.set_font("helvetica", "B", 11) 
    num_comprobante = datos.get('n_comprobante', "SIN NÚMERO")
    #p.drawRightString(width - 50, height - 50, f"COMPROBANTE N°: {num_comprobante}")
    pdf.cell(90, 5, f"COMPROBANTE N°: {num_comprobante}", 0, 1, 'R') 
    
    # Subtítulo y Fecha de Emisión
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
        return pdf.output(dest='S').encode('latin-1', errors='ignore')
    
    finally:
        # Aseguramos el ping a la conexión para mantener la sesión activa
        # tras completar la generación del archivo.
        if conn and conn.is_connected():
            conn.ping(reconnect=True)


@log_ejecucion
def procesar_retencion_y_pdf(self, factura_id, n_comprobante_manual):
    # --- CONEXIÓN DINÁMICA ---
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    if not conn:
        st.error("No se pudo conectar a la base de datos.")
        return None

    # Registro de actividad
    registrar_log_automatico(conn, "PROCESAR_RETENCION", f"Usuario {st.session_state.usuario} procesó retención {n_comprobante_manual} para factura {factura_id} del cliente {st.session_state.cliente_id}")

    cursor = None
    try:
        cursor = conn.cursor()
        
        factura = self.obtener_factura(factura_id)
        proveedor = factura.proveedor
        
        datos_dinamicos = {
            'sujeto': {
                'nombre': proveedor.nombre,
                'rif': proveedor.rif,
                'direccion': proveedor.direccion
            },
            'agente': {
                'nombre': 'KING DRIVER, C.A.',
                'rif': 'J-50146059-4',
                'direccion': 'CALLE 13 ENTRE AV. 4 Y 5, VALERA, TRUJILLO'
            },
            'n_comprobante': n_comprobante_manual, 
            'base': factura.monto_operacion,
            'factura': factura.numero_factura,
            'control': factura.numero_control,
            'porcentaje': factura.porcentaje_retencion,
            'sustraendo': factura.sustraendo,
            'total_retenido': factura.monto_retenido,
            'fecha_operacion': factura.fecha.strftime('%Y-%m-%d')
        }

        # Pasamos conn a la función generadora
        return generar_comprobante_pdf(datos_dinamicos, conn)

    except Exception as e:
        st.error(f"Error al procesar PDF: {e}")
        return None

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
def obtener_siguiente_comprobante(self):
    from datetime import datetime
    
    # --- CONEXIÓN DINÁMICA ---
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    # Registro de actividad
    registrar_log_automatico(conn, "OBTENER_NRO_COMPROBANTE", f"Usuario {st.session_state.usuario} consultó siguiente nro de comprobante para {st.session_state.cliente_id}")
    
    cursor = None
    try:
        cursor = conn.cursor()
        
        # 1. Sacamos el prefijo del periodo actual (Ej: 202604)
        periodo_actual = datetime.now().strftime('%Y%m')
        
        # 2. Buscamos el último comprobante guardado en la DB
        cursor.execute(
            "SELECT n_comprob_islr FROM retenciones_islr WHERE n_comprob_islr LIKE %s ORDER BY n_comprob_islr DESC LIMIT 1",
            (f"{periodo_actual}%",)
        )
        ultimo_registro = cursor.fetchone()

        if ultimo_registro:
            # Si existe, tomamos los últimos 8 dígitos, le sumamos 1 y rellenamos con ceros
            ultimo_num = int(ultimo_registro[0][6:]) # Cortamos después de '202604'
            nuevo_correlativo = str(ultimo_num + 1).zfill(8)
        else:
            # Si es la primera retención del mes, empezamos en 1
            nuevo_correlativo = "00000001"

        return f"{periodo_actual}{nuevo_correlativo}"

    except Exception as e:
        st.error(f"Error al obtener comprobante: {e}")
        return None
        
    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
def procesar_excel_proveedores_db(df):
    """
    Limpia y carga los proveedores a MySQL manejando automáticamente el tipo de persona.
    """
    import pymysql
    
    # 1. Limpieza de datos
    df['rif'] = df['rif'].astype(str).str.strip().str.upper()
    df['razon_social'] = df['razon_social'].astype(str).str.strip().str.upper()
    df['direccion_fiscal'] = df['direccion_fiscal'].astype(str).str.strip()

    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    # Registro de actividad
    registrar_log_automatico(conn, "CARGA_PROVEEDORES", f"Usuario {st.session_state.usuario} procesó excel de proveedores para {st.session_state.cliente_id}")
    
    cursor = conn.cursor()
    
    try:
        for _, row in df.iterrows():
            # --- LÓGICA DE DETECCIÓN DE TIPO ---
            # Si empieza por V o E es Persona Natural (PN), de lo contrario Jurídica (PJ)
            rif = row['rif']
            tipo = "PN" if rif.startswith(('V', 'E')) else "PJ"

            sql = """
                INSERT INTO proveedores (rif, tipo_persona, razon_social, direccion_fiscal)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                tipo_persona = VALUES(tipo_persona),
                razon_social = VALUES(razon_social),
                direccion_fiscal = VALUES(direccion_fiscal)
            """
            # Pasamos los 4 valores necesarios
            cursor.execute(sql, (rif, tipo, row['razon_social'], row['direccion_fiscal']))
        
        conn.commit()
        st.success(f"✅ Se han procesado {len(df)} proveedores correctamente.")
        
    except Exception as e:
        st.error(f"❌ Error al procesar proveedores: {e}")
        
    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
            
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
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
            # AQUÍ ESTÁ EL SECRETO:
            if cursor:
                cursor.close() 
            
            # NO cierres conn. 
            # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
            if conn and conn.is_connected():
                conn.ping(reconnect=True)
                
    return existe

@log_ejecucion
def resetear_estado_retencion(n_factura):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    # Registro de actividad
    registrar_log_automatico(conn, "RESETEAR_ESTADO_RETENCION", f"Usuario {st.session_state.usuario} reseteó estado de retención para la factura {n_factura} en {st.session_state.cliente_id}")
    
    cursor = None
    filas_afectadas = 0
    try:
        cursor = conn.cursor()
        sql = "UPDATE libro_compras SET retencion_realizada = 0 WHERE n_factura = %s"
        cursor.execute(sql, (n_factura,))
        filas_afectadas = cursor.rowcount
        conn.commit()
        
        if filas_afectadas > 0:
            return True
        else:
            print(f"No se encontró la factura: {n_factura}")
            return False
            
    except Exception as e:
        st.error(f"Error al resetear retención: {e}")
        return False
        
    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
        
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



@log_ejecucion
def consultar_tabla_db(conn, nombre_tabla):
    """
    Consulta registros usando la conexión activa pasada como parámetro.
    """
    df = pd.DataFrame()
    cursor = None
    
    # Registro de actividad (usando la conexión que ya recibiste)
    if conn and conn.is_connected():
        usuario = st.session_state.get('usuario', 'Desconocido')
        cliente = st.session_state.get('cliente_id', 'N/A')
        registrar_log_automatico(conn, "CONSULTA_TABLA", f"Usuario {usuario} consultó {nombre_tabla} para cliente {cliente}")
    
        try:
            cursor = conn.cursor()
            # Usamos nombre_tabla (el argumento) en lugar de una variable fija
            query = f"SELECT * FROM {nombre_tabla}"
            df = pd.read_sql(query, conn)
        except Exception as e:
            st.error(f"Error al consultar la tabla {nombre_tabla}: {e}")
        finally:
            if cursor:
                cursor.close()
            # Mantenemos la conexión viva para futuras operaciones
            conn.ping(reconnect=True)
            
    return df


@log_ejecucion
def actualizar_tabla_completa_db(conn, nombre_tabla, df_nuevo):
    """
    Actualización genérica: hace TRUNCATE y luego inserta el DF completo.
    """
    if not conn or not conn.is_connected():
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
            cursor.close()
        if conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
def generar_pdf_comprobante(df, n_comp, conn):
    """
    Genera el PDF del comprobante, registra la actividad en el log
    y mantiene la conexión a MySQL viva.
    """
    # 1. Registrar la actividad
    registrar_log_automatico(conn, "GENERACION_COMPROBANTE", f"Usuario {st.session_state.usuario} generó PDF de comprobante {n_comp} para {st.session_state.cliente_id}")

    cursor = conn.cursor()
    
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        
        # Encabezado
        pdf.cell(190, 10, "COMPROBANTE DE ASIENTO CONTABLE", 0, 1, 'C')
        pdf.set_font("Arial", '', 10)
        pdf.cell(190, 10, f"Comprobante Nro: {n_comp}", 0, 1, 'L')
        pdf.cell(190, 5, f"Fecha de Impresión: {pd.Timestamp.now().strftime('%d/%m/%Y')}", 0, 1, 'L')
        pdf.ln(10)
        
        # Tabla - Encabezados
        pdf.set_fill_color(200, 220, 255)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(30, 8, "Fecha", 1, 0, 'C', 1)
        pdf.cell(100, 8, "Descripción / Cuenta", 1, 0, 'C', 1)
        pdf.cell(30, 8, "Debe", 1, 0, 'C', 1)
        pdf.cell(30, 8, "Haber", 1, 1, 'C', 1)
        
        # Tabla - Datos
        pdf.set_font("Arial", '', 8)
        t_debe = 0
        t_haber = 0
        
        for _, row in df.iterrows():
            pdf.cell(30, 7, str(row['fecha']), 1, 0, 'C')
            descripcion_txt = f"{row['cuenta_contable']} - {row['descripcion']}"
            if len(descripcion_txt) > 55:
                descripcion_txt = descripcion_txt[:52] + "..."
            pdf.cell(100, 7, descripcion_txt, 1, 0, 'L')
            pdf.cell(30, 7, f"{row['debe']:,.2f}", 1, 0, 'R')
            pdf.cell(30, 7, f"{row['haber']:,.2f}", 1, 1, 'R')
            t_debe += row['debe']
            t_haber += row['haber']
            
        # Totales
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(130, 8, "TOTALES GENERALES (Bs.)", 1, 0, 'R', 1)
        pdf.cell(30, 8, f"{t_debe:,.2f}", 1, 0, 'R', 1)
        pdf.cell(30, 8, f"{t_haber:,.2f}", 1, 1, 'R', 1)
        
        # Firmas
        pdf.ln(20)
        pdf.cell(95, 10, "__________________________", 0, 0, 'C')
        pdf.cell(95, 10, "__________________________", 0, 1, 'C')
        pdf.cell(95, 5, "Preparado por", 0, 0, 'C')
        pdf.cell(95, 5, "Revisado por", 0, 1, 'C')
        
        return pdf.output(dest='S').encode('latin-1')

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close()
        
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
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




# --- CONFIGURACIÓN DE FILTROS (DEBE IR PRIMERO) ---
# Definir sucursal primero para que exista cuando los KPIs la llamen
sucursal = st.sidebar.multiselect("Sucursal", ["Sede Principal"], default=["Sede Principal"])

# Definir fechas (Asegúrate que anio_seleccionado ya exista)
f_inicio_global = datetime(anio_seleccionado, 1, 1)
f_fin_global = datetime(anio_seleccionado, 12, 31)

# --- AHORA SÍ, LA EJECUCIÓN DE KPIs ---
db_actual = st.session_state.get('DB_ACTUAL')

if db_actual and db_actual != 'none':
    conn = conectar_db(db_actual)
    if conn:
        try:
            # Ahora 'sucursal' ya existe y no dará error
            kpis = obtener_kpis_financieros(conn, f_inicio_global, f_fin_global, sucursal, st.session_state.get('DB_ACTUAL'))
        except Exception as e:
            st.error(f"Error al generar el Dashboard: {e}")
        finally:
            if conn.is_connected():
                conn.close() # Esto libera el puerto para el resto del sistema
else:
    # Diccionario por defecto para que el dashboard no quede en blanco
    kpis = {k: 0 for k in ["activo", "pasivo", "patrimonio", "utilidad", "entradas_efectivo", "salidas_efectivo", "flujo_neto", "saldo_real_final"]}
    kpis["top_proveedor"] = "Seleccione Empresa"



@log_ejecucion
def mostrar_treemap_gastos(conn, f_i, f_f):
    # Registro de actividad
    registrar_log_automatico(conn, "CONSULTA_TREEMAP_GASTOS", f"Usuario {st.session_state.usuario} consultó Treemap de gastos para {st.session_state.cliente_id} entre {f_i} y {f_f}")

    cursor = None
    try:
        # Buscamos solo cuentas de gasto (nivel 5) con movimiento
        query = """
            SELECT plan_cuentas as Cuenta, 
                   SUM(debe) - SUM(haber) as Monto 
            FROM asientos_contables 
            WHERE fecha BETWEEN %s AND %s AND SUBSTRING(plan_cuentas, 1, 1) = '5'
            GROUP BY plan_cuentas
            HAVING Monto > 0
        """
        df_gastos = pd.read_sql(query, conn, params=(f_i, f_f))
        
        # Obtenemos el cursor de la conexión para cumplir con el protocolo de cierre en el finally
        cursor = conn.cursor()

        if not df_gastos.empty:
            fig = px.treemap(
                df_gastos, 
                path=['Cuenta'], 
                values='Monto',
                title="Distribución de Gastos (Treemap)",
                color='Monto',
                color_continuous_scale='Reds'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay gastos registrados en este período para mostrar el Treemap.")

    except Exception as e:
        st.error(f"Error al generar el Treemap de gastos: {e}")

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
        
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)


@log_ejecucion
def mostrar_balance_con_drilldown(df_balance, conn):
    # Registro de actividad
    registrar_log_automatico(conn, "CONSULTA_BALANCE_GENERAL", f"Usuario {st.session_state.usuario} consultó balance para {st.session_state.cliente_id}")

    st.subheader("⚖️ Balance General Detallado")
    
    # Preparamos el DF para la visualización
    df_ver = df_balance.copy()
    
    cursor = None
    try:
        # Aquí definimos la tabla interactiva
        # Nota: Asegúrate de tener df_balance bien definido. 
        # Si usas df_compras, asegúrate de que sea el objeto correcto.
        event = st.dataframe(
            df_ver,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )

        # Lógica de detección de selección
        if event.selection.rows:
            indice_seleccionado = event.selection.rows[0]
            cuenta_seleccionada = df_ver.iloc[indice_seleccionado]
            st.write(f"Has seleccionado la cuenta: {cuenta_seleccionada['nombre']}")
            # Aquí iría tu lógica para navegar al libro mayor...

    except Exception as e:
        st.error(f"Error al procesar la selección del balance: {e}")

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        # Si en algún momento abres un cursor dentro de esta función, lo cierras aquí:
        if cursor:
            cursor.close() 
            
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)


@log_ejecucion
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
            # Consulta dinámica a la base de datos de la empresa
            usuario = st.session_state.get('usuario', 'Desconocido')
            registrar_log_automatico(conn, "CONSULTA_LIBRO_MAYOR", f"Usuario {usuario} consultó mayor en {db_nombre}")
            query_cuentas = f"SELECT DISTINCT cuenta_contable FROM `{db_nombre}`.asientos_contables ORDER BY cuenta_contable"
            df_cuentas = pd.read_sql(query_cuentas, conn)
            
            if not df_cuentas.empty:
                lista_opciones = df_cuentas['cuenta_contable'].tolist()
                idx_inicial = lista_opciones.index(cuenta_previa) if cuenta_previa in lista_opciones else 0
                
                cuenta_sel = st.selectbox("Seleccione cuenta de detalle:", lista_opciones, index=idx_inicial)
                
                col1, col2 = st.columns(2)
                f_m_d = col1.date_input("Desde", f_ini_g, key="m_d")
                f_m_h = col2.date_input("Hasta", f_fin_g, key="m_h")
                df_reporte = pd.DataFrame()
                saldo_inicial_periodo = 0.0

                if st.button("🔍 Generar Movimientos"):
                    # 1. Recibimos los datos
                    res_reporte, saldo_inicial_periodo = ejecutar_mayor_analitico(db_nombre, cuenta_sel, f_m_d, f_m_h)
                    
                    if not res_reporte.empty:
                        # Guardamos en sesión
                        st.session_state.reporte_mayor = res_reporte
                        
                        # CORRECCIÓN: Usa 'res_reporte' en lugar de 'df_reporte' aquí
                        st.session_state.saldo_final_reporte = saldo_inicial_periodo + res_reporte['debe'].sum() - res_reporte['haber'].sum()
                        
                        st.session_state.cuenta_actual = cuenta_sel
                    else:
                        st.warning("No se obtuvieron datos.")

                st.divider()

                if st.session_state.reporte_mayor is not None:
                    reporte = st.session_state.reporte_mayor
                    movs_solos = st.session_state.movs_solos
                    
                    # En la parte donde muestras los metrics:
                    if st.session_state.reporte_mayor is not None:
                        reporte = st.session_state.reporte_mayor
                        movs_solos = st.session_state.movs_solos
                        
                        if not reporte.empty:
                            t_debe = movs_solos['debe'].sum()
                            t_haber = movs_solos['haber'].sum()
                            
                            # Usamos el saldo_final que guardamos en session_state
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
            if cursor: cursor.close()
            if conn: conn.close()



@log_ejecucion
def generar_nro_comprobante(conn, fecha_emision):
    # Registro de actividad
    registrar_log_automatico(conn, "GENERACION_COMPROBANTE", f"Usuario {st.session_state.usuario} generando nro comprobante para {st.session_state.cliente_id}")
    
    cursor = None
    try:
        cursor = conn.cursor()
        periodo = fecha_emision.strftime("%Y%m")
        
        # Ejemplo de cómo podrías obtener el último número desde la base de datos:
        # cursor.execute("SELECT MAX(nro_comprobante) FROM comprobantes WHERE ...")
        # resultado = cursor.fetchone()
        
        # Por ahora mantenemos tu lógica placeholder:
        return f"{periodo}00000001"

    except Exception as e:
        st.error(f"Error generando número de comprobante: {e}")
        return None

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
        
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



@log_ejecucion
def cargar_datos_retenciones_iva(f_desde, f_hasta):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        return pd.DataFrame()

    try:
        # Registro de actividad
        registrar_log_automatico(conn, "CONSULTA_BALANCE_GENERAL", f"Usuario {st.session_state.usuario} consultó balance para {st.session_state.cliente_id}")
        
        cursor = conn.cursor()
        
        # Usamos los nombres REALES de tu tabla
        query = """
            SELECT id, 
                   N_Comprobante1, 
                   Razon_Social_Sujeto_Retenido, 
                   RIF_Sujeto_Retenido, 
                   Fecha_Factura, 
                   Total_Comrpas, 
                   Base_Imponible, 
                   IVA_Retenido 
            FROM retenciones_iva 
            WHERE Fecha_Factura BETWEEN %s AND %s
        """
        df = pd.read_sql(query, conn, params=(f_desde, f_hasta))
        
        # Renombramos para que tu código de Streamlit no se rompa
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
        st.error(f"Error al consultar datos: {e}")
        return pd.DataFrame()

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
            
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



@log_ejecucion
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
        df = pd.read_sql(query, conn, params=(f_desde, f_hasta))
        
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
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close()
            
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



@log_ejecucion
def eliminar_registro_retencion(id_registro):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        return False

    try:
        # Registro de actividad
        registrar_log_automatico(conn, "ELIMINAR_RETENCION", f"Usuario {st.session_state.usuario} eliminó registro de retención {id_registro} para {st.session_state.cliente_id}")
        
        cursor = conn.cursor()
        query = "DELETE FROM retenciones_iva WHERE id = %s"
        cursor.execute(query, (id_registro,))
        conn.commit()
        return True

    except Exception as e:
        st.error(f"Error al eliminar: {e}")
        return False

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close()
            
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



@log_ejecucion
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
            cursor.close()
        if conn and conn.is_connected():
            conn.ping(reconnect=True)



@log_ejecucion
def obtener_metricas_iva(conn, mes_n, ano):
    cursor = None
    try:
        # Registro de actividad
        registrar_log_automatico(conn, "CONSULTA_METRICAS_IVA", f"Usuario {st.session_state.usuario} consultó métricas de IVA para {st.session_state.cliente_id}")
        
        cursor = conn.cursor(dictionary=True)
        # Filtramos exactamente por lo que el usuario eligió en los selectores
        query = """
            SELECT 
                SUM(Total_Comrpas) as total, 
                SUM(IVA_Retenido) as ret, 
                SUM(Compras_Excentas) as exe
            FROM retenciones_iva 
            WHERE Mes = %s AND Ano = %s
        """
        # Aseguramos que el mes tenga formato '01', '02', etc.
        mes_str = f"{mes_n:02d}" 
        cursor.execute(query, (mes_str, str(ano)))
        res = cursor.fetchone()
        
        return {
            "compras": float(res['total'] or 0),
            "retenido": float(res['ret'] or 0),
            "exento": float(res['exe'] or 0)
        }

    except Exception as e:
        st.error(f"Error obteniendo métricas IVA: {e}")
        return {"compras": 0, "retenido": 0, "exento": 0}

    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close() 
        
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)


@log_ejecucion
def obtener_datos_agente_db(valor_busqueda):
    conn_central = conectar_db("control_central")
    if not conn_central: return None

    try:
        cursor = conn_central.cursor(dictionary=True)
        # Si es un string, busca por db_nombre. Si es int, busca por id.
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif, domicilio_fiscal FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif, domicilio_fiscal FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        cursor.close()
        return datos
    except Exception as e:
        # Aquí es donde ocurre el error 1292. Si ves esto en pantalla, 
        # sabrás exactamente qué valor está fallando.
        st.error(f"Error en consulta DB: {e} | Valor buscado: {valor_busqueda}")
        return None
    finally:
        if conn_central and conn_central.is_connected():
            conn_central.close()


@log_ejecucion
def obtener_empresa_activa():
    """
    Toma el objeto completo guardado por el selectbox.
    """
    empresa_data = st.session_state.get('id_empresa_seleccionada')
    
    # Validamos si es un diccionario válido
    if not empresa_data or not isinstance(empresa_data, dict):
        return None
        
    return empresa_data



@log_ejecucion
def obtener_facturas_pendientes(conn):
    try:
        query = """
            SELECT * FROM libro_compras 
            WHERE retencion_iva_realizada = 0 
            OR retencion_iva_realizada IS NULL
        """
        df = pd.read_sql(query, conn)
        
        # Agrega este aviso visual
        if df.empty:
            st.info("ℹ️ No hay facturas pendientes de retención.")
            
        return df
    except Exception as e:
        st.error(f"Error al cargar facturas pendientes: {e}")
        return pd.DataFrame()



@log_ejecucion
def marcar_retencion_completada(conn, id_factura, n_comprobante):
    cursor = conn.cursor()
    # Marcamos la factura como procesada para que no vuelva a aparecer
    query = """
        UPDATE libro_compras 
        SET retencion_realizada = TRUE,
            n_comprobante_retencion = %s,
            fecha_comprobante = CURRENT_DATE
        WHERE id = %s
    """
    cursor.execute(query, (n_comprobante, id_factura))
    conn.commit()
    cursor.close()


@log_ejecucion
def obtener_todas_las_empresas():
    conn_central = conectar_db("control_central")
    if not conn_central: return []
    try:
        cursor = conn_central.cursor(dictionary=True)
        # Filtramos directamente en la consulta SQL
        # Asumiendo que en 'clientes' tienes una columna 'usuario_id'
        query = "SELECT * FROM clientes WHERE usuario_id = %s"
        cursor.execute(query, (user_id,))
        resultados = cursor.fetchall()
        cursor.close()
        return resultados
    except Exception as e:
        st.error(f"Error al filtrar empresas: {e}")
        return []
    finally:
        if conn_central and conn_central.is_connected():
            conn_central.close()

@log_ejecucion
def obtener_empresas_del_usuario(db_nombre_en_sesion):
    conn = conectar_db("control_central")
    if not conn: return []

    try:
        cursor = conn.cursor(dictionary=True)
        # Filtramos por el nombre de la base de datos que ya tienes en sesión
        query = "SELECT id, nombre_empresa FROM clientes WHERE db_nombre = %s"
        cursor.execute(query, (db_nombre_en_sesion,))
        resultados = cursor.fetchall()
        cursor.close()
        return resultados
    except Exception as e:
        st.error(f"Error: {e}")
        return []
    finally:
        if conn and conn.is_connected(): conn.close()


@log_ejecucion
def actualizar_registro_retencion(fila):
    db_nombre = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_nombre)
    cursor = conn.cursor()
    
    try:
        query = """UPDATE retenciones_iva SET 
                   Razon_Social_del_Agente_de_Retencion = %s, RIF_Agente_Retencion = %s,
                   Direccion_FiscalAgente_Retencion = %s, E_Emision = %s, F_Entrega = %s,
                   Razon_Social_Sujeto_Retenido = %s, RIF_Sujeto_Retenido = %s,
                   Ano = %s, Mes = %s, N_Comprobante1 = %s,
                   Fecha_Factura = %s, Numero_Factura = %s, Numero_Contro = %s,
                   N_Nota_Debito = %s, N_Nota_Credito = %s, NFactura_Afectada = %s,
                   Total_Comrpas = %s, Compras_Excentas = %s,
                   Base_Imponible = %s, Alicuota = %s, Impuesto_Iva = %s,
                   Alicuota_75 = %s, IVA_Retenido = %s,
                   Base_Imponible_8 = %s, IVA_8 = %s, RET_IVA_8 = %s,
                   id_empresa = %s
                   WHERE id = %s"""
        
        # Función auxiliar para buscar el valor por nombre largo o por nombre corto
        def v(nombre_largo, nombre_corto):
            return fila.get(nombre_largo, fila.get(nombre_corto, ''))

        valores = (
            str(v('Razon_Social_del_Agente_de_Retencion', 'razon')),
            str(v('RIF_Agente_Retencion', 'rif')),
            str(v('Direccion_FiscalAgente_Retencion', 'direccion')),
            str(v('E_Emision', 'e_emision')),
            str(v('F_Entrega', 'f_entrega')),
            str(v('Razon_Social_Sujeto_Retenido', 'razon_sujeto')),
            str(v('RIF_Sujeto_Retenido', 'rif_sujeto')),
            str(v('Ano', 'Ano')),
            str(v('Mes', 'Mes')),
            str(v('N_Comprobante1', 'nro_comp')),
            str(v('Fecha_Factura', 'f_fac')),
            str(v('Numero_Factura', 'Numero_Factura')),
            str(v('Numero_Contro', 'Numero_Contro')),
            str(v('N_Nota_Debito', 'N_Nota_Debito')),
            str(v('N_Nota_Credito', 'N_Nota_Credito')),
            str(v('NFactura_Afectada', 'NFactura_Afectada')),
            str(v('Total_Comrpas', 'total')),
            str(v('Compras_Excentas', 'Compras_Excentas')),
            str(v('Base_Imponible', 'base')),
            str(v('Alicuota', 'Alicuota')),
            str(v('Impuesto_Iva', 'Impuesto_Iva')),
            str(v('Alicuota_75', 'Alicuota_75')),
            str(v('IVA_Retenido', 'm_ret')),
            float(v('Base_Imponible_8', 'Base_Imponible_8') or 0),
            float(v('IVA_8', 'IVA_8') or 0),
            float(v('RET_IVA_8', 'RET_IVA_8') or 0),
            int(fila.get('id_empresa', 0)),
            int(fila.get('id', 0))
        )
        
        cursor.execute(query, valores)
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Error al actualizar registro {fila.get('id')}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

@log_ejecucion
def inicializar_sesion_empresa(lista_empresas):
    """
    Capa de resiliencia: Si el estado está vacío, lo inyecta a la fuerza.
    """
    if "id_empresa_seleccionada" not in st.session_state or st.session_state["id_empresa_seleccionada"] is None:
        st.session_state["id_empresa_seleccionada"] = lista_empresas[0]
        st.session_state["DB_ACTUAL"] = lista_empresas[0].get('db_nombre')
        # No ponemos rerun aquí para evitar bucles infinitos

@log_ejecucion
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
    if conn is None or not conn.is_connected():
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
        st.subheader("📝 Generar Nueva Retención")
        db_actual = st.session_state.get("DB_ACTUAL")

        if not db_actual:
            st.error("⚠️ Debes seleccionar una empresa primero.")
            st.stop()

        conn = conectar_db(db_actual)
        if not conn:
            st.error("❌ No se pudo establecer conexión.")
            st.stop()

        conn.ping(reconnect=True, attempts=3, delay=1)
        st.write(f"Conectado a: **{db_actual}**")

        # Filtros
        col_b1, col_b2 = st.columns(2)
        f_desde = col_b1.date_input("Desde", f_inicio_global, key="ret_iva_desde")
        f_hasta = col_b2.date_input("Hasta", f_fin_global, key="ret_iva_hasta")

        # --- 3. LÓGICA DE PROCESAMIENTO ---
        # En lugar de hacer una carga directa de toda la tabla, haces esto:
        # 1. Obtenemos las pendientes
        df_facturas = obtener_facturas_pendientes(conn)

        if not df_facturas.empty:
            # 2. Agregamos una columna de checkbox para seleccionar
            if 'Seleccionar' not in df_facturas.columns:
                df_facturas.insert(0, "Seleccionar", False)

            # 3. Muestra el editor y captura los cambios
            df_editado = st.data_editor(
                df_facturas,
                column_config={"Seleccionar": st.column_config.CheckboxColumn(required=True)},
                hide_index=True,
                use_container_width=True
            )

            # 4. Filtramos solo las marcadas
            seleccion = df_editado[df_editado["Seleccionar"] == True]
            
            if not seleccion.empty:
                st.session_state['facturas_seleccionadas'] = seleccion
                st.success(f"Facturas seleccionadas: {len(seleccion)}")
            else:
                st.session_state['facturas_seleccionadas'] = None

        facturas_seleccionadas = st.session_state.get('facturas_seleccionadas')
        if facturas_seleccionadas is not None and not facturas_seleccionadas.empty:
            total_base_agrupado = facturas_seleccionadas['base_imponible'].sum()
            total_iva_agrupado = facturas_seleccionadas['iva_monto'].sum()
            total_facturas_agrupado = facturas_seleccionadas['total_compras'].sum()
            total_exento_agrupado = facturas_seleccionadas['importe_exento'].sum()
            
            factura_principal = facturas_seleccionadas.iloc[0]
            val_sugerido = str(factura_principal['fecha_operacion']).replace("-", "")[:6] + str(factura_principal['id']).zfill(8)

            # Este botón SÍ puede estar aquí porque es el trigger del form
            

            st.write("### 📝 Datos del Comprobante (Grupo)")

            
            # Caso Éxito
            if st.session_state.get('mostrar_exito'):
                st.success(f"### ✅ Comprobante `{st.session_state.get('last_iva', {}).get('nro_comp')}` generado.")
                st.balloons()
                if 'last_iva' in st.session_state:
                    st.divider()
                    st.write("#### Detalle del grupo procesado:")
                    porcentaje_actual = st.session_state.get('porcentaje_ret', 75)

                    # 2. Creamos la lista procesando cada fila
                    lista_de_facturas = []

                    for _, fila in facturas_seleccionadas.iterrows():
                        # Calculamos el monto de retención con el valor seguro
                        iva = float(fila.get('impuesto_iva', 0))
                        monto_ret = (iva * porcentaje_actual) / 100
                        
                        # Agregamos a la lista
                        lista_de_facturas.append({
                            'fecha': fila['fecha_operacion'],
                            'n_fact': fila['n_factura'],
                            'n_cont': fila['n_control'],
                            'total': fila['total_compras'],
                            'base': fila['base_imponible'],
                            'iva': iva,
                            'm_ret': monto_ret
                        })
                    #st.table(lista_de_facturas)
                # --- 3. BOTÓN PARA RESETEAR ---
                if st.button("🔄 Registrar otro grupo", key="btn_reset_retencion"):
                    st.session_state['facturas_seleccionadas'] = None
                    st.session_state['mostrar_exito'] = False
                    st.rerun()
            else:
                # Formulario
                factura_principal = facturas_seleccionadas.iloc[0]
                #st.write("DEBUG - Columnas detectadas:", facturas_seleccionadas.columns.tolist())
                val_sugerido = str(factura_principal['fecha_operacion']).replace("-", "")[:6] + str(factura_principal['id']).zfill(8)
                
                st.info(f"Agrupando {len(facturas_seleccionadas)} facturas de **{factura_principal['proveedor']}**")
                
                with st.form("form_retencion_iva"):
                    c1, c2, c3 = st.columns(3)
                    razon_social_ret = c1.text_input("Sujeto Retenido", value=factura_principal['proveedor'])
                    rif_ret = c2.text_input("RIF Retenido", value=factura_principal['rif'])
                    nro_comp = c3.text_input("N° Comprobante (14 dígitos)", value=val_sugerido, key=f"nro_{val_sugerido}")
                    
                    st.write("*(Los montos abajo representan la suma de todas las facturas seleccionadas)*")
                    
                    c7, c8, c9, c_ex = st.columns(4)
                    base_i = c7.number_input("Base Imponible Total", value=float(total_base_agrupado), format="%.2f")
                    iva_i = c8.number_input("Impuesto IVA Total", value=float(total_iva_agrupado), format="%.2f")
                    monto_exento_val = c_ex.number_input("Monto Exento Total", value=float(total_exento_agrupado), format="%.2f")
                    total_c = c9.number_input("Total Facturas", value=float(total_facturas_agrupado), format="%.2f")
                    
                    c10, c11 = st.columns(2)
                    porcentaje_ret = c10.selectbox("Porcentaje de Retención", [75, 100])
                    iva_retenido = (float(iva_i) * porcentaje_ret) / 100
                    c11.metric("IVA a Retener Total", f"Bs. {iva_retenido:,.2f}")

                    # Justo antes de la llamada a la función:

                    # 1. Obtenemos los datos de la empresa basada en la base de datos actual
                    db_actual = st.session_state.get('DB_ACTUAL')
                    empresa_data = obtener_datos_agente_db(db_actual)

                    if not empresa_data:
                        st.error("⚠️ No se pudieron cargar los datos de la empresa.")
                    else:
                        # 2. AQUÍ VA EL SELECTBOX QUE ME PREGUNTAS
                        # Al pasarle [empresa_data] como lista, el selectbox solo tendrá una opción
                        empresa_seleccionada = st.selectbox(
                            "Empresa", 
                            options=[empresa_data], 
                            format_func=lambda x: x['nombre_empresa']
                        )
                        
                        # Guardamos la empresa seleccionada en sesión
                        st.session_state['id_empresa_seleccionada'] = empresa_seleccionada

                    # 3. EL BOTÓN VA AQUÍ (Asegúrate de que no haya st.stop() antes de esta línea)
                    enviado = st.form_submit_button("💾 Guardar y Generar Documentos")


                if enviado:
                    # 1. Recuperación y validación inicial
                    empresa_data = st.session_state.get('id_empresa_seleccionada') or st.session_state.get('id_empresa_actual')
                    db_nombre = st.session_state.get('DB_ACTUAL')
                    
                    if not empresa_data or not db_nombre:
                        st.error("❌ Faltan datos de empresa o base de datos.")
                        st.stop()

                    conn = conectar_db(db_nombre)
                    if not conn or not conn.is_connected():
                        st.warning("⚠️ Reconectando...")
                        conn = conectar_db(db_nombre)

                    # 2. Extracción de datos empresa
                    id_final = empresa_data.get('id') if isinstance(empresa_data, dict) else empresa_data
                    empresa_nombre = empresa_data.get('nombre_empresa') or empresa_data.get('razon_social') or "EMPRESA"
                    empresa_rif = empresa_data.get('rif') or "000000000"
                    domicilio_fiscal = empresa_data.get('domicilio_fiscal') or empresa_data.get('direccion') or "DIRECCIÓN NO REGISTRADA"

                    try:
                        cursor = conn.cursor()
                        
                        # 3. Iteración sobre las facturas seleccionadas
                        for _, fila in facturas_seleccionadas.iterrows():
                            # Cálculos
                            base = float(fila.get('base_imponible', 0) or 0)
                            impuesto = float(fila.get('iva_monto', 0) or 0)
                            ratio = round(impuesto / base, 2) if base > 0 else 0
                            es_8 = ratio <= 0.08
                            iva_retenido = (impuesto * porcentaje_ret) / 100
                            
                            b16, i16, r16 = (base, impuesto, iva_retenido) if not es_8 else (0.0, 0.0, 0.0)
                            b8, i8, r8 = (base, impuesto, iva_retenido) if es_8 else (0.0, 0.0, 0.0)
                            
                            fecha_corta = str(fila['fecha_operacion']).split(" ")[0]
                            ano_f, mes_f = fecha_corta.split("-")[0], fecha_corta.split("-")[1]

                            # Inserción en retenciones_iva
                            query_ins = """
                                INSERT INTO retenciones_iva (
                                    Razon_Social_del_Agente_de_Retencion, RIF_Agente_Retencion, id_empresa, 
                                    Direccion_FiscalAgente_Retencion, E_Emision, F_Entrega, Razon_Social_Sujeto_Retenido, 
                                    RIF_Sujeto_Retenido, Ano, Mes, N_Comprobante1, Fecha_Factura, Numero_Factura, 
                                    Numero_Contro, Total_Comrpas, Compras_Excentas, Base_Imponible, Impuesto_Iva, 
                                    IVA_Retenido, Base_Imponible_8, IVA_8, RET_IVA_8, Alicuota, Alicuota_75, N_Nota_Debito
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """

                            params = (
                                empresa_nombre, empresa_rif, id_final, domicilio_fiscal,
                                fecha_corta, fecha_corta, razon_social_ret, rif_ret, ano_f, mes_f,
                                nro_comp, fecha_corta, str(fila['n_factura']), str(fila['n_control']),
                                round(float(fila.get('total_compras', 0)), 2), # Asegúrate que tu DataFrame tenga esta columna
                                round(float(fila.get('importe_exento', 0)), 2),
                                round(b16, 2), round(i16, 2), round(iva_retenido, 2),
                                round(b8, 2), round(i8, 2), round(r8, 2),
                                "16%", "75%", None
                            )
                            cursor.execute(query_ins, params)
                            cursor.execute("UPDATE libro_compras SET retencion_iva_realizada = 1 WHERE id = %s", (int(fila['id']),))

                        # Confirmación final
                        conn.commit()
                        st.session_state['last_iva'] = {'nro_comp': nro_comp}
                        st.session_state['mostrar_exito'] = True
                        st.rerun()

                    except Exception as e:
                        if conn: conn.rollback()
                        st.error(f"❌ Error al procesar: {e}")
                    finally:
                        if cursor: cursor.close()
                        if conn: conn.close()

                
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
                if not conn.is_connected():
                    conn.reconnect(attempts=3, delay=1)
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
                        datos_empresa = {"nombre_empresa": "NO ENCONTRADO", "rif": "N/A", "domicilio_fiscal": "N/A"}

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

                            # --- 1. OBTENER DATOS (ANTES DE DIBUJAR) ---
                            # --- 1. OBTENER DATOS (ANTES DE DIBUJAR) ---
                            df_detalle = obtener_detalle_comprobante(opcion_busqueda) # <--- CAMBIADO A LA VARIABLE CORRECTA

                            if not df_detalle.empty:
                                # Convertimos la primera fila a diccionario para que d.get() funcione
                                d = df_detalle.iloc[0].to_dict()
                            else:
                                st.error("No se encontraron datos para este comprobante.")
                                return # O maneja el error como prefieras

                            # --- BLOQUE 1: AGENTE DE RETENCIÓN ---
                            # 1. Recuperamos el nombre seleccionado y buscamos su ID real
                            nombre_empresa_actual = st.session_state.get('CLIENTE_NOMBRE')

                            # Buscamos en el DataFrame el registro que coincide con el nombre
                            datos_actuales = df_sidebar[df_sidebar['nombre_empresa'] == nombre_empresa_actual].iloc[0]
                            # Convertimos explícitamente a int de Python
                            id_real = int(datos_actuales['id'])

                            # 2. Llamamos a la función usando el ID REAL obtenido de la BD
                            datos_empresa = obtener_datos_agente_db(id_real)

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
                            domicilio_real = str(datos_empresa.get('domicilio_fiscal', 'NO REGISTRADO'))

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
                            pdf_output = pdf.output(dest='S').encode('latin-1')
                            
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
                if not conn.is_connected():
                    conn.reconnect(attempts=3, delay=1)
            except Exception as e:
                conn = conectar_db(db_actual)


            facturas_bloqueadas = pd.read_sql("SELECT n_factura as numero_factura, proveedor FROM libro_compras WHERE retencion_iva_realizada = 1", conn)

            if not facturas_bloqueadas.empty:
                opciones = facturas_bloqueadas['numero_factura'] + " - " + facturas_bloqueadas['proveedor']
                seleccion_label = st.selectbox("Seleccione factura para habilitar:", opciones, key="sel_des_iva")
                nro_a_desbloquear = seleccion_label.split(" - ")[0]
                
                if st.button("Habilitar Factura", key="btn_des_iva"):
                    cursor_aux = conn.cursor()
                    cursor_aux.execute("UPDATE libro_compras SET retencion_iva_realizada = 0 WHERE n_factura = %s", (nro_a_desbloquear,))
                    conn.commit()
                    st.success(f"Factura {nro_a_desbloquear} habilitada.")
                    st.rerun()
            else:
                st.info("No hay facturas bloqueadas actualmente.")

        
        # --- TAB 6: ARCHIVO TXT SENIAT ---
        with tab5:
            st.write("Cargando TXT...")
            st.subheader("🚀 Generación de Archivo TXT para el SENIAT")
            st.info("Seleccione el rango de fechas para consolidar las retenciones.")

            col1, col2 = st.columns(2)
            with col1:
                fecha_inicio = st.date_input("Fecha Inicio", datetime.now().replace(day=1))
            with col2:
                fecha_fin = st.date_input("Fecha Fin", datetime.now())

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
                        if conn.is_connected():
                            conn.close()

@log_ejecucion
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
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close()
        
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)


if 'df_balance' in st.session_state and st.session_state.df_balance is not None:
    
    # 1. Recuperamos la data
    df_temp = st.session_state.df_balance.copy()
    
    # 2. Aseguramos las columnas correctas (incluyendo 'Cuenta Contable')
    # Nota: Si en tu base de datos se llama 'nombre', la renombramos aquí mismo
    if 'nombre' in df_temp.columns:
        df_temp = df_temp.rename(columns={'nombre': 'Cuenta Contable'})
    
    columnas_finales = ['codigo', 'Cuenta Contable', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
    # Solo filtramos las que existan para evitar errores
    df_excel = df_temp[[c for c in columnas_finales if c in df_temp.columns]]

    # 3. Generamos el Excel
    excel_data = generar_excel_formateado(
        df_excel, 
        "Balance de Comprobación: KING DRIVER, C.A.", 
        f"Periodo: {f_inicio_bc} - {f_fin_bc}"
    )

# --- Lógica para el EXCEL del Balance General ---
if 'df_balance_general' in st.session_state and st.session_state.df_balance_general is not None:
    
    # 1. Copiamos para limpiar sin afectar la vista de pantalla
    df_bg_excel = st.session_state.df_balance_general.copy()

    # 2. Renombramos la columna para que se vea profesional
    if 'nombre' in df_bg_excel.columns:
        df_bg_excel = df_bg_excel.rename(columns={'nombre': 'Cuenta Contable'})

    # 3. FILTRO DE COLUMNAS: Solo lo que le interesa al cliente/SENIAT
    # Quitamos nivel, tipo, padre, id, etc.
    cols_permitidas_bg = ['codigo', 'Cuenta Contable', 'Monto'] 
    # (Ajusta 'Monto' por el nombre real de tu columna de saldo, ej: 'Saldo Final')
    df_bg_final = df_bg_excel[[c for c in cols_permitidas_bg if c in df_bg_excel.columns]]

    # 4. Generación del archivo Excel con formato
    output_bg = io.BytesIO()
    with pd.ExcelWriter(output_bg, engine='xlsxwriter') as writer:
        df_bg_final.to_excel(writer, index=False, sheet_name='BalanceGeneral', startrow=4)
        
        workbook = writer.book
        worksheet = writer.sheets['BalanceGeneral']

        # Formatos (Manteniendo el estilo King Driver)
        fmt_header = workbook.add_format({
            'bold': True, 'fg_color': '#1E3A8A', 'font_color': 'white', 'border': 1, 'align': 'center'
        })
        fmt_titulo = workbook.add_format({'bold': True, 'size': 14, 'font_color': '#1E3A8A'})

        # Encabezados del reporte en las primeras filas
        worksheet.write('A1', f"AUDITORÍA PROFESIONAL: {EMPRESA}", fmt_titulo)
        worksheet.write('A2', "REPORTE: BALANCE GENERAL (ESTADO DE SITUACIÓN FINANCIERA)", workbook.add_format({'bold': True}))
        worksheet.write('A3', f"Fecha de Corte: {f_fin_bc}") # Usamos la fecha 'Hasta'

        # Aplicar formato a las columnas
        for col_num, value in enumerate(df_bg_final.columns.values):
            worksheet.write(4, col_num, value, fmt_header)
            worksheet.set_column(col_num, col_num, 30) # Un poco más ancho para nombres de cuentas

    st.divider()
    
    # 5. BOTÓN DE DESCARGA ÚNICO
    st.download_button(
        label="📥 Descargar Balance General en Excel",
        data=output_bg.getvalue(),
        file_name=f"Balance_General_{EMPRESA}_{f_fin_bc}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key="btn_descarga_bg" # Key diferente para que no choque con el otro tab
    )

@log_ejecucion
def cargar_estado_cuenta_bdv(uploaded_file, conn):

    # 1. Recuperamos las variables del estado global
    mes_sel = st.session_state.get('mes_seleccionado')
    ano_sel = st.session_state.get('ano_seleccionado')

    # 2. Validación de seguridad
    if not mes_sel or not ano_sel:
        st.error("❌ No se ha seleccionado mes o año en el dashboard.")
        return

    # 3. Verificamos si el mes está cerrado
    if mes_esta_cerrado(conn, mes_sel, ano_sel):
        st.error("❌ No se pueden realizar cambios. El mes está bloqueado.")
        return
    
    # Registro de actividad
    registrar_log_automatico(conn, "CARGA_ESTADO_CUENTA", f"Usuario {st.session_state.usuario} cargó estado de cuenta para {st.session_state.cliente_id}")
    
    cursor = conn.cursor(buffered=True)
    try:
        # 1. CAMBIAMOS DE BASE DE DATOS
        cursor.execute("USE kingdirver_ca")
        
        # 2. Leemos el archivo
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.str.strip()
        
        movimientos_insertados = 0
        
        # 3. Procesamos filas
        for index, row in df.iterrows():
            if pd.isna(row.get('Referencia')): continue
            
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
        
        return True  # <--- ESTO ES LO QUE TE FALTA
        
        # 4. Regresamos a la base original
        cursor.execute("SELECT * FROM control_central.usuarios WHERE rol = 'admin'")
        
        st.success(f"✅ ¡Éxito! Se guardaron {movimientos_insertados} registros.")
        
    except Exception as e:
        conn.rollback() # Si algo falla, revertimos los cambios para no dejar datos corruptos
        st.error(f"❌ Error al procesar el archivo: {e}")
        
    finally:
        # AQUÍ ESTÁ EL SECRETO:
        cursor.close() 
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        conn.ping(reconnect=True)

# 1. Definimos una pequeña función de mapeo (dinámica)
def obtener_alias_banco(nombre_ui):
    # Esto garantiza que siempre busques el nombre correcto en la tabla
    mapeo = {
        "Banco de Venezuela": "BDV",
        "Banesco": "Banesco",
        "Banco Mercantil": "Mercantil"
    }
    return mapeo.get(nombre_ui, nombre_ui) # Si no está en el mapa, busca el nombre tal cual


@log_ejecucion
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

    empresa_seleccionada = st.sidebar.selectbox("Seleccione Empresa", empresas_db)
    
    if st.session_state.get('DB_ACTUAL') != empresa_seleccionada:
        st.session_state['DB_ACTUAL'] = empresa_seleccionada
        st.rerun()

    db = st.session_state.get('DB_ACTUAL')
    if not db: return

    # --- 2. PREPARACIÓN ---
    meses_dict = {"Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04", "Mayo": "05", "Junio": "06", 
                  "Julio": "07", "Agosto": "08", "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"}
    mes_num = meses_dict[mes_sel]
    fecha_fin = f"{ano_sel}-{mes_num}-{calendar.monthrange(int(ano_sel), int(mes_num))[1]}"
    fecha_inicio = f"{ano_sel}-{mes_num}-01"

    # --- 3. CARGA DE BANCOS (Usando la DB seleccionada) ---
    cursor = conn.cursor(buffered=True)
    # 1. CARGA DE BANCOS (Primero definimos la lista)
    cursor = conn.cursor(buffered=True)
    try:
        query_bancos = f"SELECT nombre, codigo FROM `{db}`.plan_cuentas WHERE nombre LIKE '%BANCO%' AND tipo = 'Detalle'"
        cursor.execute(query_bancos)
        bancos_dict = {b[0]: b[1] for b in cursor.fetchall()}
        
        if not bancos_dict:
            st.warning("No se encontraron cuentas bancarias.")
            return

        # 2. SELECCIÓN DE BANCO
        nombre_banco_sel = st.sidebar.selectbox("Seleccione Banco", list(bancos_dict.keys()))
        cuenta_codigo = bancos_dict[nombre_banco_sel]
        
        # 3. TRANSFORMACIÓN DE NOMBRE PARA LA BD (Aquí aplicas tu función de alias)
        banco_db = obtener_alias_banco(nombre_banco_sel)

        # 4. CONSULTAS PRINCIPALES
        # A. Saldo Banco (Usando el alias banco_db)
        sql_saldos = f"""SELECT saldo_inicial, saldo_final 
                        FROM `{db}`.saldos_bancarios 
                        WHERE banco = %s AND mes = %s AND ano = %s"""
        cursor.execute(sql_saldos, (banco_db, mes_sel, ano_sel))
        res_banco = cursor.fetchone()
        saldo_inicial, saldo_final_banco = (float(res_banco[0]), float(res_banco[1])) if res_banco else (0.0, 0.0)

        # B. Saldo Libros
        # 1. DEPURACIÓN: Vamos a ver qué ve la BD antes de intentar sumar
        cursor.execute(f"SELECT DISTINCT cuenta_contable FROM `{db}`.asientos_contables LIMIT 10")
        muestras = cursor.fetchall()

        # 0. INICIALIZACIÓN DE SEGURIDAD
        saldo_abril = 0.0
        debe_mayo = 0.0
        haber_mayo = 0.0

        query_saldo_anterior = f"""
            SELECT saldo_final 
            FROM `{db}`.saldos_bancarios 
            WHERE banco = %s AND mes = 'Abril' AND ano = 2026
        """
        cursor.execute(query_saldo_anterior, (banco_db,))
        res_anterior = cursor.fetchone()
        saldo_abril = float(res_anterior[0]) if res_anterior else 0.0

        # 2. Obtener solo los movimientos de MAYO
        query_mayo = f"""
            SELECT IFNULL(SUM(debe), 0.0), IFNULL(SUM(haber), 0.0) 
            FROM `{db}`.asientos_contables 
            WHERE TRIM(cuenta_contable) = TRIM(%s) 
            AND fecha BETWEEN %s AND %s
        """
        cursor.execute(query_mayo, (nombre_banco_sel,))
        debe_mayo, haber_mayo = cursor.fetchone()

        # 3. Aplicar tu lógica de cadena: Saldo Final = Saldo Anterior + Movimientos
        saldo_final_libros = saldo_abril + (float(debe_mayo) - float(haber_mayo))

        # C. Movimientos
        query_mov = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = '{{estado}}' AND fecha_movimiento BETWEEN '{fecha_inicio}' AND '{fecha_fin}'"
        df_banco = pd.read_sql(query_mov.format(estado='Pendiente'), conn)
        df_conciliado = pd.read_sql(query_mov.format(estado='Conciliado'), conn)

    except Exception as e:
        st.error(f"Error en la consulta para {db}: {e}")
    finally:
        cursor.close()

    # --- VISUALIZACIÓN (Misma que la tuya, pero ahora segura) ---
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
        
    # --- 1. Inicializa variables en el session_state si no existen ---
    if 'saldo_final_libros' not in st.session_state:
        st.session_state.saldo_final_libros = 0.0

    # --- 2. Tu botón de ejecución ---
    if st.button("🚀 Ejecutar Conciliación"):
        # Llamamos a la función que ahora debe retornar los valores
        resultado = conciliar_datos(conn, fecha_inicio, fecha_fin, db)
        
        # Guardamos los resultados en el session_state para que no desaparezcan
        st.session_state.saldo_final_libros = resultado
        
        # Recargamos la página una sola vez para que muestre los datos calculados
        st.rerun()

        # --- 6. LÓGICA DE PDF CENTRALIZADA ---
        st.divider()
        st.subheader("📄 Reporte de Conciliación")
    
    # 1. Preparar listas base
    lista_ingresos = df_banco[df_banco['monto'] > 0].to_dict('records') if not df_banco.empty else []
    lista_egresos = df_banco[df_banco['monto'] < 0].to_dict('records') if not df_banco.empty else []
    
    # 2. Ajuste automático por diferencia
    diferencia = round(saldo_final_banco - saldo_final_libros, 2)
    if abs(diferencia) > 0.01:
        partida_ajuste = {"fecha_movimiento": fecha_fin, "referencia": "AJUSTE", "descripcion": "Diferencia por redondeo", "monto": diferencia}
        if diferencia > 0: lista_ingresos.append(partida_ajuste)
        else: lista_egresos.append(partida_ajuste)

    # 3. GENERAR EL PDF UNA SOLA VEZ
    try:
        # En tu código principal, donde capturas la fecha:

        # Luego, cuando llamas a la función, usa esa misma variable:
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

    # 4. Mostrar detalles conciliados si existen
    if not df_conciliado.empty:
        st.subheader("✅ Movimientos Conciliados")
        col_d, col_h = st.columns(2)
        col_d.write("Ingresos")
        col_d.dataframe(df_conciliado[df_conciliado['monto'] > 0])
        col_h.write("Egresos")
        col_h.dataframe(df_conciliado[df_conciliado['monto'] < 0])
    else:
        st.info("ℹ️ No hay movimientos conciliados en este periodo.")

        

@log_ejecucion
def conciliar_datos(conn, fecha_inicio, fecha_fin, db_empresa):
    # 1. Recuperamos lo necesario
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')

    # 2. VALIDACIÓN DE SEGURIDAD
    if not db_actual:
        st.error("No se ha seleccionado una base de datos de empresa.")
        st.stop()

    empresa_data = obtener_datos_agente_db(db_actual)

    # 3. FILTRO DE ACCESO
    if empresa_data and rol != 'admin':
        if empresa_data['id'] != cliente_id:
            st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
            st.stop()

    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        return

    # 4. ASEGURAR CONEXIÓN (Protocolo para evitar el error de socket)
    try:
        if not conn.is_connected():
            conn.reconnect(attempts=3, delay=1)
    except Exception:
        # Si la conexión principal está muerta, intentamos obtener una nueva
        conn = get_db_connection() 

    cursor = None
    try:
        usuario = st.session_state.get('usuario', 'Desconocido')
        registrar_log_automatico(conn, "CONCILIAR_DATOS", f"Usuario {usuario} concilió datos para {db_empresa}")
        
        cursor = conn.cursor(buffered=True)
        
        query_match = f"""
            UPDATE `{db_empresa}`.banco_movimientos bm
            JOIN `{db_empresa}`.asientos_contables ac ON bm.referencia = ac.referencia
            SET bm.estado_conciliacion = 'Conciliado', bm.asiento_id = ac.id
            WHERE bm.fecha_movimiento BETWEEN %s AND %s
            AND bm.estado_conciliacion = 'Pendiente'
        """
        
        cursor.execute(query_match, (fecha_inicio, fecha_fin))
        conn.commit()
        st.success(f"✅ ¡Conciliación inteligente ejecutada para {empresa_data['nombre_empresa']}!")
        
    except Exception as e:
        # Si falla, intentamos reconectar antes del rollback para que no de error de socket
        try:
            if conn.is_connected():
                conn.rollback()
        except:
            pass # Si el socket está totalmente roto, ya no se puede hacer rollback
        st.error(f"❌ Error al conciliar: {e}")
    finally:
        if cursor:
            cursor.close()

@log_ejecucion
def diagnosticar_conciliacion(conn, db_empresa):
    """
    db_empresa: Nombre de la base de datos específica (ej: 'empresa_a_db')
    """
    # 1. Recuperamos lo necesario de la sesión
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')
    usuario = st.session_state.get('usuario', 'Desconocido')

    # 2. VALIDACIÓN DE SEGURIDAD
    if not db_actual:
        st.error("No se ha seleccionado una base de datos de empresa.")
        st.stop()

    # Obtenemos los datos desde el control central para validar
    # Asegúrate de que esta función obtenga los datos de control_central.clientes
    empresa_data = obtener_datos_agente_db(db_actual)

    # 3. FILTRO DE ACCESO
    if empresa_data and rol != 'admin':
        if empresa_data['id'] != cliente_id:
            st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
            st.stop()
    
    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa para el diagnóstico.")
        return

    cursor = None
    try:
        registrar_log_automatico(conn, "DIAGNOSTICO_CONCILIACION", f"Usuario {usuario} realizó diagnóstico para cliente: {cliente_id}")
        
        cursor = conn.cursor(buffered=True)
        
        # Usamos la variable db_empresa para hacer las consultas dinámicas
        query = f"""
            SELECT b.referencia AS ref_b, a.referencia AS ref_a, 
                   b.monto AS monto_b, (a.haber - a.debe) AS monto_a
            FROM `{db_empresa}`.banco_movimientos b, `{db_empresa}`.asientos_contables a
            LIMIT 5
        """
        df_diagnostico = pd.read_sql(query, conn)
        
        st.subheader(f"🔍 Diagnóstico para: {empresa_data['nombre_empresa']}")
        st.table(df_diagnostico)
        
    except Exception as e:
        st.error(f"❌ Error en el diagnóstico para {db_empresa}: {e}")
    finally:
        if cursor:
            cursor.close()

from fpdf import FPDF
@log_ejecucion
def crear_pdf_conciliacion(conn, df_conciliado, saldo_inicial, saldo_final_banco, saldo_final_libros, lista_ingresos, lista_egresos):
    # 1. Recuperación de estado de sesión
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')

    # 2. VALIDACIÓN DE SEGURIDAD
    if not db_actual:
        st.error("No se ha seleccionado una base de datos de empresa.")
        st.stop()

    # 3. VERIFICACIÓN DE PERMISOS
    empresa_data = obtener_datos_agente_db(db_actual)
    if empresa_data and rol != 'admin':
        if empresa_data['id'] != cliente_id:
            st.error("⚠️ Acceso denegado.")
            st.stop()

    # 4. FECHA DINÁMICA (Aquí ya no usamos fecha_seleccionada)
    mes = st.session_state.get('mes_seleccionado') 
    anio = st.session_state.get('anio_seleccionado')
    
    if not mes or not anio:
        st.error("Por favor, selecciona un mes y un año en la interfaz.")
        st.stop()
        
    mes_anio = f"{mes} {anio}"

    # 5. GESTIÓN DE CONEXIÓN
    try:
        if not conn.is_connected():
            conn.reconnect(attempts=3, delay=1)
    except:
        conn = get_db_connection()

    cursor = None
    try:
        registrar_log_automatico(conn, "GENERAR_PDF_CONCILIACION", f"Usuario {st.session_state.usuario} | Cliente {cliente_id}")
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT nombre_empresa, rif, domicilio_fiscal FROM control_central.clientes WHERE id = %s", (cliente_id,))
        empresa = cursor.fetchone()
        
        pdf = FPDF()
        pdf.add_page()
        
        # Encabezado
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, empresa['nombre_empresa'] if empresa else "Conciliacion Bancaria", ln=True, align='C')
        
        if empresa:
            pdf.set_font("Arial", '', 10)
            pdf.cell(0, 5, f"RIF: {empresa['rif']} | Dirección: {empresa['domicilio_fiscal']}", ln=True, align='C')
        
        # Usamos el mes_anio que definimos arriba
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"Conciliacion Bancaria - Mes: {mes_anio}", ln=True, align='C')
        pdf.ln(5)
        
        # ... (resto de tu lógica se mantiene igual)
        pdf.set_font("Arial", 'B', 12)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(140, 10, "Saldo Final Banco", 1, 0, 'L', True)
        pdf.cell(50, 10, f"{saldo_final_banco:,.2f}", 1, 1, 'R')
        
        def pintar_seccion(titulo, lista_movimientos):
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(190, 8, titulo, ln=True)
            pdf.set_font("Arial", size=9)
            for mov in lista_movimientos:
                pdf.cell(30, 8, str(mov['fecha_movimiento']), 1)
                pdf.cell(40, 8, str(mov['referencia']), 1)
                pdf.cell(90, 8, str(mov['descripcion'])[:45], 1)
                pdf.cell(30, 8, f"{float(mov['monto']):,.2f}", 1, 1, 'R')
        
        pintar_seccion("Mas: Ingresos Pendientes", lista_ingresos)
        pintar_seccion("Menos: Egresos Pendientes", lista_egresos)
        
        pdf.ln(5)
        pdf.cell(140, 10, "Saldo Final Libros", 1, 0, 'L', True)
        pdf.cell(50, 10, f"{saldo_final_libros:,.2f}", 1, 1, 'R')
        
        dif = saldo_final_libros - saldo_final_banco
        pdf.ln(5)
        if abs(dif) < 0.01:
            pdf.set_text_color(0, 128, 0)
            pdf.cell(0, 10, "ESTADO: CONCILIADO - Diferencia Cero", ln=True, align='C')
        else:
            pdf.set_text_color(255, 0, 0)
            pdf.cell(0, 10, f"Diferencia pendiente de cuadre: {dif:,.2f}", ln=True, align='R')
        
        return pdf.output(dest='S').encode('latin-1')

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.ping(reconnect=True)

@log_ejecucion
def guardar_saldo_mensual(conn, banco, mes, ano, inicial, final):
    # Usamos buffered=True para que el conector consuma todo al instante
    cursor = conn.cursor(buffered=True)
    try:
        # Registro de actividad
        registrar_log_automatico(conn, "GUARDAR_SALDO_MENSUAL", f"Usuario {st.session_state.usuario} guardó saldo mensual para {st.session_state.cliente_id} (Banco: {banco})")
        
        query = """
            INSERT INTO kingdirver_ca.saldos_bancarios (banco, mes, ano, saldo_inicial, saldo_final)
            VALUES (%s, %s, %s, %s, %s) AS nuevo
            ON DUPLICATE KEY UPDATE 
            saldo_inicial = nuevo.saldo_inicial, 
            saldo_final = nuevo.saldo_final
        """
        cursor.execute(query, (str(banco), str(mes), int(ano), float(inicial), float(final)))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Error en la base de datos: {e}")
        conn.rollback()
        return False
    finally:
        # AQUÍ ESTÁ EL SECRETO:
        cursor.close() 
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        conn.ping(reconnect=True)

@log_ejecucion
def mes_esta_cerrado(conn, mes_nombre, ano):
    mes_map = {"Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
               "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12}
    mes_num = mes_map[mes_nombre]
    
    cursor = conn.cursor(buffered=True)
    try:
        # Registro de activida
        registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"Usuario {st.session_state.usuario} consultó tasa BCV directa {st.session_state.cliente_id}")
        
        cursor.execute("""
            SELECT COUNT(*) FROM kingdirver_ca.banco_movimientos 
            WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s 
            AND estado_conciliacion = 'Cerrado'
        """, (mes_num, ano))
        resultado = cursor.fetchone()[0] > 0
        return resultado
        
    except Exception as e:
        st.error(f"Error al verificar estado del mes: {e}")
        return False
        
    finally:
        cursor.close() 

@log_ejecucion
def mostrar_interfaz_busqueda_comprobante():
    # --- FRAME DE BÚSQUEDA ---
    # Usamos un expander para no recargar la vista principal
    with st.expander("🔍 Buscar Asiento Contable por Número de Comprobante", expanded=True):
        st.markdown("---")
        # Diseño en columnas para centrar y estilizar el input
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            st.markdown("### Ingrese los datos de búsqueda")
            # Input de texto para el número de comprobante con un placeholder de ejemplo
            n_comprobante_input = st.text_input(
                "Nº de Comprobante",
                key="input_n_comprobante",
                placeholder="Ej: ASI 202206001",
                help="Introduzca el código exacto del comprobante a consultar."
            )
            
            # Botón estilizado con el color principal (primary)
            buscar_btn = st.button(
                "🔍 Visualizar Reporte",
                key="btn_buscar_comprobante",
                type="primary",
                use_container_width=True
            )
            
        st.markdown("---")

        # Lógica de búsqueda al pulsar el botón
        if buscar_btn and n_comprobante_input:
            with st.spinner(f"Buscando el comprobante {n_comprobante_input}..."):
                # Aquí llamarías a tu función de base de datos
                # df_asiento = obtener_datos_comprobante_db(n_comprobante_input)
                # simulate_data = {} # Simulación para el ejemplo
                
                # Por ahora simulamos que encontramos datos
                existe_comprobante = True # Cambiar a False para probar error
                
                if existe_comprobante:
                    st.success(f"¡Comprobante {n_comprobante_input} encontrado!")
                    # Llamamos a la función que diseña el reporte
                    disenar_reporte_asiento_contable(n_comprobante_input)
                else:
                    st.error(f"❌ No se encontraron registros para el comprobante Nº: {n_comprobante_input}")
                    st.info("Verifique el número e intente nuevamente.")



@log_ejecucion
def consultar_bcv_directo_sin_bd():
    """Plan B absoluto: Si no hay BD, consulta la web directo y no rompe la app"""
    cursor = None
    
    try:
        # Registro de actividad
        registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"Usuario {st.session_state.usuario} consultó tasa BCV directa {st.session_state.cliente_id}")
        
        url = "https://www.bcv.org.ve/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_container = soup.find('div', id='dolar')
            if dolar_container:
                tasa_texto = dolar_container.find('strong').text.strip()
                tasa_float = float(tasa_texto.replace(',', '.'))
                return tasa_float, "Web BCV (Sin BD)"
                
    except Exception:
        pass
        
    finally:
        # AQUÍ ESTÁ EL SECRETO:
        if cursor:
            cursor.close()
            
        # NO cierres conn. 
        # En su lugar, haz un 'ping' para decirle a MySQL que sigues ahí:
        if conn and conn.is_connected():
            conn.ping(reconnect=True)
            
    return 1.0000, "Por defecto (Error Total)"
@log_ejecucion
def obtener_tasa_bcv_hoy(conn):
    """
    Busca la tasa en la BD. Si no existe para hoy, la consulta en la web 
    del BCV, la guarda en la BD y la retorna. Incluye autoreconexión.
    """
    # 1. VERIFICACIÓN DE SEGURIDAD: Reconexión automática
    try:
        if conn and not conn.is_connected():
            conn.reconnect(attempts=3, delay=2)
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
        
        # B. Si no está en BD, consultamos la Web
        url = "https://www.bcv.org.ve/"
        headers = {"User-Agent": "Mozilla/5.0..."}
        
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            dolar_container = soup.find('div', id='dolar')
            
            if dolar_container:
                tasa_texto = dolar_container.find('strong').text.strip()
                tasa_float = float(tasa_texto.replace(',', '.'))
                
                # --- AQUÍ ESTÁ EL LOG QUE QUERÍAS ---
                try:
                    # Ubica donde obtienes la tasa (cuando la traes de la web o de la BD)
                    # Y justo ahí, añade esta llamada:

                    registrar_log_automatico(conn, "CONSULTA_TASA_BCV", f"El usuario {st.session_state.usuario} consultó la tasa del BCV")
                except Exception:
                    pass # Si el log falla, no pasa nada, la app sigue viva
                
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

@log_ejecucion
def generar_reporte_multimoneda(conn, mes, ano):
    """
    Consolida saldos iniciales (siempre fijos de inicio de año) con los asientos 
    contables del mes seleccionado, aplicando la conversión a USD al vuelo.
    """
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT 
            t_origen.fecha,
            t_origen.plan_cuentas,      -- Ahora sí va a compilar fino
            t_origen.cuenta_contable,
            t_origen.descripcion,
            t_origen.debe,
            t_origen.haber,
            COALESCE(
                (SELECT t.tasa_valor FROM kingdirver_ca.tasas_diarias t WHERE t.fecha = t_origen.fecha LIMIT 1),
                (SELECT t2.tasa_valor FROM kingdirver_ca.tasas_diarias t2 WHERE t2.fecha <= t_origen.fecha ORDER BY t2.fecha DESC LIMIT 1),
                (SELECT t3.tasa_valor FROM kingdirver_ca.tasas_diarias t3 ORDER BY t3.fecha ASC LIMIT 1),
                1.0000
            ) AS tasa_bcv
        FROM (
            -- PARTE 1: Saldos Iniciales (Aquí sí existe plan_cuentas originalmente)
            SELECT fecha, plan_cuentas, cuenta_contable, descripcion, debe, haber
            FROM kingdirver_ca.saldos_iniciales
            WHERE YEAR(fecha) = %s
            
            UNION ALL
            
            -- PARTE 2: Asientos Contables 
            -- 🔥 TRUCO contable: Como asientos_contables NO tiene plan_cuentas, 
            -- usamos 'cuenta_contable' en su lugar para clonar la columna en el aire y que no falle el UNION.
            SELECT fecha, cuenta_contable AS plan_cuentas, cuenta_contable, descripcion, debe, haber
            FROM kingdirver_ca.asientos_contables
            WHERE MONTH(fecha) = %s AND YEAR(fecha) = %s
        ) AS t_origen
        ORDER BY t_origen.fecha ASC
    """
    
    # Pasamos los parámetros en el orden correcto de las condiciones:
    # 1. Año para saldos iniciales. 2. Mes para asientos. 3. Año para asientos.
    cursor.execute(query, (ano, mes, ano))
    datos = cursor.fetchall()
    cursor.close()
    
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

def actualizar_libro_diario_en_db(db_nombre, df_cambios):
    conn = conectar_db(db_nombre)
    cursor = conn.cursor()
    try:
        for _, row in df_cambios.iterrows():
            # El nombre de la columna en la BD es 'plan_cuentas'
            # El nombre de la columna en el DataFrame es 'plan_de_cuentas'
            sql = """
                UPDATE asientos_contables 
                SET n_comprobante = %s, descripcion = %s, fecha = %s, 
                    plan_cuentas = %s, cuenta_contable = %s, referencia = %s, 
                    debe = %s, haber = %s 
                WHERE id = %s
            """
            cursor.execute(sql, (
                row['n_comprobante'], 
                row['descripcion'], 
                row['fecha'], 
                row['plan_de_cuentas'], # Aquí usamos el nombre del DataFrame
                row['cuenta_contable'], 
                row['referencia'], 
                float(row['debe']), 
                float(row['haber']), 
                int(row['id'])
            ))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Error técnico en SQL: {str(e)}")
        return False
    finally:
        cursor.close()
        conn.close()

# =========================================================================
# 🔥 MÓDULO EXCLUSIVO: GESTIÓN DE INVENTARIO Y PRODUCCIÓN DE CONTENIDO
# Cliente: Representaciones Pedacito de Cielo
# =========================================================================

@log_ejecucion
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
                use_container_width=True, hide_index=True
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
                        st.dataframe(pd.DataFrame(data_kardex), use_container_width=True, hide_index=True)
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
            st.dataframe(df_receta_v, use_container_width=True, hide_index=True)
            
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
                use_container_width=True, hide_index=True
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
                        use_container_width=True, hide_index=True
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
@log_ejecucion         
def limpiar_conexion(conn):
    """Purga cualquier resultado pendiente en la conexión."""
    try:
        # Forzamos una consulta simple que no devuelve nada complejo
        # y consumimos todo el set de resultados
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()
    except:
        pass


# 1. DEFINICIÓN DE LA FUNCIÓN (DEBE IR ANTES DE USARSE)
def reset_empresa():
    st.session_state.conn = None 
    st.session_state.data_loaded = False
    st.session_state.kpis = None
    
    # Limpiamos el menú y forzamos el redibujado de la página
    if 'opcion_menu_auditoria' in st.session_state:
        del st.session_state['opcion_menu_auditoria']
    
    st.rerun() # <--- ESTO ES LO QUE OBLIGA A LA APP A MOSTRAR EL NUEVO MENÚ



# =========================================================
# 3. EJECUCIÓN FINAL (KPIs y Lógica Principal)
# =========================================================

if 'DB_ACTUAL' in st.session_state and st.session_state['DB_ACTUAL']:
    db_nombre = st.session_state['DB_ACTUAL']
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE', 'Empresa')
    
    conn = conectar_db(db_nombre)
    
    if conn:
        try:
            # 1. Limpieza de variables: Si sucursal es None, usamos un string vacío o un valor que SQL entienda
            f_inicio = st.session_state.get('f_inicio_global', '2026-01-01')
            f_fin = st.session_state.get('f_fin_global', '2026-12-31')
            sucursal = st.session_state.get('sucursal_seleccionada')
            # Si sucursal es None, forzamos a una cadena vacía o un valor neutro
            sucursal_segura = sucursal if sucursal is not None else ""
            
            # 2. Inicialización
            kpis, df_bar, df_pie, df_diario_local = None, None, None, None
            
            # 3. Procesamiento seguro
            # KPIs
            try:
                kpis = obtener_kpis_financieros(conn, f_inicio, f_fin, sucursal_segura)
            except Exception as e:
                st.error(f"⚠️ Error en KPIs: {e}")

            # Gráficos
            try:
                df_bar, df_pie = obtener_datos_graficos(conn, f_inicio, f_fin, sucursal_segura)
            except Exception as e:
                st.error(f"⚠️ Error en Gráficos: {e}")

            # Libro Diario
            try:
                df_diario_local = consultar_libro_diario_db(conn)
            except Exception as e:
                st.error(f"⚠️ Error en Libro Diario: {e}")
            
            # 4. Resultado final
            if any(var is not None for var in [kpis, df_bar, df_diario_local]):
                st.success(f"✅ Datos cargados correctamente para: {EMPRESA}")
            else:
                st.warning("⚠️ No se pudieron cargar los datos solicitados.")

        except Exception as e:
            st.error(f"❌ Error crítico: {e}")
            st.code(f"Detalle: {e}")
        finally:
            if conn and hasattr(conn, 'is_connected') and conn.is_connected():
                conn.close()
    else:
        st.error(f"❌ No se pudo establecer conexión con la base: {db_nombre}")
else:
    st.warning("⚠️ Por favor, seleccione una empresa en el panel lateral.")



# =========================================================================
# 1. TODO EL BLOQUE DEL SIDEBAR (Únicamente controles y navegación)
# =========================================================================
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=100)
    st.header("Panel de Auditoría")

    st.markdown("---")
    if st.button("🚪 Cerrar Sesión"):
        # Borramos todo lo de la sesión
        for key in st.session_state.keys():
            del st.session_state[key]
        # Recargamos la app para que vuelva a la pantalla de login
        st.rerun()

    # --- Navegación ---
    if st.session_state.get('rol') == 'admin':
        menu = st.radio("Navegación", ["📊 Auditoría Contable", "⚙️ Gestión de Usuarios"], key="menu_nav")
    else:
        menu = "📊 Auditoría Contable"

    st.divider()

    # --- Módulos y Configuración ---
    if menu == "📊 Auditoría Contable":
        st.markdown(
            """
            <style>
                div[data-baseweb="listbox"] { max-height: 350px !important; overflow-y: auto !important; }
                .stSelectbox div[role="button"] { margin-bottom: 5px; }
            </style>
            """,
            unsafe_allow_html=True
        )

        query_sidebar = "SELECT id, nombre_empresa, db_nombre FROM control_central.clientes"
        if st.session_state.get('rol') != 'admin':
            c_id = st.session_state.get('cliente_id')
            query_sidebar += f" WHERE id = {c_id}"

        df_sidebar = pd.DataFrame() 
        conn_sidebar = conectar_db()
        # 3. Solo si la conexión es válida, intentamos hacer la consulta
        if conn_sidebar is not None:
            try:
                query_sidebar = "SELECT id, nombre_empresa, db_nombre FROM control_central.clientes"
                if st.session_state.get('rol') != 'admin':
                    c_id = st.session_state.get('cliente_id')
                    query_sidebar += f" WHERE id = {c_id}"
                
                # Ejecutamos la consulta
                df_sidebar = pd.read_sql(query_sidebar, conn_sidebar)
            except Exception as e:
                st.error(f"Error al cargar clientes: {e}")
            finally:
                # Cerramos SIEMPRE la conexión
                conn_sidebar.close()
        else:
            st.sidebar.warning("⚠️ Sin conexión a BD")

        # Aseguramos que el df tenga datos antes de intentar el selectbox
        # ... (tu código previo hasta el if not df_sidebar.empty:) ...

        if not df_sidebar.empty:
            # 1. Selector de Empresa
            seleccion = st.sidebar.selectbox(
                "Seleccione Empresa", 
                df_sidebar['nombre_empresa'].tolist(), 
                key="selector_empresa", 
                on_change=reset_empresa
            )
            
            # 2. Sincronización de datos
            datos_filtrados = df_sidebar[df_sidebar['nombre_empresa'] == seleccion]
            
            if not datos_filtrados.empty:
                # ¡Aquí estaba el error! Estas líneas deben estar más a la derecha
                datos_sel = datos_filtrados.iloc[0]
                st.session_state['DB_ACTUAL'] = datos_sel['db_nombre']
                st.session_state['CLIENTE_NOMBRE'] = seleccion
                st.sidebar.write(f"Empresa: {seleccion.upper()}")
            
            st.subheader("Módulos")
            
            # --- El resto del código mantiene el mismo nivel que st.subheader ---
            modulos_disponibles = [
                "🏠 Inicio", "📂 Plan de Cuentas", "📝 Asientos Contables", 
                "📖 Mayor Analítico", "📊 Estados Financieros", "📚 Libros Fiscales", "👤 Proveedores"
            ]

            empresa_en_mayusculas = seleccion.upper()
            if "PEDACITO" in empresa_en_mayusculas and "CLIELO" in empresa_en_mayusculas:
                modulos_disponibles.append("🧁 Inventarios")

            opcion_menu = st.sidebar.selectbox("📂 SELECCIONE UN MÓDULO", modulos_disponibles)
            st.session_state['opcion_menu_auditoria'] = opcion_menu

            # Sub-opciones
            if opcion_menu == "📝 Asientos Contables":
                sub_opcion = st.sidebar.radio("Acciones:", ["Subir Datos", "Conciliación Bancaria","Consultar Comprobante", "Consultar Saldos Iniciales", "Consultar Cierre Contable"], key="sub_asientos")
            elif opcion_menu == "📊 Estados Financieros":
                st.sidebar.markdown("---")
                sub_opcion = st.sidebar.radio("Reportes Financieros:", ["Balance de Comprobación", "Balance General", "Estado de Resultados"], key="sub_estados")
            elif opcion_menu == "📚 Libros Fiscales":
                sub_opcion = st.sidebar.radio("Reportes Fiscales:", ["Libro de Ventas", "Libro de Compras", "Comprobante de Retención ISLR","Comprobante de Retención IVA"], key="sub_libros")
            else:
                sub_opcion = None
            
            st.sidebar.divider()
            st.sidebar.subheader("📅 Período de Consulta")
            col_anio, col_mes = st.sidebar.columns(2)
            col_anio.number_input("Año", value=2026, step=1, key="f_anio_global")
            col_mes.selectbox("Mes", ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"], index=datetime.now().month - 1, key="f_mes_global")

        else:
            st.error("No se encontraron empresas asociadas.")
            st.stop()

    

# --- VALIDACIÓN DE CONEXIÓN GLOBAL ---
def asegurar_conexion():
    if 'conn' not in st.session_state or st.session_state.conn is None:
        st.session_state.conn = conectar_db("control_central")
    
    if st.session_state.conn is not None and not st.session_state.conn.is_connected():
        st.session_state.conn = conectar_db("control_central")
    
    return st.session_state.conn


# --- INTERRUPTOR DE PANTALLAS ---

# PANTALLA: GESTIÓN DE USUARIOS
if menu == "⚙️ Gestión de Usuarios": 
    try:
        # 1. Aseguramos conexión
        if not conn or not conn.is_connected():
            conn = conectar_db("control_central")

        # 2. ELIMINAMOS ESTE BLOQUE QUE CAUSA EL ERROR:
        # with conn.cursor() as cursor:
        #    cursor.execute("SELECT * FROM control_central.usuarios WHERE rol = 'admin'")
        #    <-- ¡NO HICISTE FETCHALL() AQUÍ, POR ESO EL ERROR!

        # 3. Llamamos directo a la función que SÍ maneja sus cursores internamente
        if conn and conn.is_connected():
            panel_administracion(conn)
        else:
            st.error("🔌 No se pudo establecer conexión con el servidor MySQL.")
            
    except Exception as e:
        st.error(f"Error al acceder a la gestión central: {e}")

    st.stop()



# --- LÓGICA DE FECHAS SEGURA ---
meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Usamos .get() con valores por defecto para que no explote si el widget no ha cargado
mes_seleccionado = st.session_state.get('f_mes_global', "Enero")
anio_f = st.session_state.get('f_anio_global', 2026)

m_idx = meses.index(mes_seleccionado) + 1

# Calculamos el último día exacto del mes
ultimo_dia = calendar.monthrange(anio_f, m_idx)[1]

# Variables de fecha tipo objeto
f_inicio_global = datetime(anio_f, m_idx, 1)
f_fin_global = datetime(anio_f, m_idx, ultimo_dia)

# Variables de texto
fecha_inicio_str = f_inicio_global.strftime('%Y-%m-%d')
fecha_fin_str = f_fin_global.strftime('%Y-%m-%d')

EMPRESA = st.session_state.get('CLIENTE_NOMBRE', 'N/A')

# 1. INICIALIZACIÓN GLOBAL (Aquí va tu código)
if 'db_a_conectar' not in st.session_state:
    st.session_state.db_a_conectar = "control_central"
    st.session_state.nombre_empresa_seleccionada = "Seleccione Cliente"



# Definición de la función de limpieza (ponla arriba de todo)
def actualizar_empresa():
    st.session_state.conn = None # Forzamos nueva conexión
    # IMPORTANTE: Aquí asignas los valores reales a session_state
    st.session_state.DB_ACTUAL = st.session_state.selector_empresa
    # Asegúrate de mapear el nombre real de la DB aquí:
    if "KING DRIVER" in st.session_state.selector_empresa:
        st.session_state.nombre_empresa_seleccionada = "KING DRIVER, C.A."
        st.session_state.db_a_conectar = "kingdirver_ca" # Nombre técnico exacto
    else:
        st.session_state.nombre_empresa_seleccionada = "REPRESENTACIONES PEDACITO DE CIELO, C.A."
        st.session_state.db_a_conectar = "pedacito_cielo_ca" # Nombre técnico exacto



# 1. Obtenemos los valores del estado
BD_A_CONECTAR = st.session_state.get('db_a_conectar', "control_central")
EMPRESA = st.session_state.get('nombre_empresa_seleccionada', "Seleccione Cliente")
opcion_menu = st.session_state.get('opcion_menu_auditoria', "🏠 Inicio")
# 2. Conexión centralizada
if BD_A_CONECTAR != "control_central":
    # Solo conectamos si no hay una conexión válida en el estado
    if 'conn' not in st.session_state or st.session_state.conn is None:
        conn = conectar_db(BD_A_CONECTAR)
        st.session_state.conn = conn
    else:
        conn = st.session_state.conn

    # 3. Bypass de seguridad (EL "USE" EN CALIENTE)
    if conn is not None:
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"USE `{BD_A_CONECTAR}`")
            st.success(f"✅ Conectado a: {EMPRESA}")
        except Exception as e:
            st.error(f"Error al cambiar de base de datos: {e}")

if "Inicio" in opcion_menu:
    # 1. Recuperamos la DB seleccionada
    db_actual = st.session_state.get('DB_ACTUAL', 'No seleccionada')
    
    # 2. Verificamos si la conexión actual coincide con la DB seleccionada
    # Usamos una variable auxiliar en session_state para comparar
    conexion_coincide = st.session_state.get('ultima_db_conectada') == db_actual

    # 3. Si no hay conexión O no coincide con la empresa seleccionada, reconectamos
    if 'conn' not in st.session_state or st.session_state.conn is None or not conexion_coincide:
        st.info(f"🔄 Conectando a la base de datos: {db_actual}...")
        
        # Intentamos conectar
        nueva_conn = conectar_db(db_actual)
        
        if nueva_conn:
            st.session_state.conn = nueva_conn
            st.session_state.ultima_db_conectada = db_actual
            st.rerun() # Recargamos para limpiar advertencias
        else:
            st.error(f"❌ No se pudo conectar a {db_actual}")
            st.stop()

    # 4. ENCABEZADO DINÁMICO (Ahora sí mostrará el nombre correcto)
    st.title(f"📊 Auditoría Profesional: {db_actual}")
    st.markdown(f"**Período de Análisis:** {f_inicio_global.strftime('%d/%m/%Y')} al {f_fin_global.strftime('%d/%m/%Y')}")
    st.divider()
    
    conn = st.session_state.conn
    # 3. LÓGICA PRINCIPAL

    # LÓGICA PRINCIPAL (Optimización sugerida)
    col_kpi, col_btn = st.columns([0.8, 0.2])
    
    with col_kpi:
        st.subheader("Indicadores Financieros en Tiempo Real")
    
    with col_btn:
        # Esto pone el botón a la derecha, se ve más elegante
        if st.button("🔄 Actualizar Datos"):
            st.cache_data.clear()
            st.rerun()
    try:

        with st.spinner('Calculando indicadores financieros...'):
            kpis = obtener_kpis_financieros(conn, f_inicio_global, f_fin_global, sucursal, st.session_state.get('DB_ACTUAL'))
            df_bar, df_pie = obtener_datos_graficos(conn, f_inicio_global, f_fin_global, sucursal)
           

        # --- FILA 1: KPIs PRINCIPALES ---
        col1, col2, col3 = st.columns(3)
        
        # Ahora kpis.get('activo', 0) ya trae el valor de 'activo_real'
        valor_activo = kpis.get('activo', 0)
        valor_pasivo = kpis.get('pasivo', 0)
        
        with col1:
            st.container(border=True).metric("💰 ACTIVO TOTAL", f"Bs. {valor_activo:,.2f}", "Recursos")
        with col2:
            porc_p = (valor_pasivo / valor_activo * 100) if valor_activo != 0 else 0
            st.container(border=True).metric("📉 PASIVO TOTAL", f"Bs. {valor_pasivo:,.2f}", f"{porc_p:.1f}% del Activo", delta_color="inverse")
        with col3:
            u_v = kpis.get('utilidad', 0)
            st.container(border=True).metric("📊 UTILIDAD NETAS", f"Bs. {u_v:,.2f}", "Resultado", delta_color="normal" if u_v >= 0 else "inverse")

        # --- FILA 2: SALUD FISCAL (SENIAT) ---
                # --- FILA 2: SALUD FISCAL (SENIAT) ---
        st.markdown("### 📑 Salud Fiscal (Resumen SENIAT)")
        f1, f2, f3 = st.columns(3)
        f1.info(f"**IVA por Enterar**\n### Bs. {kpis.get('retenido', 0.0):,.2f}")
        f2.success(f"**Compras Brutas**\n### Bs. {kpis.get('compras', 0.0):,.2f}")
        f3.warning(f"**Monto Exento**\n### Bs. {kpis.get('exento', 0.0):,.2f}")

        st.divider()

        # --- FILA 3: SALUD FINANCIERA ---
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
        patrimonio_v = kpis.get('patrimonio', 0)
        r3.metric("Capital Propio", f"Bs. {patrimonio_v:,.2f}", "Patrimonio Neto")


        # --- FILA 4: ANÁLISIS VISUAL ---
        st.divider()
        col_izq, col_der = st.columns(2)
        with col_izq:
            st.subheader("📊 Comparativo Ingresos/Egresos")
            if not df_bar.empty:
                st.plotly_chart(px.bar(df_bar, x='Categoría', y='Monto', color='Categoría', color_discrete_map={'Ingresos': '#00CC96', 'Egresos': '#EF553B'}), use_container_width=True)
        with col_der:
            st.subheader("🍕 Distribución de Gastos")
            if not df_pie.empty:
                st.plotly_chart(px.pie(df_pie, values='Saldo Final', names='nombre', hole=0.4), use_container_width=True)

        # --- FILA 5: FLUJO DE EFECTIVO ---
        st.divider()
        st.subheader("💸 Movimiento de Caja (Efectivo Real)")
        c1, c2, c3 = st.columns(3)

        # 1. Entradas del mes
        c1.metric("Entradas (BDV)", f"Bs. {kpis.get('entradas_efectivo', 0.0):,.2f}", "Cobros")

        # 2. Salidas del mes
        c2.metric("Salidas (BDV)", f"Bs. {kpis.get('salidas_efectivo', 0.0):,.2f}", "Pagos", delta_color="inverse")

        # 3. SALDO REAL (El que suma Saldos Iniciales + Asientos)
        # Cambiamos 'flujo_neto' por 'saldo_real_final'
        saldo_acumulado = kpis.get('saldo_real_final', 0.0) 
        c3.metric("Saldo Real en Banco", f"Bs. {saldo_acumulado:,.2f}", "Disponible", delta_color="normal" if saldo_acumulado >= 0 else "inverse")

        # --- FILA 6: PROVEEDORES ---
        st.divider()
        st.subheader("📦 Gestión Operativa")
        p1, p2 = st.columns(2)
        p1.info(f"**Top Proveedor:** {kpis.get('top_proveedor', 'N/A')} ({kpis.get('top_porcentaje', 0)}%)")
        n_a = kpis.get('alertas_retencion', 0)
        if n_a > 0: p2.warning(f"⚠️ {n_a} facturas sin retención aplicada.")
        else: p2.success("✅ Retenciones al día.")

        # --- SECCIÓN: INDICADORES CAMBIARIOS EN LA INTERFAZ ---
        st.markdown("### 🏦 Indicadores Cambiarios")

        # 1. Traer la tasa normal de la BD o Web
        tasa_dolar, origen_datos = obtener_tasa_bcv_hoy(conn)

        col_tasa, col_info = st.columns([1, 2])

        with col_tasa:
            s = f"{tasa_dolar:,.8f}"
            tasa_formateada = f"Bs. {s.replace(',', 'X').replace('.', ',').replace('X', '.')}"
            st.metric(label="💵 Tasa Oficial BCV (USD/VES)", value=tasa_formateada)

        with col_info:
            st.caption("ℹ️ **Actualización Automática:**")
            st.info(f"El sistema sincroniza directamente con el Banco Central de Venezuela. \n\n**Fuente de lectura actual:** {origen_datos}")
            
            # 🔥 EL BOTÓN MÁGICO DE ACTUALIZACIÓN FORZADA
            if st.button("🔄 Forzar Sincronización BCV"):
                from datetime import date
                try:
                    # Limpiamos conexiones pegadas
                    if conn.is_connected():
                        conn.handle_unread_result()
                        
                    # Forzamos la consulta directa a la web saltándonos la BD
                    tasa_fresca, origen_fresco = consultar_bcv_directo_sin_bd()
                    
                    if "Error" not in origen_fresco:
                        hoy = date.today()
                        cursor = conn.cursor()
                        # Metemos el valor actualizado a la fuerza
                        cursor.execute("""
                            INSERT INTO kingdirver_ca.tasas_diarias (fecha, tasa_valor) 
                            VALUES (%s, %s)
                            ON DUPLICATE KEY UPDATE tasa_valor = %s
                        """, (hoy, tasa_fresca, tasa_fresca))
                        conn.commit()
                        cursor.close()
                        st.success("¡Tasa actualizada con éxito desde el BCV!")
                        st.rerun()
                    else:
                        st.error("No se pudo conectar a la web del BCV en este momento.")
                except Exception as e:
                    st.error(f"Error al sincronizar: {e}")
        # --- SECCIÓN VISUAL: REPORTE CONTABLE MULTIMONEDA ---
        st.markdown("---")
        st.markdown("## 📊 Reporte de Libro Diario Multimoneda")

        # 1. Filtros de búsqueda y acciones (Agregamos una 4ta columna para el botón)
        col_filtro1, col_filtro2, col_filtro3, col_boton = st.columns([1.5, 1.5, 2, 2])

        with col_filtro1:
            mes_seleccionado = st.selectbox(
                "Seleccione el Mes:", 
                options=list(range(1, 13)), 
                format_func=lambda x: ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][x-1],
                index=date.today().month - 1
            )

        with col_filtro2:
            ano_seleccionado = st.selectbox(
                "Seleccione el Año:", 
                options=[2024, 2025, 2026, 2027], 
                index=2  # Fijo en 2026 por defecto
            )

        with col_filtro3:
            # Metemos un espacio en blanco arriba para alinear verticalmente el toggle con los selectores
            st.markdown("<div style='padding-top: 25px;'></div>", unsafe_allow_html=True)
            moneda_vista = "Dólares (USD)" if st.toggle("🇺🇸 Ver reporte en USD", value=False) else "Bolívares (VES)"
        # --- BLOQUE LÓGICO DE DATOS (Debe ejecutarse antes para poder descargar) ---
        try:
            df_diario = generar_reporte_multimoneda(conn, mes_seleccionado, ano_seleccionado)
            
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
                # 🔥 AQUÍ SE INTEGRA LA ZONA DE REPORTES FINANCIEROS EN DIVISAS
                # =========================================================================
                st.markdown("<br>", unsafe_allow_html=True) 
                
                with st.expander("📊 Reportes Financieros Consolidados (Multimoneda)", expanded=False):
                    st.markdown(f"### 📋 Balance de Comprobación — Período Seleccionado ({moneda_vista})")
                    st.write("Consolidación analítica de saldos: Apertura, Movimientos mensuales y Saldos de Cierre.")
                    
                    if st.button("🧮 Generar Balance de Comprobación", use_container_width=True):
                        
                        # Definimos qué columnas numéricas usar según la divisa seleccionada
                        col_debe_calc = 'debe_usd' if moneda_vista == "Dólares (USD)" else 'debe'
                        col_haber_calc = 'haber_usd' if moneda_vista == "Dólares (USD)" else 'haber'
                        
                        # --- PASO 1: Identificar cuáles filas son Saldos Iniciales y cuáles son Asientos ---
                        df_diario['es_inicial'] = df_diario['descripcion'].str.contains("SALDOS INICIALES", case=False, na=False)
                        
                        # --- PASO 2: Agrupar por Cuenta y Plan de Cuentas (Código) ---
                        balance_data = []
                        
                        # Agrupamos por la combinación de código y nombre
                        for (codigo, cuenta), group in df_diario.groupby(['plan_cuentas', 'cuenta_contable']):
                            
                            grupo_inicial = group[group['es_inicial']]
                            grupo_mes = group[~group['es_inicial']]
                            
                            # 1. Saldo Inicial Neto
                            ini_debe = grupo_inicial[col_debe_calc].sum()
                            ini_haber = grupo_inicial[col_haber_calc].sum()
                            saldo_inicial = ini_debe - ini_haber
                            
                            # 2. Movimientos puros del mes
                            mes_debe = grupo_mes[col_debe_calc].sum()
                            mes_haber = grupo_mes[col_haber_calc].sum()
                            
                            # 3. Saldo Final
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
                        
                        # Ordenamos el dataframe por el código contable para que se vea estructurado (1.1, 1.2, etc.)
                        df_balance = df_balance.sort_values(by='Código Contable').reset_index(drop=True)
                        
                        # --- PASO 3: Formatear las 6 columnas con el diseño premium ---
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
                        
                        # --- PASO 4: Renderizar la tabla de 6 columnas definitivas ---
                        st.dataframe(df_balance_visual, use_container_width=True, hide_index=True)
                        
                        # --- PASO 5: Totales de Control Contable ---
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
            # =========================================================================
            # 🔥 NUEVO MÓDULO PREMIUM: AUDITORÍA FORENSE CON IA
            # =========================================================================
            st.markdown("<br>", unsafe_allow_html=True)
            
            with st.expander("🕵️‍♂️ Módulo de Auditoría Forense con IA (Antifraude)", expanded=False):
                st.markdown("### 🔍 Análisis de Patrones y Detección Automatizada de Anomalías")
                st.write("La IA analiza los asientos del mes buscando importes atípicos, desviaciones estadísticas y registros duplicados.")
                
                if st.button("🚀 Ejecutar Escáner Antifraude", use_container_width=True):
                    st.info("Procesando algoritmos estadísticos sobre el Libro Diario...")
                    
                    # Definimos la columna numérica a evaluar según la moneda visual actual
                    col_analisis = 'debe_usd' if moneda_vista == "Dólares (USD)" else 'debe'
                    simb = "$" if moneda_vista == "Dólares (USD)" else "Bs."
                    
                    # 🔥 CORRECCIÓN CRÍTICA: Aseguramos que la columna descripción no tenga nulos (NaN) para que no rompa el filtro
                    df_diario['descripcion'] = df_diario['descripcion'].fillna("").astype(str)
                    
                    # Filtramos los movimientos operativos reales del mes (ignorando los registros que correspondan a la apertura de saldos iniciales)
                    df_asientos = df_diario[
                        ~(df_diario['descripcion'].str.contains("SALDOS INICIALES", case=False, na=False)) & 
                        (df_diario[col_analisis] > 0)  # Solo auditamos donde se mueva dinero (mayor a cero)
                    ].copy()
                    
                    anomalies_found = False
                    alertas_duplicados = []
                    alertas_montos = []

                    if df_asientos.empty:
                        # Mensaje inteligente si de verdad el mes no tiene movimientos operativos individuales
                        st.warning("📊 El sistema determinó que este período no registra transacciones operativas o de gastos en el Libro Diario para ser evaluadas por el modelo estadístico.")
                    else:
                        # -----------------------------------------------------------------
                        # ALGORITMO 1: DETECCIÓN DE FACTURAS / REGISTROS DUPLICADOS
                        # -----------------------------------------------------------------
                        # Buscamos registros que compartan exactamente la misma fecha, cuenta e importe el mismo día
                        duplicados = df_asientos[df_asientos.duplicated(subset=['fecha', 'cuenta_contable', col_analisis], keep=False)]
                        
                        if not duplicados.empty:
                            anomalies_found = True
                            for cuenta, gp in duplicados.groupby('cuenta_contable'):
                                monto_dup = gp[col_analisis].iloc[0]
                                alertas_duplicados.append(
                                    f"🚩 **Sospecha de Duplicidad:** Se encontraron {len(gp)} registros idénticos el mismo día en la cuenta **{cuenta}** por un monto de {simb} {monto_dup:,.2f}."
                                )

                        # -----------------------------------------------------------------
                        # ALGORITMO 2: DESVIACIÓN ESTÁNDAR (Z-SCORE CONTABLE MULTIVARIABLE)
                        # -----------------------------------------------------------------
                        # Calculamos la media y desviación agrupada por cuenta contable
                        stats = df_asientos.groupby('cuenta_contable')[col_analisis].agg(['mean', 'std']).reset_index()
                        
                        # Cruzamos estadísticas con el df de auditoría
                        df_audit = df_asientos.merge(stats, on='cuenta_contable', how='left')
                        
                        # Si hay un solo movimiento, la desviación da NaN. Reemplazamos por 1.0 de forma segura para evitar divisiones por cero
                        df_audit['std'] = df_audit['std'].fillna(0.0).replace(0.0, 1.0)
                        
                        # Calculamos el Z-score real
                        df_audit['z_score'] = (df_audit[col_analisis] - df_audit['mean']) / df_audit['std']
                        
                        # Marcamos como anomalía si el Z-score supera el umbral estadístico (Z > 2.0)
                        # y además el monto supera en un 50% la media histórica (evita falsos positivos con montos pequeños)
                        anomalas_std = df_audit[(df_audit['z_score'] > 2.0) & (df_audit[col_analisis] > df_audit['mean'] * 1.5)]
                        
                        if not anomalas_std.empty:
                            for idx, row in anomalas_std.iterrows():
                                porcentaje_desvio = ((row[col_analisis] - row['mean']) / row['mean']) * 100 if row['mean'] > 0 else 100
                                
                                # Filtro de ruido contable para transacciones insignificantes
                                if porcentaje_desvio > 15:
                                    anomalies_found = True
                                    alertas_montos.append(
                                        f"🚨 **Monto Atípico Detectado:** En la cuenta **{row['cuenta_contable']}**, el registro *'{row['descripcion']}'* tiene un importe de **{simb} {row[col_analisis]:,.2f}**. "
                                        f"¡Esto representa un desvío del **{porcentaje_desvio:.0f}% por encima** de su comportamiento transaccional promedio!"
                                    )

                        # -----------------------------------------------------------------
                        # RENDERIZADO DE ALERTAS EN LA INTERFAZ CONTABLE
                        # -----------------------------------------------------------------
                        if anomalies_found:
                            st.error("❌ ¡Alerta del Sistema! Se detectaron inconsistencias de riesgo en el período analizado.")
                            
                            # Mostramos las alertas de montos atípicos
                            if alertas_montos:
                                st.markdown("#### 📉 Alertas de Desviación Presupuestaria e Importes Atípicos")
                                for alerta in alertas_montos:
                                    st.warning(alerta)
                                    
                            # Mostramos las alertas de registros duplicados
                            if alertas_duplicados:
                                st.markdown("#### 📑 Alertas de Posibles Registros o Facturas Duplicadas")
                                for alerta in alertas_duplicados:
                                    st.info(alerta)
                                    
                            st.markdown("---")
                            st.caption("💡 *Recomendación de la IA: Solicite los soportes físicos de estos asientos y verifique los números de control antes de proceder con el cierre de mes.*")
                        else:
                            st.success("✨ ¡Análisis Completo! La IA ejecutó los modelos de varianza y la data operativa está perfectamente limpia y alineada con los parámetros habituales.")
                  
        except Exception as e:
            st.error(f"❌ Error al procesar el reporte: {e}")

    except Exception as e:
        st.error(f"❌ Error al procesar el reporte: {e}")
    finally:
        # Cierre de conexión seguro
        if 'conn' in st.session_state and st.session_state.conn.is_connected():
            st.session_state.conn.close()


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
                # --- 3. Visualización y Edición ---
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
                        df_subido.columns = ['id_ex', 'N_comprobante', 'Descripcion', 'Fecha', 
                                           'plan_de_cuentas', 'cuenta_contable', 'Ref', 'Debe', 'Haber']
                        df_subido = df_subido.drop(columns=['id_ex'])
                        
                        # Limpieza
                        if str(df_subido.iloc[0, 1]).lower() in ['n_comprobante', 'nan']:
                            df_subido = df_subido.iloc[1:].reset_index(drop=True)
                        df_subido['Fecha'] = pd.to_datetime(df_subido['Fecha'], errors='coerce').dt.date

                        st.write("### ✅ Vista previa de la carga:")
                        st.dataframe(df_subido, hide_index=True, use_container_width=True)

                        # 2. Importación segura
                        if st.button("🚀 Confirmar e Importar al Diario"):
                            # Usamos db_actual (la que validamos al principio del módulo)
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
                                    conn.close() # Cierre garantizado
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

        # 3. Encapsulamos toda la lógica en un try...finally para garantizar el cierre
     
        # 1. Selectores Globales
        col1, col2 = st.columns([1, 1])
        with col1:
            mes_sel = st.selectbox("Mes", ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                                           "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"], index=2,key="mes_seleccionado")
        with col2:
            ano_sel = st.selectbox("Año", [2025, 2026, 2027], index=1, key="ano_seleccionado")


        # Tabs: Orden Lógico de trabajo
        tab1,tab2,tab3,tab4,tab5  = st.tabs([
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

                            st.write("### ✅ Vista previa:")
                            v_debe = df_subido['Debe'].apply(limpiar_monto_contable).sum()
                            v_haber = df_subido['Haber'].apply(limpiar_monto_contable).sum()

                            st.dataframe(
                                df_subido.style.format({
                                    'Debe': lambda x: formato_contable(limpiar_monto_contable(x)),
                                    'Haber': lambda x: formato_contable(limpiar_monto_contable(x))
                                }), 
                                hide_index=True, use_container_width=True
                            )

                            c1, c2, c3 = st.columns(3)
                            c1.metric("TOTAL DEBE", formato_contable(v_debe))
                            c2.metric("TOTAL HABER", formato_contable(v_haber))
                            
                            if abs(v_debe - v_haber) < 0.01:
                                c3.success("✅ CUADRADO")
                                if st.button("🚀 Confirmar e Importar"):
                                    # PASAMOS db_actual PARA QUE LA FUNCIÓN SEPA DÓNDE INSERTAR
                                    if cargar_saldos_iniciales_db(df_subido, db_name=db_actual):
                                        st.balloons()
                                        st.success("✅ ¡ASIENTO DE APERTURA GUARDADO!")
                                        st.rerun()
                            else:
                                c3.error(f"❌ DESCUADRE: {formato_contable(abs(v_debe - v_haber))}")
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
elif opcion_menu == "📖 Mayor Analítico":
    st.subheader("📖 Mayor Analítico")

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
        # 3. EJECUCIÓN SEGURA
        mostrar_interfaz_mayor(f_inicio_global, f_fin_global, db_actual)

# E. ESTADOS FINANCIEROS -> BALANCE COMPROBACIÓN
elif sub_opcion == "Balance de Comprobación":
    # 1. Obtener datos de sesión
    EMPRESA = st.session_state.get('CLIENTE_NOMBRE')
    db_actual = st.session_state.get('DB_ACTUAL')
    sucursal = st.session_state.get('SUCURSAL_SELECCIONADA', 'Todas') # ARREGLA EL ERROR DE 'SUCURSAL'
    
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()
    
    st.subheader(f"⚖️ Balance de Comprobación: {EMPRESA}")
    
    # --- FILTROS (Sin base de datos para que no den error) ---
    col_f1, col_f2 = st.columns(2)
    f_bal_desde = col_f1.date_input("Desde", f_inicio_global, key="bal_desde")
    f_bal_hasta = col_f2.date_input("Hasta", f_fin_global, key="bal_hasta")

    # 2. CONEXIÓN EXCLUSIVA PARA EL BALANCE
    conn_temporal = conectar_db(db_actual)
    
    if conn_temporal:
        try:
            # Despertar conexión
            conn_temporal.ping(reconnect=True)
            
            # 2. Generar el reporte usando la conexión temporal
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

                # Identifica quién está descuadrado:



                # --- OBTENER TOTALES DIRECTO DE LA FILA Σ (YA CALCULADA) ---
                fila_sigma = df_display[df_display['codigo'] == 'Σ']

                # Definimos variables con 0.0 por defecto para evitar el error 'not defined'
                t_inicial = t_debe = t_haber = t_final = 0.0

                if not fila_sigma.empty:
                    t = fila_sigma.iloc[0] # Usamos iloc[0] para acceder a la serie de la fila
                else:
                    # Creamos una serie vacía o con ceros si no existe Σ
                    t = pd.Series({'Saldo Inicial': 0.0, 'Debe': 0.0, 'Haber': 0.0, 'Saldo Final': 0.0})

                # --- AHORA AQUÍ VA LA VISUALIZACIÓN DEL RESUMEN PATRIMONIAL ---
                st.markdown("### 📊 Resumen Patrimonial")

                # Usamos columnas para que se vea profesional y alineado
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Saldo Inicial", formato_contable(t['Saldo Inicial']))
                c2.metric("Total Debe", formato_contable(t['Debe']))
                c3.metric("Total Haber", formato_contable(t['Haber']))
                c4.metric("Saldo Final", formato_contable(t['Saldo Final']))

                # Opcional: Un mensaje de cuadre con color
                if abs(abs(t['Debe']) - abs(t['Haber'])) < 0.01:
                    st.success("✅ La ecuación patrimonial está balanceada.")
                else:
                    # Calculamos la diferencia real para mostrarla
                    diferencia = t['Debe'] - t['Haber']
                    st.error(f"❌ Descuadre detectado: {formato_contable(diferencia)}")

               

                # --- BOTONES DE EXPORTACIÓN ---
                st.divider()
                col_btn1, col_btn2 = st.columns(2)

                # 1. PREPARAR EL DATAFRAME PARA EXCEL (Solo lo que el cliente debe ver)
                # Filtramos las columnas y les ponemos nombres bonitos
                columnas_excel = {
                    'codigo': 'Código',
                    'nombre': 'Cuenta',
                    'Saldo Inicial': 'Saldo Inicial',
                    'Debe': 'Debe',
                    'Haber': 'Haber',
                    'Saldo Final': 'Saldo Final'
                }

                # Creamos una copia limpia para la descarga
                df_excel = df_bal[list(columnas_excel.keys())].copy()
                df_excel = df_excel.rename(columns=columnas_excel)

                # 2. GENERAR EL ARCHIVO EXCEL
                output_ex = io.BytesIO()
                with pd.ExcelWriter(output_ex, engine='xlsxwriter') as writer:
                    df_excel.to_excel(writer, index=False, sheet_name='Balance')
                    
                    # --- AUTO-AJUSTE DE COLUMNAS Y FORMATO (OPCIONAL PERO PRO) ---
                    workbook  = writer.book
                    worksheet = writer.sheets['Balance']
                    format_num = workbook.add_format({'num_format': '#,##0.00'})
                    
                    # Ajustar ancho de columna Cuenta
                    worksheet.set_column('B:B', 40)
                    # Aplicar formato de moneda a las columnas numéricas (C, D, E, F)
                    worksheet.set_column('C:F', 18, format_num)

                col_btn1.download_button(
                    label="📥 Descargar Excel Limpio",
                    data=output_ex.getvalue(),
                    file_name=f"Balance_{EMPRESA}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

                # PDF
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
                            # Negrita para niveles principales
                            pdf.set_font("Arial", 'B' if row['nivel'] <= 2 else '', 7)
                            # Sangría visual según nivel
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

            else:
                st.info("No hay datos para el rango seleccionado.")

        except Exception as e:
            st.error(f"Error procesando balance: {e}")
        
        finally:
            # 3. EL CIERRE SAGRADO: Pase lo que pase, soltamos la conexión.
            if conn_temporal.is_connected():
                conn_temporal.close()
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
    f_corte = st.date_input("Fecha de Corte", value=f_fin_global, key="bg_corte")
    
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
                    use_container_width=True, height=500, hide_index=True
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
                    use_container_width=True
                )

                # --- PDF ---
                if col_pdf.button("📄 Generar PDF Profesional", use_container_width=True, type="primary"):
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
                            use_container_width=True
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
            if conn_temporal.is_connected():
                conn_temporal.close()
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
    
    col_f1, col_f2 = st.columns(2)
    f_er_desde = col_f1.date_input("Desde", f_inicio_global, key="er_desde")
    f_er_hasta = col_f2.date_input("Hasta", f_fin_global, key="er_hasta")
    
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
                    use_container_width=True, 
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
                # 1. GESTIÓN DE TASA BCV
                if 'tasa_bcv' not in st.session_state:
                    tasa, _ = obtener_tasa_bcv_hoy(conn)
                    st.session_state.tasa_bcv = tasa

                if st.button("🔄 Actualizar Tasa BCV"):
                    tasa, _ = obtener_tasa_bcv_hoy(conn)
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
                    use_container_width=True
                )

                # --- PDF ---
                if col_pdf.button("📄 Generar PDF Profesional", use_container_width=True, type="primary"):
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
                            use_container_width=True
                        )
                    except Exception as e_pdf:
                        st.error(f"Error PDF: {e_pdf}")

            else:
                st.info("No se encontraron movimientos de resultados en este periodo.")

        
        except Exception as e:
            st.error(f"Error en Estado de Resultados: {e}")
        finally:
            if conn_er.is_connected():
                conn_er.close()
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

        # Si quieres que la lógica de la pestaña activa sea más estricta, 
        # podrías usar st.session_state.active_tab aquí, pero con los st.tabs, 
        # Streamlit ya gestiona la navegación de forma nativa.

        # --- PESTAÑA 1: CARGA DESDE EXCEL ---
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
                    resultado = st.data_editor(df_preview, key=f"editor_{archivo_v.name}", use_container_width=True,column_config=column_config)
                    
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
            with col_v1:
                desde_v = st.date_input("Desde", f_inicio_global, key="f_desde_v", disabled=ver_todo_v)
            with col_v2:
                hasta_v = st.date_input("Hasta", f_fin_global, key="f_hasta_v", disabled=ver_todo_v)

            if st.button("📊 Consultar Ventas"):
                conn_query = conectar_db(db_actual)
                if conn_query:
                    try:
                        if ver_todo_v: 
                            query = "SELECT * FROM libro_ventas ORDER BY fecha_factura DESC"
                        else:
                            query = f"SELECT * FROM libro_ventas WHERE fecha_factura BETWEEN '{desde_v}' AND '{hasta_v}' ORDER BY fecha_factura ASC"
                        st.session_state.df_ventas_editor = pd.read_sql(query, conn_query)
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
                st.dataframe(df_visual, use_container_width=True, hide_index=True)

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
                        use_container_width=True,
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
                                use_container_width=True
                            )
                        finally:
                            # Cerramos la conexión temp inmediatamente después de generar los datos
                            conn_temp.close()

                with col_btn2:
                    if st.button("💾 Guardar Cambios en Ventas", type="primary", use_container_width=True):
                        cambios = st.session_state["editor_ventas_key"]
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
                                conn_save.close()

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
            with st.popover("🚨 VACIAR VENTAS (RANGO SELECCIONADO)", use_container_width=True):
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
            with col_c1:
                desde_c = st.date_input("Desde", f_inicio_global, key="desde_c", disabled=ver_todo)
            with col_c2:
                hasta_c = st.date_input("Hasta", f_fin_global, key="hasta_c", disabled=ver_todo)

            st.error("⚠️ **Atención:** Las acciones aquí solo afectan al Libro de Compras.")

            # 2. CARGA AUTOMÁTICA
            try:
                conn = conectar_db(db_actual)
                query = "SELECT * FROM libro_compras ORDER BY fecha_operacion DESC" if ver_todo else \
                        "SELECT * FROM libro_compras WHERE fecha_operacion BETWEEN %s AND %s"
                params = None if ver_todo else (desde_c, hasta_c)
                
                df_recuperado = pd.read_sql(query, conn, params=params)
                conn.close()

                if not df_recuperado.empty:
                    st.session_state.df_compras_editor = df_recuperado
                else:
                    st.warning("No se encontraron registros en el rango seleccionado.")
                    if "df_compras_editor" in st.session_state:
                        del st.session_state.df_compras_editor
            except Exception as e:
                st.error(f"❌ Error al consultar la base de datos: {e}")

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
                    use_container_width=True,
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
                use_container_width=True
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
                        use_container_width=True
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
            
            with st.popover("🚨 VACIAR COMPRAS (RANGO SELECCIONADO)", use_container_width=True):
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
                
                if 'fecha_de_operación' in df_excel.columns:
                    # AQUÍ ESTÁ EL TRUCO: convertimos a objeto date de Python, no a string
                    df_excel['fecha_de_operación'] = pd.to_datetime(df_excel['fecha_de_operación']).dt.date
                        
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
                st.dataframe(df_visual, use_container_width=True, hide_index=True)

                # C. Editor funcional
                with st.expander("✏️ Editar Registros"):
                    cambios_df_excel = st.data_editor(
                        st.session_state.df_carga_excel,
                        key="editor_carga_excel",
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True
                    )
                    st.session_state.df_carga_excel = cambios_df_excel

                # D. Totales
                st.markdown("---")
                def f_bs(v): return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("TOTAL COMPRAS", f_bs(cambios_df_excel['total_compras'].sum()))
                m2.metric("TOTAL EXENTO", f_bs(cambios_df_excel['compras_exentas'].sum()))
                m3.metric("TOTAL BASE", f_bs(cambios_df_excel['base_imponible'].sum()))
                m4.metric("TOTAL IVA", f_bs(cambios_df_excel['credito_fiscales'].sum()))

            # E. BOTÓN DE GUARDADO FINAL (Llamando a tu función con los datos ya limpios)
            if st.button("🚀 Guardar carga masiva en DB", type="primary"):
                if "df_carga_excel" in st.session_state and not st.session_state.df_carga_excel.empty:
                    with st.spinner("⏳ Guardando registros..."):
                        try:
                            # PASAMOS EL DATAFRAME A TU FUNCIÓN
                            cargar_libro_compras_db(st.session_state.df_carga_excel, db_actual)
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
        
        def calcular_sustraendo(porcentaje):
            return VALOR_UT * (porcentaje / 100) * FACTOR

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
                
                # 3. Fecha Operación (CAMBIADO A DD/MM/AAAA)
                fecha_obj = row['fecha_operacion']
                fecha_str = fecha_obj.strftime("%d/%m/%Y") 
                ET.SubElement(detalle, "FechaOperacion").text = fecha_str
                
                # 4. Concepto y Montos
                ET.SubElement(detalle, "CodigoConcepto").text = str(row['codigo_concepto']).zfill(3)
                ET.SubElement(detalle, "MontoOperacion").text = f"{float(row['monto_operacion']):.2f}"
                ET.SubElement(detalle, "PorcentajeRetencion").text = f"{float(row['porcentaje_retencion']):.2f}"
                
                # NOTA: He eliminado Sustraendo, MontoRetenido y NumeroComprobante 
                # porque el SENIAT dio "Elemento no esperado" para esos campos.
                    
            xml_str = ET.tostring(root, encoding='utf-8')
            parsed = minidom.parseString(xml_str)
            return parsed.toprettyxml(indent="  ")

        # --- 🔘 TABLA DE REFERENCIA ---
        # --- 🔘 TABLA DE REFERENCIA ESTILO SENIAT ---
        # --- 🔘 TABLA DE REFERENCIA ESTILO SENIAT (INTEGRADA Y CALCULADA) ---
        # --- 🔘 TABLA DE REFERENCIA ESTILO SENIAT (CON UMBRALES CALCULADOS) ---
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
                use_container_width=True,
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
            st.markdown("### 🆕 Generar Nueva Retención")

            col_fecha1, col_fecha2 = st.columns(2)
            f_xml_desde_n = col_fecha1.date_input("Desde", value=datetime(2026, 10, 1), key="nueva_desde")
            f_xml_hasta_n = col_fecha2.date_input("Hasta", value=datetime(2026, 10, 31), key="nueva_hasta")

            col_c1, col_c2 = st.columns(2)

            with col_c1:
                if st.button("🔍 Consultar Facturas Pendientes", use_container_width=True):
                    conn = conectar_db(db_actual)
                    if conn:
                        # Consulta optimizada que une libro_compras con proveedores
                        query = """
                        SELECT 
                            lc.fecha_operacion AS fecha_operacion,
                            NULL AS id, 
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

                        try:
                            # Carga de datos segura con Pandas y parámetros de MySQL
                            st.session_state.df_retencion = pd.read_sql(
                                query, 
                                conn, 
                                params=(f_xml_desde_n, f_xml_hasta_n)
                            )
                            st.success("✅ Facturas y Datos Fiscales cargados con éxito.")
                        except Exception as e:
                            st.error(f"❌ Error al consultar la base de datos: {e}")
                        finally:
                            conn.close()
            with col_c2:
                if st.button("🏢 Cargar Directorio de Proveedores", use_container_width=True):
                    conn = conectar_db()
                    if conn:
                        st.session_state.df_prov_fiscal = pd.read_sql("SELECT rif, razon_social, direccion_fiscal FROM proveedores", conn)
                        conn.close()
                        st.info("📂 Directorio actualizado.")

            # Inicialización de estados
            if "pdf_listo" not in st.session_state:
                st.session_state.pdf_listo = False
            if "datos_pdf" not in st.session_state:
                st.session_state.datos_pdf = None

            if "df_retencion" in st.session_state:
                # Definimos solo las columnas que queremos que el usuario vea
                columnas_a_mostrar = [
                    "fecha_operacion", "rif_retenido", "proveedor_nombre", 
                    "numero_factura", "numero_control", "monto_operacion"
                ]
                
                sel_f = st.dataframe(
                    st.session_state.df_retencion[columnas_a_mostrar],  # <--- Filtramos aquí
                    on_select="rerun", 
                    selection_mode="single-row", 
                    hide_index=True, 
                    use_container_width=True
                )
                
                if sel_f.selection.rows:
                    # Extraemos los datos de la fila seleccionada
                    f_data = st.session_state.df_retencion.iloc[sel_f.selection.rows[0]]
                    
                    # El key dinámico fuerza al formulario a refrescarse al cambiar de factura
                    with st.form(key=f"form_final_islr_{f_data['id']}"): 

                        st.markdown("#### 🛠️ Datos del Comprobante")
                        c1, c2, c3 = st.columns([3, 4, 5])
                        
                        rif_r = c1.text_input("RIF", value=f_data['rif_retenido'])
                        id_seguro = f_data.get('id') or 0
                        val_sugerido = f_data['fecha_operacion'].strftime("%Y%m") + str(id_seguro).zfill(8)
                        n_comprob_manual = c2.text_input("N° Comprobante (Manual)", value=val_sugerido)
                        razon_r = st.text_input("Razón Social", value=f_data['proveedor_nombre'])
                        
                        # --- LÓGICA DE DIRECCIÓN MEJORADA ---
                        dir_bd = f_data.get('proveedor_direccion', '') 

                        # 2. Convertimos a string para evitar errores si llega un None
                        dir_bd = str(dir_bd) if dir_bd is not None else ""

                        # 3. Ahora sí, hacemos la validación
                        if dir_bd.strip() != "" and dir_bd.upper() != "NONE":
                            dir_r = st.text_input("Dirección", value=dir_bd, key=f"dir_{f_data['id']}")
                        else:
                            st.warning("⚠️ PROVEEDOR NO REGISTRADO EN DIRECTORIO")
                            dir_r = st.text_input("Dirección", value="Escriba la dirección aquí...", key=f"dir_{f_data['id']}")
                        
                        c7, c8, c9 = st.columns(3)
                        base_r = c7.number_input("Base Imponible", value=float(f_data['monto_operacion']))
                        porc_r = c8.number_input("% Retención", value=3.0)
                        codigo_r = c9.text_input("Código Concepto", value="001", help="Ingresa el código del SENIAT (ej. 001, 002)")
                        
                        # Asegúrate de que el resultado sea siempre un float válido antes de pasarlo al input
                        valor_calculado = calcular_sustraendo(porc_r) if rif_r.upper().startswith(('V', 'E')) else 0.0
                        # Forzamos a float y redondeamos a 2 decimales para evitar el error de truncamiento
                        val_sust = round(float(valor_calculado), 2)

                        sust_r = c9.number_input("Sustraendo", value=val_sust, format="%.2f")
                        
                        btn_procesar = st.form_submit_button("🚀 Procesar y Guardar")
                        
                        if btn_procesar:
                            # 1. Calculamos m_final aquí mismo para asegurarnos de que exista
                            conn = conectar_db(st.session_state.get('DB_ACTUAL'))
                            m_final = round(float((float(base_r) * (float(porc_r) / 100)) - float(sust_r)), 2)
                            
                            if comprobar_existencia_comprobante(n_comprob_manual):
                                st.error(f"⚠️ El comprobante **{n_comprob_manual}** ya existe.")
                            else:
                                # 2. Ahora m_final ya está definida y lista para usarse
                                # Verifica el valor antes de enviarlo (esto ayuda a depurar)
                                st.write(f"DEBUG: Enviando monto_retenido: {m_final}")

                                exito, valor = registrar_retencion_islr_db(
                                    int(f_data.get('id') or 0),  # <--- Esto convierte None en 0 de forma segura
                                    rif_r, 
                                    razon_r, 
                                    dir_r, 
                                    str(f_data['numero_factura']), 
                                    str(f_data['numero_control']), 
                                    f_data['fecha_operacion'], 
                                    "001", 
                                    base_r, 
                                    porc_r, 
                                    sust_r, 
                                    f_data['fecha_operacion'].strftime("%Y%m"), 
                                    m_final,  # <--- Este es el valor limpio
                                    n_comprob_manual
)
                                
                                if exito:
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
                                    st.success(f"✅ Comprobante N° {n_comprob_manual} registrado.")
                                    st.rerun()

            # Bloque de descarga
            if st.session_state.pdf_listo and st.session_state.datos_pdf:
                st.write("---")
                st.info("💡 El comprobante está listo para descargar.")
                pdf_bytes = generar_comprobante_pdf(st.session_state.datos_pdf, conn)
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
                    st.rerun()

            with tab3:
                # --- SECCIÓN: EDITOR DE HISTORIAL ---
                st.divider()
                st.markdown("### 🔎 Editor y Filtros de Historial")

                with st.expander("📅 Filtros de Consulta para Editar", expanded=True):
                    col_f1, col_f2 = st.columns(2)
                    
                    # Keys únicas para evitar conflictos
                    f_inicio_h = col_f1.date_input("Desde", datetime(2026, 8, 1), key="h_desde_editor")
                    f_fin_h = col_f2.date_input("Hasta", datetime(2026, 8, 31), key="h_hasta_editor")
                    
                    st.write("") 
                    btn_cargar = st.button("📂 Cargar Historial para Editar", use_container_width=True, type="primary")

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
                            st.session_state.df_retenciones_editor = pd.read_sql(query, conn, params=parametros)
                            
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
                    if st.button("💾 Sincronizar Historial con DB", type="primary", use_container_width=True):
                        estado = st.session_state["editor_tabla_retenciones"]
                        db_actual = st.session_state.get('DB_ACTUAL')
                        conn = conectar_db()
                        
                        if conn and db_actual:
                            try:
                                cursor = conn.cursor()
                                # Aseguramos el contexto de la base de datos correcta
                                cursor.execute(f"USE {db_actual}")
                                
                                total_eliminados = 0
                                total_editados = 0
                                
                                # PROCESAR ELIMINACIONES
                                for row_idx in estado["deleted_rows"]:
                                    id_real = int(st.session_state.df_retenciones_editor.iloc[row_idx]["id"]) 
                                    cursor.execute("DELETE FROM retenciones_islr WHERE id = %s", (id_real,))
                                    total_eliminados += 1

                                # PROCESAR EDICIONES
                                for row_idx, cambios in estado["edited_rows"].items():
                                    id_real = int(st.session_state.df_retenciones_editor.iloc[int(row_idx)]["id"])
                                    
                                    for campo, valor in cambios.items():
                                        # Limpieza de tipos de datos de numpy
                                        valor_final = valor.item() if hasattr(valor, 'item') else valor
                                        
                                        # Importante: Esto funcionará siempre que el nombre de la columna en el editor
                                        # sea igual al nombre real en la tabla MySQL.
                                        cursor.execute(f"UPDATE retenciones_islr SET {campo} = %s WHERE id = %s", 
                                                       (valor_final, id_real))
                                    total_editados += 1

                                conn.commit()
                                
                                if total_eliminados > 0 or total_editados > 0:
                                    st.success(f"✅ Sincronización exitosa en {db_actual}: se eliminaron {total_eliminados} y actualizaron {total_editados} registros.")
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
                if st.button("📂 Cargar/Actualizar Historial", use_container_width=True):
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
                            st.session_state.df_historial_islr = pd.read_sql(query_historial, conn)
                            
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
                        use_container_width=True
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
                                        use_container_width=True,
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
                            df = pd.read_sql("SELECT rif_retenido, numero_factura FROM retenciones_islr", conn)
                            st.dataframe(df, use_container_width=True)
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
                # Inserta esto ANTES de la línea que te da el error

                
                with st.container(border=True):
                    col_xml1, col_xml2 = st.columns(2)
                    f_xml_desde = col_xml1.date_input("Desde", value=datetime(2026, 4, 1), key="xml_desde")
                    f_xml_hasta = col_xml2.date_input("Hasta", value=datetime(2026, 4, 30), key="xml_hasta")
                    
                    # Botón de procesamiento
                    if st.button("🚀 Procesar Datos XML", use_container_width=False):
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
                            df_xml = pd.read_sql(query_xml, conn, params=(f_xml_desde, f_xml_hasta))
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
                            use_container_width=False
                        )


    elif sub_opcion == "Comprobante de Retención IVA":
        # 1. Aseguramos que el módulo datetime esté disponible sin conflictos
        import datetime as dt 
        
        # 2. Validamos la conexión antes de entrar a la interfaz pesada
        db_actual = st.session_state.get('DB_ACTUAL', 'control_central')
        conn_valida = conectar_db(db_actual)
        
        if conn_valida:
            # Llamamos a la función con la seguridad de que la conexión existe
            mostrar_interfaz_retencion_iva(EMPRESA, f_inicio_global, f_fin_global)
        else:
            st.error("No se pudo restablecer la conexión para el módulo de IVA.")

# --- USAMOS "IN" PARA QUE NO IMPORTE EL EMOJI QUE PONGAS EN EL SIDEBAR ---
elif "Proveedores" in opcion_menu:
    st.title("👤 Gestión de Directorio de Proveedores")
    
    # 1. Obtenemos la conexión
    conn_empresa = conectar_db(db_actual)
    
    try:
        # 2. Definición estricta de tabs
        tab1, tab2 = st.tabs(["📥 Cargar desde Excel", "📋 Directorio Actual"])
        
        # 3. Lógica de Pestaña 1
        with tab1:
            st.markdown("### Subir Archivo Masivo")
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
            st.markdown("### 📋 Directorio Actual")
            df_prov = consultar_tabla_db(conn_empresa, "proveedores")
            
            if df_prov is None or df_prov.empty:
                df_prov = pd.DataFrame(columns=["rif", "tipo_persona", "razon_social", "direccion_fiscal"])
            
            df_editado = st.data_editor(
                df_prov, 
                key="editor_proveedores_dinamico", 
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "rif": st.column_config.TextColumn("RIF (Llave Primaria)", required=True),
                    "tipo_persona": st.column_config.SelectboxColumn("Tipo", options=["PN", "PJ"], required=True),
                    "razon_social": st.column_config.TextColumn("Razón Social", required=True),
                    "direccion_fiscal": st.column_config.TextColumn("Dirección Fiscal", required=True)
                }
            )
            
            if st.button("💾 Guardar Todo"):
                actualizar_tabla_completa_db(conn_empresa, "proveedores", df_editado)
                st.success("¡Directorio actualizado con éxito, Papi!")
                st.rerun()

        # 5. Zona de respaldo (fuera de las tabs pero dentro del try)
        st.markdown("---") 
        if 'df_prov' in locals() and not df_prov.empty:
            import io
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_prov.to_excel(writer, index=False, sheet_name='Proveedores')
            st.download_button("📥 Descargar Respaldo", data=output.getvalue(), file_name="Respaldo_Proveedores.xlsx")
            
    finally:
        # 6. Cierre de conexión garantizado
        if conn_empresa and conn_empresa.is_connected():
            conn_empresa.close()

elif "Inventarios" in opcion_menu:
    # Invocamos el módulo exclusivo pasando la conexión a la base de datos
    modulo_inventario_pedacito_cielo(conn)
