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
            
            # --- DIAGNÓSTICO TEMPORAL (Puedes quitarlo luego) ---
            st.write("Datos encontrados en BD:", user_data)
            # --------------------------------------------------
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




with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2645/2645328.png", width=100)
    st.header("Panel de Auditoría")

    st.markdown("---")
    if st.button("🚪 Cerrar Sesión"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    # --- Navegación ---
    user_rol = str(st.session_state.get('rol', 'admin')).strip().lower()
    if user_rol == 'admin':
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

        # Conexión para la barra lateral en TiDB Cloud
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

                # CONSULTA CON JOIN: Vinculamos clientes con usuarios para traer el propietario
                query_join = """
                    SELECT c.id, c.nombre_empresa, c.db_nombre, u.usuario as nombre_usuario, u.rol as rol_usuario 
                    FROM clientes c
                    LEFT JOIN usuarios u ON (c.id = u.cliente_id OR c.db_nombre = u.db_nombre)
                """
                
                if user_rol != 'admin':
                    c_id = st.session_state.get('cliente_id')
                    if c_id:
                        query_join += f" WHERE c.id = {c_id}"

                df_sidebar = pd.read_sql(query_join, conn_sidebar)

            except Exception as e:
                st.error(f"❌ Error de conexión en la barra lateral: {e}")
            finally:
                try:
                    if conn_sidebar and hasattr(conn_sidebar, 'close'):
                        conn_sidebar.close()
                except:
                    pass
        else:
            st.error("❌ No se pudo conectar a la base de datos central.")
            st.stop()

        if not df_sidebar.empty:
            df_sidebar = df_sidebar.fillna("")
            
            # Selector de Empresa con soporte masivo
            nombres_empresas = df_sidebar['nombre_empresa'].tolist()
            empresa_previa = st.session_state.get('CLIENTE_NOMBRE')
            indice_inicial = 0
            if empresa_previa in nombres_empresas:
                indice_inicial = nombres_empresas.index(empresa_previa)

            seleccion = st.selectbox(
                "Seleccione Empresa", 
                nombres_empresas, 
                index=indice_inicial,
                key="selector_empresa"
            )
            
            if not seleccion:
                st.warning("⚠️ Por favor, seleccione una empresa válida.")
                st.stop()
                
            empresa_filtrada = df_sidebar[df_sidebar['nombre_empresa'] == seleccion]
            if empresa_filtrada.empty:
                st.error("❌ No se encontró la empresa seleccionada en los registros.")
                st.stop()
                
            datos_sel = empresa_filtrada.iloc[0]
            db_raw = datos_sel['db_nombre']
            usuario_asignado = datos_sel['nombre_usuario'] if 'nombre_usuario' in datos_sel and datos_sel['nombre_usuario'] else "No asignado"
            
            if pd.isna(db_raw) or not db_raw:
                st.error(f"⚠️ La empresa '{seleccion}' no tiene asignada una base de datos válida.")
                st.stop()
                
            DB_ACTUAL = str(db_raw).strip()
            st.session_state['DB_ACTUAL'] = DB_ACTUAL
            st.session_state['CLIENTE_NOMBRE'] = seleccion
            st.session_state['cliente_id_seleccionado'] = int(datos_sel['id'])
            
            # Mostramos en pantalla la empresa y el usuario vinculado dinámicamente
            st.write(f"Empresa seleccionada: '{str(seleccion).upper()}'")
            st.info(f"👤 **Usuario Propietario:** {str(usuario_asignado).capitalize()}")
            
            st.subheader("Módulos")
            modulos_disponibles = [
                "🏠 Inicio", "📂 Plan de Cuentas", "📝 Asientos Contables", 
                "📖 Mayor Analítico", "📊 Estados Financieros", "📚 Libros Fiscales", "👤 Proveedores"
            ]

            empresa_en_mayusculas = seleccion.upper()
            if "PEDACITO" in empresa_en_mayusculas and "CLIELO" in empresa_en_mayusculas:
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
            
            # --- BLOQUE DE FILTROS DE FECHA ---
            st.divider()
            st.subheader("📅 Período de Consulta")

            # Diccionario global de meses
            dic_meses = {
                "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
                "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
                "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
            }
            meses_lista = list(dic_meses.keys())

            col_anio, col_mes = st.columns(2)
            col_anio.number_input("Año", step=1, min_value=2020, max_value=2030, key="año_seleccionado_contabilidad")
            col_mes.selectbox("Mes", meses_lista, key="mes_seleccionado_contabilidad")

        else:
            st.error("⚠️ No se pudieron cargar las empresas desde TiDB Cloud. Verifica que la tabla 'clientes' exista en el esquema central.")
            st.stop()
