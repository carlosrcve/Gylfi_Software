# instagram.py
import ssl
import pandas as pd
import pymysql
import streamlit as st
from datetime import date as d_tipo, datetime as dt_tipo
import io
import numpy as np
import pandas as pd



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
    empresa_data = {
        "nombre_empresa": "King Driver, C.A.",
        "rif": "J-XXXXXXXX-X",
        "domicilio_fiscal": "Caracas, Venezuela",
    }

  st.title("📖 Libro de Compras")
  st.markdown(f"### 🏢 {empresa_data['nombre_empresa']}")
  st.markdown(f"**RIF:** {empresa_data.get('rif', 'N/D')}")
  st.markdown("---")

  # --- ESTRUCTURA DE TABS DE COMPRAS ---
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

  with tab1:
    st.subheader("🔍 Consulta y Edición: Libro de Compras")

    # Filtros de fecha
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

    # --- FUNCIÓN CON CACHÉ PARA CONSULTAR EL LIBRO DE COMPRAS ---
    @st.cache_data(ttl=30, show_spinner=False)
    def consultar_libro_compras_cached(empresa, ver_todo_val, f_desde, f_hasta):
      df_res = pd.DataFrame()
      conn = conectar_db(empresa)
      if conn:
        try:
          with conn.cursor() as cursor:
            # Aseguramos preventivamente la estructura completa de la tabla
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
                "SELECT * FROM libro_compras ORDER BY fecha_operacion DESC, id"
                " DESC"
            )
            df_res = pd.read_sql(query, conn)
          else:
            query = (
                "SELECT * FROM libro_compras WHERE fecha_operacion BETWEEN %s"
                " AND %s ORDER BY fecha_operacion ASC, id ASC"
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

    # Botón explícito de consulta
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

      # --- EDITOR DE DATOS ---
      st.subheader("✏️ Administrar Compras (Modificar, Eliminar)")
      st.info(
          "💡 **Instrucciones:** Puedes editar celdas directamente de los"
          " registros existentes, o eliminar registros seleccionando la fila y"
          " haciendo clic en el icono de papelera."
      )

      key_editor_compras = "editor_consulta_final"

      cambios_df = st.data_editor(
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
              "nota_credito": st.column_config.TextColumn(
                  "Nº Nota Crédito",
                  help=(
                      "Número de la Nota de Crédito emitida por el proveedor"
                      " (si aplica)"
                  ),
              ),
              "nota_debito": st.column_config.TextColumn(
                  "Nº Nota Débito", help="Número de la Nota de Débito (si aplica)"
              ),
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
              "fecha_comprobante": st.column_config.DateColumn(
                  "F. Comprobante", format="DD/MM/YYYY"
              ),
              "created_at": st.column_config.DatetimeColumn(
                  "F. Registro", disabled=True
              ),
              "updated_at": st.column_config.DatetimeColumn(
                  "F. Actualización", disabled=True
              ),
          },
      )

      # --- CÁLCULO DE TOTALES ---
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

      # --- BOTÓN DE DESCARGA EN EXCEL ---
      st.markdown("### 📥 Descargar Reporte")

      nombre_archivo = f"Libro de compras del {desde_c.strftime('%Y-%m-%d')} al {hasta_c.strftime('%Y-%m-%d')}.xlsx"

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

      # --- BOTÓN ÚNICO DE GUARDAR ---
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

                # 1. MODIFICAR / EDITAR FILAS EXISTENTES
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

                # 2. ELIMINAR FILAS
                for row_idx in cambios.get("deleted_rows", []):
                  id_del = int(df_mostrar_compras.iloc[row_idx]["id"])
                  cursor.execute(
                      "DELETE FROM libro_compras WHERE id = %s", (id_del,)
                  )

                conn.commit()
                st.cache_data.clear()
                st.success(
                    "✅ ¡Modificaciones y eliminaciones guardadas"
                    " correctamente en MySQL!"
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
        else:
          st.warning(
              "⚠️ No hay registro de cambios activos en la sesión."
          )

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
            with conn_prov.cursor(pymysql.cursors.DictCursor) as cursor_p:
              cursor_p.execute("""
                                CREATE TABLE IF NOT EXISTS proveedores (
                                    id INT AUTO_INCREMENT PRIMARY KEY,
                                    rif VARCHAR(50),
                                    razon_social VARCHAR(150)
                                );
                            """)
              conn_prov.commit()
              cursor_p.execute("SELECT rif, razon_social FROM proveedores")
              res_prov = cursor_p.fetchall()
              df_p = pd.DataFrame(res_prov)
          except Exception:
            pass
          finally:
            try:
              conn_prov.close()
            except Exception:
              pass
        return df_p

      with st.expander(
          "➕ Registrar Nueva Factura (Con listas desplegables y cálculos"
          " automáticos)",
          expanded=False,
      ):
        df_prov = obtener_proveedores_cached(db_actual)

        if not df_prov.empty and "razon_social" in df_prov.columns:
          df_prov["display_prov"] = (
              df_prov["razon_social"] + " (" + df_prov["rif"] + ")"
          )
          lista_opciones_proveedores = df_prov["display_prov"].tolist()
        else:
          lista_opciones_proveedores = []

        if lista_opciones_proveedores:
          prov_elegido = st.selectbox(
              "Proveedor / RIF",
              options=lista_opciones_proveedores,
              key="rt_prov",
          )
          razon_social_val = prov_elegido.split(" (")[0]
          rif_val = prov_elegido.split(" (")[1].replace(")", "")
        else:
          st.warning(
              "No hay proveedores registrados. Se registrará como cliente"
              " general."
          )
          razon_social_val = "VARIOS"
          rif_val = "J000000000"

        col_x1, col_x2 = st.columns(2)
        with col_x1:
          tipo_doc_val = st.selectbox(
              "Tipo de Documento",
              ["01-Factura", "03-Nota de Crédito"],
              key="rt_tipo_doc",
          )
          fecha_op_val = st.date_input(
              "Fecha de Operación / Emisión", key="rt_f_op"
          )
        with col_x2:
          n_factura_val = st.text_input(
              "Número de Factura", key="rt_n_fact"
          )
          n_control_val = st.text_input(
              "Número de Control", key="rt_n_ctrl"
          )
          nota_cred_val = st.text_input(
              "Nº Nota de Crédito (Opcional)", value="", key="rt_nc"
          )

        st.markdown("---")
        st.markdown(
            "### 💰 Control de Montos, Alícuota e IVA Automático"
        )

        alicuota_opciones = {
            "General (16%)": 16.0,
            "Reducida (8%)": 8.0,
            "Exonerada / Otra (0%)": 0.0,
        }

        alicuota_label = st.selectbox(
            "Seleccione la Alícuota de IVA",
            options=list(alicuota_opciones.keys()),
            key="rt_alicuota",
        )
        iva_porcentaje_val = alicuota_opciones[alicuota_label]

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
          base_imp_input = st.number_input(
              "Base Imponible",
              min_value=0.00,
              format="%.2f",
              step=100.00,
              key="rt_base",
          )
        with col_m2:
          iva_monto_input = base_imp_input * (iva_porcentaje_val / 100.0)
          st.number_input(
              f"IVA Monto ({iva_porcentaje_val}% Automático)",
              value=float(iva_monto_input),
              format="%.2f",
              disabled=True,
          )
        with col_m3:
          exento_input = st.number_input(
              "Monto Exento",
              min_value=0.00,
              format="%.2f",
              step=100.00,
              key="rt_exento",
          )

        total_calculado = base_imp_input + iva_monto_input + exento_input

        def formato_venezuela(val):
          return (
              f"{val:,.2f}".replace(",", "X")
              .replace(".", ",")
              .replace("X", ".")
          )

        st.success(
            "💵 **Monto Total Calculado Automáticamente:**"
            f" **{formato_venezuela(total_calculado)}**"
        )

        if st.button(
            "💾 Guardar Factura en Base de Datos",
            type="primary",
            use_container_width=True,
            key="rt_btn_guardar",
        ):
          if not n_factura_val or n_factura_val == "0":
            st.error("❌ El número de factura es obligatorio.")
          else:
            try:
              conn_ins = conectar_db(db_actual)
              if conn_ins:
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
                st.success(
                    "✅ ¡Factura agregada exitosamente con su monto total y"
                    " alícuota calculada!"
                )
                st.rerun()
            except Exception as e:
              st.error(f"❌ Error al guardar la factura: {e}")

  # Pestañas adicionales en construcción
  with tab2:
    st.info("📸 Módulo de Escaneo Inteligente en desarrollo.")
  with tab3:
    st.info("🚨 Módulo de Vaciado de Rango en desarrollo.")
  with tab4:
    st.info("📊 Módulo de Carga desde Excel en desarrollo.")
  with tab5:
    st.info("📁 Módulo de PDFs Por Lotes en desarrollo.")
  with tab6:
    st.info("📝 Módulo de Notas de Crédito / Débito en desarrollo.")


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
