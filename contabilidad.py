# contabilidad.py
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
from sqlalchemy import create_engine,text
import warnings
import bcrypt
import time
import ssl
import pymysql.cursors
import streamlit.components.v1 as components
import fitz # PyMuPDF (asegúrate de tenerla instalada o usa pdf2image)
import google.generativeai as genai
import pdfplumber
import tempfile
import pytesseract
import cv2
import fitz  # PyMuPDF para manejar PDFs escaneados

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
                    password="W3Zkbr4E2trGCfoX",
                    database="control_central", # Conectamos primero a central para asegurarnos de poder crearla si falta
                    connect_timeout=20,
                    charset='utf8mb4',
                    ssl=ssl_context
                )
                with conn.cursor() as cursor_temp:
                    cursor_temp.execute(f"CREATE DATABASE IF NOT EXISTS `{db_a_usar}`;")
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
            password="W3Zkbr4E2trGCfoX",
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


def mostrar_plantilla_bienvenida():
    """Pantalla de bienvenida elegante y fluida tras iniciar sesión"""
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
        
        # Botón para entrar de inmediato sin esperas artificiales
        if st.button("🚀 Continuar al Sistema", type="primary", use_container_width=True):
            st.session_state['bienvenida_completada'] = True
            st.rerun()

def play_success_sound():
    # Inyectamos un pequeño reproductor HTML5 oculto que ejecuta el sonido mediante JS de forma independiente al ciclo de Streamlit
    sound_html = """
        <audio autoplay style="display:none;">
            <source src="https://www.myinstants.com/media/sounds/ding-sound-effect_1.mp3" type="audio/mp3">
        </audio>
    """
    components.html(sound_html, height=0, width=0)


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
                    
                    # 🔑 AQUÍ ESTABA EL DETALLE: Guardamos la base de datos del cliente en la sesión
                    # (Asegúrate de que 'nombre_base_de_datos' coincida con la columna que retorna tu función verificar_usuario)
                    st.session_state['db_cliente'] = res.get('nombre_base_de_datos') 
                    
                    st.session_state['bienvenida_completada'] = False
                    
                    st.rerun()
                else:
                    st.error("❌ Credenciales incorrectas")
            
            st.markdown('</div>', unsafe_allow_html=True)


