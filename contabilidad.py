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
def obtener_saldos_acumulados(conexion, fecha_corte, nombre_db):
    if not conexion: 
        return {"activo": 0, "pasivo": 0, "patrimonio": 0}
    
    db_segura = str(nombre_db).strip()
    cur = conexion.cursor(pymysql.cursors.DictCursor)
    
    try:
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
