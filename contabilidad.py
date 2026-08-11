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
                    # Forzamos el uso del esquema central en TiDB Cloud donde están las 500 empresas
                    cursor_tmp.execute("USE control_central;")
                except Exception:
                    pass 
                cursor_tmp.close()

                # Definimos las consultas asegurando la lectura masiva
                # Definimos las consultas asegurando la lectura masiva
                queries_a_probar = [
                    "SELECT id, nombre_empresa, db_nombre FROM control_central.clientes",
                    "SELECT id, nombre_empresa, db_nombre FROM clientes"
                ]
                
                for q in queries_a_probar:
                    try:
                        q_final = q
                        if user_rol != 'admin':
                            # Usamos cliente_id de la tabla usuarios o hacemos un JOIN directo para mayor precisión
                            c_id = st.session_state.get('cliente_id')
                            user_db_nombre = st.session_state.get('db_nombre_usuario') # O filtramos directo por ID de la tabla clientes
                            
                            if c_id:
                                q_final = f"{q} WHERE id = {c_id}"
                        
                        df_sidebar = pd.read_sql(q_final, conn_sidebar)
                        
                        # Si es cliente y la consulta anterior por ID de clientes falló o vino vacía, 
                        # filtramos el dataframe global usando el db_nombre asignado en la sesión/tabla usuarios
                        if user_rol != 'admin' and df_sidebar.empty:
                            q_fallback = q
                            df_all = pd.read_sql(q_fallback, conn_sidebar)
                            db_asignada = st.session_state.get('db_a_conectar')
                            if not db_asignada and 'db_nombre' in st.session_state:
                                db_asignada = st.session_state.get('db_nombre')
                            
                            if db_asignada and not df_all.empty:
                                df_sidebar = df_all[df_all['db_nombre'] == db_asignada]

                        if not df_sidebar.empty:
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
                
            st.write(f"Empresa seleccionada: '{str(seleccion).upper()}'")
            
            empresa_filtrada = df_sidebar[df_sidebar['nombre_empresa'] == seleccion]
            if empresa_filtrada.empty:
                st.error("❌ No se encontró la empresa seleccionada en los registros.")
                st.stop()
                
            datos_sel = empresa_filtrada.iloc[0]
            db_raw = datos_sel['db_nombre']
            
            if pd.isna(db_raw) or not db_raw:
                st.error(f"⚠️ La empresa '{seleccion}' no tiene asignada una base de datos válida.")
                st.stop()
                
            DB_ACTUAL = str(db_raw).strip()
            st.session_state['DB_ACTUAL'] = DB_ACTUAL
            st.session_state['CLIENTE_NOMBRE'] = seleccion
            st.session_state['cliente_id_seleccionado'] = int(datos_sel['id'])
            
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

            col_anio, col_mes = st.columns(2)
            col_anio.number_input("Año", step=1, min_value=2020, max_value=2030, key="año_seleccionado_contabilidad")
            col_mes.selectbox("Mes", meses_lista, key="mes_seleccionado_contabilidad")

        else:
            st.error("⚠️ No se pudieron cargar las empresas desde TiDB Cloud. Verifica que la tabla 'clientes' exista en el esquema central.")
            st.stop()
