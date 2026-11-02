# instagram.py - Módulo Independiente del Libro de Compras
#https://gylfisoftware.streamlit.app/?modulo=libro_compras
#https://gylfisoftware.streamlit.app/?modulo=libro_ventas
#https://gylfisoftware.streamlit.app/?modulo=retencion_islr
#https://gylfisoftware.streamlit.app/?modulo=retencion_iva
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
import datetime as dt
import streamlit as st
import pandas as pd
# ... tus otros imports ...


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
    conn_central = conectar_db("kingdriver_ca")
    if not conn_central:
        return {
            "nombre_empresa": "Empresa Inteligencia Artificial, C.A.",
            "rif": "J-12345678-9",
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
            "nombre_empresa": "Empresa Inteligencia Artificial, C.A.",
            "rif": "J-12345678-9",
            "domicilio_fiscal": "Caracas, Venezuela"
        }
    except Exception:
        return {
            "nombre_empresa": "Empresa Inteligencia Artificial, C.A.",
            "rif": "J-12345678-9",
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

def obtener_facturas_pendientes(conn, f_desde, f_hasta):
    try:
        query = """
            SELECT id, fecha_operacion, tipo_documento, n_factura, n_control, 
                   proveedor, rif, total_compras, base_imponible, iva_monto, 
                   importe_exento, retencion_iva_realizada
            FROM libro_compras 
            WHERE (retencion_iva_realizada = 0 OR retencion_iva_realizada IS NULL OR retencion_iva_realizada = FALSE)
            AND fecha_operacion BETWEEN %s AND %s
            ORDER BY fecha_operacion ASC
        """
        df = ejecutar_consulta(query, conn, params=(f_desde, f_hasta))
        
        if df.empty:
            st.info(f"ℹ️ No hay facturas pendientes de retención de IVA entre {f_desde} y {f_hasta}.")
            
        return df
    except Exception as e:
        st.error(f"Error al cargar facturas pendientes de IVA: {e}")
        return pd.DataFrame()

# --- FUNCIÓN CON CACHÉ GLOBAL (Fuera de modulo_compras) ---
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


@st.cache_data(ttl=60, show_spinner=False)
def obtener_proveedores_cached(empresa):
    df_p = pd.DataFrame()
    conn_prov = conectar_db(empresa)
    if conn_prov:
        try:
            conn_prov.ping(reconnect=True)
            df_p = pd.read_sql("SELECT rif, razon_social FROM proveedores", conn_prov)
        except Exception:
            pass
        finally:
            try:
                conn_prov.close()
            except Exception:
                pass
    return df_p


# --- FUNCIÓN PRINCIPAL DEL MÓDULO ---
def modulo_compras():
    aplicar_estilo_publico()

    db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
    empresa_data = obtener_datos_agente_db(db_actual)
    st.title("📖 Libro de Compras")
    st.markdown(f"### 🏢 {empresa_data.get('nombre_empresa', 'King Driver, C.A.')}")
    st.markdown(f"**RIF:** {empresa_data.get('rif', 'N/D')}")
    st.markdown("---")

    tab_titles = [
        "🔍 Consultar y Editar",
        "📸 Escaneo Inteligente",
        "🚨 Vaciado de Rango",
        "📊 Cargar desde Excel",
        "📁 PDFs POR LOTES",
        "📝 Notas de Crédito / Débito"
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
            desde_c = st.date_input("Desde", _obtener_f_segura("f_inicio_global"), key="desde_c", disabled=ver_todo)
        with col_c2:
            hasta_c = st.date_input("Hasta", _obtener_f_segura("f_fin_global"), key="hasta_c", disabled=ver_todo)

        st.error("⚠️ **Atención:** Las acciones aquí solo afectan al Libro de Compras.")

        if st.button("📊 Consultar Compras", key="btn_consultar_compras"):
            df_recuperado = consultar_libro_compras_cached(db_actual, ver_todo, desde_c, hasta_c)
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
                        lambda x: "{:,.2f}".format(x).replace(",", "X").replace(".", ",").replace("X", ".")
                        if pd.notnull(x)
                        else "0,00"
                    )

            st.subheader("👁️ Vista de Consulta")
            st.dataframe(df_visual_c, use_container_width=True, hide_index=True)

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

            st.markdown("### 📊 Totales")

            def f_bs(v):
                return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            t1, t2, t3, t4 = st.columns(4)
            t1.metric("Total Compras", f_bs(df_mostrar_compras["total_compras"].sum() if "total_compras" in df_mostrar_compras.columns else 0.0))
            t2.metric("Total Exento", f_bs(df_mostrar_compras["importe_exento"].sum() if "importe_exento" in df_mostrar_compras.columns else 0.0))
            t3.metric("Total Base", f_bs(df_mostrar_compras["base_imponible"].sum() if "base_imponible" in df_mostrar_compras.columns else 0.0))
            t4.metric("Total IVA", f_bs(df_mostrar_compras["iva_monto"].sum() if "iva_monto" in df_mostrar_compras.columns else 0.0))
            st.markdown("---")

            st.markdown("### 📥 Descargar Reporte")

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

            if st.button("💾 Guardar cambios de edición en DB", type="primary", use_container_width=True, key="btn_guardar_final_compras"):
                if key_editor_compras in st.session_state:
                    cambios = st.session_state[key_editor_compras]
                    conn = conectar_db(db_actual)

                    if conn:
                        try:
                            conn.ping(reconnect=True)
                            with conn.cursor() as cursor:
                                cursor.execute("DESCRIBE libro_compras")
                                columnas_db = [fila["Field"] if isinstance(fila, dict) else fila[0] for fila in cursor.fetchall()]

                                def limpiar_dato(val):
                                    if val is None or pd.isna(val):
                                        return None
                                    if hasattr(val, "strftime"):
                                        return val.strftime("%Y-%m-%d")
                                    if isinstance(val, (int, float)):
                                        return val
                                    return str(val).strip()

                                cursor.execute("START TRANSACTION")

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

            with st.expander(
                "➕ Registrar Nueva Factura (Con listas desplegables y cálculos automáticos)",
                expanded=False,
            ):
                df_prov = obtener_proveedores_cached(db_actual)

                if not df_prov.empty and "razon_social" in df_prov.columns and "rif" in df_prov.columns:
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

    # ==========================================
    # RESTO DE PESTAÑAS (tab2 - tab6)
    # ==========================================
    with tab2:
        st.subheader("📸 Escaneo Inteligente de Documentos (OCR)")
        
        if "df_buffer_escaneo" not in st.session_state:
            st.session_state.df_buffer_escaneo = pd.DataFrame()

        archivo = st.file_uploader(
            "Sube factura, nota de crédito o débito (PDF o Imagen)", 
            type=['jpg', 'png', 'jpeg', 'pdf'], 
            key="uploader_factura"
        )

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
                                st.warning(f"⚠️ Límite de cuota alcanzado, reintentando en 40s... (Intento {intentos}/3)")
                                time.sleep(40)
                            else:
                                st.error(f"❌ Error crítico: {error_str}")
                                break
                    
                    if resultados:
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

        # --- ÁREA DE EDICIÓN Y REVISIÓN ---
        if not st.session_state.df_buffer_escaneo.empty:
            st.info(f"💡 Revisando {len(st.session_state.df_buffer_escaneo)} documentos en espera.")
            df_a_editar = st.session_state.df_buffer_escaneo.copy()
            
            if "fecha_operacion" in df_a_editar.columns:
                df_a_editar["fecha_operacion"] = pd.to_datetime(df_a_editar["fecha_operacion"], errors='coerce').dt.date
            
            columnas_ordenadas = [
                "fecha_operacion", "tipo_documento", "n_factura", "n_control", 
                "nota_credito", "nota_debito", "n_factura_afectada", "proveedor", 
                "rif", "tipo_transaccion", "total_compras", "importe_exento", 
                "base_imponible", "iva_porcentaje", "iva_monto"
            ]
            
            columnas_existentes = [col for col in columnas_ordenadas if col in df_a_editar.columns]
            otras_cols = [col for col in df_a_editar.columns if col not in columnas_existentes]
            df_a_editar = df_a_editar[columnas_existentes + otras_cols]
            
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
                    target_db = st.session_state.get('DB_ACTUAL') or st.session_state.get('id_empresa_actual') or "kingdriver_ca"
                    
                    try:
                        engine_db = obtener_engine_cached(target_db)
                    except Exception as ex_eng:
                        st.error(f"❌ Error al crear el motor de base de datos: {ex_eng}")
                        st.stop()

                    df_a_procesar = st.session_state.df_buffer_escaneo.copy()
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
                            
                            with engine_db.connect() as conn:
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
                                    fila_df.to_sql('libro_compras', con=engine_db, if_exists='append', index=False)
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

    # ==========================================
    # TAB 3: VACIADO DE RANGO
    # ==========================================
    with tab3:
        st.subheader("🚨 Vaciado de Compras")
        
        with st.popover("🚨 VACIAR COMPRAS (RANGO SELECCIONADO)", use_container_width=True):
            st.subheader("Seleccionar Rango a Borrar")
            
            fecha_d = st.date_input("Desde:", key="rango_desde_borrar_compras")
            fecha_h = st.date_input("Hasta:", key="rango_hasta_borrar_compras")
            
            st.markdown("---")
            st.subheader("Confirmar Borrado")
            st.warning(f"Se eliminarán los registros desde {fecha_d} hasta {fecha_h}") 
            
            confirmar_check = st.checkbox("Confirmo que deseo borrar", key="check_borrar_final_compras")
            
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

    # ==========================================
    # TAB 4: CARGAR DESDE EXCEL
    # ==========================================
    with tab4:
        st.subheader("📊 Cargar desde Excel")
        st.subheader("📊 Carga Masiva desde Excel (LIBROS DE COMPRAS)")
        archivo_ex = st.file_uploader("Sube tu archivo Excel", type=['xlsx'], key="uploader_excel_compras_masivo")
        
        @st.cache_data(show_spinner=False)
        def leer_excel_masivo_cached(file_buffer):
            df_excel = pd.read_excel(file_buffer)
            df_excel.columns = df_excel.columns.str.strip().str.lower().str.replace(" ", "_")
            
            for col in df_excel.columns:
                if any(k in col for k in ['control', 'factura', 'rif', 'documento', 'proveedor']):
                    df_excel[col] = df_excel[col].astype(str).replace({'nan': '', 'None': ''})
                    
            return df_excel

        if archivo_ex is not None:
            st.session_state.df_carga_excel = leer_excel_masivo_cached(archivo_ex)

        if "df_carga_excel" in st.session_state and not st.session_state.df_carga_excel.empty:
            df_temp = st.session_state.df_carga_excel.copy()
            
            col_fecha = next((c for c in df_temp.columns if 'fecha' in c.lower()), None)
            if col_fecha:
                df_temp = df_temp.rename(columns={col_fecha: 'fecha_operacion'})
                
                df_temp['fecha_operacion'] = pd.to_datetime(df_temp['fecha_operacion'], errors='coerce')\
                                            .dt.strftime('%Y-%m-%d')\
                                            .fillna(pd.Timestamp.now().strftime('%Y-%m-%d'))
                
                st.session_state.df_carga_excel = df_temp

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

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("TOTAL COMPRAS", f_bs(df_calc['total_compras'].sum()))
            m2.metric("TOTAL EXENTO", f_bs(df_calc['compras_exentas'].sum()))
            m3.metric("TOTAL BASE", f_bs(df_calc['base_imponible'].sum()))
            m4.metric("TOTAL IVA", f_bs(df_calc['credito_fiscales'].sum()))

            st.markdown("---")

            if st.button("🚀 Guardar carga masiva en DB", type="primary", use_container_width=True, key="btn_guardar_masivo_compras"):
                with st.spinner("⏳ Guardando registros en la base de datos..."):
                    try:
                        df_to_save = st.session_state.df_carga_excel.copy()
                        
                        if 'retencion_realizada' not in df_to_save.columns:
                            df_to_save['retencion_realizada'] = 0.0
                        
                        if 'retencion_iva_realizada' not in df_to_save.columns:
                            df_to_save['retencion_iva_realizada'] = 0.0

                        cargar_libro_compras_db(df_to_save, db_actual)
                        
                        st.cache_data.clear()
                        st.success("✅ ¡Proceso finalizado y guardado correctamente en la base de datos!")
                        
                        del st.session_state.df_carga_excel
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error crítico al guardar en DB: {e}")
        else:
            st.info("ℹ️ Por favor, sube un archivo Excel válido para comenzar la carga masiva.")

    # ==========================================
    # TAB 5: PDFs POR LOTES
    # ==========================================
    with tab5:
        st.subheader("📁 PDFs POR LOTES")
        st.subheader("📥 Bandeja de Entrada - Procesamiento Local de Facturas (PDF)")
        st.info("Arrastra o selecciona múltiples archivos PDF de facturas. Se acumularán en cola para su posterior revisión y registro.")

        if "cola_pdfs" not in st.session_state:
            st.session_state.cola_pdfs = []
        if "archivos_procesados_ids" not in st.session_state:
            st.session_state.archivos_procesados_ids = set()
        if "datos_extraidos_ia" not in st.session_state:
            st.session_state.datos_extraidos_ia = {}

        archivos_pdf = st.file_uploader(
            "Sube tus facturas en PDF", 
            type=['pdf'], 
            accept_multiple_files=True,
            key="uploader_pdf_cola"
        )

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

        if st.session_state.cola_pdfs:
            st.markdown(f"### 📋 Cola de Documentos ({len(st.session_state.cola_pdfs)} en espera)")
            
            if st.button("🗑️ Vaciar Cola", key="btn_vaciar_cola_pdfs"):
                st.session_state.cola_pdfs = []
                st.session_state.archivos_procesados_ids = set()
                st.session_state.datos_extraidos_ia = {}
                st.rerun()

            df_cola = pd.DataFrame([{
                "Archivo": item["nombre"], 
                "Estado": item["estado"]
            } for item in st.session_state.cola_pdfs])
            
            st.dataframe(df_cola, use_container_width=True, hide_index=True)
            st.markdown("---")

            st.markdown("### 📝 Auditoría, Extracción Local Rápida y Registro al Libro de Compras")
            
            documentos_pendientes = [item for item in st.session_state.cola_pdfs if item["estado"] == "Pendiente"]
            
            if documentos_pendientes:
                nombres_pendientes = [item["nombre"] for item in documentos_pendientes]
                documento_seleccionado_nombre = st.selectbox(
                    "Selecciona un documento pendiente para revisar y registrar:", 
                    nombres_pendientes,
                    key="select_doc_auditoria"
                )

                doc_obj = next((item for item in documentos_pendientes if item["nombre"] == documento_seleccionado_nombre), None)

                if doc_obj:
                    col_ia1, col_ia2 = st.columns([1, 3])
                    with col_ia1:
                        if st.button("⚡ Procesar Factura (Local)", key="btn_procesar_factura_local"):
                            with st.spinner("Leyendo estructura del PDF localmente..."):
                                datos_extraidos = extraer_datos_con_regex(doc_obj["objeto"])
                                
                                if datos_extraidos:
                                    st.session_state.datos_extraidos_ia[doc_obj["nombre"]] = datos_extraidos
                                    st.success("¡Datos extraídos con éxito de forma local!")
                                    st.rerun()
                                else:
                                    st.error("No se pudieron extraer datos automáticos de este PDF.")

                    datos_pre = st.session_state.datos_extraidos_ia.get(doc_obj["nombre"], {})

                    with st.form("form_registro_libro_compras"):
                        st.info(f"Registrando datos para el archivo: **{doc_obj['nombre']}**")
                        
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

    # ==========================================
    # TAB 6: NOTAS DE CRÉDITO / DÉBITO
    # ==========================================
    with tab6:
        st.subheader("📝 Gestión de Notas de Crédito y Débito")
        st.info("💡 **Flujo Fiscal:** Consulta el libro de compras por fecha, selecciona la factura a afectar y genera su documento de ajuste asociado con su respectivo número de control.")

        st.markdown("#### 1️⃣ Seleccionar Periodo del Libro de Compras")
        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            fecha_desde = st.date_input("Desde", key="nc_fecha_desde")
        with col_f2:
            fecha_hasta = st.date_input("Hasta", key="nc_fecha_hasta")
        with col_f3:
            st.markdown("<br>", unsafe_allow_html=True)
            btn_consultar_lc = st.button("🔍 Consultar", key="btn_consultar_lc_nc")

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

        if "df_nc_libro_compras" in st.session_state and not st.session_state.df_nc_libro_compras.empty:
            st.markdown("---")
            st.markdown("#### 2️⃣ Selecciona la Factura que será Afectada")
            
            df_select = st.session_state.df_nc_libro_compras.copy()
            df_select.insert(0, "Seleccionar", False)

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

            filas_elegidas = df_seleccionado_usuario[df_seleccionado_usuario["Seleccionar"] == True]

            if len(filas_elegidas) == 1:
                factura_base = filas_elegidas.iloc[0]
                st.session_state.factura_seleccionada_nc = factura_base
                st.info(f"📌 **Factura seleccionada:** Nº {factura_base['n_factura']} | Proveedor: {factura_base['proveedor']}")
            elif len(filas_elegidas) > 1:
                st.warning("⚠️ Por favor selecciona **solo una** factura para aplicarle el documento de ajuste.")
            
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


def modulo_ventas():
    aplicar_estilo_publico()

    db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
    empresa_data = obtener_datos_agente_db(db_actual)
    nombre = (
        empresa_data.get("nombre_empresa", "King Driver, C.A.")
        if empresa_data
        else "King Driver, C.A."
    )

    st.title("📊 Libro de Ventas")
    st.markdown(f"### 🏢 {nombre}")
    st.markdown("---")

    # Validación inicial de empresa
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Selecciona una empresa en el menú lateral.")
        st.stop()

    # Inicialización de estado de pestaña activa
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "🔍 Consultar y Editar"

    # Estructura de pestañas
    tab_titles = ["📊 Cargar desde Excel", "🔍 Consultar y Editar", "🚨 Vaciado de Rango"]
    tab1, tab2, tab3 = st.tabs(tab_titles)

    # ==========================================
    # TAB 1: CARGAR DESDE EXCEL
    # ==========================================
    with tab1:
        st.subheader("📊 Cargar desde Excel")
        with st.expander("📥 Importar Libro de Ventas desde Excel", expanded=True):
            archivo_v = st.file_uploader("Seleccionar archivo Excel", type=['xlsx'], key="v_up_directo")
            
            if archivo_v:
                df_preview = pd.read_excel(archivo_v, header=0)

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

                if 'fecha_factura' in df_preview.columns:
                    df_preview['fecha_factura'] = pd.to_datetime(df_preview['fecha_factura'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('2026-06-13')
                
                column_config = {
                    "fecha_factura": st.column_config.TextColumn("fecha_factura")
                }
                
                resultado = st.data_editor(df_preview, key=f"editor_{archivo_v.name}", use_container_width=True, column_config=column_config)
                
                st.markdown("### 📊 Totales")
                def f_bs(v): return f"Bs. {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                cols_a_sumar = ['total_ventas_con_iva', 'ventas_exentas', 'base_imponible', 'debito_fiscal']
                df_limpio = resultado.copy()
                
                for col in cols_a_sumar:
                    if col in df_limpio.columns:
                        df_limpio[col] = pd.to_numeric(df_limpio[col], errors='coerce').fillna(0.0)
                    else:
                        df_limpio[col] = 0.0
                        st.warning(f"⚠️ La columna esperada '{col}' no se encontró en el archivo. Verifique el encabezado del Excel.")

                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Total Ventas", f_bs(df_limpio['total_ventas_con_iva'].sum()))
                t2.metric("Ventas Exentas", f_bs(df_limpio['ventas_exentas'].sum()))
                t3.metric("Total Base", f_bs(df_limpio['base_imponible'].sum()))
                t4.metric("Débito Fiscal", f_bs(df_limpio['debito_fiscal'].sum()))
                
                if st.button("🚀 Procesar e Importar", type="primary"):
                    with st.spinner("⏳ Procesando..."):
                        try:
                            conn_upload = conectar_db(db_actual)
                            if conn_upload:
                                if 'cargar_libro_ventas_db' in globals():
                                    cargar_libro_ventas_db(resultado, conn_upload)
                                conn_upload.close()
                                st.success("✅ Archivo procesado correctamente.")
                                st.balloons()
                        except Exception as e:
                            st.error(f"❌ Error crítico: {e}")

    # ==========================================
    # TAB 2: CONSULTAR Y EDITAR
    # ==========================================
    with tab2:
        st.subheader("🔍 Consultar y Editar: Libro de Ventas")
        st.info("💡 Consulta, modifica o elimina registros del libro de ventas almacenados en la base de datos.")
        
        col_v1, col_v2, col_v3 = st.columns([1, 1, 1])
        with col_v3:
            ver_todo_v = st.checkbox("📂 Ver todo", key="todo_ventas")

        def _obtener_f_segura_v(key_s):
            val = st.session_state.get(key_s)
            if val is not None:
                try:
                    if hasattr(val, "year") and hasattr(val, "month"):
                        return val
                    elif isinstance(val, str):
                        return datetime.strptime(val, "%Y-%m-%d").date()
                except Exception:
                    pass
            return datetime.today().date()

        with col_v1:
            desde_v = st.date_input("Desde", _obtener_f_segura_v("f_inicio_global_v"), key="desde_v", disabled=ver_todo_v)
        with col_v2:
            hasta_v = st.date_input("Hasta", _obtener_f_segura_v("f_fin_global_v"), key="hasta_v", disabled=ver_todo_v)

        @st.cache_data(ttl=30, show_spinner=False)
        def consultar_libro_ventas_cached(empresa, ver_todo_val, f_desde, f_hasta):
            df_res = pd.DataFrame()
            conn = conectar_db(empresa)
            if conn:
                try:
                    conn.ping(reconnect=True)
                    if ver_todo_val:
                        query = "SELECT * FROM libro_ventas ORDER BY fecha_factura DESC"
                        df_res = pd.read_sql(query, conn)
                    else:
                        query = "SELECT * FROM libro_ventas WHERE fecha_factura BETWEEN %s AND %s ORDER BY fecha_factura ASC"
                        df_res = pd.read_sql(query, conn, params=(f_desde, f_hasta))
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            return df_res

        if st.button("📊 Consultar Ventas", key="btn_consultar_ventas"):
            df_recuperado_v = consultar_libro_ventas_cached(db_actual, ver_todo_v, desde_v, hasta_v)
            if df_recuperado_v is not None and not df_recuperado_v.empty:
                st.session_state.df_ventas_editor = df_recuperado_v
            else:
                st.warning("No se encontraron registros de ventas en el rango seleccionado.")
                if "df_ventas_editor" in st.session_state:
                    del st.session_state.df_ventas_editor

        if "df_ventas_editor" in st.session_state:
            df_mostrar_ventas = st.session_state.df_ventas_editor.copy()
            st.subheader("✏️ Administrar Ventas (Modificar, Eliminar)")
            
            key_editor_ventas = "editor_consulta_ventas_final"
            cambios_ventas_df = st.data_editor(
                df_mostrar_ventas,
                key=key_editor_ventas,
                num_rows="fixed",
                use_container_width=True,
                hide_index=True
            )

    # ==========================================
    # TAB 3: VACIADO DE RANGO
    # ==========================================
    with tab3:
        st.subheader("🚨 Vaciado de Ventas por Rango")
        with st.popover("🚨 VACIAR VENTAS (RANGO SELECCIONADO)", use_container_width=True):
            st.subheader("Seleccionar Rango a Borrar")
            fecha_d_v = st.date_input("Desde:", key="rango_desde_borrar_ventas")
            fecha_h_v = st.date_input("Hasta:", key="rango_hasta_borrar_ventas")
            
            st.markdown("---")
            st.warning(f"Se eliminarán los registros de ventas desde {fecha_d_v} hasta {fecha_h_v}")
            confirmar_check_v = st.checkbox("Confirmo que deseo borrar las ventas", key="check_borrar_ventas")
            
            if st.button("EJECUTAR BORRADO VENTAS", type="primary", disabled=not confirmar_check_v, key="btn_ejecutar_borrado_ventas"):
                try:
                    conn_del_v = conectar_db(db_actual)
                    if conn_del_v:
                        conn_del_v.ping(reconnect=True)
                        with conn_del_v.cursor() as cursor:
                            cursor.execute(
                                "DELETE FROM libro_ventas WHERE fecha_factura BETWEEN %s AND %s",
                                (fecha_d_v.strftime('%Y-%m-%d'), fecha_h_v.strftime('%Y-%m-%d'))
                            )
                            conn_del_v.commit()
                        conn_del_v.close()
                    st.cache_data.clear()
                    st.success("✅ Rango de ventas eliminado correctamente.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al ejecutar el borrado: {e}")


def modulo_retencion_islr():
    aplicar_estilo_publico()
    db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
    empresa_data = obtener_datos_agente_db(db_actual)
    nombre = (
        empresa_data.get("nombre_empresa", "King Driver, C.A.")
        if empresa_data
        else "King Driver, C.A."
    )

    st.title("🧾 Comprobante de Retención ISLR")
    st.markdown(f"### 🏢 {nombre}")
    st.markdown("---")

    # Validación inicial de empresa
    if not db_actual or db_actual == 'none':
        st.warning("⚠️ Selecciona una empresa en el menú lateral.")
        st.stop()

    # -----------------------------------------
    # CONFIGURACIÓN TRIBUTARIA Y TAREAS (SIDEBAR)
    # -----------------------------------------
    st.sidebar.markdown("---") 
    st.sidebar.markdown("### ⚙️ Tareas de ISLR")

    VALOR_UT = 43.00
    FACTOR = 83.333333
    
    def calcular_sustraendo(porcentaje_retencion):
        sustraendos = {
            1.0: (FACTOR * 0.01) * VALOR_UT,
            2.0: (FACTOR * 0.02) * VALOR_UT,
            3.0: (FACTOR * 0.03) * VALOR_UT,
            5.0: (FACTOR * 0.05) * VALOR_UT
        }
        resultado = sustraendos.get(float(porcentaje_retencion), 0.00)
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
            
            ET.SubElement(detalle, "RifRetenido").text = "".join(filter(str.isalnum, str(row['rif_retenido'])))
            ET.SubElement(detalle, "NumeroFactura").text = "".join(filter(str.isalnum, str(row['numero_factura'])))
            ET.SubElement(detalle, "NumeroControl").text = "".join(filter(str.isalnum, str(row['numero_control'])))
            
            fecha_obj = row['fecha_operacion']
            if hasattr(fecha_obj, 'strftime'):
                fecha_str = fecha_obj.strftime("%d/%m/%Y")
            else:
                fecha_str = str(fecha_obj)
            ET.SubElement(detalle, "FechaOperacion").text = fecha_str
            
            codigo_concepto = str(row['codigo_concepto']).zfill(3)
            ET.SubElement(detalle, "CodigoConcepto").text = codigo_concepto
            ET.SubElement(detalle, "MontoOperacion").text = f"{float(row['monto_operacion']):.2f}"
            
            porcentaje = float(row['porcentaje_retencion'])
            ET.SubElement(detalle, "PorcentajeRetencion").text = f"{porcentaje:.2f}"

        xml_str = ET.tostring(root, encoding='utf-8')
        parsed = minidom.parseString(xml_str)
        return parsed.toprettyxml(indent="  ")

    # -----------------------------------------
    # TABLA DE REFERENCIA DE SUSTRAENDOS
    # -----------------------------------------
    with st.expander("📊 Ver Tabla de Referencia de Sustraendos (Manual SENIAT)", expanded=False):
        umbral_pnr = VALOR_UT * FACTOR 
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
        "nombre": nombre,
        "rif": empresa_data.get("rif", "J507757188") if empresa_data else "J507757188",
        "direccion": empresa_data.get("direccion", "CARACAS") if empresa_data else "CARACAS"
    }

    # -----------------------------------------
    # ESTRUCTURA DE LAS 6 PESTAÑAS
    # -----------------------------------------
    if 'active_tab_islr' not in st.session_state:
        st.session_state.active_tab_islr = 0

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
                            WHERE (lc.retencion_islr_realizada = 0 OR lc.retencion_islr_realizada IS NULL OR lc.retencion_islr_realizada = FALSE)
                            AND lc.fecha_operacion BETWEEN %s AND %s
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
        st.subheader("🖨️ Módulo de Reimpresión")
        st.info("Generación de formatos PDF listos para imprimir o enviar al proveedor.")
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

    with tab4:
        st.subheader("⚙️ Gestión de Facturas y Relaciones")
        st.info("Control de documentos vinculados a los pagos y retenciones.")
        st.divider()
        
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


    with tab5:
        st.subheader("🚀 Exportar XML para el SENIAT")
        st.info("Generación del archivo XML estructurado conforme a las normativas del portal del SENIAT.")
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

    with tab6:
        st.subheader("📊 Reportes y Resumen General")
        st.info("Estadísticas y totales acumulados por periodo fiscal.")
        # --- SECCIÓN C: GENERAR ARCHIVO XML SENIAT ---
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
            # Obtención segura de columnas manejando posibles nombres alternativos o nulos
            col_exento = 'importe_exento' if 'importe_exento' in facturas_seleccionadas.columns else ('monto_exento' if 'monto_exento' in facturas_seleccionadas.columns else None)
            
            total_base_agrupado = float(facturas_seleccionadas['base_imponible'].sum() if 'base_imponible' in facturas_seleccionadas.columns else 0)
            total_iva_agrupado = float(facturas_seleccionadas['iva_monto'].sum() if 'iva_monto' in facturas_seleccionadas.columns else facturas_seleccionadas.get('impuesto_iva', 0).sum())
            total_facturas_agrupado = float(facturas_seleccionadas['total_compras'].sum() if 'total_compras' in facturas_seleccionadas.columns else 0)
            total_exento_agrupado = float(facturas_seleccionadas[col_exento].sum() if col_exento else 0)
            
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
                
                domicilio_fiscal = (
                    empresa_data_env.get('direccion_fiscal') or 
                    empresa_data_env.get('direccion') or 
                    "DIRECCIÓN NO REGISTRADA"
                )

                cursor = None
                try:
                    cursor = conn_env.cursor()
        
                    for _, fila in facturas_seleccionadas.iterrows():
                        tipo_doc_str = str(fila.get('tipo_documento', '')).strip().lower()
                        monto_total_fila = float(fila.get('total_compras', 0) or 0)
                        es_nc = 'credito' in tipo_doc_str or 'nota de credito' in tipo_doc_str or monto_total_fila < 0
                        
                        signo = -1 if es_nc else 1

                        total_fila = abs(float(fila.get('total_compras', 0) or 0)) * signo
                        base = abs(float(fila.get('base_imponible', 0) or 0)) * signo
                        impuesto = abs(float(fila.get('iva_monto', 0) or fila.get('impuesto_iva', 0) or 0)) * signo
                        exento = abs(float(fila.get('importe_exento', 0) or 0)) * signo

                        if abs(base) == 0 and abs(impuesto) == 0 and abs(total_fila) > 0:
                            if abs(exento) > 0:
                                base = (abs(total_fila) - abs(exento)) * signo
                            else:
                                base = round(abs(total_fila) / 1.16, 2) * signo
                            impuesto = round(abs(total_fila) - abs(exento) - abs(base), 2) * signo

                        ratio = round(abs(impuesto) / abs(base), 2) if abs(base) > 0 else 0
                        es_8 = ratio <= 0.08
                        
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
                        n_nota_debito_val = None
                        
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
                            num_factura_val,       
                            num_control_val,       
                            n_nota_debito_val,     
                            n_nota_credito_val,    
                            n_factura_afectada_val,
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

                        # Actualización exclusiva de IVA sin tocar el ISLR
                        query_update = """
                            UPDATE libro_compras 
                            SET retencion_iva_realizada = 1 
                            WHERE id = %s
                        """
                        cursor.execute(query_update, (int(fila['id']),))

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

def modulo_retencion_iva():
    import datetime as dt
    
    aplicar_estilo_publico()
    
    db_actual = st.session_state.get("DB_ACTUAL", "kingdriver_ca")
    empresa_data = obtener_datos_agente_db(db_actual)
    nombre = (
        empresa_data.get("nombre_empresa", "King Driver, C.A.")
        if empresa_data
        else "King Driver, C.A."
    )

    st.title("🧾 Comprobante de Retención IVA")
    st.markdown(f"### 🏢 {nombre}")
    st.markdown("---")

    # Validación de base de datos activa
    if db_actual and db_actual != 'none':
        try:
            empresa_dict = {
                "nombre": nombre,
                "rif": empresa_data.get("rif", "J507757188") if empresa_data else "J507757188",
                "direccion": empresa_data.get("direccion", "CARACAS") if empresa_data else "CARACAS"
            }
            
            # Carga delegada a la interfaz principal de retención de IVA
            if 'mostrar_interfaz_retencion_iva' in globals():
                mostrar_interfaz_retencion_iva(
                    empresa_dict, 
                    st.session_state.get('f_inicio_global', dt.date.today()), 
                    st.session_state.get('f_fin_global', dt.date.today())
                )
            else:
                st.info("Módulo de retención IVA vinculado correctamente. Interfaz en preparación.")
        except Exception as e:
            st.error(f"❌ Error al cargar el módulo de Retención IVA: {e}")
    else:
        st.error("⚠️ No se detectó una base de datos activa en la sesión.")

if __name__ == "__main__":
    # Prueba local opcional
    pass
