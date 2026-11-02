## instagram.py - Módulo Independiente del Libro de Compras
import io
import ssl
import time
from datetime import date as d_tipo, datetime, datetime as dt_tipo
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import pymysql
import streamlit as st
from sqlalchemy import create_engine, text


def aplicar_estilo_publico():

  """Oculta la barra lateral y ajusta el contenedor principal."""
  st.markdown("""
      <style>
          [data-testid="stSidebar"] { display: none !important; width: 0 !important; }
          [data-testid="collapsedControl"] { display: none !important; }
          section.main { width: 100% !important; margin-left: 0 !important; }
      </style>
  """, unsafe_allow_html=True)


def conectar_db(db_name=None):
  """Establece una conexión directa segura con TiDB Cloud."""
  target_db = db_name if db_name else st.session_state.get("DB_ACTUAL", "kingdriver_ca")
  try:
      password_escaped = quote_plus("W3Zkbr4E2trGCfoX")
      conn = pymysql.connect(
          host="gateway01.us-east-1.prod.aws.tidbcloud.com",
          user="4K4VAw4t4ZPFUTF.root",
          password="W3Zkbr4E2trGCfoX",
          database=target_db,
          port=4000,
          ssl={"ssl": None},
          cursorclass=pymysql.cursors.DictCursor
      )
      return conn
  except Exception as e:
      return None


@st.cache_data(ttl=300)
def obtener_datos_agente_db(valor_busqueda):
  """Consulta segura de los datos de la empresa para el encabezado."""
  conn_central = conectar_db("kingdriver_ca")  # O tu base central de clientes
  if not conn_central:
      return {
          "nombre_empresa": "King Driver, C.A.",
          "rif": "J-XXXXXXXX-X",
          "domicilio_fiscal": "Caracas, Venezuela"
      }
  
  cursor = None
  try:
      cursor = conn_central.cursor(pymysql.cursors.DictCursor)
      if isinstance(valor_busqueda, str):
          query = "SELECT id, nombre_empresa, rif, db_nombre, estado, direccion_fiscal FROM clientes WHERE db_nombre = %s"
      else:
          query = "SELECT id, nombre_empresa, rif, db_nombre, estado, direccion_fiscal FROM clientes WHERE id = %s"
      
      cursor.execute(query, (valor_busqueda,))
      datos = cursor.fetchone()
      return datos if datos else {
          "nombre_empresa": "King Driver, C.A.",
          "rif": "J-XXXXXXXX-X",
          "domicilio_fiscal": "Caracas, Venezuela"
      }
  except Exception:
      return {
          "nombre_empresa": "King Driver, C.A.",
          "rif": "J-XXXXXXXX-X",
          "domicilio_fiscal": "Caracas, Venezuela"
      }
  finally:
      if cursor: cursor.close()
      if conn_central: conn_central.close()


@st.cache_resource(show_spinner=False)
def obtener_engine_cached(db_name):
  """Crea y almacena en caché la conexión de SQLAlchemy."""
  password_escaped = quote_plus("W3Zkbr4E2trGCfoX")
  database_url = f"mysql+pymysql://4K4VAw4t4ZPFUTF.root:{password_escaped}@gateway01.us-east-1.prod.aws.tidbcloud.com:4000/{db_name}"
  return create_engine(
      database_url,
      connect_args={"ssl": {"ssl_ca": None, "check_hostname": False}},
  )


# --- FUNCIÓN PRINCIPAL DEL MÓDULO ---
def modulo_compras():
  aplicar_estilo_publico()

  db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
  empresa_data = obtener_datos_agente_db(db_actual)

  st.title("📖 Libro de Compras")
  st.markdown(f"### 🏢 {empresa_data.get('nombre_empresa', 'King Driver, C.A.')}")
  st.markdown(f"**RIF:** {empresa_data.get('rif', 'N/D')}")
  st.markdown("---")





if __name__ == "__main__":
  modulo_compras()
