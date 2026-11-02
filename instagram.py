# instagram.py - Módulo Independiente del Libro de Compras
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

# --- FUNCIÓN DE CONEXIÓN A MYSQL / TIDB CLOUD ---
def conectar_db(db_name=None):
    """Establece una conexión directa con la base de datos de MySQL."""
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
        st.error(f"❌ Error de conexión a la Base de Datos ({target_db}): {e}")
        return None
      
# --- 1. FUNCIONES AUXILIARES Y DE CACHÉ (NIVEL GLOBAL) ---
def aplicar_estilo_publico():
  """Oculta la barra lateral y ajusta el contenedor principal."""
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


@st.cache_resource(show_spinner=False)
def obtener_engine_cached(db_name):
  """Crea y almacena en caché la conexión de SQLAlchemy con TiDB Cloud."""
  password_escaped = quote_plus("W3Zkbr4E2trGCfoX")
  database_url = f"mysql+pymysql://4K4VAw4t4ZPFUTF.root:{password_escaped}@gateway01.us-east-1.prod.aws.tidbcloud.com:4000/{db_name}"
  return create_engine(
      database_url,
      connect_args={"ssl": {"ssl_ca": None, "check_hostname": False}},
  )


@st.cache_data(ttl=30, show_spinner=False)
def consultar_libro_compras_cached(empresa, ver_todo_val, f_desde, f_hasta):
  df_res = pd.DataFrame()
  conn = conectar_db(empresa)
  if conn:
    try:
      with conn.cursor() as cursor:
        cursor.execute("""
                    CREATE TABLE IF NOT EXISTS libro_compras (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        fecha_operacion DATE,
                        tipo_documento VARCHAR(50),
                        n_factura VARCHAR(50),
                        n_control VARCHAR(50),
                        nota_credito VARCHAR(50),
                        nota_debito VARCHAR(50),
                        proveedor VARCHAR(150),
                        rif VARCHAR(50),
                        total_compras DECIMAL(18,2) DEFAULT 0.00,
                        importe_exento DECIMAL(18,2) DEFAULT 0.00,
                        base_imponible DECIMAL(18,2) DEFAULT 0.00,
                        iva_porcentaje DECIMAL(5,2) DEFAULT 16.00,
                        iva_monto DECIMAL(18,2) DEFAULT 0.00,
                        monto_iva_retenido DECIMAL(18,2) DEFAULT 0.00,
                        fecha_comprobante DATE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    );
                """)
        conn.commit()

      if ver_todo_val:
        query = (
            "SELECT * FROM libro_compras ORDER BY fecha_operacion DESC, id DESC"
        )
        df_res = pd.read_sql(query, conn)
      else:
        query = (
            "SELECT * FROM libro_compras WHERE fecha_operacion BETWEEN %s AND"
            " %s ORDER BY fecha_operacion ASC, id ASC"
        )
        df_res = pd.read_sql(query, conn, params=(f_desde, f_hasta))
    except Exception as ex:
      st.error(f"Error al ejecutar consulta SQL: {ex}")
    finally:
      try:
        conn.close()
      except Exception:
        pass
  return df_res


@st.cache_data(ttl=30, show_spinner=False)
def obtener_fechas_compras_cached(empresa):
  fechas = []
  conn = conectar_db(empresa)
  if conn:
    try:
      df_fechas = pd.read_sql(
          "SELECT DISTINCT fecha_operacion FROM libro_compras ORDER BY"
          " fecha_operacion DESC LIMIT 10",
          conn,
      )
      if not df_fechas.empty:
        fechas = df_fechas["fecha_operacion"].tolist()
    except Exception:
      pass
    finally:
      try:
        conn.close()
      except Exception:
        pass
  return fechas


# --- 2. FUNCIÓN PRINCIPAL DEL MÓDULO ---
def modulo_compras():
  aplicar_estilo_publico()

  db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
  empresa_data = obtener_datos_agente_db(db_actual)

  if not empresa_data:
    empresa_data = {
        "nombre_empresa": "King Driver, C.A.",
        "rif": "J-XXXXXXXX-X",
        "domicilio_fiscal": "Caracas, Venezuela",
    }

  st.title("📖 Libro de Compras")
  st.markdown(f"### 🏢 {empresa_data['nombre_empresa']}")
  st.markdown(f"**RIF:** {empresa_data.get('rif', 'N/D')}")
  st.markdown("---")

  # --- ESTRUCTURA PRINCIPAL DE PESTAÑAS ---
  tab_titles = [
      "🔍 Consultar y Editar",
      "📸 Escaneo Inteligente",
      "🚨 Vaciado de Rango",
      "📊 Cargar desde Excel",
      "📁 PDFs POR LOTES",
      "📝 Notas de Crédito / Débito",
  ]
  tabs = st.tabs(tab_titles)
  tab1, tab2, tab3, tab4, tab5, tab6 = tabs

  # ==========================================
  # TAB 1: CONSULTAR Y EDITAR
  # ==========================================
  with tab1:
    st.subheader("🔍 Consulta y Edición: Libro de Compras")

    col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
    with col_c3:
      ver_todo = st.checkbox("📂 Ver todo", key="todo_compras")

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

    st.error(
        "⚠️ **Atención:** Las acciones aquí solo afectan al Libro de Compras."
    )

    if st.button("📊 Consultar Compras", key="btn_consultar_compras"):
      df_recuperado = consultar_libro_compras_cached(
          db_actual, ver_todo, desde_c, hasta_c
      )
      if df_recuperado is not None and not df_recuperado.empty:
        st.session_state.df_compras_editor = df_recuperado
      else:
        st.warning("No se encontraron registros en el rango seleccionado.")
        if "df_compras_editor" in st.session_state:
          del st.session_state.df_compras_editor

    if "df_compras_editor" in st.session_state:
      df_mostrar_compras = st.session_state.df_compras_editor.copy()

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
              lambda x: (
                  "{:,.2f}".format(x)
                  .replace(",", "X")
                  .replace(".", ",")
                  .replace("X", ".")
                  if pd.notnull(x)
                  else "0,00"
              )
          )

      st.subheader("👁️ Vista de Consulta")
      st.dataframe(df_visual_c, use_container_width=True, hide_index=True)

      st.subheader("✏️ Administrar Compras (Modificar, Eliminar)")
      st.info(
          "💡 **Instrucciones:** Puedes editar celdas directamente de los"
          " registros existentes, o eliminar registros seleccionando la fila y"
          " haciendo clic en el icono de papelera."
      )

      key_editor_compras = "editor_consulta_final"

      st.data_editor(
          df_mostrar_compras,
          key=key_editor_compras,
          num_rows="fixed",
          use_container_width=True,
          hide_index=True,
          column_config={
              "id": st.column_config.NumberColumn("ID", disabled=True),
              "fecha_operacion": st.column_config.DateColumn(
                  "F. Operación", format="DD/MM/YYYY"
              ),
              "tipo_documento": st.column_config.TextColumn("Tipo Doc."),
              "n_factura": st.column_config.TextColumn("Nº Factura"),
              "n_control": st.column_config.TextColumn("Nº Control"),
              "nota_credito": st.column_config.TextColumn("Nº Nota Crédito"),
              "nota_debito": st.column_config.TextColumn("Nº Nota Débito"),
              "proveedor": st.column_config.TextColumn("Proveedor"),
              "rif": st.column_config.TextColumn("RIF"),
              "total_compras": st.column_config.NumberColumn(
                  "Total Compras", format="%,.2f", step=0.01
              ),
              "importe_exento": st.column_config.NumberColumn(
                  "Importe Exento", format="%,.2f", step=0.01
              ),
              "base_imponible": st.column_config.NumberColumn(
                  "Base Imponible", format="%,.2f", step=0.01
              ),
              "iva_porcentaje": st.column_config.NumberColumn(
                  "% IVA", format="%.1f", step=0.1
              ),
              "iva_monto": st.column_config.NumberColumn(
                  "IVA Monto", format="%,.2f", step=0.01
              ),
          },
      )

      st.markdown("### 📊 Totales")

      def f_bs(v):
        return (
            f"Bs. {v:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

      t1, t2, t3, t4 = st.columns(4)
      t1.metric(
          "Total Compras",
          f_bs(
              df_mostrar_compras["total_compras"].sum()
              if "total_compras" in df_mostrar_compras.columns
              else 0.0
          ),
      )
      t2.metric(
          "Total Exento",
          f_bs(
              df_mostrar_compras["importe_exento"].sum()
              if "importe_exento" in df_mostrar_compras.columns
              else 0.0
          ),
      )
      t3.metric(
          "Total Base",
          f_bs(
              df_mostrar_compras["base_imponible"].sum()
              if "base_imponible" in df_mostrar_compras.columns
              else 0.0
          ),
      )
      t4.metric(
          "Total IVA",
          f_bs(
              df_mostrar_compras["iva_monto"].sum()
              if "iva_monto" in df_mostrar_compras.columns
              else 0.0
          ),
      )
      st.markdown("---")

      nombre_archivo = f"Libro_de_compras_{desde_c.strftime('%Y%m%d')}_{hasta_c.strftime('%Y%m%d')}.xlsx"
      buffer = io.BytesIO()
      with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_mostrar_compras.to_excel(
            writer, index=False, sheet_name="Libro de Compras"
        )
      buffer.seek(0)

      st.download_button(
          label="📊 Descargar Libro de Compras en Excel",
          data=buffer,
          file_name=nombre_archivo,
          mime=(
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ),
          use_container_width=True,
          key="btn_download_excel_compras",
      )

      st.markdown("---")

      if st.button(
          "💾 Guardar cambios de edición en DB",
          type="primary",
          use_container_width=True,
          key="btn_guardar_final_compras",
      ):
        if key_editor_compras in st.session_state:
          cambios = st.session_state[key_editor_compras]
          conn = conectar_db(db_actual)
          if conn:
            try:
              with conn.cursor() as cursor:
                cursor.execute("DESCRIBE libro_compras")
                columnas_db = [fila[0] for fila in cursor.fetchall()]

                def limpiar_dato(val):
                  if val is None or (
                      isinstance(val, float) and np.isnan(val)
                  ):
                    return None
                  if isinstance(val, (pd.Timestamp, pd.Timedelta)):
                    return str(val.date())
                  if isinstance(val, (np.integer, np.int64)):
                    return int(val)
                  if isinstance(val, (np.floating, np.float64)):
                    return float(val)
                  return str(val).strip()

                cursor.execute("START TRANSACTION")

                for row_idx, dict_cambios in cambios.get(
                    "edited_rows", {}
                ).items():
                  id_edit = int(df_mostrar_compras.iloc[int(row_idx)]["id"])
                  if (
                      "fecha_operacion" in dict_cambios
                      and dict_cambios["fecha_operacion"]
                  ):
                    f = dict_cambios["fecha_operacion"]
                    dict_cambios["fecha_operacion"] = (
                        f.strftime("%Y-%m-%d")
                        if hasattr(f, "strftime")
                        else str(f)
                    )

                  if dict_cambios:
                    cols_val = [
                        f"{k} = %s" for k in dict_cambios.keys() if k in columnas_db
                    ]
                    vals_val = [
                        limpiar_dato(v)
                        for k, v in dict_cambios.items()
                        if k in columnas_db
                    ]
                    if cols_val:
                      sql_upd = f"UPDATE libro_compras SET {', '.join(cols_val)} WHERE id = %s"
                      cursor.execute(sql_upd, vals_val + [id_edit])

                for row_idx in cambios.get("deleted_rows", []):
                  id_del = int(df_mostrar_compras.iloc[row_idx]["id"])
                  cursor.execute(
                      "DELETE FROM libro_compras WHERE id = %s", (id_del,)
                  )

                conn.commit()
                st.cache_data.clear()
                st.success(
                    "✅ ¡Modificaciones y eliminaciones guardadas correctamente!"
                )
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

  


# --- 3. INVOCACIÓN DE SEGURIDAD PARA MÓDULO AUTÓNOMO ---
if __name__ == "__main__":
  modulo_compras()
