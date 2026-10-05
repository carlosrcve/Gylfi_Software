with tab6:
            st.markdown("### 🧾 Emisión de Facturas, Libro de Ventas y Registro de Cobranza (CxC)")
            st.markdown("Genera la factura de venta a tus clientes comerciales, impacta automáticamente el libro de ventas, genera el asiento contable y deja lista la expectativa de cobro bancario.")

            try:
                # 1. Cargar clientes comerciales desde la base de datos existente
                conn_cli = conectar_db(db_actual)
                df_clientes = None
                if conn_cli:
                    query_cli = "SELECT rif, razon_social, direccion_fiscal, codigo_cuenta FROM clientes_comerciales ORDER BY razon_social ASC"
                    df_clientes = ejecutar_consulta(query_cli, conn_cli)
                    conn_cli.close()

                if df_clientes is not None and not df_clientes.empty:
                    # Crear diccionario para el selectbox: Muestra Razón Social y RIF
                    dict_clientes = {}
                    for _, row in df_clientes.iterrows():
                        label_c = f"{row['razon_social']} (RIF: {row['rif']})"
                        dict_clientes[label_c] = {
                            "rif": row['rif'],
                            "razon_social": row['razon_social'],
                            "cuenta": row['codigo_cuenta']
                        }

                    selected_cliente_label = st.selectbox("1) Seleccionar Cliente Comercial", list(dict_clientes.keys()), key="select_cli_factura")
                    cli_info = dict_clientes[selected_cliente_label]

                    st.divider()
                    st.markdown("#### 📋 Datos de la Factura y Control Fiscal")
                    
                    col_f1, col_f2, col_f3 = st.columns(3)
                    with col_f1:
                        nro_factura = st.text_input("2) Número de Factura", placeholder="Ej. 00001234").strip()
                    with col_f2:
                        nro_control = st.text_input("3) Número de Control", placeholder="Ej. 00-000012").strip()
                    with col_f3:
                        fecha_emision = st.date_input("4) Fecha de Emisión")

                    st.divider()
                    st.markdown("#### 💰 Montos y Desglose Impositivo")

                    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                    with col_m1:
                        base_imponible = st.number_input("5) Base Imponible", min_value=0.0, step=100.0, format="%.2f")
                    with col_m2:
                        monto_exento = st.number_input("6) Monto Exento", min_value=0.0, step=0.0, format="%.2f")
                    with col_m3:
                        alicuota_iva = st.selectbox("7) Alícuota IVA (%)", [16.0, 8.0, 0.0], index=0)
                    
                    # Cálculos automáticos para los campos de IVA y Total
                    calc_iva = base_imponible * (alicuota_iva / 100.0)
                    calc_bruto = base_imponible + monto_exento + calc_iva

                    with col_m4:
                        monto_iva = st.number_input("8) Monto IVA", value=calc_iva, min_value=0.0, format="%.2f", disabled=True)
                    with col_m5:
                        monto_bruto = st.number_input("9) Monto Total Factura", value=calc_bruto, min_value=0.0, format="%.2f", disabled=True)

                    st.info(f"📊 **Resumen Fiscal:** Base Imponible: ${base_imponible:,.2f} | Exento: ${monto_exento:,.2f} | IVA ({alicuota_iva}%): ${monto_iva:,.2f} | Total Bruto: ${monto_bruto:,.2f}")
                    st.divider()
                    st.markdown("#### 🏦 Datos Preliminares del Cobro / Referencia Bancaria (Opcional si es a crédito)")
                    
                    # Consultar las cuentas bancarias o de efectivo desde plan_cuentas
                    dict_bancos = {}
                    try:
                        conn_pc = conectar_db(db_actual)
                        if conn_pc:
                            query_pc = "SELECT codigo, nombre FROM plan_cuentas WHERE tipo = 'Detalle' AND (codigo LIKE '101%%' OR nombre LIKE '%%Banco%%' OR nombre LIKE '%%Caja%%') ORDER BY nombre ASC"
                            df_bancos = ejecutar_consulta(query_pc, conn_pc)
                            conn_pc.close()
                            
                            if df_bancos is not None and not df_bancos.empty:
                                for _, r_b in df_bancos.iterrows():
                                    lbl_b = f"{r_b['codigo']} - {r_b['nombre']}"
                                    dict_bancos[lbl_b] = r_b['nombre']
                    except Exception as e_pc:
                        pass

                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        ref_banco_cobro = st.text_input("Referencia Bancaria del Pago (si ya fue pagada)").strip()
                    with col_b2:
                        if dict_bancos:
                            selected_banco_label = st.selectbox("Banco Receptor / Cuenta", list(dict_bancos.keys()))
                            banco_receptor = dict_bancos[selected_banco_label]
                        else:
                            banco_receptor = st.text_input("Banco Receptor / Cuenta", placeholder="Ej. Banesco Cta Custodia").strip()

                    st.divider()

                    # BOTÓN DE ACCIÓN GLOBAL CON LOS 3 DISPARADORES ADAPTADOS A LAS TABLAS
                    if st.button("🚀 Emitir Factura, Actualizar Libro de Ventas y Asiento Contable", type="primary", use_container_width=True):
                        if nro_factura and nro_control:
                            try:
                                conn_trans = conectar_db(db_actual)
                                if conn_trans:
                                    cursor = conn_trans.cursor()
                                    
                                    # A. Asegurar tabla ordenes_cobranza si no existe
                                    cursor.execute("""
                                        CREATE TABLE IF NOT EXISTS ordenes_cobranza (
                                            id INT AUTO_INCREMENT PRIMARY KEY,
                                            empresa_db VARCHAR(50),
                                            rif_cliente VARCHAR(20),
                                            n_factura VARCHAR(50),
                                            n_control VARCHAR(50),
                                            fecha_emision DATE,
                                            base_imponible DECIMAL(18,2),
                                            monto_exento DECIMAL(18,2),
                                            porcentaje_alicuota DECIMAL(5,2),
                                            monto_iva DECIMAL(18,2),
                                            monto_bruto DECIMAL(18,2),
                                            estado_cobro VARCHAR(50) DEFAULT 'Pendiente',
                                            referencia_banco VARCHAR(100),
                                            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                        )
                                    """)

                                    # B. Insertar en ordenes_cobranza
                                    q_ins_oc = """
                                        INSERT INTO ordenes_cobranza 
                                        (empresa_db, rif_cliente, n_factura, n_control, fecha_emision, base_imponible, monto_exento, porcentaje_alicuota, monto_iva, monto_bruto, referencia_banco, estado_cobro)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """
                                    estado_inicial = 'Conciliado' if ref_banco_cobro else 'Pendiente'
                                    cursor.execute(q_ins_oc, (
                                        str(db_actual), cli_info['rif'], nro_factura, nro_control, fecha_emision,
                                        base_imponible, monto_exento, alicuota_iva, monto_iva, monto_bruto,
                                        ref_banco_cobro if ref_banco_cobro else None, estado_inicial
                                    ))

                                    # FRAME 1: Insertar en libro_ventas (adaptado a sus columnas exactas)
                                    q_ins_lv = """
                                        INSERT INTO libro_ventas 
                                        (fecha_factura, nombre_razon_social, rif, n_factura, n_control, total_ventas_con_iva, ventas_exentas, base_imponible, porcentaje_alicuota, debito_fiscal)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """
                                    cursor.execute(q_ins_lv, (
                                        fecha_emision, cli_info['razon_social'], cli_info['rif'], nro_factura, nro_control,
                                        monto_bruto, monto_exento, base_imponible, alicuota_iva, monto_iva
                                    ))

                                    # FRAME 2: Insertar Asientos Contables (adaptado a la tabla asientos_contables)
                                    import time
                                    n_comprob_asiento = f"FACT-{nro_factura}-{int(time.time())}"
                                    desc_asiento = f"Venta de bienes/servicios según Factura Nro {nro_factura} a {cli_info['razon_social']}"
                                    
                                    # Línea 1: Cuenta por Cobrar (Debe - Monto Bruto)
                                    cursor.execute("""
                                        INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (n_comprob_asiento, desc_asiento, fecha_emision, cli_info['cuenta'], f"CxC - {cli_info['razon_social']}", nro_factura, monto_bruto, 0.00, 1))

                                    # Línea 2: Ingreso por Ventas (Haber - Base Imponible)
                                    if base_imponible > 0:
                                        cursor.execute("""
                                            INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """, (n_comprob_asiento, desc_asiento, fecha_emision, "401-01", "Ingresos por Ventas / Servicios", nro_factura, 0.00, base_imponible, 1))

                                    # Línea 3: Débito Fiscal IVA (Haber - Monto IVA)
                                    if monto_iva > 0:
                                        cursor.execute("""
                                            INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """, (n_comprob_asiento, desc_asiento, fecha_emision, "202-01", "Débito Fiscal IVA por Pagar", nro_factura, 0.00, monto_iva, 1))

                                    # FRAME 3: Si colocó referencia bancaria, registrar en banco_movimientos (adaptado a sus columnas exactas)
                                    if ref_banco_cobro:
                                        cursor.execute("""
                                            INSERT INTO banco_movimientos (banco_nombre, cuenta_numero, fecha_movimiento, referencia, descripcion, monto, estado_conciliacion)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                                        """, (
                                            banco_receptor if banco_receptor else "Banco Principal", "Principal", fecha_emision,
                                            ref_banco_cobro, f"Cobro de Factura {nro_factura} - {cli_info['razon_social']}", monto_bruto, "Conciliado"
                                        ))

                                    conn_trans.commit()
                                    cursor.close()
                                    conn_trans.close()

                                    st.success(f"✅ ¡Factura #{nro_factura} emitida con éxito! Se han guardado los registros en el Libro de Ventas, Asientos Contables y Tesorería.")
                                    st.balloons()
                                    st.rerun()

                                else:
                                    st.error("❌ No se pudo establecer conexión con la base de datos para guardar la transacción.")

                            except Exception as err_fac:
                                st.error(f"❌ Error crítico al procesar la factura y sus asientos: {err_fac}")
                        else:
                            st.warning("⚠️ Debes rellenar obligatoriamente el Número de Factura y el Número de Control fiscal.")

                    # =========================================================================
                    # 📊 PANEL DE VISUALIZACIÓN EN TIEMPO REAL
                    # =========================================================================
                    st.divider()
                    st.markdown("### 🔍 Registros Recientes en los Tres Frentes (Empresa: `" + str(db_actual) + "`)")
                    
                    sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
                        "🧾 Órdenes de Cobranza", 
                        "📖 Libro de Ventas", 
                        "⚖️ Asientos Contables", 
                        "🏦 Movimientos Bancarios"
                    ])

                    conn_vis = conectar_db(db_actual)
                    if conn_vis:
                        with sub_tab1:
                            st.markdown("#### Órdenes de Cobranza Registradas")
                            try:
                                df_oc = ejecutar_consulta("SELECT id, n_factura, n_control, fecha_emision, rif_cliente, monto_bruto, estado_cobro, referencia_banco FROM ordenes_cobranza ORDER BY id DESC LIMIT 20", conn_vis)
                                if df_oc is not None and not df_oc.empty:
                                    st.dataframe(df_oc, use_container_width=True)
                                else:
                                    st.info("No hay órdenes de cobranza registradas todavía.")
                            except Exception as e:
                                st.info("La tabla `ordenes_cobranza` aún no tiene datos o está por crearse.")

                        with sub_tab2:
                            st.markdown("#### Libro de Ventas (Fiscal)")
                            try:
                                df_lv = ejecutar_consulta("SELECT id, fecha_factura, n_factura, n_control, rif, nombre_razon_social, base_imponible, debito_fiscal, total_ventas_con_iva FROM libro_ventas ORDER BY id DESC LIMIT 20", conn_vis)
                                if df_lv is not None and not df_lv.empty:
                                    st.dataframe(df_lv, use_container_width=True)
                                else:
                                    st.info("No hay registros en el libro de ventas.")
                            except Exception as e:
                                st.info("Libro de ventas vacío o pendiente de primer registro.")

                        with sub_tab3:
                            st.markdown("#### Últimos Asientos Contables Generados")
                            try:
                                df_ac = ejecutar_consulta("SELECT id, n_comprobante, fecha, cuenta_contable, referencia, debe, haber, descripcion FROM asientos_contables ORDER BY id DESC LIMIT 30", conn_vis)
                                if df_ac is not None and not df_ac.empty:
                                    st.dataframe(df_ac, use_container_width=True)
                                else:
                                    st.info("No hay asientos contables registrados.")
                            except Exception as e:
                                st.info("Tabla de asientos contables vacía.")

                        with sub_tab4:
                            st.markdown("#### Movimientos de Tesorería / Bancos")
                            try:
                                df_bm = ejecutar_consulta("SELECT id, fecha_movimiento, banco_nombre, referencia, descripcion, monto, estado_conciliacion FROM banco_movimientos ORDER BY id DESC LIMIT 20", conn_vis)
                                if df_bm is not None and not df_bm.empty:
                                    st.dataframe(df_bm, use_container_width=True)
                                else:
                                    st.info("No hay movimientos bancarios registrados.")
                            except Exception as e:
                                st.info("Tabla de movimientos bancarios vacía.")

                        conn_vis.close()

                else:
                    st.info("ℹ️ No se encontraron clientes comerciales registrados. Cárgalos primero en el maestro de clientes.")

            except Exception as e_tab6:
                st.error(f"Error general en el módulo de facturación: {e_tab6}")
