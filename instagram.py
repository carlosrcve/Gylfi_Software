# instagram.py
import ssl
import pandas as pd
import pymysql
import streamlit as st


def conectar_db(nombre_db=None):
  db_a_usar = nombre_db if nombre_db else "control_central"
  ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
  ssl_context.check_hostname = False
  ssl_context.verify_mode = ssl.CERT_NONE

  try:
    conn = pymysql.connect(
        host="gateway01.us-east-1.prod.aws.tidbcloud.com",
        port=4000,
        user="4K4VAw4t4ZPFUTF.root",
        password="W3Zkbr4E2trGCfoX",
        database=db_a_usar,
        connect_timeout=15,
        charset="utf8mb4",
        ssl=ssl_context,
    )
    return conn
  except Exception as ex:
    st.error(f"❌ Error de conexión DB ('{db_a_usar}'): {ex}")
    return None

def obtener_datos_agente_db(valor_busqueda):
  conn_central = conectar_db("control_central")
  if not conn_central:
    return None

  try:
    with conn_central.cursor(pymysql.cursors.DictCursor) as cursor:
      # Consultamos solo los campos seguros que sabemos que existen en la tabla clientes
      if isinstance(valor_busqueda, str):
        query = (
            "SELECT id, nombre_empresa, rif FROM clientes WHERE db_nombre = %s"
        )
      else:
        query = "SELECT id, nombre_empresa, rif FROM clientes WHERE id = %s"

      cursor.execute(query, (valor_busqueda,))
      datos = cursor.fetchone()
      
      # Si no lo encuentra por db_nombre exacto, devolvemos un diccionario base por seguridad
      if not datos:
        return {
            "id": 1,
            "nombre_empresa": "King Driver, C.A.",
            "rif": "J-XXXXXXXX-X",
        }
      return datos
  except Exception as e:
    # Si ocurre cualquier detalle, devolvemos datos por defecto para que la vista pública no se caiga
    return {
        "id": 1,
        "nombre_empresa": "King Driver, C.A.",
        "rif": "J-XXXXXXXX-X",
    }
  finally:
    if conn_central and conn_central.open:
      conn_central.close()


def aplicar_estilo_publico():
  """Oculta la barra lateral y deja la pantalla 100% limpia para Instagram."""
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

  # 1. Obtenemos los datos de la empresa actual (King Driver)
  db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
  empresa_data = obtener_datos_agente_db(db_actual)

  if not empresa_data:
    # Si por alguna razón no está en la tabla clientes, le damos datos por defecto
    empresa_data = {
        "nombre_empresa": "King Driver, C.A.",
        "rif": "J-XXXXXXXX-X",
        "domicilio_fiscal": "Caracas, Venezuela",
    }

  st.title("📖 Libro de Compras")
  st.markdown(f"### 🏢 {empresa_data['nombre_empresa']}")
  st.markdown(f"**RIF:** {empresa_data.get('rif', 'N/D')}")
  st.markdown("---")

  # 2. Conectamos a la BD específica para extraer los registros de compras
  conn_cliente = conectar_db(db_actual)
  if not conn_cliente:
    st.error("⚠️ No se pudo establecer conexión con la base de datos del cliente.")
    return

  try:
    # Aseguramos que la tabla exista preventivamente
    with conn_cliente.cursor() as cursor:
      cursor.execute("""
                CREATE TABLE IF NOT EXISTS libro_compras (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    fecha DATE,
                    rif_proveedor VARCHAR(50),
                    nombre_proveedor VARCHAR(150),
                    numero_factura VARCHAR(50),
                    total_compras DECIMAL(18,2)
                );
            """)
      conn_cliente.commit()

    query = "SELECT * FROM libro_compras"
    df = pd.read_sql(query, conn_cliente)
    conn_cliente.close()

    if not df.empty:
      st.dataframe(df, use_container_width=True)
    else:
      st.info("No hay registros disponibles en el libro de compras actualmente.")

  except Exception as e:
    st.error(f"Error al cargar los datos públicos: {e}")


def modulo_ventas():
  aplicar_estilo_publico()
  db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
  empresa_data = obtener_datos_agente_db(db_actual)
  nombre = (
      empresa_data["nombre_empresa"]
      if empresa_data
      else "King Driver, C.A."
  )

  st.title("📊 Libro de Ventas")
  st.markdown(f"### 🏢 {nombre}")
  st.markdown("---")
  st.info("Módulo de ventas público en preparación.")


def modulo_retencion_islr():
  aplicar_estilo_publico()
  st.title("🧾 Comprobante de Retención ISLR")
  st.markdown("---")


def modulo_retencion_iva():
  aplicar_estilo_publico()
  st.title("🧾 Comprobante de Retención IVA")
  st.markdown("---")
