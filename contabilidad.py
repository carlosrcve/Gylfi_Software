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

    # Estructura principal de pestañas
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

    with tab1:
        st.subheader("🔍 Consulta y Edición: Libro de Compras")
        st.info("💡 Utiliza las pestañas superiores para navegar entre el escaneo OCR, consulta de registros y herramientas de mantenimiento.")
        
        # Carga inicial básica de la tabla si existe
        engine = obtener_engine_cached(db_actual)
        try:
            df_inicial = pd.read_sql("SELECT * FROM libro_compras ORDER BY fecha_operacion DESC LIMIT 50", engine)
            if not df_inicial.empty:
                st.dataframe(df_inicial, use_container_width=True)
            else:
                st.info("ℹ️ No hay registros guardados en el libro de compras todavía.")
        except Exception:
            st.info("ℹ️ La tabla de compras se inicializará al registrar el primer documento.")

    with tab2:
        st.subheader("📸 Escaneo Inteligente de Documentos (OCR)")
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

    with tab3:
        st.subheader("🚨 Vaciado de Compras por Rango")
        st.warning("Herramienta para depuración de rangos de fechas en el libro de compras.")

    with tab4:
        st.info("📊 Módulo de Carga desde Excel en desarrollo.")
    with tab5:
        st.info("📁 Módulo de PDFs Por Lotes en desarrollo.")
    with tab6:
        st.info("📝 Módulo de Notas de Crédito / Débito en desarrollo.")


if __name__ == "__main__":
    modulo_compras()
