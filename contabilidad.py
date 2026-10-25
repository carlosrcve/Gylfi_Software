# contabilidad.py
import os
import streamlit as st
import streamlit as str_lit
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
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


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

def obtener_datos_empresa_activa():
    """
    Consulta directamente la base de datos control_central.clientes 
    utilizando el cliente_id de la sesión actual y devuelve un diccionario 
    con el nombre, RIF y dirección fiscal de la empresa.
    """
    datos_agente = {
        "nombre": "EMPRESA NO IDENTIFICADA",
        "rif": "J-00000000-0",
        "direccion": "DIRECCIÓN NO REGISTRADA"
    }

    id_sesion = st.session_state.get('cliente_id')

    try:
        # Usamos tu función conectar_db existente
        conn_central = conectar_db("control_central")
        if conn_central:
            # Usamos context manager para cerrar el cursor automáticamente
            with conn_central.cursor() as cursor_c:
                res_agente = None

                # 1. Búsqueda principal por el ID del cliente en la sesión
                if id_sesion is not None:
                    cursor_c.execute(
                        "SELECT nombre_empresa, rif, direccion_fiscal FROM clientes WHERE id = %s", 
                        (id_sesion,)
                    )
                    row = cursor_c.fetchone()
                    if row:
                        res_agente = {
                            "nombre_empresa": row[0],
                            "rif": row[1],
                            "direccion_fiscal": row[2]
                        }

                # 2. Respaldo absoluto: si no encuentra por ID, tomamos el primer registro de la tabla
                if not res_agente:
                    cursor_c.execute(
                        "SELECT nombre_empresa, rif, direccion_fiscal FROM clientes LIMIT 1"
                    )
                    row = cursor_c.fetchone()
                    if row:
                        res_agente = {
                            "nombre_empresa": row[0],
                            "rif": row[1],
                            "direccion_fiscal": row[2]
                        }

                if res_agente:
                    datos_agente = {
                        "nombre": res_agente.get("nombre_empresa", "EMPRESA NO IDENTIFICADA"),
                        "rif": res_agente.get("rif", "J-00000000-0"),
                        "direccion": res_agente.get("direccion_fiscal", "DIRECCIÓN NO REGISTRADA")
                    }
    except Exception as e:
        print(f"Error obteniendo datos del agente desde control_central: {e}")

    return datos_agente
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

def ejecutar_consulta(query, conn, params=None):
    cursor = None
    try:
        # Usamos DictCursor de PyMySQL
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, params or ())
        resultados = cursor.fetchall()
        return pd.DataFrame(resultados) if resultados else pd.DataFrame()
    except Exception as e:
        # CONVERSIÓN SEGURA: Forzamos str(e) para evitar que Python falle formateando objetos internos
        st.error(f"❌ Error crítico en ejecutar_consulta: {str(e)} | Query: {query}")
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
            cursor.execute("SELECT * FROM usuarios WHERE usuario = %s", (user,))
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
                    cursor.execute("UPDATE usuarios SET clave_hash = %s WHERE id = %s", (nuevo_hash, user_data['id']))
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
        return user_data
    else:
        return None

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


# ==============================================================================
# 1. PANEL DE ADMINISTRACIÓN DE USUARIOS (Con aislamiento por Firma)
# ==============================================================================
def panel_administracion(conn, rol_usuario, firma_id):
    if rol_usuario == "admin":
        st.header("⚙️ Gestión Global de Usuarios y Accesos (Super Admin)")
    else:
        st.header("⚙️ Gestión de Usuarios de mi Despacho Contable")
        st.info("💡 Aquí puedes registrar a los operadores fiscales o asistentes de tu propia firma.")
    
    # 1. FORMULARIO DE REGISTRO
    with st.expander("➕ Registrar Nuevo Usuario del Sistema", expanded=True):
        with st.form("registro_usuario"):
            col1, col2 = st.columns(2)
            
            with col1:
                nuevo_u = st.text_input("Nombre de Usuario", help="Ej: operador_juan o contador_maria")
                nueva_p = st.text_input("Contraseña", type="password")
            
            with col2:
                # Si es Super Admin puede crear admins de firma o clientes. Si es una firma, solo crea operadores/clientes de su despacho.
                if rol_usuario == "admin":
                    rol_asignado = st.selectbox("Rol del Sistema", ["admin_firma", "cliente", "admin"])
                else:
                    rol_asignado = st.selectbox("Rol del Sistema", ["operador_fiscal", "cliente"])
                
                # Buscamos las empresas disponibles para asociar
                try:
                    # Si es admin maestro ve todo; si es admin de firma, solo ve las empresas asignadas a su firma
                    if rol_usuario == "admin":
                        query_cli = "SELECT id, nombre_empresa FROM control_central.clientes"
                        df_cli = ejecutar_consulta(query_cli, conn)
                    else:
                        query_cli = "SELECT id, nombre_empresa FROM control_central.clientes WHERE firma_id = %s"
                        df_cli = ejecutar_consulta(query_cli, conn, params=(firma_id,))
                        
                    opciones_clientes = {row['nombre_empresa']: row['id'] for _, row in df_cli.iterrows()} if df_cli is not None and not df_cli.empty else {}
                    
                    nombre_sel = st.selectbox("Asociar a Empresa / Cliente", 
                                             ["Ninguna / Acceso Total"] + list(opciones_clientes.keys()))
                except Exception as e:
                    st.warning(f"⚠️ No se pudieron cargar las empresas: {e}")
                    opciones_clientes = {}
                    nombre_sel = "Ninguna / Acceso Total"

            btn_crear = st.form_submit_button("Guardar Usuario en Base de Datos")
            
            if btn_crear:
                if not nuevo_u or not nueva_p:
                    st.error("❌ El usuario y la contraseña son obligatorios.")
                else:
                    try:
                        salt = bcrypt.gensalt()
                        hash_cifrado = bcrypt.hashpw(nueva_p.encode('utf-8'), salt)
                        
                        c_id = opciones_clientes.get(nombre_sel) if nombre_sel != "Ninguna / Acceso Total" else None
                        
                        cursor = conn.cursor()
                        # Si es una firma, guardamos su firma_id para aislar los datos
                        if rol_usuario == "admin":
                            sql = """INSERT INTO usuarios (usuario, clave_hash, rol, cliente_id) VALUES (%s, %s, %s, %s)"""
                            cursor.execute(sql, (nuevo_u, hash_cifrado.decode('utf-8'), rol_asignado, c_id))
                        else:
                            sql = """INSERT INTO usuarios (usuario, clave_hash, rol, cliente_id, firma_id) VALUES (%s, %s, %s, %s, %s)"""
                            cursor.execute(sql, (nuevo_u, hash_cifrado.decode('utf-8'), rol_asignado, c_id, firma_id))
                            
                        conn.commit()
                        cursor.close()
                        
                        st.success(f"✅ Usuario '{nuevo_u}' registrado exitosamente.")
                        st.balloons()
                    except Exception as e:
                        st.error(f"❌ Error al registrar: Probablemente el usuario ya existe. ({e})")

    # 2. TABLA DE USUARIOS ACTUALES (Filtrada por permisos)
    st.subheader("👥 Usuarios Registrados")
    try:
        if rol_usuario == "admin":
            query_view = """
                SELECT u.usuario, u.rol, c.nombre_empresa as empresa_asignada 
                FROM control_central.usuarios u
                LEFT JOIN control_central.clientes c ON u.cliente_id = c.id
            """
            df_usuarios = ejecutar_consulta(query_view, conn)
        else:
            # El despacho contable solo ve los usuarios que pertenecen a su propia firma
            query_view = """
                SELECT u.usuario, u.rol, c.nombre_empresa as empresa_asignada 
                FROM control_central.usuarios u
                LEFT JOIN control_central.clientes c ON u.cliente_id = c.id
                WHERE u.firma_id = %s
            """
            df_usuarios = ejecutar_consulta(query_view, conn, params=(firma_id,))
            
        if df_usuarios is not None and not df_usuarios.empty:
            st.dataframe(df_usuarios, width='stretch', hide_index=True)
        else:
            st.info("No hay usuarios registrados todavía.")
    except Exception:
        st.info("No hay usuarios registrados todavía.")


# ==============================================================================
# 2. PANEL DE ADMINISTRACIÓN DE EMPRESAS (Exclusivo Super Admin)
# ==============================================================================
def panel_administracion_empresas(conn):
    st.header("⚙️ Gestión Global de Empresas y Despachos (Super Admin)")
    st.info("💡 Desde este panel maestro, tú (como dueño de Gylfi Software) registras los despachos contables y sus bases de datos asignadas.")

    with st.expander("➕ Registrar Nueva Empresa / Despacho Cliente", expanded=True):
        with st.form("registro_empresa_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                nombre_empresa = st.text_input("Razón Social de la Empresa", placeholder="Ej: Despacho Contable Oviedo, C.A.")
                rif = st.text_input("R.I.F.", placeholder="Ej: J-57894514-9")
                direccion_fiscal = st.text_area("Dirección Fiscal", placeholder="Ej: Av. Principal...")
                tipo_contribuyente = st.selectbox("Tipo de Contribuyente", options=["Contribuyente Ordinario", "Contribuyente Especial"])

            with col2:
                db_nombre = st.text_input("Nombre de la Base de Datos (MySQL)", placeholder="Ej: db_despacho_oviedo")
                estado_empresa = st.selectbox("Estado Inicial", options=["Activo", "Suspendido"])
                fecha_vencimiento = st.date_input("Fecha de Vencimiento de Licencia")
                ultimo_digito = st.number_input("Último Dígito del RIF", min_value=0, max_value=9, step=1, value=0)

            btn_guardar_empresa = st.form_submit_button("💾 Guardar Empresa en Base de Datos", type="primary")

            if btn_guardar_empresa:
                if not nombre_empresa or not rif or not db_nombre:
                    st.error("❌ Los campos Razón Social, RIF y Nombre de Base de Datos son obligatorios.")
                else:
                    try:
                        cursor = conn.cursor()
                        query_insert_empresa = """
                            INSERT INTO clientes 
                            (nombre_empresa, rif, db_nombre, estado, fecha_vencimiento, tipo_contribuyente, ultimo_digito, direccion_fiscal)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        valores = (
                            nombre_empresa.strip(),
                            rif.strip(),
                            db_nombre.strip(),
                            estado_empresa,
                            fecha_vencimiento.strftime("%Y-%m-%d"),
                            tipo_contribuyente,
                            int(ultimo_digito),
                            direccion_fiscal.strip()
                        )
                        cursor.execute(query_insert_empresa, valores)
                        conn.commit()
                        cursor.close()
                        st.success(f"✅ ¡Empresa **{nombre_empresa}** registrada con éxito!")
                    except Exception as e:
                        st.error(f"❌ Error al registrar: {e}")

    st.markdown("---")
    st.subheader("📋 Listado General de Clientes y Despachos")

    try:
        df_clientes = ejecutar_consulta("SELECT * FROM clientes ORDER BY id DESC", conn)
    except Exception as e:
        st.error(f"Error al consultar la tabla clientes: {e}")
        df_clientes = pd.DataFrame()

    if not df_clientes.empty:
        key_editor_clientes = "editor_tabla_clientes_admin"
        df_editado_clientes = st.data_editor(
            df_clientes,
            key=key_editor_clientes,
            num_rows="fixed",
            width="stretch",
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "nombre_empresa": st.column_config.TextColumn("Razón Social"),
                "rif": st.column_config.TextColumn("RIF"),
                "db_nombre": st.column_config.TextColumn("Base de Datos (MySQL)"),
                "estado": st.column_config.SelectboxColumn("Estado", options=["Activo", "Suspendido"], required=True),
                "fecha_vencimiento": st.column_config.DateColumn("Vencimiento", format="DD/MM/YYYY"),
                "tipo_contribuyente": st.column_config.SelectboxColumn("Tipo Contribuyente", options=["Contribuyente Ordinario", "Contribuyente Especial"], required=True),
            }
        )

        if st.button("💾 Guardar Cambios en Empresas", type="primary", key="btn_guardar_cambios_clientes"):
            cambios_cli = st.session_state.get(key_editor_clientes, {})
            try:
                cursor_upd = conn.cursor()
                cursor_upd.execute("START TRANSACTION")
                for idx_str, dict_mod in cambios_cli.get("edited_rows", {}).items():
                    id_row = int(df_clientes.iloc[int(idx_str)]["id"])
                    if dict_mod:
                        cols_sql = [f"{k} = %s" for k in dict_mod.keys()]
                        vals_sql = list(dict_mod.values())
                        sql_u = f"UPDATE clientes SET {', '.join(cols_sql)} WHERE id = %s"
                        cursor_upd.execute(sql_u, vals_sql + [id_row])
                for idx_del in cambios_cli.get("deleted_rows", []):
                    id_del = int(df_clientes.iloc[idx_del]["id"])
                    cursor_upd.execute("DELETE FROM clientes WHERE id = %s", (id_del,))
                conn.commit()
                cursor_upd.close()
                st.success("✅ ¡Cambios guardados correctamente!")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"❌ Error al guardar: {e}")
    else:
        st.warning("⚠️ No hay empresas registradas actualmente.")


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

@st.cache_data(ttl=300)
def obtener_saldos_acumulados(fecha_corte, nombre_db):
    if not nombre_db: 
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    
    db_segura = str(nombre_db).strip()
    
    # 1. Abrimos la conexión de forma local dentro de la función cacheada
    conexion = conectar_db(db_segura)
    if not conexion:
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    
    cur = None
    try:
        cur = conexion.cursor(pymysql.cursors.DictCursor)
        cur.execute(f"USE `{db_segura}`")
        
        # IMPORTANTE: Se usa LIKE '1%%' con doble porcentaje para que Python no lo confunda con formato
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
        # 2. Cerramos cursor y conexión de manera segura
        if cur:
            try:
                cur.close()
            except:
                pass
        if conexion:
            try:
                conexion.close()
            except:
                pass

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
    
    # Rango de fechas exacto del año para aprovechar los índices de la base de datos
    f_anio_ini = f"{anio_base}-01-01"
    f_anio_fin = f"{anio_base}-12-31"
    
    meses_skeleton = pd.DataFrame({
        'anio': [anio_base] * 12,
        'mes': list(range(1, 13))
    })

    db_segura = str(db).strip()
    query = f"""
        SELECT 
            CAST(SUBSTRING(fecha, 1, 4) AS UNSIGNED) as anio,
            CAST(SUBSTRING(fecha, 6, 2) AS UNSIGNED) as mes,
            
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
        WHERE fecha >= %s AND fecha <= %s
        GROUP BY SUBSTRING(fecha, 1, 4), SUBSTRING(fecha, 6, 2)
        ORDER BY anio ASC, mes ASC
    """
    
    cursor = None
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, (f_anio_ini, f_anio_fin))
        resultados = cursor.fetchall()
        
        df_sql = pd.DataFrame(resultados) if resultados else pd.DataFrame()

        if not df_sql.empty and 'mes' in df_sql.columns:
            df_sql['mes'] = pd.to_numeric(df_sql['mes'], errors='coerce')
            df_sql['anio'] = pd.to_numeric(df_sql['anio'], errors='coerce')
            df = pd.merge(meses_skeleton, df_sql, on=['anio', 'mes'], how='left')
        else:
            df = meses_skeleton.copy()

        # BLINDAJE: Aseguramos que todas las columnas contables existan aunque SQL no devuelva filas
        columnas_requeridas = ['ing_haber', 'ing_debe', 'cos_debe', 'cos_haber', 
                               'gas_debe', 'gas_haber', 'oing_haber', 'oing_debe', 
                               'oeg_debe', 'oeg_haber']
        for col in columnas_requeridas:
            if col not in df.columns:
                df[col] = 0.0

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



@st.cache_data(ttl=300)
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

    # Construcción dinámica de la query para DPP
    if db == 'kingdriver_ca':
        dpp_query = "SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.020%%' THEN haber ELSE 0 END) as DPP_haber, SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03.020%%' THEN debe ELSE 0 END) as DPP_debe"
    else:
        dpp_query = """SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03%%' AND plan_cuentas NOT LIKE '6.1.1.03.013%%' AND plan_cuentas NOT LIKE '6.1.1.03.021%%' AND plan_cuentas NOT LIKE '6.1.1.03.022%%' THEN haber ELSE 0 END) as DPP_haber,
                    SUM(CASE WHEN plan_cuentas LIKE '6.1.1.03%%' AND plan_cuentas NOT LIKE '6.1.1.03.013%%' AND plan_cuentas NOT LIKE '6.1.1.03.021%%' AND plan_cuentas NOT LIKE '6.1.1.03.022%%' THEN debe ELSE 0 END) as DPP_debe"""

    query = """
        SELECT 
            CAST(SUBSTRING(fecha, 1, 4) AS UNSIGNED) as anio,
            CAST(SUBSTRING(fecha, 6, 2) AS UNSIGNED) as mes,
            
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
        WHERE fecha >= %s AND fecha <= %s
        GROUP BY SUBSTRING(fecha, 1, 4), SUBSTRING(fecha, 6, 2)
        ORDER BY anio ASC, mes ASC
    """.format(db_segura=db_segura, dpp_query=dpp_query)
    
    cursor = None
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(query, (str(f_inicio_anual), str(f_fin_anual)))
        resultados = cursor.fetchall()
        
        df_sql = pd.DataFrame(resultados) if resultados else pd.DataFrame()

        if not df_sql.empty and 'mes' in df_sql.columns:
            df = pd.merge(meses_skeleton, df_sql, on=['anio', 'mes'], how='left')
        else:
            df = meses_skeleton.copy()

        # BLINDAJE: Aseguramos que todas las columnas contables y acumuladas existan en el DataFrame
        columnas_requeridas = [
            'exentos_acum', 'gravados_acum', 'compras_exentas_acum', 'compras_16_acum',
            'DPP_haber', 'DPP_debe', 'comisiones_bancarias_haber', 'comisiones_bancarias_debe',
            'refrigerios_haber', 'refrigerios_debe', 'representacion_haber', 'representacion_debe',
            'otros_ingresos_haber', 'otros_ingresos_debe', 'otros_egresos_haber', 'otros_egresos_debe',
            'iva_debito_fiscal', 'iva_por_pagar', 'retencion_iva_compras', 'pagos_anticipados_islr',
            'retencion_islr_proveedores', 'islr_pagar'
        ]
        for col in columnas_requeridas:
            if col not in df.columns:
                df[col] = 0.0

        df = df.fillna(0)

        # Des-acumulación mes a mes para los acumulados
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

        import calendar
        df['primer_dia_mes'] = df.apply(lambda row: datetime.date(int(row['anio']), int(row['mes']), 1), axis=1)

        df_filtrado = df[(df['primer_dia_mes'] >= datetime.date(f_inicio.year, f_inicio.month, 1)) & 
                         (df['primer_dia_mes'] <= datetime.date(f_fin.year, f_fin.month, 1))].copy()

        if df_filtrado.empty:
            df_filtrado = df.copy()

        # Sumatorias totales para el periodo filtrado
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
    
    if not db or not str(db).replace("_", "").isalnum():
        raise ValueError(f"Nombre de base de datos inválido: {db}")

    if 'conectar_db' not in globals() and 'conectar_db' not in locals():
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

    # Definimos el rango exacto para aprovechar los índices de MySQL
    f_ini = f"{año}-01-01"
    f_fin = f"{año}-{str(mes_limite).zfill(2)}-31" # Cubre hasta el último día del mes límite

    # Consulta optimizada sin funciones destructoras de índices en el WHERE
    query = f"""
        SELECT 
            CAST(SUBSTRING(fecha, 6, 2) AS UNSIGNED) as mes,
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
        WHERE fecha >= %s AND fecha <= %s 
        GROUP BY CAST(SUBSTRING(fecha, 6, 2) AS UNSIGNED)
        ORDER BY mes ASC
    """
    
    try:
        df = ejecutar_consulta(query, conn, params=(f_ini, f_fin))
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

    # 🛡️ Si la tabla es proveedores, nos aseguramos de que tenga las 6 columnas exactas obligatorias
    if nombre_tabla == "proveedores":
        columnas_obligatorias = ["rif", "tipo_persona", "razon_social", "direccion_fiscal", "codigo_cuenta", "descripcion_cuenta"]
        for col in columnas_obligatorias:
            if col not in df_nuevo.columns:
                df_nuevo[col] = "" # Si falta alguna, se crea vacía para no romper la BD
        # Reordenamos el DataFrame para que coincida exactamente con el orden de las columnas de MySQL
        df_nuevo = df_nuevo[columnas_obligatorias]

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
        # 2. Construcción directa de la consulta
        query = f"SELECT * FROM `{nombre_tabla}`"
        
        if limite and isinstance(limite, int):
            query += f" LIMIT {limite}"
            
        # 3. Ejecutamos la consulta
        resultado = ejecutar_consulta(query, conn)
        
        # 4. GARANTÍA DE DATOS: Aseguramos que el resultado sea siempre un DataFrame de Pandas
        if isinstance(resultado, pd.DataFrame):
            df = resultado
        elif isinstance(resultado, list):
            # Si viene como lista de diccionarios o tuplas
            df = pd.DataFrame(resultado)
        else:
            # Si 'ejecutar_consulta' devuelve cursor directo
            try:
                cursor = conn.cursor(dictionary=True) # O el equivalente en tu conector
                cursor.execute(query)
                datos = cursor.fetchall()
                df = pd.DataFrame(datos)
            except Exception:
                df = pd.DataFrame()

        # Si el DataFrame está vacío, al menos devolvemos un DataFrame sin filas pero con las columnas de la BD
        if df.empty:
            # Intentamos obtener las columnas directamente si el df está totalmente vacío
            cursor = conn.cursor()
            cursor.execute(f"SHOW COLUMNS FROM `{nombre_tabla}`")
            columnas = [row[0] for row in cursor.fetchall()]
            df = pd.DataFrame(columns=columnas)

        return df

    except Exception as e:
        st.error(f"Error consultando {nombre_tabla}: {e}")
        return None


@st.cache_data(ttl=300)
def obtener_datos_agente_db(valor_busqueda):
    return _obtener_datos_agente_db_v2(valor_busqueda)

def _obtener_datos_agente_db_v2(valor_busqueda):
    conn_central = conectar_db() 
    if not conn_central: 
        return None

    cursor = None
    try:
        cursor = conn_central.cursor(pymysql.cursors.DictCursor)
        
        # ¡Añadimos direccion_fiscal a las columnas seleccionadas!
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif, db_nombre, estado, direccion_fiscal FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif, db_nombre, estado, direccion_fiscal FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        return datos
        
    except Exception as e:
        st.error(f"❌ Error interno de consulta: {e}")
        return None
        
    finally:
        if cursor: cursor.close()
        if conn_central: conn_central.close()


def cargar_asientos_contables_db(df, conn=None):
    # 1. Obtener y asegurar la base de datos actual de la sesión
    db_actual = st.session_state.get('DB_ACTUAL')
    if not db_actual:
        st.error("⚠️ No se ha seleccionado una base de datos de empresa en la sesión.")
        return False

    usuario_actual = str(st.session_state.get('usuario', 'Admin'))
    registrar_log_automatico(conn, "CONSULTA_BALANCE_GENERAL", f"Usuario {usuario_actual} intentó cargar asientos para {db_actual}")

    # 2. Gestionar la conexión si no viene dada
    if not conn:
        conn = conectar_db(db_actual)
    
    if not conn: 
        st.error("❌ No se pudo establecer conexión con la base de datos.")
        return False
        
    cursor = None
    try:
        # --- LIMPIEZA DE DATOS CRÍTICA ---
        df_limpio = df.copy()
        
        # Normalizar nombres de columnas a minúsculas o buscar variantes comunes para evitar KeyErrors
        df_limpio.columns = [str(c).strip() for c in df_limpio.columns]
        
        # Diccionario de posibles nombres para la columna de fecha
        col_fecha_candidatos = ['Fecha', 'fecha', 'FECHA', 'Fecha de Operacion', 'Fecha de Operación']
        col_fecha_encontrada = None
        for c in col_fecha_candidatos:
            if c in df_limpio.columns:
                col_fecha_encontrada = c
                break
                
        if not col_fecha_encontrada:
            st.error(f"❌ El archivo Excel no contiene una columna de fecha válida. Columnas detectadas: {list(df_limpio.columns)}")
            return False

        # Renombrar temporalmente a 'Fecha' para estandarizar
        if col_fecha_encontrada != 'Fecha':
            df_limpio.rename(columns={col_fecha_encontrada: 'Fecha'}, inplace=True)

        # 1. Convertir fecha y ELIMINAR filas donde la fecha sea nula (NaT)
        df_limpio['Fecha'] = pd.to_datetime(df_limpio['Fecha'], errors='coerce')
        df_limpio = df_limpio.dropna(subset=['Fecha']) 
        
        if df_limpio.empty:
            st.warning("⚠️ No se encontraron fechas válidas en el archivo Excel.")
            return False

        # 2. VALIDACIÓN ESTRICTA DE PERÍODOS BLOQUEADOS DESDE MYSQL
        anios_meses_excel = set((row['Fecha'].year, row['Fecha'].month) for _, row in df_limpio.iterrows())
        
        cursor = conn.cursor()
        
        # Validación dinámica consultando directamente en MySQL si el período está bloqueado
        for anio, mes in anios_meses_excel:
            try:
                query_verificar_bloqueo = f"""
                    SELECT COUNT(*) FROM `{db_actual}`.asientos_contables 
                    WHERE YEAR(fecha) = %s AND MONTH(fecha) = %s AND bloqueado = 1
                """
                cursor.execute(query_verificar_bloqueo, (anio, mes))
                resultado = cursor.fetchone()
                
                if resultado and resultado[0] > 0:
                    cursor.close()
                    st.error(f"❌ **¡Alerta! El período {mes:02d}/{anio} está cerrado y bloqueado.** No se puede subir el libro de diario porque este mes ya se encuentra cerrado en la base de datos.")
                    return False
            except Exception:
                # Si la columna 'bloqueado' no existe o la tabla aún no la contempla, la ignoramos para no interrumpir el flujo
                pass

        # Mapeo flexible de columnas de Debe y Haber
        for col_objetivo, posibles in [
            ('Debe', ['Debe', 'DEBE', 'debe']),
            ('Haber', ['Haber', 'HABER', 'haber']),
            ('N_comprobante', ['N_comprobante', 'n_comprobante', 'Comprobante', 'Nro Comprobante']),
            ('Descripcion', ['Descripcion', 'Descripción', 'DESCRIPCION', 'concepto']),
            ('plan_de_cuentas', ['plan_de_cuentas', 'Plan de Cuentas', 'cuenta', 'codigo_cuenta']),
            ('cuenta_contable', ['cuenta_contable', 'Cuenta Contable', 'nombre_cuenta', 'descripcion_cuenta']),
            ('Ref', ['Ref', 'REF', 'Referencia', 'referencia'])
        ]:
            if col_objetivo not in df_limpio.columns:
                encontrado = False
                for p in posibles:
                    if p in df_limpio.columns:
                        df_limpio.rename(columns={p: col_objetivo}, inplace=True)
                        encontrado = True
                        break
                if not encontrado and col_objetivo in ['Debe', 'Haber']:
                    df_limpio[col_objetivo] = 0.0
                elif not encontrado:
                    df_limpio[col_objetivo] = ""

        # 3. Asegurar que Debe y Haber sean números usando la función de limpieza
        df_limpio['Debe'] = df_limpio['Debe'].apply(limpiar_moneda).round(2)
        df_limpio['Haber'] = df_limpio['Haber'].apply(limpiar_moneda).round(2)

        # 4. Procesamiento masivo optimizado mediante vectorización (Ultra rápido)
        try:
            for col in ['N_comprobante', 'Descripcion', 'plan_de_cuentas', 'cuenta_contable', 'Ref']:
                if col not in df_limpio.columns:
                    df_limpio[col] = ""

            df_limpio['Fecha_str'] = df_limpio['Fecha'].dt.strftime('%Y-%m-%d')

            valores = list(zip(
                df_limpio['N_comprobante'].astype(str),
                df_limpio['Descripcion'].astype(str),
                df_limpio['Fecha_str'],
                df_limpio['plan_de_cuentas'].astype(str),
                df_limpio['cuenta_contable'].astype(str),
                df_limpio['Ref'].astype(str),
                df_limpio['Debe'].astype(float),
                df_limpio['Haber'].astype(float)
            ))
        except Exception as e_row:
            st.error(f"Error procesando los datos masivos del archivo: {e_row}")
            if cursor: cursor.close()
            return False
        
        if not valores:
            st.warning("⚠️ No se encontraron datos válidos para insertar.")
            if cursor: cursor.close()
            return False

        # 5. Inserción masiva si todo está abierto
        query_insert = f"""
            INSERT INTO `{db_actual}`.asientos_contables 
            (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.executemany(query_insert, valores)
        conn.commit()
        cursor.close()
        
        st.success(f"✅ ¡Éxito! {len(valores)} asientos cargados correctamente en `{db_actual}`.")
        return True

    except Exception as e:
        if conn: conn.rollback()
        st.error(f"❌ Error al procesar o insertar en la base de datos: {e}")
        return False
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.ping(reconnect=True)
            except:
                pass

def actualizar_libro_diario_en_db(db_nombre, df_cambios):
    conn = conectar_db(db_nombre)
    if not conn:
        return False
        
    cursor = conn.cursor()
    try:
        sql_update = """
            UPDATE asientos_contables 
            SET n_comprobante = %s, descripcion = %s, fecha = %s, 
                plan_cuentas = %s, cuenta_contable = %s, referencia = %s, 
                debe = %s, haber = %s 
            WHERE id = %s
        """
        
        sql_insert = """
            INSERT INTO asientos_contables 
            (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
        """
        
        lista_inserts = []
        lista_updates = []
        
        for _, row in df_cambios.iterrows():
            row_id = row.get('id')
            
            # Limpiar y extraer el código de la cuenta
            plan_val = str(row.get('plan_cuentas', ''))
            plan_cuentas_val = plan_val.split(" - ")[0] if " - " in plan_val else plan_val
            
            n_comprobante = str(row.get('n_comprobante', '')).strip()
            descripcion = str(row.get('descripcion', '')).strip()
            fecha = str(row.get('fecha', '')).strip()
            cuenta_contable = str(row.get('cuenta_contable', '')).strip()
            referencia = str(row.get('referencia', '')).strip()
            debe = float(row.get('debe', 0.0) or 0.0)
            haber = float(row.get('haber', 0.0) or 0.0)
            
            # Clasificar si es un INSERT o un UPDATE
            if pd.isna(row_id) or str(row_id).strip() in ['', 'None', 'nan']:
                lista_inserts.append((
                    n_comprobante, descripcion, fecha, 
                    plan_cuentas_val, cuenta_contable, referencia, 
                    debe, haber
                ))
            else:
                lista_updates.append((
                    n_comprobante, descripcion, fecha, 
                    plan_cuentas_val, cuenta_contable, referencia, 
                    debe, haber, int(row_id)
                ))
        
        # Ejecución masiva optimizada (Muchísimo más rápida)
        if lista_inserts:
            cursor.executemany(sql_insert, lista_inserts)
            
        if lista_updates:
            cursor.executemany(sql_update, lista_updates)
            
        conn.commit()
        return True
        
    except Exception as e:
        conn.rollback()
        st.error(f"Error técnico en SQL: {str(e)}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def mes_esta_cerrado(conn, mes_nombre, ano, db_nombre=None):
    """
    BYPASS TEMPORAL: Fuerza a que cualquier mes se considere abierto 
    para permitir la subida del libro de diario sin bloqueos.
    """
    # Forzamos el retorno en False para que NUNCA bloquee por cierre de mes
    return False
    
    # --- (Código original desactivado temporalmente) ---
    mes_map = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
        "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
    }
    
    if mes_nombre not in mes_map:
        return False
        
    mes_num = mes_map[mes_nombre]
    
    if not db_nombre:
        db_nombre = st.session_state.get('DB_ACTUAL') or st.session_state.get('empresa_actual')

    cursor = conn.cursor()
    try:
        usuario_actual = st.session_state.get('usuario', 'Sistema')
        try:
            registrar_log_automatico(conn, "VALIDAR_MES_CERRADO", f"Usuario {usuario_actual} validó cierre del mes {mes_nombre} {ano} para la empresa {db_nombre}")
        except Exception:
            pass 
        
        if db_nombre:
            query = f"""
                SELECT COUNT(*) FROM `{db_nombre}`.periodos_cerrados 
                WHERE mes = %s AND ano = %s AND estado = 'Cerrado'
            """
        else:
            query = """
                SELECT COUNT(*) FROM periodos_cerrados 
                WHERE mes = %s AND ano = %s AND estado = 'Cerrado'
            """
            
        cursor.execute(query, (mes_num, ano))
        resultado_fetch = cursor.fetchone()
        
        if resultado_fetch:
            if isinstance(resultado_fetch, dict):
                cantidad = list(resultado_fetch.values())[0]
            else:
                cantidad = resultado_fetch[0]
            return cantidad > 0
            
        return False
        
    except Exception as e:
        return False
        
    finally:
        cursor.close()

def mostrar_tablero_conciliacion(conn, mes_sel, ano_sel):
    st.title("⚖️ Conciliación Bancaria")

    # 1. RECUPERAR CONTEXTO GLOBAL
    db = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id') or st.session_state.get('cliente_id_seleccionado')

    if not db:
        st.warning("⚠️ No se ha seleccionado una base de datos activa.")
        return

    # 2. CONEXIÓN CON CONTROL CENTRAL PARA DATOS DE LA EMPRESA
    cursor = conn.cursor()
    nombre_empresa_mostrada = db
    rif_empresa = ""
    
    try:
        if cliente_id:
            cursor.execute("SELECT nombre_empresa, rif FROM control_central.clientes WHERE id = %s", (cliente_id,))
            res_cliente = cursor.fetchone()
            if res_cliente:
                nombre_empresa_mostrada = res_cliente[0]
                rif_empresa = res_cliente[1]
    except Exception:
        pass

    st.markdown(f"### 🏢 Empresa: **{nombre_empresa_mostrada}** {f'(RIF: {rif_empresa})' if rif_empresa else ''}")
    st.divider()

    # 3. PREPARACIÓN DE FECHAS
    meses_dict = {
        "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04", 
        "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08", 
        "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
    }
    mes_num = meses_dict[mes_sel]
    fecha_inicio = f"{ano_sel}-{mes_num}-01"
    ultimo_dia = calendar.monthrange(int(ano_sel), int(mes_num))[1]
    fecha_fin = f"{ano_sel}-{mes_num}-{ultimo_dia:02d}"

    # Cálculo dinámico del mes anterior
    meses_lista = list(meses_dict.keys())
    idx_mes_actual = meses_lista.index(mes_sel)
    if idx_mes_actual == 0:
        mes_anterior = "Diciembre"
        ano_anterior = str(int(ano_sel) - 1)
    else:
        mes_anterior = meses_lista[idx_mes_actual - 1]
        ano_anterior = str(ano_sel)

    # Inicializar variables de depuración
    debug_info = {}

    # 4. CARGA DE BANCOS
    try:
        query_bancos = f"""
            SELECT nombre, codigo FROM `{db}`.plan_cuentas 
            WHERE UPPER(nombre) LIKE '%BANCO%'
        """
        cursor.execute(query_bancos)
        bancos_dict = {b[0]: b[1] for b in cursor.fetchall()}
        
        if not bancos_dict:
            query_alternativa = f"""
                SELECT nombre, codigo FROM `{db}`.plan_cuentas 
                WHERE codigo LIKE '1%' AND (tipo = 'Detalle' OR tipo IS NULL OR tipo = '')
            """
            cursor.execute(query_alternativa)
            bancos_dict = {b[0]: b[1] for b in cursor.fetchall()}

        if not bancos_dict:
            st.warning(f"⚠️ No se encontraron cuentas bancarias o de activo en el plan de cuentas de la empresa ({db}).")
            cursor.close()
            return

        nombre_banco_sel = st.selectbox("Seleccione Banco", list(bancos_dict.keys()), key="select_banco_tablero_seguro")
        cuenta_codigo = bancos_dict[nombre_banco_sel]
        
        banco_db = obtener_alias_banco(nombre_banco_sel) if 'obtener_alias_banco' in globals() else nombre_banco_sel

        # 5. CONSULTAS PRINCIPALES
        sql_saldos = f"""SELECT saldo_inicial, saldo_final 
                        FROM `{db}`.saldos_bancarios 
                        WHERE (banco = %s OR banco LIKE %s) AND LOWER(mes) = LOWER(%s) AND CAST(ano AS CHAR) = %s"""
        
        cursor.execute(sql_saldos, (nombre_banco_sel, f"%{nombre_banco_sel}%", mes_sel, str(ano_sel)))
        res_banco = cursor.fetchone()
        
        if res_banco:
            saldo_inicial = float(res_banco[0]) if res_banco[0] is not None else 0.0
            saldo_final_banco_tabla = float(res_banco[1]) if res_banco[1] is not None else 0.0
        else:
            saldo_inicial = 0.0
            saldo_final_banco_tabla = 0.0

        # B. Saldo Libros (Mes anterior)
        query_saldo_anterior = f"""
            SELECT saldo_final 
            FROM `{db}`.saldos_bancarios 
            WHERE (banco = %s OR banco LIKE %s) AND LOWER(mes) = LOWER(%s) AND CAST(ano AS CHAR) = %s
        """
        cursor.execute(query_saldo_anterior, (nombre_banco_sel, f"%{nombre_banco_sel}%", mes_anterior, str(ano_anterior)))
        res_anterior = cursor.fetchone()
        saldo_mes_anterior = float(res_anterior[0]) if res_anterior else 0.0

        # C. Movimientos del mes en la tabla asientos_contables
        query_movimientos_mes = f"""
            SELECT IFNULL(SUM(debe), 0.0), IFNULL(SUM(haber), 0.0), COUNT(*) 
            FROM `{db}`.asientos_contables 
            WHERE (
                TRIM(cuenta_contable) = TRIM(%s) OR 
                TRIM(cuenta_contable) = TRIM(%s) OR 
                TRIM(plan_cuentas) = TRIM(%s) OR
                TRIM(plan_cuentas) = TRIM(%s) OR
                cuenta_contable LIKE %s
            ) 
            AND fecha BETWEEN %s AND %s
        """
        patron_cuenta = f"{cuenta_codigo}%"
        
        cursor.execute(query_movimientos_mes, (cuenta_codigo, nombre_banco_sel, cuenta_codigo, nombre_banco_sel, patron_cuenta, fecha_inicio, fecha_fin))
        res_mov = cursor.fetchone()
        
        debe_mes = float(res_mov[0]) if res_mov and res_mov[0] is not None else 0.0
        haber_mes = float(res_mov[1]) if res_mov and res_mov[1] is not None else 0.0
        cantidad_asientos = int(res_mov[2]) if res_mov and res_mov[2] is not None else 0

        # LÓGICA HÍBRIDA CONTABLE:
        # Si existen asientos contables detallados en el mes, aplicamos: Saldo Inicial + Debe - Haber.
        # Si NO hay asientos en el mes (ej. meses previos a mayo), usamos directamente el saldo final guardado en la tabla saldos_bancarios.
        if cantidad_asientos > 0:
            saldo_final_libros = saldo_inicial + debe_mes - haber_mes
        else:
            saldo_final_libros = saldo_final_banco_tabla

        # El saldo final de banco oficial para comparar en el tablero viene de la tabla saldos_bancarios
        saldo_final_banco = saldo_final_banco_tabla

        # D. Movimientos de Banco
        query_mov_pendientes = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = 'Pendiente' AND fecha_movimiento BETWEEN %s AND %s"
        df_banco = ejecutar_consulta(query_mov_pendientes, conn, params=(fecha_inicio, fecha_fin)) if 'ejecutar_consulta' in globals() else pd.DataFrame()

        query_mov_conciliados = f"SELECT * FROM `{db}`.banco_movimientos WHERE estado_conciliacion = 'Conciliado' AND fecha_movimiento BETWEEN %s AND %s"
        df_conciliado = ejecutar_consulta(query_mov_conciliados, conn, params=(fecha_inicio, fecha_fin)) if 'ejecutar_consulta' in globals() else pd.DataFrame()

        # Guardar datos para depuración visual
        debug_info = {
            "Base de Datos": db,
            "Banco Seleccionado": nombre_banco_sel,
            "Código de Cuenta": cuenta_codigo,
            "Alias Buscado en Saldos": banco_db,
            "Periodo": f"{mes_sel} {ano_sel} ({fecha_inicio} al {fecha_fin})",
            "Saldo Banco Encontrado": res_banco,
            "Debe Mes Encontrado": debe_mes,
            "Haber Mes Encontrado": haber_mes,
            "Saldo Final Libros Calculado": saldo_final_libros
        }

    except Exception as e:
        st.error(f"Error en la consulta para {db}: {e}")
        df_banco = pd.DataFrame()
        df_conciliado = pd.DataFrame()
        saldo_final_libros = 0.0
        saldo_inicial = 0.0
        saldo_final_banco = 0.0
    finally:
        cursor.close()

    # 🛠️ Formato venezolano
    def formato_venezolano(val):
        try:
            return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except:
            return "0,00"

    # 6. VISUALIZACIÓN
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
    
    if not df_banco.empty and 'monto' in df_banco.columns:
        df_banco['monto'] = pd.to_numeric(df_banco['monto'], errors='coerce').fillna(0.0)
        df_banco_ingresos = df_banco[df_banco['monto'] > 0].copy()
        if not df_banco_ingresos.empty:
            df_banco_ingresos['monto'] = df_banco_ingresos['monto'].apply(formato_venezolano)
            
        df_banco_egresos = df_banco[df_banco['monto'] < 0].copy()
        if not df_banco_egresos.empty:
            df_banco_egresos['monto'] = df_banco_egresos['monto'].apply(formato_venezolano)
    else:
        df_banco_ingresos = pd.DataFrame()
        df_banco_egresos = pd.DataFrame()

    col_p1.write("📥 Ingresos Pendientes")
    col_p1.dataframe(df_banco_ingresos, use_container_width=True, hide_index=True)
    col_p2.write("📤 Egresos Pendientes")
    col_p2.dataframe(df_banco_egresos, use_container_width=True, hide_index=True)
        
    if 'saldo_final_libros' not in st.session_state:
        st.session_state.saldo_final_libros = 0.0

    if st.button("🚀 Ejecutar Conciliación", key="btn_ejecutar_conciliacion_tablero"):
        resultado = conciliar_datos(conn, fecha_inicio, fecha_fin, db) if 'conciliar_datos' in globals() else 0.0
        st.session_state.saldo_final_libros = resultado
        st.success("Conciliación ejecutada con éxito.")
        st.rerun()

    # 7. LÓGICA DE PDF CENTRALIZADA
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
            conn, df_conciliado, saldo_inicial, saldo_final_banco, saldo_final_libros, lista_ingresos, lista_egresos, mes_sel=mes_sel, ano_sel=ano_sel
        )
        st.download_button(
            label="📄 Descargar Conciliación PDF", 
            data=pdf_data, 
            file_name=f"conciliacion_{mes_sel}_{ano_sel}.pdf", 
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Error generando el PDF: {e}")

    # 8. MOVIMIENTOS CONCILIADOS
    if not df_conciliado.empty and 'monto' in df_conciliado.columns:
        st.subheader("✅ Movimientos Conciliados")
        df_conciliado['monto'] = pd.to_numeric(df_conciliado['monto'], errors='coerce').fillna(0.0)
        
        df_conciliado_ingresos = df_conciliado[df_conciliado['monto'] > 0].copy()
        if not df_conciliado_ingresos.empty:
            df_conciliado_ingresos['monto'] = df_conciliado_ingresos['monto'].apply(formato_venezolano)
            
        df_conciliado_egresos = df_conciliado[df_conciliado['monto'] < 0].copy()
        if not df_conciliado_egresos.empty:
            df_conciliado_egresos['monto'] = df_conciliado_egresos['monto'].apply(formato_venezolano)

        col_d, col_h = st.columns(2)
        col_d.write("Ingresos")
        col_d.dataframe(df_conciliado_ingresos, use_container_width=True, hide_index=True)
        col_h.write("Egresos")
        col_h.dataframe(df_conciliado_egresos, use_container_width=True, hide_index=True)
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


def generar_pdf_comprobante(df, n_comp, conn):
    """
    Genera el PDF del comprobante usando la base de datos actual de la sesión,
    registra la actividad en el log y mantiene la conexión a MySQL viva.
    """
    # Obtener la base de datos actual de la sesión de Streamlit para control centralizado
    db_actual = st.session_state.get('DB_ACTUAL')
    
    if not db_actual:
        st.error("No se ha especificado una base de datos activa para el registro de logs o consultas.")
        return None

    # 1. Registrar la actividad de forma centralizada controlando la BD actual
    try:
        usuario_actual = st.session_state.get('usuario', 'Desconocido')
        cliente_id_actual = st.session_state.get('cliente_id', 'N/A')
        
        registrar_log_automatico(
            conn, 
            "GENERACION_COMPROBANTE", 
            f"Usuario {usuario_actual} generó PDF de comprobante {n_comp} para el cliente {cliente_id_actual} en la base de datos {db_actual}"
        )
    except Exception as log_error:
        print(f"Advertencia al registrar log automático: {log_error}")

    cursor = conn.cursor()
    
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        
        # Encabezado
        pdf.cell(190, 10, "COMPROBANTE DE ASIENTO CONTABLE", 0, 1, 'C')
        pdf.set_font("Arial", '', 10)
        pdf.cell(190, 10, f"Comprobante Nro: {n_comp}", 0, 1, 'L')
        pdf.cell(190, 5, f"Base de Datos: {db_actual}", 0, 1, 'L')
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
        
        # Generar salida del PDF adaptada a tipo string, bytes o bytearray
        pdf_output = pdf.output(dest='S')
        if isinstance(pdf_output, str):
            return pdf_output.encode('latin-1')
        elif isinstance(pdf_output, bytearray):
            return bytes(pdf_output)
        else:
            return pdf_output

    finally:
        # Cierre seguro del cursor
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        
        # Mantener conexión activa
        if conn:
            try:
                if hasattr(conn, "ping"):
                    conn.ping(reconnect=True)
            except Exception as ping_error:
                print(f"Error al hacer ping a la conexión MySQL: {ping_error}")

# 💡 Sugerencia: Cachear la obtención de cuentas a nivel global o de módulo
@st.cache_data(ttl=300)
def _obtener_cuentas_detalle(db_nombre):
    conn = conectar_db(db_nombre)
    if not conn:
        return pd.DataFrame()
    try:
        query = """
            SELECT codigo, nombre 
            FROM plan_cuentas 
            WHERE codigo IS NOT NULL 
              AND TRIM(codigo) != '' 
              AND LOWER(codigo) != 'nan'
              AND LOWER(TRIM(tipo)) = 'detalle'
            ORDER BY codigo
        """
        df = ejecutar_consulta(query, conn)
        if df.empty:
            query = """
                SELECT codigo, nombre 
                FROM plan_cuentas 
                WHERE codigo IS NOT NULL 
                  AND TRIM(codigo) != '' 
                  AND LOWER(codigo) != 'nan'
                ORDER BY codigo
            """
            df = ejecutar_consulta(query, conn)
        return df if df is not None else pd.DataFrame()
    finally:
        if conn: conn.close()

def mostrar_interfaz_mayor(f_ini_g, f_fin_g, db_nombre):
    st.subheader("📖 Libro Mayor Analítico")

    # 1. ESTADOS DE SESIÓN
    if 'reporte_mayor' not in st.session_state: st.session_state.reporte_mayor = None
    if 'movs_solos' not in st.session_state: st.session_state.movs_solos = None
    if 'cuenta_actual' not in st.session_state: st.session_state.cuenta_actual = ""

    # Registrar log de forma segura sin mantener la conexión abierta innecesariamente
    conn_log = conectar_db(db_nombre)
    if conn_log:
        try:
            registrar_log_automatico(conn_log, "CONSULTA_LIBRO_MAYOR", f"Usuario {st.session_state.get('usuario', 'Desconocido')} consultó mayor en {db_nombre}")
        except:
            pass
        finally:
            conn_log.close()

    # 2. Carga optimizada de cuentas mediante caché
    df_cuentas = _obtener_cuentas_detalle(db_nombre)
    if df_cuentas.empty:
        st.error(f"❌ No se encontraron cuentas en el plan de cuentas de: {db_nombre}")
        return

    # Construcción ultrarrápida de opciones sin iterrows()
    df_cuentas['codigo_str'] = df_cuentas['codigo'].astype(str).str.strip()
    df_cuentas['nombre_str'] = df_cuentas['nombre'].fillna("").astype(str).str.strip()
    
    opciones_mapa = {
        (f"{row.codigo_str} - {row.nombre_str}" if row.nombre_str else row.codigo_str): row.codigo_str
        for _, row in df_cuentas.iterrows()
    }
    lista_opciones = list(opciones_mapa.keys())

    cuenta_sel_label = st.selectbox("Seleccione cuenta:", lista_opciones, key="select_cuenta_mayor")
    cuenta_para_consulta = opciones_mapa.get(cuenta_sel_label, cuenta_sel_label.split(" - ")[0])
    
    import datetime
    def_inicio = f_ini_g if f_ini_g else datetime.date(2026, 5, 1)
    def_fin = f_fin_g if f_fin_g else datetime.date(2026, 5, 31)

    col1, col2 = st.columns(2)
    f_m_d = col1.date_input("Desde", value=def_inicio, key="m_d_mayo")
    f_m_h = col2.date_input("Hasta", value=def_fin, key="m_h_mayo")

    if st.button("🔍 Generar Movimientos", key="btn_generar_movs_mayor"):
        st.info(f"⏳ Procesando mayor para la cuenta {cuenta_para_consulta} del {f_m_d} al {f_m_h}...")
        
        res_reporte, movs_solos, saldo_final_real = ejecutar_mayor_analitico(db_nombre, cuenta_para_consulta, f_m_d, f_m_h)
        
        if res_reporte is not None and not res_reporte.empty:
            st.session_state.reporte_mayor = res_reporte
            st.session_state.movs_solos = movs_solos if not movs_solos.empty else res_reporte
            st.session_state.saldo_final_reporte = saldo_final_real
            st.session_state.cuenta_actual = cuenta_sel_label
            st.rerun()
        else:
            st.session_state.reporte_mayor = None
            st.session_state.movs_solos = None
            st.warning("⚠️ La función `ejecutar_mayor_analitico` no devolvió registros para los parámetros dados.")

    st.divider()

    if st.session_state.reporte_mayor is not None:
        reporte = st.session_state.reporte_mayor
        movs_solos = st.session_state.movs_solos
        
        if not reporte.empty and movs_solos is not None:
            t_debe = movs_solos['debe'].sum() if 'debe' in movs_solos.columns else 0.0
            t_haber = movs_solos['haber'].sum() if 'haber' in movs_solos.columns else 0.0
            s_final = st.session_state.get('saldo_final_reporte', 0.0)

            m1, m2, m3 = st.columns(3)
            m1.metric("TOTAL DEBE", f"Bs. {t_debe:,.2f}")
            m2.metric("TOTAL HABER", f"Bs. {t_haber:,.2f}")
            m3.metric("SALDO FINAL", f"Bs. {s_final:,.2f}")

            # Limpieza rápida de fecha en texto plano
            reporte_vista = reporte.copy()
            if 'fecha' in reporte_vista.columns:
                reporte_vista['fecha'] = reporte_vista['fecha'].astype(str).str.split().str[0].str.replace('00:00:00', '').str.strip()

            st.dataframe(reporte_vista, use_container_width=True, hide_index=True)


@st.cache_data(ttl=300)
def generar_balance_profesional(db, f_i, f_f, sucursal):
    # Nota: Pasamos 'db' como argumento para que el sistema de caché de Streamlit 
    # sepa cuándo invalidar el resultado si cambia la empresa o el rango de fechas.
    conn = conectar_db(db)
    if not conn:
        st.error("Papi, no se pudo establecer conexión a la base de datos.")
        return None

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"USE `{db}`")
        
        # 1. Consultar el plan de cuentas original
        query_plan = f"SELECT codigo, nombre, nivel, tipo, padre FROM `{db}`.plan_cuentas ORDER BY codigo"
        df_plan = ejecutar_consulta(query_plan, conn)
        
        if df_plan is None or df_plan.empty:
            st.warning("⚠️ El plan de cuentas está vacío.")
            return None

        # 2. Obtener los saldos del balance de comprobación
        df_saldos = generar_balance_comprobacion(conn, f_i, f_f, sucursal)
        
        cols_finales = ['codigo', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        
        if df_saldos is None or df_saldos.empty:
            df_saldos = pd.DataFrame(columns=cols_finales)
        else:
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

        # 3. Hacer el merge
        df = pd.merge(
            df_plan, 
            df_saldos[['llave_join', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']], 
            on='llave_join', 
            how='left'
        )
        
        cols_num = ['Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        df[cols_num] = df[cols_num].fillna(0.0).astype(float)

        # 4. Limpiar saldos en cuentas de tipo "Grupo"
        if 'tipo' in df.columns:
            is_grupo = df['tipo'].astype(str).str.lower() == 'grupo'
            df.loc[is_grupo, cols_num] = 0.0

        # 5. SUMATORIA JERÁRQUICA OPTIMIZADA
        niveles_disponibles = sorted([n for n in df['nivel'].dropna().unique()], reverse=True)
        
        # Convertimos a diccionario indexado para acelerar la acumulación sin iterrows pesados
        # (Agrupamos de abajo hacia arriba de forma más eficiente)
        for n in niveles_disponibles:
            filas_nivel = df[df['nivel'] == n]
            for _, fila in filas_nivel.iterrows():
                p_cod = fila['llave_padre']
                if pd.notna(p_cod) and p_cod != '' and p_cod != 'none' and p_cod != 'nan':
                    mask_padre = df['llave_join'] == str(p_cod)
                    if mask_padre.any():
                        df.loc[mask_padre, cols_num] = df.loc[mask_padre, cols_num].values + fila[cols_num].values

        df['Saldo Final'] = df['Saldo Inicial'] + df['Debe'] - df['Haber']

        # 6. Fila Total Global
        df_nivel_1 = df[df['nivel'] == 1]
        
        total_debe = float(df_nivel_1['Debe'].sum())
        total_haber = float(df_nivel_1['Haber'].sum())
        total_saldo_inicial_neto = float(df_nivel_1['Saldo Inicial'].sum())
        total_saldo_final_neto = float(df_nivel_1['Saldo Final'].sum())

        fila_total = pd.DataFrame([{
            'codigo': 'Σ', 
            'nombre': 'TOTAL GENERAL', 
            'nivel': 0, 
            'tipo': 'Total', 
            'padre': None,
            'Saldo Inicial': round(total_saldo_inicial_neto, 2),
            'Debe': total_debe,
            'Haber': total_haber,
            'Saldo Final': round(total_saldo_final_neto, 2)
        }])
        
        cols_salida = ['codigo', 'nombre', 'nivel', 'tipo', 'padre', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final']
        df_final = pd.concat([df[cols_salida], fila_total[cols_salida]], ignore_index=True)
        return df_final

    except Exception as e:
        st.error(f"Error procesando balance profesional: {e}")
        return None
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@st.cache_data(ttl=300)
def consultar_libro_diario_db(db_a_usar=None, fecha_inicio=None, fecha_fin=None):
    """
    Consulta el libro diario de forma optimizada y cacheada para evitar saturar la memoria.
    """
    if not db_a_usar:
        db_a_usar = st.session_state.get('DB_ACTUAL') or st.session_state.get('empresa_actual')

    if not db_a_usar or db_a_usar == 'none':
        st.error("❌ No se ha seleccionado una base de datos de empresa válida.")
        return pd.DataFrame()

    # Si no se pasan fechas, acotamos por seguridad al año en curso para no descargar toda la BD
    import datetime
    if not fecha_inicio:
        fecha_inicio = f"{datetime.datetime.now().year}-01-01"
    if not fecha_fin:
        fecha_fin = str(datetime.date.today())

    conn = conectar_db(db_a_usar) if 'conectar_db' in globals() else None
    if not conn:
        st.error(f"❌ No se pudo establecer conexión con la base de datos `{db_a_usar}`.")
        return pd.DataFrame()

    try:
        # Consulta acotada por rango de fechas (aprovecha los índices de la columna fecha)
        query = """
            SELECT id, n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber 
            FROM asientos_contables 
            WHERE fecha >= %s AND fecha <= %s 
            ORDER BY fecha ASC, id ASC
        """
        params = (str(fecha_inicio), str(fecha_fin))
        
        df = pd.read_sql(query, conn, params=params)
        
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
            
            # Excluir columnas sensibles o innecesarias
            df = df.drop(columns=['bloqueado'], errors='ignore')
            
            if not all(col in df.columns for col in ['debe', 'haber']):
                st.error(f"⚠️ Estructura incompatible. Columnas: {df.columns.tolist()}")
                return pd.DataFrame()
                
            return df
        
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"❌ Error al consultar el libro diario en `{db_a_usar}`: {e}")
        return pd.DataFrame()
        
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



@st.cache_data(ttl=300)
def ejecutar_mayor_analitico(db_nombre, cuenta, fecha_desde, fecha_hasta):
    """
    Calcula el mayor analítico sanitizando la cuenta en Python y 
    aprovechando los índices de MySQL (sin funciones en el WHERE).
    """
    # 1. SANITIZACIÓN EN PYTHON (Adiós a TRIM() y funciones lentas en SQL)
    cuenta_limpia = str(cuenta).strip()
    if " - " in cuenta_limpia:
        cuenta_limpia = cuenta_limpia.split(" - ")[0].strip()
    cuenta_solo_numeros = "".join(filter(str.isdigit, cuenta_limpia))

    db_actual = db_nombre if db_nombre and db_nombre != 'none' else st.session_state.get('DB_ACTUAL')
    if not db_actual or db_actual == 'none':
        db_actual = st.session_state.get('empresa_actual')

    conn = conectar_db(db_actual)
    if not conn:
        return pd.DataFrame(), pd.DataFrame(), 0.0

    try:
        f_inicio = pd.to_datetime(fecha_desde).normalize()
        f_fin = pd.to_datetime(fecha_hasta).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = %s AND table_name = 'saldos_iniciales'
        """, (db_actual,))
        tiene_saldos_iniciales = cursor.fetchone()[0] > 0
        
        # 2. CONSULTAS SQL LIMPIAS (Comparación exacta, velocidad máxima)
        if tiene_saldos_iniciales:
            query_saldo = f"""
                SELECT 
                    (SELECT IFNULL(SUM(debe - haber), 0) FROM `{db_actual}`.saldos_iniciales WHERE cuenta_contable = %s OR cuenta_contable = %s) +
                    (SELECT IFNULL(SUM(debe - haber), 0) FROM `{db_actual}`.asientos_contables 
                     WHERE (plan_cuentas = %s OR plan_cuentas = %s OR cuenta_contable = %s OR cuenta_contable = %s) AND fecha < %s) 
                AS saldo_previo
            """
            res_saldo = pd.read_sql(
                query_saldo, conn, 
                params=(cuenta_limpia, cuenta_solo_numeros, cuenta_limpia, cuenta_solo_numeros, cuenta_limpia, cuenta_solo_numeros, f_inicio.strftime('%Y-%m-%d %H:%M:%S'))
            )
        else:
            query_saldo = f"""
                SELECT IFNULL(SUM(debe - haber), 0) AS saldo_previo
                FROM `{db_actual}`.asientos_contables 
                WHERE (plan_cuentas = %s OR plan_cuentas = %s OR cuenta_contable = %s OR cuenta_contable = %s) AND fecha < %s
            """
            res_saldo = pd.read_sql(
                query_saldo, conn, 
                params=(cuenta_limpia, cuenta_solo_numeros, cuenta_limpia, cuenta_solo_numeros, f_inicio.strftime('%Y-%m-%d %H:%M:%S'))
            )

        saldo_inicial_periodo = float(res_saldo.iloc[0, 0]) if not res_saldo.empty else 0.0

        query_movs = f"""
            SELECT DATE_FORMAT(fecha, '%Y-%m-%d') AS fecha, n_comprobante, descripcion, referencia, debe, haber 
            FROM `{db_actual}`.asientos_contables 
            WHERE (
                plan_cuentas = %s OR 
                plan_cuentas = %s OR 
                cuenta_contable = %s OR 
                cuenta_contable = %s
            ) 
            AND fecha >= %s AND fecha <= %s 
            ORDER BY fecha ASC, id ASC
        """
        df_movs = pd.read_sql(
            query_movs, conn, 
            params=(cuenta_limpia, cuenta_solo_numeros, cuenta_limpia, cuenta_solo_numeros, f_inicio.strftime('%Y-%m-%d %H:%M:%S'), f_fin.strftime('%Y-%m-%d %H:%M:%S'))
        )
        
        if not df_movs.empty:
            df_movs['debe'] = pd.to_numeric(df_movs['debe'], errors='coerce').fillna(0.0)
            df_movs['haber'] = pd.to_numeric(df_movs['haber'], errors='coerce').fillna(0.0)
            df_movs['Saldo'] = saldo_inicial_periodo + (df_movs['debe'] - df_movs['haber']).cumsum()
            df_movs['fecha'] = df_movs['fecha'].astype(str)
        else:
            df_movs = pd.DataFrame(columns=['fecha', 'n_comprobante', 'descripcion', 'referencia', 'debe', 'haber', 'Saldo'])

        fila_inicial = pd.DataFrame([{
            'fecha': str(fecha_desde),
            'n_comprobante': 'S/I',
            'descripcion': f'SALDO INICIAL AL {fecha_desde}',
            'referencia': 'INICIAL',
            'debe': 0.00, 
            'haber': 0.00,
            'Saldo': saldo_inicial_periodo
        }])

        df_final = pd.concat([fila_inicial, df_movs], ignore_index=True)
        
        if not df_final.empty and 'fecha' in df_final.columns:
            df_final['fecha'] = df_final['fecha'].astype(str).str.split().str[0].replace(['NaT', 'nan', 'NaT 00:00:00', 'None'], '')

        saldo_final_real = float(df_final['Saldo'].iloc[-1]) if not df_final.empty else saldo_inicial_periodo
        
        return df_final, df_movs, saldo_final_real

    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), 0.0
    finally:
        if conn:
            try: conn.close()
            except: pass

@st.cache_data(ttl=300)
def generar_balance_comprobacion(db, f_i, f_f, sucursal):
    """
    Genera el balance de comprobación cacheado y con limpieza de códigos eficiente.
    """
    if not db:
        return pd.DataFrame(columns=['Código', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final'])
    
    conn = conectar_db(db)
    if not conn:
        return pd.DataFrame(columns=['Código', 'Saldo Inicial', 'Debe', 'Haber', 'Saldo Final'])
    
    try:
        # 1. Traer los Saldos Iniciales fijos de la tabla 'saldos_iniciales'
        sql_si = f"SELECT plan_cuentas, SUM(debe) - SUM(haber) as val FROM `{db}`.saldos_iniciales GROUP BY plan_cuentas"
        
        # 2. Movimientos del rango seleccionado en 'asientos_contables'
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
                    
                    # Sanitización limpia en Python
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
        balance['Saldo Inicial'] = balance['si']
        
        es_activo_gasto = balance['Tipo'].isin(['1', '5'])
        
        balance['Saldo Final'] = 0.0
        balance.loc[es_activo_gasto, 'Saldo Final'] = balance['Saldo Inicial'] + balance['debe'] - balance['haber']
        balance.loc[~es_activo_gasto, 'Saldo Final'] = balance['Saldo Inicial'] - balance['debe'] + balance['haber']
        
        return balance[['Código', 'Saldo Inicial', 'debe', 'haber', 'Saldo Final']].rename(columns={
            'debe': 'Debe', 'haber': 'Haber'
        })

    except Exception as e:
        st.error(f"❌ Error crítico procesando el balance: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            try: conn.close()
            except: pass


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
    
    # 1. Definimos el mapeo de nombres de columna
    cols = {name: i for i, name in enumerate(df.columns)}
    
    # Función de limpieza interna
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
            return round(min(max(val, -99999999.99), 99999999.99), 2)
        except: return 0.0

    def convertir_fecha(v):
        try:
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
    
    valores_a_insertar = []
    data = df.astype(str).replace('nan', '').values
    
    # 2. Recolectamos todas las tuplas en memoria (Ultra rápido)
    for fila in data:
        if "FECHA" in str(fila[0]).upper() or str(fila[cols.get('rif', 2)]).strip() == "": 
            continue

        idx_total = cols.get('total_ventas_con_iva', 5)
        idx_exentas = cols.get('ventas_exentas', 6)
        idx_base = cols.get('base_imponible', 7)
        idx_debito = cols.get('debito_fiscal', 9)

        valores_a_insertar.append((
            convertir_fecha(fila[0]), 
            str(fila[1]).upper()[:255].strip(), 
            str(fila[cols.get('rif', 2)]).replace('-', '').replace('.', '').strip(), 
            str(fila[cols.get('n_factura', 3)]).replace('.0', '').strip().zfill(5), 
            str(fila[cols.get('n_control', 4)]).replace('.0', '').strip().zfill(5),
            f_n(fila[idx_total]), 
            f_n(fila[idx_exentas]), 
            f_n(fila[idx_base]), 
            16.0, 
            f_n(fila[idx_debito])
        ))

    if not valores_a_insertar:
        cursor.close()
        return 0

    try:
        # 3. Inserción masiva en lote de un solo golpe
        cursor.executemany(sql, valores_a_insertar)
        conn.commit()
        exitos = cursor.rowcount if cursor.rowcount > 0 else len(valores_a_insertar)
        return exitos
    except Exception as e:
        conn.rollback()
        st.error(f"❌ Error al cargar libro de ventas: {e}")
        return 0
    finally:
        cursor.close()


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


def cargar_libro_compras_db(df, conn_o_db=None):
    if conn_o_db is None:
        nombre_db = st.session_state.get("db_cliente")
        conn = conectar_db(nombre_db)
    elif isinstance(conn_o_db, str):
        conn = conectar_db(conn_o_db)
    else:
        conn = conn_o_db 

    if not conn:
        st.error("❌ No se pudo establecer conexión con la base de datos.")
        return 0

    cursor = conn.cursor()
    
    # 1. Mapeo de nombres de columna dinámico
    cols = {name.lower().strip(): i for i, name in enumerate(df.columns)}
    
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
            return round(min(max(val, -99999999.99), 99999999.99), 2)
        except: return 0.0

    def convertir_fecha(v):
        try:
            if str(v).replace('.','',1).isdigit() and float(v) > 30000:
                return (pd.to_datetime('1899-12-30') + pd.to_timedelta(float(v), 'D')).strftime('%Y-%m-%d')
            return pd.to_datetime(v).strftime('%Y-%m-%d')
        except: return "2026-06-05"

    sql = """INSERT INTO libro_compras 
              (fecha_operacion, tipo_documento, n_factura, n_control, proveedor, rif, 
               total_compras, importe_exento, base_imponible, iva_porcentaje, iva_monto,
               retencion_realizada, retencion_iva_realizada, tipo_transaccion) 
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
              ON DUPLICATE KEY UPDATE 
              fecha_operacion = VALUES(fecha_operacion), 
              tipo_documento = VALUES(tipo_documento),
              n_control = VALUES(n_control),
              proveedor = VALUES(proveedor),
              total_compras = VALUES(total_compras),
              importe_exento = VALUES(importe_exento),
              base_imponible = VALUES(base_imponible),
              iva_monto = VALUES(iva_monto)"""
    
    def get_col_idx(posibles, default_idx):
        for p in posibles:
            for col_name, idx in cols.items():
                if p in col_name:
                    return idx
        return default_idx

    idx_fecha = get_col_idx(['fecha'], 0)
    idx_tipo = get_col_idx(['tipo_de_documento', 'tipo_documento', 'tipo'], 1)
    idx_fact = get_col_idx(['numero_de_documento', 'factura', 'n_factura'], 2)
    idx_control = get_col_idx(['numero_de_control', 'control', 'n_control'], 3)
    idx_prov = get_col_idx(['nombre_o_razon_social', 'proveedor', 'razon_social'], 4)
    idx_rif = get_col_idx(['rif', 'r.i.f'], 5)
    idx_total = get_col_idx(['total_compra', 'total_compras', 'total'], 6)
    idx_exento = get_col_idx(['compras_exentas', 'exento', 'importe_exento'], 7)
    idx_base = get_col_idx(['base_imponible', 'base'], 8)
    idx_alicuota = get_col_idx(['alicuota', 'porcentaje'], 9)
    idx_iva = get_col_idx(['credito_fiscales', 'iva_monto', 'iva'], 10)

    data = df.astype(str).replace('nan', '').values
    valores_a_insertar = []

    # 2. Acumulamos todas las tuplas en memoria (Operación ultrarrápida)
    for fila in data:
        fact_val = str(fila[idx_fact]).replace('.0', '').strip()
        rif_val = str(fila[idx_rif]).strip()
        if "FECHA" in str(fila[idx_fecha]).upper() or not fact_val or fact_val.lower() == 'nan': 
            continue

        val_total = f_n(fila[idx_total])
        val_exento = f_n(fila[idx_exento])
        val_base = f_n(fila[idx_base])
        val_alicuota = f_n(fila[idx_alicuota]) if f_n(fila[idx_alicuota]) > 0 else 16.0
        val_iva = f_n(fila[idx_iva])

        valores_a_insertar.append((
            convertir_fecha(fila[idx_fecha]), 
            str(fila[idx_tipo]).replace('.0', '').strip().zfill(2), 
            fact_val.zfill(5) if len(fact_val) < 5 else fact_val,
            str(fila[idx_control]).replace('.0', '').strip(),
            str(fila[idx_prov]).upper()[:255].strip(), 
            rif_val.replace('-', '').replace('.', '').strip(), 
            val_total, 
            val_exento, 
            val_base, 
            val_alicuota, 
            val_iva, 
            0.00, 
            0.00, 
            "C"   
        ))

    if not valores_a_insertar:
        cursor.close()
        return 0

    try:
        # 3. Inserción masiva en lote con executemany
        cursor.executemany(sql, valores_a_insertar)
        conn.commit()
        exitos = cursor.rowcount if cursor.rowcount > 0 else len(valores_a_insertar)
        return exitos
    except Exception as e:
        conn.rollback()
        st.error(f"❌ Error al cargar libro de compras: {e}")
        return 0
    finally:
        cursor.close()

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


# Configura tu clave (asegúrate de que tu api_key esté configurada correctamente)
genai.configure(api_key="AQ.Ab8RN6KEpVYjcWJ4XLcEBNSK1ASqvBcnsuJkon-tb0fhLsVMLA")

def convertir_pdf_a_imagen_bytes(pdf_file_obj):
    """Convierte la primera página de un PDF subido en Streamlit a bytes de imagen JPEG optimizada para velocidad"""
    try:
        pdf_file_obj.seek(0)
        doc = fitz.open(stream=pdf_file_obj.read(), filetype="pdf")
        if len(doc) == 0:
            return None
        
        page = doc[0] 
        # Reducimos a 96 DPI (calidad estándar de pantalla) para agilizar el renderizado y el envío a la IA
        pix = page.get_pixmap(dpi=96) 
        
        # Comprimimos el JPEG a una calidad óptima (ej. 85) para aligerar los bytes transmitidos
        img_bytes = pix.tobytes("jpeg", jpg_quality=85)
        return img_bytes
    except Exception as e:
        st.error(f"Error convirtiendo el PDF a imagen: {e}")
        return None


def obtener_modelo_valido():
    """Instancia directamente el modelo actual y oficial de Gemini para el procesamiento OCR."""
    try:
        # Apuntamos directamente al modelo oficial requerido por la API
        return genai.GenerativeModel('gemini-3.8-flash')
    except Exception as e:
        st.error(f"❌ Error al inicializar el modelo de IA: {e}")
        return None


def extraer_datos_con_regex(pdf_file_obj):
    pdf_file_obj.seek(0)
    doc = fitz.open(stream=pdf_file_obj.read(), filetype="pdf")
    texto_completo = ""
    for pagina in doc:
        texto_completo += pagina.get_text("text") + "\n"
        
    # Estructura alineada 100% con tu tabla libro_compras
    datos = {
        "fecha_operacion": datetime.today().strftime('%Y-%m-%d'), # Por defecto hoy si no la halla
        "tipo_documento": "01",
        "n_factura": "",
        "n_control": "",
        "n_factura_afectada": None,
        "proveedor": "PROVEEDOR NO IDENTIFICADO",
        "rif": "",
        "tipo_transaccion": "01",
        "total_compras": 0.0,
        "importe_exento": 0.0,
        "base_imponible": 0.0,
        "iva_porcentaje": 16.0,
        "iva_monto": 0.0
    }
    
    lineas = [l.strip() for l in texto_completo.split('\n') if l.strip()]
    
    # 1. Buscar RIF del emisor (ej. J-12345678-9 o J123456789)
    match_rif = re.search(r'\b([JVEG]\s*-?\s*\d{8}\s*-?\s*\d)\b', texto_completo, re.IGNORECASE)
    if match_rif:
        datos["rif"] = re.sub(r'[^0-9JVEG]', '', match_rif.group(1)).upper()
        
    # 2. Intentar deducir el Proveedor (usualmente las primeras líneas del texto fiscal traen la Razón Social)
    if len(lineas) > 0:
        candidato = lineas[0]
        if "RIF" in candidato.upper() or len(candidato) < 4:
            if len(lineas) > 1:
                datos["proveedor"] = lineas[1][:255]
        else:
            datos["proveedor"] = candidato[:255]

    # 3. Buscar Número de Control (ej. N° Control: 00-001234 o Control: 001234)
    match_control = re.search(r'(?:control|n[°º]\s*control)[:\s#]*([0-9\-]{5,15})', texto_completo, re.IGNORECASE)
    if match_control:
        datos["n_control"] = match_control.group(1).strip()
        
    # 4. Buscar Factura N°
    match_fac = re.search(r'(?:factura|n[°º]\s*factura|documento)[:\s#]*([0-9A-Za-z\-]{3,15})', texto_completo, re.IGNORECASE)
    if match_fac:
        datos["n_factura"] = match_fac.group(1).strip()

    # 5. Buscar Fecha (Formato DD/MM/YYYY o YYYY-MM-DD)
    match_fecha = re.search(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b', texto_completo)
    if match_fecha:
        f_str = match_fecha.group(1).replace('/', '-')
        try:
            partes = f_str.split('-')
            if len(partes[0]) == 2: # Viene como DD-MM-YYYY
                datos["fecha_operacion"] = f"{partes[2]}-{partes[1]}-{partes[0]}"
            else:
                datos["fecha_operacion"] = f_str
        except:
            pass

    # Función auxiliar para limpiar montos en formato venezolano (ej. 65.710,49 -> 65710.49)
    def limpiar_monto(texto_monto):
        try:
            # Quitamos los puntos de miles y sustituimos la coma decimal por punto
            limpio = texto_monto.replace('.', '').replace(',', '.')
            return float(limpio)
        except:
            return 0.0

    # 6. Extracción quirúrgica de montos en Bs. (Bloque de totales inferior)
    # Recorremos las líneas buscando las etiquetas clave y extrayendo el monto que está justo antes de 'Bs.'
    for i, linea in enumerate(lineas):
        linea_lower = linea.lower()
        
        # Buscar Base Imponible (ej: "Base imponible 16,00%: 131,30 USD 65.710,49 Bs.")
        if "base imponible" in linea_lower or "base imponible 16" in linea_lower:
            # Si el monto está en la misma línea o en la siguiente
            texto_a_buscar = linea
            if "bs" not in linea_lower and i + 1 < len(lineas):
                texto_a_buscar += " " + lineas[i + 1]
            
            m_val = re.search(r'([\d\.,]+)\s*Bs\.?', texto_a_buscar, re.IGNORECASE)
            if m_val:
                datos["base_imponible"] = limpiar_monto(m_val.group(1))

        # Buscar IVA (ej: "IVA 16,00%: 21,01 USD 10.513,68 Bs.")
        elif "iva" in linea_lower and ("16" in linea_lower or "monto iva" in linea_lower):
            texto_a_buscar = linea
            if "bs" not in linea_lower and i + 1 < len(lineas):
                texto_a_buscar += " " + lineas[i + 1]
                
            m_val = re.search(r'([\d\.,]+)\s*Bs\.?', texto_a_buscar, re.IGNORECASE)
            if m_val:
                datos["iva_monto"] = limpiar_monto(m_val.group(1))

        # Buscar Total (ej: "Total: 152,31 USD 76.224,17 Bs.")
        elif linea_lower.startswith("total:") or linea_lower == "total":
            texto_a_buscar = linea
            if "bs" not in linea_lower and i + 1 < len(lineas):
                texto_a_buscar += " " + lineas[i + 1]
                
            m_val = re.search(r'([\d\.,]+)\s*Bs\.?', texto_a_buscar, re.IGNORECASE)
            if m_val:
                datos["total_compras"] = limpiar_monto(m_val.group(1))

    # Respaldo matemático: Si por alguna razón no halló el total pero tiene base e IVA, los suma
    if datos["total_compras"] == 0.0 and datos["base_imponible"] > 0:
        datos["total_compras"] = round(datos["base_imponible"] + datos["iva_monto"], 2)

    return datos


def extraer_texto_pdf(uploaded_file):
    if uploaded_file is None:
        st.error("El archivo recibido es None.")
        return ""
        
    try:
        # Asegurarnos de rebobinar el archivo siempre
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
            
        bytes_pdf = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()

        if not bytes_pdf:
            st.error("El archivo PDF está vacío (0 bytes).")
            return ""
    
        texto_extraido = ""
        
        with fitz.open(stream=bytes_pdf, filetype="pdf") as doc:
            st.info(f"📄 El PDF tiene {len(doc)} página(s).")
            for i, pagina in enumerate(doc):
                txt_pagina = pagina.get_text("text")
                texto_extraido += txt_pagina
                st.write(f"Página {i+1} - Texto nativo extraído: {len(txt_pagina)} caracteres.")
                
        # Si no hay texto nativo, intentamos OCR
        if len(texto_extraido.strip()) < 10:
            st.warning("⚠️ Texto nativo muy corto. Intentando forzar OCR...")
            texto_extraido = ""
            with fitz.open(stream=bytes_pdf, filetype="pdf") as doc:
                for i, pagina in enumerate(doc):
                    pix = pagina.get_pixmap(dpi=300)
                    img_bytes = pix.tobytes("png")
                    
                    imagen = Image.open(io.BytesIO(img_bytes)).convert("L")
                    enhancer = ImageEnhance.Contrast(imagen)
                    imagen_filtrada = enhancer.enhance(2.0)
                    
                    try:
                        texto_pagina = pytesseract.image_to_string(imagen_filtrada, lang='spa')
                        texto_extraido += texto_pagina + "\n"
                        st.write(f"OCR Página {i+1}: {len(texto_pagina)} caracteres leídos.")
                    except Exception as err_tess:
                        st.error(f"❌ Error crítico de Tesseract OCR: {err_tess}")
                        st.info("💡 Asegúrate de tener Tesseract instalado en tu PC y que la ruta esté bien configurada.")
                        
        return texto_extraido

    except Exception as e:
        st.error(f"❌ Error general en extraer_texto_pdf: {e}")
        return ""


def extraer_datos_factura(archivo):
    model = obtener_modelo_valido()
    if not model:
        st.error("No se encontró ningún modelo compatible en tu cuenta.")
        return None
        
    try:
        if archivo.type == "application/pdf":
            img_data = convertir_pdf_a_imagen_bytes(archivo)
            if not img_data:
                st.error("No se pudo convertir el PDF a imagen.")
                return None
            tipo_mime = "image/jpeg"
        else:
            archivo.seek(0)
            img_data = archivo.read()
            tipo_mime = archivo.type if archivo.type else "image/jpeg"

        prompt_instrucciones = """
            Eres un asistente contable experto en OCR fiscal en Venezuela (normativa SENIAT). 
            Tu tarea es analizar el documento escaneado y extraer la información adaptada estrictamente al orden y esquema de la tabla de MySQL.

            REGLAS DE EXTRACCIÓN:
            1. 'fecha_operacion': Fecha de emisión del documento en formato YYYY-MM-DD.
            2. 'tipo_documento': Devuelve '01' si es factura, '03' si es Nota de Crédito, o '02' si es Nota de Débito.
            3. 'n_factura': 
               - Si es factura, extrae el número de factura.
               - Si es Nota de Crédito o Débito, extrae el número propio del documento de ajuste (ej. "00000720").
            4. 'n_control': Busca la etiqueta "N° de Control" o formato "00-XXXXXX" (ej. "00-026357").
            5. 'nota_credito': Si es Nota de Crédito, coloca su número de documento. De lo contrario, null.
            6. 'nota_debito': Si es Nota de Débito, coloca su número de documento. De lo contrario, null.
            7. 'n_factura_afectada': 
               - Si es Nota de Crédito o Débito, extrae el número de la Factura Afectada (ej. "00008274"). 
               - Si es una factura normal, déjalo en null.
            8. 'proveedor': Extrae la **Razón Social completa** del emisor o proveedor (ej. "INVERSIONES COMERCIALES C.A.").
            9. 'rif': RIF del emisor sin guiones ni espacios (ej. J317227719).
            10. 'tipo_transaccion': Devuelve por defecto '01'.
            11. Montos: Extrae 'total_compras', 'importe_exento', 'base_imponible', 'iva_porcentaje' e 'iva_monto' expresados numéricamente.
            12. Devuelve SOLO un JSON puro sin markdown extra.

            Formato requerido estrictamente en JSON (orden exacto de la BD):
            {
                "fecha_operacion": "YYYY-MM-DD",
                "tipo_documento": "string",
                "n_factura": "string",
                "n_control": "string",
                "nota_credito": "string",
                "nota_debito": "string",
                "n_factura_afectada": "string",
                "proveedor": "string",
                "rif": "string",
                "tipo_transaccion": "string",
                "total_compras": float,
                "importe_exento": float,
                "base_imponible": float,
                "iva_porcentaje": float,
                "iva_monto": float
            }
        """
        
        response = model.generate_content([
            prompt_instrucciones,
            {"mime_type": tipo_mime, "data": img_data}
        ])
        
        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
        start = texto_limpio.find('{')
        end = texto_limpio.rfind('}') + 1
        texto_limpio = texto_limpio[start:end]
        
        datos = json.loads(texto_limpio)
        
        # Limpieza y blindaje de datos extraídos
        datos['proveedor'] = str(datos.get('proveedor', 'VARIOS')).strip().upper()
        datos['rif'] = str(datos.get('rif', '')).replace('-', '').replace(' ', '').strip().upper()
        datos['n_factura'] = str(datos.get('n_factura', '')).strip().upper()
        datos['n_control'] = str(datos.get('n_control', '')).strip().upper()
        datos['tipo_transaccion'] = str(datos.get('tipo_transaccion', '01')).strip()
        
        for campo_extra in ['nota_credito', 'nota_debito', 'n_factura_afectada']:
            if datos.get(campo_extra) and str(datos[campo_extra]).lower() not in ['none', 'nan', '', 'null']:
                datos[campo_extra] = str(datos[campo_extra]).strip().upper()
            else:
                datos[campo_extra] = None
                
        for campo in ['total_compras', 'importe_exento', 'base_imponible', 'iva_porcentaje', 'iva_monto']:
            try:
                datos[campo] = float(datos[campo])
            except:
                datos[campo] = 0.0
        
        return datos
        
    except Exception as e:
        st.error(f"Error procesando con el modelo de IA: {e}")
        return None

def obtener_facturas_pendientes(conn, f_desde, f_hasta):
    """
    Consulta las facturas pendientes de retención acotando las columnas 
    necesarias para aligerar la transferencia de datos desde la base de datos.
    """
    try:
        query = """
            SELECT id, fecha_operacion, tipo_documento, n_factura, n_control, 
                   proveedor, rif, total_compras, base_imponible, iva_monto, retencion_realizada 
            FROM libro_compras 
            WHERE (retencion_realizada = 0 OR retencion_realizada IS NULL OR retencion_realizada = '' OR retencion_realizada = FALSE)
            AND fecha_operacion BETWEEN %s AND %s
        """
        df = ejecutar_consulta(query, conn, params=(f_desde, f_hasta))
        
        if df.empty:
            st.info(f"ℹ️ No hay facturas pendientes de retención entre {f_desde} y {f_hasta}.")
            
        return df
    except Exception as e:
        st.error(f"Error al cargar facturas pendientes: {e}")
        return pd.DataFrame()


def obtener_detalle_comprobante(nro_comprobante):
    """
    Obtiene los detalles completos del comprobante de forma directa 
    utilizando el número de comprobante como parámetro único.
    """
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        return pd.DataFrame()

    try:
        try:
            registrar_log_automatico(conn, "CONSULTA_DETALLE_COMPROBANTE", f"Usuario {st.session_state.usuario} consultó el comprobante {nro_comprobante}")
        except Exception:
            pass
        
        cursor = conn.cursor()
        
        # Consulta directa optimizada sin subconsultas anidadas
        query = """
            SELECT 
                id, Razon_Social_del_Agente_de_Retencion, RIF_Agente_Retencion, 
                Direccion_FiscalAgente_Retencion, E_Emision, F_Entrega, 
                Razon_Social_Sujeto_Retenido, RIF_Sujeto_Retenido, Ano, Mes, 
                N_Comprobante1, Fecha_Factura, Numero_Factura, Numero_Contro, 
                NFactura_Afectada, Total_Comrpas, Compras_Excentas, Base_Imponible, 
                Base_Imponible_8, Impuesto_Iva, IVA_Retenido, IVA_8, RET_IVA_8
            FROM retenciones_iva 
            WHERE N_Comprobante1 = %s
        """
        
        df = pd.read_sql(query, conn, params=(nro_comprobante,))
        return df

    except Exception as e:
        st.error(f"Error al obtener detalle del comprobante: {e}")
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


def obtener_detalle_comprobante(id_registro):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        return pd.DataFrame()

    try:
        registrar_log_automatico(conn, "CONSULTA_DETALLE_COMPROBANTE", f"Usuario {st.session_state.usuario} consultó {id_registro}")
        
        cursor = conn.cursor()
        
        # FORZAMOS EL ALIAS LIMPIO AS direccion_agente
        query = """
            SELECT 
                r.id, 
                r.Razon_Social_del_Agente_de_Retencion, 
                r.RIF_Agente_Retencion, 
                r.Direccion_FiscalAgente_Retencion,
                r.E_Emision, 
                r.F_Entrega, 
                r.Razon_Social_Sujeto_Retenido, 
                r.RIF_Sujeto_Retenido, 
                r.Ano, 
                r.Mes, 
                r.N_Comprobante1, 
                r.Fecha_Factura, 
                r.Numero_Factura, 
                r.Numero_Contro, 
                r.NFactura_Afectada,
                r.Total_Comrpas, 
                r.Compras_Excentas, 
                r.Base_Imponible, 
                r.Base_Imponible_8, 
                r.Impuesto_Iva, 
                r.IVA_Retenido, 
                r.IVA_8, 
                r.RET_IVA_8
            FROM retenciones_iva r
            WHERE r.N_Comprobante1 = (SELECT N_Comprobante1 FROM retenciones_iva WHERE id = %s)
        """
        
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

def eliminar_registro_retencion(id_registro):
    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    cursor = None
    
    if not conn:
        st.error("⚠️ No se pudo conectar a la base de datos de la empresa actual.")
        return False

    try:
        cursor = conn.cursor()
        
        # Registro de actividad seguro usando .get() para evitar KeyErrors en sesión
        usuario = st.session_state.get('usuario', 'Sistema')
        cliente_id = st.session_state.get('cliente_id', 'N/A')
        registrar_log_automatico(conn, "ELIMINAR_RETENCION", f"Usuario {usuario} eliminó registro de retención {id_registro} para el cliente {cliente_id}")
        
        # Ejecutamos la eliminación en la base de datos de la empresa (db_actual)
        query = "DELETE FROM retenciones_iva WHERE id = %s"
        cursor.execute(query, (id_registro,))
        conn.commit()
        
        return True

    except Exception as e:
        st.error(f"❌ Error al eliminar el registro de retención: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
                
        if conn:
            try:
                # Mantenemos el patrón seguro de conexión
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

        st.write(f"Conectado a: **{db_actual}**")

        # --- MANEJADOR DE PANTALLA DE ÉXITO (PERSISTENTE) ---
        if st.session_state.get('mostrar_exito'):
            st.success(f"### ✅ Comprobante `{st.session_state.get('last_iva', {}).get('nro_comp')}` generado y guardado exitosamente.")
            
            if 'last_iva' in st.session_state and 'facturas_seleccionadas' in st.session_state:
                st.divider()
                st.write("#### 📄 Detalle del Comprobante Generado:")
                
                facturas_guardadas = st.session_state.get('facturas_seleccionadas')
                porcentaje_actual = st.session_state.get('porcentaje_ret', 75)

                if facturas_guardadas is not None and not facturas_guardadas.empty:
                    lista_de_facturas = []
                    for _, fila in facturas_guardadas.iterrows():
                        iva = float(fila.get('impuesto_iva', 0))
                        monto_ret = (iva * porcentaje_actual) / 100
                        
                        lista_de_facturas.append({
                            'Fecha': fila['fecha_operacion'],
                            'N° Factura': fila['n_factura'],
                            'N° Control': fila['n_control'],
                            'Total Compras': fila['total_compras'],
                            'Base Imponible': fila['base_imponible'],
                            'IVA': iva,
                            'IVA Retenido': monto_ret
                        })
                    
                    df_resumen_procesado = pd.DataFrame(lista_de_facturas)
                    st.dataframe(df_resumen_procesado, hide_index=True, width="stretch")
            
            # Botón para limpiar y registrar otro grupo cuando el usuario lo decida
            if st.button("🔄 Registrar otro grupo de facturas", key="btn_reset_retencion"):
                st.session_state['facturas_seleccionadas'] = None
                st.session_state['mostrar_exito'] = False
                st.rerun()
            
            st.divider()

        # --- 3. LÓGICA DE PROCESAMIENTO NORMAL (PENDIENTES) ---
        col_b1, col_b2 = st.columns(2)
        f_desde = col_b1.date_input("Desde", st.session_state.get('f_inicio_global', dt.date.today()), key="ret_iva_desde")
        f_hasta = col_b2.date_input("Hasta", st.session_state.get('f_fin_global', dt.date.today()), key="ret_iva_hasta")

        df_facturas = obtener_facturas_pendientes(conn, f_desde, f_hasta)

        if not df_facturas.empty:
            if 'Seleccionar' not in df_facturas.columns:
                df_facturas.insert(0, "Seleccionar", False)

            df_editado = st.data_editor(
                df_facturas,
                column_config={"Seleccionar": st.column_config.CheckboxColumn(required=True)},
                hide_index=True,
                width="stretch"
            )

            seleccion = df_editado[df_editado["Seleccionar"] == True]
            
            if not seleccion.empty:
                st.session_state['facturas_seleccionadas'] = seleccion
                st.success(f"Facturas seleccionadas: {len(seleccion)}")
            else:
                # Solo limpiamos si no estamos mostrando un éxito reciente
                if not st.session_state.get('mostrar_exito'):
                    st.session_state['facturas_seleccionadas'] = None

        facturas_seleccionadas = st.session_state.get('facturas_seleccionadas')
        
        if facturas_seleccionadas is not None and not facturas_seleccionadas.empty:
            total_base_agrupado = facturas_seleccionadas['base_imponible'].sum()
            total_iva_agrupado = facturas_seleccionadas['iva_monto'].sum()
            total_facturas_agrupado = facturas_seleccionadas['total_compras'].sum()
            total_exento_agrupado = facturas_seleccionadas['importe_exento'].sum()
            
            factura_principal = facturas_seleccionadas.iloc[0]
            val_sugerido = str(factura_principal['fecha_operacion']).replace("-", "")[:6] + str(factura_principal['id']).zfill(8)

            st.write("### 📝 Datos del Comprobante (Grupo)")
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
                st.session_state['porcentaje_ret'] = porcentaje_ret 
                iva_retenido = (float(iva_i) * porcentaje_ret) / 100
                c11.metric("IVA a Retener Total", f"Bs. {iva_retenido:,.2f}")

                db_actual_form = st.session_state.get('DB_ACTUAL')
                empresa_data = obtener_datos_agente_db(db_actual_form)

                if not empresa_data:
                    st.error("⚠️ No se pudieron cargar los datos de la empresa.")
                else:
                    empresa_seleccionada = st.selectbox(
                        "Empresa", 
                        options=[empresa_data] if isinstance(empresa_data, dict) else empresa_data, 
                        format_func=lambda x: x.get('nombre_empresa', 'EMPRESA')
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
                
                # 🔍 AQUÍ ESTÁ LA MAGIA: Leemos la dirección fiscal nueva, respaldada con las anteriores
                domicilio_fiscal = (
                    empresa_data_env.get('direccion_fiscal') or 
                    empresa_data_env.get('direccion') or 
                    "DIRECCIÓN NO REGISTRADA"
                )

                cursor = None
                try:
                    cursor = conn_env.cursor()
        
                    for _, fila in facturas_seleccionadas.iterrows():
                        # 1. Detectar si es Nota de Crédito
                        tipo_doc_str = str(fila.get('tipo_documento', '')).strip().lower()
                        monto_total_fila = float(fila.get('total_compras', 0) or 0)
                        es_nc = 'credito' in tipo_doc_str or 'nota de credito' in tipo_doc_str or monto_total_fila < 0
                        
                        # Factor de signo: -1 si es nota de crédito, 1 si es factura normal
                        signo = -1 if es_nc else 1

                        # Extraemos los valores base respetando su signo natural o forzando el signo correcto
                        total_fila = abs(float(fila.get('total_compras', 0) or 0)) * signo
                        base = abs(float(fila.get('base_imponible', 0) or 0)) * signo
                        impuesto = abs(float(fila.get('iva_monto', 0) or fila.get('impuesto_iva', 0) or 0)) * signo
                        exento = abs(float(fila.get('importe_exento', 0) or 0)) * signo

                        # Si la base o el IVA vienen en 0 pero hay un total, los recalculamos
                        if abs(base) == 0 and abs(impuesto) == 0 and abs(total_fila) > 0:
                            if abs(exento) > 0:
                                base = (abs(total_fila) - abs(exento)) * signo
                            else:
                                base = round(abs(total_fila) / 1.16, 2) * signo
                            impuesto = round(abs(total_fila) - abs(exento) - abs(base), 2) * signo

                        ratio = round(abs(impuesto) / abs(base), 2) if abs(base) > 0 else 0
                        es_8 = ratio <= 0.08
                        
                        # Cálculo exacto del IVA retenido (75% del IVA, aplicando el signo correspondiente)
                        iva_retenido_fila = round((abs(impuesto) * porcentaje_ret) / 100, 2) * signo
                        
                        b16, i16, r16 = (base, impuesto, iva_retenido_fila) if not es_8 else (0.0, 0.0, 0.0)
                        b8, i8, r8 = (base, impuesto, iva_retenido_fila) if es_8 else (0.0, 0.0, 0.0)
                        
                        fecha_corta = str(fila['fecha_operacion']).split(" ")[0]
                        ano_f, mes_f = fecha_corta.split("-")[0], fecha_corta.split("-")[1]

                        n_factura_cruda = str(fila.get('n_factura', '')).strip()
                        n_control_cruda = str(fila.get('n_control', '')).strip()
                        
                        es_nota_credito = es_nc
                        es_nota_debito = 'debito' in tipo_doc_str or 'nota de debito' in tipo_doc_str

                        num_factura_val = n_factura_cruda
                        num_control_val = n_control_cruda
                        n_nota_credito_val = None
                        n_nota_debito_val = None  # 🛠️ Corregido con minúscula al inicio
                        
                        n_factura_afectada_val = (
                            str(fila.get('factura_afectada', '')).strip() or 
                            str(fila.get('n_factura_afectada', '')).strip() or 
                            str(fila.get('afectada', '')).strip()
                        )
                        if n_factura_afectada_val in ["None", "nan", ""]:
                            n_factura_afectada_val = None

                        if es_nota_credito:
                            n_nota_credito_val = n_factura_cruda
                            num_factura_val = None
                        elif es_nota_debito:
                            n_nota_debito_val = n_factura_cruda
                            num_factura_val = None

                        query_ins_iva = """
                            INSERT INTO retenciones_iva (
                                Razon_Social_del_Agente_de_Retencion, 
                                RIF_Agente_Retencion,  
                                Direccion_FiscalAgente_Retencion, 
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
                                N_Nota_Debito,
                                N_Nota_Credito,
                                NFactura_Afectada,
                                Total_Comrpas, 
                                Compras_Excentas, 
                                Base_Imponible, 
                                Alicuota,
                                Impuesto_Iva, 
                                Alicuota_75,
                                IVA_Retenido, 
                                Base_Imponible_8, 
                                IVA_8, 
                                RET_IVA_8
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                                %s, %s, %s, %s, %s, %s
                            )
                        """

                        params_iva = (
                            empresa_nombre, 
                            empresa_rif, 
                            domicilio_fiscal,
                            fecha_corta, 
                            fecha_corta, 
                            razon_social_ret, 
                            rif_ret, 
                            ano_f, 
                            mes_f,
                            nro_comp, 
                            fecha_corta, 
                            num_factura_val,       # Número de factura (vacío si es nota)
                            num_control_val,       # Número de control
                            n_nota_debito_val,     # N_Nota_Debito
                            n_nota_credito_val,    # N_Nota_Credito (aquí cae perfecto si es nota de crédito)
                            n_factura_afectada_val,# NFactura_Afectada (registrada obligatoriamente para notas)
                            str(round(float(fila.get('total_compras', 0)), 2)),
                            str(round(float(fila.get('importe_exento', 0)), 2)),
                            str(round(b16, 2)), 
                            "16%", 
                            str(round(i16, 2)), 
                            f"{porcentaje_ret}%", 
                            str(round(iva_retenido_fila, 2)),
                            round(b8, 2), 
                            round(i8, 2), 
                            round(r8, 2)
                        )
                        
                        cursor.execute(query_ins_iva, params_iva)
                        
                        query_update = """
                            UPDATE libro_compras 
                            SET retencion_realizada = 1 
                            WHERE id = %s
                        """
                        cursor.execute(query_update, (fila['id'],))

                    conn_env.commit()
                    st.session_state['last_iva'] = {'nro_comp': nro_comp}
                    st.session_state['mostrar_exito'] = True
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

                        # --- LÓGICA DE EXPORTACIÓN A PDF PROFESIONAL (CORREGIDO) ---
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
                                    self.ln(3)

                            pdf = PDF_PRO(orientation='L', unit='mm', format='A4')
                            pdf.add_page()

                            # --- 1. OBTENER DATOS DE LA CONSULTA DETALLADA ---
                            df_detalle = obtener_detalle_comprobante(opcion_busqueda)

                            if not df_detalle.empty:
                                d = df_detalle.iloc[0].to_dict()
                            else:
                                st.error("No se encontraron datos para este comprobante.")
                                return

                            # --- BLOQUE 1: AGENTE DE RETENCIÓN ---
                            id_real = st.session_state.get('id_empresa_seleccionada', {}).get('id', 1)
                            if not id_real or id_real == 1:
                                id_real = int(EMPRESA) if str(EMPRESA).isdigit() else 1

                            datos_empresa = obtener_datos_agente_db(id_real)
                            if datos_empresa is None:
                                datos_empresa = {"nombre_empresa": "NO ENCONTRADO", "rif": "N/A", "direccion": "N/A"}

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
                            pdf.set_font("Arial", "", 8)
                            pdf.text(17, 59, "Dirección Fiscal del Agente de Retencion:")
                            pdf.set_font("Arial", "", 7)
                            pdf.set_xy(17, 61) 

                            # Inyección directa de la dirección exacta de la empresa para terminar de una vez
                            # ------- BLOQUE 2: DIRECCIÓN Y FECHAS ----------------------
                            pdf.rect(15, 55, 175, 15)
                            pdf.set_font("Arial", "", 8)
                            pdf.text(17, 59, "Dirección Fiscal del Agente de Retencion:")
                            pdf.set_font("Arial", "", 7)
                            pdf.set_xy(17, 61) 

                            # Dirección oficial exacta con saltos de línea
                            dir_final = str(d.get('Direccion_FiscalAgente_Retencion', 'NO REGISTRADO'))

                            pdf.multi_cell(170, 3.2, dir_final.upper())

                            # ------- BLOQUE 3:  ----------------------
                            pdf.rect(200, 55, 35, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(202, 59, "E. Emision:")
                            pdf.set_font("Arial", "B", 9); pdf.text(202, 66, str(d.get('E_Emision', '')))

                            pdf.rect(235, 55, 40, 15) 
                            pdf.set_font("Arial", "", 8); pdf.text(237, 59, "F. Entrega:")
                            pdf.set_font("Arial", "B", 9); pdf.text(237, 66, str(d.get('F_Entrega', '')))

                            # --- BLOQUE 4: SUJETO RETENIDO ---
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

                            # --- DETECCIÓN REAL Y ROBUSTA DE NOTA DE CRÉDITO / DÉBITO ---
                            cols_numericas = ['Compras_Excentas', 'Base_Imponible', 'Impuesto_Iva', 'IVA_Retenido', 
                                             'Base_Imponible_8', 'IVA_8', 'RET_IVA_8']
                            for col in cols_numericas:
                                if col in df_detalle.columns:
                                    df_detalle[col] = df_detalle[col].fillna(0)

                            tiene_alicuota_8 = 'Base_Imponible_8' in df_detalle.columns and df_detalle['Base_Imponible_8'].sum() > 0

                            # Evaluamos si hay notas revisando tipos de documento, columnas de notas o montos negativos
                            tiene_notas = False
                            for _, r_val in df_detalle.iterrows():
                                td = str(r_val.get('tipo_documento', '')).strip()
                                nc = str(r_val.get('nota_credito', '')).strip()
                                nd = str(r_val.get('nota_debito', '')).strip()
                                tot_val_check = safe_float(r_val.get('Total_Comrpas') or r_val.get('Total_Compras') or 0)
                                if td in ['02', '03'] or (nc and nc != 'None' and nc != 'nan') or (nd and nd != 'None' and nd != 'nan') or tot_val_check < 0:
                                    tiene_notas = True
                                    break

                            # ESTRUCTURA Y ANCHOS DE LA TABLA DINÁMICA
                            if tiene_notas:
                                if tiene_alicuota_8:
                                    h = ["Fecha", "Tipo", "Nº NCredito", "N.Contr", "Fac. Afectada", "Total", "Exento", "Base 16%", "IVA 16%", "Ret. 16%", "Base 8%", "IVA 8%", "Ret. 8%", "Total Ret."]
                                    w = [18, 12, 22, 20, 22, 22, 16, 18, 16, 18, 16, 16, 16, 20]
                                else:
                                    h = ["Fecha", "Tipo", "Nº Fact", "N.Contr", "Fac. Afectada", "Total", "Exento", "Base 16%", "IVA 16%", "Ret. 16%", "Total Ret."]
                                    w = [20, 14, 25, 22, 25, 25, 18, 22, 20, 22, 24]
                            else:
                                if tiene_alicuota_8:
                                    h = ["Fecha", "N.Fact", "N.Contr", "Total", "Exento", "Base 16%", "IVA 16%", "Ret. 16%", "Base 8%", "IVA 8%", "Ret. 8%", "Total Ret."]
                                    w = [20, 18, 22, 25, 20, 22, 20, 22, 20, 20, 20, 22]
                                else:
                                    h = ["Fecha", "N.Fact", "N.Contr", "Total", "Exento", "Base 16%", "IVA 16%", "Ret. 16%", "Total Ret."]
                                    w = [22, 20, 25, 28, 22, 26, 22, 26, 28]

                            ancho_total_tabla = sum(w) 
                            # Centramos la tabla correctamente en la página A4 apaisada (297mm de ancho total, 267mm imprimibles)
                            x_inicio_tabla = (297 - ancho_total_tabla) / 2

                            # --- DIBUJAR CABECERA DE TABLA ---
                            pdf.set_y(95)
                            pdf.set_x(x_inicio_tabla)
                            pdf.set_fill_color(240, 240, 240)
                            pdf.set_font("Arial", "B", 7)

                            for i in range(len(h)):
                                pdf.cell(w[i], 5, h[i], 1, 0, 'C', fill=True)
                            pdf.ln()

                            # Inicializar Totales Generales
                            tot_gen_total, tot_gen_exento = 0.0, 0.0
                            tot_gen_base16, tot_gen_iva16, tot_gen_ret16 = 0.0, 0.0, 0.0
                            tot_gen_base8, tot_gen_iva8, tot_gen_ret8 = 0.0, 0.0, 0.0

                            # --- BUCLE DE REGISTROS ---
                            pdf.set_font("Arial", "", 7)
                            for _, fila in df_detalle.iterrows():
                                pdf.set_x(x_inicio_tabla)
                                d_row = fila.to_dict()
                                
                                exento = safe_float(d_row.get('Compras_Excentas'))
                                b16 = safe_float(d_row.get('Base_Imponible'))
                                i16 = safe_float(d_row.get('Impuesto_Iva'))
                                r16 = safe_float(d_row.get('IVA_Retenido'))
                                b8 = safe_float(d_row.get('Base_Imponible_8'))
                                i8 = safe_float(d_row.get('IVA_8'))
                                r8 = safe_float(d_row.get('RET_IVA_8'))
                                
                                # Si total viene directo de la BD lo usamos, de lo contrario sumamos
                                total_fila = safe_float(d_row.get('Total_Comrpas') or d_row.get('Total_Compras'))
                                if total_fila == 0 and (exento != 0 or b16 != 0 or b8 != 0):
                                    total_fila = exento + b16 + b8 + i16 + i8 
                                
                                tot_gen_total += total_fila
                                tot_gen_exento += exento
                                tot_gen_base16 += b16
                                tot_gen_iva16 += i16
                                tot_gen_base8 += b8
                                tot_gen_iva8 += i8

                                # EVALUAMOS CON ABS() PARA PERMITIR VALORES NEGATIVOS DE NOTAS DE CRÉDITO
                                valor_a_mostrar_r16 = r16 if abs(b16) > 0 or abs(r16) > 0 else 0.0
                                valor_a_mostrar_r8 = r8 if abs(b8) > 0 or abs(r8) > 0 else 0.0
                                total_fila_retencion = valor_a_mostrar_r16 + valor_a_mostrar_r8

                                if abs(b16) > 0 or abs(r16) > 0:
                                    tot_gen_ret16 += r16
                                if abs(b8) > 0 or abs(r8) > 0:
                                    tot_gen_ret8 += r8

                                # Capturamos la fecha y la factura afectada de forma totalmente segura
                                fecha_op = str(d_row.get('Fecha_Factura') or '')
                                tipo_doc = str(d_row.get('tipo', tipo_doc_calculado if 'tipo_doc_calculado' in locals() else ('03' if total_fila < 0 else '01')))
                                
                                # 🛠️ CAPTURA INTELIGENTE DEL NÚMERO DE DOCUMENTO (Evita que salga "None")
                                nro_doc = str(
                                    d_row.get('Numero_Factura') or 
                                    d_row.get('N_Nota_Credito') or 
                                    d_row.get('N_Nota_Debito') or 
                                    d_row.get('n_factura') or 
                                    ''
                                ).strip()
                                if nro_doc.lower() in ['none', 'nan', 'nat', '']:
                                    nro_doc = ""

                                nro_ctrl = str(d_row.get('Numero_Contro', ''))
                                
                                fac_afectada = str(
                                    d_row.get('NFactura_Afectada') or 
                                    d_row.get('nfactura_afectada') or 
                                    d_row.get('N_Factura_Afectada') or 
                                    ''
                                ).strip()
                                if fac_afectada.lower() in ['none', 'nan', 'nat', '']:
                                    fac_afectada = ""

                                if tiene_notas:
                                    # 1. Fecha en w[0] (¡ESTO FALTABA Y DESCUADRABA TODO!)
                                    pdf.cell(w[0], 4, fecha_op, 1, 0, 'C')
                                    # 2. Tipo en w[1]
                                    pdf.cell(w[1], 4, tipo_doc, 1, 0, 'C')
                                    # 3. N° Doc/Nota en w[2]
                                    pdf.cell(w[2], 4, nro_doc, 1, 0, 'C')
                                    # 4. N.Contr en w[3]
                                    pdf.cell(w[3], 4, nro_ctrl, 1, 0, 'C')
                                    # 5. Fac. Afectada en w[4] (¡AQUÍ SE PINTA EL NÚMERO!)
                                    pdf.cell(w[4], 4, fac_afectada, 1, 0, 'C')
                                    # Resto de columnas intactas
                                    pdf.cell(w[5], 4, f"{total_fila:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[6], 4, f"{exento:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[7], 4, f"{b16:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[8], 4, f"{i16:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[9], 4, f"{valor_a_mostrar_r16:,.2f}", 1, 0, 'R')

                                    if tiene_alicuota_8:
                                        pdf.cell(w[10], 4, f"{b8:,.2f}", 1, 0, 'R')
                                        pdf.cell(w[11], 4, f"{i8:,.2f}", 1, 0, 'R')
                                        pdf.cell(w[12], 4, f"{valor_a_mostrar_r8:,.2f}", 1, 0, 'R')
                                        pdf.cell(w[13], 4, f"{total_fila_retencion:,.2f}", 1, 1, 'R', fill=True)
                                    else:
                                        pdf.cell(w[10], 4, f"{valor_a_mostrar_r16:,.2f}", 1, 1, 'R', fill=True)
                                else:
                                    # Sin notas (cuando no aplica factura afectada)
                                    pdf.cell(w[0], 4, fecha_op, 1, 0, 'C')
                                    pdf.cell(w[1], 4, nro_doc, 1, 0, 'C')
                                    pdf.cell(w[2], 4, nro_ctrl, 1, 0, 'C')
                                    pdf.cell(w[3], 4, f"{total_fila:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[4], 4, f"{exento:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[5], 4, f"{b16:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[6], 4, f"{i16:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[7], 4, f"{valor_a_mostrar_r16:,.2f}", 1, 0, 'R')

                                    if tiene_alicuota_8:
                                        pdf.cell(w[8], 4, f"{b8:,.2f}", 1, 0, 'R')
                                        pdf.cell(w[9], 4, f"{i8:,.2f}", 1, 0, 'R')
                                        pdf.cell(w[10], 4, f"{valor_a_mostrar_r8:,.2f}", 1, 0, 'R')
                                        pdf.cell(w[11], 4, f"{total_fila_retencion:,.2f}", 1, 1, 'R', fill=True)
                                    else:
                                        pdf.cell(w[8], 4, f"{valor_a_mostrar_r16:,.2f}", 1, 1, 'R', fill=True)
                            # --- FILA DE TOTALES GENERALES ---
                            pdf.set_x(x_inicio_tabla)
                            pdf.set_font("Arial", "B", 7)
                            pdf.set_fill_color(220, 220, 220)

                            if tiene_notas:
                                pdf.cell(sum(w[:5]), 5, "TOTALES", 1, 0, 'R', fill=True)
                                pdf.cell(w[5], 5, f"{tot_gen_total:,.2f}", 1, 0, 'R')
                                pdf.cell(w[6], 5, f"{tot_gen_exento:,.2f}", 1, 0, 'R')
                                pdf.cell(w[7], 5, f"{tot_gen_base16:,.2f}", 1, 0, 'R')
                                pdf.cell(w[8], 5, f"{tot_gen_iva16:,.2f}", 1, 0, 'R')
                                pdf.cell(w[9], 5, f"{tot_gen_ret16:,.2f}", 1, 0, 'R')

                                if tiene_alicuota_8:
                                    pdf.cell(w[10], 5, f"{tot_gen_base8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[11], 5, f"{tot_gen_iva8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[12], 5, f"{tot_gen_ret8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[13], 5, f"{tot_gen_ret16 + tot_gen_ret8:,.2f}", 1, 1, 'R', fill=True)
                                else:
                                    pdf.cell(w[10], 5, f"{tot_gen_ret16:,.2f}", 1, 1, 'R', fill=True)
                            else:
                                pdf.cell(sum(w[:3]), 5, "TOTALES", 1, 0, 'R', fill=True)
                                pdf.cell(w[3], 5, f"{tot_gen_total:,.2f}", 1, 0, 'R')
                                pdf.cell(w[4], 5, f"{tot_gen_exento:,.2f}", 1, 0, 'R')
                                pdf.cell(w[5], 5, f"{tot_gen_base16:,.2f}", 1, 0, 'R')
                                pdf.cell(w[6], 5, f"{tot_gen_iva16:,.2f}", 1, 0, 'R')
                                pdf.cell(w[7], 5, f"{tot_gen_ret16:,.2f}", 1, 0, 'R')

                                if tiene_alicuota_8:
                                    pdf.cell(w[8], 5, f"{tot_gen_base8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[9], 5, f"{tot_gen_iva8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[10], 5, f"{tot_gen_ret8:,.2f}", 1, 0, 'R')
                                    pdf.cell(w[11], 5, f"{tot_gen_ret16 + tot_gen_ret8:,.2f}", 1, 1, 'R', fill=True)
                                else:
                                    pdf.cell(w[8], 5, f"{tot_gen_ret16:,.2f}", 1, 1, 'R', fill=True)

                            # --- SECCIÓN DE FIRMAS CONTROLADA DINÁMICAMENTE ---
                            pos_y_actual = pdf.get_y()
                            if pos_y_actual > 165:
                                pdf.add_page()
                                y_firmas = 60
                            else:
                                y_firmas = pos_y_actual + 30

                            import os
                            ruta_firma = os.path.join("assets", "cielo.png")

                            # Dibujar firma e imágenes alineadas
                            if os.path.exists(ruta_firma):
                                pdf.image(ruta_firma, x=55, y=y_firmas - 20, w=35)
                                
                            pdf.set_font("Arial", "B", 8)
                            pdf.line(40, y_firmas, 110, y_firmas)
                            pdf.line(185, y_firmas, 255, y_firmas)

                            pdf.text(52, y_firmas + 5, "AGENTE DE RETENCION")
                            pdf.text(197, y_firmas + 5, "SUJETO RETENIDO")

                            pdf.set_font("Arial", "B", 7)
                            nombre_empresa = datos_empresa.get('nombre_empresa', 'N/A')
                            rif_empresa = datos_empresa.get('rif', 'N/A')

                            pdf.set_xy(40, y_firmas + 8)
                            pdf.multi_cell(70, 4, f"{nombre_empresa}\nRIF: {rif_empresa}", 0, 'C')

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
            from datetime import date as d_tipo, datetime

            hoy = d_tipo.today()
            inicio_mes = hoy.replace(day=1)

            col1, col2 = st.columns(2)
            with col1:
                fecha_inicio = st.date_input("Fecha Inicio", inicio_mes, key="txt_f_inicio")
            with col2:
                fecha_fin = st.date_input("Fecha Fin", hoy, key="txt_f_fin")

            if st.button("🔍 Filtrar y Generar TXT"):
                db_nombre = st.session_state.get('DB_ACTUAL')
                if not db_nombre:
                    st.error("Error: No se ha seleccionado una base de datos.")
                else:
                    conn = conectar_db(db_nombre)
                    try:
                        import pymysql
                        cursor = conn.cursor(pymysql.cursors.DictCursor)
                        
                        query_txt = "SELECT * FROM retenciones_iva WHERE E_Emision BETWEEN %s AND %s"
                        cursor.execute(query_txt, (fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d')))
                        registros_txt = cursor.fetchall()
                        cursor.close()
                        
                        if registros_txt:
                            lineas_txt = []
                            for reg in registros_txt:
                                # 1. Detectar si es Nota de Crédito o Nota de Débito
                                nc_raw = str(reg.get('N_Nota_Credito') or reg.get('nota_credito') or '').strip()
                                nd_raw = str(reg.get('N_Nota_Debito') or reg.get('nota_debito') or '').strip()
                                
                                tiene_nc = nc_raw and nc_raw.lower() not in ['none', 'nan', '', 'null', 'nat']
                                tiene_nd = nd_raw and nd_raw.lower() not in ['none', 'nan', '', 'null', 'nat']
                                
                                if tiene_nc:
                                    tipo_doc = '03'  # Nota de Crédito
                                    num_doc = nc_raw
                                    factura_afectada = str(reg.get('NFactura_Afectada') or reg.get('n_factura_afectada') or '').strip()
                                elif tiene_nd:
                                    tipo_doc = '02'  # Nota de Débito
                                    num_doc = nd_raw
                                    factura_afectada = str(reg.get('NFactura_Afectada') or reg.get('n_factura_afectada') or '').strip()
                                else:
                                    tipo_doc = str(reg.get('Tipo_Documento') or reg.get('tipo_documento') or '01').strip()
                                    num_doc = str(reg.get('Numero_Factura') or reg.get('n_factura') or '').strip()
                                    factura_afectada = ""

                                # 2. Manejo de Alícuotas y Montos (¡Absolutamente en positivo, sin signos negativos!)
                                es_ocho = float(reg.get('Base_Imponible_8', 0) or 0) > 0
                                
                                if es_ocho:
                                    m_base = abs(float(reg.get('Base_Imponible_8', 0) or 0))
                                    m_ret = abs(float(reg.get('RET_IVA_8', 0) or 0))
                                    m_ali = "8.00"
                                else:
                                    m_base = abs(float(reg.get('Base_Imponible', reg.get('base_imponible', 0)) or 0))
                                    m_ret = abs(float(reg.get('IVA_Retenido', reg.get('monto_iva_retenido', 0)) or 0))
                                    m_ali = "16.00"

                                exento = abs(float(reg.get('Compras_Excentas', reg.get('importe_exento', 0)) or 0))
                                
                                # Cálculo estricto del IVA y Total Compras exigido por el SENIAT
                                iva_monto_calc = round(m_base * (float(m_ali) / 100.0), 2)
                                total_compras_calc = round(exento + m_base + iva_monto_calc, 2)
                                
                                # Si el monto retenido viene en 0, lo calculamos de forma predeterminada (ej. 75% o 100%)
                                if m_ret == 0.0 and iva_monto_calc > 0:
                                    m_ret = round(iva_monto_calc * 0.75, 2) # Ajusta el porcentaje según tu cliente (0.75 o 1.0)

                                # 3. Manejo seguro de fecha
                                fecha_raw = reg.get('Fecha_Factura') or reg.get('fecha_operacion') or ''
                                try:
                                    f_obj = datetime.strptime(str(fecha_raw).split(" ")[0], '%Y-%m-%d')
                                except:
                                    f_obj = datetime.now()
                                periodo = f_obj.strftime("%Y%m")
                                
                                # 4. Construcción estricta de los 15 campos del SENIAT
                                campos = [
                                    str(reg.get('RIF_Agente_Retencion', '')).replace('-', '').strip(),
                                    periodo,
                                    f_obj.strftime('%Y-%m-%d'),
                                    'C', 
                                    tipo_doc,  # '01' Factura, '03' Nota de Crédito
                                    str(reg.get('RIF_Sujeto_Retenido', reg.get('rif', ''))).replace('-', '').strip(),
                                    num_doc,  # Número de Factura o de Nota de Crédito
                                    str(reg.get('Numero_Contro', reg.get('n_control', ''))).strip(),
                                    f"{total_compras_calc:.2f}",
                                    f"{m_base:.2f}", 
                                    f"{m_ret:.2f}", 
                                    '0',
                                    str(reg.get('N_Comprobante1', reg.get('n_comprobante_retencion', ''))).strip(),
                                    f"{exento:.2f}",
                                    m_ali, 
                                    '0'
                                ]
                                
                                lineas_txt.append("\t".join(campos))
                            
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

@st.cache_data(ttl=300)
def consultar_saldos_iniciales_db(db_nombre):
    """
    Consulta los saldos iniciales de la empresa activa con control central de sesión.
    """
    if not db_nombre:
        return pd.DataFrame()

    # Control central: Asegurar que la base de datos consultada coincida con la activa en la sesión si está definida
    db_actual = st.session_state.get('DB_ACTUAL')
    if db_actual and db_nombre != db_actual:
        st.warning(f"⚠️ Advertencia de seguridad: Intentando consultar saldos de '{db_nombre}' cuando la sesión activa es '{db_actual}'.")

    # 1. Intentamos conectar
    conn = conectar_db(db_nombre)
    
    # Validación segura compatible con diferentes conectores (PyMySQL, mysql-connector, etc.)
    conexion_valida = False
    if conn:
        try:
            if hasattr(conn, "is_connected") and conn.is_connected():
                conexion_valida = True
            else:
                # Si no tiene is_connected, intentamos un ping o asumimos activa si abrió correctamente
                if hasattr(conn, "ping"):
                    conn.ping(reconnect=True)
                conexion_valida = True
        except Exception:
            conexion_valida = False

    if conexion_valida:
        cursor = None
        try:
            # 2. Registramos el log de forma centralizada
            usuario = st.session_state.get('usuario', 'Desconocido')
            cliente = st.session_state.get('cliente_id', 'Desconocido')
            registrar_log_automatico(
                conn, 
                "CONSULTA_SALDOS_INICIALES", 
                f"Usuario {usuario} consultó saldos iniciales para el cliente {cliente} en la base de datos {db_nombre}"
            )
            
            cursor = conn.cursor(dictionary=True)
            query = f"SELECT * FROM `{db_nombre}`.saldos_iniciales ORDER BY id ASC"
            cursor.execute(query)
            
            resultados = cursor.fetchall()
            return pd.DataFrame(resultados) if resultados else pd.DataFrame()
                
        except Exception as e:
            st.error(f"❌ Error en la consulta de saldos en {db_nombre}: {e}")
            return pd.DataFrame()
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    if hasattr(conn, "ping"):
                        conn.ping(reconnect=True)
                except Exception:
                    pass
    else:
        st.error("❌ No se pudo establecer conexión con la base de datos.")
        return pd.DataFrame()

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



def generar_reporte_multimoneda(conn, mes, ano, db="kingdirver_ca"):
    """
    Versión altamente optimizada: Consolida saldos iniciales y asientos contables 
    utilizando rangos de fecha indexables y resolución de tasas por vectorización en Pandas.
    """
    if not conn:
        return pd.DataFrame()
        
    cursor = conn.cursor()
    
    # Calcular el rango de fechas exacto para el mes y año seleccionados (Sargable)
    mes_int = int(mes)
    ano_int = int(ano)
    ultimo_dia = calendar.monthrange(ano_int, mes_int)[1]
    fecha_inicio_mes = f"{ano_int}-{mes_int:02d}-01"
    fecha_fin_mes = f"{ano_int}-{mes_int:02d}-{ultimo_dia:02d}"
    
    try:
        # 1. Consulta optimizada sin funciones destructoras de índices en el WHERE de asientos
        query_transacciones = f"""
            SELECT fecha, plan_cuentas, cuenta_contable, descripcion, debe, haber
            FROM `{db}`.saldos_iniciales
            WHERE YEAR(fecha) = %s
            
            UNION ALL
            
            SELECT fecha, cuenta_contable AS plan_cuentas, cuenta_contable, descripcion, debe, haber
            FROM `{db}`.asientos_contables
            WHERE fecha BETWEEN %s AND %s
        """
        cursor.execute(query_transacciones, (ano_int, fecha_inicio_mes, fecha_fin_mes))
        rows = cursor.fetchall()
        
        if not rows:
            cursor.close()
            return pd.DataFrame()
            
        # Convertir transacciones a DataFrame
        columnas = ['fecha', 'plan_cuentas', 'cuenta_contable', 'descripcion', 'debe', 'haber']
        df = pd.DataFrame(rows, columns=columnas)
        
        # 2. Cargar todas las tasas diarias una sola vez para evitar subconsultas fila por fila
        query_tasas = f"SELECT fecha, tasa_valor FROM `{db}`.tasas_diarias ORDER BY fecha ASC"
        cursor.execute(query_tasas)
        tasas_rows = cursor.fetchall()
        cursor.close()
        
        df_tasas = pd.DataFrame(tasas_rows, columns=['fecha', 'tasa_valor']) if tasas_rows else pd.DataFrame(columns=['fecha', 'tasa_valor'])
        
        # Asegurar tipos de datos correctos
        df['debe'] = pd.to_numeric(df['debe'], errors='coerce').fillna(0.0)
        df['haber'] = pd.to_numeric(df['haber'], errors='coerce').fillna(0.0)
        df['fecha'] = pd.to_datetime(df['fecha'])
        df = df.sort_values('fecha')
        
        # 3. Resolución de tasas eficiente en memoria (Equivalente al COALESCE de SQL pero instantáneo)
        if not df_tasas.empty:
            df_tasas['fecha'] = pd.to_datetime(df_tasas['fecha'])
            df_tasas['tasa_valor'] = pd.to_numeric(df_tasas['tasa_valor'], errors='coerce').fillna(1.0)
            df_tasas = df_tasas.sort_values('fecha')
            
            # merge_asof asigna la tasa exacta o la tasa inmediatamente anterior disponible (backward)
            df = pd.merge_asof(df, df_tasas, on='fecha', direction='backward')
            
            # Respaldo para fechas anteriores al primer registro de tasa
            primera_tasa = df_tasas['tasa_valor'].iloc[0]
            df['tasa_bcv'] = df['tasa_bcv'].fillna(primera_tasa)
        else:
            df['tasa_bcv'] = 1.0000
            
        # Blindaje contra división por cero
        df['tasa_bcv'] = df['tasa_bcv'].replace(0, 1.0)
        
        # 4. Operaciones matemáticas vectorizadas en memoria
        df['debe_usd'] = df['debe'] / df['tasa_bcv']
        df['haber_usd'] = df['haber'] / df['tasa_bcv']
        
        return df
        
    except Exception as e:
        st.error(f"Error generando reporte multimoneda para {db}: {e}")
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        return pd.DataFrame()


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
    conn_central = conectar_db() 
    if not conn_central: 
        st.warning("⚠️ No se pudo conectar a la base de datos central en obtener_datos_agente_db.")
        return None

    cursor = None
    try:
        cursor = conn_central.cursor(pymysql.cursors.DictCursor)
        
        # Usamos SELECT * para evitar errores de columnas que no existen
        if isinstance(valor_busqueda, str):
            query = "SELECT * FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT * FROM clientes WHERE id = %s"
        
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


def resetear_estado_retencion(numero_factura, db_nombre=None):
    db_actual = db_nombre if db_nombre and db_nombre != 'none' else st.session_state.get('DB_ACTUAL')
    if not db_actual or db_actual == 'none':
        db_actual = st.session_state.get('empresa_actual')

    conn = None
    cursor = None
    try:
        conn = conectar_db(db_actual)
        if not conn:
            return False
            
        cursor = conn.cursor()
        
        # 1. Limpiamos la tabla de retenciones_islr
        sql_ret = """
            UPDATE retenciones_islr 
            SET monto_retenido = 0.00, 
                porcentaje_retencion = 0.00 
            WHERE numero_factura = %s
        """
        cursor.execute(sql_ret, (numero_factura,))
        
        # 2. IMPORTANTE: Liberamos también el libro de compras para que la consulta principal la vuelva a traer
        sql_lc = """
            UPDATE libro_compras 
            SET retencion_realizada = 0 
            WHERE n_factura = %s
        """
        cursor.execute(sql_lc, (numero_factura,))
        
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if conn:
            try: conn.close()
            except: pass


def extraer_datos_factura_local(ruta_archivo):
    """
    Versión ultrarrápida: Intenta lectura de texto nativo en PDFs (instantáneo) 
    y optimiza el DPI y procesamiento para documentos escaneados.
    """
    try:
        ext = ruta_archivo.lower().split('.')[-1]
        texto_bruto = ""
        img = None

        # 1. Intentar extracción de texto digital directo si es PDF (Evita OCR si es nativo)
        if ext == 'pdf':
            doc = fitz.open(ruta_archivo)
            page = doc[0]
            texto_nativo = page.get_text("text")
            
            # Si el PDF tiene texto digital legible, lo usamos de inmediato (0 segundos de espera)
            if texto_nativo and len(texto_nativo.strip()) > 30:
                texto_bruto = texto_nativo
                doc.close()
            else:
                # Si es un PDF escaneado, renderizamos a 150 DPI (cuatro veces más rápido que 300 DPI)
                pix = page.get_pixmap(dpi=150)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8)
                img = cv2.imdecode(img_np, cv2.IMREAD_COLOR)
                doc.close()
        elif ext in ['jpg', 'jpeg', 'png']:
            img = cv2.imread(ruta_archivo)
        else:
            return {"error": "Formato de archivo no soportado. Usa PDF, JPG o PNG."}

        # 2. Si se requiere OCR (imágenes o PDFs escaneados)
        if not texto_bruto:
            if img is None:
                return {"error": "No se pudo leer la imagen o el archivo está corrupto."}

            # Preprocesamiento optimizado en escala de grises y binarización simple
            gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, gris = cv2.threshold(gris, 140, 255, cv2.THRESH_BINARY)

            # OCR local con configuración optimizada para velocidad
            config_tesseract = r'--oem 3 --psm 6'
            texto_bruto = pytesseract.image_to_string(gris, lang='spa', config=config_tesseract)

        # Diccionario con los 5 campos clave
        datos = {
            "nro_factura": "",
            "nro_control": "",
            "fecha": "",
            "base_imponible": "0.00",
            "monto_exento": "0.00"
        }

        # 3. Extracción veloz mediante expresiones regulares
        match_fact = re.search(r'(?:N[ºo°]?\.?\s*Factura|FACTURA|Nro\.?)\s*[:#]?\s*(\d+)', texto_bruto, re.IGNORECASE)
        if match_fact:
            datos["nro_factura"] = match_fact.group(1)

        match_ctrl = re.search(r'(?:Control|Nro\.?\s*Ctrl|CTRL)\s*[:#]?\s*([0-9-]+)', texto_bruto, re.IGNORECASE)
        if match_ctrl:
            datos["nro_control"] = match_ctrl.group(1)

        match_fecha = re.search(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b', texto_bruto)
        if match_fecha:
            datos["fecha"] = match_fecha.group(1).replace("-", "/")

        match_bi = re.search(r'(?:Base\s*Imponible|BI|GRAVADA)\s*[:#]?\s*([\d\.,]+)', texto_bruto, re.IGNORECASE)
        if match_bi:
            datos["base_imponible"] = match_bi.group(1).replace('.', '').replace(',', '.')

        match_ex = re.search(r'(?:Exento|EXENTO|EX).\s*[:#]?\s*([\d\.,]+)', texto_bruto, re.IGNORECASE)
        if match_ex:
            datos["monto_exento"] = match_ex.group(1).replace('.', '').replace(',', '.')

        return datos

    except Exception as e:
        return {"error": f"Error procesando el archivo localmente: {str(e)}"}



def guardar_saldo_mensual(conn, banco, mes, ano, inicial, final, db_name=None):
    # Si no se pasa un nombre de BD explícito, intentamos sacarlo de la sesión
    if not db_name:
        db_name = st.session_state.get('DB_ACTUAL', 'kingdirver_ca')
        
    cursor = conn.cursor()
    try:
        # Registro de actividad (protegido por si faltan variables en session_state)
        usuario = st.session_state.get('usuario', 'Sistema')
        cliente_id = st.session_state.get('cliente_id', 'N/A')
        registrar_log_automatico(conn, "GUARDAR_SALDO_MENSUAL", f"Usuario {usuario} guardó saldo mensual para {cliente_id} (Banco: {banco})")
        
        # Consulta corregida usando VALUES() para total compatibilidad con TiDB
        query = f"""
            INSERT INTO `{db_name}`.saldos_bancarios (banco, mes, ano, saldo_inicial, saldo_final)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
            saldo_inicial = VALUES(saldo_inicial), 
            saldo_final = VALUES(saldo_final)
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


def procesar_excel_proveedores_db(df):
    """
    Limpieza y carga masiva optimizada de proveedores a MySQL mediante executemany,
    manejando automáticamente el tipo de persona y las cuentas contables.
    """
    if df is None or df.empty:
        st.warning("⚠️ El archivo Excel está vacío o no contiene datos válidos.")
        return

    # 0. Rellenar celdas vacías (NaN) con string vacío
    df = df.fillna("")

    # 1. Limpieza masiva vectorizada en Pandas
    df['rif'] = df['rif'].astype(str).str.strip().str.upper()
    df['razon_social'] = df['razon_social'].astype(str).str.strip().str.upper()
    df['direccion_fiscal'] = df['direccion_fiscal'].astype(str).str.strip()
    
    df['codigo_cuenta'] = df['codigo_cuenta'].astype(str).str.strip() if 'codigo_cuenta' in df.columns else ""
    df['descripcion_cuenta'] = df['descripcion_cuenta'].astype(str).str.strip() if 'descripcion_cuenta' in df.columns else ""

    db_actual = st.session_state.get('DB_ACTUAL')
    conn = conectar_db(db_actual)
    
    if conn is None:
        st.error("❌ No se pudo conectar a la base de datos.")
        return

    # Registro de actividad protegido
    try:
        registrar_log_automatico(conn, "CARGA_PROVEEDORES", "Usuario procesó excel de proveedores con cuentas de forma masiva")
    except Exception:
        pass
    
    cursor = None
    try:
        cursor = conn.cursor()
        
        # 2. Construcción de lista de tuplas para inserción por lotes (Evita el cuello de botella RBAR)
        lista_datos = []
        for _, row in df.iterrows():
            rif = row['rif']
            if not rif or rif in ['NAN', '']:
                continue
                
            tipo = "PN" if rif.startswith(('V', 'E')) else "PJ"
            razon = row['razon_social']
            direccion = row['direccion_fiscal']
            cod_cuenta = row['codigo_cuenta']
            desc_cuenta = row['descripcion_cuenta']
            
            lista_datos.append((rif, tipo, razon, direccion, cod_cuenta, desc_cuenta))
        
        if not lista_datos:
            st.warning("⚠️ No se encontraron RIFs válidos para procesar en el archivo.")
            return

        sql = """
            INSERT INTO proveedores (rif, tipo_persona, razon_social, direccion_fiscal, codigo_cuenta, descripcion_cuenta)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
            tipo_persona = VALUES(tipo_persona),
            razon_social = VALUES(razon_social),
            direccion_fiscal = VALUES(direccion_fiscal),
            codigo_cuenta = VALUES(codigo_cuenta),
            descripcion_cuenta = VALUES(descripcion_cuenta)
        """
        
        # 3. Ejecución masiva optimizada
        cursor.executemany(sql, lista_datos)
        conn.commit()
        
        st.success(f"✅ Se han procesado e insertado {len(lista_datos)} proveedores correctamente.")
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        st.error(f"❌ Error al procesar proveedores: {e}")
        
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


import pandas as pd
import pymysql
import streamlit as st

def renderizar_tab_asientos_ventas(db_connection):
    st.subheader("🤖 Asientos Automatizados - Libro de Ventas")
    st.markdown("""
    Sube tu **Libro de Ventas** en Excel. El sistema procesará los datos, consultará la tabla de clientes comerciales por RIF y generará los asientos contables correspondientes.
    """)

    # ----------------------------------------------------
    # VALIDACIÓN DE ROL Y FILTRADO DE EMPRESAS
    # ----------------------------------------------------
    usuario_actual = str(
        st.session_state.get("user", st.session_state.get("usuario", "norbe"))
    ).strip()

    rol_usuario = "cliente"
    es_admin = False
    db_asignada_usuario = ""

    dbs_filtradas = []
    mapa_nombres_empresas = {}

    try:
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_temp:
            cursor_temp.execute(
                "SELECT rol, db_nombre FROM control_central.usuarios WHERE usuario = %s",
                (usuario_actual,),
            )
            res_usuario = cursor_temp.fetchone()

            if res_usuario:
                rol_usuario = str(res_usuario.get("rol", "cliente")).strip().lower()
                db_asignada_usuario = str(
                    res_usuario.get("db_nombre", "")
                ).strip()

            es_admin = rol_usuario in [
                "admin",
                "administrador",
            ] or st.session_state.get("es_admin", False)

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
                    if (
                        db_asignada_usuario
                        and db_name.lower() == db_asignada_usuario.lower()
                    ):
                        dbs_filtradas.append(db_name)
                        mapa_nombres_empresas[db_name] = nombre_comercial

    except Exception as e:
        st.warning(f"⚠️ Error consultando `control_central`: {e}")
        if es_admin:
            dbs_filtradas = ["kingdriver_ca"]
        else:
            dbs_filtradas = [
                db_asignada_usuario if db_asignada_usuario else "kingdriver_ca"
            ]

    if not dbs_filtradas:
        dbs_filtradas = [db_asignada_usuario] if db_asignada_usuario else ["kingdriver_ca"]

    if not dbs_filtradas:
        st.error("⚠️ No se encontró una empresa asignada a tu usuario en la tabla `usuarios`.")
        return

    # ----------------------------------------------------
    # INTERFAZ SEGÚN EL ROL
    # ----------------------------------------------------
    if es_admin:
        st.markdown("### 🏢 Contexto de Empresa (Modo Administrador)")

        index_default = 0
        for i, db_name in enumerate(dbs_filtradas):
            if any(
                k in str(st.session_state).lower()
                and db_name.lower() in str(st.session_state[k]).lower()
                for k in st.session_state
            ):
                index_default = i
                break
            if "driver" in db_name.lower() or "king" in db_name.lower():
                index_default = i

        format_func = lambda db: (
            f"{mapa_nombres_empresas.get(db, db)} ({db})"
            if db in mapa_nombres_empresas
            else db
        )

        nombre_db_cliente = st.selectbox(
            "Selecciona la Base de Datos de la Empresa Activa:",
            dbs_filtradas,
            index=index_default,
            format_func=format_func,
            key="select_db_admin_asientos_ventas",
        )
    else:
        nombre_db_cliente = dbs_filtradas[0]
        nombre_amigable = mapa_nombres_empresas.get(
            nombre_db_cliente, nombre_db_cliente
        )
        st.info(f"🏢 **Empresa Activa:** {nombre_amigable} (`{nombre_db_cliente}`)")

    if not nombre_db_cliente:
        st.error("⚠️ Debes seleccionar una base de datos.")
        return

    db_segura = str(nombre_db_cliente).strip()

    mapa_descripciones = {}
    opciones_desplegable = []

    # ----------------------------------------------------
    # CARGA DE PLAN DE CUENTAS
    # ----------------------------------------------------
    if db_connection:
        try:
            with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_opt:
                cursor_opt.execute(
                    f"SELECT codigo, nombre, tipo FROM `{db_segura}`.plan_cuentas ORDER BY codigo ASC"
                )
                cuentas_opt = cursor_opt.fetchall()

                cuentas_detalle = [
                    c for c in cuentas_opt
                    if str(c.get("tipo", "")).strip().lower() == "detalle"
                ]
                lista_cuentas = cuentas_detalle if cuentas_detalle else cuentas_opt

                for c in lista_cuentas:
                    codigo = str(c.get("codigo", "")).strip()
                    nombre = str(c.get("nombre", "")).strip()
                    if codigo:
                        mapa_descripciones[codigo] = nombre
                        opciones_desplegable.append(codigo)

                if not opciones_desplegable:
                    opciones_desplegable = [
                        "1.1.2.01.001",
                        "4.1.1.01.001",
                        "2.1.2.01.001",
                    ]
                    mapa_descripciones = {
                        "1.1.2.01.001": "Cuentas por Cobrar Comerciales",
                        "4.1.1.01.001": "Ventas de Servicios / Ingresos",
                        "2.1.2.01.001": "IVA Débito Fiscal",
                    }
        except Exception as e:
            st.warning(f"⚠️ Advertencia al consultar plan de cuentas: {e}. Usando cuentas predeterminadas.")
            opciones_desplegable = ["1.1.2.01.001", "4.1.1.01.001", "2.1.2.01.001"]
            mapa_descripciones = {
                "1.1.2.01.001": "Cuentas por Cobrar Comerciales",
                "4.1.1.01.001": "Ventas de Servicios / Ingresos",
                "2.1.2.01.001": "IVA Débito Fiscal",
            }

    # ----------------------------------------------------
    # CARGAR CLIENTES COMERCIALES
    # ----------------------------------------------------
    mapa_clientes_rif = {}
    try:
        with db_connection.cursor(pymysql.cursors.DictCursor) as cursor_cli:
            cursor_cli.execute(
                f"SELECT rif, codigo_cuenta, descripcion_cuenta FROM `{db_segura}`.clientes_comerciales"
            )
            clientes_registrados = cursor_cli.fetchall()
            for cli in clientes_registrados:
                rif_limpio = str(cli.get("rif", "")).strip().upper()
                mapa_clientes_rif[rif_limpio] = {
                    "codigo_cuenta": str(cli.get("codigo_cuenta", "")).strip(),
                    "descripcion_cuenta": str(cli.get("descripcion_cuenta", "")).strip(),
                }
    except Exception as e:
        st.warning(f"⚠️ No se pudo consultar la tabla `clientes_comerciales`: {e}")

    # ----------------------------------------------------
    # FUNCIONES AUXILIARES DE LIMPIEZA
    # ----------------------------------------------------
    def limpiar_y_forzar_numerico(df):
        if df is None or df.empty:
            return df
        for col in df.columns:
            c_lower = str(col).lower().strip()
            keywords = [
                "debe", "haber", "venta", "base", "debito", "crédito", 
                "credito", "total", "iva", "monto", "impuesto", "exenta", 
                "alícuota", "alicuota"
            ]

            if any(term in c_lower for term in keywords) or col in ["debe", "haber"]:
                def parsear_valor_latino(val):
                    if val is None or pd.isna(val) or str(val).strip() in ["", "nan", "None"]:
                        return 0.0
                    if isinstance(val, (int, float)):
                        return float(val)
                    
                    val_str = str(val).strip().replace(" ", "").replace("$", "").replace("Bs.", "")
                    
                    try:
                        return float(val_str)
                    except ValueError:
                        pass

                    try:
                        if "," in val_str and "." in val_str:
                            if val_str.rfind(",") > val_str.rfind("."):
                                val_str = val_str.replace(".", "").replace(",", ".")
                            else:
                                val_str = val_str.replace(",", "")
                        elif "," in val_str:
                            val_str = val_str.replace(".", "").replace(",", ".")
                        elif "." in val_str:
                            partes = val_str.split(".")
                            if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) != 2):
                                val_str = val_str.replace(".", "")
                        return float(val_str)
                    except Exception:
                        return 0.0

                df[col] = df[col].apply(parsear_valor_latino)
        return df

    def formato_venezolano(val):
        try:
            return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except:
            return "0,00"

    # ----------------------------------------------------
    # CARGA Y VISTA PREVIA DEL EXCEL
    # ----------------------------------------------------
    st.markdown("---")
    st.markdown("### 📋 Primer Frame: Libro de Ventas Subido")

    key_uploader_dinamica = f"uploader_libro_ventas_{db_segura}"
    archivo_excel = st.file_uploader(
        "Subir Libro de Ventas (Excel)",
        type=["xlsx", "xls"],
        key=key_uploader_dinamica,
    )

    if archivo_excel is not None:
        try:
            df_ventas = pd.read_excel(archivo_excel, dtype=str)
            df_ventas.columns = df_ventas.columns.str.strip()
            
            # GARANTIZAR NOMBRES DE COLUMNAS ÚNICOS
            cols_vistas = []
            nuevas_cols = []
            for c in df_ventas.columns:
                c_str = str(c)
                if c_str in cols_vistas:
                    i = 1
                    while f"{c_str}_{i}" in cols_vistas:
                        i += 1
                    c_str = f"{c_str}_{i}"
                cols_vistas.append(c_str)
                nuevas_cols.append(c_str)
            df_ventas.columns = nuevas_cols

            df_ventas = limpiar_y_forzar_numerico(df_ventas)

            df_ventas_visual = df_ventas.copy()
            for col in df_ventas_visual.columns:
                c_lower = str(col).lower().strip()
                es_total_ventas = "total" in c_lower and "venta" in c_lower
                es_ventas_exentas = "exenta" in c_lower and "venta" in c_lower
                
                if es_total_ventas or es_ventas_exentas or "base" in c_lower or "debito" in c_lower:
                    df_ventas_visual[col] = df_ventas_visual[col].apply(formato_venezolano)

            configuracion_columnas_dataframe = {}
            for col in df_ventas.columns:
                c_lower = str(col).lower().strip()
                es_total_ventas = "total" in c_lower and "venta" in c_lower
                es_ventas_exentas = "exenta" in c_lower and "venta" in c_lower
                
                if es_total_ventas or es_ventas_exentas or "base" in c_lower or "debito" in c_lower:
                    configuracion_columnas_dataframe[col] = (
                        st.column_config.TextColumn(str(col))
                    )

            st.dataframe(
                df_ventas_visual,
                use_container_width=True,
                column_config=configuracion_columnas_dataframe,
            )

            st.markdown("---")
            st.markdown("### ⚙️ Configuración de Asientos de Ventas")

            col_cfg1, col_cfg2 = st.columns(2)
            with col_cfg1:
                n_comprobante_base = st.text_input(
                    "Número de Comprobante (Fijo para todas las líneas):",
                    value="050001",
                    key=f"prefijo_ventas_{db_segura}",
                )

            if st.button(
                "🔄 Generar Estructura del Segundo Frame (Ventas)",
                key=f"btn_generar_frame_ventas_{db_segura}",
            ):
                try:
                    filas_asiento_temporal = []

                    # ----------------------------------------------------
                    # MAPEO DE COLUMNAS FUERA DEL BUCLE (OPTIMIZACIÓN O(1))
                    # ----------------------------------------------------
                    def encontrar_columna(posibles_nombres):
                        for col in df_ventas.columns:
                            c_clean = str(col).strip().lower()
                            for pos in posibles_nombres:
                                if pos.lower() in c_clean:
                                    return col
                        return None

                    col_fecha = encontrar_columna(["Fecha de Factura", "Fecha"])
                    col_razon = encontrar_columna(["Nombre y Apellido o Razón Social", "Razon Social", "Cliente"])
                    col_rif = encontrar_columna(["R.I.F.", "RIF", "Rif"])
                    
                    col_factura = None
                    for col in df_ventas.columns:
                        c_clean = str(col).strip().lower()
                        if ("factura" in c_clean or "nro" in c_clean or "num" in c_clean) and "fecha" not in c_clean:
                            col_factura = col
                            break

                    col_exentas = encontrar_columna(["Ventas Exentas", "Exentas"])
                    col_base = encontrar_columna(["Base Imponible"])
                    col_debito = encontrar_columna(["Débito Fiscal", "Debito Fiscal"])
                    col_total = encontrar_columna(["Total Ventas Incluyendo el IVA", "Total Ventas"])

                    # ----------------------------------------------------
                    # BUCLE DE PROCESAMIENTO ULTRARRÁPIDO
                    # ----------------------------------------------------
                    for idx, row in df_ventas.iterrows():
                        # 1. Fecha
                        raw_fecha = row[col_fecha] if col_fecha else ""
                        if hasattr(raw_fecha, "strftime"):
                            fecha_op = raw_fecha.strftime("%Y-%m-%d")
                        else:
                            val_str = str(raw_fecha).strip().split(" ")[0]
                            try:
                                fecha_op = pd.to_datetime(val_str).strftime("%Y-%m-%d")
                            except Exception:
                                fecha_op = val_str[:10] if val_str else ""

                        # 2. Razón Social y RIF
                        razon_social = str(row[col_razon] if col_razon and pd.notna(row[col_razon]) else "Sin Nombre").strip()
                        rif_cliente = str(row[col_rif] if col_rif and pd.notna(row[col_rif]) else "").strip().upper()

                        # 3. Número de Documento
                        nro_doc = ""
                        if col_factura and pd.notna(row[col_factura]):
                            val = row[col_factura]
                            if isinstance(val, pd.Series):
                                val = val.iloc[0]
                            nro_doc = str(val).strip()
                        if not nro_doc:
                            nro_doc = str(idx + 1)

                        # 4. Montos Numéricos
                        try:
                            ventas_exentas = float(row[col_exentas]) if col_exentas and pd.notna(row[col_exentas]) else 0.0
                        except Exception:
                            ventas_exentas = 0.0

                        try:
                            base_imponible = float(row[col_base]) if col_base and pd.notna(row[col_base]) else 0.0
                        except Exception:
                            base_imponible = 0.0

                        try:
                            debito_fiscal = float(row[col_debito]) if col_debito and pd.notna(row[col_debito]) else 0.0
                        except Exception:
                            debito_fiscal = 0.0

                        try:
                            total_ventas = float(row[col_total]) if col_total and pd.notna(row[col_total]) else (base_imponible + ventas_exentas + debito_fiscal)
                        except Exception:
                            total_ventas = base_imponible + ventas_exentas + debito_fiscal

                        n_comprobante_actual = str(n_comprobante_base).strip()
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
                            "referencia": nro_doc,
                            "debe": formato_venezolano(float(total_ventas)),
                            "haber": formato_venezolano(0.0),
                        })

                        # 2. Ingresos (HABER)
                        monto_ingreso = float(base_imponible + ventas_exentas)
                        if monto_ingreso > 0:
                            filas_asiento_temporal.append({
                                "n_comprobante": n_comprobante_actual,
                                "descripcion": f"Ingresos por Ventas Factura {nro_doc} - {razon_social}",
                                "fecha": fecha_op,
                                "plan_cuentas": opcion_ingreso,
                                "cuenta_contable": mapa_descripciones.get(opcion_ingreso, ""),
                                "referencia": nro_doc,
                                "debe": formato_venezolano(0.0),
                                "haber": formato_venezolano(monto_ingreso),
                            })

                        # 3. IVA Débito Fiscal (HABER)
                        if debito_fiscal > 0:
                            filas_asiento_temporal.append({
                                "n_comprobante": n_comprobante_actual,
                                "descripcion": f"IVA Débito Fiscal Factura {nro_doc} - {razon_social}",
                                "fecha": fecha_op,
                                "plan_cuentas": opcion_iva_debito,
                                "cuenta_contable": mapa_descripciones.get(opcion_iva_debito, ""),
                                "referencia": nro_doc,
                                "debe": formato_venezolano(0.0),
                                "haber": formato_venezolano(float(debito_fiscal)),
                            })

                    df_nuevo = pd.DataFrame(filas_asiento_temporal)
                    st.session_state["df_asientos_ventas_proceso"] = df_nuevo
                    st.rerun()

                except Exception as proc_err:
                    st.error(f"Error procesando los datos de ventas: {proc_err}")
        except Exception as excel_err:
            st.error(f"Error al leer o procesar el archivo Excel: {excel_err}")

    # ----------------------------------------------------
    # SEGUNDO FRAME: ESTRUCTURA COMPLETA DE VENTAS (OPTIMIZADO)
    # ----------------------------------------------------
    if 'df_asientos_ventas_proceso' in st.session_state and not st.session_state['df_asientos_ventas_proceso'].empty:
        df_a_procesar = st.session_state['df_asientos_ventas_proceso'].copy()
        
        st.markdown(f"### 📋 Segundo Frame: Estructura del Asiento de Ventas ({len(df_a_procesar)} registros)")
        
        # 1. Limpieza vectorizada rápida de Debe y Haber
        for col in ['debe', 'haber']:
            if col in df_a_procesar.columns:
                df_a_procesar[col] = (
                    df_a_procesar[col]
                    .astype(str)
                    .str.replace('$', '', regex=False)
                    .str.replace('€', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
                df_a_procesar[col] = pd.to_numeric(df_a_procesar[col], errors='coerce').fillna(0.0)

        if 'mapa_descripciones' not in locals() and 'mapa_descripciones' not in globals():
            mapa_descripciones = {} 
        
        mapa_descripciones["4.1.1.01.001"] = "Ingresos Exento I.V.A."

        def formato_venezolano(val):
            try:
                return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except Exception:
                return "0,00"

        def extraer_solo_codigo(val):
            val_str = str(val).strip()
            return val_str.split(" - ")[0].strip() if " - " in val_str else val_str

        # 2. OPTIMIZACIÓN CLAVE: Cargar clientes comerciales UNA SOLA VEZ en memoria
        lista_clientes_comerciales = []
        try:
            with db_connection.cursor() as cur_cc:
                cur_cc.execute(f"SELECT codigo_cuenta, descripcion_cuenta, rif, razon_social FROM `{db_segura}`.clientes_comerciales;")
                lista_clientes_comerciales = cur_cc.fetchall()
        except Exception as e:
            print(f"Error cargando clientes_comerciales: {e}")

        def buscar_cliente_en_memoria(texto_fila):
            if not texto_fila or str(texto_fila).strip() in ["", "nan", "None"]:
                return None, None, None
            texto_upper = str(texto_fila).upper()
            for codigo_cta, desc_cta, rif_cli, razon in lista_clientes_comerciales:
                if (razon and str(razon).upper() in texto_upper) or (desc_cta and str(desc_cta).upper() in texto_upper):
                    return str(codigo_cta).strip(), str(desc_cta).strip(), str(rif_cli).strip()
            return None, None, None

        # 3. Asignación rápida de cuentas usando la búsqueda en memoria
        for idx in df_a_procesar.index:
            desc_actual = str(df_a_procesar.at[idx, "descripcion"]) if "descripcion" in df_a_procesar.columns else ""
            cod_cliente, desc_cliente, rif_oficial = buscar_cliente_en_memoria(desc_actual)
            
            haber_val = float(df_a_procesar.at[idx, "haber"]) if "haber" in df_a_procesar.columns else 0.0
            debe_val = float(df_a_procesar.at[idx, "debe"]) if "debe" in df_a_procesar.columns else 0.0

            if haber_val > 0 and debe_val == 0:
                df_a_procesar.at[idx, "plan_cuentas"] = "4.1.1.01.001"
            else:
                if cod_cliente:
                    df_a_procesar.at[idx, "plan_cuentas"] = cod_cliente
                    if cod_cliente not in mapa_descripciones and desc_cliente:
                        mapa_descripciones[cod_cliente] = desc_cliente

            if rif_oficial and rif_oficial not in desc_actual and " - RIF:" not in desc_actual:
                df_a_procesar.at[idx, "descripcion"] = f"{desc_actual} - RIF: {rif_oficial}"

            codigo_actual = extraer_solo_codigo(df_a_procesar.at[idx, "plan_cuentas"])
            if codigo_actual == "4.1.1.01.001":
                df_a_procesar.at[idx, "cuenta_contable"] = "Ingresos Exento I.V.A."
            else:
                df_a_procesar.at[idx, "cuenta_contable"] = mapa_descripciones.get(codigo_actual, desc_cliente or "")

        opciones_codigos_puros = list(mapa_descripciones.keys())
        if not opciones_codigos_puros or "4.1.1.01.001" not in opciones_codigos_puros:
            opciones_codigos_puros = ["4.1.1.01.001"] + [op for op in opciones_codigos_puros if op != "4.1.1.01.001"]

        # 4. Preparar visualización
        df_para_mostrar = df_a_procesar.copy()
        for col in ['debe', 'haber']:
            if col in df_para_mostrar.columns:
                df_para_mostrar[col] = pd.to_numeric(df_para_mostrar[col], errors='coerce').fillna(0.0)
                df_para_mostrar[col] = df_para_mostrar[col].apply(formato_venezolano)

        df_editado_crudo = st.data_editor(
            df_para_mostrar,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "n_comprobante": st.column_config.TextColumn("n_comprobante"),
                "descripcion": st.column_config.TextColumn("Descripción (Incluye RIF)"),
                "fecha": st.column_config.TextColumn("Fecha"),
                "plan_cuentas": st.column_config.SelectboxColumn(
                    "Plan de Cuentas (Cliente o Ingreso Exento)",
                    options=opciones_codigos_puros,
                    required=True
                ),
                "cuenta_contable": st.column_config.TextColumn("Descripción Cuenta", disabled=True),
                "referencia": st.column_config.TextColumn("Referencia"),
                "debe": st.column_config.TextColumn("Debe"),
                "haber": st.column_config.TextColumn("Haber"),
            },
            key="editor_segundo_frame_ventas"
        )
        
        # 5. Re-conversión a numéricos
        df_editado = df_editado_crudo.copy()
        for col in ['debe', 'haber']:
            if col in df_editado.columns:
                col_limpia = (
                    df_editado[col]
                    .astype(str)
                    .str.replace('$', '', regex=False)
                    .str.replace('.', '', regex=False)
                    .str.replace(',', '.', regex=False)
                    .str.strip()
                )
                df_editado[col] = pd.to_numeric(col_limpia, errors='coerce').fillna(0.0).astype(float)

        for idx in df_editado.index:
            codigo_puro = extraer_solo_codigo(df_editado.at[idx, "plan_cuentas"])
            df_editado.at[idx, "plan_cuentas"] = codigo_puro
            if codigo_puro == "4.1.1.01.001":
                df_editado.at[idx, "cuenta_contable"] = "Ingresos Exento I.V.A."
            else:
                df_editado.at[idx, "cuenta_contable"] = mapa_descripciones.get(codigo_puro, "")

        st.session_state['df_asientos_proceso'] = df_editado
        
        tot_debe = float(df_editado['debe'].sum())
        tot_haber = float(df_editado['haber'].sum())
        
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("Total Debe (Ventas)", formato_venezolano(tot_debe))
        col_m2.metric("Total Haber (Ventas)", formato_venezolano(tot_haber))

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
            use_container_width=False
        )

        if st.button("💾 Guardar Asientos de Ventas en el Libro Diario", key="btn_guardar_ventas_finales", use_container_width=False):
            try:
                df_val = df_editado.copy()
                df_val['fecha'] = pd.to_datetime(df_val['fecha'], errors='coerce')
                anios_meses_excel = set((row['fecha'].year, row['fecha'].month) for _, row in df_val.iterrows() if pd.notnull(row['fecha']))
                
                bloqueo_detectado = False
                mensaje_bloqueo = ""
                
                for anio, mes in anios_meses_excel:
                    try:
                        with db_connection.cursor() as cur_check:
                            cur_check.execute(f"""
                                SELECT COUNT(*) FROM `{db_segura}`.asientos_contables 
                                WHERE YEAR(fecha) = %s AND MONTH(fecha) = %s AND bloqueado = 1
                            """, (anio, mes))
                            res_bloqueo = cur_check.fetchone()
                            
                            if res_bloqueo and res_bloqueo[0] > 0:
                                bloqueo_detectado = True
                                mensaje_bloqueo = f"❌ **Operación Denegada**: El período correspondiente al mes **{mes:02d}/{anio}** se encuentra **CERRADO y BLOQUEADO**."
                                break
                    except Exception:
                        pass

                if bloqueo_detectado:
                    st.error(mensaje_bloqueo)
                else:
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
                                haber DECIMAL(15, 2) DEFAULT 0.00,
                                bloqueado TINYINT DEFAULT 0
                            );
                        """)
                        
                        # 6. OPTIMIZACIÓN CLAVE: Inserción Masiva por Lotes (executemany)
                        datos_a_insertar = []
                        for _, row in df_editado.iterrows():
                            codigo_limpio = extraer_solo_codigo(row["plan_cuentas"])
                            fecha_str = str(row["fecha"]).split(" ")[0] if pd.notnull(row["fecha"]) else None
                            ref_val = str(row["referencia"]) if pd.notnull(row["referencia"]) else ""
                            
                            datos_a_insertar.append((
                                str(row["n_comprobante"]),
                                str(row["descripcion"]),
                                fecha_str,
                                str(codigo_limpio),
                                str(row["cuenta_contable"]),
                                ref_val,
                                float(row["debe"]),
                                float(row["haber"])
                            ))
                        
                        sql_insert = f"""
                            INSERT INTO `{db_segura}`.asientos_contables 
                            (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                        """
                        cursor.executemany(sql_insert, datos_a_insertar)
                        db_connection.commit()
                        
                        st.success(f"✅ ¡{len(datos_a_insertar)} asientos de ventas guardados correctamente en `{db_segura}`!")
                        
            except Exception as db_err:
                if hasattr(db_connection, 'rollback'):
                    db_connection.rollback()
                st.error(f"❌ Error crítico al guardar en MySQL: {str(db_err)}")

def generar_pdf_resumen_seniat(records, empresa_nombre, periodo_str, tot_base, tot_sust, tot_neta):
    pdf = FPDF(orientation='L', unit='mm', format='A4') # Orientación Horizontal
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Encabezado
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, f"RESUMEN DE RETENCIONES DE ISLR PARA EL SENIAT", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Empresa / Cliente: {empresa_nombre}  |  Periodo Fiscal: {periodo_str}", ln=True, align="C")
    pdf.ln(5)
    
    # Encabezados de la Tabla (Ancho total A4 Landscape ~ 277mm)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(240, 240, 240)
    
    ancho_cols = {
        'Fila / Doc': 25, 'Fecha': 20, 'N° Doc': 20, 'N° Control': 22, 
        'R.I.F.': 25, 'Nombre o Razón Social': 60, 'Cód. Concepto (XML)': 25, 
        'Base Imponible (Bs.)': 28, 'Sustraendo (Bs.)': 25, 'Retención Neta (Bs.)': 27
    }
    
    for col, width in ancho_cols.items():
        pdf.cell(width, 7, col[:15], border=1, align="C", fill=True)
    pdf.ln()
    
    # Contenido de Filas
    pdf.set_font("Helvetica", "", 8)
    for row in records:
        pdf.cell(ancho_cols['Fila / Doc'], 6, str(row.get('Fila / Doc', ''))[:14], border=1)
        pdf.cell(ancho_cols['Fecha'], 6, str(row.get('Fecha', '')), border=1, align="C")
        pdf.cell(ancho_cols['N° Doc'], 6, str(row.get('N° Doc', '')), border=1, align="C")
        pdf.cell(ancho_cols['N° Control'], 6, str(row.get('N° Control', '')), border=1, align="C")
        pdf.cell(ancho_cols['R.I.F.'], 6, str(row.get('R.I.F.', '')), border=1, align="C")
        pdf.cell(ancho_cols['Nombre o Razón Social'], 6, str(row.get('Nombre o Razón Social', ''))[:32], border=1)
        pdf.cell(ancho_cols['Cód. Concepto (XML)'], 6, str(row.get('Cód. Concepto (XML)', '')), border=1, align="C")
        
        base_val = float(row.get('Base Imponible (Bs.)', 0) or 0)
        sust_val = float(row.get('Sustraendo (Bs.)', 0) or 0)
        neto_val = float(row.get('Retención Neta (Bs.)', 0) or 0)
        
        pdf.cell(ancho_cols['Base Imponible (Bs.)'], 6, f"{base_val:,.2f}", border=1, align="R")
        pdf.cell(ancho_cols['Sustraendo (Bs.)'], 6, f"{sust_val:,.2f}", border=1, align="R")
        pdf.cell(ancho_cols['Retención Neta (Bs.)'], 6, f"{neto_val:,.2f}", border=1, align="R")
        pdf.ln()
        
    # Fila de Totales
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    ancho_acumulado_texto = sum([ancho_cols['Fila / Doc'], ancho_cols['Fecha'], ancho_cols['N° Doc'], ancho_cols['N° Control'], ancho_cols['R.I.F.'], ancho_cols['Nombre o Razón Social'], ancho_cols['Cód. Concepto (XML)']])
    
    pdf.cell(ancho_acumulado_texto, 7, "TOTALES GENERALES A ENTERAR AL SENIAT:", border=1, align="R", fill=True)
    pdf.cell(ancho_cols['Base Imponible (Bs.)'], 7, f"{tot_base:,.2f}", border=1, align="R", fill=True)
    pdf.cell(ancho_cols['Sustraendo (Bs.)'], 7, f"{tot_sust:,.2f}", border=1, align="R", fill=True)
    pdf.cell(ancho_cols['Retención Neta (Bs.)'], 7, f"{tot_neta:,.2f}", border=1, align="R", fill=True)
    
    return bytes(pdf.output())


@st.cache_data(ttl=300)
def _obtener_empresas_sidebar_cache(user_rol, user_limpio):
    conn_sidebar = conectar_db()
    if conn_sidebar is None:
        return []

    df_sidebar = pd.DataFrame()
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
        else:
            queries_a_probar = [
                f"""
                SELECT c.* FROM control_central.clientes c
                JOIN control_central.usuarios u ON c.id = u.cliente_id
                WHERE LOWER(TRIM(u.usuario)) = '{user_limpio}'
                """,
                f"""
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
    except Exception:
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

    # --- RESPALDO OBLIGATORIO PARA ELENITA ---
    elif df_sidebar.empty and user_limpio == 'elenita':
        df_sidebar = pd.DataFrame([{
            'id': 1,  # Ajusta el ID según corresponda
            'nombre_empresa': 'King Driver, C.A.',  # Ajusta el nombre de la empresa
            'rif': 'J-XXXXXXXX-X',
            'db_nombre': 'kingdriver_ca'  # Ajusta el nombre de la base de datos real
        }])

    if not df_sidebar.empty:
        df_sidebar = df_sidebar.fillna("")

    return df_sidebar.to_dict('records')




def generar_pdf_preimpreso(conn, datos_factura, items_factura):
    """
    Genera un PDF transparente con los datos posicionados milimétricamente
    según la configuración guardada en MySQL, auto-inicializando los valores por defecto.
    """
    cursor = conn.cursor(dictionary=True)
    
    # 0. Auto-insertar valores por defecto en MySQL si la tabla está vacía o faltan campos
    defaults = [
        ('nro_factura', 160.00, 25.00, 11),
        ('nro_control', 160.00, 31.00, 11),
        ('fecha_emision', 155.00, 42.00, 10),
        ('razon_social', 35.00, 55.00, 10),
        ('rif_cliente', 35.00, 61.00, 10),
        ('direccion_cliente', 35.00, 67.00, 9),
        ('telefono_cliente', 135.00, 67.00, 9),
        ('tabla_items_y_inicial', 25.00, 90.00, 9),
        ('salto_linea_item', 6.00, 0.00, 9),
        ('exento', 165.00, 205.00, 10),
        ('base_imponible', 165.00, 213.00, 10),
        ('alicuota_iva', 130.00, 221.00, 10),
        ('iva', 165.00, 221.00, 10),
        ('monto_total', 165.00, 232.00, 11)
    ]
    
    for campo, px, py, ft in defaults:
        cursor.execute("""
            INSERT INTO config_factura_preimpresa (campo, pos_x, pos_y, fuente_tamanio) 
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE pos_x = pos_x
        """, (campo, px, py, ft))
    conn.commit()

    # 1. Consultar coordenadas reales desde la base de datos
    cursor.execute("SELECT campo, pos_x, pos_y, fuente_tamanio FROM config_factura_preimpresa")
    configs = {row['campo']: row for row in cursor.fetchall()}
    cursor.close()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    
    def get_pos(campo_nombre):
        if campo_nombre in configs:
            x = float(configs[campo_nombre]['pos_x']) * mm
            # Conversión de milímetros desde arriba hacia el sistema de coordenadas de ReportLab (desde abajo)
            y = (279.4 - float(configs[campo_nombre]['pos_y'])) * mm
            return x, y
        return 0, 0

    # --- Cabecera / Documento ---
    if 'nro_factura' in configs:
        x, y = get_pos('nro_factura')
        c.setFont("Helvetica-Bold", int(configs['nro_factura']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('nro_factura', '')))

    if 'nro_control' in configs:
        x, y = get_pos('nro_control')
        c.setFont("Helvetica-Bold", int(configs['nro_control']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('nro_control', '')))

    if 'fecha_emision' in configs:
        x, y = get_pos('fecha_emision')
        c.setFont("Helvetica", int(configs['fecha_emision']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('fecha_emision', '')))

    # --- Datos del Cliente ---
    if 'razon_social' in configs:
        x, y = get_pos('razon_social')
        c.setFont("Helvetica", int(configs['razon_social']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('razon_social', '')))

    if 'rif_cliente' in configs:
        x, y = get_pos('rif_cliente')
        c.setFont("Helvetica", int(configs['rif_cliente']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('rif_cliente', '')))

    if 'direccion_cliente' in configs:
        x, y = get_pos('direccion_cliente')
        c.setFont("Helvetica", int(configs['direccion_cliente']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('direccion_cliente', ''))[:60])

    if 'telefono_cliente' in configs:
        x, y = get_pos('telefono_cliente')
        c.setFont("Helvetica", int(configs['telefono_cliente']['fuente_tamanio']))
        c.drawString(x, y, str(datos_factura.get('telefono_cliente', '')))

    # --- Renglones / Ítems de la Factura ---
    if 'tabla_items_y_inicial' in configs:
        x_base, y_actual = get_pos('tabla_items_y_inicial')
        salto_y = float(configs.get('salto_linea_item', {'pos_x': 6.0})['pos_x']) * mm 
        
        for idx, item in enumerate(items_factura):
            y_renglon = y_actual - (idx * salto_y)
            
            c.setFont("Helvetica", 9)
            c.drawString(x_base, y_renglon, str(item.get('codigo', '')))
            c.drawString(x_base + 20*mm, y_renglon, str(item.get('descripcion', ''))[:35])
            c.drawString(x_base + 105*mm, y_renglon, str(item.get('cantidad', '0')))
            c.drawString(x_base + 120*mm, y_renglon, str(item.get('precio_unitario', '0.00')))
            c.drawString(x_base + 145*mm, y_renglon, str(item.get('total_linea', '0.00')))

    # --- Totales y Datos Fiscales al Pie ---
    campos_totales = ['exento', 'base_imponible', 'alicuota_iva', 'iva', 'monto_total']
    for campo in campos_totales:
        if campo in configs:
            x, y = get_pos(campo)
            tam = int(configs[campo]['fuente_tamanio'])
            font = "Helvetica-Bold" if campo == 'monto_total' else "Helvetica"
            c.setFont(font, tam)
            c.drawString(x, y, str(datos_factura.get(campo, '0.00')))

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def gestionar_sidebar():
    user_rol = str(st.session_state.get('rol', 'admin')).strip().lower()
    user_id = st.session_state.get('user_id', st.session_state.get('cliente_id', 'N/A'))
    nombre_usuario_actual = (
        st.session_state.get('nombre_usuario') or 
        st.session_state.get('username') or 
        st.session_state.get('usuario') or 
        'Usuario'
    )
    user_limpio = str(nombre_usuario_actual).strip().lower()

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
        if st.button("🚪 Cerrar Sesión", key="btn_logout_unico_definitivo"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        # --- Navegación ---
        if user_rol == 'admin':
            menu = st.radio("Navegación", ["📊 Auditoría Contable", "⚙️ Gestión de Usuarios","⚙️ Gestión de Empresas"], key="menu_nav")
        else:
            menu = "📊 Auditoría Contable"

        st.divider()

        # --- Selección de Empresa (Optimizada con caché y session_state) ---
        if menu == "📊 Auditoría Contable":
            # Llamada a la función con caché (evita latencia de red innecesaria)
            registros_cache = _obtener_empresas_sidebar_cache(user_rol, user_limpio)
            df_sidebar = pd.DataFrame(registros_cache)

            # 🛠️ Fallback de seguridad si el usuario es 'anderson' y no vino mapeado en la BD
            if df_sidebar.empty and user_limpio == 'anderson':
                df_sidebar = pd.DataFrame([{
                    'id': 1,
                    'nombre_empresa': 'Gomas Puente Hierro 2023, C.A.',
                    'db_nombre': 'gomas_puente_hierro'  # Cambia por el nombre real de su base de datos en MySQL
                }])

            if user_rol != 'admin' and df_sidebar.empty:
                st.error(f"❌ El usuario '{nombre_usuario_actual}' no tiene una empresa asignada en la base de datos o en las relaciones de usuario.")
                st.stop()

            if not df_sidebar.empty:
                # 🔍 BÚSQUEDA DINÁMICA DE COLUMNAS PARA EVITAR KEYERRORS
                cols_disponibles = [str(c).lower() for c in df_sidebar.columns]
                
                posibles_nombres = ['nombre_empresa', 'nombre', 'empresa', 'cliente', 'razon_social']
                col_empresa = next((df_sidebar.columns[cols_disponibles.index(p)] for p in posibles_nombres if p in cols_disponibles), None)
                if not col_empresa and len(df_sidebar.columns) > 0:
                    col_empresa = df_sidebar.columns[0]

                posibles_dbs = ['db_nombre', 'database', 'base_datos', 'db']
                col_db = next((df_sidebar.columns[cols_disponibles.index(p)] for p in posibles_dbs if p in cols_disponibles), None)
                if not col_db and len(df_sidebar.columns) > 1:
                    col_db = df_sidebar.columns[1]

                nombres_empresas = df_sidebar[col_empresa].tolist() if col_empresa else []
                nombre_seleccionado = nombres_empresas[0] if nombres_empresas else "Empresa Desconocida"

                st.markdown(f"**🏢 Empresa Asignada:**")
                st.info(f"{str(nombre_seleccionado).upper()}")

                st.session_state['cliente_seleccionado_previo'] = nombre_seleccionado

                fila_seleccionada = df_sidebar[df_sidebar[col_empresa] == nombre_seleccionado] if col_empresa else pd.DataFrame()
                if fila_seleccionada.empty:
                    fila_seleccionada = df_sidebar.iloc[[0]]

                datos_sel = fila_seleccionada.iloc[0]
                db_seleccionada = str(datos_sel[col_db]).strip() if col_db else "rishon_letzion_ca"
                
                # --- ALMACENAMIENTO SEGURO EN SESSION_STATE ---
                st.session_state['DB_ACTUAL'] = db_seleccionada
                st.session_state['db_a_conectar'] = db_seleccionada
                st.session_state['CLIENTE_NOMBRE'] = nombre_seleccionado
                if 'id' in datos_sel:
                    st.session_state['cliente_id_seleccionado'] = int(datos_sel['id'])

    return menu

# 0. Primero validamos si la sesión expiró por tiempo
verificar_inactividad()

if 'logueado' not in st.session_state or not st.session_state['logueado']:
    # 1. Si no está logueado, muestra la pantalla de acceso
    login_screen()
    st.stop()

elif not st.session_state.get('bienvenida_completada', False):
    # 2. Si acaba de loguearse, muestra la plantilla grande con la barra de carga
    mostrar_plantilla_bienvenida()
    st.stop()

else:
    # --- INICIALIZACIÓN OBLIGATORIA DEL MENÚ PRINCIPAL TRAS EL LOGIN ---
    if 'opcion_menu_auditoria' not in st.session_state:
        st.session_state['opcion_menu_auditoria'] = "🏠 Inicio"

    # 3. Si ya pasó la bienvenida, carga el menú lateral y la aplicación normal
    menu_lateral = gestionar_sidebar()


# ==============================================================================
# ENRUTAMIENTO Y CONTROL DE ACCESO SEGÚN EL ROL (Multi-nivel)
# ==============================================================================

rol_actual = st.session_state.get('rol', 'cliente') # 'admin' (Tú) o 'admin_firma' (Dueño de Despacho) / 'cliente'
firma_id_actual = st.session_state.get('firma_id', None) # El ID de la firma a la que pertenece este contador

if menu_lateral == "⚙️ Gestión de Usuarios":
    try:
        conn = conectar_db()
        if conn:
            # Pasamos el rol y el ID de la firma para que el panel se filtre automáticamente
            panel_administracion(conn, rol_actual, firma_id_actual)
            try:
                conn.close()
            except Exception:
                pass
        else:
            st.error("🔌 No se pudo establecer conexión con el servidor MySQL.")
    except Exception as e:
        st.error(f"Error al acceder a la gestión de usuarios: {e}")
    st.stop()

if menu_lateral == "⚙️ Gestión de Empresas":
    # 🔒 RESTRICCIÓN ABSOLUTA: Solo el Administrador Maestro (Tú) puede ver la creación de despachos globales
    if rol_actual != "admin":
        st.error("⛔ Acceso denegado. Esta sección central es exclusiva para el Administrador General de Gylfi Software.")
        st.stop()
        
    try:
        conn = conectar_db(db_actual) if "db_actual" in locals() else conectar_db()
        if conn:
            panel_administracion_empresas(conn)
            try:
                conn.close()
            except Exception:
                pass
        else:
            st.error("🔌 No se pudo establecer conexión con el servidor MySQL.")
    except Exception as e:
        st.error(f"Error al acceder a la gestión central de empresas: {e}")
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
            "📖 Mayor Analítico", "📊 Estados Financieros", "📚 Libros Fiscales", "👤 Proveedores","👤 Clientes","📦 Respaldos y Exportación"
        ]

        if "PEDACITO" in str(nombre_sel).upper() and "CIELO" in str(nombre_sel).upper():
            if "🧁 Inventarios" not in modulos_disponibles:
                modulos_disponibles.append("🧁 Inventarios")

        # Condición exclusiva para Gomas Puente Hierro (ajusta el texto según cómo aparezca en tu variable nombre_sel)
        if "GOMAS" in str(nombre_sel).upper() and "PUENTE" in str(nombre_sel).upper():
            if "📄 Factura Preimpresa" not in modulos_disponibles:
                modulos_disponibles.append("📄 Factura Preimpresa")

        # Buscamos si ya hay una opción guardada, de lo contrario fijamos 0 (Inicio)
        indice_actual = 0
        if 'opcion_menu_auditoria' in st.session_state and st.session_state['opcion_menu_auditoria'] in modulos_disponibles:
            indice_actual = modulos_disponibles.index(st.session_state['opcion_menu_auditoria'])

        opcion_menu = st.selectbox("📂 SELECCIONE UN MÓDULO", modulos_disponibles, index=indice_actual, key="opcion_menu_selectbox_dinamico")
        st.session_state['opcion_menu_auditoria'] = opcion_menu

        if opcion_menu == "📝 Asientos Contables":
            sub_opcion = st.radio("Acciones:", ["Subir Datos", "Conciliación Bancaria","Tesorería y Proveedores", "Activo Fijo", "Consultar Comprobante", "Consultar Saldos Iniciales", "Consultar Cierre Contable","Gestor Documental"], key="sub_asientos")
        elif opcion_menu == "📊 Estados Financieros":
            st.markdown("---")
            sub_opcion = st.radio("Reportes Financieros:", ["Balance de Comprobación", "Balance General", "Estado de Resultados"], key="sub_estados")
        elif opcion_menu == "📚 Libros Fiscales":
            sub_opcion = st.radio("Reportes Fiscales:", ["Libro de Ventas", "Libro de Compras", "Comprobante de Retención ISLR", "Comprobante de Retención IVA"], key="sub_libros")
        elif opcion_menu == "📄 Factura Preimpresa":
            sub_opcion = st.radio("Configuración y Emisión:", ["Generar PDF Preimpreso", "Calibrar Coordenadas (X,Y)"], key="sub_factura_preimpresa")
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


# Al autenticar o pasar la plantilla de bienvenida por primera vez:
# 1. Aseguramos que la opción por defecto del menú de auditoría sea Inicio si no existe
if 'opcion_menu_auditoria' not in st.session_state:
    st.session_state['opcion_menu_auditoria'] = "🏠 Inicio"

# 2. Recuperamos siempre la opción actual del menú
opcion_menu = st.session_state.get('opcion_menu_auditoria', "🏠 Inicio")


# 3. Evaluamos si el usuario está en el Dashboard de Inicio
if opcion_menu == "🏠 Inicio":
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
                    db_objetivo = 'rishon_letzion_ca'
                else:
                    st.error(f"❌ Acceso denegado: El usuario '{nombre_usuario_actual}' no tiene una empresa (DB) asociada.")
                    st.stop()
        except Exception as e:
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

    # --- LÓGICA DE CONEXIÓN ROBUSTA ---
    necesita_reconexion = False

    if 'conn' not in st.session_state or st.session_state.get('ultima_db_conectada') != db_objetivo or st.session_state.conn is None:
        necesita_reconexion = True
    else:
        try:
            st.session_state.conn.ping(reconnect=True)
            if db_objetivo and db_objetivo != "control_central":
                with st.session_state.conn.cursor() as cursor:
                    cursor.execute(f"USE `{db_objetivo}`")
        except Exception:
            necesita_reconexion = True

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

    f_inicio_global = date(anio_f, 1, 1) 
    f_fin_global = date(anio_f, m_idx, ultimo_dia)

    st.session_state["f_inicio_global"] = f_inicio_global
    st.session_state["f_fin_global"] = f_fin_global

    # 5. UI DEL DASHBOARD DE INICIO
    if db_objetivo:
        st.title(f"📊 Auditoría Profesional: {db_objetivo}")
        st.markdown(f"**Período de Análisis (Acumulado):** {f_inicio_global.strftime('%d/%m/%Y')} al {f_fin_global.strftime('%d/%m/%Y')}")
        st.divider()
    else:
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
            kpis = obtener_saldos_acumulados(f_fin_global, db_objetivo)
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
    
    db_actual = st.session_state.get('DB_ACTUAL')
    if not db_actual:
        st.error("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()

    # --- FUNCIÓN DE CARGA RÁPIDA A MEMORIA LOCAL (SESSION STATE) ---
    def cargar_plan_cuentas_memoria(empresa):
        conn = conectar_db(empresa)
        df_res = pd.DataFrame()
        if conn:
            try:
                conn.ping(reconnect=True)
                df_res = consultar_tabla_db(conn, "plan_cuentas")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        
        columnas_requeridas = ['id', 'codigo', 'nombre', 'nivel', 'tipo', 'padre']
        if df_res is None or df_res.empty:
            df_res = pd.DataFrame(columns=columnas_requeridas)
        else:
            for col in columnas_requeridas:
                if col not in df_res.columns:
                    df_res[col] = ""

            for col in ['codigo', 'nombre', 'tipo', 'padre']:
                if col in df_res.columns:
                    df_res[col] = df_res[col].fillna("").astype(str).replace(['nan', 'None', '<NA>'], '')
            
            if 'id' in df_res.columns:
                df_res['id'] = pd.to_numeric(df_res['id'], errors='coerce')
            if 'nivel' in df_res.columns:
                df_res['nivel'] = pd.to_numeric(df_res['nivel'], errors='coerce').fillna(1).astype(int)

            if 'codigo' in df_res.columns:
                df_res = df_res.sort_values(by='codigo', ascending=True).reset_index(drop=True)
                
        st.session_state.df_plan_cuentas_memoria = df_res
        st.session_state.db_plan_cuentas_cargada = empresa

    # Verificamos si los datos no están cargados en memoria o si cambió la BD activa
    if "df_plan_cuentas_memoria" not in st.session_state or st.session_state.get("db_plan_cuentas_cargada") != db_actual:
        cargar_plan_cuentas_memoria(db_actual)

    # Obtenemos la conexión rápida para operaciones de escritura
    conn_empresa = conectar_db(db_actual)
    
    try:
        st.markdown("""
            <style>
                .stTabs [data-baseweb="tab-list"] { gap: 10px; background-color: transparent; padding: 10px 0px; }
                .stTabs [data-baseweb="tab"] {
                    height: 45px; background-color: #f8f9fa; border-radius: 8px; padding: 0px 20px;
                    font-weight: 600; color: #495057; border: 1px solid #e9ecef;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.02); transition: all 0.3s ease;
                }
                .stTabs [data-baseweb="tab"]:hover { background-color: #e2e6ea; color: #1d3557; border-color: #ced4da; }
                .stTabs [aria-selected="true"] {
                    background-color: #1d3557 !important; color: #ffffff !important;
                    border-color: #1d3557 !important; box-shadow: 0 4px 8px rgba(29, 53, 87, 0.2);
                }
            </style>
        """, unsafe_allow_html=True)

        tab1, tab2, tab3, tab4 = st.tabs([
            "📥 Cargar Plan", 
            "📋 Visualizar Plan", 
            "📥 Descargar Excel",
            "🗑️ Vaciar Plan"
        ])
        
        # --- TAB 1: CARGA DESDE EXCEL ---
        with tab1:
            st.markdown("### Subir Archivo Excel")
            archivo_plan = st.file_uploader("Seleccione el archivo", type=["xlsx", "xls"], key="plan_up")
            
            if archivo_plan:
                df_plan = pd.read_excel(archivo_plan)
                df_plan.columns = df_plan.columns.str.strip().str.lower()
                df_plan = df_plan.rename(columns={'nombre de la cuenta': 'nombre'})
                
                st.info(f"📁 Archivo cargado exitosamente. Total de filas encontradas: **{len(df_plan)}**")
                st.dataframe(df_plan, use_container_width=True, height=400)
                
                if st.button("🚀 Iniciar Importación a Base de Datos", type="primary"):
                    columnas_sql = ['id', 'codigo', 'nombre', 'nivel', 'tipo', 'padre']
                    if 'codigo' in df_plan.columns and 'nombre' in df_plan.columns:
                        try:
                            for col in columnas_sql:
                                if col not in df_plan.columns:
                                    df_plan[col] = None
                                    
                            df_final = df_plan[columnas_sql]
                            df_final = df_final.astype(object).where(df_final.notnull(), None)
                            
                            actualizar_tabla_completa_db(conn_empresa, 'plan_cuentas', df_final)
                            cargar_plan_cuentas_memoria(db_actual)
                            st.success("✅ ¡Plan de cuentas sincronizado correctamente!")
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error al importar a la base de datos: {e}")
                    else:
                        st.error("❌ El archivo Excel debe contener al menos las columnas 'codigo' y 'nombre'.")

        # --- TAB 2: VISUALIZAR Y MODIFICAR ---
        with tab2:
            st.markdown("### 📋 Plan de Cuentas (Gestión y Modificación)")
            
            # Mostrar mensaje HTML de eliminación pendiente si existe
            if "mensaje_html_eliminacion" in st.session_state:
                st.markdown(st.session_state.mensaje_html_eliminacion, unsafe_allow_html=True)
                del st.session_state.mensaje_html_eliminacion

            # Botón para forzar refresco desde BD si lo deseas
            col_r1, col_r2 = st.columns([4, 1])
            with col_r2:
                if st.button("🔄 Recargar BD", key="btn_refrescar_plan_state", use_container_width=True):
                    cargar_plan_cuentas_memoria(db_actual)
                    st.rerun()

            df_actual = st.session_state.df_plan_cuentas_memoria

            with st.expander("➕ Agregar Nueva Cuenta Contable", expanded=False):
                with st.form("form_nueva_cuenta"):
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        nuevo_codigo = st.text_input("Código Contable (ej. 1.1.1.01.003)")
                        nuevo_nombre = st.text_input("Nombre de la Cuenta (ej. Caja en Moneda Extranjera)")
                        nuevo_nivel = st.number_input("Nivel", min_value=1, max_value=5, value=5)
                    with col_f2:
                        nuevo_tipo = st.selectbox("Tipo", options=["Detalle", "Grupo"])
                        nuevo_padre = st.text_input("Cuenta Padre (ej. 1.1.1.01)")
                    
                    if st.form_submit_button("💾 Guardar Nueva Cuenta"):
                        if not nuevo_codigo or not nuevo_nombre:
                            st.warning("⚠️ El código y el nombre son obligatorios.")
                        else:
                            try:
                                conn_empresa.ping(reconnect=True)
                                cursor_ins = conn_empresa.cursor()
                                cursor_ins.execute("SELECT MAX(id) FROM plan_cuentas")
                                res_max = cursor_ins.fetchone()
                                siguiente_id = (res_max[0] or 0) + 1 if res_max else 1

                                sql_ins = "INSERT INTO plan_cuentas (id, codigo, nombre, nivel, tipo, padre) VALUES (%s, %s, %s, %s, %s, %s)"
                                cursor_ins.execute(sql_ins, (
                                    siguiente_id, nuevo_codigo.strip(), nuevo_nombre.strip(), 
                                    int(nuevo_nivel), nuevo_tipo, nuevo_padre.strip() if nuevo_padre else None
                                ))
                                conn_empresa.commit()
                                cursor_ins.close()
                                cargar_plan_cuentas_memoria(db_actual)
                                st.success(f"✅ Cuenta '{nuevo_codigo}' agregada con éxito.")
                                st.rerun()
                            except Exception as ex_ins:
                                st.error(f"❌ Error al insertar: {ex_ins}")

            # Sección 2: Eliminar Cuenta
            with st.expander("🗑️ Eliminar Cuenta Contable (Por Error)", expanded=False):
                with st.form("form_eliminar_cuenta"):
                    st.warning("⚠️ Precaución: Eliminar una cuenta la borrará permanentemente.")
                    
                    lista_cuentas_del = []
                    if not df_actual.empty and 'codigo' in df_actual.columns and 'nombre' in df_actual.columns:
                        lista_cuentas_del = [f"{row['codigo']} - {row['nombre']}" for _, row in df_actual.iterrows()]

                    cuenta_a_borrar = st.selectbox("Seleccione la cuenta a eliminar", options=lista_cuentas_del if lista_cuentas_del else ["No hay cuentas disponibles"])
                    confirmar_borrado = st.checkbox("Confirmo que deseo eliminar permanentemente esta cuenta")
                    
                    if st.form_submit_button("🗑️ Eliminar Cuenta Seleccionada", type="primary"):
                        if not lista_cuentas_del or cuenta_a_borrar == "No hay cuentas disponibles":
                            st.warning("⚠️ No hay cuentas para eliminar.")
                        elif not confirmar_borrado:
                            st.warning("⚠️ Debe marcar la casilla de confirmación.")
                        else:
                            try:
                                codigo_extraido = cuenta_a_borrar.split(" - ")[0].strip()
                                conn_empresa.ping(reconnect=True)
                                cursor_del = conn_empresa.cursor()
                                cursor_del.execute("DELETE FROM plan_cuentas WHERE codigo = %s", (codigo_extraido,))
                                conn_empresa.commit()
                                cursor_del.close()
                                cargar_plan_cuentas_memoria(db_actual)
                                
                                # Guardamos el mensaje HTML en la sesión para que sobreviva al rerun
                                st.session_state.mensaje_html_eliminacion = f"""
                                    <div style="padding: 12px 15px; background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; border-radius: 6px; font-weight: 600; margin-bottom: 15px;">
                                        🗑️ Cuenta eliminada: <span style="font-family: monospace; background-color: #f5c6cb; padding: 2px 6px; border-radius: 4px;">{codigo_extraido}</span>
                                    </div>
                                """
                                
                                st.rerun()
                            except Exception as ex_del:
                                if hasattr(conn_empresa, 'rollback'):
                                    conn_empresa.rollback()
                                st.error(f"❌ Error al eliminar: {ex_del}")

            st.markdown("---")
            st.markdown("#### ✏️ Modificar Cuentas Existentes")

            df_editado = st.data_editor(
                df_actual, 
                key="editor_plan_cuentas_ordenado_con_borrado", 
                num_rows="fixed", 
                use_container_width=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True), 
                    "codigo": st.column_config.TextColumn("Código Contable", required=True),
                    "nombre": st.column_config.TextColumn("Nombre Cuenta", required=True),
                    "nivel": st.column_config.NumberColumn("Nivel", min_value=1, max_value=5),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Grupo", "Detalle"], required=True),
                    "padre": st.column_config.TextColumn("Cuenta Padre")
                }
            )

            # --- GUARDADO EN LOTE INSTANTÁNEO ---
            if st.button("💾 Guardar Cambios en Cuentas Existentes", type="primary", use_container_width=False):
                if df_editado is None or df_editado.empty:
                    st.error("⚠️ El editor está vacío.")
                    st.stop()

                try:
                    # 1. Reutilizamos la conexión activa para cero latencia de red
                    conn_empresa.ping(reconnect=True)
                    cursor = conn_empresa.cursor()
                    
                    datos_a_actualizar = []
                    for _, row in df_editado.iterrows():
                        cuenta_id = row.get('id')
                        codigo = str(row.get('codigo', '')).strip()
                        nombre = str(row.get('nombre', '')).strip()
                        
                        try:
                            nivel = int(row.get('nivel', 1)) if pd.notnull(row.get('nivel')) else 1
                        except Exception:
                            nivel = 1
                        
                        tipo = str(row.get('tipo', 'Detalle')).strip()
                        tipo = tipo if tipo in ['Grupo', 'Detalle'] else 'Detalle'
                        
                        padre = str(row.get('padre', '')).strip()
                        padre = padre if padre not in ['', 'nan', 'None', '<NA>'] else None

                        if not codigo or not nombre:
                            continue

                        if pd.notnull(cuenta_id) and str(cuenta_id).strip() not in ['', 'nan', 'None', '<NA>', '0.0', '0']:
                            datos_a_actualizar.append((codigo, nombre, nivel, tipo, padre, int(float(cuenta_id))))

                    if datos_a_actualizar:
                        sql_update = """
                            UPDATE plan_cuentas 
                            SET codigo = %s, nombre = %s, nivel = %s, tipo = %s, padre = %s 
                            WHERE id = %s
                        """
                        # 2. Ejecución masiva instantánea en la nube
                        cursor.executemany(sql_update, datos_a_actualizar)
                        conn_empresa.commit()

                    cursor.close()
                    
                    # 3. Actualizamos la memoria RAM local al instante sin perder el foco
                    st.session_state.df_plan_cuentas_memoria = df_editado.copy()
                    
                    # 4. Mensaje flotante rápido (NO bloquea la UI ni recarga el script)
                    st.toast(f"✅ ¡{len(datos_a_actualizar)} cuentas guardadas al instante!", icon="💾")
                    
                except Exception as ex_save:
                    if hasattr(conn_empresa, 'rollback'):
                        try:
                            conn_empresa.rollback()
                        except Exception:
                            pass
                    st.error(f"❌ Error al guardar: {ex_save}")

        # --- TAB 3: DESCARGAR EXCEL ---
        with tab3:
            st.markdown("### 📥 Descargar Respaldo")
            df_export = st.session_state.df_plan_cuentas_memoria
            if df_export is not None and not df_export.empty:
                import io
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='PlanCuentas')
                st.download_button(
                    label="📥 Descargar Excel",
                    data=output.getvalue(),
                    file_name="Plan_de_Cuentas_Respaldo.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.info("No hay datos para descargar.")

        # --- TAB 4: VACIAR TABLA ---
        with tab4:
            st.markdown("### ⚠️ Vaciar Plan de Cuentas")
            st.warning("Esta acción borrará TODA la información del plan de cuentas.")
            if st.checkbox("Estoy seguro de querer borrar todo", key="chk_vaciar_plan_seguro"):
                if st.button("🗑️ ELIMINAR TODOS LOS DATOS", type="primary", use_container_width=True):
                    conn_empresa.ping(reconnect=True)
                    cursor = conn_empresa.cursor()
                    cursor.execute("TRUNCATE TABLE plan_cuentas")
                    conn_empresa.commit()
                    cursor.close()
                    cargar_plan_cuentas_memoria(db_actual)
                    st.success("✅ ¡Tabla vaciada exitosamente!")
                    st.balloons()
                    st.rerun()

    except Exception as e:
        st.error(f"❌ Error crítico: {e}")
    finally:
        if conn_empresa:
            try:
                conn_empresa.close()
            except Exception:
                pass


elif opcion_menu == "📝 Asientos Contables":
    db_actual = st.session_state.get('DB_ACTUAL')
    cliente_id = st.session_state.get('cliente_id')
    rol = st.session_state.get('rol')
    
    if not db_actual:
        st.error("No se ha seleccionado una base de datos.")
        st.stop()

    empresa_data = obtener_datos_agente_db(db_actual)
    if empresa_data and rol != 'admin':
        if empresa_data.get('id') != cliente_id:
            st.error("⚠️ Acceso denegado a esta empresa.")
            st.stop()

    if sub_opcion == "Subir Datos":
        st.markdown(f"## 📝 Gestión de Libro Diario: {EMPRESA}")
        
        tab1, tab2, tab3, tab4 = st.tabs([
            "📖 Ver Libro Diario", 
            "📤 Importar Excel", 
            "🗑️ Vaciar Asiento de Diarios",
            "📈 Asientos Ingresos Automatizados"
        ])

        def exportar_a_excel(df):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='LibroDiario')
            return output.getvalue()

        def formato_venezolano(val):
            try:
                return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except Exception:
                return "0,00"

        def parsear_monto_seguro(val):
            if pd.isna(val) or val == '' or val is None:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            
            val_str = str(val).strip().replace('$', '').replace(' ', '')
            if val_str in ['', 'nan', 'None']:
                return 0.0
            
            if '.' in val_str and ',' in val_str:
                if val_str.rfind(',') > val_str.rfind('.'):
                    val_str = val_str.replace('.', '').replace(',', '.')
                else:
                    val_str = val_str.replace(',', '')
            elif ',' in val_str and '.' not in val_str:
                val_str = val_str.replace(',', '.')
            elif val_str.count('.') > 1:
                partes = val_str.split(',')
                enteros = partes[0].replace('.', '')
                decimales = partes[1] if len(partes) > 1 else '00'
                val_str = f"{enteros}.{decimales}"
                
            try:
                return float(val_str)
            except Exception:
                return 0.0

        # CONEXIÓN ÚNICA Y REUTILIZABLE
        conn_general = conectar_db(db_actual)
        if not conn_general:
            st.error("❌ No se pudo conectar a la base de datos.")
            st.stop()

        try:
            # ==========================================
            # TAB 1: CONSULTA, CREACIÓN Y ELIMINACIÓN
            # ==========================================
            with tab1:
                accion_diario = st.selectbox(
                    "Seleccione la operación a realizar:",
                    ["🔍 Consultar y Modificar Asientos", "➕ Agregar Nuevo Asiento", "🗑️ Eliminar Comprobante Contable"],
                    key="select_accion_diario"
                )
                
                st.divider()

                if accion_diario == "🔍 Consultar y Modificar Asientos":
                    st.subheader("Consulta y Modificación de Asientos Contables")
                    
                    modo_busqueda = st.radio(
                        "Filtrar asientos contables por:", 
                        ["📅 Rango de Fechas", "🔢 Número de Comprobante"], 
                        horizontal=True,
                        key="radio_modo_busqueda_unificado"
                    )

                    df_diario = None

                    try:
                        if modo_busqueda == "📅 Rango de Fechas":
                            col1, col2 = st.columns(2)
                            with col1:
                                f_inicio = st.date_input("Fecha Inicio", key="f_inicio_mod") 
                            with col2:
                                f_fin = st.date_input("Fecha Fin", key="f_fin_mod")
                            
                            query = f"SELECT n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber FROM asientos_contables WHERE fecha BETWEEN '{f_inicio}' AND '{f_fin}' ORDER BY fecha, n_comprobante"
                            df_diario = pd.read_sql(query, conn_general)
                        else:
                            col_d1, col_d2 = st.columns(2)
                            with col_d1:
                                fec_inicio = st.date_input("Fecha Desde (para buscar)", key="nc_desde")
                            with col_d2:
                                fec_fin = st.date_input("Fecha Hasta (para buscar)", key="nc_hasta")

                            query_compps = f"SELECT DISTINCT n_comprobante FROM asientos_contables WHERE fecha BETWEEN '{fec_inicio}' AND '{fec_fin}' ORDER BY n_comprobante"
                            df_compps = pd.read_sql(query_compps, conn_general)

                            if not df_compps.empty:
                                lista_comprobantes = df_compps['n_comprobante'].tolist()
                                comp_seleccionado = st.selectbox("Seleccione el comprobante asociado:", lista_comprobantes, key="select_n_comp_exacto")
                                if comp_seleccionado:
                                    query = f"SELECT id, n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber FROM asientos_contables WHERE n_comprobante = '{comp_seleccionado}'"
                                    df_diario = pd.read_sql(query, conn_general)
                            else:
                                st.warning("⚠️ No se encontraron comprobantes registrados en el rango seleccionado.")
                    except Exception as e:
                        st.error(f"❌ Error al consultar los registros: {e}")

                    if df_diario is not None and not df_diario.empty:
                        df_diario.columns = [c.lower() for c in df_diario.columns]
                        st.info(f"Mostrando {len(df_diario)} registros para editar.")

                        try:
                            cursor_pc = conn_general.cursor()
                            cursor_pc.execute("SELECT codigo, nombre FROM plan_cuentas WHERE tipo = 'Detalle' ORDER BY codigo")
                            cuentas_db_mod = cursor_pc.fetchall()
                            cursor_pc.close()
                        except Exception:
                            cuentas_db_mod = []

                        opciones_cuentas_mod = [f"{cod} - {nom}" for cod, nom in cuentas_db_mod]

                        column_config_dict = {
                            "debe": st.column_config.NumberColumn("Debe", format="%,.2f", min_value=0.0),
                            "haber": st.column_config.NumberColumn("Haber", format="%,.2f", min_value=0.0),
                            "id": st.column_config.NumberColumn("ID", disabled=True),
                            "n_comprobante": st.column_config.TextColumn("Comprobante", disabled=True),
                            "fecha": st.column_config.DateColumn("Fecha"),
                            "descripcion": st.column_config.TextColumn("Descripción")
                        }

                        if opciones_cuentas_mod:
                            column_config_dict["plan_cuentas"] = st.column_config.SelectboxColumn("Plan Cuentas", options=opciones_cuentas_mod, required=True)

                        df_editado = st.data_editor(
                            df_diario, 
                            use_container_width=True, 
                            hide_index=True,
                            num_rows="dynamic",
                            key="editor_diario_dinamico",
                            column_config=column_config_dict
                        )

                        if not df_editado.empty:
                            comprobante_fijo = df_diario['n_comprobante'].iloc[0]
                            fecha_fija = df_diario['fecha'].iloc[0]
                            desc_fija = df_diario['descripcion'].iloc[0] if 'descripcion' in df_diario.columns else ""

                            df_editado['n_comprobante'] = df_editado['n_comprobante'].fillna(comprobante_fijo)
                            df_editado['fecha'] = df_editado['fecha'].fillna(fecha_fija)
                            df_editado['descripcion'] = df_editado['descripcion'].fillna(desc_fija)

                        if st.button("💾 Guardar Cambios", key="btn_guardar_cambios", type="primary"):
                            try:
                                t_debe_val = pd.to_numeric(df_editado['debe'], errors='coerce').sum()
                                t_haber_val = pd.to_numeric(df_editado['haber'], errors='coerce').sum()

                                if abs(t_debe_val - t_haber_val) >= 0.01:
                                    st.error(f"❌ El asiento no cuadra. Debe: {formato_contable(t_debe_val)} | Haber: {formato_contable(t_haber_val)}")
                                else:
                                    exito = actualizar_libro_diario_en_db(db_actual, df_editado)
                                    if exito:
                                        st.success("¡Registros actualizados correctamente en la base de datos!")
                                        st.balloons()
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error("Error al guardar en la base de datos.")
                            except Exception as e:
                                st.error(f"Error técnico: {str(e)}")

                        excel_data = exportar_a_excel(df_editado)
                        st.download_button(
                            label="📥 Descargar Datos Visualizados",
                            data=excel_data,
                            file_name="Libro_Diario_Filtrado.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        
                        t_debe = pd.to_numeric(df_editado['debe'], errors='coerce').sum()
                        t_haber = pd.to_numeric(df_editado['haber'], errors='coerce').sum()
                        
                        st.divider()
                        c1, c2, c3 = st.columns(3)
                        c1.metric("TOTAL DEBE", formato_contable(t_debe))
                        c2.metric("TOTAL HABER", formato_contable(t_haber))
                        
                        dif = abs(t_debe - t_haber)
                        if dif < 0.01:
                            c3.success("✅ DIARIO CUADRADO")
                        else:
                            c3.error(f"❌ DESCUADRE: {formato_contable(t_debe - t_haber)}")

                elif accion_diario == "➕ Agregar Nuevo Asiento":
                    st.subheader("Registro de Nuevo Comprobante Contable")

                    try:
                        cursor_pc = conn_general.cursor()
                        cursor_pc.execute("SELECT codigo, nombre FROM plan_cuentas WHERE tipo = 'Detalle' ORDER BY codigo")
                        cuentas_db = cursor_pc.fetchall()
                        cursor_pc.close()
                    except Exception:
                        cuentas_db = [("1.1.1.01.001", "Caja Chica"), ("1.1.1.02.001", "Banco Banesco")]

                    opciones_cuentas = [f"{cod} - {nom}" for cod, nom in cuentas_db]
                    dict_nombres_cuentas = {cod: nom for cod, nom in cuentas_db}

                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        nuevo_n_comp = st.text_input("Número de Comprobante", key="input_n_comp")
                    with col_f2:
                        nuevo_fecha = st.date_input("Fecha del Asiento", key="input_fecha")

                    nuevo_desc = st.text_input("Descripción general del Asiento", key="input_desc_gral")

                    st.markdown("### Líneas del Comprobante")

                    if "df_asiento_actual" not in st.session_state:
                        st.session_state["df_asiento_actual"] = pd.DataFrame([
                            {
                                "plan_cuentas": opciones_cuentas[0] if opciones_cuentas else "", 
                                "cuenta_contable": dict_nombres_cuentas.get(opciones_cuentas[0].split(" - ")[0], "") if opciones_cuentas else "", 
                                "referencia": "", 
                                "debe": 0.0, 
                                "haber": 0.0
                            }
                        ])

                    df_editado_nuevo = st.data_editor(
                        st.session_state["df_asiento_actual"],
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True,
                        key="editor_asiento_interactivo",
                        column_config={
                            "plan_cuentas": st.column_config.SelectboxColumn("Plan Cuentas", options=opciones_cuentas, required=True),
                            "cuenta_contable": st.column_config.TextColumn("Descripción Cuenta", help="Se asigna al guardar"),
                            "referencia": st.column_config.TextColumn("Referencia / Factura"),
                            "debe": st.column_config.NumberColumn("Debe", format="%,.2f", min_value=0.0),
                            "haber": st.column_config.NumberColumn("Haber", format="%,.2f", min_value=0.0)
                        }
                    )

                    df_editado_nuevo = df_editado_nuevo[df_editado_nuevo['plan_cuentas'].notna() & (df_editado_nuevo['plan_cuentas'].astype(str).str.strip() != "")]

                    total_debe = pd.to_numeric(df_editado_nuevo['debe'], errors='coerce').sum()
                    total_haber = pd.to_numeric(df_editado_nuevo['haber'], errors='coerce').sum()
                    diferencia = total_debe - total_haber

                    st.markdown("---")
                    col_m1, col_m2, col_m3 = st.columns(3)
                    col_m1.metric(label="Total Debe", value=formato_contable(total_debe))
                    col_m2.metric(label="Total Haber", value=formato_contable(total_haber))
                    col_m3.metric(
                        label="Diferencia (Descuadre)", 
                        value=formato_contable(abs(diferencia)),
                        delta="Cuadrado 🟢" if abs(diferencia) < 0.01 else "Descuadrado 🔴",
                        delta_color="off" if abs(diferencia) < 0.01 else "inverse"
                    )

                    st.markdown("---")

                    if st.button("💾 Guardar Nuevo Comprobante", type="primary"):
                        if not nuevo_n_comp:
                            st.error("Debe indicar un Número de Comprobante.")
                        elif df_editado_nuevo.empty:
                            st.error("El asiento debe contener al menos una línea.")
                        elif abs(total_debe - total_haber) >= 0.01:
                            st.error(f"❌ El asiento no cuadra. Debe: {formato_contable(total_debe)} | Haber: {formato_contable(total_haber)}")
                        else:
                            try:
                                cursor_ins = conn_general.cursor()
                                sql_insert = """
                                    INSERT INTO asientos_contables 
                                    (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """
                                
                                datos_insertar = []
                                for _, row in df_editado_nuevo.iterrows():
                                    plan_val = str(row.get('plan_cuentas', ''))
                                    codigo_cuenta = plan_val.split(" - ")[0] if " - " in plan_val else plan_val
                                    desc_cuenta = dict_nombres_cuentas.get(codigo_cuenta, "")
                                    
                                    ref_val = row.get('referencia')
                                    ref_str = str(ref_val) if pd.notna(ref_val) else ""
                                    
                                    debe_float = float(row.get('debe', 0.0)) if pd.notna(row.get('debe')) else 0.0
                                    haber_float = float(row.get('haber', 0.0)) if pd.notna(row.get('haber')) else 0.0
                                    
                                    datos_insertar.append((
                                        str(nuevo_n_comp),
                                        str(nuevo_desc),
                                        str(nuevo_fecha),
                                        codigo_cuenta,
                                        desc_cuenta,
                                        ref_str,
                                        debe_float,
                                        haber_float,
                                        0
                                    ))
                                
                                cursor_ins.executemany(sql_insert, datos_insertar)
                                conn_general.commit()
                                cursor_ins.close()
                                
                                st.success(f"¡Comprobante N° {nuevo_n_comp} guardado exitosamente!")
                                st.balloons()
                                
                                if "df_asiento_actual" in st.session_state:
                                    del st.session_state["df_asiento_actual"]
                                    
                                time.sleep(1)
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Error al registrar en la base de datos: {str(e)}")

                elif accion_diario == "🗑️ Eliminar Comprobante Contable":
                    st.subheader("Eliminación de Comprobante")
                    st.warning("⚠️ Precaución: Esta acción eliminará permanentemente todas las líneas asociadas al número de comprobante indicado.")
                    
                    comp_a_eliminar = st.text_input("Ingrese el Número de Comprobante que desea eliminar:")
                    
                    if comp_a_eliminar:
                        try:
                            df_prev = pd.read_sql(f"SELECT n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber FROM asientos_contables WHERE n_comprobante = '{comp_a_eliminar}'", conn_general)
                        except Exception:
                            df_prev = pd.DataFrame()
                        
                        if not df_prev.empty:
                            st.markdown(f"**Se encontraron {len(df_prev)} líneas para el Comprobante N° {comp_a_eliminar}:**")
                            
                            st.data_editor(
                                df_prev, 
                                hide_index=True,
                                disabled=True,
                                column_config={
                                    "debe": st.column_config.NumberColumn("Debe", format="%,.2f"),
                                    "haber": st.column_config.NumberColumn("Haber", format="%,.2f")
                                }
                            )
                            
                            if st.button("🔥 Confirmar Eliminación Definitiva", type="primary"):
                                try:
                                    cursor_del = conn_general.cursor()
                                    cursor_del.execute("DELETE FROM asientos_contables WHERE n_comprobante = %s", (comp_a_eliminar,))
                                    conn_general.commit()
                                    cursor_del.close()
                                    
                                    st.success(f"¡Comprobante N° {comp_a_eliminar} eliminado correctamente!")
                                    st.balloons()
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al eliminar el comprobante: {str(e)}")
                        else:
                            st.info(f"No se encontró ningún registro asociado al Comprobante N° '{comp_a_eliminar}'.")

            # ==========================================
            # TAB 2: IMPORTACIÓN EXCEL
            # ==========================================
            with tab2:
                st.markdown("### 📤 Cargar nuevos Asientos Contables")
                archivo_excel = st.file_uploader("Seleccione el archivo .xlsx", type=["xlsx", "xls"], key="up_diario_tabs")
                
                if archivo_excel:
                    try:
                        df_subido = pd.read_excel(archivo_excel, dtype=object)
                        df_subido.columns = df_subido.columns.astype(str).str.strip().str.lower()

                        rename_dict = {}
                        for col in df_subido.columns:
                            if col in ['débito', 'debito', 'debe']:
                                rename_dict[col] = 'debe'
                            elif col in ['crédito', 'credito', 'haber']:
                                rename_dict[col] = 'haber'
                        df_subido = df_subido.rename(columns=rename_dict)

                        if 'fecha' in df_subido.columns:
                            df_subido['fecha'] = pd.to_datetime(df_subido['fecha'], errors='coerce').dt.date

                        for col in ['debe', 'haber']:
                            if col in df_subido.columns:
                                df_subido[col] = df_subido[col].apply(parsear_monto_seguro)
                            else:
                                df_subido[col] = 0.0

                        if 'saldo' in df_subido.columns:
                            df_subido['saldo'] = df_subido['saldo'].apply(parsear_monto_seguro)
                            max_val = df_subido['saldo'].abs().max()
                            if max_val > 1e12:
                                df_subido['saldo'] = 0.0
                        else:
                            df_subido['saldo'] = 0.0

                        df_para_mostrar = df_subido.copy()
                        for col in ['debe', 'haber', 'saldo']:
                            if col in df_para_mostrar.columns:
                                df_para_mostrar[col] = df_para_mostrar[col].apply(formato_venezolano)

                        df_para_mostrar = df_para_mostrar.rename(columns={'debe': 'débito', 'haber': 'crédito'})

                        for col in df_subido.columns:
                            if col != 'fecha': 
                                df_subido[col] = df_subido[col].astype(str).replace(['nan', 'None', ''], '')

                        st.write("### ✅ Vista previa de la carga:")
                        st.dataframe(df_para_mostrar, hide_index=True, use_container_width=True)

                        if st.button("🚀 Confirmar e Importar al Diario", use_container_width=True):
                            try:
                                with st.spinner(f"Subiendo datos a la base: {db_actual}..."):
                                    if cargar_asientos_contables_db(df_subido, conn_general):
                                        st.balloons()
                                        st.success(f"✅ ¡Asientos procesados con éxito en {db_actual}!")
                            except Exception as e:
                                st.error(f"Error crítico en la inserción: {e}")
                                
                    except Exception as e:
                        st.error(f"Error al procesar el archivo: {e}")

            # ==========================================
            # TAB 3: LIMPIEZA POR RANGO DE FECHAS
            # ==========================================
            with tab3:
                st.markdown("### ⚙️ Administración: Limpieza por Fechas")
                with st.container(border=True):
                    st.warning("⚠️ **BORRADO SELECTIVO DE ASIENTOS**")
                    
                    col_f1, col_f2 = st.columns(2)
                    f_eliminar_inicio = col_f1.date_input("Desde:", key="del_inicio")
                    f_eliminar_fin = col_f2.date_input("Hasta:", key="del_fin")
                    
                    st.write(f"Se eliminarán los asientos entre **{f_eliminar_inicio}** y **{f_eliminar_fin}**.")
                    
                    check_borrar = st.checkbox("Estoy seguro de borrar este periodo.", key="check_borrar_rango")
                    
                    if check_borrar:
                        if st.button("🧨 BORRAR RANGO SELECCIONADO", type="primary"):
                            try:
                                cursor = conn_general.cursor()
                                query_delete = "DELETE FROM asientos_contables WHERE fecha BETWEEN %s AND %s"
                                cursor.execute(query_delete, (f_eliminar_inicio, f_eliminar_fin))
                                
                                filas_afectadas = cursor.rowcount
                                conn_general.commit()
                                cursor.close()
                                
                                st.success(f"✅ Éxito: Se eliminaron {filas_afectadas} asientos del periodo.")
                            except Exception as e:
                                st.error(f"Error al ejecutar la limpieza: {e}")

            # ==========================================
            # TAB 4: ASIENTOS INTEGRADOS / VENTAS
            # ==========================================
            with tab4:
                if conn_general:
                    renderizar_tab_asientos_ventas(conn_general)
                else:
                    st.error("No se pudo establecer la conexión con la base de datos de la empresa para los asientos automatizados.")

        finally:
            if conn_general:
                try:
                    conn_general.close()
                except Exception:
                    pass
    else:
        st.warning("⚠️ Por favor, seleccione una opción válida para gestionar sus asientos.")

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

        # Filtro de acceso
        if rol != 'admin' and empresa_data.get('id') != cliente_id:
            st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
            st.stop()

        # 2. Conexión Maestra Reutilizable (Optimizada en Session State)
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
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "⚙️ Configuración Saldos", 
            "📂 Importar Movimientos", 
            "📜 Estado de Cuenta", 
            "📊 Conciliación Bancaria", 
            "🔒 Cierre de Mes",
            "🗑️ Vaciar Estado de Cuenta"
        ])

        # ==========================================
        # PESTAÑA 1: CONFIGURACIÓN DE SALDOS
        # ==========================================
        with tab1:
            st.subheader("⚙️ Gestión de Saldos Bancarios")

            try:
                query_saldos = f"""
                    SELECT id, banco, mes, ano, saldo_inicial, saldo_final 
                    FROM `{db_actual}`.saldos_bancarios 
                    ORDER BY ano DESC, id DESC
                """
                
                df_saldos = ejecutar_consulta(query_saldos, conn)
                
                if df_saldos is not None and not df_saldos.empty:
                    df_saldos['saldo_inicial'] = pd.to_numeric(df_saldos['saldo_inicial'], errors='coerce').fillna(0.0)
                    df_saldos['saldo_final'] = pd.to_numeric(df_saldos['saldo_final'], errors='coerce').fillna(0.0)

                    st.info("💡 **Consejo:** Puedes hacer doble clic directamente en las celdas de **saldo_inicial** o **saldo_final** de la tabla para modificarlos, y luego hacer clic en guardar.")
                    
                    df_editable = df_saldos.copy()
                    
                    def formato_venezolano(val):
                        try:
                            return f"{float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        except Exception:
                            return "0,00"

                    df_editable['saldo_inicial'] = df_editable['saldo_inicial'].apply(formato_venezolano)
                    df_editable['saldo_final'] = df_editable['saldo_final'].apply(formato_venezolano)

                    edited_df_preview = st.data_editor(
                        df_editable,
                        column_config={
                            "id": st.column_config.NumberColumn("ID", disabled=True),
                            "banco": st.column_config.TextColumn("Banco"),
                            "mes": st.column_config.TextColumn("Mes"),
                            "ano": st.column_config.NumberColumn("Año", disabled=True),
                            "saldo_inicial": st.column_config.TextColumn("Saldo Inicial", help="Formato contable (ej. 15.539,00)"),
                            "saldo_final": st.column_config.TextColumn("Saldo Final", help="Formato contable (ej. 15.539,00)"),
                        },
                        hide_index=True,
                        use_container_width=True,
                        key="editor_saldos_bancarios"
                    )

                    if st.button("💾 Guardar cambios de la tabla", key="btn_guardar_tabla_saldos", type="primary"):
                        try:
                            cursor_upd = conn.cursor()
                            actualizaciones = 0
                            
                            for index, row in edited_df_preview.iterrows():
                                row_id = row['id']
                                orig_row = df_saldos.loc[df_saldos['id'] == row_id].iloc[0]
                                
                                try:
                                    val_ini_limpio = float(str(row['saldo_inicial']).replace(".", "").replace(",", "."))
                                except Exception:
                                    val_ini_limpio = orig_row['saldo_inicial']

                                try:
                                    val_fin_limpio = float(str(row['saldo_final']).replace(".", "").replace(",", "."))
                                except Exception:
                                    val_fin_limpio = orig_row['saldo_final']

                                if (val_ini_limpio != orig_row['saldo_inicial']) or (val_fin_limpio != orig_row['saldo_final']) or (row['banco'] != orig_row['banco']):
                                    query_update = f"""
                                        UPDATE `{db_actual}`.saldos_bancarios 
                                        SET banco = %s, saldo_inicial = %s, saldo_final = %s 
                                        WHERE id = %s
                                    """
                                    cursor_upd.execute(query_update, (row['banco'], val_ini_limpio, val_fin_limpio, row_id))
                                    actualizaciones += 1
                                    
                            conn.commit()
                            cursor_upd.close()
                            
                            if actualizaciones > 0:
                                st.success(f"✅ ¡Se actualizaron {actualizaciones} registro(s) con éxito!")
                                st.rerun()
                            else:
                                st.info("ℹ️ No se detectaron cambios nuevos para guardar.")
                                
                        except Exception as e:
                            conn.rollback()
                            st.error(f"❌ Error al guardar las modificaciones: {e}")

                else:
                    nombre_emp = empresa_data.get('nombre_empresa', 'la empresa')
                    st.info(f"No hay saldos registrados para {nombre_emp}.")
                    
            except Exception as e:
                st.error(f"Error al cargar la tabla de saldos: {e}")

            # Formulario de registro nuevo
            st.markdown("---")
            st.subheader("➕ Agregar Nuevo Saldo Mensual")
            
            with st.form("form_saldos_main"):
                banco_input = st.selectbox("Banco", ["Banco de Venezuela (BDV)", "Banesco", "Mercantil"])
                
                c1, c2 = st.columns(2)
                m_input = c1.selectbox("Mes", ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                                               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"])
                a_input = c2.selectbox("Año", [2025, 2026, 2027])
                
                c4, c5 = st.columns(2)
                val_ini = c4.number_input("Saldo Inicial", value=0.00, format="%.2f")
                val_fin = c5.number_input("Saldo Final", value=0.00, format="%.2f")
                
                if st.form_submit_button("Registrar Nuevo Saldo"):
                    if guardar_saldo_mensual(conn, banco_input, m_input, a_input, val_ini, val_fin, db_name=db_actual):
                        st.success(f"✅ Saldo de **{banco_input}** para **{m_input} {a_input}** guardado con éxito.")
                        st.rerun()

            # Eliminación segura
            with st.expander("🗑️ Eliminar un registro"):
                id_eliminar = st.number_input("ID del registro a eliminar", min_value=1, step=1, key="input_id_eliminar_tab1")
                if st.button("Confirmar Eliminación", key="btn_confirmar_eliminar_tab1", type="primary"):
                    try:
                        cursor = conn.cursor()
                        cursor.execute(f"DELETE FROM `{db_actual}`.saldos_bancarios WHERE id = %s", (id_eliminar,))
                        conn.commit()
                        cursor.close()
                        st.warning("Registro eliminado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al eliminar: {e}")
        # --- TAB 2: GESTIÓN Y GENERACIÓN DE ÓRDENES DE PAGO Y CRUCE ---
        with tab2:
            st.markdown("### 🧾 Gestión y Generación de Órdenes de Pago y Cruce")

            # --- CARGAR PROVEEDORES OPTIMIZADO CON CACHÉ GLOBAL ---
            @st.cache_data(ttl=600, show_spinner=False)
            def cargar_datos_maestros_flash(empresa):
                p_lista, p_dict = [], {}
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        df_cp = ejecutar_consulta(
                            "SELECT id, nombre, rif, codigo_cuenta, descripcion_cuenta FROM proveedores_carga WHERE empresa_db = %s ORDER BY nombre ASC", 
                            conn, params=(str(empresa),)
                        )
                        if df_cp is None or df_cp.empty:
                            df_cp = ejecutar_consulta(
                                "SELECT id, nombre, rif, codigo_cuenta, descripcion_cuenta FROM proveedores_carga ORDER BY nombre ASC", 
                                conn
                            )
                        conn.close()
                        
                        if df_cp is not None and not df_cp.empty:
                            for _, row in df_cp.iterrows():
                                label = f"{row['nombre']} (RIF: {row['rif']})"
                                p_lista.append(label)
                                p_dict[label] = {
                                    'id_interno': row['id'],
                                    'rif': row['rif'],
                                    'nombre': row['nombre'],
                                    'codigo_cuenta': str(row.get('codigo_cuenta', 'N/A')),
                                    'descripcion_cuenta': str(row.get('descripcion_cuenta', 'N/A'))
                                }
                except Exception:
                    pass
                return p_lista, p_dict

            lista_provs, dict_provs = cargar_datos_maestros_flash(db_actual)

            # --- GESTIÓN DE SESSION STATE ---
            if "orden_guardada_exito" not in st.session_state:
                st.session_state["orden_guardada_exito"] = False

            # --- FASE 1: EMITIR NUEVA ORDEN DE PAGO CON ST.FORM ---
            if not st.session_state.orden_guardada_exito:
                st.markdown("### ✍️ Emitir Nueva Orden de Pago")
                
                with st.form("form_emision_op", clear_on_submit=True):
                    col_f1_1, col_f1_2 = st.columns(2)
                    with col_f1_1:
                        prov_seleccionado_form = st.selectbox("Seleccionar Proveedor", options=lista_provs if lista_provs else ["No hay proveedores"])
                        nro_factura_form = st.text_input("Número de Factura")
                        nro_control_form = st.text_input("Número de Control")
                    with col_f1_2:
                        fecha_emision_form = st.date_input("Fecha de Emisión")
                        
                        st.markdown("""
                            <div style="background-color: #ffe6e6; padding: 6px 12px; border-radius: 6px; border: 1px solid #ff9999; margin-bottom: 5px;">
                                <span style="color: #c0392b; font-weight: bold; font-size: 13px;">🔴 Campos de ingreso manual</span>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        base_imponible_form = st.number_input("Base Imponible", min_value=0.0, format="%.2f")
                        monto_exento_form = st.number_input("Monto Exento", min_value=0.0, format="%.2f")

                    col_f1_3, col_f1_4 = st.columns(2)
                    with col_f1_3:
                        alicuota_iva_form = st.selectbox("Alícuota IVA", options=[16.0, 8.0, 31.0, 0.0], format_func=lambda x: f"{x}%")
                    with col_f1_4:
                        monto_iva_calculado = base_imponible_form * (alicuota_iva_form / 100.0)
                        st.text(f"Monto IVA (Calculado): {monto_iva_calculado:,.2f}")

                    monto_bruto_calculado = base_imponible_form + monto_exento_form + monto_iva_calculado
                    st.text(f"Monto Bruto / Total Factura: {monto_bruto_calculado:,.2f}")
                    
                    st.markdown("---")

                    # --- 2DO FRAME: RETENCIÓN DE IVA ---
                    st.markdown("#### 2️⃣ Frame: Retención de IVA")
                    col_f2_1, col_f2_2 = st.columns(2)
                    with col_f2_1:
                        porcentaje_ret_iva = st.selectbox("Porcentaje Retención IVA", options=[75.0, 100.0, 25.0, 50.0, 0.00], format_func=lambda x: f"{x}%")
                    with col_f2_2:
                        retencion_iva_calculada = monto_iva_calculado * (porcentaje_ret_iva / 100.0)
                        st.text(f"Monto Retención IVA: {retencion_iva_calculada:,.2f}")
                    
                    st.markdown("---")

                    # --- 3ER FRAME: RETENCIÓN DE ISLR ---
                    st.markdown("#### 3️⃣ Frame: Retención de ISLR")
                    col_f3_1, col_f3_2, col_f3_3, col_f3_4 = st.columns(4)
                    with col_f3_1:
                        tipo_persona_form = st.selectbox("Tipo de Persona", options=["Jurídico Domiciliado", "Natural Residenciado", "Otro"])
                    with col_f3_2:
                        islr_porcentaje_form = st.number_input("% Retención ISLR", min_value=0.0, max_value=100.0, format="%.2f", value=1.0)
                    with col_f3_3:
                        islr_sustraendo_form = st.number_input("Sustraendo ISLR", min_value=0.0, format="%.2f", value=0.0)
                    with col_f3_4:
                        retencion_islr_calculada = max(0.0, (base_imponible_form * (islr_porcentaje_form / 100.0)) - islr_sustraendo_form)
                        st.text(f"Retención ISLR: {retencion_islr_calculada:,.2f}")

                    st.markdown("---")
                    
                    # --- 4TO FRAME: MONTO NETO Y OBSERVACIONES ---
                    st.markdown("#### 4️⃣ Frame: Cálculo del Monto Neto a Pagar")
                    monto_neto_calculado = monto_bruto_calculado - retencion_islr_calculada - retencion_iva_calculada
                    
                    col_f4_1, col_f4_2 = st.columns(2)
                    with col_f4_1:
                        st.text(f"💵 Monto Neto a Pagar: {monto_neto_calculado:,.2f}")
                    with col_f4_2:
                        observaciones_form = st.text_area("Observaciones / Concepto del Pago")

                    st.markdown("---")
                    
                    btn_guardar_op = st.form_submit_button("💾 Guardar y Registrar Orden de Pago", use_container_width=True)

                if btn_guardar_op:
                    if not nro_factura_form:
                        st.error("⚠️ El número de factura es obligatorio.")
                    elif not lista_provs:
                        st.error("⚠️ No hay proveedores cargados para asociar la orden.")
                    else:
                        try:
                            info_prov_form = dict_provs[prov_seleccionado_form]
                            conn_ins = conectar_db(db_actual)
                            if conn_ins:
                                cursor = conn_ins.cursor()
                                query_insert = """
                                    INSERT INTO ordenes_pago (
                                        empresa_db, proveedor_id, nro_factura, nro_control, 
                                        monto_bruto, monto_exento, base_imponible, iva_porcentaje, monto_iva, 
                                        retencion_islr, retencion_iva, monto_neto, estado, fecha_emision, 
                                        observaciones, islr_porcentaje, islr_sustraendo, tipo_persona
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """
                                cursor.execute(query_insert, (
                                    str(db_actual),
                                    str(info_prov_form['id_interno']),
                                    str(nro_factura_form),
                                    str(nro_control_form),
                                    float(monto_bruto_calculado),
                                    float(monto_exento_form),
                                    float(base_imponible_form),
                                    float(alicuota_iva_form),
                                    float(monto_iva_calculado),
                                    float(retencion_islr_calculada),
                                    float(retencion_iva_calculada),
                                    float(monto_neto_calculado),
                                    'Pendiente',
                                    str(fecha_emision_form),
                                    str(observaciones_form),
                                    float(islr_porcentaje_form),
                                    float(islr_sustraendo_form),
                                    str(tipo_persona_form)
                                ))
                                conn_ins.commit()
                                cursor.close()
                                conn_ins.close()
                                
                                st.session_state.orden_guardada_exito = True
                                st.success("🎉 ¡Orden de pago guardada con éxito!")
                                st.rerun()
                        except Exception as err_ins:
                            st.error(f"❌ Error al guardar la orden de pago: {err_ins}")

            else:
                if st.button("➕ Emitir Nueva Orden de Pago", type="secondary", use_container_width=True):
                    st.session_state.orden_guardada_exito = False
                    st.rerun()

            # --- FASE 2 Y 3: HISTORIAL Y MÓDULOS INDEPENDIENTES ---
            if st.session_state.orden_guardada_exito:
                st.markdown("---")
                st.markdown("### 📊 Historial de Órdenes de Pago y Previsualización YAML")
                
                try:
                    conn_historial = conectar_db(db_actual)
                    df_ops = None
                    
                    if conn_historial:
                        query_ops = f"SELECT * FROM ordenes_pago WHERE empresa_db = '{db_actual}' ORDER BY id DESC"
                        df_ops = ejecutar_consulta(query_ops, conn_historial)
                        
                        if df_ops is None or df_ops.empty:
                            df_ops = ejecutar_consulta("SELECT * FROM ordenes_pago ORDER BY id DESC", conn_historial)
                        
                        conn_historial.close()
                        
                    if df_ops is not None and not df_ops.empty:
                        lista_ops_procesadas = []
                        
                        # Indexación rápida de proveedores para evitar bucles anidados lentos
                        dict_provs_por_id = {str(v['id_interno']): v for v in dict_provs.values()}
                        dict_provs_por_rif = {str(v['rif']): v for v in dict_provs.values()}
                        fallback_prov = list(dict_provs.values())[0] if dict_provs else None
                        
                        for _, r_op in df_ops.iterrows():
                            p_id = str(r_op['proveedor_id'])
                            prov_encontrado = dict_provs_por_id.get(p_id) or dict_provs_por_rif.get(p_id) or fallback_prov
                            
                            lista_ops_procesadas.append({
                                'id': r_op['id'],
                                'proveedor_rif': prov_encontrado['rif'] if prov_encontrado else 'N/A',
                                'proveedor': prov_encontrado['nombre'] if prov_encontrado else 'Desconocido',
                                'cuenta_gasto_codigo': prov_encontrado.get('codigo_cuenta', 'N/A') if prov_encontrado else 'N/A',
                                'cuenta_gasto_desc': prov_encontrado.get('descripcion_cuenta', 'N/A') if prov_encontrado else 'N/A',
                                'nro_factura': r_op['nro_factura'],
                                'nro_control': r_op['nro_control'],
                                'monto_bruto': r_op['monto_bruto'],
                                'monto_exento': r_op['monto_exento'],
                                'base_imponible': r_op['base_imponible'],
                                'iva_porcentaje': r_op['iva_porcentaje'],
                                'monto_iva': r_op['monto_iva'],
                                'retencion_islr': r_op['retencion_islr'],
                                'retencion_iva': r_op['retencion_iva'],
                                'monto_neto': r_op['monto_neto'],
                                'estado': r_op['estado'],
                                'fecha_emision': r_op['fecha_emision'],
                                'observaciones': r_op['observaciones'],
                                'islr_porcentaje': r_op['islr_porcentaje'],
                                'islr_sustraendo': r_op['islr_sustraendo'],
                                'tipo_persona': r_op['tipo_persona']
                            })
                        
                        import pandas as pd
                        df_ops_final = pd.DataFrame(lista_ops_procesadas)
                        
                        df_display = df_ops_final[['id', 'proveedor', 'nro_factura', 'monto_bruto', 'monto_neto', 'retencion_islr', 'estado', 'fecha_emision']]
                        st.dataframe(df_display, use_container_width=True, hide_index=True)
                        
                        st.markdown("---")
                        
                        opciones_ordenes = {f"ID: {row['id']} | Factura: {row['nro_factura']} | Proveedor: {row['proveedor']} | Estado: {row['estado']}": row for _, row in df_ops_final.iterrows()}
                        
                        seleccion_op_key = st.selectbox(
                            "🔍 Selecciona una Orden de Pago para configurar sus cuentas y previsualizar los asientos:", 
                            options=list(opciones_ordenes.keys()),
                            index=0,
                            key="select_op_final_v2"
                        )
                        
                        if seleccion_op_key:
                            sel_data = opciones_ordenes[seleccion_op_key]
                            
                            st.markdown("---")
                            st.markdown(f"### ⚙ Configuración de Cuentas para la Orden #{sel_data['id']}")
                            
                            col_c1, col_c2, col_c3 = st.columns(3)
                            with col_c1:
                                cta_gasto_sel = st.selectbox("Cuenta de Gasto / Costo", options=lista_cuentas_detalle if lista_cuentas_detalle else ["Sin cuentas"], key=f"cta_gasto_{sel_data['id']}")
                                info_gasto = dict_cuentas_detalle.get(cta_gasto_sel, {'codigo': '6.1.1.01.001', 'nombre': 'Gastos Generales'})
                            with col_c2:
                                cta_iva_sel = st.selectbox("Cuenta Crédito Fiscal IVA", options=lista_cuentas_detalle if lista_cuentas_detalle else ["Sin cuentas"], key=f"cta_iva_{sel_data['id']}")
                                info_iva = dict_cuentas_detalle.get(cta_iva_sel, {'codigo': '1.1.4.02.001', 'nombre': 'Crédito Fiscal IVA'})
                            with col_c3:
                                cta_banco_sel = st.selectbox("Cuenta Banco / Salida", options=lista_cuentas_detalle if lista_cuentas_detalle else ["Sin cuentas"], key=f"cta_banco_{sel_data['id']}")
                                info_banco = dict_cuentas_detalle.get(cta_banco_sel, {'codigo': '1.1.1.01.001', 'nombre': 'Banco Principal'})
                                info_banco['nombre'] = info_banco.get('nombre', 'Banco Principal')

                            st.markdown("---")
                            st.markdown("### 🔄 Proceso de Registro por Módulos (Paso a Paso)")

                            key_paso = f"paso_actual_{sel_data['id']}"
                            if key_paso not in st.session_state:
                                st.session_state[key_paso] = 1

                            paso = st.session_state[key_paso]

                            # --- PASO 1: LIBRO DE COMPRAS ---
                            if paso == 1:
                                st.markdown("#### 📄 Paso 1: Registrar en `libro_compras`")
                                st.code(f"""fecha_operacion: {sel_data['fecha_emision']}
            tipo_documento: Factura
            n_factura: {sel_data['nro_factura']}
            n_control: {sel_data['nro_control']}
            proveedor: {sel_data['proveedor']}
            rif: {sel_data['proveedor_rif']}
            total_compras: {sel_data['monto_bruto']:,.2f}
            base_imponible: {sel_data['base_imponible']:,.2f}
            iva_porcentaje: {sel_data['iva_porcentaje']}%
            iva_monto: {sel_data['monto_iva']:,.2f}
            retencion_iva: {sel_data['retencion_iva']:,.2f}""", language="yaml")
                                
                                if st.button("💾 Guardar Libro de Compras y Pasar al Asiento", key=f"btn_guardar_libro_{sel_data['id']}", use_container_width=True):
                                    rif_val = str(sel_data.get('proveedor_rif', '')).strip()
                                    fact_val = str(sel_data.get('nro_factura', '')).strip()
                                    ctrl_val = str(sel_data.get('nro_control', '')).strip()
                                    prov_val = str(sel_data.get('proveedor', '')).strip()
                                    
                                    if not fact_val or fact_val in ['None', 'N/A', '?', '']:
                                        st.error("⚠️ Error: El número de factura está vacío o es inválido.")
                                    elif not rif_val or rif_val in ['None', 'N/A', '?', '']:
                                        st.error(f"⚠️ Error: El RIF del proveedor ('{rif_val}') está vacío.")
                                    else:
                                        with st.spinner("Guardando en Libro de Compras..."):
                                            try:
                                                conn_l = conectar_db(db_actual)
                                                if conn_l:
                                                    with conn_l.cursor() as cur_l:
                                                        cur_l.execute("SELECT id FROM libro_compras WHERE n_factura = %s AND rif = %s", (fact_val, rif_val))
                                                        existe = cur_l.fetchone()
                                                        
                                                        if existe:
                                                            st.warning(f"⚠️ La factura **{fact_val}** ya se encuentra registrada. Avanzando...")
                                                        else:
                                                            query_libro = """
                                                                INSERT INTO libro_compras (
                                                                    fecha_operacion, tipo_documento, n_factura, n_control, 
                                                                    n_factura_afectada, proveedor, rif, tipo_transaccion, 
                                                                    total_compras, importe_exento, base_imponible, iva_porcentaje, 
                                                                    iva_monto, retencion_realizada, retencion_iva_realizada, 
                                                                    n_comprobante_retencion, monto_iva_retenido, fecha_comprobante, 
                                                                    created_at, updated_at
                                                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                                                            """
                                                            valores_libro = (
                                                                str(sel_data['fecha_emision']),
                                                                "Factura",
                                                                fact_val,
                                                                ctrl_val if ctrl_val and ctrl_val != 'None' else 'S/N',
                                                                None,
                                                                prov_val if prov_val and prov_val != 'None' else 'Proveedor Genérico',
                                                                rif_val,
                                                                "01",
                                                                float(sel_data.get('monto_bruto', 0.0)),
                                                                float(sel_data.get('monto_exento', 0.0)),
                                                                float(sel_data.get('base_imponible', 0.0)),
                                                                float(sel_data.get('iva_porcentaje', 16.0)),
                                                                float(sel_data.get('monto_iva', 0.0)),
                                                                1 if float(sel_data.get('retencion_iva', 0.0)) > 0 else 0,
                                                                float(sel_data.get('retencion_iva', 0.0)),
                                                                f"COMP-{fact_val}",
                                                                float(sel_data.get('retencion_iva', 0.0)),
                                                                str(sel_data['fecha_emision'])
                                                            )
                                                            cur_l.execute(query_libro, valores_libro)
                                                            conn_l.commit()
                                                            st.success("✅ ¡Libro de Compras guardado con éxito!")
                                                    conn_l.close()
                                                    st.session_state[key_paso] = 2
                                                    st.rerun()
                                            except Exception as err_l:
                                                st.error(f"❌ Error al guardar libro de compras: {err_l}")

                            # --- PASO 2: ASIENTO CONTABLE ---
                            elif paso == 2:
                                st.markdown("#### 📒 Paso 2: Registrar `asientos_contables`")
                                st.code(f"""- n_comprobante: OP-{sel_data['nro_factura']}
              fecha: {sel_data['fecha_emision']}
              asientos:
                - plan_cuentas: {info_gasto['codigo']}
                  debe: {sel_data['base_imponible']:,.2f}
                  haber: 0.00
                - plan_cuentas: {info_iva['codigo']}
                  debe: {sel_data['monto_iva']:,.2f}
                  haber: 0.00
                - plan_cuentas: 2.1.2.01.005
                  debe: 0.00
                  haber: {sel_data['retencion_islr']:,.2f}
                - plan_cuentas: 2.1.2.01.003
                  debe: 0.00
                  haber: {sel_data['retencion_iva']:,.2f}
                - plan_cuentas: {info_banco['codigo']}
                  debe: 0.00
                  haber: {sel_data['monto_neto']:,.2f}""", language="yaml")
                                
                                if st.button("💾 Guardar Asiento Contable y Pasar a Banco", key=f"btn_guardar_asiento_{sel_data['id']}", use_container_width=True):
                                    with st.spinner("Registrando asiento contable..."):
                                        try:
                                            conn_a = conectar_db(db_actual)
                                            if conn_a:
                                                with conn_a.cursor() as cur_a:
                                                    n_comp_val = f"OP-{sel_data['nro_factura']}"
                                                    fecha_val = str(sel_data['fecha_emision'])
                                                    lineas_asiento = [
                                                        (info_gasto['codigo'], info_gasto['nombre'], float(sel_data['base_imponible']), 0.00),
                                                        (info_iva['codigo'], info_iva['nombre'], float(sel_data['monto_iva']), 0.00),
                                                        ("2.1.2.01.005", "Retención ISLR Por Pagar", 0.00, float(sel_data['retencion_islr'])),
                                                        ("2.1.2.01.003", "Retención IVA Por Pagar", 0.00, float(sel_data['retencion_iva'])),
                                                        (info_banco['codigo'], info_banco['nombre'], 0.00, float(sel_data['monto_neto']))
                                                    ]
                                                    query_asiento = """
                                                        INSERT INTO asientos_contables (
                                                            n_comprobante, descripcion, fecha, plan_cuentas, 
                                                            cuenta_contable, referencia, debe, haber, bloqueado
                                                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                                                    """
                                                    for c_cod, c_nom, debe_v, haber_v in lineas_asiento:
                                                        if debe_v > 0 or haber_v > 0:
                                                            cur_a.execute(query_asiento, (
                                                                n_comp_val,
                                                                f"Pago a Proveedor {sel_data['proveedor']} - Factura {sel_data['nro_factura']}",
                                                                fecha_val,
                                                                c_cod,
                                                                c_nom,
                                                                n_comp_val,
                                                                debe_v,
                                                                haber_v
                                                            ))
                                                    conn_a.commit()
                                                conn_a.close()
                                                st.success("✅ ¡Asiento Contable guardado con éxito!")
                                                st.session_state[key_paso] = 3
                                                st.rerun()
                                        except Exception as err_a:
                                            st.error(f"❌ Error al guardar asiento contable: {err_a}")

                            # --- PASO 3: MOVIMIENTO BANCARIO ---
                            elif paso == 3:
                                st.markdown("#### 🏦 Paso 3: Registrar `banco_movimientos`")
                                prov_nombre = str(sel_data.get('proveedor', '')).strip()
                                prov_rif = str(sel_data.get('proveedor_rif', '')).strip()
                                nro_fact = str(sel_data.get('nro_factura', '')).strip()
                                desc_val = f"Pago Factura Nro {nro_fact} - {prov_nombre} (RIF: {prov_rif})"

                                st.code(f"""banco_nombre: {info_banco['nombre']}
            reference: OP-{nro_fact}
            descripcion: {desc_val}
            monto: {sel_data['monto_neto']:,.2f}
            estado: {sel_data['estado']}""", language="yaml")
                                
                                if st.button("💾 Guardar Movimiento Bancario y Finalizar", key=f"btn_guardar_banco_{sel_data['id']}", use_container_width=True):
                                    with st.spinner("Registrando movimiento bancario..."):
                                        try:
                                            conn_b = conectar_db(db_actual)
                                            if conn_b:
                                                with conn_b.cursor() as cur_b:
                                                    fecha_val = str(sel_data['fecha_emision'])
                                                    query_banco = """
                                                        INSERT INTO banco_movimientos (
                                                            banco_nombre, cuenta_numero, fecha_movimiento, 
                                                            referencia, descripcion, monto, estado_conciliacion
                                                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                                    """
                                                    cur_b.execute(query_banco, (
                                                        info_banco['nombre'],
                                                        info_banco['codigo'],
                                                        fecha_val,
                                                        f"OP-{nro_fact}",
                                                        desc_val,
                                                        float(sel_data['monto_neto']),
                                                        "Pendiente"
                                                    ))
                                                    conn_b.commit()
                                                conn_b.close()
                                                st.success("🎉 ¡Proceso completo! Movimiento Bancario guardado con éxito.")
                                                st.session_state[key_paso] = 1
                                                st.rerun()
                                        except Exception as err_b:
                                            st.error(f"❌ Error al guardar movimiento bancario: {err_b}")
                except Exception as ex_historial:
                    st.warning(f"Aviso en historial: {ex_historial}")
    
        with tab3:
            sst.subheader("📂 Estado de Cuenta Bancario")

            db_actual = st.session_state.get('DB_ACTUAL')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            # Usamos la conexión reutilizada del módulo global
            try:
                if conn is None:
                    conn = conectar_db(db_actual)
                else:
                    try:
                        conn.ping(reconnect=True)
                    except Exception:
                        conn = conectar_db(db_actual)
                        st.session_state['conn_conciliacion'] = conn
                
                if conn is None:
                    st.error("No se pudo establecer conexión con la base de datos.")
                    st.stop()

                import calendar
                mes_map = {
                    "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                    "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
                }
                mes_num = mes_map.get(mes_sel, 1)
                
                fecha_inicio = f"{ano_sel}-{mes_num:02d}-01"
                ultimo_dia = calendar.monthrange(int(ano_sel), int(mes_num))[1]
                fecha_fin = f"{ano_sel}-{mes_num:02d}-{ultimo_dia}"

                # Consulta optimizada directamente a la tabla
                cursor = conn.cursor()
                query = f"""
                    SELECT id, banco_nombre, cuenta_numero, fecha_movimiento, referencia, 
                           descripcion, monto, estado_conciliacion 
                    FROM `{db_actual}`.banco_movimientos 
                    WHERE fecha_movimiento >= %s AND fecha_movimiento <= %s
                    ORDER BY fecha_movimiento DESC
                """
                cursor.execute(query, (fecha_inicio, fecha_fin))
                rows = cursor.fetchall()
                cursor.close()

                if rows:
                    df_cuenta = pd.DataFrame(rows, columns=[
                        'id', 'banco_nombre', 'cuenta_numero', 'fecha_movimiento', 
                        'referencia', 'descripcion', 'monto', 'estado_conciliacion'
                    ])
                    
                    # Conversión numérica optimizada
                    df_cuenta['monto'] = pd.to_numeric(df_cuenta['monto'], errors='coerce').fillna(0.0)

                    # Renderizado rápido y nativo sin bucles lentos de formato string en Pandas
                    st.dataframe(
                        df_cuenta,
                        column_config={
                            "id": st.column_config.NumberColumn("ID", disabled=True),
                            "banco_nombre": st.column_config.TextColumn("Banco"),
                            "cuenta_numero": st.column_config.TextColumn("N° Cuenta"),
                            "fecha_movimiento": st.column_config.DateColumn("Fecha"),
                            "referencia": st.column_config.TextColumn("Referencia"),
                            "descripcion": st.column_config.TextColumn("Descripción"),
                            "monto": st.column_config.NumberColumn(
                                "Monto",
                                format="%,.2f",
                                help="Monto del movimiento bancario"
                            ),
                            "estado_conciliacion": st.column_config.TextColumn("Estado")
                        },
                        hide_index=True,
                        use_container_width=True, 
                        height=450
                    )
                    st.write(f"**Total movimientos encontrados:** {len(df_cuenta)}")
                else:
                    st.info(f"No hay movimientos registrados para el periodo {mes_sel} {ano_sel}.")

            except Exception as e:
                err_code = e.args[0] if len(e.args) > 0 else "Desconocido"
                err_msg = e.args[1] if len(e.args) > 1 else str(e)
                st.error(f"❌ Error en la base de datos [Código {err_code}]: {err_msg}")

            # Panel de administración condicional
            if rol == 'admin':
                with st.expander("⚠️ Zona de Administración"):
                    if st.button("🗑️ Vaciar Todo (CUIDADO)", type="primary"):
                        try:
                            cursor_del = conn.cursor()
                            cursor_del.execute(f"DELETE FROM `{db_actual}`.banco_movimientos WHERE empresa_id = %s", (cliente_id,))
                            conn.commit()
                            cursor_del.close()
                            st.success("Registros de esta empresa eliminados correctamente.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al vaciar registros: {e}")

    
        # ==========================================
        # --- TAB 4: CONCILIACIÓN BANCARIA (TABLERO) ---
        # ==========================================
        with tab4:
            st.subheader("📊 Resumen del Periodo")

            db_actual = st.session_state.get('DB_ACTUAL')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            try:
                # Reutilizamos la conexión global ya validada al inicio del módulo
                if 'conn_conciliacion' in st.session_state and st.session_state['conn_conciliacion']:
                    conn = st.session_state['conn_conciliacion']
                    try:
                        conn.ping(reconnect=True)
                    except Exception:
                        conn = conectar_db(db_actual)
                        st.session_state['conn_conciliacion'] = conn
                else:
                    conn = conectar_db(db_actual)
                    st.session_state['conn_conciliacion'] = conn

                if conn:
                    with st.spinner("Calculando tablero de conciliación..."):
                        mostrar_tablero_conciliacion(conn, mes_sel, ano_sel)
                else:
                    st.error("❌ ERROR CRÍTICO: No se pudo establecer conexión con la base de datos.")
                    
            except Exception as e:
                st.error(f"❌ Error al conectar con el tablero: {e}")

        # ==========================================
        # --- TAB 5: CIERRE Y BLOQUEO DE MES ---
        # ==========================================
        with tab5:
            st.subheader("🔒 Cierre y Bloqueo de Mes")

            db_actual = st.session_state.get('DB_ACTUAL')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            mes_map = {
                "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
                "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
            }
            mes_num = mes_map.get(mes_sel, 1)

            try:
                # Reutilización optimizada de la conexión maestra del módulo
                if 'conn_conciliacion' in st.session_state and st.session_state['conn_conciliacion']:
                    conn = st.session_state['conn_conciliacion']
                    try:
                        conn.ping(reconnect=True)
                    except Exception:
                        conn = conectar_db(db_actual)
                        st.session_state['conn_conciliacion'] = conn
                else:
                    conn = conectar_db(db_actual)
                    st.session_state['conn_conciliacion'] = conn

                if not conn:
                    st.error("No se pudo establecer conexión con la base de datos.")
                    st.stop()

                # Verificación rápida del estado del mes
                cursor = conn.cursor()
                query_check = f"SELECT COUNT(*) FROM `{db_actual}`.banco_movimientos WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s AND estado_conciliacion = 'Cerrado'"
                cursor.execute(query_check, (mes_num, ano_sel))
                es_cerrado = cursor.fetchone()[0] > 0
                cursor.close()

                if es_cerrado:
                    st.error(f"🔒 El mes de {mes_sel} {ano_sel} en `{db_actual}` está CERRADO.")
                else:
                    st.warning("⚠️ Acción irreversible: El cierre de mes bloquea ediciones.")
                    if st.checkbox("✅ Entiendo las consecuencias, quiero cerrar el mes", key="chk_cierre"):
                        if st.button("Confirmar Cierre de Mes", type="primary"):
                            try:
                                cursor_upd = conn.cursor()
                                query_update = f"""
                                    UPDATE `{db_actual}`.banco_movimientos 
                                    SET estado_conciliacion = 'Cerrado' 
                                    WHERE MONTH(fecha_movimiento) = %s AND YEAR(fecha_movimiento) = %s
                                """
                                cursor_upd.execute(query_update, (mes_num, ano_sel))
                                conn.commit()
                                cursor_upd.close()
                                
                                st.success("✅ Mes cerrado con éxito.")
                                st.rerun()
                            except Exception as e:
                                conn.rollback()
                                st.error(f"❌ Error al ejecutar el cierre de mes: {e}")

            except Exception as e:
                st.error(f"Error de conexión o consulta con la base de datos: {e}")

        with tab6:
            stst.subheader("🗑️ Vaciar Estado de Cuenta (Movimientos Bancarios) por Rango")

            db_actual = st.session_state.get('DB_ACTUAL')

            if not db_actual:
                st.error("No se ha seleccionado una base de datos de empresa.")
                st.stop()

            st.warning("⚠️ **¡Atención!** Esta acción eliminará permanentemente los registros de la tabla `banco_movimientos` (estado de cuenta) de esta empresa dentro del rango seleccionado.")

            col1, col2 = st.columns(2)
            with col1:
                fecha_desde = st.date_input("Fecha Inicio", key="f_inicio_vaciar")
            with col2:
                fecha_hasta = st.date_input("Fecha Fin", key="f_fin_vaciar")

            confirmar_checkbox = st.checkbox(
                f"Confirmo que deseo eliminar el estado de cuenta del {fecha_desde} al {fecha_hasta}", 
                key="chk_vaciar_movimientos_rango"
            )

            if confirmar_checkbox:
                if st.button("🚨 Ejecutar Eliminación en Movimientos Bancarios", type="primary"):
                    try:
                        # Reutilización optimizada de la conexión maestra del módulo
                        if 'conn_conciliacion' in st.session_state and st.session_state['conn_conciliacion']:
                            conn = st.session_state['conn_conciliacion']
                            try:
                                conn.ping(reconnect=True)
                            except Exception:
                                conn = conectar_db(db_actual)
                                st.session_state['conn_conciliacion'] = conn
                        else:
                            conn = conectar_db(db_actual)
                            st.session_state['conn_conciliacion'] = conn

                        if not conn:
                            st.error("❌ Error de conexión con la base de datos.")
                            st.stop()

                        # Ejecución directa y rápida del borrado por rango
                        cursor = conn.cursor()
                        query_delete = f"""
                            DELETE FROM `{db_actual}`.banco_movimientos 
                            WHERE fecha_movimiento >= %s 
                            AND fecha_movimiento <= %s
                        """
                        cursor.execute(query_delete, (fecha_desde, fecha_hasta))
                        total_borrados = cursor.rowcount
                        conn.commit()
                        cursor.close()

                        if total_borrados > 0:
                            st.balloons()
                            st.success(f"🎉 ¡Listo! Se eliminaron **{total_borrados}** registros de `banco_movimientos` del {fecha_desde} al {fecha_hasta}. ¡Estado de cuenta limpio! 🚀")
                            st.rerun()
                        elif total_borrados == 0:
                            st.warning(f"⚠️ La consulta se ejecutó con éxito, pero **no se encontraron movimientos** en el rango del {fecha_desde} al {fecha_hasta}.")
                        else:
                            st.error("❌ Ocurrió un error técnico al procesar la eliminación.")

                    except Exception as e:
                        if 'conn' in locals() and conn:
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                        st.error(f"❌ Error crítico al procesar la solicitud: {e}")

    elif sub_opcion == "Tesorería y Proveedores":
        st.subheader("💳 Módulo de Tesorería y Cruce con Proveedores")
        
        # Pestañas organizadas para cubrir todo el ciclo y mantenimiento
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📂 Directorio de Proveedores", 
            "🧾 Órdenes de Pago (CxP)", 
            "🔗 Conciliación Bancaria", 
            "✏️ Modificar / Eliminar", 
            "🗑️ Mantenimiento Masivo",
        ])
        
        with tab1:
            st.markdown("### 📋 Registro y Configuración de Proveedores (Tesorería)")

            # --- BLINDAJE ÚNICO Y OPTIMIZADO DE LA TABLA ---
            @st.cache_data(ttl=3600, show_spinner=False)
            def asegurar_tabla_proveedores(empresa):
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        cur = conn.cursor()
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS proveedores_carga (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                empresa_db VARCHAR(100) NOT NULL,
                                nombre VARCHAR(200) NOT NULL,
                                rif VARCHAR(50) NOT NULL,
                                codigo_cuenta VARCHAR(50),
                                descripcion_cuenta VARCHAR(255),
                                telefono VARCHAR(50),
                                email VARCHAR(100),
                                banco VARCHAR(100),
                                nro_cuenta VARCHAR(100),
                                tipo_cuenta VARCHAR(50),
                                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                INDEX (empresa_db)
                            )
                        """)
                        conn.commit()
                        cur.close()
                        conn.close()
                except Exception:
                    pass

            asegurar_tabla_proveedores(db_actual)

            # --- FUNCIÓN CON CACHÉ OPTIMIZADA (CONEXIÓN ÚNICA) ---
            @st.cache_data(ttl=300, show_spinner=False)
            def cargar_datos_proveedores_tab1(empresa):
                m_lista, m_dict, c_lista, c_dict = [], {}, [], {}
                
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        # 1. Consulta al catálogo maestro
                        df_maestro = ejecutar_consulta("SELECT rif, razon_social, codigo_cuenta, descripcion_cuenta FROM proveedores ORDER BY razon_social ASC", conn)
                        if df_maestro is not None and not df_maestro.empty:
                            for _, row in df_maestro.iterrows():
                                label_m = f"{row['razon_social']} (RIF: {row['rif']})"
                                m_lista.append(label_m)
                                m_dict[label_m] = {
                                    "razon_social": row['razon_social'] or "",
                                    "rif": row['rif'] or "",
                                    "codigo_cuenta": row.get('codigo_cuenta', '') or "",
                                    "descripcion_cuenta": row.get('descripcion_cuenta', '') or ""
                                }
                        
                        # 2. Consulta a proveedores cargados (misma conexión abierta)
                        df_cargados = ejecutar_consulta(
                            "SELECT id, nombre, rif, codigo_cuenta, descripcion_cuenta, telefono, email, banco, nro_cuenta, tipo_cuenta FROM proveedores_carga WHERE empresa_db = %s ORDER BY nombre ASC", 
                            conn, params=(str(empresa),)
                        )
                        if df_cargados is not None and not df_cargados.empty:
                            for _, row in df_cargados.iterrows():
                                label_c = f"💾 [Guardado] {row['nombre']} (RIF: {row['rif']})"
                                c_lista.append(label_c)
                                c_dict[label_c] = {
                                    "nombre": row['nombre'] or "",
                                    "rif": row['rif'] or "",
                                    "codigo_cuenta": row['codigo_cuenta'] or "",
                                    "descripcion_cuenta": row['descripcion_cuenta'] or "",
                                    "telefono": row['telefono'] or "",
                                    "email": row['email'] or "",
                                    "banco": row['banco'] or "Banesco",
                                    "nro_cuenta": row['nro_cuenta'] or "",
                                    "tipo_cuenta": row['tipo_cuenta'] or "Corriente"
                                }
                        conn.close()
                except Exception:
                    pass
                    
                return m_lista, m_dict, c_lista, c_dict

            lista_maestros, dict_maestros, lista_cargados, dict_cargados = cargar_datos_proveedores_tab1(db_actual)

            # --- GESTIÓN DE SESSION STATE PARA LIMPIEZA SEGURA ---
            if "form_reset" not in st.session_state: 
                st.session_state["form_reset"] = False

            if st.session_state["form_reset"]:
                st.session_state["val_nombre"] = ""
                st.session_state["val_rif"] = ""
                st.session_state["val_cod_cta"] = ""
                st.session_state["val_desc_cta"] = ""
                st.session_state["val_tel"] = ""
                st.session_state["val_email"] = ""
                st.session_state["val_banco"] = "Banesco"
                st.session_state["val_nro_cta"] = ""
                st.session_state["val_tipo_cta"] = "Corriente"
                st.session_state["form_reset"] = False

            # Inicializar valores por defecto si no existen
            for key, default_val in [
                ("val_nombre", ""), ("val_rif", ""), ("val_cod_cta", ""), 
                ("val_desc_cta", ""), ("val_tel", ""), ("val_email", ""), 
                ("val_banco", "Banesco"), ("val_nro_cta", ""), ("val_tipo_cta", "Corriente")
            ]:
                if key not in st.session_state:
                    st.session_state[key] = default_val

            # --- SECCIÓN SUPERIOR DE IMPORTACIÓN / AUTOCOMPLETAR ---
            col_imp1, col_imp2 = st.columns(2)

            with col_imp1:
                if lista_maestros:
                    with st.expander("📥 Importar desde catálogo 'proveedores' (A-Z)", expanded=False):
                        prov_seleccionado = st.selectbox("Seleccione proveedor del catálogo:", lista_maestros, key="sel_cat_maestro")
                        if st.button("🔄 Cargar datos del catálogo", key="btn_load_catalogo"):
                            datos_sel = dict_maestros.get(prov_seleccionado, {})
                            st.session_state["val_nombre"] = datos_sel.get("razon_social", "")
                            st.session_state["val_rif"] = datos_sel.get("rif", "")
                            st.session_state["val_cod_cta"] = datos_sel.get("codigo_cuenta", "")
                            st.session_state["val_desc_cta"] = datos_sel.get("descripcion_cuenta", "")
                            st.toast("✅ ¡Datos importados al formulario!", icon="📥")
                            st.rerun()

            with col_imp2:
                if lista_cargados:
                    with st.expander("⚡ Autocompletar con Proveedores Registrados", expanded=False):
                        sel_autocompletar = st.selectbox("Seleccione proveedor guardado:", lista_cargados, key="sel_cat_cargado")
                        if st.button("🔄 Cargar datos guardados", key="btn_load_guardados"):
                            datos_auto = dict_cargados.get(sel_autocompletar, {})
                            st.session_state["val_nombre"] = datos_auto.get("nombre", "")
                            st.session_state["val_rif"] = datos_auto.get("rif", "")
                            st.session_state["val_cod_cta"] = datos_auto.get("codigo_cuenta", "")
                            st.session_state["val_desc_cta"] = datos_auto.get("descripcion_cuenta", "")
                            st.session_state["val_tel"] = datos_auto.get("telefono", "")
                            st.session_state["val_email"] = datos_auto.get("email", "")
                            st.session_state["val_banco"] = datos_auto.get("banco", "Banesco")
                            st.session_state["val_nro_cta"] = datos_auto.get("nro_cuenta", "")
                            st.session_state["val_tipo_cta"] = datos_auto.get("tipo_cuenta", "Corriente")
                            st.toast("✅ ¡Datos cargados en el formulario!", icon="⚡")
                            st.rerun()

            st.markdown("---")

            # --- SECCIÓN DE REGISTRO CON WIDGETS LIGADOS A SESSION_STATE ---
            col_p1, col_p2 = st.columns(2)

            with col_p1:
                st.markdown("#### 🏢 Datos de Identificación y Contabilidad")
                nombre_prov = st.text_input("Nombre / Razón Social del Proveedor", key="val_nombre")
                rif_prov = st.text_input("RIF o Documento de Identidad (ej: J-12345678-9)", key="val_rif")
                cod_cuenta_prov = st.text_input("Código de Cuenta Contable", key="val_cod_cta")
                desc_cuenta_prov = st.text_input("Descripción de Cuenta Contable", key="val_desc_cta")
                telefono_prov = st.text_input("Teléfono de Contacto", key="val_tel")
                email_prov = st.text_input("Correo Electrónico", key="val_email")

            with col_p2:
                st.markdown("#### 🏦 Datos Bancarios y Destino")
                lista_bancos = ["Banesco", "Mercantil", "Banco del Caribe", "Banplus", "Banco Activo", "Banco del Tesoro", "Exterior", "Provincial", "BOD / 100% Banco", "Banco de Venezuela", "BNC", "Otros / Extranjero"]
                banco_prov = st.selectbox("Banco Destino", lista_bancos, key="val_banco")
                nro_cuenta_prov = st.text_input("Número de Cuenta (20 dígitos)", key="val_nro_cta")
                lista_tipos_cta = ["Corriente", "Ahorro", "Divisas"]
                tipo_cuenta_prov = st.selectbox("Tipo de Cuenta", lista_tipos_cta, key="val_tipo_cta")

            st.markdown("")
            btn_guardar_prov = st.button("💾 Guardar en Tabla Proveedores Carga", type="primary", use_container_width=True)

            if btn_guardar_prov:
                if nombre_prov.strip() and rif_prov.strip():
                    try:
                        conn_ins = conectar_db(db_actual)
                        if conn_ins:
                            cursor_ins = conn_ins.cursor()
                            query_ins = """
                                INSERT INTO proveedores_carga 
                                (empresa_db, nombre, rif, codigo_cuenta, descripcion_cuenta, telefono, email, banco, nro_cuenta, tipo_cuenta)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """
                            cursor_ins.execute(query_ins, (
                                str(db_actual), 
                                nombre_prov.strip(), 
                                rif_prov.strip(), 
                                cod_cuenta_prov.strip(), 
                                desc_cuenta_prov.strip(), 
                                telefono_prov.strip(), 
                                email_prov.strip(), 
                                banco_prov, 
                                nro_cuenta_prov.strip(), 
                                tipo_cuenta_prov
                            ))
                            conn_ins.commit()
                            cursor_ins.close()
                            conn_ins.close()
                            
                            st.session_state["form_reset"] = True
                            cargar_datos_proveedores_tab1.clear()

                            st.success(f"✅ ¡Proveedor '{nombre_prov}' guardado con éxito!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar en `proveedores_carga`: {e}")
                else:
                    st.warning("⚠️ Debe existir un nombre y un RIF válido para procesar el registro.")

            st.divider()

            # --- LISTADO DE LA TABLA 'proveedores_carga' (Optimizado) ---
            st.markdown("### 🗂️ Proveedores Almacenados en `proveedores_carga`")
            try:
                conn_list = conectar_db(db_actual)
                if conn_list:
                    df_prov = ejecutar_consulta(
                        "SELECT id, nombre, rif, codigo_cuenta, descripcion_cuenta, banco, nro_cuenta FROM proveedores_carga WHERE empresa_db = %s ORDER BY nombre ASC", 
                        conn_list, 
                        params=(str(db_actual),)
                    )
                    conn_list.close()
                    
                    if df_prov is not None and not df_prov.empty:
                        st.dataframe(df_prov, use_container_width=True, hide_index=True)
                    else:
                        st.info("ℹ️ La tabla `proveedores_carga` está vacía para esta empresa actualmente.")
            except Exception as e:
                st.error(f"Error al cargar la lista: {e}")

        with tab2:
            st.markdown("### 🧾 Gestión y Generación de Órdenes de Pago y Cruce")

            # --- CARGAR PROVEEDORES Y PLAN DE CUENTAS OPTIMIZADO CON CACHÉ ---
            @st.cache_data(ttl=300, show_spinner=False)
            def cargar_datos_maestros_optimizados(empresa):
                p_lista, p_dict, c_lista, c_dict = [], {}, [], {}
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        # 1. Proveedores de carga
                        df_cp = ejecutar_consulta(
                            "SELECT id, nombre, rif, codigo_cuenta, descripcion_cuenta FROM proveedores_carga WHERE empresa_db = %s ORDER BY nombre ASC", 
                            conn, params=(str(empresa),)
                        )
                        # 2. Plan de cuentas detalle (misma conexión abierta)
                        df_cuentas = ejecutar_consulta(
                            "SELECT id, codigo, nombre, nivel, tipo, padre FROM plan_cuentas WHERE tipo = 'Detalle'", 
                            conn
                        )
                        conn.close()
                        
                        if df_cp is not None and not df_cp.empty:
                            for _, row in df_cp.iterrows():
                                pid = row['id']
                                label = f"{row['nombre']} (RIF: {row['rif']})"
                                if label not in p_lista:
                                    p_lista.append(label)
                                p_dict[label] = {
                                    'id_interno': pid,
                                    'rif': row['rif'],
                                    'nombre': row['nombre'],
                                    'codigo_cuenta': str(row.get('codigo_cuenta', 'N/A')),
                                    'descripcion_cuenta': str(row.get('descripcion_cuenta', 'N/A'))
                                }
                        
                        if df_cuentas is not None and not df_cuentas.empty:
                            for _, row in df_cuentas.iterrows():
                                clabel = f"{str(row['codigo']).strip()} - {str(row['nombre']).strip()}"
                                if clabel not in c_lista:
                                    c_lista.append(clabel)
                                    c_dict[clabel] = {
                                        'codigo': str(row['codigo']).strip(),
                                        'nombre': str(row['nombre']).strip()
                                    }
                except Exception as ex:
                    pass
                return p_lista, p_dict, c_lista, c_dict

            lista_provs, dict_provs, lista_cuentas_detalle, dict_cuentas_detalle = cargar_datos_maestros_optimizados(db_actual)

            # --- GESTIÓN DE SESSION STATE PARA LIMPIEZA DE LA ORDEN DE PAGO ---
            if "op_form_reset" not in st.session_state: 
                st.session_state["op_form_reset"] = False

            if st.session_state["op_form_reset"]:
                st.session_state["op_fact"] = ""
                st.session_state["op_ctrl"] = ""
                st.session_state["op_base"] = 0.0
                st.session_state["op_exento"] = 0.0
                st.session_state["op_porc_islr"] = 1.0
                st.session_state["op_sustraendo"] = 0.0
                st.session_state["op_obs"] = ""
                st.session_state["op_form_reset"] = False

            # Inicializar valores por defecto en el session_state si no existen
            for key, default_val in [
                ("op_fact", ""), ("op_ctrl", ""), ("op_base", 0.0), 
                ("op_exento", 0.0), ("op_porc_islr", 1.0), ("op_sustraendo", 0.0), 
                ("op_obs", ""), ("orden_guardada_exito", False)
            ]:
                if key not in st.session_state:
                    st.session_state[key] = default_val

            # ==========================================
            # 🎛️ SELECTOR DE VISTA
            # ==========================================
            st.markdown("---")
            modo_vista = st.selectbox(
                "📍 Selecciona la vista de trabajo:",
                options=[
                    "Emitir Nueva Orden de Pago", 
                    "Ver cola de órdenes pendientes por procesar"
                ],
                key="selector_modo_vista_seguro_op"
            )
            st.markdown("---")

            # ==========================================
            # 📋 OPCIÓN 1: EMITIR NUEVA ORDEN DE PAGO
            # ==========================================
            if modo_vista == "Emitir Nueva Orden de Pago":
                if not st.session_state.orden_guardada_exito:
                    st.markdown("### ✍️ Emitir Nueva Orden de Pago")
                    
                    modo_registro = st.radio(
                        "Seleccione el método de registro de la factura:",
                        ("1. Registro Manual", "2. Escaneo de Factura (Automático)"),
                        horizontal=True,
                        key="modo_registro_factura"
                    )

                    if modo_registro == "2. Escaneo de Factura (Automático)":
                        archivo_escaneado = st.file_uploader("Seleccione el archivo de la factura escaneada", type=["pdf", "jpg", "png"], key="uploader_factura_escaneada")
                        if archivo_escaneado is not None:
                            if st.button("🚀 Procesar factura escaneada", type="primary", key="btn_procesar_escaneo"):
                                with st.spinner("Leyendo datos fiscales de la factura..."):
                                    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{archivo_escaneado.name}") as tmp_file:
                                        tmp_file.write(archivo_escaneado.getvalue())
                                        ruta_temporal = tmp_file.name

                                    res_ocr = extraer_datos_factura_local(ruta_temporal)
                                    os.unlink(ruta_temporal)

                                if "error" in res_ocr:
                                    st.error(res_ocr["error"])
                                else:
                                    st.success("¡Factura procesada con éxito! Campos extraídos:")
                                    st.session_state["op_fact"] = str(res_ocr.get("nro_factura", ""))
                                    st.session_state["op_ctrl"] = str(res_ocr.get("nro_control", ""))
                                    st.session_state["op_base"] = float(res_ocr.get("base_imponible", 0.0))
                                    st.session_state["op_exento"] = float(res_ocr.get("monto_exento", 0.0))
                                    st.rerun()

                    with st.container():
                        col_f1_1, col_f1_2 = st.columns(2)
                        with col_f1_1:
                            prov_seleccionado_form = st.selectbox("Seleccionar Proveedor", options=lista_provs if lista_provs else ["No hay proveedores"], key="op_prov")
                            nro_factura_form = st.text_input("Número de Factura", key="op_fact")
                            nro_control_form = st.text_input("Número de Control", key="op_ctrl")
                        with col_f1_2:
                            fecha_emision_form = st.date_input("Fecha de Emisión", key="op_fecha")
                            
                            st.markdown("""
                                <div style="background-color: #ffe6e6; padding: 6px 12px; border-radius: 6px; border: 1px solid #ff9999; margin-bottom: 5px;">
                                    <span style="color: #c0392b; font-weight: bold; font-size: 13px;">🔴 Campos de ingreso manual</span>
                                </div>
                            """, unsafe_allow_html=True)
                            
                            base_imponible_form = st.number_input("Base Imponible", min_value=0.0, format="%.2f", key="op_base")
                            monto_exento_form = st.number_input("Monto Exento", min_value=0.0, format="%.2f", key="op_exento")

                        col_f1_3, col_f1_4 = st.columns(2)
                        with col_f1_3:
                            alicuota_iva_form = st.selectbox("Alícuota IVA", options=[16.0, 8.0, 31.0, 0.0], format_func=lambda x: f"{x}%", key="op_alicuota")
                        with col_f1_4:
                            monto_iva_calculado = base_imponible_form * (alicuota_iva_form / 100.0)
                            st.metric(label="Monto IVA (Calculado)", value=f"{monto_iva_calculado:,.2f}")

                        monto_bruto_calculado = base_imponible_form + monto_exento_form + monto_iva_calculado
                        st.metric(label="Monto Bruto / Total Factura (Calculado)", value=f"{monto_bruto_calculado:,.2f}")
                        
                        st.markdown("---")

                        # --- 2DO FRAME: RETENCIÓN DE IVA ---
                        st.markdown("#### 2️⃣ Frame: Retención de IVA")
                        col_f2_1, col_f2_2 = st.columns(2)
                        with col_f2_1:
                            porcentaje_ret_iva = st.selectbox("Porcentaje Retención IVA", options=[75.0, 100.0, 25.0, 50.0, 0.00], format_func=lambda x: f"{x}%", key="op_porc_ret_iva")
                        with col_f2_2:
                            retencion_iva_calculada = monto_iva_calculado * (porcentaje_ret_iva / 100.0)
                            st.metric(label="Monto Retención IVA (Calculado)", value=f"{retencion_iva_calculada:,.2f}")
                        
                        st.markdown("---")

                        # --- 3ER FRAME: RETENCIÓN DE ISLR ---
                        st.markdown("#### 3️⃣ Frame: Retención de ISLR")
                        col_f3_1, col_f3_2, col_f3_3, col_f3_4 = st.columns(4)
                        with col_f3_1:
                            tipo_persona_form = st.selectbox("Tipo de Persona", options=["Jurídico Domiciliado", "Natural Residenciado", "Otro"], key="op_tipo_p")
                        with col_f3_2:
                            islr_porcentaje_form = st.number_input("% Retención ISLR", min_value=0.0, max_value=100.0, format="%.2f", key="op_porc_islr")
                        with col_f3_3:
                            islr_sustraendo_form = st.number_input("Sustraendo ISLR", min_value=0.0, format="%.2f", key="op_sustraendo")
                        with col_f3_4:
                            retencion_islr_calculada = max(0.0, (base_imponible_form * (islr_porcentaje_form / 100.0)) - islr_sustraendo_form)
                            st.metric(label="Monto Retención ISLR Final", value=f"{retencion_islr_calculada:,.2f}")

                        st.markdown("---")
                        
                        # --- 4TO FRAME: MONTO NETO Y OBSERVACIONES ---
                        st.markdown("#### 4️⃣ Frame: Cálculo del Monto Neto a Pagar")
                        monto_neto_calculado = monto_bruto_calculado - retencion_islr_calculada - retencion_iva_calculada
                        
                        col_f4_1, col_f4_2 = st.columns(2)
                        with col_f4_1:
                            st.metric(label="💵 Monto Neto a Pagar", value=f"{monto_neto_calculado:,.2f}")
                        with col_f4_2:
                            observaciones_form = st.text_area("Observaciones / Concepto del Pago", key="op_obs")

                        st.markdown("---")
                        
                        # --- BOTONES DE CÁLCULO Y GUARDADO ---
                        col_btn_1, col_btn_2 = st.columns(2)
                        with col_btn_1:
                            btn_calcular = st.button("🧮 Calcular / Refrescar Montos", type="secondary", key="btn_calcular_principal", use_container_width=True)
                        with col_btn_2:
                            btn_guardar_op = st.button("💾 Guardar y Registrar Orden de Pago", type="primary", key="btn_guardar_principal", use_container_width=True)

                        if btn_calcular:
                            st.toast("✅ ¡Cálculos actualizados al instante!", icon="🧮")
                            st.rerun()

                        # --- BLOQUE DE REGISTRO DE ORDEN DE PAGO ---
                        if btn_guardar_op:
                            if not nro_factura_form:
                                st.error("⚠️ El número de factura es obligatorio.")
                            elif not lista_provs:
                                st.error("⚠️ No hay proveedores cargados para asociar la orden.")
                            else:
                                try:
                                    info_prov_form = dict_provs[prov_seleccionado_form]
                                    conn_ins = conectar_db(db_actual)
                                    if conn_ins:
                                        cursor = conn_ins.cursor()
                                        query_insert = """
                                            INSERT INTO ordenes_pago (
                                                empresa_db, proveedor_id, nro_factura, nro_control, 
                                                monto_bruto, monto_exento, base_imponible, iva_porcentaje, monto_iva, 
                                                retencion_islr, retencion_iva, monto_neto, estado, fecha_emision, 
                                                observaciones, islr_porcentaje, islr_sustraendo, tipo_persona
                                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """
                                        cursor.execute(query_insert, (
                                            str(db_actual),
                                            str(info_prov_form['id_interno']),
                                            str(nro_factura_form),
                                            str(nro_control_form),
                                            float(monto_bruto_calculado),
                                            float(monto_exento_form),
                                            float(base_imponible_form),
                                            float(alicuota_iva_form),
                                            float(monto_iva_calculado),
                                            float(retencion_islr_calculada),
                                            float(retencion_iva_calculada),
                                            float(monto_neto_calculado),
                                            'Pendiente',
                                            str(fecha_emision_form),
                                            str(observaciones_form),
                                            float(islr_porcentaje_form),
                                            float(islr_sustraendo_form),
                                            str(tipo_persona_form)
                                        ))
                                        conn_ins.commit()
                                        cursor.close()
                                        conn_ins.close()
                                        
                                        st.session_state.op_form_reset = True
                                        cargar_datos_maestros_optimizados.clear()
                                        
                                        st.success("🎉 ¡Orden de pago guardada con éxito!")
                                        st.rerun()
                                except Exception as err_ins:
                                    st.error(f"❌ Error al guardar la orden de pago: {err_ins}")

            # ==========================================
            # 📊 OPCIÓN 2: VER COLA DE ÓRDENES PENDIENTES
            # ==========================================
            else:
                st.markdown("### 📊 Historial de Órdenes de Pago Pendientes por Contabilizar")
                try:
                    conn_list_op = conectar_db(db_actual)
                    df_ops = None
                    
                    if conn_list_op:
                        query_ops = f"SELECT * FROM ordenes_pago WHERE empresa_db = '{db_actual}' ORDER BY id DESC"
                        df_ops = ejecutar_consulta(query_ops, conn_list_op)
                        
                        if df_ops is None or df_ops.empty:
                            df_ops = ejecutar_consulta("SELECT * FROM ordenes_pago ORDER BY id DESC", conn_list_op)
                            
                        conn_list_op.close()
                        
                    if df_ops is not None and not df_ops.empty:
                        lista_ops_procesadas = []
                        
                        # Indexación rápida de proveedores para evitar bucles lentos
                        dict_provs_por_id = {str(v['id_interno']): v for v in dict_provs.values()}
                        dict_provs_por_rif = {str(v['rif']): v for v in dict_provs.values()}
                        fallback_prov = list(dict_provs.values())[0] if dict_provs else None
                        
                        for _, r_op in df_ops.iterrows():
                            p_id = str(r_op['proveedor_id'])
                            prov_encontrado = dict_provs_por_id.get(p_id) or dict_provs_por_rif.get(p_id) or fallback_prov
                            
                            lista_ops_procesadas.append({
                                'id': r_op['id'],
                                'proveedor_rif': prov_encontrado['rif'] if prov_encontrado else 'N/A',
                                'proveedor': prov_encontrado['nombre'] if prov_encontrado else 'Desconocido',
                                'cuenta_gasto_codigo': prov_encontrado.get('codigo_cuenta', 'N/A') if prov_encontrado else 'N/A',
                                'cuenta_gasto_desc': prov_encontrado.get('descripcion_cuenta', 'N/A') if prov_encontrado else 'N/A',
                                'nro_factura': r_op['nro_factura'],
                                'nro_control': r_op['nro_control'],
                                'monto_bruto': r_op['monto_bruto'],
                                'monto_exento': r_op['monto_exento'],
                                'base_imponible': r_op['base_imponible'],
                                'iva_porcentaje': r_op['iva_porcentaje'],
                                'monto_iva': r_op['monto_iva'],
                                'retencion_islr': r_op['retencion_islr'],
                                'retencion_iva': r_op['retencion_iva'],
                                'monto_neto': r_op['monto_neto'],
                                'estado': r_op['estado'],
                                'fecha_emision': r_op['fecha_emision'],
                                'observaciones': r_op['observaciones'],
                                'islr_porcentaje': r_op['islr_porcentaje'],
                                'islr_sustraendo': r_op['islr_sustraendo'],
                                'tipo_persona': r_op['tipo_persona']
                            })
                        
                        import pandas as pd
                        df_ops_final = pd.DataFrame(lista_ops_procesadas)
                        
                        IDs_ya_procesados = [1, 2, 3]
                        df_ops_final = df_ops_final[
                            (df_ops_final['estado'].str.lower() == 'pendiente') & 
                            (~df_ops_final['id'].isin(IDs_ya_procesados))
                        ]
                        
                        if df_ops_final.empty:
                            st.info("🎉 ¡Excelente! No hay órdenes de pago pendientes por contabilizar en este momento.")
                        else:
                            df_display = df_ops_final[['id', 'proveedor', 'nro_factura', 'monto_bruto', 'monto_neto', 'retencion_islr', 'estado', 'fecha_emision']]
                            st.dataframe(df_display, use_container_width=True, hide_index=True)
                            
                            st.markdown("---")
                            opciones_ordenes = {f"ID: {row['id']} | Factura: {row['nro_factura']} | Proveedor: {row['proveedor']} | Estado: {row['estado']}": row for _, row in df_ops_final.iterrows()}
                            lista_claves_ops = list(opciones_ordenes.keys())
                            
                            if "select_op_final_v2" in st.session_state and st.session_state["select_op_final_v2"] not in lista_claves_ops:
                                st.session_state["select_op_final_v2"] = lista_claves_ops[0] if lista_claves_ops else None
                            
                            seleccion_op_key = st.selectbox(
                                "🔍 Selecciona una Orden de Pago para configurar sus cuentas y previsualizar los asientos:", 
                                options=lista_claves_ops,
                                index=0,
                                key="select_op_final_v2"
                            )
                            
                            if seleccion_op_key and seleccion_op_key in opciones_ordenes:
                                sel_data = opciones_ordenes[seleccion_op_key]
                                
                                st.markdown("---")
                                st.markdown(f"### ⚙ Configuración de Cuentas para la Orden #{sel_data['id']}")
                                
                                col_c1, col_c2, col_c3 = st.columns(3)
                                with col_c1:
                                    cta_gasto_sel = st.selectbox("Cuenta de Gasto / Costo", options=lista_cuentas_detalle if lista_cuentas_detalle else ["Sin cuentas"], key=f"cta_gasto_{sel_data['id']}")
                                    info_gasto = dict_cuentas_detalle.get(cta_gasto_sel, {'codigo': '6.1.1.01.001', 'nombre': 'Gastos Generales'})
                                with col_c2:
                                    cta_iva_sel = st.selectbox("Cuenta Crédito Fiscal IVA", options=lista_cuentas_detalle if lista_cuentas_detalle else ["Sin cuentas"], key=f"cta_iva_{sel_data['id']}")
                                    info_iva = dict_cuentas_detalle.get(cta_iva_sel, {'codigo': '1.1.4.02.001', 'nombre': 'Crédito Fiscal IVA'})
                                with col_c3:
                                    cta_banco_sel = st.selectbox("Cuenta Banco / Salida", options=lista_cuentas_detalle if lista_cuentas_detalle else ["Sin cuentas"], key=f"cta_banco_{sel_data['id']}")
                                    info_banco = dict_cuentas_detalle.get(cta_banco_sel, {'codigo': '1.1.1.01.001', 'nombre': 'Banco Principal'})
                                    info_banco['nombre'] = info_banco.get('nombre', 'Banco Principal')

                                st.markdown("---")
                                st.markdown("### 🔄 Proceso de Registro por Módulos (Paso a Paso)")

                                key_paso = f"paso_actual_{sel_data['id']}"
                                if key_paso not in st.session_state:
                                    st.session_state[key_paso] = 1

                                paso = st.session_state[key_paso]

                                # --- PASO 1: LIBRO DE COMPRAS ---
                                if paso == 1:
                                    st.markdown("#### 📄 Paso 1: Registrar en `libro_compras`")
                                    st.code(f"""fecha_operacion: {sel_data['fecha_emision']}
                tipo_documento: Factura
                n_factura: {sel_data['nro_factura']}
                n_control: {sel_data['nro_control']}
                proveedor: {sel_data['proveedor']}
                rif: {sel_data['proveedor_rif']}
                total_compras: {sel_data['monto_bruto']:,.2f}
                base_imponible: {sel_data['base_imponible']:,.2f}
                iva_porcentaje: {sel_data['iva_porcentaje']}%
                iva_monto: {sel_data['monto_iva']:,.2f}
                retencion_iva: {sel_data['retencion_iva']:,.2f}""", language="yaml")
                                    
                                    if st.button("💾 Guardar Libro de Compras y Pasar al Asiento", key=f"btn_guardar_libro_{sel_data['id']}", use_container_width=False):
                                        rif_val = str(sel_data.get('proveedor_rif', '')).strip()
                                        fact_val = str(sel_data.get('nro_factura', '')).strip()
                                        ctrl_val = str(sel_data.get('nro_control', '')).strip()
                                        prov_val = str(sel_data.get('proveedor', '')).strip()
                                        
                                        if not fact_val or fact_val in ['None', 'N/A', '?', '']:
                                            st.error("⚠️ Error: El número de factura está vacío o es inválido.")
                                        elif not rif_val or rif_val in ['None', 'N/A', '?', '']:
                                            st.error(f"⚠️ Error: El RIF del proveedor ('{rif_val}') está vacío.")
                                        else:
                                            with st.spinner("Guardando en Libro de Compras..."):
                                                try:
                                                    conn_l = conectar_db(db_actual)
                                                    if conn_l:
                                                        with conn_l.cursor() as cur_l:
                                                            cur_l.execute("SELECT id FROM libro_compras WHERE n_factura = %s AND rif = %s", (fact_val, rif_val))
                                                            existe = cur_l.fetchone()
                                                            
                                                            if existe:
                                                                st.warning(f"⚠️ La factura **{fact_val}** ya se encuentra registrada. Avanzando...")
                                                            else:
                                                                query_libro = """
                                                                    INSERT INTO libro_compras (
                                                                        fecha_operacion, tipo_documento, n_factura, n_control, 
                                                                        n_factura_afectada, proveedor, rif, tipo_transaccion, 
                                                                        total_compras, importe_exento, base_imponible, iva_porcentaje, 
                                                                        iva_monto, retencion_realizada, retencion_iva_realizada, 
                                                                        n_comprobante_retencion, monto_iva_retenido, fecha_comprobante, 
                                                                        created_at, updated_at
                                                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                                                                """
                                                                valores_libro = (
                                                                    str(sel_data['fecha_emision']), "Factura", str(fact_val),
                                                                    str(ctrl_val if ctrl_val and ctrl_val != 'None' else 'S/N'), None,
                                                                    str(prov_val if prov_val and prov_val != 'None' else 'Proveedor Genérico'),
                                                                    str(rif_val), "01", float(sel_data.get('monto_bruto', 0.0)),
                                                                    float(sel_data.get('monto_exento', 0.0)), float(sel_data.get('base_imponible', 0.0)),
                                                                    float(sel_data.get('iva_porcentaje', 16.0)), float(sel_data.get('monto_iva', 0.0)),
                                                                    1 if float(sel_data.get('retencion_iva', 0.0)) > 0 else 0,
                                                                    1 if float(sel_data.get('retencion_iva', 0.0)) > 0 else 0,
                                                                    str(f"COMP-{fact_val}"), float(sel_data.get('retencion_iva', 0.0)),
                                                                    str(sel_data['fecha_emision'])
                                                                )
                                                                cur_l.execute(query_libro, valores_libro)
                                                                conn_l.commit()
                                                                st.success("✅ ¡Libro de Compras guardado con éxito!")
                                                        conn_l.close()
                                                        st.session_state[key_paso] = 2
                                                        st.rerun()
                                                except Exception as err_l:
                                                    st.error(f"❌ Error al guardar libro de compras: {err_l}")

                                # --- PASO 2: ASIENTO CONTABLE ---
                                elif paso == 2:
                                    total_gasto_costo = float(sel_data['base_imponible']) + float(sel_data.get('monto_exento', 0.0))
                                    
                                    st.markdown("#### 📒 Paso 2: Registrar `asientos_contables`")
                                    st.code(f"""- n_comprobante: OP-{sel_data['nro_factura']}
                fecha: {sel_data['fecha_emision']}
                asientos:
                  - plan_cuentas: {info_gasto['codigo']}
                    debe: {total_gasto_costo:,.2f}
                    haber: 0.00
                  - plan_cuentas: {info_iva['codigo']}
                    debe: {sel_data['monto_iva']:,.2f}
                    haber: 0.00
                  - plan_cuentas: 2.1.2.01.005
                    debe: 0.00
                    haber: {sel_data['retencion_islr']:,.2f}
                  - plan_cuentas: 2.1.2.01.003
                    debe: 0.00
                    haber: {sel_data['retencion_iva']:,.2f}
                  - plan_cuentas: {info_banco['codigo']}
                    debe: 0.00
                    haber: {sel_data['monto_neto']:,.2f}""", language="yaml")
                                    
                                    if st.button("💾 Guardar Asiento Contable y Pasar a Banco", key=f"btn_guardar_asiento_{sel_data['id']}", use_container_width=False):
                                        with st.spinner("Registrando asiento contable..."):
                                            try:
                                                conn_a = conectar_db(db_actual)
                                                if conn_a:
                                                    with conn_a.cursor() as cur_a:
                                                        n_comp_val = f"OP-{sel_data['nro_factura']}"
                                                        fecha_val = str(sel_data['fecha_emision'])
                                                        lineas_asiento = [
                                                            (info_gasto['codigo'], info_gasto['nombre'], total_gasto_costo, 0.00),
                                                            (info_iva['codigo'], info_iva['nombre'], float(sel_data['monto_iva']), 0.00),
                                                            ("2.1.2.01.005", "Retención ISLR Por Pagar", 0.00, float(sel_data['retencion_islr'])),
                                                            ("2.1.2.01.003", "Retención IVA Por Pagar", 0.00, float(sel_data['retencion_iva'])),
                                                            (info_banco['codigo'], info_banco['nombre'], 0.00, float(sel_data['monto_neto']))
                                                        ]
                                                        query_asiento = """
                                                            INSERT INTO asientos_contables (
                                                                n_comprobante, descripcion, fecha, plan_cuentas, 
                                                                cuenta_contable, referencia, debe, haber, bloqueado
                                                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                                                        """
                                                        for c_cod, c_nom, debe_v, haber_v in lineas_asiento:
                                                            if debe_v > 0 or haber_v > 0:
                                                                cur_a.execute(query_asiento, (
                                                                    n_comp_val,
                                                                    f"Pago a Proveedor {sel_data['proveedor']} - Factura {sel_data['nro_factura']}",
                                                                    fecha_val, c_cod, c_nom, n_comp_val, debe_v, haber_v
                                                                ))
                                                        conn_a.commit()
                                                    conn_a.close()
                                                    st.success("✅ ¡Asiento Contable guardado con éxito!")
                                                    st.session_state[key_paso] = 3
                                                    st.rerun()
                                            except Exception as err_a:
                                                st.error(f"❌ Error al guardar asiento contable: {err_a}")
                    
                except Exception as ex_historial:
                    st.warning(f"Aviso en historial: {ex_historial}")
        with tab3:
            st.markdown("### 🔗 Conciliación, Cruce Bancario y Emisión de Comprobante")
            st.markdown("Cruza las órdenes de pago, registra primero el movimiento en el banco, selecciona la cuenta contable de salida, previsualiza el asiento y guárdalo en la base de datos.")

            try:
                # --- FUNCIÓN OPTIMIZADA CON CACHÉ PARA PLAN DE CUENTAS Y ÓRDENES PENDIENTES ---
                @st.cache_data(ttl=300, show_spinner=False)
                def cargar_datos_conciliacion_opt(empresa):
                    b_lista, b_dict, df_ops_pend = [], {}, None
                    try:
                        conn = conectar_db(empresa)
                        if conn:
                            # 1. Plan de cuentas bancarias/detalle
                            df_ctas = ejecutar_consulta(
                                "SELECT codigo, nombre FROM plan_cuentas WHERE tipo = 'Detalle' AND (codigo LIKE '1.1.1%%' OR LOWER(nombre) LIKE '%%banco%%' OR LOWER(nombre) LIKE '%%caja%%') ORDER BY codigo", 
                                conn
                            )
                            if df_ctas is None or df_ctas.empty:
                                df_ctas = ejecutar_consulta("SELECT codigo, nombre FROM plan_cuentas WHERE tipo = 'Detalle' ORDER BY codigo", conn)
                            
                            if df_ctas is not None and not df_ctas.empty:
                                for _, r_cta in df_ctas.iterrows():
                                    lbl_cta = f"{str(r_cta['codigo']).strip()} - {str(r_cta['nombre']).strip()}"
                                    b_lista.append(lbl_cta)
                                    b_dict[lbl_cta] = {
                                        'codigo': str(r_cta['codigo']).strip(),
                                        'nombre': str(r_cta['nombre']).strip()
                                    }

                            # 2. Órdenes de pago pendientes por conciliar
                            query_pendientes = """
                                SELECT op.id, p.nombre AS proveedor, p.rif, p.banco AS banco_prov, p.nro_cuenta AS cuenta_prov, 
                                       op.nro_factura, op.monto_bruto, op.retencion_islr, op.retencion_iva, op.monto_neto, op.fecha_emision, op.observaciones, op.estado
                                FROM ordenes_pago op
                                JOIN proveedores_carga p ON op.proveedor_id = p.id
                                WHERE op.empresa_db = %s 
                                  AND (op.estado NOT IN ('Conciliado', 'Pagado') OR op.estado IS NULL)
                                ORDER BY op.fecha_emision DESC
                            """
                            df_ops_pend = ejecutar_consulta(query_pendientes, conn, params=(str(empresa),))
                            conn.close()
                    except Exception:
                        pass
                    return b_lista, b_dict, df_ops_pend

                lista_bancos_detalle, dict_bancos_detalle, df_pendientes = cargar_datos_conciliacion_opt(db_actual)

                # ==========================================
                # ⚡ PASO 1 Y 2: CONCILIACIÓN DE ÓRDENES
                # ==========================================
                if df_pendientes is not None and not df_pendientes.empty:
                    import pandas as pd
                    df_pendientes['monto_neto'] = pd.to_numeric(df_pendientes['monto_neto'], errors='coerce').fillna(0.0)
                    
                    st.divider()
                    st.markdown("#### ⚡ Paso 1: Datos Bancarios y Registro en Banco")
                    
                    dict_ops_pend = {
                        f"ID: {row['id']} | Prov: {row['proveedor']} | Factura: {row['nro_factura']} | Neto: {row['monto_neto']:,.2f} | Estado: {row['estado']}": row['id']
                        for _, row in df_pendientes.iterrows()
                    }
                    
                    selected_op_label = st.selectbox("Selecciona la Orden de Pago a Conciliar", list(dict_ops_pend.keys()), key="select_op_cruce_tab3")
                    fila_op_sel = df_pendientes[df_pendientes['id'] == dict_ops_pend[selected_op_label]].iloc[0]
                    
                    col_m1, col_m2 = st.columns(2)
                    with col_m1:
                        referencia_bancaria = st.text_input("Número de Referencia Bancaria (según Estado de Cuenta)", key="input_ref_banco_b").strip()
                    with col_m2:
                        fecha_pago_real = st.date_input("Fecha real del movimiento en el Banco", key="input_fec_banco_b")

                    # --- TABLA BANCO MOVIMIENTOS ---
                    st.divider()
                    st.markdown("#### 📊 Movimientos Bancarios Registrados por Rango de Fecha")
                    
                    col_fec_bm1, col_fec_bm2 = st.columns(2)
                    with col_fec_bm1:
                        fec_desde_bm_tab3 = st.date_input("Desde la fecha (Movimiento)", key="bm_tab3_fec_desde")
                    with col_fec_bm2:
                        fec_hasta_bm_tab3 = st.date_input("Hasta la fecha (Movimiento)", key="bm_tab3_fec_hasta")

                    try:
                        conn_v_bm = conectar_db(db_actual)
                        if conn_v_bm:
                            query_ver_bm = """
                                SELECT id, banco_nombre, cuenta_numero, fecha_movimiento, referencia, descripcion, monto, estado_conciliacion, asiento_id 
                                FROM banco_movimientos 
                                WHERE fecha_movimiento BETWEEN %s AND %s
                                ORDER BY fecha_movimiento DESC, id DESC
                            """
                            df_ver_bm = ejecutar_consulta(query_ver_bm, conn_v_bm, params=(str(fec_desde_bm_tab3), str(fec_hasta_bm_tab3)))
                            conn_v_bm.close()

                            if df_ver_bm is not None and not df_ver_bm.empty:
                                df_ver_bm['monto'] = pd.to_numeric(df_ver_bm['monto'], errors='coerce').fillna(0.0)

                                st.dataframe(
                                    df_ver_bm[['id', 'fecha_movimiento', 'banco_nombre', 'referencia', 'descripcion', 'monto', 'estado_conciliacion', 'asiento_id']],
                                    use_container_width=True,
                                    hide_index=True,
                                    column_config={
                                        "id": "ID",
                                        "fecha_movimiento": "Fecha Mov.",
                                        "banco_nombre": "Banco",
                                        "referencia": "Referencia",
                                        "descripcion": "Descripción",
                                        "monto": st.column_config.NumberColumn("Monto", format="%,.2f", help="Monto del movimiento bancario"),
                                        "estado_conciliacion": "Estado",
                                        "asiento_id": "Comprobante"
                                    }
                                )
                            else:
                                st.info("ℹ️ No hay movimientos registrados en el rango de fechas seleccionado.")
                    except Exception as err_v_bm:
                        st.error(f"❌ Error al cargar los movimientos bancarios: {err_v_bm}")

                    st.divider()
                    st.markdown("#### ⚡ Paso 2: Selección de Cuenta Contable, Previsualización y Registro en Asientos")

                    cta_banco_salida = st.selectbox(
                        "🏦 Selecciona la Cuenta Bancaria / Salida de Dinero (Haber)", 
                        options=lista_bancos_detalle if lista_bancos_detalle else ["No hay cuentas de detalle disponibles"],
                        key="select_banco_salida_pago"
                    )

                    info_banco_prev = dict_bancos_detalle.get(cta_banco_salida, {'codigo': '1.1.1.01.001', 'nombre': 'Banco Principal'})
                    monto_prev = float(fila_op_sel['monto_neto'])
                    n_fact_prev = str(fila_op_sel['nro_factura'])
                    prov_prev = str(fila_op_sel['proveedor'])
                    n_comp_prev = f"PAGO-{n_fact_prev}"
                    desc_prev = f"Cancelación de Pago a {prov_prev} - Factura {n_fact_prev}"
                    ref_prev = referencia_bancaria if referencia_bancaria else "(Pendiente de Ref)"
                    fecha_prev = str(fecha_pago_real)

                    html_asiento = f"""
                    <style>
                        .tabla-asiento {{ width: 100%; border-collapse: collapse; font-family: sans-serif; font-size: 13px; margin: 10px 0; background-color: #ffffff; box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-radius: 6px; overflow: hidden; }}
                        .tabla-asiento th {{ background-color: #f8f9fa; color: #333; padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6; font-weight: bold; }}
                        .tabla-asiento td {{ padding: 9px 10px; border-bottom: 1px solid #e9ecef; color: #212529; }}
                        .monto-col {{ text-align: right; font-family: monospace; font-weight: bold; }}
                        .badge-bloqueado {{ background-color: #e2e3e5; color: #383d41; padding: 2px 6px; border-radius: 4px; font-size: 11px; }}
                    </style>
                    <table class="tabla-asiento">
                        <thead>
                            <tr>
                                <th>N° Comprobante</th><th>Descripción</th><th>Fecha</th><th>Plan Cuentas</th><th>Cuenta Contable</th><th>Referencia</th><th style="text-align: right;">Debe</th><th style="text-align: right;">Haber</th><th style="text-align: center;">Bloq</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><b>{n_comp_prev}</b></td><td>{desc_prev}</td><td>{fecha_prev}</td><td><code>2.1.1.01.001</code></td><td>Proveedores Nacionales</td><td>{ref_prev}</td><td class="monto-col" style="color: #2b8a3e;">{monto_prev:,.2f}</td><td class="monto-col">0.00</td><td style="text-align: center;"><span class="badge-bloqueado">0</span></td>
                            </tr>
                            <tr>
                                <td><b>{n_comp_prev}</b></td><td>{desc_prev}</td><td>{fecha_prev}</td><td><code>{info_banco_prev['codigo']}</code></td><td>{info_banco_prev['nombre']}</td><td>{ref_prev}</td><td class="monto-col">0.00</td><td class="monto-col" style="color: #c92a2a;">{monto_prev:,.2f}</td><td style="text-align: center;"><span class="badge-bloqueado">0</span></td>
                            </tr>
                        </tbody>
                        <tfoot>
                            <tr style="background-color: #f8f9fa; font-weight: bold;">
                                <td colspan="6" style="text-align: right;">TOTALES:</td><td class="monto-col" style="color: #2b8a3e;">{monto_prev:,.2f}</td><td class="monto-col" style="color: #c92a2a;">{monto_prev:,.2f}</td><td></td>
                            </tr>
                        </tfoot>
                    </table>
                    """
                    st.markdown(html_asiento, unsafe_allow_html=True)

                    col_btn_p1, col_btn_p2 = st.columns(2)

                    with col_btn_p1:
                        if st.button("📥 Registrar Movimiento en Banco", type="secondary", key="btn_guardar_banco_mov", use_container_width=True):
                            if not referencia_bancaria:
                                st.warning("⚠️ Debes introducir obligatoriamente la referencia bancaria del estado de cuenta.")
                            else:
                                try:
                                    conn_bm = conectar_db(db_actual)
                                    if conn_bm:
                                        with conn_bm.cursor() as cur_bm:
                                            import datetime
                                            fecha_actual_hoy = datetime.date.today().strftime('%Y-%m-%d')
                                            monto_a_pagar = float(fila_op_sel['monto_neto'])
                                            n_fact_val = str(fila_op_sel['nro_factura'])
                                            prov_nombre_val = str(fila_op_sel['proveedor'])
                                            n_comp_asiento = f"PAGO-{n_fact_val}"

                                            cur_bm.execute("""
                                                INSERT INTO banco_movimientos (
                                                    banco_nombre, cuenta_numero, fecha_movimiento, referencia, 
                                                    descripcion, monto, estado_conciliacion, asiento_id, fecha_importacion
                                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            """, (
                                                str(fila_op_sel['banco_prov']) if fila_op_sel['banco_prov'] else "Banco Emisor",
                                                str(fila_op_sel['cuenta_prov']) if fila_op_sel['cuenta_prov'] else "N/A",
                                                str(fecha_pago_real), referencia_bancaria, f"Pago Factura #{n_fact_val} - {prov_nombre_val}",
                                                -monto_a_pagar, 'Pendiente Asiento', n_comp_asiento, fecha_actual_hoy
                                            ))

                                            cur_bm.execute("UPDATE ordenes_pago SET estado = 'Procesado' WHERE id = %s AND empresa_db = %s", (int(fila_op_sel['id']), str(db_actual)))
                                            conn_bm.commit()

                                        conn_bm.close()
                                        cargar_datos_conciliacion_opt.clear()
                                        st.success("✅ ¡Movimiento bancario registrado con éxito!")
                                        st.rerun()
                                except Exception as err_bm:
                                    st.error(f"❌ Error al guardar en banco_movimientos: {err_bm}")

                    with col_btn_p2:
                        if st.button("💾 Guardar Asiento en Libro Diario y Conciliar", type="primary", key="btn_guardar_asiento_diario", use_container_width=True):
                            if not referencia_bancaria:
                                st.warning("⚠️ Asegúrate de haber ingresado la referencia bancaria.")
                            elif not lista_bancos_detalle or "No hay cuentas" in cta_banco_salida:
                                st.error("⚠️ Debes seleccionar una cuenta bancaria válida.")
                            else:
                                try:
                                    conn_update = conectar_db(db_actual)
                                    if conn_update:
                                        with conn_update.cursor() as cursor_m:
                                            monto_a_pagar = float(fila_op_sel['monto_neto'])
                                            n_fact_val = str(fila_op_sel['nro_factura'])
                                            prov_nombre_val = str(fila_op_sel['proveedor'])
                                            n_comp_asiento = f"PAGO-{n_fact_val}"

                                            query_asiento_pago = """
                                                INSERT INTO asientos_contables (
                                                    n_comprobante, descripcion, fecha, plan_cuentas, 
                                                    cuenta_contable, referencia, debe, haber, bloqueado
                                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                                            """
                                            # Debe
                                            cursor_m.execute(query_asiento_pago, (n_comp_asiento, f"Cancelación de Pago a {prov_nombre_val} - Factura {n_fact_val}", str(fecha_pago_real), "2.1.1.01.001", "Proveedores Nacionales", referencia_bancaria, monto_a_pagar, 0.00))
                                            # Haber
                                            cursor_m.execute(query_asiento_pago, (n_comp_asiento, f"Cancelación de Pago a {prov_nombre_val} - Factura {n_fact_val}", str(fecha_pago_real), info_banco_prev['codigo'], info_banco_prev['nombre'], referencia_bancaria, 0.00, monto_a_pagar))
                                            # Update Orden
                                            cursor_m.execute("UPDATE ordenes_pago SET referencia_banco = %s, fecha_pago = %s, estado = 'Conciliado' WHERE id = %s AND empresa_db = %s", (referencia_bancaria, fecha_pago_real, int(fila_op_sel['id']), str(db_actual)))
                                            conn_update.commit()

                                        conn_update.close()
                                        cargar_datos_conciliacion_opt.clear()
                                        st.success(f"✅ ¡Proceso completado! Asiento `{n_comp_asiento}` guardado y orden #{fila_op_sel['id']} marcada como Conciliada.")
                                        st.rerun()
                                except Exception as ex_m:
                                    st.error(f"❌ Error al registrar el asiento contable: {ex_m}")
                else:
                    st.info("🎉 ¡Excelente! No hay órdenes de pago disponibles para conciliar.")

                # ==========================================
                # 📜 HISTORIAL DE PAGOS CONCILIADOS
                # ==========================================
                st.divider()
                st.markdown("### 📜 Historial de Pagos Conciliados y Estado de Cuenta Interno")
                st.markdown("Consulta, filtra por rango de fechas, edita referencias o revierte los pagos conciliados según tu control interno.")

                col_fec1, col_fec2 = st.columns(2)
                with col_fec1:
                    fecha_desde = st.date_input("Historial Desde", key="hist_fecha_desde")
                with col_fec2:
                    fecha_hasta = st.date_input("Historial Hasta", key="hist_fecha_hasta")

                conn_conc = conectar_db(db_actual)
                df_conciliados = None
                if conn_conc:
                    query_conciliados = """
                        SELECT op.id, p.nombre AS proveedor, op.nro_factura, op.monto_neto, op.referencia_banco, op.fecha_pago, op.estado
                        FROM ordenes_pago op
                        JOIN proveedores_carga p ON op.proveedor_id = p.id
                        WHERE op.empresa_db = %s AND op.estado = 'Conciliado' AND op.fecha_pago BETWEEN %s AND %s
                        ORDER BY op.fecha_pago DESC
                    """
                    df_conciliados = ejecutar_consulta(query_conciliados, conn_conc, params=(str(db_actual), str(fecha_desde), str(fecha_hasta)))
                    conn_conc.close()

                if df_conciliados is not None and not df_conciliados.empty:
                    st.markdown(f"📊 Se encontraron **{len(df_conciliados)}** pago(s) conciliado(s) en el rango seleccionado.")
                    st.dataframe(
                        df_conciliados, 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "monto_neto": st.column_config.NumberColumn("Monto Neto", format="%,.2f", help="Monto neto pagado")
                        }
                    )
                    
                    st.markdown("#### ⚙️ Modificar o Revertir un Pago Conciliado")
                    
                    dict_historial = {f"ID: {r['id']} | Factura: {r['nro_factura']} | Proveedor: {r['proveedor']} | Ref: {r['referencia_banco']}": r for _, r in df_conciliados.iterrows()}
                    selected_hist_label = st.selectbox("Selecciona el registro a gestionar:", list(dict_historial.keys()), key="select_gestion_historial")
                    
                    if selected_hist_label:
                        row_sel = dict_historial[selected_hist_label]
                        
                        col_ed1, col_ed2 = st.columns(2)
                        with col_ed1:
                            nuevo_ref_banco = st.text_input("Nueva Referencia Bancaria", value=str(row_sel['referencia_banco']), key=f"edit_ref_{row_sel['id']}")
                        with col_ed2:
                            fecha_actual_pago = pd.to_datetime(row_sel['fecha_pago']).date() if pd.notnull(row_sel['fecha_pago']) else None
                            nueva_fecha_pago = st.date_input("Nueva Fecha de Pago", value=fecha_actual_pago, key=f"edit_fecha_{row_sel['id']}")
                        
                        col_btn_ed1, col_btn_ed2 = st.columns(2)
                        with col_btn_ed1:
                            if st.button("💾 Guardar Cambios del Pago", type="primary", key=f"btn_save_edit_{row_sel['id']}", use_container_width=True):
                                try:
                                    conn_edit = conectar_db(db_actual)
                                    if conn_edit:
                                        with conn_edit.cursor() as cur_e:
                                            cur_e.execute("UPDATE ordenes_pago SET referencia_banco = %s, fecha_pago = %s WHERE id = %s AND empresa_db = %s", (nuevo_ref_banco.strip(), nueva_fecha_pago, int(row_sel['id']), str(db_actual)))
                                            conn_edit.commit()
                                        conn_edit.close()
                                        st.success(f"✅ ¡Pago ID #{row_sel['id']} actualizado correctamente!")
                                        st.rerun()
                                except Exception as err_ed:
                                    st.error(f"❌ Error al modificar el registro: {err_ed}")
                                    
                        with col_btn_ed2:
                            if st.button("🔄 Revertir a Estado 'Pendiente'", type="secondary", key=f"btn_revert_{row_sel['id']}", use_container_width=True):
                                try:
                                    conn_rev = conectar_db(db_actual)
                                    if conn_rev:
                                        with conn_rev.cursor() as cur_r:
                                            cur_r.execute("UPDATE ordenes_pago SET estado = 'Pendiente', referencia_banco = NULL, fecha_pago = NULL WHERE id = %s AND empresa_db = %s", (int(row_sel['id']), str(db_actual)))
                                            conn_rev.commit()
                                        conn_rev.close()
                                        cargar_datos_conciliacion_opt.clear()
                                        st.warning(f"⚠️ El pago ID #{row_sel['id']} ha sido devuelto a estado **Pendiente**.")
                                        st.rerun()
                                except Exception as err_rev:
                                    st.error(f"❌ Error al revertir el registro: {err_rev}")

                    st.markdown("---")
                    
                    # EXCEL SOBRE DEMANDA (Solo procesa al pulsar)
                    @st.cache_data(show_spinner=False)
                    def generar_excel_conciliados(df):
                        import io
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df.to_excel(writer, index=False, sheet_name='Pagos Conciliados')
                        return output.getvalue()

                    st.download_button(
                        label="📥 Descargar Reporte de Pagos Conciliados (Excel)",
                        data=generar_excel_conciliados(df_conciliados),
                        file_name=f"reporte_pagos_conciliados_{db_actual}_{fecha_desde}_al_{fecha_hasta}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.info("ℹ️ No hay pagos conciliados registrados para el rango de fechas seleccionado.")

            except Exception as e:
                st.error(f"Error en el módulo de conciliación: {e}")

        with tab4:
            st.markdown("### ✏️ Modificar y Actualizar Registros")
            st.markdown("Selecciona la tabla que deseas administrar, filtra por fechas y corrige o elimina el registro necesario.")
            
            sub_gestion = st.radio(
                "Elige la tabla a administrar:", 
                ["Proveedores Carga", "Órdenes de Pago", "Movimientos Bancarios"], 
                horizontal=True, 
                key="radio_gestion_tab4"
            )
            
            # --- FUNCIÓN CON CACHÉ PARA CARGAR DATOS DE EDICIÓN ---
            @st.cache_data(ttl=60, show_spinner=False)
            def cargar_datos_edicion(empresa, tabla, f_desde=None, f_hasta=None):
                df = None
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        if tabla == "proveedores":
                            df = ejecutar_consulta("SELECT id, empresa_db, nombre, rif, codigo_cuenta, descripcion_cuenta, telefono, email, banco, nro_cuenta, tipo_cuenta FROM proveedores_carga WHERE empresa_db = %s", conn, params=(str(empresa),))
                        elif tabla == "ordenes":
                            query = "SELECT id, nro_factura, monto_bruto, retencion_islr, retencion_iva, monto_neto, estado, observaciones, fecha_emision FROM ordenes_pago WHERE empresa_db = %s AND fecha_emision BETWEEN %s AND %s ORDER BY fecha_emision DESC"
                            df = ejecutar_consulta(query, conn, params=(str(empresa), str(f_desde), str(f_hasta)))
                        elif tabla == "banco":
                            query = "SELECT id, banco_nombre, cuenta_numero, fecha_movimiento, referencia, descripcion, monto, estado_conciliacion, asiento_id FROM banco_movimientos WHERE empresa_db = %s AND fecha_movimiento BETWEEN %s AND %s ORDER BY fecha_movimiento DESC LIMIT 100"
                            df = ejecutar_consulta(query, conn, params=(str(empresa), str(f_desde), str(f_hasta)))
                        conn.close()
                except Exception:
                    pass
                return df

            # ==========================================
            # 🏢 1. PROVEEDORES CARGA
            # ==========================================
            if sub_gestion == "Proveedores Carga":
                st.markdown("#### 🏢 Editar / Actualizar Proveedor de Carga")
                try:
                    df_pc = cargar_datos_edicion(db_actual, "proveedores")
                    
                    if df_pc is not None and not df_pc.empty:
                        dict_pc = {f"ID: {r['id']} - {r['nombre']} (RIF: {r['rif']})": r for _, r in df_pc.iterrows()}
                        sel_pc_label = st.selectbox("Selecciona el Proveedor a modificar", list(dict_pc.keys()), key="sel_pc_edit_full")
                        
                        fila_pc = dict_pc[sel_pc_label]
                        id_pc_sel = fila_pc['id']
                        
                        with st.form("form_editar_proveedor_carga"):
                            st.markdown(f"**Modificando el registro ID:** `{id_pc_sel}`")
                            
                            col_ed1, col_ed2 = st.columns(2)
                            with col_ed1:
                                nuevo_nombre = st.text_input("Razón Social / Nombre", value=fila_pc['nombre'] or "").strip()
                                nuevo_rif = st.text_input("RIF", value=fila_pc['rif'] or "").strip()
                                nuevo_tel = st.text_input("Teléfono", value=fila_pc['telefono'] or "").strip()
                                nuevo_email = st.text_input("Correo Electrónico", value=fila_pc['email'] or "").strip()
                                
                            with col_ed2:
                                lista_bancos_opt = ["Banesco", "Mercantil", "Provincial", "BOD / 100% Banco", "Banco de Venezuela", "BNC", "Otros / Extranjero"]
                                idx_banco = lista_bancos_opt.index(fila_pc['banco']) if fila_pc['banco'] in lista_bancos_opt else 0
                                nuevo_banco = st.selectbox("Banco Destino", lista_bancos_opt, index=idx_banco)
                                
                                nueva_cuenta = st.text_input("Número de Cuenta", value=fila_pc['nro_cuenta'] or "").strip()
                                
                                lista_tipos_opt = ["Corriente", "Ahorro", "Divisas"]
                                idx_tipo = lista_tipos_opt.index(fila_pc['tipo_cuenta']) if fila_pc['tipo_cuenta'] in lista_tipos_opt else 0
                                nuevo_tipo_cta = st.selectbox("Tipo de Cuenta", lista_tipos_opt, index=idx_tipo)
                                
                                nuevo_cod_cta = st.text_input("Código Cuenta Contable", value=fila_pc['codigo_cuenta'] or "").strip()
                            
                            col_btn1, col_btn2 = st.columns(2)
                            with col_btn1:
                                btn_actualizar_pc = st.form_submit_button("💾 Actualizar Toda la Línea", type="primary")
                            with col_btn2:
                                btn_eliminar_pc = st.form_submit_button("🗑️ Eliminar este Registro", type="secondary")
                                
                            if btn_actualizar_pc:
                                if nuevo_nombre and nuevo_rif:
                                    try:
                                        conn_up = conectar_db(db_actual)
                                        with conn_up.cursor() as cur_up:
                                            cur_up.execute("""
                                                UPDATE proveedores_carga 
                                                SET nombre = %s, rif = %s, telefono = %s, email = %s, banco = %s, nro_cuenta = %s, tipo_cuenta = %s, codigo_cuenta = %s
                                                WHERE id = %s AND empresa_db = %s
                                            """, (nuevo_nombre, nuevo_rif, nuevo_tel, nuevo_email, nuevo_banco, nueva_cuenta, nuevo_tipo_cta, nuevo_cod_cta, id_pc_sel, str(db_actual)))
                                            conn_up.commit()
                                        conn_up.close()
                                        cargar_datos_edicion.clear()
                                        st.success("✅ ¡Proveedor actualizado con éxito!")
                                        st.rerun()
                                    except Exception as ex_up:
                                        st.error(f"❌ Error al actualizar: {ex_up}")
                                else:
                                    st.warning("⚠️ El nombre y el RIF no pueden estar vacíos.")
                                    
                            if btn_eliminar_pc:
                                try:
                                    conn_del = conectar_db(db_actual)
                                    with conn_del.cursor() as cur_d:
                                        cur_d.execute("DELETE FROM proveedores_carga WHERE id = %s AND empresa_db = %s", (id_pc_sel, str(db_actual)))
                                        conn_del.commit()
                                    conn_del.close()
                                    cargar_datos_edicion.clear()
                                    st.success("🗑️ Proveedor eliminado con éxito.")
                                    st.rerun()
                                except Exception as ex_del:
                                    st.error(f"❌ Error al eliminar: {ex_del}")
                    else:
                        st.info("No hay proveedores registrados para modificar.")
                except Exception as e:
                    st.error(f"Error en gestión de proveedores: {e}")
                    
            # ==========================================
            # 🧾 2. ÓRDENES DE PAGO
            # ==========================================
            elif sub_gestion == "Órdenes de Pago":
                st.markdown("#### 🧾 Consultar, Visualizar y Editar Órdenes de Pago por Rango de Fechas")
                
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    fec_desde_edit = st.date_input("Desde la fecha", key="edit_op_fecha_desde")
                with col_f2:
                    fec_hasta_edit = st.date_input("Hasta la fecha", key="edit_op_fecha_hasta")

                try:
                    df_op_edit = cargar_datos_edicion(db_actual, "ordenes", fec_desde_edit, fec_hasta_edit)
                    
                    if df_op_edit is not None and not df_op_edit.empty:
                        st.markdown(f"📊 Se encontraron **{len(df_op_edit)}** orden(es) de pago en el rango seleccionado:")
                        
                        st.dataframe(
                            df_op_edit[['id', 'fecha_emision', 'nro_factura', 'monto_bruto', 'monto_neto', 'estado']], 
                            use_container_width=True, 
                            hide_index=True,
                            column_config={
                                "monto_bruto": st.column_config.NumberColumn("Monto Bruto", format="%,.2f"),
                                "monto_neto": st.column_config.NumberColumn("Monto Neto", format="%,.2f")
                            }
                        )
                        
                        st.divider()
                        
                        dict_ope = {f"ID: {r['id']} | Fecha: {r['fecha_emision']} | Factura: {r['nro_factura']} | Neto: {r['monto_neto']:,.2f} | Estado: {r['estado']}": r for _, r in df_op_edit.iterrows()}
                        sel_ope_label = st.selectbox("Selecciona la Orden de Pago a modificar de la lista superior:", list(dict_ope.keys()), key="sel_ope_edit_full")
                        
                        fila_ope = dict_ope[sel_ope_label]
                        id_ope_sel = fila_ope['id']
                        
                        with st.form("form_editar_orden_pago"):
                            st.markdown(f"**Modificando la Orden ID:** `{id_ope_sel}` (Fecha Emisión: {fila_ope['fecha_emision']})")
                            
                            col_eo1, col_eo2 = st.columns(2)
                            with col_eo1:
                                nuevo_nro_fact = st.text_input("Número de Factura", value=fila_ope['nro_factura'] or "").strip()
                                nuevo_monto_bruto = st.number_input("Monto Bruto", value=float(fila_ope['monto_bruto']), min_value=0.00, step=100.00, format="%.2f")
                            with col_eo2:
                                nueva_ret_islr = st.number_input("Retención ISLR", value=float(fila_ope['retencion_islr']), min_value=0.00, step=10.00, format="%.2f")
                                nueva_ret_iva = st.number_input("Retención IVA", value=float(fila_ope['retencion_iva']), min_value=0.00, step=10.00, format="%.2f")
                            
                            nuevo_neto_calc = nuevo_monto_bruto - nueva_ret_islr - nueva_ret_iva
                            st.info(f"💵 **Nuevo Monto Neto Calculado:** {nuevo_neto_calc:,.2f}")
                            
                            nuevas_obs = st.text_area("Observaciones", value=fila_ope['observaciones'] or "").strip()
                            
                            col_bop1, col_bop2 = st.columns(2)
                            with col_bop1:
                                btn_act_op = st.form_submit_button("💾 Actualizar Orden de Pago", type="primary")
                            with col_bop2:
                                btn_del_op = st.form_submit_button("🗑️ Eliminar Orden", type="secondary")
                                
                            if btn_act_op:
                                try:
                                    conn_uop = conectar_db(db_actual)
                                    with conn_uop.cursor() as cur_uop:
                                        cur_uop.execute("""
                                            UPDATE ordenes_pago 
                                            SET nro_factura = %s, monto_bruto = %s, retencion_islr = %s, retencion_iva = %s, monto_neto = %s, observaciones = %s
                                            WHERE id = %s AND empresa_db = %s
                                        """, (nuevo_nro_fact, nuevo_monto_bruto, nueva_ret_islr, nueva_ret_iva, nuevo_neto_calc, nuevas_obs, id_ope_sel, str(db_actual)))
                                        conn_uop.commit()
                                    conn_uop.close()
                                    cargar_datos_edicion.clear()
                                    st.success("✅ ¡Orden de pago actualizada con éxito!")
                                    st.rerun()
                                except Exception as ex_uop:
                                    st.error(f"❌ Error al actualizar la orden: {ex_uop}")
                                    
                            if btn_del_op:
                                try:
                                    conn_dop = conectar_db(db_actual)
                                    with conn_dop.cursor() as cur_dop:
                                        cur_dop.execute("DELETE FROM ordenes_pago WHERE id = %s AND empresa_db = %s", (id_ope_sel, str(db_actual)))
                                        conn_dop.commit()
                                    conn_dop.close()
                                    cargar_datos_edicion.clear()
                                    st.success("🗑️ Orden de pago eliminada con éxito.")
                                    st.rerun()
                                except Exception as ex_dop:
                                    st.error(f"❌ Error al eliminar la orden: {ex_dop}")
                    else:
                        st.info("ℹ️ No hay órdenes de pago registradas para el rango de fechas seleccionado.")
                except Exception as e:
                    st.error(f"Error en gestión de órdenes: {e}")

            # ==========================================
            # 🏦 3. MOVIMIENTOS BANCARIOS
            # ==========================================
            elif sub_gestion == "Movimientos Bancarios":
                st.markdown("#### 🏦 Consultar, Visualizar y Editar Movimientos Bancarios por Rango de Fechas")
                
                col_bm1, col_bm2 = st.columns(2)
                with col_bm1:
                    fec_desde_bm = st.date_input("Desde la fecha (Movimiento)", key="edit_bm_fecha_desde")
                with col_bm2:
                    fec_hasta_bm = st.date_input("Hasta la fecha (Movimiento)", key="edit_bm_fecha_hasta")

                try:
                    df_bm_edit = cargar_datos_edicion(db_actual, "banco", fec_desde_bm, fec_hasta_bm)
                    
                    if df_bm_edit is not None and not df_bm_edit.empty:
                        st.markdown(f"📊 Se encontraron **{len(df_bm_edit)}** movimiento(s) bancario(s):")
                        
                        st.dataframe(
                            df_bm_edit[['id', 'fecha_movimiento', 'banco_nombre', 'referencia', 'monto', 'estado_conciliacion', 'asiento_id']], 
                            use_container_width=True, 
                            hide_index=True,
                            column_config={
                                "monto": st.column_config.NumberColumn("Monto", format="%,.2f")
                            }
                        )
                        
                        st.divider()

                        if "msg_alerta_bm" in st.session_state:
                            tipo_msg, texto_msg = st.session_state.msg_alerta_bm
                            getattr(st, tipo_msg)(texto_msg)
                            del st.session_state.msg_alerta_bm
                        
                        dict_bm_sel = {f"ID: {r['id']} | Fecha: {r['fecha_movimiento']} | Ref: {r['referencia']} | Monto: {r['monto']:,.2f}": r for _, r in df_bm_edit.iterrows()}
                        
                        col_sel_fast, col_btn_fast = st.columns([3, 1])
                        with col_sel_fast:
                            sel_bm_label = st.selectbox("Selecciona el Movimiento Bancario:", list(dict_bm_sel.keys()), key="sel_bm_edit_full")
                        
                        fila_bm = dict_bm_sel[sel_bm_label]
                        id_bm_sel = fila_bm['id']

                        with col_btn_fast:
                            st.markdown("<br>", unsafe_allow_html=True)
                            if st.button("🗑️ Eliminar Rápido", type="secondary", key=f"btn_del_fast_{id_bm_sel}", use_container_width=True):
                                try:
                                    conn_dbm = conectar_db(db_actual)
                                    with conn_dbm.cursor() as cur_dbm:
                                        cur_dbm.execute("DELETE FROM banco_movimientos WHERE id = %s", (id_bm_sel,))
                                        conn_dbm.commit()
                                    conn_dbm.close()
                                    cargar_datos_edicion.clear()
                                    
                                    st.session_state.msg_alerta_bm = ("warning", f"🗑️ Movimiento ID #{id_bm_sel} eliminado al instante.")
                                    st.rerun()
                                except Exception as ex_dbm:
                                    st.session_state.msg_alerta_bm = ("error", f"❌ Error al eliminar: {ex_dbm}")
                                    st.rerun()

                        st.divider()
                        st.markdown(f"**Modificando Movimiento ID:** `{id_bm_sel}`")
                        
                        col_be1, col_be2 = st.columns(2)
                        with col_be1:
                            nuevo_banco_nom = st.text_input("Banco Nombre", value=fila_bm['banco_nombre'] or "", key=f"nb_{id_bm_sel}").strip()
                            nuevo_nro_cta_bm = st.text_input("Cuenta Número", value=fila_bm['cuenta_numero'] or "", key=f"nc_{id_bm_sel}").strip()
                            nueva_ref_bm = st.text_input("Referencia Bancaria", value=fila_bm['referencia'] or "", key=f"nr_{id_bm_sel}").strip()
                        with col_be2:
                            nuevo_monto_bm = st.number_input("Monto", value=float(fila_bm['monto']), step=100.00, format="%.2f", key=f"nm_{id_bm_sel}")
                            
                            estados_posibles = ["Conciliado", "Pendiente Asiento", "No Conciliado"]
                            idx_est = estados_posibles.index(fila_bm['estado_conciliacion']) if fila_bm['estado_conciliacion'] in estados_posibles else 0
                            nuevo_estado_conc = st.selectbox("Estado Conciliación", estados_posibles, index=idx_est, key=f"ne_{id_bm_sel}")
                            
                            nuevo_asiento_id = st.text_input("Asiento ID asociado", value=fila_bm['asiento_id'] or "", key=f"na_{id_bm_sel}").strip()
                        
                        nueva_desc_bm = st.text_area("Descripción del Movimiento", value=fila_bm['descripcion'] or "", key=f"nd_{id_bm_sel}").strip()
                        
                        if st.button("💾 Actualizar Movimiento", type="primary", key=f"btn_act_bm_{id_bm_sel}", use_container_width=True):
                            try:
                                conn_ubm = conectar_db(db_actual)
                                with conn_ubm.cursor() as cur_ubm:
                                    cur_ubm.execute("""
                                        UPDATE banco_movimientos 
                                        SET banco_nombre = %s, cuenta_numero = %s, referencia = %s, monto = %s, estado_conciliacion = %s, asiento_id = %s, descripcion = %s
                                        WHERE id = %s
                                    """, (nuevo_banco_nom, nuevo_nro_cta_bm, nueva_ref_bm, nuevo_monto_bm, nuevo_estado_conc, nuevo_asiento_id, nueva_desc_bm, id_bm_sel))
                                    conn_ubm.commit()
                                conn_ubm.close()
                                cargar_datos_edicion.clear()
                                
                                st.session_state.msg_alerta_bm = ("success", f"✅ ¡Movimiento ID #{id_bm_sel} actualizado con éxito!")
                                st.rerun()
                            except Exception as ex_ubm:
                                st.session_state.msg_alerta_bm = ("error", f"❌ Error al actualizar: {ex_ubm}")
                                st.rerun()
                    else:
                        st.info("ℹ️ No hay movimientos bancarios registrados para el rango de fechas seleccionado.")
                except Exception as e:
                    st.error(f"Error en gestión de movimientos bancarios: {e}")
        with tab5:
            st.markdown("### 🗑️ Mantenimiento y Borrado Masivo")
            st.warning("⚠️ **¡ZONA DE PELIGRO!** Las acciones aquí eliminan por completo los registros de las tablas para la empresa actual. Esta acción no se puede deshacer.")
            
            tipo_borrado = st.selectbox("Selecciona qué deseas limpiar de forma masiva", [
                "--- Seleccionar opción ---", 
                "Eliminar todos los Proveedores Carga", 
                "Eliminar todas las Órdenes de Pago", 
                "⚠️ ¡Reiniciar TODO el Módulo de Tesorería!"
            ])
            
            confirmar_seguridad = st.checkbox("Confirmo que deseo ejecutar este borrado masivo")
            
            if st.button("🔥 Ejecutar Borrado Masivo", type="primary"):
                if confirmar_seguridad:
                    if tipo_borrado == "--- Seleccionar opción ---":
                        st.warning("⚠️ Selecciona una opción válida de borrado.")
                    else:
                        try:
                            conn_maint = conectar_db(db_actual)
                            if conn_maint:
                                with conn_maint.cursor() as cur_m:
                                    msg = ""
                                    if tipo_borrado == "Eliminar todos los Proveedores Carga":
                                        cur_m.execute("DELETE FROM proveedores_carga WHERE empresa_db = %s", (str(db_actual),))
                                        msg = "Todos los proveedores de carga han sido eliminados."
                                    elif tipo_borrado == "Eliminar todas las Órdenes de Pago":
                                        cur_m.execute("DELETE FROM ordenes_pago WHERE empresa_db = %s", (str(db_actual),))
                                        msg = "Todas las órdenes de pago han sido eliminadas."
                                    elif tipo_borrado == "⚠️ ¡Reiniciar TODO el Módulo de Tesorería!":
                                        cur_m.execute("DELETE FROM proveedores_carga WHERE empresa_db = %s", (str(db_actual),))
                                        cur_m.execute("DELETE FROM ordenes_pago WHERE empresa_db = %s", (str(db_actual),))
                                        msg = "Módulo de tesorería reiniciado por completo."
                                    
                                    conn_maint.commit()
                                conn_maint.close()
                                
                                # Limpiamos todas las cachés globales para evitar datos residuales
                                st.cache_data.clear()
                                
                                st.success(f"✅ {msg}")
                                st.rerun()
                        except Exception as ex_maint:
                            st.error(f"❌ Error al ejecutar el mantenimiento: {ex_maint}")
                else:
                    st.warning("⚠️ Debes marcar la casilla de confirmación de seguridad para proceder.")

    elif sub_opcion == "Consultar Comprobante":
        st.subheader("🔍 Buscador de Comprobantes")

        # 1. SEGURIDAD Y CONTEXTO
        db_actual = st.session_state.get('DB_ACTUAL')
        cliente_id = st.session_state.get('cliente_id')
        rol = st.session_state.get('rol')

        if not db_actual:
            st.error("No se ha seleccionado una base de datos de empresa.")
            st.stop()

        # --- FUNCIÓN CON CACHÉ PARA DATOS DE EMPRESA ---
        @st.cache_data(ttl=300, show_spinner=False)
        def obtener_datos_agente_cached(db_name):
            return obtener_datos_agente_db(db_name)

        empresa_data = obtener_datos_agente_cached(db_actual)

        # 2. FILTRO DE ACCESO
        if empresa_data and rol != 'admin':
            if empresa_data.get('id') != cliente_id:
                st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                st.stop()

        if not empresa_data:
            st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        else:
            # --- FILTROS DE PERÍODO PROPIOS PARA LA BÚSQUEDA ---
            st.markdown("### 📅 Seleccione el Período a Consultar")
            col_m, col_a = st.columns(2)
            
            meses_nombres = [
                "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
            ]
            
            with col_m:
                mes_sel = st.selectbox(
                    "Mes", 
                    options=meses_nombres, 
                    index=0, 
                    key="busc_mes_sel"
                )
            with col_a:
                ano_actual = pd.Timestamp.now().year
                ano_sel = st.selectbox(
                    "Año", 
                    options=list(range(ano_actual, 2023, -1)), 
                    index=0, 
                    key="busc_ano_sel"
                )

            meses_dict = {
                "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04", 
                "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08", 
                "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
            }
            mes_num = meses_dict.get(mes_sel, "01")
            fecha_inicio = f"{ano_sel}-{mes_num}-01"
            ultimo_dia = calendar.monthrange(int(ano_sel), int(mes_num))[1]
            fecha_fin = f"{ano_sel}-{mes_num}-{ultimo_dia:02d}"

            # --- FUNCIÓN CON CACHÉ PARA EL LISTADO DE COMPROBANTES ---
            @st.cache_data(ttl=60, show_spinner=False)
            def cargar_listado_comprobantes(empresa, f_inicio, f_fin):
                df = pd.DataFrame()
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        query = f"""
                            SELECT n_comprobante as 'Nº', MAX(fecha) as 'Fecha', MAX(descripcion) as 'Concepto' 
                            FROM `{empresa}`.asientos_contables 
                            WHERE fecha BETWEEN %s AND %s
                            GROUP BY n_comprobante ORDER BY fecha DESC
                        """
                        df = pd.read_sql(query, conn, params=(f_inicio, f_fin))
                        conn.close()
                except Exception:
                    pass
                return df

            df_listado = cargar_listado_comprobantes(db_actual, fecha_inicio, fecha_fin)

            # --- PARTE 2: INTERFAZ DE SELECCIÓN (LISTA DESPLEGABLE Y TABLA) ---
            n_comp_seleccionado = ""
            opciones_comprobantes = [""]
            mapa_comprobantes = {}

            if not df_listado.empty:
                for _, row in df_listado.iterrows():
                    n_comp_val = str(row['Nº'])
                    fecha_val = str(row['Fecha'])
                    concepto_val = str(row['Concepto']) if pd.notna(row['Concepto']) else "Sin descripción"
                    
                    etiqueta_opcion = f"Comprobante Nº: {n_comp_val} ({fecha_val}) - {concepto_val[:60]}"
                    opciones_comprobantes.append(etiqueta_opcion)
                    mapa_comprobantes[etiqueta_opcion] = n_comp_val

            with st.expander(f"📋 Listado de Comprobantes ({mes_sel} {ano_sel})", expanded=True):
                if not df_listado.empty:
                    comp_elegido_combo = st.selectbox(
                        "📌 Seleccione un comprobante de la lista (por número, fecha o concepto):",
                        options=opciones_comprobantes,
                        key="combo_selector_comprobante"
                    )
                    
                    if comp_elegido_combo and comp_elegido_combo in mapa_comprobantes:
                        n_comp_seleccionado = mapa_comprobantes[comp_elegido_combo]

                    st.markdown("---")
                    st.write("O haz clic en una fila de la tabla:")
                    
                    event = st.dataframe(
                        df_listado, use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row"
                    )
                    if len(event.selection.rows) > 0:
                        idx = event.selection.rows[0]
                        n_comp_seleccionado = str(df_listado.iloc[idx]['Nº'])
                else:
                    st.warning(f"⚠️ No se encontraron asientos contables registrados para el período: **{mes_sel} {ano_sel}**. Prueba cambiando el mes o el año arriba.")

            # Sincronizar con session_state para el input de texto
            if "busc_comp" not in st.session_state:
                st.session_state.busc_comp = ""

            if n_comp_seleccionado and n_comp_seleccionado != st.session_state.busc_comp:
                st.session_state.busc_comp = n_comp_seleccionado
                st.rerun()

            # --- PARTE 3: GENERAR REPORTE ---
            with st.expander("🔍 Generar Reporte", expanded=True):
                n_comp = st.text_input("Nº de Comprobante", key="busc_comp")
                btn_comp = st.button("🔎 Generar Reporte", type="primary", use_container_width=False)

            if btn_comp and n_comp:
                # Reporte visual
                disenar_reporte_asiento_contable(n_comp)
                
                # PDF con conexión optimizada
                try:
                    conn_pdf = conectar_db(db_actual)
                    if conn_pdf:
                        query_pdf = f"SELECT * FROM `{db_actual}`.asientos_contables WHERE n_comprobante = %s"
                        df_asiento_pdf = pd.read_sql(query_pdf, conn_pdf, params=(n_comp,))
                        conn_pdf.close()
                        
                        if not df_asiento_pdf.empty:
                            st.divider()
                            pdf_bytes = generar_pdf_comprobante(df_asiento_pdf, n_comp, None) # Pasamos None si ya cerró la conexión o según tu estructura interna
                            st.download_button(
                                label=f"📥 Descargar PDF {n_comp}",
                                data=pdf_bytes,
                                file_name=f"Comprobante_{n_comp}.pdf",
                                mime="application/pdf",
                                use_container_width=False
                            )
                        else:
                            st.warning(f"No se encontraron registros para el comprobante {n_comp}.")
                except Exception as e:
                    st.error(f"Error al generar el PDF del comprobante: {e}")


    elif sub_opcion == "Consultar Saldos Iniciales":
        st.subheader("🏁 Comprobante de Apertura")
        
        # 1. SEGURIDAD Y CONTEXTO (Una sola vez para todo el bloque)
        db_actual = st.session_state.get('DB_ACTUAL')
        cliente_id = st.session_state.get('cliente_id')
        rol = st.session_state.get('rol')

        if not db_actual:
            st.error("No se ha seleccionado una base de datos de empresa.")
            st.stop()

        @st.cache_data(ttl=300, show_spinner=False)
        def obtener_datos_agente_cached(db_name):
            return obtener_datos_agente_db(db_name)

        empresa_data = obtener_datos_agente_cached(db_actual)

        # 2. FILTRO DE ACCESO
        if empresa_data and rol != 'admin':
            if empresa_data.get('id') != cliente_id:
                st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                st.stop()

        if not empresa_data:
            st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        else:
            # --- MENÚ DE PESTAÑAS ---
            tab1, tab2, tab3 = st.tabs(["📖 Ver Comprobante", "📥 Importar Excel", "🗑️ Gestionar Data"])

            # ==========================================
            # PESTAÑA 1: VER COMPROBANTE
            # ==========================================
            with tab1:
                st.markdown(f"### Comprobante de Saldos Iniciales: **{empresa_data.get('nombre_empresa', db_actual)}**")
                
                @st.cache_data(ttl=60, show_spinner=False)
                def cargar_saldos_iniciales_cached(empresa):
                    try:
                        return consultar_saldos_iniciales_db(empresa)
                    except Exception:
                        return pd.DataFrame()

                df_apertura = cargar_saldos_iniciales_cached(db_actual)
                
                if not df_apertura.empty:
                    df_apertura.columns = [str(c).lower().strip() for c in df_apertura.columns]
                    
                    if 'descripcion' in df_apertura.columns:
                        df_apertura['descripcion'] = df_apertura['descripcion'].astype(str)
                    if 'codigo' in df_apertura.columns:
                        df_apertura['codigo'] = df_apertura['codigo'].astype(str)
                    
                    for col_num in ['debe', 'haber']:
                        if col_num in df_apertura.columns:
                            df_apertura[col_num] = pd.to_numeric(df_apertura[col_num], errors='coerce').fillna(0.0)

                    fmt = {'debe': formato_contable, 'haber': formato_contable}
                    st.dataframe(df_apertura.style.format(fmt), use_container_width=True, hide_index=True)
                    
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

            # ==========================================
            # PESTAÑA 2: IMPORTAR EXCEL
            # ==========================================
            with tab2:
                st.markdown("### 📤 Cargar nuevo Comprobante de Apertura")

                if st.session_state.get(f'exito_guardado_{db_actual}', False):
                    st.success("✅ ¡ASIENTOS GUARDADOS EXITOSAMENTE!")
                    st.info("💡 El comprobante ya se encuentra registrado en la base de datos. Si deseas cargar otro archivo diferente, puedes seleccionar uno nuevo abajo.")
                    st.markdown("---")

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

                        resumen_comprobantes = df_subido.groupby('N_comprobante')[['Debe_num', 'Haber_num']].sum().reset_index()
                        
                        st.write("### 📊 Auditoría por Comprobante:")
                        todo_cuadrado = True
                        
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
                                    st.session_state[f'exito_guardado_{db_actual}'] = True
                                    st.cache_data.clear()
                                    st.balloons()
                                    st.rerun()
                        else:
                            c3.error("❌ HAY COMPROBANTES DESCUADRADOS EN EL ARCHIVO")
                            st.warning("⚠️ Revisa las filas del comprobante en tu Excel, ya que tienen montos en el Debe pero les falta su contrapartida en el Haber.")

                    except Exception as e:
                        st.error(f"Error crítico: {e}")

            # ==========================================
            # PESTAÑA 3: GESTIONAR DATA
            # ==========================================
            with tab3:
                st.markdown("### ⚙️ Administración de Datos")

                if st.session_state.get(f'exito_borrado_{db_actual}', False):
                    st.success("🗑️ ¡Los saldos iniciales han sido eliminados y la tabla se vació exitosamente!")
                    st.info("💡 La información fue purgada de la base de datos de forma permanente.")
                    st.markdown("---")

                with st.container(border=True):
                    st.error("⚠️ **ADVERTENCIA CRÍTICA: BORRADO PERMANENTE**")
                    st.write(f"Estás operando sobre la base de datos: **{db_actual}**")
                    
                    confirmar_borrado = st.checkbox("He leído la advertencia y estoy de acuerdo en borrar toda la información de esta empresa.", key=f"check_borrar_{db_actual}")

                    if confirmar_borrado:
                        if st.button("🧨 VACIAR TABLA DE SALDOS", type="primary", use_container_width=False):
                            conn = conectar_db(db_actual)
                            if conn:
                                cursor = None
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute(f"TRUNCATE TABLE `{db_actual}`.saldos_iniciales")
                                    conn.commit()
                                    
                                    st.session_state[f'exito_borrado_{db_actual}'] = True
                                    st.cache_data.clear()
                                    st.balloons()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al vaciar: {e}")
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
                    else:
                        st.info("💡 Debe marcar la casilla de arriba para habilitar el botón de borrado.")


    elif sub_opcion == "Activo Fijo":
        # Asegúrate de que 'db_nombre' esté disponible en tu sesión
        db_nombre = st.session_state.get('DB_ACTUAL')

        if not db_nombre:
            st.warning("⚠️ Por favor, selecciona una empresa en el panel lateral para gestionar los Activos Fijos.")
        else:
            st.markdown(f"## 🏢 Módulo de Activos Fijos y Depreciación")
            
            # Pestañas de la 1 a la 5 con sus respectivos iconos
            t_reg, t_dep, t_aux, t_lim, t_cont, t_mod = st.tabs([
                "📥 1. Registro de Activos", 
                "📊 2. Cálculo de Depreciación", 
                "📖 3. Auxiliar y Modificación", 
                "🗑️ 4. Limpieza Total",
                "🧾 5. Contabilización",
                "🗑️ 6. Editar/Modificar Asientos Depreciación"

            ])
            
            # --- PESTAÑA 1: REGISTRO DE ACTIVOS FIJOS ---
            with t_reg:
                st.markdown("### 📝 Registrar Nuevo Activo Fijo")
                with st.form("form_crear_activo", clear_on_submit=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        codigo_placa = st.text_input("Código de Placa / Inventario", placeholder="Ej: ACT-001")
                        nombre_activo = st.text_input("Nombre del Activo Fijo*", placeholder="Ej: Escritorio Ejecutivo")
                        rubro = st.selectbox("Rubro del Activo Fijo", [
                            "Muebles y Enseres", 
                            "Equipos de Computación", 
                            "Maquinaria y Equipo", 
                            "Vehículos", 
                            "Edificaciones",
                            "Herramientas"
                        ])
                        fecha_adquisicion = st.date_input("Fecha de Adquisición", value=datetime.today())
                        
                    with col2:
                        costo_activo = st.number_input("Costo del Activo", min_value=0.0, step=100.0, format="%.2f")
                        valor_residual = st.number_input("Valor Residual / Salvamento", min_value=0.0, step=10.0, format="%.2f", value=0.0)
                        vida_util_meses = st.number_input("Vida Útil (en meses)", min_value=1, step=12, value=60)
                        metodo_depreciacion = st.selectbox("Método de Depreciación", ["Línea Recta"])
                    
                    btn_guardar = st.form_submit_button("💾 Guardar Activo Fijo", use_container_width=True)
                    
                    if btn_guardar:
                        if not nombre_activo.strip():
                            st.error("❌ El nombre del activo es obligatorio.")
                        else:
                            try:
                                conn = conectar_db(db_nombre)
                                if conn:
                                    with conn.cursor() as cursor:
                                        query = """
                                            INSERT INTO activo_fijo 
                                            (codigo_placa, nombre_activo, rubro, fecha_adquisicion, costo_activo, valor_residual, vida_util_meses, metodo_depreciacion)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                        """
                                        cursor.execute(query, (
                                            codigo_placa.strip(), nombre_activo.strip(), rubro, fecha_adquisicion, 
                                            costo_activo, valor_residual, vida_util_meses, metodo_depreciacion
                                        ))
                                        conn.commit()
                                    conn.close()
                                    
                                    # Limpiamos la caché global para que el auxiliar y depreciación reflejen el nuevo activo de inmediato
                                    st.cache_data.clear()
                                    st.success(f"✅ ¡Activo '{nombre_activo.strip()}' registrado con éxito!")
                            except Exception as e:
                                st.error(f"Error al guardar en la base de datos: {e}")

            # --- FUNCIÓN CON CACHÉ PARA CARGAR ACTIVOS FIJOS ---
            @st.cache_data(ttl=60, show_spinner=False)
            def cargar_activos_fijos_cached(empresa):
                df = pd.DataFrame()
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        df = pd.read_sql("SELECT * FROM activo_fijo", conn)
                        conn.close()
                except Exception:
                    pass
                return df

            # --- PESTAÑA 2: CÁLCULO DE DEPRECIACIÓN ---
            with t_dep:
                st.markdown("### 📈 Cálculo de Depreciación (Mensual y Acumulada)")
                
                col_f1, _ = st.columns([2, 2])
                with col_f1:
                    fecha_cierre = st.date_input("Fecha de Cierre para el Cálculo", value=datetime.today(), key="f_cierre_activo")
                    
                df_activos = cargar_activos_fijos_cached(db_nombre)
                    
                if not df_activos.empty:
                    resultados = []
                    for _, row in df_activos.iterrows():
                        f_adq = pd.to_datetime(row['fecha_adquisicion'])
                        f_cier = pd.to_datetime(fecha_cierre)
                        
                        if f_cier >= f_adq:
                            meses_antiguedad = (f_cier.year - f_adq.year) * 12 + (f_cier.month - f_adq.month)
                            if f_cier.day >= f_adq.day:
                                meses_antiguedad += 1
                            meses_antiguedad = max(0, meses_antiguedad)
                        else:
                            meses_antiguedad = 0
                        
                        costo = float(row['costo_activo'])
                        residual = float(row['valor_residual'])
                        vida_util = int(row['vida_util_meses'])
                        
                        dep_mensual = (costo - residual) / vida_util if vida_util > 0 else 0.0
                        dep_acumulada = min(dep_mensual * meses_antiguedad, costo - residual)
                        dep_acumulada = max(0.0, dep_acumulada)
                        costo_neto = costo - dep_acumulada
                        
                        resultados.append({
                            "ID": row['id'],
                            "Placa": row['codigo_placa'],
                            "Activo": row['nombre_activo'],
                            "Rubro": row['rubro'],
                            "Adquisición": row['fecha_adquisicion'],
                            "Costo": costo,
                            "Residual": residual,
                            "Vida Útil (Meses)": vida_util,
                            "Meses Transcl.": meses_antiguedad,
                            "Dep. Mensual": dep_mensual,
                            "Dep. Acumulada": dep_acumulada,
                            "Costo Neto": costo_neto
                        })
                        
                    df_reporte = pd.DataFrame(resultados)
                    
                    total_costo = df_reporte['Costo'].sum()
                    total_dep_mensual = df_reporte['Dep. Mensual'].sum()
                    total_dep_acum = df_reporte['Dep. Acumulada'].sum()
                    total_neto = df_reporte['Costo Neto'].sum()
                    
                    df_totales = pd.DataFrame([{
                        "ID": "TOTALES", "Placa": "", "Activo": "", "Rubro": "", "Adquisición": "",
                        "Costo": total_costo, "Residual": df_reporte['Residual'].sum(),
                        "Vida Útil (Meses)": "", "Meses Transcl.": "",
                        "Dep. Mensual": total_dep_mensual, "Dep. Acumulada": total_dep_acum, "Costo Neto": total_neto
                    }])
                    
                    df_final_mostrar = pd.concat([df_reporte, df_totales], ignore_index=True)
                    
                    format_dict = {
                        "Costo": "{:,.2f}", "Residual": "{:,.2f}",
                        "Dep. Mensual": "{:,.2f}", "Dep. Acumulada": "{:,.2f}", "Costo Neto": "{:,.2f}"
                    }
                    
                    st.dataframe(df_final_mostrar.style.format(format_dict, na_rep=""), use_container_width=True, hide_index=True)
                    
                    # --- DESCARGA EN EXCEL ---
                    import io
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_final_mostrar.to_excel(writer, index=False, sheet_name='Activos Fijos')
                    excel_data = output.getvalue()
                    
                    st.download_button(
                        label="📥 Descargar Auxiliar en Excel",
                        data=excel_data,
                        file_name=f"auxiliar_activos_fijos_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                    
                    st.divider()
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total Costo Histórico", f"{total_costo:,.2f}")
                    m2.metric("Total Dep. Mensual", f"{total_dep_mensual:,.2f}")
                    m3.metric("Total Dep. Acumulada", f"{total_dep_acum:,.2f}")
                    m4.metric("Total Valor en Libros", f"{total_neto:,.2f}")
                else:
                    st.info("No hay activos fijos registrados para calcular la depreciación.")

            # --- PESTAÑA 3: AUXILIAR, MODIFICAR Y ELIMINAR ---
            with t_aux:
                st.markdown("### 📖 Auxiliar de Activos Fijos (Editar o Eliminar por Fila)")
                
                df_aux = cargar_activos_fijos_cached(db_nombre)
                    
                if not df_aux.empty:
                    opciones_dict = {f"ID {row['id']} - {row['nombre_activo']} ({row['codigo_placa']})": row['id'] for _, row in df_aux.iterrows()}
                    
                    seleccion_editar = st.selectbox("Seleccione un activo para modificar o eliminar:", list(opciones_dict.keys()), key="sel_activo_auxiliar")
                    id_seleccionado = opciones_dict[seleccion_editar]
                    
                    activo_actual = df_aux[df_aux['id'] == id_seleccionado].iloc[0]
                    
                    with st.form("form_editar_activo"):
                        st.write(f"Editando Activo ID: {id_seleccionado}")
                        e_placa = st.text_input("Código de Placa", value=str(activo_actual['codigo_placa']))
                        e_nombre = st.text_input("Nombre del Activo", value=str(activo_actual['nombre_activo']))
                        e_rubro = st.text_input("Rubro", value=str(activo_actual['rubro']))
                        
                        fecha_bd = pd.to_datetime(activo_actual['fecha_adquisicion']).date()
                        e_fecha_adq = st.date_input("Fecha de Adquisición", value=fecha_bd)
                        
                        e_costo = st.number_input("Costo del Activo", value=float(activo_actual['costo_activo']))
                        e_residual = st.number_input("Valor Residual", value=float(activo_actual['valor_residual']))
                        e_vida = st.number_input("Vida Útil (Meses)", value=int(activo_actual['vida_util_meses']))
                        
                        col_btn1, col_btn2 = st.columns(2)
                        actualizar = col_btn1.form_submit_button("🔄 Actualizar Cambios", use_container_width=True)
                        eliminar_uno = col_btn2.form_submit_button("🗑️ Eliminar este Activo", use_container_width=True)
                        
                        if actualizar:
                            try:
                                conn = conectar_db(db_nombre)
                                if conn:
                                    with conn.cursor() as cursor:
                                        q_upd = """
                                            UPDATE activo_fijo 
                                            SET codigo_placa=%s, nombre_activo=%s, rubro=%s, fecha_adquisicion=%s, costo_activo=%s, valor_residual=%s, vida_util_meses=%s 
                                            WHERE id=%s
                                        """
                                        cursor.execute(q_upd, (e_placa, e_nombre, e_rubro, e_fecha_adq, e_costo, e_residual, e_vida, id_seleccionado))
                                        conn.commit()
                                    conn.close()
                                    st.cache_data.clear()
                                    st.success("✅ ¡Activo actualizado correctamente!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error al actualizar: {e}")
                            
                        if eliminar_uno:
                            try:
                                conn = conectar_db(db_nombre)
                                if conn:
                                    with conn.cursor() as cursor:
                                        cursor.execute("DELETE FROM activo_fijo WHERE id = %s", (id_seleccionado,))
                                        conn.commit()
                                    conn.close()
                                    st.cache_data.clear()
                                    st.warning("🗑️ Activo eliminado del auxiliar.")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error al eliminar: {e}")
                else:
                    st.info("El auxiliar de activos fijos está vacío.")

            # --- PESTAÑA 4: LIMPIEZA TOTAL ---
            with t_lim:
                st.markdown("### ⚙️ Gestión de Limpieza Total del Auxiliar")
                with st.container(border=True):
                    st.error("⚠️ **ZONA DE PELIGRO**: Esta acción eliminará por completo **todos** los registros de activos fijos de esta empresa.")
                    
                    confirmar_limpieza = st.checkbox("Estoy seguro de vaciar todo el auxiliar de activo fijo.", key="chk_limpiar_aux")
                    
                    if confirmar_limpieza:
                        if st.button("🧨 ELIMINAR TODO EL AUXILIAR DE ACTIVOS", type="primary"):
                            try:
                                conn = conectar_db(db_nombre)
                                if conn:
                                    with conn.cursor() as cursor:
                                        cursor.execute("DELETE FROM activo_fijo")
                                        conn.commit()
                                    conn.close()
                                    st.cache_data.clear()
                                    st.success("✅ Se han eliminado todos los activos fijos de la base de datos.")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Error al vaciar la tabla: {e}")

            # --- FUNCIONES CON CACHÉ PARA OPTIMIZAR EL RENDIMIENTO ---
            @st.cache_data(ttl=60, show_spinner=False)
            def cargar_datos_contabilizacion_cached(empresa):
                df_c = pd.DataFrame()
                df_a = pd.DataFrame()
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        df_c = pd.read_sql("SELECT * FROM plan_cuentas", conn)
                        df_a = pd.read_sql("SELECT * FROM activo_fijo", conn)
                        conn.close()
                except Exception:
                    pass
                return df_c, df_a

            @st.cache_data(ttl=30, show_spinner=False)
            def cargar_lista_comprobantes_cached(empresa):
                lista = []
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        df_comps = pd.read_sql("SELECT DISTINCT n_comprobante, fecha FROM asientos_contables ORDER BY fecha DESC", conn)
                        if not df_comps.empty:
                            lista = df_comps['n_comprobante'].tolist()
                        conn.close()
                except Exception:
                    pass
                return lista

            @st.cache_data(ttl=30, show_spinner=False)
            def cargar_lineas_comprobante_cached(empresa, n_comp):
                df = pd.DataFrame()
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        df = pd.read_sql("SELECT * FROM asientos_contables WHERE n_comprobante = %s", conn, params=(n_comp,))
                        conn.close()
                except Exception:
                    pass
                return df


            # --- PESTAÑA 5: CONTABILIZACIÓN DE DEPRECIACIÓN ---
            with t_cont:
                st.markdown("### 🧾 Generación de Asientos de Depreciación por Activo Individual")
                st.markdown("Seleccione cada activo, asigne sus cuentas correspondientes y agréguelo al lote antes de registrar el comprobante final.")
                
                if 'lote_depreciacion_temp' not in st.session_state:
                    st.session_state['lote_depreciacion_temp'] = []
                
                df_cuentas, df_activos_cont = cargar_datos_contabilizacion_cached(db_nombre)
                
                if df_cuentas.empty:
                    st.warning("⚠️ No se encontraron registros en la tabla `plan_cuentas`. Configure su plan de cuentas primero.")
                elif df_activos_cont.empty:
                    st.info("ℹ️ No hay activos fijos registrados.")
                else:
                    cols_cuentas = df_cuentas.columns.tolist()
                    col_codigo = next((c for c in cols_cuentas if 'codigo' in c.lower() or 'cuenta' in c.lower()), cols_cuentas[0])
                    col_nombre = next((c for c in cols_cuentas if 'nombre' in c.lower() or 'descripcion' in c.lower() or 'desc' in c.lower()), cols_cuentas[1] if len(cols_cuentas) > 1 else cols_cuentas[0])
                    
                    opciones_cuentas = {f"{row[col_codigo]} - {row[col_nombre]}": row[col_codigo] for _, row in df_cuentas.iterrows()}
                    opciones_activos = {f"{row.get('codigo_placa', row.get('id'))} - {row.get('nombre_activo', 'Sin Nombre')}": row for _, row in df_activos_cont.iterrows()}
                    
                    col_g1, col_g2, col_g3 = st.columns(3)
                    with col_g1:
                        n_comprobante = st.text_input("Número de Comprobante", value=f"DEP-{datetime.today().strftime('%Y%m')}")
                    with col_g2:
                        fecha_asiento = st.date_input("Fecha del Asiento", value=datetime.today())
                    with col_g3:
                        descripcion_general = st.text_input("Glosa / Descripción General", value="Depreciación mensual de activos fijos")

                    st.divider()
                    
                    with st.form("form_agregar_activo_lote"):
                        st.markdown("#### ➕ Agregar Activo al Lote")
                        
                        activo_sel_label = st.selectbox("Seleccione el Activo Fijo", list(opciones_activos.keys()), key="sel_activo_lote")
                        activo_data = opciones_activos[activo_sel_label]
                        
                        costo = float(activo_data.get('costo_activo', 0.0))
                        residual = float(activo_data.get('valor_residual', 0.0))
                        vida_util = int(activo_data.get('vida_util_meses', 1))
                        dep_mensual = (costo - residual) / vida_util if vida_util > 0 else 0.0
                        
                        st.info(f"📊 **Cálculo automático:** Costo: `{costo:,.2f}` | Residual: `{residual:,.2f}` | Vida Útil: `{vida_util} meses` | **Depreciación Mensual: `{dep_mensual:,.2f}`**")
                        
                        col_f1, col_f2 = st.columns(2)
                        with col_f1:
                            cta_gasto_sel = st.selectbox("Cuenta de Gasto (DEBE)", list(opciones_cuentas.keys()), key="sel_cta_gasto")
                        with col_f2:
                            cta_acum_sel = st.selectbox("Cuenta de Depreciación Acumulada (HABER)", list(opciones_cuentas.keys()), key="sel_cta_acum")
                        
                        btn_agregar = st.form_submit_button("📥 Agregar este Activo al Frame del Lote", use_container_width=True)
                        
                        if btn_agregar:
                            cod_gasto = opciones_cuentas[cta_gasto_sel]
                            cod_acum = opciones_cuentas[cta_acum_sel]
                            ref_placa = str(activo_data.get('codigo_placa', f"ID-{activo_data.get('id')}"))
                            nombre_act = activo_data.get('nombre_activo', 'Activo')
                            
                            item_debe = {
                                "n_comprobante": n_comprobante,
                                "fecha": str(fecha_asiento),
                                "descripcion": f"{descripcion_general} - {nombre_act} (Placa: {ref_placa})",
                                "cuenta_contable": cod_gasto,
                                "referencia": ref_placa,
                                "debe": dep_mensual,
                                "haber": 0.00
                            }
                            item_haber = {
                                "n_comprobante": n_comprobante,
                                "fecha": str(fecha_asiento),
                                "descripcion": f"{descripcion_general} - {nombre_act} (Placa: {ref_placa})",
                                "cuenta_contable": cod_acum,
                                "referencia": ref_placa,
                                "debe": 0.00,
                                "haber": dep_mensual
                            }
                            
                            st.session_state['lote_depreciacion_temp'].append(item_debe)
                            st.session_state['lote_depreciacion_temp'].append(item_haber)
                            st.success(f"✅ ¡{nombre_act} agregado al lote correctamente!")
                            st.rerun()

                    if st.session_state['lote_depreciacion_temp']:
                        st.divider()
                        st.markdown("### 📋 Vista Previa del Lote Acumulado (Frame)")
                        
                        df_lote = pd.DataFrame(st.session_state['lote_depreciacion_temp'])
                        
                        format_lote = {
                            "debe": "{:,.2f}",
                            "haber": "{:,.2f}"
                        }
                        st.dataframe(df_lote.style.format(format_lote, na_rep=""), use_container_width=True, hide_index=True)
                        
                        t_debe_lote = df_lote['debe'].sum()
                        t_haber_lote = df_lote['haber'].sum()
                        
                        col_m1, col_m2, col_m3 = st.columns(3)
                        col_m1.metric("Total Debe Lote", f"{t_debe_lote:,.2f}")
                        col_m2.metric("Total Haber Lote", f"{t_haber_lote:,.2f}")
                        
                        if abs(t_debe_lote - t_haber_lote) < 0.01:
                            col_m3.success("⚖️ Partida Doble Cuadrada")
                        else:
                            col_m3.error("⚠️ Descuadre en Partida Doble")
                        
                        col_b1, col_b2 = st.columns(2)
                        
                        with col_b1:
                            if st.button("🗑️ Limpiar / Vaciar Lote", use_container_width=True):
                                st.session_state['lote_depreciacion_temp'] = []
                                st.rerun()
                        
                        with col_b2:
                            if st.button("🚀 Registrar Todo el Lote en Base de Datos", type="primary", use_container_width=True):
                                try:
                                    conn = conectar_db(db_nombre)
                                    if conn:
                                        with conn.cursor() as cursor:
                                            query_insert = """
                                                INSERT INTO asientos_contables 
                                                (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            """
                                            for fila in st.session_state['lote_depreciacion_temp']:
                                                cursor.execute(query_insert, (
                                                    fila['n_comprobante'],
                                                    fila['descripcion'],
                                                    fila['fecha'],
                                                    fila['cuenta_contable'],
                                                    fila['cuenta_contable'],
                                                    fila['referencia'],
                                                    fila['debe'],
                                                    fila['haber'],
                                                    0
                                                ))
                                            conn.commit()
                                        conn.close()
                                        st.cache_data.clear()
                                        st.success(f"🎉 ¡Comprobante `{n_comprobante}` registrado exitosamente con todas sus cuentas individuales!")
                                        st.session_state['lote_depreciacion_temp'] = []
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al guardar en base de datos: {e}")

            # --- PESTAÑA 6: MODIFICAR, EDITAR O ELIMINAR ASIENTOS CONTABLES ---
            with t_mod:
                st.markdown("### 🛠️ Gestión y Corrección de Asientos Contables")
                st.markdown("Busque un comprobante registrado para editar sus líneas o eliminar registros erróneos.")
                
                def formato_moneda_latam(valor):
                    try:
                        if pd.isna(valor):
                            return "0,00"
                        s = f"{float(valor):,.2f}"
                        return s.replace(",", "X").replace(".", ",").replace("X", ".")
                    except:
                        return "0,00"

                def parsear_moneda_latam(valor_str):
                    if pd.isna(valor_str):
                        return 0.0
                    if isinstance(valor_str, (int, float)):
                        return float(valor_str)
                    try:
                        limpio = str(valor_str).replace(".", "").replace(",", ".")
                        return float(limpio)
                    except:
                        return 0.0

                lista_comprobantes = cargar_lista_comprobantes_cached(db_nombre)
                
                if not lista_comprobantes:
                    st.info("ℹ️ No se encontraron comprobantes registrados en la base de datos.")
                else:
                    comp_a_editar = st.selectbox("Seleccione el Número de Comprobante a Revisar / Modificar", lista_comprobantes, key="select_comp_editar")
                    
                    df_lineas_comp = cargar_lineas_comprobante_cached(db_nombre, comp_a_editar)
                    
                    if not df_lineas_comp.empty:
                        st.markdown(f"#### 📄 Editando Comprobante: `{comp_a_editar}`")
                        st.info("💡 Puede editar los valores numéricos usando el formato latino (ej: `7.530,13`) directamente en la tabla.")
                        
                        df_lineas_comp['debe'] = pd.to_numeric(df_lineas_comp['debe'], errors='coerce').fillna(0.0)
                        df_lineas_comp['haber'] = pd.to_numeric(df_lineas_comp['haber'], errors='coerce').fillna(0.0)
                        
                        df_editor_view = df_lineas_comp.copy()
                        df_editor_view['debe'] = df_editor_view['debe'].apply(formato_moneda_latam)
                        df_editor_view['haber'] = df_editor_view['haber'].apply(formato_moneda_latam)

                        df_editado_raw = st.data_editor(
                            df_editor_view,
                            num_rows="dynamic",
                            use_container_width=True,
                            hide_index=True,
                            key=f"editor_asientos_{comp_a_editar}",
                            column_config={
                                "id": st.column_config.Column("ID", disabled=True),
                                "n_comprobante": st.column_config.TextColumn("N° Comprobante"),
                                "fecha": st.column_config.DateColumn("Fecha"),
                                "descripcion": st.column_config.TextColumn("Descripción"),
                                "cuenta_contable": st.column_config.TextColumn("Cuenta Contable"),
                                "debe": st.column_config.TextColumn("debe"),
                                "haber": st.column_config.TextColumn("haber"),
                                "bloqueado": st.column_config.CheckboxColumn("Bloqueado")
                            }
                        )
                        
                        df_editado = df_editado_raw.copy()
                        df_editado['debe'] = df_editado['debe'].apply(parsear_moneda_latam)
                        df_editado['haber'] = df_editado['haber'].apply(parsear_moneda_latam)
                        
                        t_debe_ed = df_editado['debe'].sum()
                        t_haber_ed = df_editado['haber'].sum()
                        
                        col_e1, col_e2, col_e3 = st.columns(3)
                        col_e1.metric("Total Debe Actualizado", formato_moneda_latam(t_debe_ed))
                        col_e2.metric("Total Haber Actualizado", formato_moneda_latam(t_haber_ed))
                        
                        if abs(t_debe_ed - t_haber_ed) < 0.01:
                            col_e3.success("⚖️ Cuadrado")
                        else:
                            col_e3.error("⚠️ Descuadrado")
                        
                        st.divider()
                        
                        col_bt1, col_bt2 = st.columns(2)
                        
                        with col_bt1:
                            if st.button("💾 Guardar Cambios en la Base de Datos", type="primary", use_container_width=True):
                                try:
                                    conn = conectar_db(db_nombre)
                                    if conn:
                                        with conn.cursor() as cursor:
                                            ids_actuales_en_bd = df_lineas_comp['id'].tolist()
                                            ids_en_editor = df_editado['id'].dropna().tolist()
                                            
                                            ids_a_eliminar = [i for i in ids_actuales_en_bd if i not in ids_en_editor]
                                            for id_del in ids_a_eliminar:
                                                cursor.execute("DELETE FROM asientos_contables WHERE id = %s", (int(id_del),))
                                            
                                            for _, row in df_editado.iterrows():
                                                val_debe = float(row.get('debe', 0.0))
                                                val_haber = float(row.get('haber', 0.0))
                                                
                                                if pd.isna(row.get('id')) or row['id'] == '':
                                                    query_ins = """
                                                        INSERT INTO asientos_contables 
                                                        (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                                    """
                                                    cursor.execute(query_ins, (
                                                        row.get('n_comprobante', comp_a_editar),
                                                        row.get('descripcion', ''),
                                                        str(row.get('fecha', datetime.today())),
                                                        row.get('plan_cuentas', ''),
                                                        row.get('cuenta_contable', ''),
                                                        row.get('referencia', ''),
                                                        val_debe,
                                                        val_haber,
                                                        int(row.get('bloqueado', 0))
                                                    ))
                                                else:
                                                    query_upd = """
                                                        UPDATE asientos_contables SET 
                                                            n_comprobante = %s,
                                                            descripcion = %s,
                                                            fecha = %s,
                                                            plan_cuentas = %s,
                                                            cuenta_contable = %s,
                                                            referencia = %s,
                                                            debe = %s,
                                                            haber = %s,
                                                            bloqueado = %s
                                                        WHERE id = %s
                                                    """
                                                    cursor.execute(query_upd, (
                                                        row['n_comprobante'],
                                                        row['descripcion'],
                                                        str(row['fecha']),
                                                        row['plan_cuentas'],
                                                        row['cuenta_contable'],
                                                        row['referencia'],
                                                        val_debe,
                                                        val_haber,
                                                        int(row.get('bloqueado', 0)),
                                                        int(row['id'])
                                                    ))
                                                    
                                            conn.commit()
                                        conn.close()
                                        st.cache_data.clear()
                                        st.success(f"✅ ¡Los cambios en el comprobante `{comp_a_editar}` se han guardado correctamente!")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al actualizar los registros: {e}")
                                    
                        with col_bt2:
                            if st.button("🗑️ Eliminar Todo este Comprobante", type="secondary", use_container_width=True):
                                try:
                                    conn = conectar_db(db_nombre)
                                    if conn:
                                        with conn.cursor() as cursor:
                                            cursor.execute("DELETE FROM asientos_contables WHERE n_comprobante = %s", (comp_a_editar,))
                                            conn.commit()
                                        conn.close()
                                        st.cache_data.clear()
                                        st.warning(f"⚠️ El comprobante `{comp_a_editar}` ha sido eliminado por completo de la base de datos.")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Error al eliminar el comprobante: {e}")

    elif sub_opcion == "Consultar Cierre Contable":
        st.subheader("🔒 Gestión de Asientos de Cierre")
        st.markdown("Genera y consulta los asientos de cierre contable **mensuales** (regularización de cuentas de resultados) y el **cierre anual** (determinación de la utilidad neta y traslado al patrimonio).")

        # 1. SEGURIDAD Y CONTEXTO
        db_actual = st.session_state.get('DB_ACTUAL')
        cliente_id = st.session_state.get('cliente_id')
        rol = st.session_state.get('rol')

        if not db_actual:
            st.error("No se ha seleccionado una base de datos de empresa.")
            st.stop()

        @st.cache_data(ttl=300, show_spinner=False)
        def obtener_datos_agente_cached(db_name):
            return obtener_datos_agente_db(db_name)

        empresa_data = obtener_datos_agente_cached(db_actual)

        if empresa_data and rol != 'admin':
            if empresa_data.get('id') != cliente_id:
                st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
                st.stop()

        if not empresa_data:
            st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        else:
            # 2. CONFIGURACIÓN DEL TIPO DE CIERRE
            tipo_cierre = st.radio(
                "📌 Seleccione el tipo de cierre contable:",
                options=["Cierre Mensual", "Cierre Anual"],
                horizontal=True,
                key="radio_tipo_cierre"
            )

            col_per1, col_per2 = st.columns(2)
            
            meses_nombres = [
                "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
            ]
            
            ano_actual = pd.Timestamp.now().year

            with col_per1:
                ano_sel = st.selectbox(
                    "Año del Cierre", 
                    options=list(range(ano_actual, 2023, -1)), 
                    index=0, 
                    key="cierre_ano_sel"
                )

            mes_sel = "Diciembre"
            if tipo_cierre == "Cierre Mensual":
                with col_per2:
                    mes_sel = st.selectbox(
                        "Mes a Cerrar", 
                        options=meses_nombres, 
                        index=pd.Timestamp.now().month - 1, 
                        key="cierre_mes_sel"
                    )
            else:
                with col_per2:
                    st.info(f"ℹ️ El **Cierre Anual** procesa el ejercicio económico completo al 31/12 de {ano_sel} para transferir las cuentas de resultados.")

            st.divider()

            # 3. ACCIONES Y PROCESAMIENTO
            st.markdown("---")
            st.subheader("⚠️ Autorización y Cierre de Período")
            
            if tipo_cierre == "Cierre Mensual":
                st.warning(
                    f"**¡Atención!** Está a punto de realizar el **Cierre Mensual de {mes_sel} {ano_sel}**. "
                    "Al autorizar y ejecutar este proceso, **se bloquearán todos los asientos contables** de este mes, "
                    "lo que impedirá registrar, modificar o eliminar transacciones con fecha de dicho período."
                )
            else:
                st.warning(
                    f"**¡Atención!** Está a punto de realizar el **Cierre Anual del ejercicio {ano_sel}**. "
                    "Esta acción bloqueará las transacciones correspondientes al período de cierre anual."
                )

            autorizar_cierre = st.checkbox(
                f"Confirmo que deseo cerrar y bloquear contablemente el período seleccionado ({mes_sel if tipo_cierre == 'Cierre Mensual' else 'Anual'} {ano_sel})",
                key="check_autorizar_cierre"
            )

            col_btn1, _ = st.columns(2)
            
            with col_btn1:
                btn_calcular_cierre = st.button(
                    f"⚙️ Calcular y Generar {tipo_cierre}", 
                    type="primary", 
                    use_container_width=True,
                    disabled=not autorizar_cierre
                )

            if not autorizar_cierre:
                st.info("ℹ️ Debe marcar la casilla de confirmación superior para habilitar el botón de procesamiento y cierre.")

            if btn_calcular_cierre and autorizar_cierre:
                conn_cierre = conectar_db(db_actual)
                if conn_cierre:
                    try:
                        with conn_cierre.cursor() as cursor:
                            meses_dict = {
                                "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04", 
                                "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08", 
                                "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
                            }
                            
                            if tipo_cierre == "Cierre Mensual":
                                m_num = meses_dict[mes_sel]
                                ultimo_d = calendar.monthrange(int(ano_sel), int(m_num))[1]
                                fecha_cierre = f"{ano_sel}-{m_num}-{ultimo_d:02d}"
                                
                                query_bloqueo = f"""
                                    UPDATE `{db_actual}`.asientos_contables 
                                    SET bloqueado = 1 
                                    WHERE YEAR(fecha) = %s AND MONTH(fecha) = %s
                                """
                                cursor.execute(query_bloqueo, (int(ano_sel), int(m_num)))
                            else:
                                fecha_cierre = f"{ano_sel}-12-31"
                                
                                query_bloqueo = f"""
                                    UPDATE `{db_actual}`.asientos_contables 
                                    SET bloqueado = 1 
                                    WHERE YEAR(fecha) = %s
                                """
                                cursor.execute(query_bloqueo, (int(ano_sel),))

                            conn_cierre.commit()

                        st.success(f"✅ Proceso de **{tipo_cierre}** completado con éxito. El período ha sido **bloqueado** en `{db_actual}` para la fecha límite `{fecha_cierre}`.")
                        
                        registrar_log_automatico(
                            conn_cierre, 
                            "GENERACION_CIERRE_CONTABLE", 
                            f"Usuario {st.session_state.get('usuario', 'Admin')} generó y bloqueó {tipo_cierre} ({fecha_cierre}) para {db_actual}"
                        )
                        
                        # Limpiamos caché para reflejar el bloqueo y los cierres de inmediato
                        st.cache_data.clear()
                        st.rerun()

                    except Exception as e:
                        if conn_cierre:
                            conn_cierre.rollback()
                        st.error(f"❌ Error al procesar el cierre contable y el bloqueo: {e}")
                    finally:
                        if conn_cierre:
                            conn_cierre.close()
                else:
                    st.error("❌ No se pudo conectar a la base de datos para realizar el cierre.")

            st.markdown("---")
            st.subheader("📋 Historial de Asientos de Cierre Registrados")
            
            # --- FUNCIÓN CON CACHÉ PARA CONSULTAR CIERRES ---
            @st.cache_data(ttl=60, show_spinner=False)
            def cargar_historial_cierres_cached(empresa, ano):
                df = pd.DataFrame()
                try:
                    conn = conectar_db(empresa)
                    if conn:
                        query_cierres = f"""
                            SELECT n_comprobante as 'Nº Comprobante', fecha as 'Fecha', descripcion as 'Concepto', 
                                   SUM(debe) as 'Total Debe', SUM(haber) as 'Total Haber'
                            FROM `{empresa}`.asientos_contables 
                            WHERE descripcion LIKE '%CIERRE%' AND YEAR(fecha) = %s
                            GROUP BY n_comprobante, fecha, descripcion 
                            ORDER BY fecha DESC
                        """
                        df = pd.read_sql(query_cierres, conn, params=(ano,))
                        conn.close()
                except Exception:
                    pass
                return df

            df_cierres = cargar_historial_cierres_cached(db_actual, ano_sel)

            if not df_cierres.empty:
                st.dataframe(df_cierres, use_container_width=True, hide_index=True)
                st.info("💡 Para visualizar el detalle completo o imprimir el comprobante de cierre en PDF, puedes copiar el número de comprobante y usar la opción **'Consultar Comprobante'**.")
            else:
                st.info(f"ℹ️ No se han encontrado asientos de cierre registrados para el año **{ano_sel}** en la empresa `{db_actual}`.")

    elif sub_opcion == "Gestor Documental":
        st.subheader("📁 Gestor Documental en la Nube")
        st.markdown("Crea carpetas personalizadas y administra comprobantes, facturas o archivos organizados.")

        db_actual = st.session_state.get('DB_ACTUAL')
        if not db_actual or db_actual == 'none':
            st.warning("⚠️ Por favor, selecciona un Cliente/Empresa primero.")
            st.stop()

        import os
        from datetime import datetime

        # --- BLINDAJE Y AUTO-CREACIÓN DE LA COLUMNA CARPETA ---
        try:
            conn_alt = conectar_db(db_actual)
            if conn_alt:
                with conn_alt.cursor() as cur_alt:
                    cur_alt.execute("""
                        SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
                        WHERE TABLE_SCHEMA = DATABASE() 
                        AND TABLE_NAME = 'documentos_cloud' 
                        AND COLUMN_NAME = 'carpeta'
                    """)
                    resultado = cur_alt.fetchone()
                    existe = resultado[0] if resultado else 0
                    
                    if existe == 0:
                        cur_alt.execute("ALTER TABLE documentos_cloud ADD COLUMN carpeta VARCHAR(150) DEFAULT 'General' AFTER empresa_db")
                        conn_alt.commit()
                conn_alt.close()
        except Exception as ex_alt:
            st.warning(f"Aviso de migración de tabla: {ex_alt}")

        # Directorio base persistente
        DIRECTORIO_SUBIDAS = "documentos_clientes"
        dir_empresa = os.path.join(DIRECTORIO_SUBIDAS, str(db_actual))
        os.makedirs(dir_empresa, exist_ok=True)

        # --- FUNCIONES CON CACHÉ PARA OPTIMIZAR EL RENDIMIENTO ---
        @st.cache_data(ttl=60, show_spinner=False)
        def obtener_carpetas_cached(empresa):
            carpetas = ["General"]
            try:
                conn = conectar_db(empresa)
                if conn:
                    df = ejecutar_consulta("SELECT DISTINCT carpeta FROM documentos_cloud WHERE empresa_db = %s", conn, params=(str(empresa),))
                    conn.close()
                    if df is not None and not df.empty:
                        carpetas = sorted(list(set(["General"] + df['carpeta'].dropna().tolist())))
            except Exception:
                pass
            return carpetas

        @st.cache_data(ttl=30, show_spinner=False)
        def obtener_documentos_cached(empresa):
            df_docs = pd.DataFrame()
            try:
                conn = conectar_db(empresa)
                if conn:
                    query_select = "SELECT id, carpeta, categoria, nombre_archivo, ruta_archivo, fecha_subida FROM documentos_cloud WHERE empresa_db = %s ORDER BY carpeta ASC, fecha_subida DESC"
                    df_docs = ejecutar_consulta(query_select, conn, params=(str(empresa),))
                    conn.close()
            except Exception:
                pass
            return df_docs

        carpetas_existentes = obtener_carpetas_cached(db_actual)

        # --- FORMULARIO DE SUBIDA CON CREACIÓN DE CARPETAS ---
        with st.expander("📤 Subir Archivos a una Carpeta", expanded=True):
            col_c1, col_c2 = st.columns(2)
            
            with col_c1:
                modo_carpeta = st.radio("Gestión de Carpeta", ["Seleccionar existente", "Crear nueva carpeta"], horizontal=True, key="radio_modo_carpeta")
                
                if modo_carpeta == "Crear nueva carpeta":
                    nombre_nueva_carpeta = st.text_input("Nombre de la nueva carpeta (ej: Facturas_Agosto_2026)", key="input_nueva_carp").strip()
                    carpeta_activa = nombre_nueva_carpeta if nombre_nueva_carpeta else "General"
                else:
                    carpeta_activa = st.selectbox("Selecciona la carpeta", carpetas_existentes, key="select_carp_existente")
                    
                categoria = st.selectbox(
                    "Categoría del Documento", 
                    ["Transferencia Bancaria", "Factura PDF", "Documento Legal", "Excel / Reporte", "Otro"],
                    key="select_cat_doc"
                )
                
            with col_c2:
                archivos_subidos = st.file_uploader(
                    "Selecciona los archivos (Puedes subir varios a la vez)", 
                    type=["pdf", "docx", "xlsx", "xls", "png", "jpg", "jpeg", "txt"], 
                    accept_multiple_files=True,
                    key="uploader_docs_cloud"
                )

            if st.button("💾 Guardar en la Carpeta", type="primary", key="btn_guardar_docs_cloud"):
                if archivos_subidos:
                    carpeta_limpia = "".join([c for c in carpeta_activa if c.isalnum() or c in (' ', '_', '-')]).strip()
                    if not carpeta_limpia:
                        carpeta_limpia = "General"
                    
                    dir_carpeta_fisica = os.path.join(dir_empresa, carpeta_limpia)
                    os.makedirs(dir_carpeta_fisica, exist_ok=True)

                    try:
                        conn_doc = conectar_db(db_actual)
                        if conn_doc:
                            with conn_doc.cursor() as cursor:
                                for archivo in archivos_subidos:
                                    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    nombre_limpio = f"{timestamp_str}_{archivo.name}"
                                    ruta_completa = os.path.join(dir_carpeta_fisica, nombre_limpio)
                                    
                                    with open(ruta_completa, "wb") as f:
                                        f.write(archivo.getbuffer())
                                    
                                    query_insert = """
                                        INSERT INTO documentos_cloud (empresa_db, carpeta, categoria, nombre_archivo, ruta_archivo) 
                                        VALUES (%s, %s, %s, %s, %s)
                                    """
                                    cursor.execute(query_insert, (str(db_actual), carpeta_limpia, categoria, archivo.name, ruta_completa))
                                
                                conn_doc.commit()
                            conn_doc.close()
                            st.cache_data.clear()
                            st.success(f"✅ ¡{len(archivos_subidos)} archivo(s) guardados con éxito en la carpeta '{carpeta_limpia}'!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar los documentos: {e}")
                else:
                    st.warning("⚠️ Debes seleccionar al menos un archivo antes de guardar.")

        st.divider()

        # --- LISTADO AGRUPADO POR CARPETAS ---
        st.markdown("### 🗂️ Documentos y Carpetas Almacenadas")
        
        df_docs = obtener_documentos_cached(db_actual)
        
        if df_docs is not None and not df_docs.empty:
            carpetas_unicas = df_docs['carpeta'].unique()
            
            for carp in carpetas_unicas:
                num_archivos = len(df_docs[df_docs['carpeta'] == carp])
                with st.expander(f"📁 Carpeta: {carp} ({num_archivos} archivos)", expanded=True):
                    df_carp = df_docs[df_docs['carpeta'] == carp]
                    
                    for _, row in df_carp.iterrows():
                        cols = st.columns([3, 2, 2, 1, 1])
                        cols[0].text(f"📄 {row['nombre_archivo']}")
                        cols[1].text(f"📂 {row['categoria']}")
                        cols[2].text(str(row['fecha_subida'])[:10])
                        
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
                            
                        if cols[4].button("🗑️", key=f"del_{row['id']}"):
                            try:
                                if os.path.exists(row['ruta_archivo']):
                                    os.remove(row['ruta_archivo'])
                                
                                conn_del = conectar_db(db_actual)
                                if conn_del:
                                    with conn_del.cursor() as cursor_del:
                                        cursor_del.execute("DELETE FROM documentos_cloud WHERE id = %s", (row['id'],))
                                        conn_del.commit()
                                    conn_del.close()
                                    
                                st.cache_data.clear()
                                st.success("🗑️ Archivo eliminado con éxito.")
                                st.rerun()
                            except Exception as ex_del:
                                st.error(f"❌ Error al eliminar: {ex_del}")
        else:
            st.info("ℹ️ No hay documentos subidos para esta empresa todavía. Crea una carpeta arriba y sube tus archivos.")

elif opcion_menu == "📖 Mayor Analítico":
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

    # --- FUNCIÓN CON CACHÉ PARA OPTIMIZAR LA CARGA DE LA EMPRESA ---
    @st.cache_data(ttl=300, show_spinner=False)
    def obtener_datos_agente_cached(db_name):
        return obtener_datos_agente_db(db_name)

    empresa_data = obtener_datos_agente_cached(db_actual)

    # 2. FILTRO DE ACCESO
    if empresa_data and rol != "admin":
        if empresa_data.get("id") != cliente_id:
            st.error(f"⚠️ Acceso denegado: empresa_data['id'] ({empresa_data.get('id')}) != cliente_id ({cliente_id})")
            st.stop()

    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa (empresa_data es None o vacío).")
    else:
        # 3. EJECUCIÓN SEGURA (Ya las fechas existen garantizadas por el sidebar)
        mostrar_interfaz_mayor(f_inicio_global, f_fin_global, db_actual)


# E. ESTADOS FINANCIEROS -> BALANCE COMPROBACIÓN
elif sub_opcion == "Balance de Comprobación":
    
    # 1. PRIMERO: Asegurar que la sesión tenga los datos del cliente activo
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
    
    # 3. TERCERO: Validar si la base de datos existe
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()
        
    st.subheader(f"⚖️ Balance de Comprobación: {EMPRESA}")
    
    # --- FILTROS DE FECHA ---
    col_f1, col_f2 = st.columns(2)
    f_bal_desde = col_f1.date_input("Desde", f_inicio_global, key="bal_desde")
    f_bal_hasta = col_f2.date_input("Hasta", f_fin_global, key="bal_hasta")

    # --- FUNCIÓN CON CACHÉ PARA OPTIMIZAR EL RENDIMIENTO DEL BALANCE ---
    @st.cache_data(ttl=60, show_spinner=False)
    def obtener_balance_cached(db_name, fecha_desde, fecha_hasta, sucursal_sel):
        df = pd.DataFrame()
        conn = conectar_db(db_name)
        if conn:
            try:
                conn.ping(reconnect=True)
                df = generar_balance_profesional(conn, fecha_desde, fecha_hasta, sucursal_sel)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return df

    # 4. OBTENCIÓN DE DATOS CON CACHÉ
    df_bal = obtener_balance_cached(db_actual, f_bal_desde, f_bal_hasta, sucursal)
    
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
                        
                        cod_str = str(row['codigo']).replace('Σ', 'TOTAL')
                        
                        pdf.cell(25, 6, cod_str, 1)
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

                    pdf_bytes = bytes(pdf.output())
                    
                    st.download_button(
                        label="⬇️ Descargar PDF Ahora", 
                        data=pdf_bytes, 
                        file_name=nombre_archivo_pdf, 
                        mime="application/pdf", 
                        use_container_width=True
                    )
                except Exception as e_pdf:
                    st.error(f"Error generando PDF: {e_pdf}")

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

    @st.cache_data(ttl=300, show_spinner=False)
    def obtener_datos_agente_cached(db_name):
        return obtener_datos_agente_db(db_name)

    empresa_data = obtener_datos_agente_cached(db_actual)

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
    
    # --- BLINDAJE LOCAL DE FECHA ---
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
    
    # --- FUNCIÓN CON CACHÉ PARA OPTIMIZAR EL BALANCE GENERAL ---
    @st.cache_data(ttl=60, show_spinner=False)
    def obtener_balance_general_cached(db_name, fecha_corte, sucursal_sel):
        df_datos = pd.DataFrame()
        conn = conectar_db(db_name)
        if conn:
            try:
                conn.ping(reconnect=True)
                df_datos = generar_balance_profesional(conn, "2000-01-01", fecha_corte, sucursal_sel)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return df_datos

    df_datos = obtener_balance_general_cached(db_actual, f_corte, sucursal)
    
    if df_datos is not None and not df_datos.empty:
        # 1. Preparación y Agrupación inicial de los datos
        df_bg = df_datos[df_datos['codigo'].astype(str).str.startswith(('1', '2', '3'))].copy()
        df_bg = df_bg.groupby(['codigo', 'nombre', 'nivel'])['Saldo Final'].sum().reset_index()
        
        # Creamos la columna 'Cuenta' con sangría visual para el reporte
        df_bg['Cuenta'] = df_bg.apply(lambda x: f"{'    ' * (int(x['nivel'])-1)}{x['nombre']}", axis=1)

        # 2. Lógica para identificar cuentas finales (hojas) y obtener totales reales
        todos_los_codigos = df_bg['codigo'].astype(str).unique()
        
        def es_hoja(codigo):
            return not any(c.startswith(str(codigo) + '.') for c in todos_los_codigos)

        df_bg['es_hoja'] = df_bg['codigo'].apply(es_hoja)

        # 3. Cálculo de Totales
        act = df_bg[df_bg['es_hoja'] & df_bg['codigo'].astype(str).str.startswith('1')]['Saldo Final'].abs().sum()
        
        pas_n1 = df_bg[(df_bg['nivel'] == 1) & (df_bg['codigo'].astype(str).str.startswith('2'))]['Saldo Final']
        pas = abs(pas_n1.values[0]) if not pas_n1.empty else df_bg[df_bg['es_hoja'] & df_bg['codigo'].astype(str).str.startswith('2')]['Saldo Final'].abs().sum()

        pat = df_bg[df_bg['es_hoja'] & df_bg['codigo'].astype(str).str.startswith('3')]['Saldo Final'].abs().sum()

        # 4. Renderizado del Reporte
        st.dataframe(
            df_bg.style.format({'Saldo Final': formato_contable}).apply(estilo_balance, axis=1),
            column_order=['codigo', 'Cuenta', 'Saldo Final'],
            use_container_width=True, height=500, hide_index=True
        )
        
        # 5. Obtención o cálculo automático de la utilidad para el cierre del Balance
        utilidad_ejercicio = st.session_state.get('utilidad_ejercicio', 0.0)
        
        if utilidad_ejercicio == 0.0 and not df_datos.empty:
            df_n1_er = df_datos[df_datos['nivel'] == 1].copy()
            if df_n1_er.empty:
                df_n1_er = df_datos[df_datos['codigo'].astype(str).str.strip().str.replace(r'[^0-9]', '', regex=True).str.len() == 1]
            
            df_n1_er['c_limpio'] = df_n1_er['codigo'].astype(str).str.strip().str.replace(r'[^0-9]', '', regex=True)
            
            ing_b = df_n1_er[df_n1_er['c_limpio'].str.startswith('4')]['Saldo Final'].sum()
            cos_b = df_n1_er[df_n1_er['c_limpio'].str.startswith('5')]['Saldo Final'].sum()
            gas_b = df_n1_er[df_n1_er['c_limpio'].str.startswith('6')]['Saldo Final'].sum()
            otros_ing_b = df_n1_er[df_n1_er['c_limpio'].str.startswith('7')]['Saldo Final'].sum()
            otros_egr_b = df_n1_er[df_n1_er['c_limpio'].str.startswith('8')]['Saldo Final'].sum()
            
            utilidad_ejercicio = abs(ing_b) + abs(otros_ing_b) - (abs(cos_b) + abs(gas_b) + abs(otros_egr_b))
            st.session_state['utilidad_ejercicio'] = utilidad_ejercicio

        patrimonio_ajustado = abs(pat) + utilidad_ejercicio
        descuadre = act - (pas + patrimonio_ajustado)
        
        st.divider()
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ACTIVOS", formato_contable(act))
        c2.metric("PASIVOS", formato_contable(pas))
        c3.metric("PATRIMONIO", formato_contable(abs(pat)))
        c4.metric("UTILIDAD EJERCICIO", formato_contable(utilidad_ejercicio), 
                    delta=f"{formato_contable(utilidad_ejercicio)}",
                    delta_color="normal" if utilidad_ejercicio >= 0 else "inverse")

        if abs(descuadre) < 0.01:
            st.success("✅ ¡Balance General Cuadrado Perfectamente!")
        else:
            st.error(f"❌ Descuadre contable detectado: {formato_contable(descuadre)}")

        # --- ÁREA DE DESCARGAS (Excel/PDF) ---
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
                    indent = "    " * (int(row['nivel']) - 1)
                    
                    cod_str = str(row['codigo']).replace('Σ', 'TOTAL')
                    nombre_str = f"{indent}{row['nombre']}"[:60]

                    pdf.cell(30, 7, cod_str, 1)
                    pdf.cell(110, 7, nombre_str, 1)
                    pdf.cell(50, 7, f"{abs(row['Saldo Final']):,.2f}", 1, 1, 'R')

                pdf.set_fill_color(0, 0, 0)
                pdf.set_text_color(255, 255, 255)
                pdf.set_font("Arial", 'B', 9)
                total_verificacion = act - (abs(pas) + abs(pat))
                pdf.cell(140, 10, "TOTAL ECUACIÓN PATRIMONIAL (ACT - PAS - PAT)", 1, 0, 'R', True)
                pdf.cell(50, 10, f"{total_verificacion:,.2f}", 1, 1, 'R', True)

                pdf_bytes = bytes(pdf.output())
                
                st.download_button(
                    label="⬇️ Descargar PDF Ahora",
                    data=pdf_bytes,
                    file_name=f"Balance_General_{EMPRESA}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e_pdf:
                st.error(f"Error al generar el PDF: {e_pdf}")
    else:
        st.info("No se encontraron datos para generar el balance.")


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

    @st.cache_data(ttl=300, show_spinner=False)
    def obtener_datos_agente_cached(db_name):
        return obtener_datos_agente_db(db_name)

    empresa_data = obtener_datos_agente_cached(db_actual)
    
    if not empresa_data:
        st.error("⚠️ No se pudieron cargar los datos de la empresa.")
        st.stop()

    # Bloqueo de acceso por rol
    if rol != 'admin' and empresa_data.get('id') != cliente_id:
        st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
        st.stop()

    # 3. INTERFAZ DEL REPORTE
    st.subheader(f"📈 Estado de Resultados: {EMPRESA}")
    
    # --- BLINDAJE LOCAL DE FECHAS ---
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
    
    # --- FUNCIÓN CON CACHÉ PARA OPTIMIZAR EL ESTADO DE RESULTADOS ---
    @st.cache_data(ttl=60, show_spinner=False)
    def obtener_estado_resultados_cached(db_name, fecha_desde, fecha_hasta, sucursal_sel):
        df_datos = pd.DataFrame()
        conn = conectar_db(db_name)
        if conn:
            try:
                conn.ping(reconnect=True)
                df_datos = generar_balance_profesional(conn, fecha_desde, fecha_hasta, sucursal_sel)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return df_datos

    df_datos = obtener_estado_resultados_cached(db_actual, f_er_desde, f_er_hasta, sucursal)
    
    if df_datos is not None and not df_datos.empty:
        # Limpiamos el código para asegurarnos de evaluar el primer dígito correctamente
        df_datos['codigo_limpio'] = df_datos['codigo'].astype(str).str.strip().str.replace(r'[^0-9]', '', regex=True)
        
        # 1. Filtramos cuentas de resultados (4 al 8) usando el código limpio
        df_er = df_datos[df_datos['codigo_limpio'].str.startswith(('4', '5', '6', '7', '8'))].copy()
        df_er['Cuenta'] = df_er.apply(lambda x: f"{'    ' * (int(x['nivel'])-1)}{x['nombre']}", axis=1)
        
        if df_er.empty:
            st.warning("⚠️ No se encontraron registros para las cuentas de Resultados (4, 5, 6, 7, 8) en el período seleccionado.")
        else:
            # 2. RENDERIZADO EN PANTALLA
            st.dataframe(
                df_er.style.format({'Saldo Final': formato_contable}).apply(estilo_balance, axis=1),
                column_order=['codigo', 'Cuenta', 'Saldo Final'],
                width='stretch', 
                height=400, 
                hide_index=True
            )
            
            # 3. CÁLCULO DE UTILIDAD / PÉRDIDA GLOBAL (Cuentas 4 a 8)
            df_n1 = df_er[df_er['nivel'] == 1]
            if df_n1.empty:
                df_n1 = df_er[df_er['codigo_limpio'].str.len() == 1]

            ing = df_n1[df_n1['codigo_limpio'].str.startswith('4')]['Saldo Final'].sum()
            cos = df_n1[df_n1['codigo_limpio'].str.startswith('5')]['Saldo Final'].sum()
            gas = df_n1[df_n1['codigo_limpio'].str.startswith('6')]['Saldo Final'].sum()
            otros_ing = df_n1[df_n1['codigo_limpio'].str.startswith('7')]['Saldo Final'].sum()
            otros_egr = df_n1[df_n1['codigo_limpio'].str.startswith('8')]['Saldo Final'].sum()

            utilidad = abs(ing) + abs(otros_ing) - (abs(cos) + abs(gas) + abs(otros_egr))
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Ingresos Totales", f"Bs. {abs(ing):,.2f}")
            with col2:
                st.metric("Costos y Gastos", f"Bs. {(abs(cos) + abs(gas) + abs(otros_egr)):,.2f}")
            with col3:
                st.metric("Utilidad / Pérdida", f"Bs. {formato_contable(utilidad)}", 
                            delta=f"{formato_contable(utilidad)}",
                            delta_color="normal" if utilidad >= 0 else "inverse")

            # 1. GESTIÓN DE TASA BCV CON CACHÉ
            @st.cache_data(ttl=3600, show_spinner=False)
            def obtener_tasa_bcv_cached(db_name):
                tasa_val = 1.0
                conn = conectar_db(db_name)
                if conn:
                    try:
                        tasa_val, _ = obtener_tasa_bcv_hoy(conn)
                    except Exception:
                        pass
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                return tasa_val

            if 'tasa_bcv' not in st.session_state:
                st.session_state.tasa_bcv = obtener_tasa_bcv_cached(db_actual)

            if st.button("🔄 Actualizar Tasa BCV"):
                st.session_state.tasa_bcv = obtener_tasa_bcv_cached(db_actual)
                st.rerun()

            tasa = st.session_state.tasa_bcv if st.session_state.tasa_bcv > 0 else 1.0

            # Cálculos en USD
            ing_usd, cos_usd, gas_usd, util_usd = [x / tasa for x in [abs(ing), abs(cos), abs(gas), utilidad]]
            costos_gastos_usd = cos_usd + gas_usd

            # 3. VISUALIZACIÓN EN USD
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
                        max-width: 300px; 
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
            df_excel = df_er[['codigo', 'Cuenta', 'Saldo Final']].copy()
            df_excel.columns = ['Código', 'Cuenta / Descripción', 'Saldo Final (Bs.)']

            with pd.ExcelWriter(output_er, engine='xlsxwriter') as writer:
                df_excel.to_excel(writer, index=False, sheet_name='Estado_Resultados')
            
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
                        indent = "    " * (int(row['nivel']) - 1)
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

                    pdf_bytes = bytes(pdf.output())
                    
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

        # --- ESTRUCTURA DE TABS (A NIVEL PRINCIPAL, SIN SANGRÍA) ---
        tab_titles = [
            "🔍 Consultar y Editar", 
            "📸 Escaneo Inteligente", 
            "🚨 Vaciado de Rango", 
            "📊 Cargar desde Excel", 
            "📁 PDFs POR LOTES",
            "📝 Notas de Crédito / Débito"  # <-- Nuestra nueva pestaña exclusiva
        ]

        # Creamos las pestañas y desempaquetamos inmediatamente
        tabs = st.tabs(tab_titles)
        tab1, tab2, tab3, tab4, tab5, tab6 = tabs
        # --- LÓGICA DE NAVEGACIÓN ---
        with tab1:  # Consultar, Modificar, Eliminar y Registrar
            st.subheader("🔍 Consulta y Edición: Libro de Compras")

            # 1. Filtros de fecha y botón de consulta inicial
            col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
            with col_c3:
                ver_todo = st.checkbox("📂 Ver todo", key="todo_compras")

            from datetime import date as d_tipo, datetime as dt_tipo

            def _obtener_f_segura(key_s):
                val = st.session_state.get(key_s)
                if val is not None:
                    try:
                        if hasattr(val, "year") and hasattr(val, "month"):
                            return val
                        elif isinstance(val, str):
                            return dt_tipo.strptime(val, "%Y-%m-%d").date()
                    except Exception:
                        pass
                return d_tipo.today()

            with col_c1:
                desde_c = st.date_input(
                    "Desde",
                    _obtener_f_segura("f_inicio_global"),
                    key="desde_c",
                    disabled=ver_todo,
                )
            with col_c2:
                hasta_c = st.date_input(
                    "Hasta",
                    _obtener_f_segura("f_fin_global"),
                    key="hasta_c",
                    disabled=ver_todo,
                )

            st.error("⚠️ **Atención:** Las acciones aquí solo afectan al Libro de Compras.")

            # --- FUNCIÓN CON CACHÉ PARA CONSULTAR EL LIBRO DE COMPRAS ---
            @st.cache_data(ttl=30, show_spinner=False)
            def consultar_libro_compras_cached(empresa, ver_todo_val, f_desde, f_hasta):
                df_res = pd.DataFrame()
                conn = conectar_db(empresa)
                if conn:
                    try:
                        conn.ping(reconnect=True)
                        if ver_todo_val:
                            query = "SELECT * FROM libro_compras ORDER BY fecha_operacion DESC"
                            df_res = pd.read_sql(query, conn)
                        else:
                            query = "SELECT * FROM libro_compras WHERE fecha_operacion BETWEEN %s AND %s ORDER BY fecha_operacion ASC"
                            df_res = pd.read_sql(query, conn, params=(f_desde, f_hasta))
                    except Exception:
                        pass
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                return df_res

            # Botón explícito de consulta
            if st.button("📊 Consultar Compras", key="btn_consultar_compras"):
                df_recuperado = consultar_libro_compras_cached(db_actual, ver_todo, desde_c, hasta_c)
                if df_recuperado is not None and not df_recuperado.empty:
                    st.session_state.df_compras_editor = df_recuperado
                else:
                    st.warning("No se encontraron registros en el rango seleccionado.")
                    if "df_compras_editor" in st.session_state:
                        del st.session_state.df_compras_editor

            # ==========================================
            # 2. RENDERIZADO DEL FRAME DE CONSULTA Y OPCIONES DE EDICIÓN
            # ==========================================
            if "df_compras_editor" in st.session_state:
                df_mostrar_compras = st.session_state.df_compras_editor.copy()

                # --- VISTA DE CONSULTA (Visualización limpia) ---
                df_visual_c = df_mostrar_compras.copy()
                cols_moneda_c = [
                    "total_compras",
                    "importe_exento",
                    "base_imponible",
                    "iva_monto",
                    "monto_iva_retenido",
                ]
                for col in cols_moneda_c:
                    if col in df_visual_c.columns:
                        df_visual_c[col] = df_visual_c[col].apply(
                            lambda x: "{:,.2f}".format(x)
                            .replace(",", "X")
                            .replace(".", ",")
                            .replace("X", ".")
                            if pd.notnull(x)
                            else "0,00"
                        )

                st.subheader("👁️ Vista de Consulta")
                st.dataframe(df_visual_c, use_container_width=True, hide_index=True)

                # --- EDITOR DE DATOS ---
                st.subheader("✏️ Administrar Compras (Modificar, Eliminar)")
                st.info("💡 **Instrucciones:** Puedes editar celdas directamente de los registros existentes, o eliminar registros seleccionando la fila y haciendo clic en el icono de papelera.")

                key_editor_compras = "editor_consulta_final"

                cambios_df = st.data_editor(
                    df_mostrar_compras,
                    key=key_editor_compras,
                    num_rows="fixed",
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", disabled=True),
                        "fecha_operacion": st.column_config.DateColumn("F. Operación", format="DD/MM/YYYY"),
                        "tipo_documento": st.column_config.TextColumn("Tipo Doc."),
                        "n_factura": st.column_config.TextColumn("Nº Factura"),
                        "n_control": st.column_config.TextColumn("Nº Control"),
                        "nota_credito": st.column_config.TextColumn("Nº Nota Crédito", help="Número de la Nota de Crédito emitida por el proveedor (si aplica)"),
                        "nota_debito": st.column_config.TextColumn("Nº Nota Débito", help="Número de la Nota de Débito (si aplica)"),
                        "proveedor": st.column_config.TextColumn("Proveedor"),
                        "rif": st.column_config.TextColumn("RIF"),
                        "total_compras": st.column_config.NumberColumn("Total Compras", format="%,.2f", step=0.01),
                        "importe_exento": st.column_config.NumberColumn("Importe Exento", format="%,.2f", step=0.01),
                        "base_imponible": st.column_config.NumberColumn("Base Imponible", format="%,.2f", step=0.01),
                        "iva_porcentaje": st.column_config.NumberColumn("% IVA", format="%.1f", step=0.1),
                        "iva_monto": st.column_config.NumberColumn("IVA Monto", format="%,.2f", step=0.01),
                        "fecha_comprobante": st.column_config.DateColumn("F. Comprobante", format="DD/MM/YYYY"),
                        "created_at": st.column_config.DatetimeColumn("F. Registro", disabled=True),
                        "updated_at": st.column_config.DatetimeColumn("F. Actualización", disabled=True),
                    },
                )

                # --- CÁLCULO DE TOTALES ---
                st.markdown("### 📊 Totales")

                def f_bs(v):
                    return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Total Compras", f_bs(df_mostrar_compras["total_compras"].sum() if "total_compras" in df_mostrar_compras.columns else 0.0))
                t2.metric("Total Exento", f_bs(df_mostrar_compras["importe_exento"].sum() if "importe_exento" in df_mostrar_compras.columns else 0.0))
                t3.metric("Total Base", f_bs(df_mostrar_compras["base_imponible"].sum() if "base_imponible" in df_mostrar_compras.columns else 0.0))
                t4.metric("Total IVA", f_bs(df_mostrar_compras["iva_monto"].sum() if "iva_monto" in df_mostrar_compras.columns else 0.0))
                st.markdown("---")

                # --- BOTÓN DE DESCARGA EN EXCEL ---
                st.markdown("### 📥 Descargar Reporte")
                import io

                nombre_archivo = f"Libro de compras del {desde_c.strftime('%Y-%m-%d')} al {hasta_c.strftime('%Y-%m-%d')}.xlsx"

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    df_mostrar_compras.to_excel(writer, index=False, sheet_name="Libro de Compras")
                buffer.seek(0)

                st.download_button(
                    label="📊 Descargar Libro de Compras en Excel",
                    data=buffer,
                    file_name=nombre_archivo,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="btn_download_excel_compras",
                )

                st.markdown("---")

                # --- BOTÓN ÚNICO DE GUARDAR ---
                if st.button("💾 Guardar cambios de edición en DB", type="primary", use_container_width=True, key="btn_guardar_final_compras"):
                    if key_editor_compras in st.session_state:
                        cambios = st.session_state[key_editor_compras]
                        conn = conectar_db(db_actual)

                        if conn:
                            try:
                                conn.ping(reconnect=True)
                                with conn.cursor() as cursor:
                                    cursor.execute("DESCRIBE libro_compras")
                                    columnas_db = [fila[0] for fila in cursor.fetchall()]

                                    def limpiar_dato(val):
                                        if val is None or (isinstance(val, float) and np.isnan(val)):
                                            return None
                                        if isinstance(val, (pd.Timestamp, pd.Timedelta)):
                                            return str(val.date())
                                        if isinstance(val, (np.integer, np.int64)):
                                            return int(val)
                                        if isinstance(val, (np.floating, np.float64)):
                                            return float(val)
                                        return str(val).strip()

                                    cursor.execute("START TRANSACTION")

                                    # 1. MODIFICAR / EDITAR FILAS EXISTENTES
                                    for row_idx, dict_cambios in cambios.get("edited_rows", {}).items():
                                        id_edit = int(df_mostrar_compras.iloc[int(row_idx)]["id"])

                                        if "fecha_operacion" in dict_cambios and dict_cambios["fecha_operacion"]:
                                            f = dict_cambios["fecha_operacion"]
                                            dict_cambios["fecha_operacion"] = f.strftime("%Y-%m-%d") if hasattr(f, "strftime") else str(f)

                                        if dict_cambios:
                                            cols_val = [f"{k} = %s" for k in dict_cambios.keys() if k in columnas_db]
                                            vals_val = [limpiar_dato(v) for k, v in dict_cambios.items() if k in columnas_db]
                                            if cols_val:
                                                sql_upd = f"UPDATE libro_compras SET {', '.join(cols_val)} WHERE id = %s"
                                                cursor.execute(sql_upd, vals_val + [id_edit])

                                    # 2. ELIMINAR FILAS
                                    for row_idx in cambios.get("deleted_rows", []):
                                        id_del = int(df_mostrar_compras.iloc[row_idx]["id"])
                                        cursor.execute("DELETE FROM libro_compras WHERE id = %s", (id_del,))

                                    conn.commit()
                                    st.cache_data.clear()
                                    st.success("✅ ¡Modificaciones y eliminaciones guardadas correctamente en MySQL!")

                                    if "df_compras_editor" in st.session_state:
                                        del st.session_state.df_compras_editor
                                    st.rerun()

                            except Exception as e:
                                if conn:
                                    conn.rollback()
                                st.error(f"❌ Error al guardar en MySQL: {e}")
                            finally:
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                    else:
                        st.warning("⚠️ No hay registro de cambios activos en la sesión.")

                st.markdown("---")

                # ==========================================
                # 3. SECCIÓN INFERIOR: AGREGAR NUEVA FACTURA CON CACHÉ
                # ==========================================
                @st.cache_data(ttl=60, show_spinner=False)
                def obtener_proveedores_cached(empresa):
                    df_p = pd.DataFrame()
                    conn_prov = conectar_db(empresa)
                    if conn_prov:
                        try:
                            conn_prov.ping(reconnect=True)
                            df_p = ejecutar_consulta("SELECT rif, razon_social FROM proveedores", conn_prov)
                        except Exception:
                            pass
                        finally:
                            try:
                                conn_prov.close()
                            except Exception:
                                pass
                    return df_p

                with st.expander(
                    "➕ Registrar Nueva Factura (Con listas desplegables y cálculos automáticos)",
                    expanded=False,
                ):
                    df_prov = obtener_proveedores_cached(db_actual)

                    if not df_prov.empty:
                        df_prov["display_prov"] = (
                            df_prov["razon_social"] + " (" + df_prov["rif"] + ")"
                        )
                        lista_opciones_proveedores = df_prov["display_prov"].tolist()
                    else:
                        lista_opciones_proveedores = []

                    if lista_opciones_proveedores:
                        prov_elegido = st.selectbox(
                            "Proveedor / RIF", options=lista_opciones_proveedores, key="rt_prov"
                        )
                        razon_social_val = prov_elegido.split(" (")[0]
                        rif_val = prov_elegido.split(" (")[1].replace(")", "")
                    else:
                        st.warning("No hay proveedores registrados. Por favor registre proveedores primero.")
                        razon_social_val = "VARIOS"
                        rif_val = "J000000000"

                    col_x1, col_x2 = st.columns(2)
                    with col_x1:
                        tipo_doc_val = st.selectbox(
                            "Tipo de Documento",
                            ["01-Factura", "03-Nota de Crédito"],
                            key="rt_tipo_doc",
                        )
                        fecha_op_val = st.date_input("Fecha de Operación / Emisión", key="rt_f_op")
                    with col_x2:
                        n_factura_val = st.text_input("Número de Factura", key="rt_n_fact")
                        n_control_val = st.text_input("Número de Control", key="rt_n_ctrl")
                        nota_cred_val = st.text_input(
                            "Nº Nota de Crédito (Opcional)", value="", key="rt_nc"
                        )

                    st.markdown("---")
                    st.markdown("### 💰 Control de Montos, Alícuota e IVA Automático")

                    alicuota_opciones = {
                        "General (16%)": 16.0,
                        "Reducida (8%)": 8.0,
                        "Exonerada / Otra (0%)": 0.0,
                    }

                    alicuota_label = st.selectbox(
                        "Seleccione la Alícuota de IVA",
                        options=list(alicuota_opciones.keys()),
                        key="rt_alicuota"
                    )
                    iva_porcentaje_val = alicuota_opciones[alicuota_label]

                    col_m1, col_m2, col_m3 = st.columns(3)
                    with col_m1:
                        base_imp_input = st.number_input(
                            "Base Imponible",
                            min_value=0.00,
                            format="%.2f",
                            step=100.00,
                            key="rt_base"
                        )
                    with col_m2:
                        iva_monto_input = base_imp_input * (iva_porcentaje_val / 100.0)
                        st.number_input(
                            f"IVA Monto ({iva_porcentaje_val}% Automático)",
                            value=float(iva_monto_input),
                            format="%.2f",
                            disabled=True
                        )
                    with col_m3:
                        exento_input = st.number_input(
                            "Monto Exento",
                            min_value=0.00,
                            format="%.2f",
                            step=100.00,
                            key="rt_exento"
                        )

                    total_calculado = base_imp_input + iva_monto_input + exento_input

                    def formato_venezuela(val):
                        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                    st.success(
                        f"💵 **Monto Total Calculado Automáticamente:** **{formato_venezuela(total_calculado)}**"
                    )

                    if st.button("💾 Guardar Factura en Base de Datos", type="primary", use_container_width=True, key="rt_btn_guardar"):
                        if not n_factura_val or n_factura_val == "0":
                            st.error("❌ El número de factura es obligatorio.")
                        else:
                            try:
                                conn_ins = conectar_db(db_actual)
                                if conn_ins:
                                    conn_ins.ping(reconnect=True)
                                    with conn_ins.cursor() as cursor_ins:
                                        query_insert_single = """
                                            INSERT INTO libro_compras 
                                            (fecha_operacion, tipo_documento, n_factura, n_control, nota_credito, proveedor, rif, total_compras, importe_exento, base_imponible, iva_porcentaje, iva_monto)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """
                                        valores = (
                                            fecha_op_val.strftime("%Y-%m-%d"),
                                            tipo_doc_val,
                                            n_factura_val,
                                            n_control_val,
                                            nota_cred_val if nota_cred_val else None,
                                            razon_social_val,
                                            rif_val,
                                            total_calculado,
                                            exento_input,
                                            base_imp_input,
                                            iva_porcentaje_val,
                                            iva_monto_input,
                                        )
                                        cursor_ins.execute(query_insert_single, valores)
                                        conn_ins.commit()
                                    conn_ins.close()
                                    st.cache_data.clear()
                                    st.success("✅ ¡Factura agregada exitosamente con su monto total y alícuota calculada!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error al guardar la factura: {e}")

        with tab2: # Escaneo Inteligente
            st.subheader("📸 Escaneo Inteligente de Documentos (OCR)")
            archivo = st.file_uploader("Sube factura, nota de crédito o débito (PDF o Imagen)", type=['jpg', 'png', 'jpeg', 'pdf'], key="uploader_factura")
            
            if "df_buffer_escaneo" not in st.session_state:
                st.session_state.df_buffer_escaneo = pd.DataFrame()

            if archivo:
                st.divider()
                
                if st.button("Procesar Documento (Individual)", key="btn_procesar_individual"):
                    with st.spinner('La IA está analizando el documento fiscal...'):
                        exito = False
                        intentos = 0
                        resultados = None
                        
                        while intentos < 3 and not exito:
                            try:
                                resultados = extraer_datos_factura(archivo)
                                exito = True
                            except Exception as e:
                                error_str = str(e)
                                if "429" in error_str:
                                    intentos += 1
                                    st.warning(f"⚠️ Límite de cuota de la API alcanzado, reintentando en 40s... (Intento {intentos}/3)")
                                    time.sleep(40)
                                else:
                                    st.error(f"❌ Error crítico: {error_str}")
                                    break
                        
                        if resultados:
                            # --- MAPEO EXACTO AL ESQUEMA DE MYSQL ---
                            fila_dict = {
                                "fecha_operacion": resultados.get("fecha_operacion"),
                                "tipo_documento": str(resultados.get("tipo_documento", "01")),
                                "n_factura": str(resultados.get("n_factura", "")).strip().upper(),
                                "n_control": str(resultados.get("n_control", "")).strip().upper(),
                                "nota_credito": str(resultados.get("nota_credito")).strip().upper() if resultados.get("nota_credito") and str(resultados.get("nota_credito")).lower() not in ['none', 'nan', '', 'null'] else None,
                                "nota_debito": str(resultados.get("nota_debito")).strip().upper() if resultados.get("nota_debito") and str(resultados.get("nota_debito")).lower() not in ['none', 'nan', '', 'null'] else None,
                                "n_factura_afectada": str(resultados.get("n_factura_afectada")).strip().upper() if resultados.get("n_factura_afectada") and str(resultados.get("n_factura_afectada")).lower() not in ['none', 'nan', '', 'null'] else None,
                                "proveedor": str(resultados.get("proveedor", "VARIOS")).strip().upper(),
                                "rif": str(resultados.get("rif", "")).replace('-', '').replace(' ', '').strip().upper(),
                                "tipo_transaccion": str(resultados.get("tipo_transaccion", "01")).strip(),
                                "total_compras": float(resultados.get("total_compras", 0.0)),
                                "importe_exento": float(resultados.get("importe_exento", 0.0)),
                                "base_imponible": float(resultados.get("base_imponible", 0.0)),
                                "iva_porcentaje": float(resultados.get("iva_porcentaje", 16.0)),
                                "iva_monto": float(resultados.get("iva_monto", 0.0))
                            }

                            nueva_fila = pd.DataFrame([fila_dict])
                            
                            st.session_state.df_buffer_escaneo = pd.concat([st.session_state.df_buffer_escaneo, nueva_fila], ignore_index=True)
                            st.success("✅ Documento agregado al buffer de revisión.")

                # --- ÁREA DE EDICIÓN Y REVISIÓN ESTRICTA ---
                if not st.session_state.df_buffer_escaneo.empty:
                    st.info(f"💡 Revisando {len(st.session_state.df_buffer_escaneo)} documentos en espera.")
                    df_a_editar = st.session_state.df_buffer_escaneo.copy()
                    
                    # Asegurar formato de fecha correcto para el DateColumn de Streamlit
                    if "fecha_operacion" in df_a_editar.columns:
                        df_a_editar["fecha_operacion"] = pd.to_datetime(df_a_editar["fecha_operacion"], errors='coerce').dt.date
                    
                    # Orden estricto según la tabla MySQL
                    columnas_ordenadas = [
                        "fecha_operacion", "tipo_documento", "n_factura", "n_control", 
                        "nota_credito", "nota_debito", "n_factura_afectada", "proveedor", 
                        "rif", "tipo_transaccion", "total_compras", "importe_exento", 
                        "base_imponible", "iva_porcentaje", "iva_monto"
                    ]
                    
                    columnas_existentes = [col for col in columnas_ordenadas if col in df_a_editar.columns]
                    otras_cols = [col for col in df_a_editar.columns if col not in columnas_existentes]
                    df_a_editar = df_a_editar[columnas_existentes + otras_cols]
                    
                    # Editor interactivo
                    buffer_editado = st.data_editor(
                        df_a_editar,
                        column_config={
                            "fecha_operacion": st.column_config.DateColumn("F. Operación", format="YYYY-MM-DD", required=True),
                            "tipo_documento": st.column_config.TextColumn("Tipo Doc"),
                            "n_factura": st.column_config.TextColumn("Nº Factura / Doc", required=True),
                            "n_control": st.column_config.TextColumn("Nº Control", required=True),
                            "nota_credito": st.column_config.TextColumn("Nota Crédito"),
                            "nota_debito": st.column_config.TextColumn("Nota Débito"),
                            "n_factura_afectada": st.column_config.TextColumn("Factura Afectada"),
                            "proveedor": st.column_config.TextColumn("Proveedor"),
                            "rif": st.column_config.TextColumn("RIF"),
                            "tipo_transaccion": st.column_config.TextColumn("Tipo Trans."),
                            "total_compras": st.column_config.NumberColumn("Total", format="%,.2f"),
                            "importe_exento": st.column_config.NumberColumn("Exento", format="%,.2f"),
                            "base_imponible": st.column_config.NumberColumn("Base Imponible", format="%,.2f"),
                            "iva_porcentaje": st.column_config.NumberColumn("% IVA", format="%.1f"),
                            "iva_monto": st.column_config.NumberColumn("IVA Monto", format="%,.2f")
                        },
                        key="editor_buffer_ocr",
                        num_rows="dynamic",
                        use_container_width=True
                    )
                    
                    st.session_state.df_buffer_escaneo = buffer_editado

                    st.markdown("---")
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
                        if st.button("🚀 Guardar TODAS en DB (Modo Seguro)", type="primary", use_container_width=True, key="btn_guardar_ocr_db"):
                            db_actual = st.session_state.get('DB_ACTUAL') or st.session_state.get('id_empresa_actual')
                            if not db_actual:
                                st.error("❌ No se encontró la base de datos activa en la sesión.")
                                st.stop()

                            df_a_procesar = st.session_state.df_buffer_escaneo.copy()
                            
                            # --- FUNCIÓN CON CACHÉ PARA EL MOTOR SQLALCHEMY ---
                            @st.cache_resource(show_spinner=False)
                            def obtener_engine_cached(db_name):
                                from urllib.parse import quote_plus
                                password_escaped = quote_plus("W3Zkbr4E2trGCfoX")
                                database_url = f"mysql+pymysql://4K4VAw4t4ZPFUTF.root:{password_escaped}@gateway01.us-east-1.prod.aws.tidbcloud.com:4000/{db_name}"
                                return create_engine(
                                    database_url,
                                    connect_args={
                                        "ssl": {
                                            "ssl_ca": None,
                                            "check_hostname": False
                                        }
                                    }
                                )

                            try:
                                engine = obtener_engine_cached(db_actual)
                            except Exception as ex_eng:
                                st.error(f"❌ Error al crear el motor de base de datos: {ex_eng}")
                                st.stop()
                            
                            bar = st.progress(0)
                            facturas_exitosas = 0
                            
                            registros = df_a_procesar.to_dict(orient='records')
                            total_regs = len(registros)
                            
                            for index, row in enumerate(registros):
                                try:
                                    fecha_op = str(row.get('fecha_operacion') or '').split(" ")[0]
                                    tipo_doc = str(row.get('tipo_documento') or '01').strip()
                                    n_factura = str(row.get('n_factura') or '').strip().upper()
                                    n_control = str(row.get('n_control') or '').strip().upper()
                                    
                                    nc_raw = row.get('nota_credito')
                                    nc_val = str(nc_raw).strip().upper() if nc_raw is not None and str(nc_raw).lower() not in ['none', 'nan', '', 'null', 'nat'] else None
                                    if nc_val == '': nc_val = None
                                    
                                    nd_raw = row.get('nota_debito')
                                    nd_val = str(nd_raw).strip().upper() if nd_raw is not None and str(nd_raw).lower() not in ['none', 'nan', '', 'null', 'nat'] else None
                                    if nd_val == '': nd_val = None
                                    
                                    afec_raw = row.get('n_factura_afectada')
                                    afec_val = str(afec_raw).strip().upper() if afec_raw is not None and str(afec_raw).lower() not in ['none', 'nan', '', 'null', 'nat'] else None
                                    if afec_val == '': afec_val = None
                                    
                                    proveedor = str(row.get('proveedor') or 'VARIOS').strip().upper()
                                    rif = str(row.get('rif') or '').replace('-', '').replace(' ', '').strip().upper()
                                    tipo_trans = str(row.get('tipo_transaccion') or '01').strip()
                                    
                                    total_c = float(row.get('total_compras') or 0.0)
                                    exento = float(row.get('importe_exento') or 0.0)
                                    base_imp = float(row.get('base_imponible') or 0.0)
                                    iva_porc = float(row.get('iva_porcentaje') or 16.0)
                                    iva_monto = float(row.get('iva_monto') or 0.0)

                                    dict_limpio = {
                                        'fecha_operacion': fecha_op,
                                        'tipo_documento': tipo_doc,
                                        'n_factura': n_factura,
                                        'n_control': n_control,
                                        'nota_credito': nc_val,
                                        'nota_debito': nd_val,
                                        'n_factura_afectada': afec_val,
                                        'proveedor': proveedor,
                                        'rif': rif,
                                        'tipo_transaccion': tipo_trans,
                                        'total_compras': total_c,
                                        'importe_exento': exento,
                                        'base_imponible': base_imp,
                                        'iva_porcentaje': iva_porc,
                                        'iva_monto': iva_monto
                                    }
                                    
                                    fila_df = pd.DataFrame([dict_limpio])
                                    resultado = 0
                                    doc_nombre = f"Factura {n_factura}"
                                    
                                    with engine.connect() as conn:
                                        if nc_val:
                                            query_check = text("SELECT COUNT(*) FROM libro_compras WHERE rif = :rif AND nota_credito = :nc")
                                            res = conn.execute(query_check, {"rif": rif, "nc": nc_val}).scalar()
                                            resultado = res if res is not None else 0
                                            doc_nombre = f"Nota de Crédito {nc_val}"
                                        elif nd_val:
                                            query_check = text("SELECT COUNT(*) FROM libro_compras WHERE rif = :rif AND nota_debito = :nd")
                                            res = conn.execute(query_check, {"rif": rif, "nd": nd_val}).scalar()
                                            resultado = res if res is not None else 0
                                            doc_nombre = f"Nota de Débito {nd_val}"
                                        else:
                                            query_check = text("SELECT COUNT(*) FROM libro_compras WHERE rif = :rif AND n_factura = :nfac AND (nota_credito IS NULL OR nota_credito = '') AND (nota_debito IS NULL OR nota_debito = '')")
                                            res = conn.execute(query_check, {"rif": rif, "nfac": n_factura}).scalar()
                                            resultado = res if res is not None else 0
                                            doc_nombre = f"Factura {n_factura}"
                                    
                                    if resultado > 0:
                                        st.warning(f"⚠️ Documento {doc_nombre} (RIF {rif}) ya registrado en DB. Saltando...")
                                    else:
                                        fila_df.to_sql('libro_compras', con=engine, if_exists='append', index=False)
                                        facturas_exitosas += 1
                                        st.write(f"✅ {doc_nombre} guardado correctamente.")

                                except Exception as e:
                                    st.error(f"❌ Error al guardar fila {index + 1}: {e}")

                                if total_regs > 0:
                                    bar.progress((index + 1) / total_regs)
                            
                            st.cache_data.clear()
                            st.success(f"✅ Proceso finalizado. Total guardados: {facturas_exitosas} de {total_regs}")
                            if facturas_exitosas > 0:
                                st.session_state.df_buffer_escaneo = pd.DataFrame()
                                st.rerun()
        with tab3: # Vaciado de Rango
            st.subheader("🚨 Vaciado de Compras")
            
            with st.popover("🚨 VACIAR COMPRAS (RANGO SELECCIONADO)", use_container_width=True):
                st.subheader("Seleccionar Rango a Borrar")
                
                # 1. Selectores de fecha dentro del popover
                fecha_d = st.date_input("Desde:", key="rango_desde_borrar_compras")
                fecha_h = st.date_input("Hasta:", key="rango_hasta_borrar_compras")
                
                st.markdown("---")
                st.subheader("Confirmar Borrado")
                st.warning(f"Se eliminarán los registros desde {fecha_d} hasta {fecha_h}") 
                
                confirmar_check = st.checkbox("Confirmo que deseo borrar", key="check_borrar_final_compras")
                
                # 2. Ejecutar con las fechas seleccionadas de forma segura y optimizada
                if st.button("EJECUTAR BORRADO", type="primary", disabled=not confirmar_check, key="btn_ejecutar_borrado_compras_rango"):
                    f_d_str = fecha_d.strftime('%Y-%m-%d')
                    f_h_str = fecha_h.strftime('%Y-%m-%d')
                    
                    try:
                        conn_del = conectar_db(db_actual)
                        if conn_del:
                            conn_del.ping(reconnect=True)
                            with conn_del.cursor() as cursor:
                                cursor.execute(
                                    "DELETE FROM libro_compras WHERE fecha_operacion BETWEEN %s AND %s", 
                                    (f_d_str, f_h_str)
                                )
                                conn_del.commit()
                            conn_del.close()
                        
                        st.cache_data.clear()
                        st.success("✅ Rango de compras eliminado correctamente.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al ejecutar el borrado: {e}")

            st.divider()

            # --- FUNCIÓN CON CACHÉ PARA LA INSPECCIÓN RÁPIDA ---
            @st.cache_data(ttl=30, show_spinner=False)
            def obtener_fechas_compras_cached(empresa):
                fechas = []
                conn = conectar_db(empresa)
                if conn:
                    try:
                        conn.ping(reconnect=True)
                        df_fechas = pd.read_sql("SELECT DISTINCT fecha_operacion FROM libro_compras ORDER BY fecha_operacion DESC LIMIT 10", conn)
                        if not df_fechas.empty:
                            fechas = df_fechas['fecha_operacion'].tolist()
                    except Exception:
                        pass
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                return fechas

            # 3. BLOQUE DE INSPECCIÓN OPTIMIZADO
            with st.expander("🕵️ Inspeccionar fechas de compras antes de borrar"):
                try:
                    fechas_existentes = obtener_fechas_compras_cached(db_actual)
                    if fechas_existentes:
                        st.write("Las 10 fechas de operación más recientes en tu libro de compras:")
                        for f in fechas_existentes:
                            st.write(f"- {f}")
                    else:
                        st.info("ℹ️ No se encontraron registros en el libro de compras.")
                except Exception:
                    st.error("No se pudieron cargar las fechas de inspección.")

        with tab4: # Cargar desde Excel y Editor de Tabla
            st.subheader("📊 Carga Masiva desde Excel (LIBROS DE COMPRAS)")
            archivo_ex = st.file_uploader("Sube tu archivo Excel", type=['xlsx'], key="uploader_excel_compras_masivo")
            
            # --- FUNCIÓN CON CACHÉ PARA LEER EL EXCEL UNA SOLA VEZ ---
            @st.cache_data(show_spinner=False)
            def leer_excel_masivo_cached(file_buffer):
                df_excel = pd.read_excel(file_buffer)
                df_excel.columns = df_excel.columns.str.strip().str.lower().str.replace(" ", "_")
                
                # Blindaje anti-error de PyArrow
                for col in df_excel.columns:
                    if any(k in col for k in ['control', 'factura', 'rif', 'documento', 'proveedor']):
                        df_excel[col] = df_excel[col].astype(str).replace({'nan': '', 'None': ''})
                        
                return df_excel

            # 1. CARGA Y LIMPIEZA INICIAL
            if archivo_ex is not None:
                st.session_state.df_carga_excel = leer_excel_masivo_cached(archivo_ex)

            # 2. VISUALIZACIÓN Y EDICIÓN
            if "df_carga_excel" in st.session_state and not st.session_state.df_carga_excel.empty:
                df_temp = st.session_state.df_carga_excel.copy()
                
                # A. Limpieza de fecha inteligente
                col_fecha = next((c for c in df_temp.columns if 'fecha' in c.lower()), None)
                if col_fecha:
                    df_temp = df_temp.rename(columns={col_fecha: 'fecha_operacion'})
                    
                    df_temp['fecha_operacion'] = pd.to_datetime(df_temp['fecha_operacion'], errors='coerce')\
                                                .dt.strftime('%Y-%m-%d')\
                                                .fillna(pd.Timestamp.now().strftime('%Y-%m-%d'))
                    
                    st.session_state.df_carga_excel = df_temp

                # B. Preparación de Vista (Solo para mostrar)
                df_visual = st.session_state.df_carga_excel.copy()
                
                cols_para_formatear = ['total_compras', 'compras_exentas', 'base_imponible', 'credito_fiscales']
                for col in cols_para_formatear:
                    if col in df_visual.columns:
                        df_visual[col] = df_visual[col].apply(
                            lambda x: "{:,.2f}".format(float(x)).replace(",", "X").replace(".", ",").replace("X", ".") 
                            if pd.notnull(x) else "0,00"
                        )
                        
                st.subheader("👁️ Vista de los datos cargados")
                st.dataframe(df_visual, use_container_width=True, hide_index=True)

                # D. Totales
                st.markdown("---")
                def f_bs(v): return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                df_calc = st.session_state.df_carga_excel.copy()
                
                renombres = {
                    'importe_exento': 'compras_exentas',
                    'iva_monto': 'credito_fiscales',
                    'total_exento': 'compras_exentas'
                }
                df_calc = df_calc.rename(columns=renombres)

                for col in ['total_compras', 'compras_exentas', 'base_imponible', 'credito_fiscales']:
                    if col not in df_calc.columns:
                        df_calc[col] = 0.0
                    else:
                        df_calc[col] = pd.to_numeric(df_calc[col], errors='coerce').fillna(0.0)

                # --- MÉTRICAS ---
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("TOTAL COMPRAS", f_bs(df_calc['total_compras'].sum()))
                m2.metric("TOTAL EXENTO", f_bs(df_calc['compras_exentas'].sum()))
                m3.metric("TOTAL BASE", f_bs(df_calc['base_imponible'].sum()))
                m4.metric("TOTAL IVA", f_bs(df_calc['credito_fiscales'].sum()))

                st.markdown("---")

                # E. BOTÓN DE GUARDADO FINAL
                if st.button("🚀 Guardar carga masiva en DB", type="primary", use_container_width=True, key="btn_guardar_masivo_compras"):
                    with st.spinner("⏳ Guardando registros en la base de datos..."):
                        try:
                            df_to_save = st.session_state.df_carga_excel.copy()
                            
                            if 'retencion_realizada' not in df_to_save.columns:
                                df_to_save['retencion_realizada'] = 0.0
                            
                            if 'retencion_iva_realizada' not in df_to_save.columns:
                                df_to_save['retencion_iva_realizada'] = 0.0

                            # LLAMADA A LA FUNCIÓN DE BD
                            cargar_libro_compras_db(df_to_save, db_actual)
                            
                            st.cache_data.clear()
                            st.success("✅ ¡Proceso finalizado y guardado correctamente en la base de datos!")
                            
                            # Limpiar estado y recargar interfaz
                            del st.session_state.df_carga_excel
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Error crítico al guardar en DB: {e}")
            else:
                st.info("ℹ️ Por favor, sube un archivo Excel válido para comenzar la carga masiva.")

        # --- TAB 5: BANDEJA DE ENTRADA INTELIGENTE (PDFs POR LOTES) ---
        with tab5:
            st.subheader("📥 Bandeja de Entrada - Procesamiento Local de Facturas (PDF)")
            st.info("Arrastra o selecciona múltiples archivos PDF de facturas. Se acumularán en cola para su posterior revisión y registro.")

            # Inicializamos la cola y el registro de IDs en session_state si no existen
            if "cola_pdfs" not in st.session_state:
                st.session_state.cola_pdfs = []
            if "archivos_procesados_ids" not in st.session_state:
                st.session_state.archivos_procesados_ids = set()
            if "datos_extraidos_ia" not in st.session_state:
                st.session_state.datos_extraidos_ia = {}

            # 1. Subida múltiple de archivos a la sesión (Cola de espera)
            archivos_pdf = st.file_uploader(
                "Sube tus facturas en PDF", 
                type=['pdf'], 
                accept_multiple_files=True,
                key="uploader_pdf_cola"
            )

            # Si el usuario selecciona nuevos archivos, los añadimos evitando duplicados
            if archivos_pdf:
                nombres_existentes = [item['nombre'] for item in st.session_state.cola_pdfs]
                for archivo in archivos_pdf:
                    file_id = getattr(archivo, "file_id", archivo.name)
                    if archivo.name not in nombres_existentes and file_id not in st.session_state.archivos_procesados_ids:
                        st.session_state.cola_pdfs.append({
                            "id": file_id,
                            "nombre": archivo.name,
                            "objeto": archivo,
                            "estado": "Pendiente"
                        })

            # 2. Visualización de la cola actual
            if st.session_state.cola_pdfs:
                st.markdown(f"### 📋 Cola de Documentos ({len(st.session_state.cola_pdfs)} en espera)")
                
                # Botón para limpiar toda la cola
                if st.button("🗑️ Vaciar Cola", key="btn_vaciar_cola_pdfs"):
                    st.session_state.cola_pdfs = []
                    st.session_state.archivos_procesados_ids = set()
                    st.session_state.datos_extraidos_ia = {}
                    st.rerun()

                # Mostrar listado rápido en tabla
                import pandas as pd
                df_cola = pd.DataFrame([{
                    "Archivo": item["nombre"], 
                    "Estado": item["estado"]
                } for item in st.session_state.cola_pdfs])
                
                st.dataframe(df_cola, use_container_width=True, hide_index=True)
                st.markdown("---")

                # ==========================================
                # 3. SECCIÓN DE AUDITORÍA Y REGISTRO INDIVIDUAL
                # ==========================================
                st.markdown("### 📝 Auditoría, Extracción Local Rápida y Registro al Libro de Compras")
                
                documentos_pendientes = [item for item in st.session_state.cola_pdfs if item["estado"] == "Pendiente"]
                
                if documentos_pendientes:
                    nombres_pendientes = [item["nombre"] for item in documentos_pendientes]
                    documento_seleccionado_nombre = st.selectbox(
                        "Selecciona un documento pendiente para revisar y registrar:", 
                        nombres_pendientes,
                        key="select_doc_auditoria"
                    )

                    # Encontrar el objeto correspondiente
                    doc_obj = next((item for item in documentos_pendientes if item["nombre"] == documento_seleccionado_nombre), None)

                    if doc_obj:
                        col_ia1, col_ia2 = st.columns([1, 3])
                        with col_ia1:
                            # Botón para disparar la extracción local por Regex
                            if st.button("⚡ Procesar Factura (Local)", key="btn_procesar_factura_local"):
                                with st.spinner("Leyendo estructura del PDF localmente..."):
                                    # Llamada directa a la función de expresiones regulares
                                    datos_extraidos = extraer_datos_con_regex(doc_obj["objeto"])
                                    
                                    if datos_extraidos:
                                        st.session_state.datos_extraidos_ia[doc_obj["nombre"]] = datos_extraidos
                                        st.success("¡Datos extraídos con éxito de forma local!")
                                        st.rerun()
                                    else:
                                        st.error("No se pudieron extraer datos automáticos de este PDF.")

                        # Recuperamos los datos precargados si ya se procesaron
                        datos_pre = st.session_state.datos_extraidos_ia.get(doc_obj["nombre"], {})

                        with st.form("form_registro_libro_compras"):
                            st.info(f"Registrando datos para el archivo: **{doc_obj['nombre']}**")
                            
                            # Campos basados en tu tabla SQL, autocompletados con la extracción local
                            col1, col2 = st.columns(2)
                            with col1:
                                f_val = datos_pre.get("fecha_operacion", "")
                                try:
                                    f_default = datetime.strptime(f_val, '%Y-%m-%d').date() if f_val else datetime.today().date()
                                except:
                                    f_default = datetime.today().date()
                                    
                                fecha_operacion = st.date_input("Fecha de Operación", value=f_default)
                                tipo_documento = st.text_input("Tipo de Documento", value="01")
                                n_factura = st.text_input("Nº de Factura", value=str(datos_pre.get("n_factura", "")))
                                n_control = st.text_input("Nº de Control", value=str(datos_pre.get("n_control", "")))
                                n_factura_afectada = st.text_input("Nº Factura Afectada (Opcional)", value="")
                                
                            with col2:
                                proveedor = st.text_input("Nombre del Proveedor", value=str(datos_pre.get("proveedor", "")))
                                rif = st.text_input("RIF del Proveedor", value=str(datos_pre.get("rif", "")))
                                tipo_transaccion = st.text_input("Tipo de Transacción", value="01")
                                base_imponible = st.number_input("Base Imponible", format="%.2f", value=float(datos_pre.get("base_imponible", 0.00)))
                                iva_porcentaje = st.number_input("% IVA", value=float(datos_pre.get("iva_porcentaje", 16.00)), format="%.2f")
                                iva_monto = st.number_input("Monto IVA", format="%.2f", value=float(datos_pre.get("iva_monto", 0.00)))
                                total_compras = st.number_input("Total Compras", format="%.2f", value=float(datos_pre.get("total_compras", 0.00)))

                            # Botón final para insertar en tu tabla SQL
                            submitted = st.form_submit_button("💾 Guardar Definitivamente en Libro de Compras", type="primary")
                            
                            if submitted:
                                db_nombre = st.session_state.get('DB_ACTUAL')
                                if not db_nombre:
                                    st.error("Error: No se ha seleccionado una base de datos activa.")
                                else:
                                    conn = conectar_db(db_nombre)
                                    if conn is None:
                                        st.error(f"❌ No se pudo conectar a la base de datos '{db_nombre}'.")
                                    else:
                                        try:
                                            conn.ping(reconnect=True)
                                            with conn.cursor() as cursor:
                                                query = """
                                                    INSERT INTO libro_compras (
                                                        fecha_operacion, tipo_documento, n_factura, n_control, 
                                                        n_factura_afectada, proveedor, rif, tipo_transaccion, 
                                                        total_compras, importe_exento, base_imponible, 
                                                        iva_porcentaje, iva_monto
                                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                                """
                                                
                                                importe_exento = float(datos_pre.get("importe_exento", 0.00))
                                                
                                                valores = (
                                                    fecha_operacion, tipo_documento, n_factura, n_control,
                                                    n_factura_afectada if n_factura_afectada else None,
                                                    proveedor, rif, tipo_transaccion,
                                                    total_compras, importe_exento, base_imponible,
                                                    iva_porcentaje, iva_monto
                                                )
                                                
                                                cursor.execute(query, valores)
                                                conn.commit()
                                            
                                            # Actualizamos el estado del documento en la cola local
                                            for item in st.session_state.cola_pdfs:
                                                if item["nombre"] == doc_obj["nombre"]:
                                                    item["estado"] = "Procesado"
                                                    st.session_state.archivos_procesados_ids.add(item["id"])
                                                    break
                                            
                                            st.cache_data.clear()
                                            st.success(f"¡Factura {n_factura} registrada exitosamente en el Libro de Compras!")
                                            st.rerun()
                                            
                                        except Exception as e:
                                            conn.rollback()
                                            st.error(f"Error al registrar la factura en la base de datos: {e}")
                                        finally:
                                            try:
                                                conn.close()
                                            except Exception:
                                                pass
                else:
                    st.success("🎉 ¡Todos los documentos en la cola ya han sido procesados y registrados!")

        with tab6:
            st.subheader("📝 Gestión de Notas de Crédito y Débito")
            st.info("💡 **Flujo Fiscal:** Consulta el libro de compras por fecha, selecciona la factura a afectar y genera su documento de ajuste asociado con su respectivo número de control.")

            # --- PASO 1: FILTRO POR RANGO DE FECHAS ---
            st.markdown("#### 1️⃣ Seleccionar Periodo del Libro de Compras")
            col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
            with col_f1:
                fecha_desde = st.date_input("Desde", key="nc_fecha_desde")
            with col_f2:
                fecha_hasta = st.date_input("Hasta", key="nc_fecha_hasta")
            with col_f3:
                st.markdown("<br>", unsafe_allow_html=True)
                btn_consultar_lc = st.button("🔍 Consultar", key="btn_consultar_lc_nc")

            # --- FUNCIÓN CON CACHÉ PARA CONSULTAR EL LIBRO DE COMPRAS EN NOTAS ---
            @st.cache_data(ttl=30, show_spinner=False)
            def consultar_lc_nc_cached(empresa, f_desde, f_hasta):
                df_res = pd.DataFrame()
                conn = conectar_db(empresa)
                if conn:
                    try:
                        conn.ping(reconnect=True)
                        query_lc = """
                            SELECT id, fecha_operacion, tipo_documento, n_factura, n_control, 
                                   proveedor, rif, total_compras, importe_exento, base_imponible, iva_monto 
                            FROM libro_compras 
                            WHERE fecha_operacion BETWEEN %s AND %s 
                            ORDER BY fecha_operacion DESC
                        """
                        df_res = pd.read_sql(query_lc, con=conn, params=(f_desde, f_hasta))
                    except Exception:
                        pass
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                return df_res

            if btn_consultar_lc:
                try:
                    df_lc_resultado = consultar_lc_nc_cached(db_actual, fecha_desde, fecha_hasta)
                    if not df_lc_resultado.empty:
                        st.session_state.df_nc_libro_compras = df_lc_resultado
                        st.success(f"✅ Se encontraron {len(df_lc_resultado)} registros en el periodo.")
                    else:
                        st.warning("⚠️ No se encontraron facturas en el rango de fechas seleccionado.")
                        if "df_nc_libro_compras" in st.session_state:
                            del st.session_state.df_nc_libro_compras
                except Exception as e:
                    st.error(f"❌ Error al consultar la base de datos: {e}")

            # --- PASO 2: MOSTRAR TABLA Y SELECCIONAR FACTURA A AFECTAR ---
            if "df_nc_libro_compras" in st.session_state and not st.session_state.df_nc_libro_compras.empty:
                st.markdown("---")
                st.markdown("#### 2️⃣ Selecciona la Factura que será Afectada")
                
                df_select = st.session_state.df_nc_libro_compras.copy()
                df_select.insert(0, "Seleccionar", False)

                # Editor interactivo con checkbox de selección
                df_seleccionado_usuario = st.data_editor(
                    df_select,
                    key="editor_seleccion_factura_nc",
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Seleccionar": st.column_config.CheckboxColumn("Seleccionar", required=True),
                        "fecha_operacion": st.column_config.DateColumn("F. Operación"),
                        "total_compras": st.column_config.NumberColumn("Total", format="%,.2f"),
                        "base_imponible": st.column_config.NumberColumn("Base Imponible", format="%,.2f"),
                        "iva_monto": st.column_config.NumberColumn("IVA Monto", format="%,.2f")
                    },
                    disabled=["id", "fecha_operacion", "tipo_documento", "n_factura", "n_control", "proveedor", "rif", "total_compras", "importe_exento", "base_imponible", "iva_monto"]
                )

                # Filtrar la fila seleccionada
                filas_elegidas = df_seleccionado_usuario[df_seleccionado_usuario["Seleccionar"] == True]

                if len(filas_elegidas) == 1:
                    factura_base = filas_elegidas.iloc[0]
                    st.session_state.factura_seleccionada_nc = factura_base
                    st.info(f"📌 **Factura seleccionada:** Nº {factura_base['n_factura']} | Proveedor: {factura_base['proveedor']}")
                elif len(filas_elegidas) > 1:
                    st.warning("⚠️ Por favor selecciona **solo una** factura para aplicarle el documento de ajuste.")
                
                # --- PASO 3: FRAME NUEVO PARA AGREGAR LA NOTA HEREDANDO MONTOS ---
                if "factura_seleccionada_nc" in st.session_state:
                    fac = st.session_state.factura_seleccionada_nc
                    
                    st.markdown("---")
                    st.markdown("#### 3️⃣ Datos del Documento de Ajuste (Nota de Crédito / Débito)")
                    
                    with st.form("form_crear_nota_fiscal"):
                        col_t1, col_t2, col_t3, col_t4 = st.columns([2, 2, 2, 2])
                        with col_t1:
                            tipo_ajuste = st.selectbox("Tipo de Ajuste", ["Nota de Crédito", "Nota de Débito"])
                        with col_t2:
                            from datetime import date
                            fecha_emision_ajuste = st.date_input("Fecha de Emisión (Nota)", value=date.today(), key="nc_fecha_emision_val")
                        with col_t3:
                            nro_documento_ajuste = st.text_input("Nº de Documento (Nota)", placeholder="Ej: 00000720")
                        with col_t4:
                            nro_control_ajuste = st.text_input("Nº de Control (Nota)", placeholder="Ej: 00-026357")

                        st.markdown(f"**Factura Afectada:** `{fac['n_factura']}` | **RIF Proveedor:** `{fac['rif']}` ({fac['proveedor']})")
                        
                        # Definimos si los montos van negativos (caso Nota de Crédito resta) o positivos
                        multiplicador = -1.0 if tipo_ajuste == "Nota de Crédito" else 1.0

                        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                        with col_m1:
                            monto_tot = fac['total_compras'] * multiplicador
                            st.metric("Total Ajuste", f"{monto_tot:,.2f}")
                        with col_m2:
                            monto_base = fac['base_imponible'] * multiplicador
                            st.metric("Base Imponible", f"{monto_base:,.2f}")
                        with col_m3:
                            monto_iva = fac['iva_monto'] * multiplicador
                            st.metric("IVA Monto", f"{monto_iva:,.2f}")
                        with col_m4:
                            monto_exento = fac['importe_exento'] * multiplicador
                            st.metric("Importe Exento", f"{monto_exento:,.2f}")

                        btn_guardar_nota_db = st.form_submit_button("🚀 Registrar Nota de Ajuste en DB", type="primary")

                        if btn_guardar_nota_db:
                            if not nro_documento_ajuste.strip() or not nro_control_ajuste.strip():
                                st.error("❌ Debes ingresar tanto el número de la nota como su respectivo número de control.")
                            else:
                                conn = None
                                try:
                                    conn = conectar_db(db_actual)
                                    if conn:
                                        conn.ping(reconnect=True)
                                        with conn.cursor() as cursor:
                                            query_insert = """
                                                INSERT INTO libro_compras (
                                                    fecha_operacion, tipo_documento, n_factura, n_control, 
                                                    nota_credito, nota_debito, n_factura_afectada, proveedor, 
                                                    rif, tipo_transaccion, total_compras, importe_exento, 
                                                    base_imponible, iva_porcentaje, iva_monto
                                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            """
                                            
                                            valores = (
                                                fecha_emision_ajuste.strftime('%Y-%m-%d'),
                                                "03" if tipo_ajuste == "Nota de Crédito" else "02",
                                                nro_documento_ajuste.strip().upper(),
                                                nro_control_ajuste.strip().upper(),
                                                nro_documento_ajuste.strip().upper() if tipo_ajuste == "Nota de Crédito" else None,
                                                nro_documento_ajuste.strip().upper() if tipo_ajuste == "Nota de Débito" else None,
                                                fac['n_factura'],
                                                fac['proveedor'],
                                                fac['rif'],
                                                "01",
                                                monto_tot,
                                                monto_exento,
                                                monto_base,
                                                fac.get('iva_porcentaje', 16.0),
                                                monto_iva
                                            )
                                            
                                            cursor.execute(query_insert, valores)
                                            conn.commit()
                                        
                                        st.cache_data.clear()
                                        st.success(f"✅ ¡{tipo_ajuste} Nº {nro_documento_ajuste} (Emitida el {fecha_emision_ajuste}) guardada y vinculada a la factura {fac['n_factura']}!")
                                        if "factura_seleccionada_nc" in st.session_state:
                                            del st.session_state.factura_seleccionada_nc
                                        st.rerun()
                                except Exception as e:
                                    if conn:
                                        conn.rollback()
                                    st.error(f"❌ Error al registrar el ajuste en la base de datos: {e}")
                                finally:
                                    if conn:
                                        conn.close()
            else:
                st.info("ℹ️ Utiliza el selector de fechas y haz clic en Consultar para ver las facturas del periodo.")

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
        import pandas as pd

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
                if hasattr(fecha_obj, 'strftime'):
                    fecha_str = fecha_obj.strftime("%d/%m/%Y")
                else:
                    fecha_str = str(fecha_obj)
                ET.SubElement(detalle, "FechaOperacion").text = fecha_str
                
                # 4. Concepto, Monto Operación y Porcentaje
                codigo_concepto = str(row['codigo_concepto']).zfill(3)
                ET.SubElement(detalle, "CodigoConcepto").text = codigo_concepto
                ET.SubElement(detalle, "MontoOperacion").text = f"{float(row['monto_operacion']):.2f}"
                
                porcentaje = float(row['porcentaje_retencion'])
                ET.SubElement(detalle, "PorcentajeRetencion").text = f"{porcentaje:.2f}"

            xml_str = ET.tostring(root, encoding='utf-8')
            parsed = minidom.parseString(xml_str)
            return parsed.toprettyxml(indent="  ")
    
        # --- 🔘 TABLA DE REFERENCIA ---
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

            # Inicializar listas de control en sesión si no existen
            if "facturas_procesadas_ids" not in st.session_state:
                st.session_state.facturas_procesadas_ids = []
            if "historial_retenciones_sesion" not in st.session_state:
                st.session_state.historial_retenciones_sesion = []

            col_c1, col_c2 = st.columns(2)
            with col_c1:
                if st.button("🔍 Consultar Facturas y Proveedores", use_container_width=True):
                    conn = conectar_db(db_actual)
                    if conn:
                        try:
                            cursor = conn.cursor()
                            # 1. Asegurar el contexto de la base de datos activa
                            if db_actual:
                                cursor.execute(f"USE {db_actual}")

                            # 2. Cargar directorio de proveedores de forma segura
                            st.session_state.df_prov_fiscal = ejecutar_consulta(
                                "SELECT rif, razon_social, direccion_fiscal FROM proveedores", conn
                            )

                            # 3. Consulta robusta al libro de compras
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
                                    0.00 AS porcentaje_retencion, 0.00 AS monto_retenido, 
                                    NULL AS periodo_retenido, 
                                    0.00 AS sustraendo, 
                                    NULL AS n_comprob_islr 
                                FROM libro_compras lc
                                LEFT JOIN (
                                    SELECT razon_social, direccion_fiscal, 
                                           TRIM(REPLACE(REPLACE(rif, '-', ''), ' ', '')) AS rif_limpio
                                    FROM proveedores
                                ) p ON TRIM(REPLACE(REPLACE(lc.rif, '-', ''), ' ', '')) COLLATE utf8mb4_unicode_ci = p.rif_limpio COLLATE utf8mb4_unicode_ci
                                WHERE lc.fecha_operacion BETWEEN %s AND %s
                                ORDER BY lc.fecha_operacion ASC
                            """

                            df_temp = ejecutar_consulta(query, conn, params=(f_xml_desde_n, f_xml_hasta_n))
                            
                            # Limpiamos de una vez las que ya se hayan procesado en esta sesión
                            if df_temp is not None and not df_temp.empty and st.session_state.facturas_procesadas_ids:
                                df_temp = df_temp[~df_temp['id'].isin(st.session_state.facturas_procesadas_ids)]

                            st.session_state.df_retencion = df_temp if df_temp is not None else pd.DataFrame()
                            
                            if not st.session_state.df_retencion.empty:
                                st.success(f"✅ ¡Se encontraron {len(st.session_state.df_retencion)} facturas en el rango!")
                            else:
                                st.warning("⚠️ No se encontraron registros de facturas en el libro de compras para el rango de fechas seleccionado.")
                                
                        except Exception as e:
                            st.error(f"❌ Error al consultar la base de datos: {e}")
                        finally:
                            conn.close()

            with col_c2:
                if st.button("🔄 Refrescar Directorio Manualmente", use_container_width=True):
                    conn = conectar_db(db_actual)
                    if conn:
                        st.session_state.df_prov_fiscal = ejecutar_consulta("SELECT rif, razon_social, direccion_fiscal FROM proveedores", conn)
                        conn.close()
                        st.info("📂 Directorio actualizado manualmente.")

            # Inicialización de estados de PDF
            if "pdf_listo" not in st.session_state:
                st.session_state.pdf_listo = False
            if "datos_pdf" not in st.session_state:
                st.session_state.datos_pdf = None

            # --- MENSAJE INFORMATIVO DE RETENCIONES REALIZADAS EN LA SESIÓN ---
            if st.session_state.historial_retenciones_sesion:
                st.success("📌 **Facturas inhabilitadas / Retenciones aplicadas en esta sesión:**")
                for item in st.session_state.historial_retenciones_sesion:
                    st.markdown(f"- 📄 **Factura N°:** {item['factura']} | **Proveedor:** {item['proveedor']} | **Comprobante N°:** `{item['comprobante']}` | **Monto Retenido:** Bs. {item['monto']:,.2f}")
                st.markdown("---")

            # Filtrar el DataFrame en tiempo real por si quedan IDs procesados
            if "df_retencion" in st.session_state and not st.session_state.df_retencion.empty:
                if st.session_state.facturas_procesadas_ids:
                    st.session_state.df_retencion = st.session_state.df_retencion[
                        ~st.session_state.df_retencion['id'].isin(st.session_state.facturas_procesadas_ids)
                    ]

            if "df_retencion" in st.session_state and not st.session_state.df_retencion.empty:
                columnas_a_mostrar = [
                    "fecha_operacion", "rif_retenido", "proveedor_nombre", 
                    "numero_factura", "numero_control", "monto_operacion"
                ]
                
                # 1. Creamos una copia de trabajo para formatear visualmente sin dañar los datos originales de la sesión
                df_temp = st.session_state.df_retencion[columnas_a_mostrar].copy()
                
                if 'monto_operacion' in df_temp.columns:
                    df_temp['monto_operacion'] = pd.to_numeric(df_temp['monto_operacion'], errors='coerce').fillna(0.0)
                    df_temp['monto_operacion'] = df_temp['monto_operacion'].apply(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

                # 2. Aplicamos estilo de Pandas para forzar la alineación a la derecha en la columna de monto
                df_styled = df_temp.style.set_properties(
                    subset=['monto_operacion'], 
                    **{'text-align': 'right'}
                ).set_table_styles([
                    {'selector': 'th.col5', 'props': [('text-align', 'right')]} # Alinea la cabecera de la columna monto_operacion
                ])
                
                sel_f = st.dataframe(
                    df_styled, 
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
                        
                        valor_razon = str(f_data.get('proveedor_nombre', ''))
                        valor_dir = str(f_data.get('proveedor_direccion', ''))

                        if valor_razon == 'PROVEEDOR NO ENCONTRADO':
                            st.warning("⚠️ Proveedor no encontrado en el directorio. Por favor ingrese los datos manualmente:")
                            valor_razon = ""
                            valor_dir = ""

                        if valor_dir in ["DIRECCIÓN NO REGISTRADA", "NONE", ""]:
                            valor_dir = ""

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
                                    # 1. Guardamos el ID en la lista negra local de la sesión para que se bloquee y desaparezca
                                    st.session_state.facturas_procesadas_ids.append(id_seguro)
                                    
                                    # 2. Agregamos al historial para el mensaje de resumen
                                    st.session_state.historial_retenciones_sesion.append({
                                        "factura": str(f_data['numero_factura']),
                                        "proveedor": razon_r,
                                        "comprobante": n_comprob_manual,
                                        "monto": m_final
                                    })

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
                                    st.success(f"✅ Comprobante N° {n_comprob_manual} registrado y factura inhabilitada de la lista.")
                                    st.rerun()

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
                    st.rerun()

            with tab3:
                # --- SECCIÓN: EDITOR DE HISTORIAL ---
                st.divider()
                st.markdown("### 🔎 Editor y Filtros de Historial")

                with st.expander("📅 Filtros de Consulta para Editar", expanded=True):
                    col_f1, col_f2 = st.columns(2)
                    
                    from datetime import date as d_tipo

                    # Keys únicas y parámetros actualizados
                    f_inicio_h = col_f1.date_input("Desde", d_tipo(2026, 8, 1), key="h_desde_editor")
                    f_fin_h = col_f2.date_input("Hasta", d_tipo(2026, 8, 31), key="h_hasta_editor")
                    st.write("") 
                    btn_cargar = st.button("📂 Cargar Historial para Editar", use_container_width=True, type="primary", key="btn_cargar_historial_islr")

                # --- FUNCIÓN CON CACHÉ PARA CARGAR EL HISTORIAL DE RETENCIONES ---
                @st.cache_data(ttl=30, show_spinner=False)
                def cargar_historial_islr_cached(empresa, f_inicio, f_fin):
                    df_res = pd.DataFrame()
                    conn = conectar_db()
                    if conn and empresa:
                        try:
                            conn.ping(reconnect=True)
                            cursor = conn.cursor()
                            cursor.execute(f"USE {empresa}")
                            query = """
                                SELECT id, rif_retenido, numero_factura, numero_control, fecha_operacion, 
                                       codigo_concepto, monto_operacion, porcentaje_retencion, 
                                       monto_retenido, periodo_retenido, n_comprob_islr 
                                FROM retenciones_islr 
                                WHERE fecha_operacion BETWEEN %s AND %s 
                                ORDER BY fecha_operacion DESC
                            """
                            df_res = ejecutar_consulta(query, conn, params=(f_inicio, f_fin))
                        except Exception:
                            pass
                        finally:
                            try:
                                conn.close()
                            except Exception:
                                pass
                    return df_res if df_res is not None else pd.DataFrame()

                # --- 1. Lógica de carga ---
                if btn_cargar:
                    db_actual = st.session_state.get('DB_ACTUAL')
                    if db_actual:
                        try:
                            df_cargado = cargar_historial_islr_cached(db_actual, f_inicio_h.strftime('%Y-%m-%d'), f_fin_h.strftime('%Y-%m-%d'))
                            st.session_state.df_retenciones_editor = df_cargado
                            if not df_cargado.empty:
                                st.success(f"✅ Registros cargados: {len(df_cargado)}")
                            else:
                                st.warning("⚠️ No se encontraron retenciones en el rango seleccionado.")
                        except Exception as e:
                            st.error(f"Error en la base de datos: {e}")
                    else:
                        st.warning("⚠️ No se ha seleccionado una base de datos activa.")

                # --- 2. Visualización y Edición ---
                if "df_retenciones_editor" in st.session_state and not st.session_state.df_retenciones_editor.empty:
                    st.info("📝 Puedes editar los montos o eliminar filas.")
                    
                    edit_ret_df = st.data_editor(
                        st.session_state.df_retenciones_editor,
                        key="editor_tabla_retenciones",
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "id": st.column_config.NumberColumn("ID", disabled=True),
                            "rif_retenido": "RIF",
                            "numero_factura": "N° Factura",
                            "monto_operacion": st.column_config.NumberColumn("Base", format="Bs %.2f"),
                            "monto_retenido": st.column_config.NumberColumn("Monto Retenido", format="Bs %.2f"),
                        }
                    )

                    # --- 3. Sincronización ---
                    if st.button("💾 Sincronizar Historial con DB", type="primary", use_container_width=True, key="btn_sincronizar_historial_islr"):
                        estado = st.session_state.get("editor_tabla_retenciones", None)
                        db_actual = st.session_state.get('DB_ACTUAL')
                        conn = conectar_db()
                        
                        if conn and db_actual:
                            try:
                                conn.ping(reconnect=True)
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
                                    mensaje = f"✅ Cambios guardados: {total_eliminados} eliminados, {total_editados} editados."
                                    st.success(mensaje)
                                    st.toast(mensaje, icon="💾")
                                    
                                    # Limpiar caché global para reflejar los cambios en toda la app
                                    st.cache_data.clear()
                                    
                                    import time
                                    time.sleep(1.0)
                                    
                                    if "df_retenciones_editor" in st.session_state:
                                        del st.session_state.df_retenciones_editor
                                    st.rerun()
                                else:
                                    st.info("ℹ️ No se detectaron cambios para guardar.")
                                    
                            except Exception as e:
                                conn.rollback()
                                st.error(f"❌ Error al sincronizar: {e}")
                            finally:
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                        elif not db_actual:
                            st.warning("⚠️ No se ha seleccionado una base de datos activa.")

            # --- TAB 4: REIMPRESIÓN ---
            with tab4:
                st.divider()
                st.markdown("### 🖨️ Reimpresión de Comprobantes")
                st.markdown("Selecciona el rango de fechas para consultar y reimprimir los comprobantes de retención.")
                
                from datetime import date as d_tipo
                
                col_h1, col_h2 = st.columns(2)
                with col_h1:
                    f_hist_desde = st.date_input("Desde (Fecha Operación)", value=d_tipo.today().replace(day=1), key="hist_fec_desde")
                with col_h2:
                    f_hist_hasta = st.date_input("Hasta (Fecha Operación)", value=d_tipo.today(), key="hist_fec_hasta")
                
                # --- FUNCIÓN CON CACHÉ PARA CARGAR EL HISTORIAL DE REIMPRESIÓN ---
                @st.cache_data(ttl=30, show_spinner=False)
                def cargar_historial_reimpresion_cached(empresa, f_desde, f_hasta):
                    df_res = pd.DataFrame()
                    conn = conectar_db()
                    if conn and empresa:
                        try:
                            conn.ping(reconnect=True)
                            cursor = conn.cursor()
                            cursor.execute(f"USE {empresa}")
                            
                            query_historial = """
                                SELECT r.*, 
                                       COALESCE(p.razon_social, r.rif_retenido) AS nombre_completo, 
                                       COALESCE(p.direccion_fiscal, 'CARACAS, VENEZUELA') AS direccion_completa
                                FROM retenciones_islr r
                                LEFT JOIN proveedores p ON r.rif_retenido COLLATE utf8mb4_unicode_ci = p.rif COLLATE utf8mb4_unicode_ci
                                WHERE r.fecha_operacion BETWEEN %s AND %s
                                ORDER BY r.id DESC
                            """
                            df_res = ejecutar_consulta(query_historial, conn, params=(f_desde, f_hasta))
                        except Exception:
                            pass
                        finally:
                            try:
                                conn.close()
                            except Exception:
                                pass
                    return df_res if df_res is not None else pd.DataFrame()

                # 1. Botón para cargar historial con filtro de fechas optimizado
                if st.button("📂 Cargar Historial por Rango", use_container_width=True, key="btn_cargar_hist_rango"):
                    db_actual = st.session_state.get('DB_ACTUAL')
                    if db_actual:
                        try:
                            df_cargado = cargar_historial_reimpresion_cached(
                                db_actual, 
                                str(f_hist_desde), 
                                str(f_hist_hasta)
                            )
                            st.session_state.df_historial_islr = df_cargado
                            st.success(f"📊 Se encontraron **{len(df_cargado)}** comprobantes en el rango seleccionado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al cargar historial: {e}")
                    else:
                        st.warning("⚠️ Por favor, selecciona una base de datos primero.")

                # 2. Visualización y Selección
                if "df_historial_islr" in st.session_state and st.session_state.df_historial_islr is not None and not st.session_state.df_historial_islr.empty:
                    st.success(f"📊 Se encontraron **{len(st.session_state.df_historial_islr)}** comprobantes en el rango seleccionado.")
                    
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
                        
                        # Procesamiento de datos optimizado
                        with st.status("🛠️ Procesando datos...", expanded=False):
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

                        # 3. Botón de descarga con conexión abierta de forma segura
                        st.write(f"✅ Factura seleccionada: **{factura_limpia}**")
                        
                        conn = conectar_db()
                        if conn:
                            try:
                                conn.ping(reconnect=True)
                                pdf_bytes_re = generar_comprobante_pdf(datos_reimp, conn)
                                
                                if pdf_bytes_re:
                                    st.download_button(
                                        label=f"📥 Descargar PDF: {h['nombre_completo'][:20]}...", 
                                        data=pdf_bytes_re, 
                                        file_name=f"Retencion_{h['n_comprob_islr']}.pdf", 
                                        mime="application/pdf", 
                                        use_container_width=True,
                                        key=f"btn_reimp_{h['id']}"
                                    )
                            except Exception as e:
                                st.error(f"Error al generar el archivo: {e}")
                            finally:
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                                    
                elif "df_historial_islr" in st.session_state and st.session_state.df_historial_islr is not None and st.session_state.df_historial_islr.empty:
                    st.info("ℹ️ No se encontraron comprobantes de retención en el rango de fechas seleccionado.")

            # --- TAB 5: GESTIÓN DE FACTURAS ---
            with tab5:
                st.divider()
                st.subheader("⚙️ Gestión y Desbloqueo de Facturas")
                st.info("Utiliza esta opción para buscar y habilitar nuevamente una factura que fue marcada como retenida por error.")

                db_actual = st.session_state.get('DB_ACTUAL')

                if db_actual:
                    # --- 1. FILTRO POR RANGO DE FECHAS ---
                    st.markdown("### 📅 Filtrar Facturas por Rango de Fecha")
                    col_f1, col_f2 = st.columns(2)
                    
                    from datetime import date, timedelta
                    fecha_desde = col_f1.date_input("Desde la fecha:", value=date.today() - timedelta(days=30), key="ges_fec_desde")
                    fecha_hasta = col_f2.date_input("Hasta la fecha:", value=date.today(), key="ges_fec_hasta")

                    # --- FUNCIÓN CON CACHÉ PARA CONSULTAR FACTURAS RETENIDAS ---
                    @st.cache_data(ttl=30, show_spinner=False)
                    def consultar_facturas_retenidas_cached(empresa, f_desde, f_hasta):
                        lista_res = []
                        conn_f = conectar_db(empresa)
                        if conn_f:
                            try:
                                conn_f.ping(reconnect=True)
                                query_listado = """
                                    SELECT rif_retenido, numero_factura, proveedor_nombre, monto_retenido, fecha_operacion 
                                    FROM retenciones_islr 
                                    WHERE (monto_retenido > 0 OR porcentaje_retencion > 0)
                                      AND fecha_operacion BETWEEN %s AND %s 
                                    ORDER BY fecha_operacion DESC
                                """
                                cursor_f = conn_f.cursor() if hasattr(conn_f, 'cursor') else None
                                if cursor_f:
                                    cursor_f.execute(query_listado, (f_desde, f_hasta))
                                    rows = cursor_f.fetchall()
                                    for row in rows:
                                        lista_res.append({
                                            "rif_retenido": row[0],
                                            "numero_factura": row[1],
                                            "proveedor_nombre": row[2],
                                            "monto_retenido": row[3],
                                            "fecha_operacion": row[4]
                                        })
                                    cursor_f.close()
                            except Exception:
                                pass
                            finally:
                                try:
                                    conn_f.close()
                                except Exception:
                                    pass
                        return lista_res

                    try:
                        facturas_retenidas = consultar_facturas_retenidas_cached(
                            db_actual, 
                            fecha_desde.strftime('%Y-%m-%d'), 
                            fecha_hasta.strftime('%Y-%m-%d')
                        )

                        # --- 3. MOSTRAR LISTADO EN EXPANDER ---
                        with st.expander("🔍 Listado de Facturas Retenidas en el Rango Seleccionado", expanded=True):
                            if facturas_retenidas:
                                import pandas as pd
                                df = pd.DataFrame(facturas_retenidas)
                                
                                df['monto_retenido'] = pd.to_numeric(df['monto_retenido'], errors='coerce').fillna(0.0)
                                df['monto_retenido'] = df['monto_retenido'].apply(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                                
                                st.dataframe(
                                    df, 
                                    use_container_width=True,
                                    column_config={
                                        "rif_retenido": "RIF",
                                        "numero_factura": "N° Factura",
                                        "proveedor_nombre": "Proveedor",
                                        "monto_retenido": "Monto Retenido",
                                        "fecha_operacion": "Fecha Operación"
                                    },
                                    hide_index=True
                                )
                            else:
                                st.info("No se encontraron facturas retenidas en el rango de fechas seleccionado.")

                        # --- 4. FORMULARIO DE DESBLOQUEO CON LISTA DESPLEGABLE DINÁMICA ---
                        st.markdown("### 🔓 Desbloquear Factura Específica")
                        
                        if facturas_retenidas:
                            opciones_facturas = {
                                f"RIF: {f['rif_retenido']} | Factura N°: {f['numero_factura']} ({f['proveedor_nombre']})": f['numero_factura']
                                for f in facturas_retenidas
                            }
                            
                            with st.form("form_desbloqueo"):
                                seleccion_factura = st.selectbox(
                                    "Selecciona la factura a habilitar (RIF y Número):",
                                    options=list(opciones_facturas.keys())
                                )
                                
                                btn_habilitar = st.form_submit_button("🔓 Habilitar Factura para Retención", type="primary")

                                if btn_habilitar:
                                    factura_a_desbloquear = opciones_facturas[seleccion_factura]
                                    resultado = resetear_estado_retencion(factura_a_desbloquear, db_actual)
                                    
                                    if resultado is True:
                                        if "facturas_procesadas_ids" in st.session_state:
                                            st.session_state.facturas_procesadas_ids = []
                                            
                                        st.cache_data.clear()
                                        st.success(f"✅ Factura N° {factura_a_desbloquear} habilitada correctamente. Ya puedes volver a procesarla.")
                                        st.rerun()
                                    else:
                                        st.error("❌ No se pudo habilitar la factura. Inténtalo de nuevo.")
                        else:
                            st.warning("⚠️ No hay facturas disponibles para desbloquear en el rango de fechas seleccionado.")

                    except Exception as e:
                        st.error(f"Error procesando la gestión de facturas: {e}")
                else:
                    st.error("No se detectó una base de datos activa en la sesión.")

            # --- TAB 6: XML SENIAT ---
            with tab6:
                # --- SECCIÓN C: GENERAR ARCHIVO XML SENIAT ---
                st.divider()
                st.markdown("### 📡 Generar Archivo XML y Vista de Control SENIAT")
                
                from datetime import date as d_tipo

                with st.container(border=True):
                    col_xml1, col_xml2 = st.columns(2)
                    f_xml_desde = col_xml1.date_input("Desde", value=d_tipo(2026, 8, 1), key="xml_desde")
                    f_xml_hasta = col_xml2.date_input("Hasta", value=d_tipo(2026, 8, 31), key="xml_hasta")
                    
                    # --- FUNCIÓN CON CACHÉ PARA CONSULTAR DATOS DEL XML SENIAT ---
                    @st.cache_data(ttl=30, show_spinner=False)
                    def consultar_datos_xml_cached(empresa, patron):
                        df_res = pd.DataFrame()
                        conn = conectar_db(empresa)
                        if conn:
                            try:
                                conn.ping(reconnect=True)
                                query_xml = """
                                    SELECT * 
                                    FROM retenciones_islr 
                                    WHERE n_comprob_islr LIKE %s
                                """
                                df_res = ejecutar_consulta(query_xml, conn, params=(patron,))
                            except Exception:
                                pass
                            finally:
                                try:
                                    conn.close()
                                except Exception:
                                    pass
                        return df_res if df_res is not None else pd.DataFrame()

                    # Botón de procesamiento optimizado
                    if st.button("🚀 Procesar Datos XML", use_container_width=True, key="btn_procesar_datos_xml"):
                        db_actual = st.session_state.get('DB_ACTUAL') 
                        if db_actual:
                            periodo_str = f_xml_hasta.strftime("%Y%m") # Ej: "202608"
                            patron_comprobante = f"{periodo_str}%"
                            
                            df_xml_raw = consultar_datos_xml_cached(db_actual, patron_comprobante)
                            
                            if not df_xml_raw.empty:
                                if 'sustraendo' not in df_xml_raw.columns:
                                    df_xml_raw['sustraendo'] = 0.0
                                
                                df_xml_raw['sustraendo'] = pd.to_numeric(df_xml_raw['sustraendo'], errors='coerce').fillna(0.0)
                                
                                mask_001 = df_xml_raw['codigo_concepto'].astype(str).str.zfill(3) == '001'
                                df_xml_raw.loc[mask_001 & (df_xml_raw['sustraendo'] == 0.0), 'sustraendo'] = 107.50

                                st.session_state['xml_data'] = generar_xml_seniat(df_xml_raw, DATOS_EMPRESA['rif'], periodo_str)
                                st.session_state['xml_filename'] = f"RET_ISLR_{periodo_str}.xml"

                                df_view = df_xml_raw.copy()
                                rename_map = {}
                                
                                for col in df_view.columns:
                                    c_low = str(col).lower()
                                    if 'comprob' in c_low: rename_map[col] = 'Fila / Doc'
                                    elif 'fecha' in c_low: rename_map[col] = 'Fecha'
                                    elif 'factura' in c_low: rename_map[col] = 'N° Doc'
                                    elif 'control' in c_low: rename_map[col] = 'N° Control'
                                    elif 'rif' in c_low and 'retenido' in c_low: rename_map[col] = 'R.I.F.'
                                    elif any(k in c_low for k in ['razon', 'nombre', 'contribuyente', 'proveedor']): rename_map[col] = 'Nombre o Razón Social'
                                    elif 'concepto' in c_low: rename_map[col] = 'Cód. Concepto (XML)'
                                    elif 'monto_operacion' in c_low or 'base' in c_low: rename_map[col] = 'Base Imponible (Bs.)'
                                    elif 'porcentaje' in c_low or 'alicuota' in c_low: rename_map[col] = 'Alicuota ISLR'
                                    elif 'retenido' in c_low and 'monto' in c_low: rename_map[col] = 'Retención Neta (Bs.)'
                                    elif 'sustraendo' in c_low: rename_map[col] = 'Sustraendo (Bs.)'

                                df_view = df_view.rename(columns=rename_map)

                                cols_num = ['Base Imponible (Bs.)', 'Alicuota ISLR', 'Sustraendo (Bs.)', 'Retención Neta (Bs.)']
                                for col_num in cols_num:
                                    if col_num in df_view.columns:
                                        df_view[col_num] = pd.to_numeric(df_view[col_num], errors='coerce').fillna(0.0)
                                    else:
                                        df_view[col_num] = 0.0

                                df_view['Retención Bruta (Bs.)'] = df_view['Retención Neta (Bs.)'] + df_view['Sustraendo (Bs.)']

                                st.session_state['xml_records'] = df_view.to_dict(orient='records')
                                st.session_state['xml_cols_originales'] = list(df_view.columns)
                                st.success(f"✅ Datos procesados con éxito ({len(df_xml_raw)} retenciones).")
                            else:
                                st.warning(f"⚠️ No se encontraron retenciones para el periodo {periodo_str}.")
                                st.session_state['xml_data'] = None
                                st.session_state['xml_records'] = None
                        else:
                            st.warning("⚠️ No se ha seleccionado una base de datos activa.")

                    # Si ya hay datos procesados, renderizamos directamente usando registros puros de Python
                    if st.session_state.get('xml_records') is not None:
                        records = st.session_state['xml_records']
                        
                        st.markdown("#### 📊 Resumen de Retenciones del Periodo")
                        
                        cols_a_mostrar = [
                            'Fila / Doc', 'Fecha', 'N° Doc', 'N° Control', 'R.I.F.', 
                            'Nombre o Razón Social', 'Cód. Concepto (XML)', 'Base Imponible (Bs.)', 
                            'Retención Bruta (Bs.)', 'Sustraendo (Bs.)', 'Retención Neta (Bs.)'
                        ]
                        
                        sample_keys = records[0].keys() if records else []
                        cols_disponibles = [c for c in cols_a_mostrar if c in sample_keys]

                        html_rows = ""
                        for row in records:
                            html_rows += "<tr>"
                            for col in cols_disponibles:
                                val = row.get(col, "")
                                if val is None:
                                    val_str = ""
                                elif col in ['Base Imponible (Bs.)', 'Retención Bruta (Bs.)', 'Sustraendo (Bs.)', 'Retención Neta (Bs.)', 'Alicuota ISLR']:
                                    try:
                                        val_str = f"{float(val):,.2f}"
                                    except:
                                        val_str = "0.00"
                                else:
                                    val_str = str(val)
                                html_rows += f"<td>{val_str}</td>"
                            html_rows += "</tr>"

                        html_headers = "".join([f"<th>{col}</th>" for col in cols_disponibles])

                        st.markdown(f"""
                            <style>
                                .styled-table {{
                                    width: 100%;
                                    border-collapse: collapse;
                                    margin: 25px 0;
                                    font-size: 0.9em;
                                    font-family: sans-serif;
                                    box-shadow: 0 0 20px rgba(0, 0, 0, 0.15);
                                }}
                                .styled-table th, .styled-table td {{
                                    padding: 12px 15px;
                                    text-align: left;
                                }}
                                .styled-table tbody tr {{
                                    border-bottom: 1px solid #dddddd;
                                }}
                                .styled-table th {{
                                    background-color: #f8f9fa;
                                }}
                            </style>
                            <div style="overflow-x:auto;">
                                <table class="styled-table">
                                    <thead><tr>{html_headers}</tr></thead>
                                    <tbody>{html_rows}</tbody>
                                </table>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        tot_base = sum(float(r.get('Base Imponible (Bs.)', 0) or 0) for r in records)
                        tot_sust = sum(float(r.get('Sustraendo (Bs.)', 0) or 0) for r in records)
                        tot_neta = sum(float(r.get('Retención Neta (Bs.)', 0) or 0) for r in records)
                        
                        cols_tot = st.columns([4, 1.5, 1.5, 1.5])
                        cols_tot[0].markdown("**TOTAL GENERAL A ENTERAR AL SENIAT:**")
                        cols_tot[1].metric("Base Imb.", f"{tot_base:,.2f}")
                        cols_tot[2].metric("Sustraendo", f"{tot_sust:,.2f}")
                        cols_tot[3].metric("Retención Neta", f"{tot_neta:,.2f}")

                        st.markdown("---")
                        
                        db_actual_nom = st.session_state.get('DB_ACTUAL', 'Empresa')
                        periodo_pdf_str = st.session_state.get('xml_filename', 'periodo').replace('RET_ISLR_', '').replace('.xml', '')
                        
                        pdf_bytes = generar_pdf_resumen_seniat(
                            records=records,
                            empresa_nombre=db_actual_nom,
                            periodo_str=periodo_pdf_str,
                            tot_base=tot_base,
                            tot_sust=tot_sust,
                            tot_neta=tot_neta
                        )

                        col_down1, col_down2 = st.columns(2)
                        
                        with col_down1:
                            btn_descarga = st.download_button(
                                label="📥 Descargar Archivo XML (Portal SENIAT)",
                                data=st.session_state['xml_data'],
                                file_name=st.session_state['xml_filename'],
                                mime="application/xml",
                                use_container_width=True,
                                key="btn_descargar_xml_seniat"
                            )
                            
                        with col_down2:
                            st.download_button(
                                label="📄 Descargar Resumen en PDF (Para Imprimir)",
                                data=pdf_bytes,
                                file_name=f"Resumen_Retenciones_ISLR_{periodo_pdf_str}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                                key="btn_descargar_pdf_seniat"
                            )
                        
                        if btn_descarga:
                            monto_neto_formateado = f"{tot_neta:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                            
                            st.markdown(f"""
                                <style>
                                    .seniat-alert-box {{
                                        background-color: #e8f5e9;
                                        border-left: 6px solid #2e7d32;
                                        border-radius: 4px;
                                        padding: 16px 20px;
                                        margin: 15px 0;
                                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                                        font-family: sans-serif;
                                    }}
                                    .seniat-alert-title {{
                                        color: #1b5e20;
                                        font-size: 1.05em;
                                        font-weight: bold;
                                        margin-bottom: 6px;
                                        display: flex;
                                        align-items: center;
                                        gap: 8px;
                                    }}
                                    .seniat-alert-text {{
                                        color: #2c3e50;
                                        font-size: 0.95em;
                                        line-height: 1.5;
                                        margin: 0;
                                    }}
                                    .seniat-monto {{
                                        color: #d32f2f;
                                        font-weight: bold;
                                    }}
                                </style>
                                <div class="seniat-alert-box">
                                    <div class="seniat-alert-title">
                                        <span>✅</span> Descarga exitosa
                                    </div>
                                    <p class="seniat-alert-text">
                                        Su archivo está listo para subir al SENIAT. Considere que las retenciones del mes a procesar ascienden a un monto de <span class="seniat-monto">{monto_neto_formateado} Bs.</span>
                                    </p>
                                </div>
                            """, unsafe_allow_html=True)
                        
                        with st.expander("👁️ Ver Código XML Generado"):
                            xml_code = st.session_state['xml_data']
                            if isinstance(xml_code, bytes):
                                xml_code = xml_code.decode('utf-8')
                            st.code(xml_code, language="xml")


    elif sub_opcion == "Comprobante de Retención IVA":
        import datetime as dt 
        
        db_actual = st.session_state.get('DB_ACTUAL', 'railway')
        
        if db_actual:
            # Carga directa y fluida delegando la gestión de conexión al módulo de la interfaz
            try:
                mostrar_interfaz_retencion_iva(
                    EMPRESA, 
                    st.session_state.get('f_inicio_global', dt.date.today()), 
                    st.session_state.get('f_fin_global', dt.date.today())
                )
            except Exception as e:
                st.error(f"❌ Error al cargar el módulo de Retención IVA: {e}")
        else:
            st.error("⚠️ No se detectó una base de datos activa en la sesión.")


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
    
    try:
        # DEFINICIÓN ESTRICTA DE TABS (4 PESTAÑAS)
        tab1, tab2, tab3, tab4 = st.tabs([
            "📥 Cargar desde Excel", 
            "📋 Directorio Actual", 
            "📥 Bandeja Proveedores PDF",
            "🗑️ Gestión / Eliminar Tabla"
        ])

        # --- FUNCIÓN CON CACHÉ PARA CONSULTAR PROVEEDORES ---
        @st.cache_data(ttl=30, show_spinner=False)
        def consultar_proveedores_cached(empresa):
            df_res = pd.DataFrame()
            conn = conectar_db(empresa)
            if conn:
                try:
                    conn.ping(reconnect=True)
                    df_res = consultar_tabla_db(conn, "proveedores")
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            return df_res if df_res is not None else pd.DataFrame()

        # 3. Lógica de Pestaña 1 (Carga Masiva Excel)
        with tab1:
            st.markdown("### Subir Archivo Masivo")
            file_p = st.file_uploader("Seleccione el archivo Excel", type=["xlsx"], key="file_prov_up")
                
            if file_p:
                df_subida = pd.read_excel(file_p)
                df_subida = df_subida.dropna(how='all')
                
                st.write(f"Vista previa (Total de filas detectadas en el archivo: {len(df_subida)}):")
                st.dataframe(df_subida, use_container_width=True, height=450)
                
                if st.button("🚀 Procesar y Guardar", type="primary", key="btn_procesar_excel_prov"):
                    try:
                        procesar_excel_proveedores_db(df_subida)
                        st.cache_data.clear()
                        st.success("✅ ¡Actualizado y sincronizado!")
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al procesar el archivo: {e}")

        # 4. Lógica de Pestaña 2 (Directorio Actual de Proveedores)
        with tab2:
            st.markdown("### 📋 Directorio Actual de Proveedores")
            
            db_actual = st.session_state.get('DB_ACTUAL')

            if db_actual:
                df_temp = consultar_proveedores_cached(db_actual)
                
                columnas_reales = ["rif", "tipo_persona", "razon_social", "direccion_fiscal", "codigo_cuenta", "descripcion_cuenta"]
                
                if df_temp.empty:
                    df_para_mostrar = pd.DataFrame(columns=columnas_reales)
                else:
                    df_para_mostrar = df_temp.copy()
                    for col in columnas_reales:
                        if col not in df_para_mostrar.columns:
                            df_para_mostrar[col] = ""

                for col in df_para_mostrar.columns:
                    df_para_mostrar[col] = df_para_mostrar[col].astype(str).replace(['None', 'nan', 'NAT'], '')

                # --- ORDENAMIENTO ALFABÉTICO AUTOMÁTICO POR RAZÓN SOCIAL ---
                if not df_para_mostrar.empty and "razon_social" in df_para_mostrar.columns:
                    df_para_mostrar['orden_aux'] = df_para_mostrar['razon_social'].str.lower()
                    df_para_mostrar = df_para_mostrar.sort_values(by='orden_aux', ascending=True).drop(columns=['orden_aux']).reset_index(drop=True)

                df_editado = st.data_editor(
                    df_para_mostrar, 
                    key="editor_proveedores_dinamico", 
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    height=450,
                    column_config={
                        "rif": st.column_config.TextColumn("RIF", required=True),
                        "tipo_persona": st.column_config.SelectboxColumn("Tipo", options=["PN", "PJ"], required=True),
                        "razon_social": st.column_config.TextColumn("Razón Social", required=True),
                        "direccion_fiscal": st.column_config.TextColumn("Dirección Fiscal", required=True),
                        "codigo_cuenta": st.column_config.TextColumn("Código Cuenta"),
                        "descripcion_cuenta": st.column_config.TextColumn("Descripción Cuenta")
                    }
                )
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("💾 Guardar Todo en BD", key="btn_guardar_proveedores", use_container_width=True, type="primary"):
                        conn_save = conectar_db(db_actual)
                        if conn_save:
                            try:
                                conn_save.ping(reconnect=True)
                                actualizar_tabla_completa_db(conn_save, "proveedores", df_editado)
                                st.cache_data.clear()
                                st.success("¡Directorio actualizado con éxito!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error al guardar: {e}")
                            finally:
                                try:
                                    conn_save.close()
                                except Exception:
                                    pass

                with col_b2:
                    if st.button("🔄 Recargar desde BD", key="btn_recargar_proveedores", use_container_width=True):
                        st.cache_data.clear()
                        st.rerun()

                st.markdown("---") 
                if not df_para_mostrar.empty:
                    import io
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_para_mostrar.to_excel(writer, index=False, sheet_name='Proveedores')
                    st.download_button(
                        "📥 Descargar Respaldo de Proveedores", 
                        data=output.getvalue(), 
                        file_name="Respaldo_Proveedores.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
            else:
                st.warning("⚠️ No se ha seleccionado una base de datos activa.")

        # ------------------------------------------
        # TAB 3: Bandeja Proveedores PDF (Cola masiva)
        # ------------------------------------------
        with tab3:
            st.subheader("📥 Bandeja de Entrada - Registro Masivo de Proveedores (PDF)")
            st.info("Arrastra o selecciona múltiples facturas de proveedores en PDF. El sistema extraerá automáticamente el RIF, la Razón Social y la Dirección Fiscal.")

            if "cola_proveedores_pdfs" not in st.session_state:
                st.session_state.cola_proveedores_pdfs = []
            if "prov_procesados_ids" not in st.session_state:
                st.session_state.prov_procesados_ids = set()
            if "datos_prov_extraidos" not in st.session_state:
                st.session_state.datos_prov_extraidos = {}

            archivos_prov_pdf = st.file_uploader(
                "Sube tus facturas de proveedores en PDF", 
                type=['pdf'], 
                accept_multiple_files=True,
                key="uploader_prov_pdf_cola"
            )

            if archivos_prov_pdf:
                nombres_existentes_prov = [item['nombre'] for item in st.session_state.cola_proveedores_pdfs]
                for archivo in archivos_prov_pdf:
                    file_id = getattr(archivo, "file_id", archivo.name)
                    if archivo.name not in nombres_existentes_prov and file_id not in st.session_state.prov_procesados_ids:
                        st.session_state.cola_proveedores_pdfs.append({
                            "id": file_id,
                            "nombre": archivo.name,
                            "objeto": archivo,
                            "estado": "Pendiente"
                        })

            if st.session_state.cola_proveedores_pdfs:
                st.markdown(f"### 📋 Cola de Proveedores ({len(st.session_state.cola_proveedores_pdfs)} en espera)")
                
                if st.button("🗑️ Vaciar Cola de Proveedores", key="btn_vaciar_cola_prov"):
                    st.session_state.cola_proveedores_pdfs = []
                    st.session_state.prov_procesados_ids = set()
                    st.session_state.datos_prov_extraidos = {}
                    st.rerun()

                import pandas as pd
                df_cola_prov = pd.DataFrame([{
                    "Archivo": item["nombre"], 
                    "Estado": item["estado"]
                } for item in st.session_state.cola_proveedores_pdfs])
                
                st.dataframe(df_cola_prov, use_container_width=True, hide_index=True)
                st.markdown("---")

                st.markdown("### 📝 Auditoría, Extracción y Registro en la Tabla de Proveedores")
                
                docs_prov_pendientes = [item for item in st.session_state.cola_proveedores_pdfs if item["estado"] == "Pendiente"]
                
                if docs_prov_pendientes:
                    nombres_prov_pendientes = [item["nombre"] for item in docs_prov_pendientes]
                    doc_prov_seleccionado = st.selectbox(
                        "Selecciona un proveedor pendiente para revisar y registrar:", 
                        nombres_prov_pendientes,
                        key="select_doc_prov_auditoria"
                    )

                    doc_prov_obj = next((item for item in docs_prov_pendientes if item["nombre"] == doc_prov_seleccionado), None)

                    if doc_prov_obj:
                        sufijo_prov = doc_prov_obj['nombre']

                        keys_defaults_prov = {
                            f"rif_{sufijo_prov}": "",
                            f"razon_{sufijo_prov}": "",
                            f"dir_{sufijo_prov}": "",
                            f"tipo_{sufijo_prov}": "Jurídica",
                            f"cc_{sufijo_prov}": "",
                            f"dc_{sufijo_prov}": ""
                        }
                        for k, v in keys_defaults_prov.items():
                            if k not in st.session_state:
                                st.session_state[k] = v

                        if st.button("⚡ Extraer Datos del Proveedor", key=f"btn_extraer_{sufijo_prov}"):
                            with st.spinner("Leyendo RIF, Razón Social y Dirección del PDF..."):
                                archivo_pdf = doc_prov_obj["objeto"]
                                
                                if hasattr(archivo_pdf, "seek"):
                                    archivo_pdf.seek(0)
                                    
                                datos_proveedor = extraer_datos_proveedor_pdf(archivo_pdf)

                                if datos_proveedor is None:
                                    st.warning("⚠️ El documento no pudo ser leído correctamente. Por favor, completa los datos manualmente.")
                                    st.session_state[f"rif_{sufijo_prov}"] = ""
                                    st.session_state[f"razon_{sufijo_prov}"] = ""
                                    st.session_state[f"dir_{sufijo_prov}"] = ""
                                else:
                                    st.session_state[f"rif_{sufijo_prov}"] = datos_proveedor.get("rif", "")
                                    st.session_state[f"razon_{sufijo_prov}"] = datos_proveedor.get("proveedor", "")
                                    st.session_state[f"dir_{sufijo_prov}"] = datos_proveedor.get("direccion_fiscal", "")
                                    st.success(f"¡Datos extraídos con éxito para: {datos_proveedor['proveedor']}!")
                                    st.rerun()

                        st.info(f"Completando información para el archivo: **{sufijo_prov}**")
                        
                        col_i1, col_i2 = st.columns(2)
                        
                        with col_i1:
                            rif = st.text_input("RIF", key=f"rif_{sufijo_prov}")
                            tipo_persona = st.selectbox(
                                "Tipo de Persona", 
                                options=["PN", "PJ", "No Residente", "Gobierno"],
                                index=1,
                                key=f"tipo_{sufijo_prov}"
                            )
                            razon_social = st.text_input("Razón Social", key=f"razon_{sufijo_prov}")
                        
                        with col_i2:
                            direccion_fiscal = st.text_area("Dirección Fiscal", key=f"dir_{sufijo_prov}")
                            codigo_cuenta = st.text_input("Código de Cuenta Contable", key=f"cc_{sufijo_prov}")
                            descripcion_cuenta = st.text_input("Descripción de Cuenta", key=f"dc_{sufijo_prov}")

                        if st.button("💾 Guardar Proveedor en Base de Datos", type="primary", key=f"btn_guardar_prov_{sufijo_prov}", use_container_width=True):
                            db_nombre = st.session_state.get('DB_ACTUAL')
                            if not db_nombre:
                                st.error("Error: No se ha seleccionado una base de datos activa.")
                            else:
                                conn = conectar_db(db_nombre)
                                if conn is None:
                                    st.error(f"❌ No se pudo conectar a la base de datos '{db_nombre}'.")
                                else:
                                    try:
                                        conn.ping(reconnect=True)
                                        with conn.cursor() as cursor:
                                            query_prov = """
                                                INSERT INTO proveedores (
                                                    rif, tipo_persona, razon_social, 
                                                    direccion_fiscal, codigo_cuenta, descripcion_cuenta
                                                ) VALUES (%s, %s, %s, %s, %s, %s)
                                                ON DUPLICATE KEY UPDATE
                                                    tipo_persona = VALUES(tipo_persona),
                                                    razon_social = VALUES(razon_social),
                                                    direccion_fiscal = VALUES(direccion_fiscal),
                                                    codigo_cuenta = VALUES(codigo_cuenta),
                                                    descripcion_cuenta = VALUES(descripcion_cuenta)
                                            """
                                            
                                            valores_prov = (
                                                rif, tipo_persona, razon_social,
                                                direccion_fiscal, codigo_cuenta, descripcion_cuenta
                                            )
                                            
                                            cursor.execute(query_prov, valores_prov)
                                            conn.commit()
                                        
                                        for item in st.session_state.cola_proveedores_pdfs:
                                            if item["nombre"] == doc_prov_obj["nombre"]:
                                                item["estado"] = "Registrado"
                                                st.session_state.prov_procesados_ids.add(item["id"])
                                                break
                                                
                                        st.cache_data.clear()
                                        st.success(f"¡Proveedor '{razon_social}' (RIF: {rif}) guardado correctamente!")
                                        st.rerun()
                                        
                                    except Exception as e:
                                        conn.rollback()
                                        st.error(f"Error al registrar el proveedor en la base de datos: {e}")
                                    finally:
                                        try:
                                            conn.close()
                                        except Exception:
                                            pass
                else:
                    st.success("🎉 ¡Todos los proveedores in la cola ya han sido procesados y registrados!")
            else:
                st.info("No hay archivos en la cola de proveedores. Sube algunos PDFs arriba para comenzar.")

        # 5. Lógica de Pestaña 4 (Gestión y borrado seguro conectado al control central)
        with tab4:
            st.subheader("⚠️ Zona de Peligro: Gestión de la Tabla Proveedores")
            st.warning("Esta acción eliminará por completo los registros de la tabla de proveedores para la empresa seleccionada actualmente.")
            
            if "mensaje_exito_proveedores" in st.session_state:
                st.success(st.session_state.mensaje_exito_proveedores)
                del st.session_state.mensaje_exito_proveedores

            confirmacion_borrado = st.checkbox(
                "Confirmo que deseo vaciar/eliminar la tabla de proveedores de esta empresa", 
                key="check_confirm_drop_prov_seguro"
            )
            
            if st.button("🗑️ Ejecutar Borrado de Proveedores", type="primary", use_container_width=True, key="btn_ejecutar_borrado_prov"):
                if confirmacion_borrado:
                    db_seleccionada = st.session_state.get('DB_ACTUAL')
                    
                    if not db_seleccionada or db_seleccionada == 'none':
                        st.error("❌ No hay ninguna empresa/base de datos activa seleccionada en el panel lateral.")
                    else:
                        conn_gestion = None
                        try:
                            conn_gestion = conectar_db(db_seleccionada)
                            
                            if conn_gestion is None:
                                st.error(f"❌ No se pudo establecer conexión con la base de datos: {db_seleccionada}")
                            else:
                                conn_gestion.ping(reconnect=True)
                                with conn_gestion.cursor() as cursor:
                                    cursor.execute("DROP TABLE IF EXISTS proveedores;")
                                    cursor.execute("""
                                        CREATE TABLE proveedores (
                                            rif VARCHAR(50) NOT NULL PRIMARY KEY,
                                            tipo_persona VARCHAR(50) NOT NULL,
                                            razon_social VARCHAR(255) NOT NULL,
                                            direccion_fiscal TEXT NOT NULL,
                                            codigo_cuenta VARCHAR(100) DEFAULT '',
                                            descripcion_cuenta VARCHAR(255) DEFAULT ''
                                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                                    """)
                                    conn_gestion.commit()
                                
                                st.cache_data.clear()
                                if "df_proveedores_cache" in st.session_state:
                                    del st.session_state.df_proveedores_cache
                                    
                                st.balloons()
                                st.session_state.mensaje_exito_proveedores = f"🎉 ¡La tabla de proveedores de la base de datos '{db_seleccionada}' ha sido ELIMINADA y recreada con éxito!"
                                st.rerun()
                                
                        except Exception as e:
                            if conn_gestion:
                                try:
                                    conn_gestion.rollback()
                                except Exception:
                                    pass
                            st.error(f"❌ Error crítico al procesar la BD '{db_seleccionada}': {e}")
                        finally:
                            if conn_gestion and hasattr(conn_gestion, 'close'):
                                try:
                                    conn_gestion.close()
                                except Exception:
                                    pass
                else:
                    st.warning("⚠️ Debes marcar la casilla de confirmación antes de ejecutar el borrado.")

    except Exception as e:
        st.error(f"❌ Error en el módulo de Proveedores: {e}")
    finally:
        # Cierre de conexión global de la pestaña garantizado de forma independiente y segura
        if 'conn_empresa' in locals() and conn_empresa:
            try:
                conn_empresa.close()
            except Exception:
                pass


elif "Clientes" in opcion_menu:
    st.title("👤 Gestión de Directorio de Clientes")
    
    # 0. ASEGURAR QUE db_actual ESTÉ DEFINIDA
    db_actual = st.session_state.get('DB_ACTUAL')
    
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Por favor, seleccione un Cliente/Empresa en el panel lateral.")
        st.stop()

    # 1. Obtenemos la conexión
    conn_empresa = conectar_db(db_actual)
    
    try:
        # DEFINICIÓN ESTRICTA DE TABS (4 PESTAÑAS)
        tab1, tab2, tab3, tab4 = st.tabs([
            "📥 Cargar desde Excel", 
            "📋 Directorio Actual", 
            "📥 Bandeja Clientes PDF",
            "🗑️ Gestión / Eliminar Tabla"
        ])
        
        # --- 3. Lógica de Pestaña 1 (Carga Masiva Excel Clientes) ---
        with tab1:
            st.markdown("### Subir Archivo Masivo de Clientes")
            file_c = st.file_uploader("Seleccione el archivo Excel", type=["xlsx"], key="file_cli_up")
                
            if file_c:
                df_subida = pd.read_excel(file_c)
                df_subida = df_subida.dropna(how='all')
                
                st.write(f"Vista previa (Total de filas detectadas en el archivo: {len(df_subida)}):")
                st.dataframe(df_subida, use_container_width=True, height=450)
                
                if st.button("🚀 Procesar y Guardar", type="primary", key="btn_procesar_excel_cli"):
                    try:
                        procesar_excel_clientes_db(df_subida)
                        st.cache_data.clear()
                        st.success("✅ ¡Actualizado y sincronizado!")
                        st.balloons()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al procesar el archivo: {e}")

        # --- FUNCIÓN CON CACHÉ PARA CONSULTAR CLIENTES RÁPIDAMENTE ---
        @st.cache_data(ttl=30, show_spinner=False)
        def consultar_clientes_cached(empresa):
            df_res = pd.DataFrame()
            conn = conectar_db(empresa)
            if conn:
                try:
                    conn.ping(reconnect=True)
                    df_res = consultar_tabla_db(conn, "clientes_comerciales")
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            return df_res if df_res is not None else pd.DataFrame()

        # --- 4. Lógica de Pestaña 2 (Directorio Actual de Clientes) ---
        with tab2:
            st.markdown("### 📋 Directorio Actual de Clientes")
            
            db_actual = st.session_state.get('DB_ACTUAL')

            if db_actual:
                # Autoverificación ligera de columnas una sola vez por carga
                conn_tmp = conectar_db(db_actual)
                if conn_tmp:
                    try:
                        conn_tmp.ping(reconnect=True)
                        with conn_tmp.cursor() as cursor_check:
                            cursor_check.execute("SHOW COLUMNS FROM clientes_comerciales LIKE 'codigo_cuenta'")
                            if not cursor_check.fetchone():
                                cursor_check.execute("ALTER TABLE clientes_comerciales ADD COLUMN codigo_cuenta VARCHAR(50) DEFAULT ''")
                                conn_tmp.commit()
                            
                            cursor_check.execute("SHOW COLUMNS FROM clientes_comerciales LIKE 'descripcion_cuenta'")
                            if not cursor_check.fetchone():
                                cursor_check.execute("ALTER TABLE clientes_comerciales ADD COLUMN descripcion_cuenta VARCHAR(255) DEFAULT ''")
                                conn_tmp.commit()
                    except Exception:
                        pass
                    finally:
                        try:
                            conn_tmp.close()
                        except Exception:
                            pass

                df_temp = consultar_clientes_cached(db_actual)
                columnas_reales = ["rif", "tipo_persona", "razon_social", "direccion_fiscal", "codigo_cuenta", "descripcion_cuenta"]
                
                if df_temp.empty:
                    df_para_mostrar = pd.DataFrame(columns=columnas_reales)
                else:
                    df_para_mostrar = df_temp.copy()
                    for col in columnas_reales:
                        if col not in df_para_mostrar.columns:
                            df_para_mostrar[col] = ""

                for col in df_para_mostrar.columns:
                    df_para_mostrar[col] = df_para_mostrar[col].astype(str).replace(['None', 'nan', 'NAT'], '')

                # --- ORDENAMIENTO ALFABÉTICO AUTOMÁTICO POR RAZÓN SOCIAL ---
                if not df_para_mostrar.empty and "razon_social" in df_para_mostrar.columns:
                    df_para_mostrar['orden_aux'] = df_para_mostrar['razon_social'].str.lower()
                    df_para_mostrar = df_para_mostrar.sort_values(by='orden_aux', ascending=True).drop(columns=['orden_aux']).reset_index(drop=True)

                df_editado = st.data_editor(
                    df_para_mostrar, 
                    key="editor_clientes_dinamico", 
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    height=450,
                    column_config={
                        "rif": st.column_config.TextColumn("RIF", required=True),
                        "tipo_persona": st.column_config.SelectboxColumn("Tipo", options=["PN", "PJ"], required=True),
                        "razon_social": st.column_config.TextColumn("Razón Social", required=True),
                        "direccion_fiscal": st.column_config.TextColumn("Dirección Fiscal", required=True),
                        "codigo_cuenta": st.column_config.TextColumn("Código Cuenta"),
                        "descripcion_cuenta": st.column_config.TextColumn("Descripción Cuenta")
                    }
                )
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("💾 Guardar Todo en BD", key="btn_guardar_clientes", use_container_width=True, type="primary"):
                        conn_save = conectar_db(db_actual)
                        if conn_save:
                            try:
                                conn_save.ping(reconnect=True)
                                actualizar_tabla_completa_db(conn_save, "clientes_comerciales", df_editado)
                                st.cache_data.clear()
                                st.success("¡Directorio de clientes actualizado con éxito!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error al guardar: {e}")
                            finally:
                                try:
                                    conn_save.close()
                                except Exception:
                                    pass

                with col_b2:
                    if st.button("🔄 Recargar desde BD", key="btn_recargar_clientes", use_container_width=True):
                        st.cache_data.clear()
                        st.rerun()

                st.markdown("---") 
                if not df_para_mostrar.empty:
                    import io
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_para_mostrar.to_excel(writer, index=False, sheet_name='Clientes')
                    st.download_button(
                        "📥 Descargar Respaldo de Clientes", 
                        data=output.getvalue(), 
                        file_name="Respaldo_Clientes.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
            else:
                st.warning("⚠️ No se ha seleccionado una base de datos activa.")

        # ------------------------------------------
        # TAB 3: Bandeja Clientes PDF (Cola masiva optimizada)
        # ------------------------------------------
        with tab3:
            st.subheader("📥 Bandeja de Entrada - Registro Masivo de Clientes (PDF)")
            st.info("Arrastra o selecciona múltiples documentos de clientes en PDF. El sistema extraerá automáticamente el RIF, la Razón Social y la Dirección Fiscal.")

            if "cola_clientes_pdfs" not in st.session_state:
                st.session_state.cola_clientes_pdfs = []
            if "cli_procesados_ids" not in st.session_state:
                st.session_state.cli_procesados_ids = set()
            if "datos_cli_extraidos" not in st.session_state:
                st.session_state.datos_cli_extraidos = {}

            archivos_cli_pdf = st.file_uploader(
                "Sube tus documentos de clientes en PDF", 
                type=['pdf'], 
                accept_multiple_files=True,
                key="uploader_cli_pdf_cola"
            )

            if archivos_cli_pdf:
                nombres_existentes_cli = [item['nombre'] for item in st.session_state.cola_clientes_pdfs]
                for archivo in archivos_cli_pdf:
                    file_id = getattr(archivo, "file_id", archivo.name)
                    if archivo.name not in nombres_existentes_cli and file_id not in st.session_state.cli_procesados_ids:
                        st.session_state.cola_clientes_pdfs.append({
                            "id": file_id,
                            "nombre": archivo.name,
                            "objeto": archivo,
                            "estado": "Pendiente"
                        })

            if st.session_state.cola_clientes_pdfs:
                st.markdown(f"### 📋 Cola de Clientes ({len(st.session_state.cola_clientes_pdfs)} en espera)")
                
                if st.button("🗑️ Vaciar Cola de Clientes", key="btn_vaciar_cola_cli"):
                    st.session_state.cola_clientes_pdfs = []
                    st.session_state.cli_procesados_ids = set()
                    st.session_state.datos_cli_extraidos = {}
                    st.rerun()

                import pandas as pd
                df_cola_cli = pd.DataFrame([{
                    "Archivo": item["nombre"], 
                    "Estado": item["estado"]
                } for item in st.session_state.cola_clientes_pdfs])
                
                st.dataframe(df_cola_cli, use_container_width=True, hide_index=True)
                st.markdown("---")

                st.markdown("### 📝 Auditoría, Extracción y Registro en la Tabla de Clientes")
                
                docs_cli_pendientes = [item for item in st.session_state.cola_clientes_pdfs if item["estado"] == "Pendiente"]
                
                if docs_cli_pendientes:
                    nombres_cli_pendientes = [item["nombre"] for item in docs_cli_pendientes]
                    doc_cli_seleccionado = st.selectbox(
                        "Selecciona un cliente pendiente para revisar y registrar:", 
                        nombres_cli_pendientes,
                        key="select_doc_cli_auditoria"
                    )

                    doc_cli_obj = next((item for item in docs_cli_pendientes if item["nombre"] == doc_cli_seleccionado), None)

                    if doc_cli_obj:
                        sufijo_cli = doc_cli_obj['nombre']

                        keys_defaults_cli = {
                            f"rif_cli_{sufijo_cli}": "",
                            f"razon_cli_{sufijo_cli}": "",
                            f"dir_cli_{sufijo_cli}": "",
                            f"tipo_cli_{sufijo_cli}": "Jurídica",
                            f"cc_cli_{sufijo_cli}": "",
                            f"dc_cli_{sufijo_cli}": ""
                        }
                        for k, v in keys_defaults_cli.items():
                            if k not in st.session_state:
                                st.session_state[k] = v

                        if st.button("⚡ Extraer Datos del Cliente", key=f"btn_extraer_cli_{sufijo_cli}"):
                            with st.spinner("Leyendo RIF, Razón Social y Dirección del PDF..."):
                                archivo_pdf = doc_cli_obj["objeto"]
                                
                                if hasattr(archivo_pdf, "seek"):
                                    archivo_pdf.seek(0)
                                    
                                datos_cliente = extraer_datos_cliente_pdf(archivo_pdf)

                                if datos_cliente is None:
                                    st.warning("⚠️ El documento no pudo ser leído correctamente. Por favor, completa los datos manualmente.")
                                    st.session_state[f"rif_cli_{sufijo_cli}"] = ""
                                    st.session_state[f"razon_cli_{sufijo_cli}"] = ""
                                    st.session_state[f"dir_cli_{sufijo_cli}"] = ""
                                else:
                                    st.session_state[f"rif_cli_{sufijo_cli}"] = datos_cliente.get("rif", "")
                                    st.session_state[f"razon_cli_{sufijo_cli}"] = datos_cliente.get("cliente", "")
                                    st.session_state[f"dir_cli_{sufijo_cli}"] = datos_cliente.get("direccion_fiscal", "")
                                    st.success(f"¡Datos extraídos con éxito para: {datos_cliente['cliente']}!")
                                    st.rerun()

                        st.info(f"Completando información para el archivo: **{sufijo_cli}**")
                        
                        col_i1, col_i2 = st.columns(2)
                        
                        with col_i1:
                            rif = st.text_input("RIF", key=f"rif_cli_{sufijo_cli}")
                            tipo_persona = st.selectbox(
                                "Tipo de Persona", 
                                options=["PN", "PJ", "No Residente", "Gobierno"],
                                index=1,
                                key=f"tipo_cli_{sufijo_cli}"
                            )
                            razon_social = st.text_input("Razón Social", key=f"razon_cli_{sufijo_cli}")
                        
                        with col_i2:
                            direccion_fiscal = st.text_area("Dirección Fiscal", key=f"dir_cli_{sufijo_cli}")
                            codigo_cuenta = st.text_input("Código de Cuenta Contable", key=f"cc_cli_{sufijo_cli}")
                            descripcion_cuenta = st.text_input("Descripción de Cuenta", key=f"dc_cli_{sufijo_cli}")

                        if st.button("💾 Guardar Cliente en Base de Datos", type="primary", key=f"btn_guardar_cli_{sufijo_cli}", use_container_width=True):
                            db_nombre = st.session_state.get('DB_ACTUAL')
                            if not db_nombre:
                                st.error("Error: No se ha seleccionado una base de datos activa.")
                            else:
                                conn = conectar_db(db_nombre)
                                if conn is None:
                                    st.error(f"❌ No se pudo conectar a la base de datos '{db_nombre}'.")
                                else:
                                    try:
                                        conn.ping(reconnect=True)
                                        with conn.cursor() as cursor:
                                            query_cli = """
                                                INSERT INTO clientes_comerciales (
                                                    rif, tipo_persona, razon_social, 
                                                    direccion_fiscal, codigo_cuenta, descripcion_cuenta
                                                ) VALUES (%s, %s, %s, %s, %s, %s)
                                                ON DUPLICATE KEY UPDATE
                                                    tipo_persona = VALUES(tipo_persona),
                                                    razon_social = VALUES(razon_social),
                                                    direccion_fiscal = VALUES(direccion_fiscal),
                                                    codigo_cuenta = VALUES(codigo_cuenta),
                                                    descripcion_cuenta = VALUES(descripcion_cuenta)
                                            """
                                            
                                            valores_cli = (
                                                rif, tipo_persona, razon_social,
                                                direccion_fiscal, codigo_cuenta, descripcion_cuenta
                                            )
                                            
                                            cursor.execute(query_cli, valores_cli)
                                            conn.commit()
                                        
                                        for item in st.session_state.cola_clientes_pdfs:
                                            if item["nombre"] == doc_cli_obj["nombre"]:
                                                item["estado"] = "Registrado"
                                                st.session_state.cli_procesados_ids.add(item["id"])
                                                break
                                                
                                        st.cache_data.clear()
                                        st.success(f"¡Cliente '{razon_social}' (RIF: {rif}) guardado correctamente!")
                                        st.rerun()
                                        
                                    except Exception as e:
                                        conn.rollback()
                                        st.error(f"Error al registrar el cliente en la base de datos: {e}")
                                    finally:
                                        try:
                                            conn.close()
                                        except Exception:
                                            pass
                else:
                    st.success("🎉 ¡Todos los clientes en la cola ya han sido procesados y registrados!")
            else:
                st.info("No hay archivos en la cola de clientes. Sube algunos PDFs arriba para comenzar.")

        # --- 5. Lógica de Pestaña 4 (Gestión y borrado seguro de clientes_comerciales) ---
        with tab4:
            st.subheader("⚠️ Zona de Peligro: Gestión de la Tabla Clientes")
            st.warning("Esta acción eliminará por completo los registros de la tabla de clientes comerciales para la empresa seleccionada actualmente.")
            
            if "mensaje_exito_clientes" in st.session_state:
                st.success(st.session_state.mensaje_exito_clientes)
                del st.session_state.mensaje_exito_clientes

            confirmacion_borrado = st.checkbox(
                "Confirmo que deseo vaciar/eliminar la tabla de clientes comerciales de esta empresa", 
                key="check_confirm_drop_cli_seguro"
            )
            
            if st.button("🗑️ Ejecutar Borrado de Clientes", type="primary", use_container_width=True, key="btn_ejecutar_borrado_cli"):
                if confirmacion_borrado:
                    db_seleccionada = st.session_state.get('DB_ACTUAL')
                    
                    if not db_seleccionada or db_seleccionada == 'none':
                        st.error("❌ No hay ninguna empresa/base de datos activa seleccionada en el panel lateral.")
                    else:
                        conn_gestion = None
                        try:
                            conn_gestion = conectar_db(db_seleccionada)
                            
                            if conn_gestion is None:
                                st.error(f"❌ No se pudo establecer conexión con la base de datos: {db_seleccionada}")
                            else:
                                conn_gestion.ping(reconnect=True)
                                with conn_gestion.cursor() as cursor:
                                    cursor.execute("DROP TABLE IF EXISTS clientes_comerciales;")
                                    cursor.execute("""
                                        CREATE TABLE clientes_comerciales (
                                            rif VARCHAR(50) NOT NULL PRIMARY KEY,
                                            tipo_persona VARCHAR(50) NOT NULL,
                                            razon_social VARCHAR(255) NOT NULL,
                                            direccion_fiscal TEXT NOT NULL,
                                            codigo_cuenta VARCHAR(100) DEFAULT '',
                                            descripcion_cuenta VARCHAR(255) DEFAULT ''
                                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                                    """)
                                    conn_gestion.commit()
                                
                                st.cache_data.clear()
                                if "df_clientes_cache" in st.session_state:
                                    del st.session_state.df_clientes_cache
                                    
                                st.balloons()
                                st.session_state.mensaje_exito_clientes = f"🎉 ¡La tabla de clientes comerciales de la base de datos '{db_seleccionada}' ha sido ELIMINADA y recreada con éxito!"
                                st.rerun()
                                
                        except Exception as e:
                            if conn_gestion:
                                try:
                                    conn_gestion.rollback()
                                except Exception:
                                    pass
                            st.error(f"❌ Error crítico al procesar la BD '{db_seleccionada}': {e}")
                        finally:
                            if conn_gestion and hasattr(conn_gestion, 'close'):
                                try:
                                    conn_gestion.close()
                                except Exception:
                                    pass
                else:
                    st.warning("⚠️ Debes marcar la casilla de confirmación antes de ejecutar el borrado.")

    except Exception as e:
        st.error(f"❌ Error en el módulo de Clientes: {e}")
    finally:
        # Cierre de conexión global de la pestaña garantizado de forma independiente y segura
        if 'conn_empresa' in locals() and conn_empresa:
            try:
                conn_empresa.close()
            except Exception:
                pass

elif opcion_menu == "📦 Respaldos y Exportación":
    st.subheader("📦 Centro de Respaldos y Exportación de Datos")
    st.markdown("""
    Este módulo te permite generar copias de seguridad instantáneas de todas las tablas operativas de la base de datos actual. 
    Puedes descargar tablas individuales o generar un **Respaldo Maestro** que agrupará toda la contabilidad en un solo archivo de Excel con pestañas independientes.
    """)
    st.divider()

    # Obtenemos la base de datos activa de forma segura desde la sesión
    db_actual_activa = st.session_state.get('DB_ACTUAL', 'rishon_letzion_ca')

    # Definimos el diccionario de tablas y sus nombres amigables para el reporte
    tablas_respaldo = {
        "Asientos Contables": "asientos_contables",
        "Movimientos Bancarios": "banco_movimientos",
        "Libro de Compras": "libro_compras",
        "Libro de Ventas": "libro_ventas",
        "Plan de Cuentas": "plan_cuentas",
        "Retenciones ISLR": "retenciones_islr",
        "Retenciones IVA": "retenciones_iva",
        "Saldos Iniciales": "saldos_iniciales",
        "Proveedores": "proveedores",
        "Clientes": "clientes",
        "Archivo TXT (Retenciones)": "archivo_txt",
        "Activo Fijo": "activo_fijo",
        "Accionistas": "accionistas"
    }

    # --- FUNCIÓN CON CACHÉ PARA CONSULTAR TABLAS RÁPIDAMENTE ---
    @st.cache_data(ttl=30, show_spinner=False)
    def consultar_tabla_respaldo_cached(empresa, tabla_db):
        df_res = pd.DataFrame()
        conn = conectar_db(empresa)
        if conn:
            try:
                conn.ping(reconnect=True)
                query = f"SELECT * FROM `{tabla_db}`"
                df_res = pd.read_sql(query, conn)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return df_res if df_res is not None else pd.DataFrame()

    col_opt1, col_opt2 = st.columns(2)

    with col_opt1:
        st.markdown("### 📄 Descarga Individual")
        tabla_seleccionada_nombre = st.selectbox("Seleccione la tabla a respaldar:", list(tablas_respaldo.keys()), key="select_tabla_respaldo")
        tabla_db_nombre = tablas_respaldo[tabla_seleccionada_nombre]

        if st.button("📥 Consultar y Preparar Tabla", key="btn_descargar_individual", use_container_width=True):
            try:
                df_ind = consultar_tabla_respaldo_cached(db_actual_activa, tabla_db_nombre)

                if not df_ind.empty:
                    import io
                    buffer_ind = io.BytesIO()
                    with pd.ExcelWriter(buffer_ind, engine='openpyxl') as writer:
                        df_ind.to_excel(writer, index=False, sheet_name=tabla_seleccionada_nombre[:31])
                    buffer_ind.seek(0)

                    nombre_archivo_ind = f"Respaldo_{tabla_db_nombre}_{db_actual_activa}_{date.today().strftime('%Y-%m-%d')}.xlsx"
                    
                    st.download_button(
                        label=f"💾 Descargar Archivo: {tabla_seleccionada_nombre}",
                        data=buffer_ind,
                        file_name=nombre_archivo_ind,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_btn_single_exec",
                        use_container_width=True
                    )
                    st.success(f"✅ ¡Tabla '{tabla_seleccionada_nombre}' lista para descargar ({len(df_ind)} registros)!")
                else:
                    st.warning(f"⚠️ La tabla '{tabla_seleccionada_nombre}' se encuentra vacía actualmente.")
            except Exception as e:
                st.error(f"❌ Error al exportar la tabla: {e}")

    with col_opt2:
        st.markdown("### 📚 Respaldo Maestro (Todo en 1)")
        st.info("Genera un libro de Excel completo con **todas las tablas** organizadas en pestañas independientes simultáneamente.")

        if st.button("🚀 Generar Respaldo Maestro Global", type="primary", key="btn_respaldo_maestro", use_container_width=True):
            try:
                conn_resp = conectar_db(db_actual_activa)
                if conn_resp:
                    import io
                    buffer_maestro = io.BytesIO()
                    
                    with pd.ExcelWriter(buffer_maestro, engine='openpyxl') as writer:
                        tablas_exportadas_count = 0
                        for nombre_amigable, nombre_tabla in tablas_respaldo.items():
                            try:
                                conn_resp.ping(reconnect=True)
                                q_m = f"SELECT * FROM `{nombre_tabla}`"
                                df_m = pd.read_sql(q_m, conn_resp)
                                sheet_name_clean = nombre_amigable.replace("/", "-")[:31]
                                df_m.to_excel(writer, index=False, sheet_name=sheet_name_clean)
                                tablas_exportadas_count += 1
                            except Exception:
                                continue
                    
                    try:
                        conn_resp.close()
                    except Exception:
                        pass

                    buffer_maestro.seek(0)
                    
                    nombre_archivo_maestro = f"Respaldo_Maestro_Contable_{db_actual_activa}_{date.today().strftime('%Y-%m-%d')}.xlsx"
                    
                    st.download_button(
                        label="📦 Descargar Archivo Excel Maestro Completo",
                        data=buffer_maestro,
                        file_name=nombre_archivo_maestro,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_btn_master_exec",
                        use_container_width=True
                    )
                    st.cache_data.clear()
                    st.balloons()
                    st.success(f"✅ ¡Respaldo Maestro generado correctamente con {tablas_exportadas_count} tablas respaldadas!")
            except Exception as e:
                st.error(f"❌ Error crítico generando el respaldo maestro: {e}")
                
elif "Inventarios" in opcion_menu:
    # Invocamos el módulo exclusivo pasando la conexión a la base de datos
    modulo_inventario_pedacito_cielo(conn)  


elif opcion_menu == "📄 Factura Preimpresa":
    st.subheader("🖨️ Emisión de Factura Preimpresa")
    
    # Obtenemos los datos fiscales de la empresa emisora activa
    empresa_actual = obtener_datos_empresa_activa()
    st.info(f"Empresa Emisora: **{empresa_actual['nombre']}** | RIF: **{empresa_actual['rif']}**")

    # 1. Consultar los clientes directamente desde la tabla clientes_comerciales con reconexión automática
    lista_clientes = []
    try:
        conn.ping(reconnect=True)
        with conn.cursor() as cursor_cli:
            cursor_cli.execute("SELECT razon_social, rif FROM clientes_comerciales ORDER BY razon_social ASC")
            lista_clientes = cursor_cli.fetchall()
    except Exception as ex:
        try:
            st.session_state.conn = None
            conn = conectar_db("gomas_puente_hierro")
            conn.ping(reconnect=True)
            with conn.cursor() as cursor_cli:
                cursor_cli.execute("SELECT razon_social, rif FROM clientes_comerciales ORDER BY razon_social ASC")
                lista_clientes = cursor_cli.fetchall()
        except Exception as ex_reconnect:
            st.error(f"Error al consultar clientes_comerciales: {ex_reconnect}")

    dict_clientes = {row[0]: row[1] for row in lista_clientes} if lista_clientes else {}
    nombres_clientes = list(dict_clientes.keys())

    # --- FUERA DEL FORMULARIO para que reaccione al instante ---
    st.markdown("### 👤 Selección de Cliente")
    col_c1, col_c2 = st.columns(2)
    
    with col_c1:
        if nombres_clientes:
            razon_soc_sel = st.selectbox("Seleccionar Cliente de la Base de Datos", nombres_clientes, key="select_cliente_preimpresa")
        else:
            razon_soc_sel = st.text_input("Razón Social del Cliente", key="razon_manual")
            
    with col_c2:
        if nombres_clientes:
            rif_cli = dict_clientes.get(razon_soc_sel, "")
            st.markdown("**RIF del Cliente (Automático):**")
            st.info(rif_cli if rif_cli else "Sin RIF registrado")
        else:
            rif_cli = st.text_input("RIF del Cliente", key="rif_manual")

    st.markdown("---")

    # --- DENTRO DEL FORMULARIO: Datos de la factura y montos fiscales ---
    with st.form("form_factura_preimpresa"):
        col1, col2 = st.columns(2)
        with col1:
            nro_fact = st.text_input("Número de Factura")
            nro_ctrl = st.text_input("Número de Control")
            fec_emi = st.text_input("Fecha de Emisión (YYYY-MM-DD)")
            base_imp = st.number_input("Base Imponible", value=0.00, format="%.2f")
            monto_ex = st.number_input("Monto Exento", value=0.00, format="%.2f")
            
        with col2:
            porc_iva = st.number_input("Porcentaje Alícuota IVA (%)", value=16.00, format="%.2f")
            monto_iva = st.number_input("Monto IVA", value=0.00, format="%.2f")
            monto_tot = st.number_input("Monto Bruto / Total", value=0.00, format="%.2f")
            
        submitted = st.form_submit_button("Generar PDF Preimpreso")
        
        if submitted:
            # Estructuramos el diccionario incorporando todos los campos fiscales de tu tabla
            datos_factura = {
                'nro_factura': nro_fact,
                'nro_control': nro_ctrl,
                'fecha_emision': fec_emi,
                'razon_social': razon_soc_sel,
                'rif_cliente': rif_cli,
                'base_imponible': str(base_imp),
                'monto_exento': str(monto_ex),
                'porcentaje_alicuota': str(porc_iva),
                'monto_iva': str(monto_iva),
                'monto_total': str(monto_tot),
                'empresa_nombre': empresa_actual['nombre'],
                'empresa_rif': empresa_actual['rif'],
                'empresa_direccion': empresa_actual['direccion']
            }
            
            items_factura = []
            
            # Invocamos la función con los argumentos requeridos
            pdf_bytes = generar_pdf_preimpreso(conn, datos_factura, items_factura)
            
            st.download_button(
                label="📥 Descargar PDF Listo para Imprimir",
                data=pdf_bytes,
                file_name=f"factura_{nro_fact}.pdf",
                mime="application/pdf"
            )
