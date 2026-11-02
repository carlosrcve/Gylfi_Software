# instagram.py - Módulo Independiente del Libro de Compras
#https://gylfisoftware.streamlit.app/?modulo=libro_compras
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

    with tab3:
        st.subheader("🚨 Vaciado de Compras por Rango")
        st.warning("Herramienta para depuración de rangos de fechas en el libro de compras.")

    with tab4:
        st.subheader("📊 Cargar desde Excel")
        st.info("📊 Carga Masiva desde Excel (LIBROS DE COMPRAS)")

    with tab5:
        st.subheader("📁 PDFs POR LOTES")
        st.info("Bandeja de Entrada - Procesamiento Local de Facturas (PDF)")

    with tab6:
        st.subheader("📝 Gestión de Notas de Crédito y Débito")
        st.info("💡 **Flujo Fiscal:** Consulta el libro de compras por fecha y genera su documento de ajuste.")


if __name__ == "__main__":
    modulo_compras()
