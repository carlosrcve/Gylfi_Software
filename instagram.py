# instagram.py
import ssl
import pandas as pd
import pymysql
import streamlit as st


def aplicar_estilo_publico():
  """Oculta la barra lateral y la barra flotante para dejar la pantalla 100% limpia."""
  st.markdown(
      """
        <style>
            [data-testid="stSidebar"] { display: none !important; width: 0 !important; }
            [data-testid="collapsedControl"] { display: none !important; }
            section.main { width: 100% !important; margin-left: 0 !important; }
        </style>
    """,
      unsafe_allow_html=True,
  )


def modulo_compras():
  aplicar_estilo_publico()

  st.title("📖 Libro de Compras")
  st.markdown("### King Driver, C.A.")
  st.markdown("---")

  # Contexto SSL para TiDB Cloud
  ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
  ssl_context.check_hostname = False
  ssl_context.verify_mode = ssl.CERT_NONE

  try:
    # Conexión directa a TiDB Cloud usando tus credenciales y la base de datos de King Driver
    conn = pymysql.connect(
        host="gateway01.us-east-1.prod.aws.tidbcloud.com",
        port=4000,
        user="4K4VAw4t4ZPFUTF.root",
        password="W3Zkbr4E2trGCfoX",
        database="kingdriver_ca",
        connect_timeout=15,
        charset="utf8mb4",
        ssl=ssl_context,
    )

    query = "SELECT * FROM libro_compras"  # Ajusta el nombre de tu tabla real si es necesario
    df = pd.read_sql(query, conn)
    conn.close()

    if not df.empty:
      st.dataframe(df, use_container_width=True)
    else:
      st.info(
          "No hay registros disponibles en el libro de compras actualmente."
      )

  except Exception as e:
    st.error(f"Error al cargar los datos públicos: {e}")


def modulo_ventas():
  aplicar_estilo_publico()
  st.title("📊 Libro de Ventas - King Driver, C.A.")
  # Tu lógica para ventas aquí...


def modulo_retencion_islr():
  aplicar_estilo_publico()
  st.title("🧾 Comprobante de Retención ISLR")
  # Tu lógica para ISLR aquí...


def modulo_retencion_iva():
  aplicar_estilo_publico()
  st.title("🧾 Comprobante de Retención IVA")
  # Tu lógica para IVA aquí...
