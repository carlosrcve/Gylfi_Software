with tab6:
    # =========================================================================
    # TAB 6: EMISIÓN DE FACTURAS Y GESTIÓN POR FRENTES (CxC)
    # =========================================================================
    st.markdown("### 🧾 Emisión de Facturas, Libro de Ventas y Registro de Cobranza (CxC)")
    st.markdown("Selecciona productos del inventario, genera la factura detallada por ítems, guarda la orden de cobranza y procesa independientemente cada frente fiscal, contable y bancario.")

    try:
        # 1. Cargar clientes comerciales desde la base de datos existente
        conn_cli = conectar_db(db_actual)
        df_clientes = None
        if conn_cli:
            query_cli = "SELECT rif, razon_social, direccion_fiscal, codigo_cuenta FROM clientes_comerciales ORDER BY razon_social ASC"
            df_clientes = ejecutar_consulta(query_cli, conn_cli)
            conn_cli.close()

        if df_clientes is not None and not df_clientes.empty:
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
                nro_factura = st.text_input("2) Número de Factura", placeholder="Ej. 00001234", key="input_nro_factura").strip()
            with col_f2:
                nro_control = st.text_input("3) Número de Control", placeholder="Ej. 00-000012", key="input_nro_control").strip()
            with col_f3:
                fecha_emision = st.date_input("4) Fecha de Emisión", key="input_fecha_emision")

            # =========================================================================
            # 🛒 DETALLE DE ÍTEMS / LÍNEAS DE VENTA CONECTADO A LA TABLA PRODUCTO
            # =========================================================================
            st.divider()
            st.markdown("#### 🛒 Detalle de Ítems / Líneas de Venta")
            st.markdown("Selecciona los productos del inventario y define la cantidad. El precio y el total se calculan automáticamente.")

            # 1. Cargar catálogo de productos disponibles desde la base de datos MySQL
            df_catalogo_prod = None
            lista_opciones_productos = []
            dict_productos = {}

            try:
                conn_prod = conectar_db(db_actual)
                if conn_prod:
                    df_catalogo_prod = ejecutar_consulta(
                        "SELECT codigo_producto, descripcion, precio_unitario FROM producto ORDER BY descripcion ASC", 
                        conn_prod
                    )
                    conn_prod.close()
                    
                    if df_catalogo_prod is not None and not df_catalogo_prod.empty:
                        for _, prod_row in df_catalogo_prod.iterrows():
                            label_prod = f"{prod_row['codigo_producto']} - {prod_row['descripcion']} (${prod_row['precio_unitario']:,.2f})"
                            lista_opciones_productos.append(label_prod)
                            dict_productos[label_prod] = {
                                "codigo": prod_row['codigo_producto'],
                                "descripcion": prod_row['descripcion'],
                                "precio": float(prod_row['precio_unitario'])
                            }
            except Exception as e:
                st.error(f"Error al cargar el catálogo de productos: {e}")

            # 2. Controlar el número de líneas de la factura en el session_state
            if "num_lineas_factura" not in st.session_state:
                st.session_state.num_lineas_factura = 1

            col_add_btn, col_del_btn = st.columns([1, 1])
            with col_add_btn:
                if st.button("➕ Agregar Línea de Producto"):
                    st.session_state.num_lineas_factura += 1
                    st.rerun()
            with col_del_btn:
                if st.session_state.num_lineas_factura > 1:
                    if st.button("➖ Eliminar Última Línea"):
                        st.session_state.num_lineas_factura -= 1
                        st.rerun()

            # 3. Renderizar filas interactivas
            items_factura_guardar = []
            base_imponible = 0.0

            if lista_opciones_productos:
                for i in range(st.session_state.num_lineas_factura):
                    st.markdown(f"**Renglón #{i+1}**")
                    c1, c2, c3, c4 = st.columns([3, 1.5, 2, 2])
                    
                    with c1:
                        prod_seleccionado = st.selectbox(
                            "Producto / Servicio", 
                            options=lista_opciones_productos, 
                            key=f"select_prod_{i}"
                        )
                    
                    info_prod = dict_productos[prod_seleccionado]
                    codigo_prod = info_prod["codigo"]
                    desc_prod = info_prod["descripcion"]
                    precio_unit = info_prod["precio"]
                    
                    with c2:
                        cantidad = st.number_input(
                            "Cantidad", 
                            min_value=0.01, 
                            value=1.0, 
                            step=1.0, 
                            format="%.2f", 
                            key=f"cant_prod_{i}"
                        )
                        
                    with c3:
                        precio_final_unit = st.number_input(
                            "Precio Unitario ($)", 
                            min_value=0.0, 
                            value=precio_unit, 
                            format="%.2f", 
                            key=f"precio_prod_{i}"
                        )
                        
                    with c4:
                        total_linea = cantidad * precio_final_unit
                        st.metric(label="Total Línea ($)", value=f"${total_linea:,.2f}")
                        
                    base_imponible += total_linea
                    
                    items_factura_guardar.append({
                        "Código": codigo_prod,
                        "Descripción": desc_prod,
                        "Cantidad": cantidad,
                        "Precio Unitario": precio_final_unit,
                        "Total ($)": total_linea
                    })
                    st.divider()
            else:
                st.warning("⚠️ No se encontraron productos registrados en la tabla `producto`. Por favor registra productos primero en el inventario.")
                base_imponible = 0.0

            import pandas as pd
            edited_items_df = pd.DataFrame(items_factura_guardar) if items_factura_guardar else pd.DataFrame(columns=["Código", "Descripción", "Cantidad", "Precio Unitario", "Total ($)"])

            # =========================================================================
            # 💰 DESGLOSE IMPOSITIVO Y TOTALES
            # =========================================================================
            st.markdown("#### 💰 Desglose Impositivo y Totales")

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                monto_exento = st.number_input("Monto Exento", min_value=0.0, step=1.0, format="%0.2f", key="input_monto_ex")
            with col_m2:
                alicuota_iva = st.selectbox("Alícuota IVA (%)", [16.0, 8.0, 0.0], index=0, key="select_alicuota")

            calc_iva = base_imponible * (alicuota_iva / 100.0)
            calc_bruto = base_imponible + monto_exento + calc_iva

            with col_m3:
                monto_iva = st.number_input("Monto IVA", value=calc_iva, min_value=0.0, format="%0.2f", disabled=True, key="input_monto_iva_f")
            with col_m4:
                monto_bruto = st.number_input("Monto Total Factura", value=calc_bruto, min_value=0.0, format="%0.2f", disabled=True, key="input_monto_bruto_f")

            st.info(f"📊 **Resumen Fiscal:** Base Imponible (Ítems): ${base_imponible:,.2f} | Exento: ${monto_exento:,.2f} | IVA ({alicuota_iva}%): ${monto_iva:,.2f} | Total Bruto: ${monto_bruto:,.2f}")
            st.divider()
            st.markdown("#### 🏦 Datos Preliminares del Cobro / Referencia Bancaria (Opcional si es a crédito)")
            
            dict_bancos = {}
            try:
                conn_pc = conectar_db(db_actual)
                if conn_pc:
                    query_pc = "SELECT codigo, nombre FROM plan_cuentas WHERE tipo = 'Detalle' AND (codigo LIKE '101%' OR nombre LIKE '%Banco%' OR nombre LIKE '%Caja%') ORDER BY nombre ASC"
                    df_bancos = ejecutar_consulta(query_pc, conn_pc)
                    conn_pc.close()
                    
                    if df_bancos is not None and not df_bancos.empty:
                        for _, r_b in df_bancos.iterrows():
                            lbl_b = f"{r_b['codigo']} - {r_b['nombre']}"
                            dict_bancos[lbl_b] = r_b['nombre']
            except Exception:
                pass

            col_b1, col_b2 = st.columns(2)
            with col_b1:
                ref_banco_cobro = st.text_input("Referencia Bancaria del Pago (si ya fue pagada)", key="input_ref_banco").strip()
            with col_b2:
                if dict_bancos:
                    selected_banco_label = st.selectbox("Banco Receptor / Cuenta", list(dict_bancos.keys()), key="select_banco_receptor")
                    banco_receptor = dict_bancos[selected_banco_label]
                else:
                    banco_receptor = st.text_input("Banco Receptor / Cuenta", placeholder="Ej. Banesco Cta Custodia", key="input_banco_manual").strip()

            st.divider()

            # BOTÓN PARA GUARDAR LA FACTURA, DETALLES Y ORDEN DE COBRANZA
            if st.button("🚀 Guardar Factura, Detalles y Orden de Cobranza", type="primary", use_container_width=True, key="btn_guardar_orden_cobranza"):
                if nro_factura and nro_control:
                    try:
                        conn_trans = conectar_db(db_actual)
                        if conn_trans:
                            cursor = conn_trans.cursor()
                            estado_inicial = 'Conciliado' if ref_banco_cobro else 'Pendiente'
                            
                            # 1. Guardar en la tabla 'ordenes_cobranza'
                            cursor.execute("""
                                INSERT INTO ordenes_cobranza 
                                (empresa_db, rif_cliente, n_factura, n_control, fecha_emision, base_imponible, monto_exento, porcentaje_alicuota, monto_iva, monto_bruto, referencia_banco, estado_cobro)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                str(db_actual), cli_info['rif'], nro_factura, nro_control, fecha_emision,
                                base_imponible, monto_exento, alicuota_iva, monto_iva, monto_bruto,
                                ref_banco_cobro if ref_banco_cobro else None, estado_inicial
                            ))

                            # 2. Guardar en la tabla maestra 'factura'
                            cursor.execute("""
                                INSERT INTO factura 
                                (empresa_db, rif_cliente, n_factura, n_control, fecha_emision, base_imponible, monto_exento, porcentaje_alicuota, monto_iva, monto_bruto, estado_cobro, referencia_banco)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                str(db_actual), cli_info['rif'], nro_factura, nro_control, fecha_emision,
                                base_imponible, monto_exento, alicuota_iva, monto_iva, monto_bruto,
                                estado_inicial, ref_banco_cobro if ref_banco_cobro else None
                            ))

                            # 3. Guardar cada ítem en la tabla 'factura_detalle'
                            for _, row_item in edited_items_df.iterrows():
                                cursor.execute("""
                                    INSERT INTO factura_detalle 
                                    (n_factura, codigo_producto, descripcion, cantidad, precio_unitario, total_linea)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """, (
                                    nro_factura,
                                    str(row_item['Código']),
                                    str(row_item['Descripción']),
                                    float(row_item['Cantidad']),
                                    float(row_item['Precio Unitario']),
                                    float(row_item['Total ($)'])
                                ))

                            conn_trans.commit()
                            cursor.close()
                            conn_trans.close()

                            st.success("✅ ¡Factura, detalles y orden de cobranza guardados con éxito en la base de datos!")
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("❌ Error de conexión con la base de datos.")
                    except Exception as err_fac:
                        st.error(f"❌ Error al procesar: {err_fac}")
                else:
                    st.warning("⚠️ Debes rellenar el Número de Factura y Control.")

            # =========================================================================
            # 📊 PANEL DE GESTIÓN POR FRENTES (SIN MODIFICAR LOS OTROS 3 FRAMES)
            # =========================================================================
            st.divider()
            st.markdown(f"### 🔍 Gestión por Frentes (Empresa: `{db_actual}`)")
            
            sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
                "🧾 Órdenes de Cobranza", 
                "📖 Libro de Ventas", 
                "⚖️ Asientos Contables", 
                "🏦 Movimientos Bancarios"
            ])

            conn_vis = conectar_db(db_actual)
            if conn_vis:
                # -------------------------------------------------------------
                # SUB-TAB 1: Órdenes de Cobranza
                # -------------------------------------------------------------
                with sub_tab1:
                    st.markdown("#### Órdenes de Cobranza Registradas")
                    try:
                        df_oc = ejecutar_consulta("SELECT id, n_factura, n_control, fecha_emision, rif_cliente, monto_bruto, estado_cobro, referencia_banco FROM ordenes_cobranza ORDER BY id DESC LIMIT 20", conn_vis)
                        if df_oc is not None and not df_oc.empty:
                            st.dataframe(df_oc, use_container_width=True)
                        else:
                            st.info("No hay órdenes de cobranza registradas todavía.")
                    except Exception:
                        st.info("La tabla `ordenes_cobranza` aún no tiene datos o está por crearse.")

                # -------------------------------------------------------------
                # SUB-TAB 2: Libro de Ventas
                # -------------------------------------------------------------
                with sub_tab2:
                    st.markdown("#### 📖 Libro de Ventas - Facturas Pendientes de Registrar")
                    try:
                        df_oc_pend = ejecutar_consulta("SELECT id, fecha_emision, n_factura, n_control, rif_cliente, monto_bruto, base_imponible, porcentaje_alicuota, monto_iva, monto_exento FROM ordenes_cobranza ORDER BY id DESC LIMIT 10", conn_vis)
                        
                        if df_oc_pend is not None and not df_oc_pend.empty:
                            df_frame_lv = pd.DataFrame({
                                "id": df_oc_pend['id'],
                                "fecha_factura": df_oc_pend['fecha_emision'],
                                "nombre_razon_social": cli_info['razon_social'],
                                "rif": df_oc_pend['rif_cliente'],
                                "n_factura": df_oc_pend['n_factura'],
                                "n_control": df_oc_pend['n_control'],
                                "total_ventas_con_iva": df_oc_pend['monto_bruto'],
                                "ventas_exentas": df_oc_pend['monto_exento'],
                                "base_imponible": df_oc_pend['base_imponible'],
                                "porcentaje_alicuota": df_oc_pend['porcentaje_alicuota'],
                                "debito_fiscal": df_oc_pend['monto_iva'],
                                "fecha_registro": pd.Timestamp.now()
                            })
                            
                            st.markdown("##### Frame con Estructura Oficial (`libro_ventas`):")
                            st.dataframe(df_frame_lv, use_container_width=True)
                            
                            sel_oc_id_lv = st.selectbox("Seleccione ID de Orden de Cobranza a guardar", df_oc_pend['id'].tolist(), key="sel_lv_id")
                            selected_row_lv = df_frame_lv[df_frame_lv['id'] == sel_oc_id_lv].iloc[0]

                            if st.button("💾 Guardar en Libro de Ventas", key="btn_save_lv_action"):
                                try:
                                    conn_lv = conectar_db(db_actual)
                                    cur_lv = conn_lv.cursor()
                                    cur_lv.execute("""
                                        INSERT INTO libro_ventas 
                                        (fecha_factura, nombre_razon_social, rif, n_factura, n_control, total_ventas_con_iva, ventas_exentas, base_imponible, porcentaje_alicuota, debito_fiscal)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (
                                        selected_row_lv['fecha_factura'], selected_row_lv['nombre_razon_social'], selected_row_lv['rif'],
                                        selected_row_lv['n_factura'], selected_row_lv['n_control'], selected_row_lv['total_ventas_con_iva'],
                                        selected_row_lv['ventas_exentas'], selected_row_lv['base_imponible'], selected_row_lv['porcentaje_alicuota'],
                                        selected_row_lv['debito_fiscal']
                                    ))
                                    conn_lv.commit()
                                    cur_lv.close()
                                    conn_lv.close()
                                    st.success("✅ ¡Factura guardada exitosamente en el Libro de Ventas!")
                                    st.rerun()
                                except Exception as err_ins_lv:
                                    st.error(f"❌ Error al guardar en libro_ventas: {err_ins_lv}")
                        else:
                            st.info("No hay órdenes de cobranza disponibles.")
                    except Exception as e_lv_err:
                        st.error(f"Error cargando frame: {e_lv_err}")

                # -------------------------------------------------------------
                # SUB-TAB 3: Asientos Contables
                # -------------------------------------------------------------
                with sub_tab3:
                    st.markdown("#### ⚖ Asientos Contables - Facturas Pendientes de Registrar")
                    try:
                        df_oc_ac = ejecutar_consulta("SELECT id, fecha_emision, n_factura, rif_cliente, monto_bruto, base_imponible, monto_iva FROM ordenes_cobranza ORDER BY id DESC LIMIT 10", conn_vis)
                        
                        if df_oc_ac is not None and not df_oc_ac.empty:
                            import time
                            df_frame_ac = pd.DataFrame({
                                "id": df_oc_ac['id'],
                                "n_comprobante": [f"FACT-{f}-{int(time.time())}" for f in df_oc_ac['n_factura']],
                                "descripcion": [f"Venta según Factura {f}" for f in df_oc_ac['n_factura']],
                                "fecha": df_oc_ac['fecha_emision'],
                                "plan_cuentas": cli_info['cuenta'],
                                "cuenta_contable": "CxC Cliente",
                                "referencia": df_oc_ac['n_factura'],
                                "debe": df_oc_ac['monto_bruto'],
                                "haber": 0.00,
                                "bloqueado": 1
                            })

                            st.markdown("##### Frame con Estructura Oficial (`asientos_contables`):")
                            st.dataframe(df_frame_ac, use_container_width=True)
                            
                            sel_oc_id_ac = st.selectbox("Seleccione ID de Orden de Cobranza a guardar", df_oc_ac['id'].tolist(), key="sel_ac_id")
                            selected_row_ac = df_oc_ac[df_oc_ac['id'] == sel_oc_id_ac].iloc[0]

                            if st.button("💾 Guardar en Asientos Contables", key="btn_save_ac_action"):
                                try:
                                    conn_ac = conectar_db(db_actual)
                                    cur_ac = conn_ac.cursor()
                                    n_comp = f"FACT-{selected_row_ac['n_factura']}-{int(time.time())}"
                                    desc_ast = f"Venta según Factura {selected_row_ac['n_factura']}"

                                    # 1. Débito (CxC)
                                    cur_ac.execute("""
                                        INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (n_comp, desc_ast, selected_row_ac['fecha_emision'], cli_info['cuenta'], "CxC Cliente", selected_row_ac['n_factura'], selected_row_ac['monto_bruto'], 0.00, 1))

                                    # 2. Haber (Ingresos)
                                    if selected_row_ac['base_imponible'] > 0:
                                        cur_ac.execute("""
                                            INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """, (n_comp, desc_ast, selected_row_ac['fecha_emision'], "401-01", "Ingresos por Ventas / Servicios", selected_row_ac['n_factura'], 0.00, selected_row_ac['base_imponible'], 1))

                                    # 3. Haber (IVA)
                                    if selected_row_ac['monto_iva'] > 0:
                                        cur_ac.execute("""
                                            INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """, (n_comp, desc_ast, selected_row_ac['fecha_emision'], "202-01", "Débito Fiscal IVA por Pagar", selected_row_ac['n_factura'], 0.00, selected_row_ac['monto_iva'], 1))

                                    conn_ac.commit()
                                    cur_ac.close()
                                    conn_ac.close()
                                    st.success("✅ ¡Asiento contable guardado con éxito con su estructura exacta!")
                                    st.rerun()
                                except Exception as err_ins_ac:
                                    st.error(f"❌ Error al guardar en asientos_contables: {err_ins_ac}")
                        else:
                            st.info("No hay órdenes de cobranza disponibles.")
                    except Exception as e_ac_err:
                        st.error(f"Error cargando frame: {e_ac_err}")

                # -------------------------------------------------------------
                # SUB-TAB 4: Movimientos Bancarios
                # -------------------------------------------------------------
                with sub_tab4:
                    st.markdown("#### 🏦 Movimientos Bancarios - Pagos Pendientes de Registrar")
                    try:
                        df_oc_bm = ejecutar_consulta("SELECT id, fecha_emision, n_factura, monto_bruto, referencia_banco FROM ordenes_cobranza WHERE referencia_banco IS NOT NULL AND referencia_banco != '' ORDER BY id DESC LIMIT 10", conn_vis)
                        
                        if df_oc_bm is not None and not df_oc_bm.empty:
                            df_frame_bm = pd.DataFrame({
                                "id": df_oc_bm['id'],
                                "banco_nombre": banco_receptor if banco_receptor else "Banco Principal",
                                "cuenta_numero": "Principal",
                                "fecha_movimiento": df_oc_bm['fecha_emision'],
                                "referencia": df_oc_bm['referencia_banco'],
                                "descripcion": [f"Cobro Factura {f}" for f in df_oc_bm['n_factura']],
                                "monto": df_oc_bm['monto_bruto'],
                                "estado_conciliacion": "Conciliado",
                                "asiento_id": None,
                                "fecha_importacion": pd.Timestamp.now()
                            })

                            st.markdown("##### Frame con Estructura Oficial (`banco_movimientos`):")
                            st.dataframe(df_frame_bm, use_container_width=True)
                            
                            sel_oc_id_bm = st.selectbox("Seleccione ID de Orden de Cobranza a guardar", df_oc_bm['id'].tolist(), key="sel_bm_id")
                            selected_row_bm = df_frame_bm[df_frame_bm['id'] == sel_oc_id_bm].iloc[0]

                            if st.button("💾 Guardar en Movimientos Bancarios", key="btn_save_bm_action"):
                                try:
                                    conn_bm = conectar_db(db_actual)
                                    cur_bm = conn_bm.cursor()
                                    cur_bm.execute("""
                                        INSERT INTO banco_movimientos (banco_nombre, cuenta_numero, fecha_movimiento, referencia, descripcion, monto, estado_conciliacion, asiento_id, fecha_importacion)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                                    """, (
                                        banco_receptor if banco_receptor else "Banco Principal", "Principal",
                                        selected_row_bm['fecha_movimiento'], selected_row_bm['referencia'],
                                        f"Cobro Factura {selected_row_bm['referencia']}", selected_row_bm['monto'],
                                        "Conciliado", None
                                    ))
                                    conn_bm.commit()
                                    cur_bm.close()
                                    conn_bm.close()
                                    st.success("✅ ¡Movimiento bancario guardado con éxito con su estructura exacta!")
                                    st.rerun()
                                except Exception as err_ins_bm:
                                    st.error(f"❌ Error al guardar en banco_movimientos: {err_ins_bm}")
                        else:
                            st.info("No hay pagos con referencia bancaria registrados pendientes.")
                    except Exception as e_bm_err:
                        st.error(f"Error cargando frame: {e_bm_err}")

                conn_vis.close()
        else:
            st.warning("⚠️ No se encontraron clientes comerciales registrados. Por favor, crea al menos un cliente primero.")
    except Exception as e_tab6:
        st.error(f"❌ Error general en la Pestaña 6: {e_tab6}")





with tab6:
            # =========================================================================
            # TAB 6: EMISIÓN DE FACTURAS Y GESTIÓN POR FRENTES (CxC)
            # =========================================================================
            st.markdown("### 🧾 Emisión de Facturas, Libro de Ventas y Registro de Cobranza (CxC)")
            st.markdown("Selecciona productos del inventario, genera la factura detallada por ítems, guarda la orden de cobranza y procesa independientemente cada frente fiscal, contable y bancario.")

            # 0. Asegurar la existencia de las tablas necesarias (producto, factura, factura_detalle) y datos iniciales
            # 0. Asegurar la existencia de las tablas necesarias y datos iniciales
            try:
                conn_init = conectar_db(db_actual)
                if conn_init:
                    cur_init = conn_init.cursor()
                    
                    # Tabla producto
                    cur_init.execute("""
                        CREATE TABLE IF NOT EXISTS producto (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            codigo_producto VARCHAR(50) UNIQUE,
                            descripcion VARCHAR(255),
                            precio_unitario DECIMAL(18,2),
                            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Insertar productos iniciales por defecto si la tabla está vacía
                    cur_init.execute("SELECT COUNT(*) FROM producto")
                    count_prod = cur_init.fetchone()[0]
                    if count_prod == 0:
                        productos_iniciales = [
                            ('PROD-001', 'Servicio o Producto Principal', 0.00),
                            ('PROD-002', 'Consultoría Contable y Tributaria', 100.00),
                            ('PROD-003', 'Asesoría Fiscal Mensual', 150.00)
                        ]
                        cur_init.executemany("""
                            INSERT INTO producto (codigo_producto, descripcion, precio_unitario)
                            VALUES (%s, %s, %s)
                        """, productos_iniciales)
                        conn_init.commit()

                    # Tabla factura principal
                    cur_init.execute("""
                        CREATE TABLE IF NOT EXISTS factura (
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

                    # Tabla factura_detalle (CORREGIDO: sin espacios y sin comentarios dentro del SQL)
                    cur_init.execute("""
                        CREATE TABLE IF NOT EXISTS factura_detalle (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            n_factura VARCHAR(50),
                            codigo_producto VARCHAR(50),
                            descripcion VARCHAR(255),
                            cantidad DECIMAL(18,2),
                            precio_unitario DECIMAL(18,2),
                            total_linea DECIMAL(18,2),
                            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    conn_init.commit()
                    cur_init.close()
                    conn_init.close()
            except Exception as e_init:
                st.warning(f"Aviso en inicialización de tablas: {e_init}")

            try:
                # 1. Cargar clientes comerciales desde la base de datos existente
                conn_cli = conectar_db(db_actual)
                df_clientes = None
                if conn_cli:
                    query_cli = "SELECT rif, razon_social, direccion_fiscal, codigo_cuenta FROM clientes_comerciales ORDER BY razon_social ASC"
                    df_clientes = ejecutar_consulta(query_cli, conn_cli)
                    conn_cli.close()

                if df_clientes is not None and not df_clientes.empty:
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
                        nro_factura = st.text_input("2) Número de Factura", placeholder="Ej. 00001234", key="input_nro_factura").strip()
                    with col_f2:
                        nro_control = st.text_input("3) Número de Control", placeholder="Ej. 00-000012", key="input_nro_control").strip()
                    with col_f3:
                        fecha_emision = st.date_input("4) Fecha de Emisión", key="input_fecha_emision")

                    # =========================================================================
                    # 🛒 DETALLE DE ÍTEMS / LÍNEAS DE VENTA CONECTADO A LA TABLA PRODUCTO
                    # =========================================================================
                    st.divider()
                    st.markdown("#### 🛒 Detalle de Ítems / Líneas de Venta")
                    st.markdown("Selecciona los productos del inventario y define la cantidad. El precio y el total se calculan automáticamente.")

                    # 1. Cargar catálogo de productos disponibles desde la base de datos MySQL
                    df_catalogo_prod = None
                    lista_opciones_productos = []
                    dict_productos = {}

                    try:
                        conn_prod = conectar_db(db_actual)
                        if conn_prod:
                            df_catalogo_prod = ejecutar_consulta(
                                "SELECT codigo_producto, descripcion, precio_unitario FROM producto ORDER BY descripcion ASC", 
                                conn_prod
                            )
                            conn_prod.close()
                            
                            if df_catalogo_prod is not None and not df_catalogo_prod.empty:
                                for _, prod_row in df_catalogo_prod.iterrows():
                                    # Formato legible para la lista desplegable
                                    label_prod = f"{prod_row['codigo_producto']} - {prod_row['descripcion']} (${prod_row['precio_unitario']:,.2f})"
                                    lista_opciones_productos.append(label_prod)
                                    dict_productos[label_prod] = {
                                        "codigo": prod_row['codigo_producto'],
                                        "descripcion": prod_row['descripcion'],
                                        "precio": float(prod_row['precio_unitario'])
                                    }
                    except Exception as e:
                        st.error(f"Error al cargar el catálogo de productos: {e}")

                    # 2. Controlar el número de líneas de la factura en el session_state
                    if "num_lineas_factura" not in st.session_state:
                        st.session_state.num_lineas_factura = 1

                    col_add_btn, col_del_btn = st.columns([1, 1])
                    with col_add_btn:
                        if st.button("➕ Agregar Línea de Producto"):
                            st.session_state.num_lineas_factura += 1
                            st.rerun()
                    with col_del_btn:
                        if st.session_state.num_lineas_factura > 1:
                            if st.button("➖ Eliminar Última Línea"):
                                st.session_state.num_lineas_factura -= 1
                                st.rerun()

                    # 3. Renderizar filas interactivas
                    items_factura_guardar = []
                    base_imponible = 0.0

                    if lista_opciones_productos:
                        for i in range(st.session_state.num_lineas_factura):
                            st.markdown(f"**Renglón #{i+1}**")
                            c1, c2, c3, c4 = st.columns([3, 1.5, 2, 2])
                            
                            with c1:
                                prod_seleccionado = st.selectbox(
                                    "Producto / Servicio", 
                                    options=lista_opciones_productos, 
                                    key=f"select_prod_{i}"
                                )
                            
                            # Extraer datos del producto seleccionado
                            info_prod = dict_productos[prod_seleccionado]
                            codigo_prod = info_prod["codigo"]
                            desc_prod = info_prod["descripcion"]
                            precio_unit = info_prod["precio"]
                            
                            with c2:
                                cantidad = st.number_input(
                                    "Cantidad", 
                                    min_value=0.01, 
                                    value=1.0, 
                                    step=1.0, 
                                    format="%.2f", 
                                    key=f"cant_prod_{i}"
                                )
                                
                            with c3:
                                # Mostrar precio unitario (heredado de la tabla producto, editable o fijo según prefieras)
                                precio_final_unit = st.number_input(
                                    "Precio Unitario ($)", 
                                    min_value=0.0, 
                                    value=precio_unit, 
                                    format="%.2f", 
                                    key=f"precio_prod_{i}"
                                )
                                
                            with c4:
                                total_linea = cantidad * precio_final_unit
                                st.metric(label="Total Línea ($)", value=f"${total_linea:,.2f}")
                                
                            base_imponible += total_linea
                            
                            # Almacenar para el guardado en base de datos
                            items_factura_guardar.append({
                                "Código": codigo_prod,
                                "Descripción": desc_prod,
                                "Cantidad": cantidad,
                                "Precio Unitario": precio_final_unit,
                                "Total ($)": total_linea
                            })
                            st.divider()
                    else:
                        st.warning("⚠️ No se encontraron productos registrados en la tabla `producto`. Por favor registra productos primero en el inventario.")
                        base_imponible = 0.0

                    # DataFrame consolidado para las operaciones posteriores
                    import pandas as pd
                    edited_items_df = pd.DataFrame(items_factura_guardar) if items_factura_guardar else pd.DataFrame(columns=["Código", "Descripción", "Cantidad", "Precio Unitario", "Total ($)"])

                    # =========================================================================
                    # 💰 DESGLOSE IMPOSITIVO Y TOTALES
                    # =========================================================================
                    st.markdown("#### 💰 Desglose Impositivo y Totales")

                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    with col_m1:
                        monto_exento = st.number_input("Monto Exento", min_value=0.0, step=1.0, format="%0.2f", key="input_monto_ex")
                    with col_m2:
                        alicuota_iva = st.selectbox("Alícuota IVA (%)", [16.0, 8.0, 0.0], index=0, key="select_alicuota")

                    calc_iva = base_imponible * (alicuota_iva / 100.0)
                    calc_bruto = base_imponible + monto_exento + calc_iva

                    with col_m3:
                        monto_iva = st.number_input("Monto IVA", value=calc_iva, min_value=0.0, format="%0.2f", disabled=True, key="input_monto_iva_f")
                    with col_m4:
                        monto_bruto = st.number_input("Monto Total Factura", value=calc_bruto, min_value=0.0, format="%0.2f", disabled=True, key="input_monto_bruto_f")

                    st.info(f"📊 **Resumen Fiscal:** Base Imponible (Ítems): ${base_imponible:,.2f} | Exento: ${monto_exento:,.2f} | IVA ({alicuota_iva}%): ${monto_iva:,.2f} | Total Bruto: ${monto_bruto:,.2f}")
                    st.divider()
                    st.markdown("#### 🏦 Datos Preliminares del Cobro / Referencia Bancaria (Opcional si es a crédito)")
                    
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
                    except Exception:
                        pass

                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        ref_banco_cobro = st.text_input("Referencia Bancaria del Pago (si ya fue pagada)", key="input_ref_banco").strip()
                    with col_b2:
                        if dict_bancos:
                            selected_banco_label = st.selectbox("Banco Receptor / Cuenta", list(dict_bancos.keys()), key="select_banco_receptor")
                            banco_receptor = dict_bancos[selected_banco_label]
                        else:
                            banco_receptor = st.text_input("Banco Receptor / Cuenta", placeholder="Ej. Banesco Cta Custodia", key="input_banco_manual").strip()

                    st.divider()

                    # BOTÓN PARA GUARDAR LA FACTURA, DETALLES Y ORDEN DE COBRANZA
                    if st.button("🚀 Guardar Factura, Detalles y Orden de Cobranza", type="primary", use_container_width=True, key="btn_guardar_orden_cobranza"):
                        if nro_factura and nro_control:
                            try:
                                conn_trans = conectar_db(db_actual)
                                if conn_trans:
                                    cursor = conn_trans.cursor()
                                    
                                    # 1. Guardar o actualizar en la tabla 'ordenes_cobranza' (para los frentes inferiores existentes)
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

                                    estado_inicial = 'Conciliado' if ref_banco_cobro else 'Pendiente'
                                    cursor.execute("""
                                        INSERT INTO ordenes_cobranza 
                                        (empresa_db, rif_cliente, n_factura, n_control, fecha_emision, base_imponible, monto_exento, porcentaje_alicuota, monto_iva, monto_bruto, referencia_banco, estado_cobro)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (
                                        str(db_actual), cli_info['rif'], nro_factura, nro_control, fecha_emision,
                                        base_imponible, monto_exento, alicuota_iva, monto_iva, monto_bruto,
                                        ref_banco_cobro if ref_banco_cobro else None, estado_inicial
                                    ))

                                    # 2. Guardar en la tabla maestra 'factura'
                                    cursor.execute("""
                                        INSERT INTO factura 
                                        (empresa_db, rif_cliente, n_factura, n_control, fecha_emision, base_imponible, monto_exento, porcentaje_alicuota, monto_iva, monto_bruto, estado_cobro, referencia_banco)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (
                                        str(db_actual), cli_info['rif'], nro_factura, nro_control, fecha_emision,
                                        base_imponible, monto_exento, alicuota_iva, monto_iva, monto_bruto,
                                        estado_inicial, ref_banco_cobro if ref_banco_cobro else None
                                    ))

                                    # 3. Guardar cada ítem en la tabla 'factura_detalle'
                                    for _, row_item in edited_items_df.iterrows():
                                        cursor.execute("""
                                            INSERT INTO factura_detalle 
                                            (n_factura, codigo_producto, descripcion, cantidad, precio_unitario, total_linea)
                                            VALUES (%s, %s, %s, %s, %s, %s)
                                        """, (
                                            nro_factura,
                                            str(row_item['Código']),
                                            str(row_item['Descripción']),
                                            float(row_item['Cantidad']),
                                            float(row_item['Precio Unitario']),
                                            float(row_item['Total ($)'])
                                        ))

                                    conn_trans.commit()
                                    cursor.close()
                                    conn_trans.close()

                                    st.success("✅ ¡Factura, detalles y orden de cobranza guardados con éxito en la base de datos!")
                                    st.balloons()
                                    st.rerun()
                                else:
                                    st.error("❌ Error de conexión con la base de datos.")
                            except Exception as err_fac:
                                st.error(f"❌ Error al procesar: {err_fac}")
                        else:
                            st.warning("⚠️ Debes rellenar el Número de Factura y Control.")

                    # =========================================================================
                    # 📊 PANEL DE GESTIÓN POR FRENTES (SIN MODIFICAR LOS OTROS 3 FRAMES)
                    # =========================================================================
                    st.divider()
                    st.markdown(f"### 🔍 Gestión por Frentes (Empresa: `{db_actual}`)")
                    
                    sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
                        "🧾 Órdenes de Cobranza", 
                        "📖 Libro de Ventas", 
                        "⚖️ Asientos Contables", 
                        "🏦 Movimientos Bancarios"
                    ])

                    conn_vis = conectar_db(db_actual)
                    if conn_vis:
                        # -------------------------------------------------------------
                        # SUB-TAB 1: Órdenes de Cobranza
                        # -------------------------------------------------------------
                        with sub_tab1:
                            st.markdown("#### Órdenes de Cobranza Registradas")
                            try:
                                df_oc = ejecutar_consulta("SELECT id, n_factura, n_control, fecha_emision, rif_cliente, monto_bruto, estado_cobro, referencia_banco FROM ordenes_cobranza ORDER BY id DESC LIMIT 20", conn_vis)
                                if df_oc is not None and not df_oc.empty:
                                    st.dataframe(df_oc, use_container_width=True)
                                else:
                                    st.info("No hay órdenes de cobranza registradas todavía.")
                            except Exception:
                                st.info("La tabla `ordenes_cobranza` aún no tiene datos o está por crearse.")

                        # -------------------------------------------------------------
                        # SUB-TAB 2: Libro de Ventas
                        # -------------------------------------------------------------
                        with sub_tab2:
                            st.markdown("#### 📖 Libro de Ventas - Facturas Pendientes de Registrar")
                            try:
                                df_oc_pend = ejecutar_consulta("SELECT id, fecha_emision, n_factura, n_control, rif_cliente, monto_bruto, base_imponible, porcentaje_alicuota, monto_iva, monto_exento FROM ordenes_cobranza ORDER BY id DESC LIMIT 10", conn_vis)
                                
                                if df_oc_pend is not None and not df_oc_pend.empty:
                                    df_frame_lv = pd.DataFrame({
                                        "id": df_oc_pend['id'],
                                        "fecha_factura": df_oc_pend['fecha_emision'],
                                        "nombre_razon_social": cli_info['razon_social'],
                                        "rif": df_oc_pend['rif_cliente'],
                                        "n_factura": df_oc_pend['n_factura'],
                                        "n_control": df_oc_pend['n_control'],
                                        "total_ventas_con_iva": df_oc_pend['monto_bruto'],
                                        "ventas_exentas": df_oc_pend['monto_exento'],
                                        "base_imponible": df_oc_pend['base_imponible'],
                                        "porcentaje_alicuota": df_oc_pend['porcentaje_alicuota'],
                                        "debito_fiscal": df_oc_pend['monto_iva'],
                                        "fecha_registro": pd.Timestamp.now()
                                    })
                                    
                                    st.markdown("##### Frame con Estructura Oficial (`libro_ventas`):")
                                    st.dataframe(df_frame_lv, use_container_width=True)
                                    
                                    sel_oc_id_lv = st.selectbox("Seleccione ID de Orden de Cobranza a guardar", df_oc_pend['id'].tolist(), key="sel_lv_id")
                                    selected_row_lv = df_frame_lv[df_frame_lv['id'] == sel_oc_id_lv].iloc[0]

                                    if st.button("💾 Guardar en Libro de Ventas", key="btn_save_lv_action"):
                                        try:
                                            conn_lv = conectar_db(db_actual)
                                            cur_lv = conn_lv.cursor()
                                            cur_lv.execute("""
                                                INSERT INTO libro_ventas 
                                                (fecha_factura, nombre_razon_social, rif, n_factura, n_control, total_ventas_con_iva, ventas_exentas, base_imponible, porcentaje_alicuota, debito_fiscal)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            """, (
                                                selected_row_lv['fecha_factura'], selected_row_lv['nombre_razon_social'], selected_row_lv['rif'],
                                                selected_row_lv['n_factura'], selected_row_lv['n_control'], selected_row_lv['total_ventas_con_iva'],
                                                selected_row_lv['ventas_exentas'], selected_row_lv['base_imponible'], selected_row_lv['porcentaje_alicuota'],
                                                selected_row_lv['debito_fiscal']
                                            ))
                                            conn_lv.commit()
                                            cur_lv.close()
                                            conn_lv.close()
                                            st.success("✅ ¡Factura guardada exitosamente en el Libro de Ventas!")
                                            st.rerun()
                                        except Exception as err_ins_lv:
                                            st.error(f"❌ Error al guardar en libro_ventas: {err_ins_lv}")
                                else:
                                    st.info("No hay órdenes de cobranza disponibles.")
                            except Exception as e_lv_err:
                                st.error(f"Error cargando frame: {e_lv_err}")

                        # -------------------------------------------------------------
                        # SUB-TAB 3: Asientos Contables
                        # -------------------------------------------------------------
                        with sub_tab3:
                            st.markdown("#### ⚖ Asientos Contables - Facturas Pendientes de Registrar")
                            try:
                                df_oc_ac = ejecutar_consulta("SELECT id, fecha_emision, n_factura, rif_cliente, monto_bruto, base_imponible, monto_iva FROM ordenes_cobranza ORDER BY id DESC LIMIT 10", conn_vis)
                                
                                if df_oc_ac is not None and not df_oc_ac.empty:
                                    import time
                                    df_frame_ac = pd.DataFrame({
                                        "id": df_oc_ac['id'],
                                        "n_comprobante": [f"FACT-{f}-{int(time.time())}" for f in df_oc_ac['n_factura']],
                                        "descripcion": [f"Venta según Factura {f}" for f in df_oc_ac['n_factura']],
                                        "fecha": df_oc_ac['fecha_emision'],
                                        "plan_cuentas": cli_info['cuenta'],
                                        "cuenta_contable": "CxC Cliente",
                                        "referencia": df_oc_ac['n_factura'],
                                        "debe": df_oc_ac['monto_bruto'],
                                        "haber": 0.00,
                                        "bloqueado": 1
                                    })

                                    st.markdown("##### Frame con Estructura Oficial (`asientos_contables`):")
                                    st.dataframe(df_frame_ac, use_container_width=True)
                                    
                                    sel_oc_id_ac = st.selectbox("Seleccione ID de Orden de Cobranza a guardar", df_oc_ac['id'].tolist(), key="sel_ac_id")
                                    selected_row_ac = df_oc_ac[df_oc_ac['id'] == sel_oc_id_ac].iloc[0]

                                    if st.button("💾 Guardar en Asientos Contables", key="btn_save_ac_action"):
                                        try:
                                            conn_ac = conectar_db(db_actual)
                                            cur_ac = conn_ac.cursor()
                                            n_comp = f"FACT-{selected_row_ac['n_factura']}-{int(time.time())}"
                                            desc_ast = f"Venta según Factura {selected_row_ac['n_factura']}"

                                            # 1. Débito (CxC)
                                            cur_ac.execute("""
                                                INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                            """, (n_comp, desc_ast, selected_row_ac['fecha_emision'], cli_info['cuenta'], "CxC Cliente", selected_row_ac['n_factura'], selected_row_ac['monto_bruto'], 0.00, 1))

                                            # 2. Haber (Ingresos)
                                            if selected_row_ac['base_imponible'] > 0:
                                                cur_ac.execute("""
                                                    INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                                """, (n_comp, desc_ast, selected_row_ac['fecha_emision'], "401-01", "Ingresos por Ventas / Servicios", selected_row_ac['n_factura'], 0.00, selected_row_ac['base_imponible'], 1))

                                            # 3. Haber (IVA)
                                            if selected_row_ac['monto_iva'] > 0:
                                                cur_ac.execute("""
                                                    INSERT INTO asientos_contables (n_comprobante, descripcion, fecha, plan_cuentas, cuenta_contable, referencia, debe, haber, bloqueado)
                                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                                """, (n_comp, desc_ast, selected_row_ac['fecha_emision'], "202-01", "Débito Fiscal IVA por Pagar", selected_row_ac['n_factura'], 0.00, selected_row_ac['monto_iva'], 1))

                                            conn_ac.commit()
                                            cur_ac.close()
                                            conn_ac.close()
                                            st.success("✅ ¡Asiento contable guardado con éxito con su estructura exacta!")
                                            st.rerun()
                                        except Exception as err_ins_ac:
                                            st.error(f"❌ Error al guardar en asientos_contables: {err_ins_ac}")
                                else:
                                    st.info("No hay órdenes de cobranza disponibles.")
                            except Exception as e_ac_err:
                                st.error(f"Error cargando frame: {e_ac_err}")

                        # -------------------------------------------------------------
                        # SUB-TAB 4: Movimientos Bancarios
                        # -------------------------------------------------------------
                        with sub_tab4:
                            st.markdown("#### 🏦 Movimientos Bancarios - Pagos Pendientes de Registrar")
                            try:
                                df_oc_bm = ejecutar_consulta("SELECT id, fecha_emision, n_factura, monto_bruto, referencia_banco FROM ordenes_cobranza WHERE referencia_banco IS NOT NULL AND referencia_banco != '' ORDER BY id DESC LIMIT 10", conn_vis)
                                
                                if df_oc_bm is not None and not df_oc_bm.empty:
                                    df_frame_bm = pd.DataFrame({
                                        "id": df_oc_bm['id'],
                                        "banco_nombre": banco_receptor if banco_receptor else "Banco Principal",
                                        "cuenta_numero": "Principal",
                                        "fecha_movimiento": df_oc_bm['fecha_emision'],
                                        "referencia": df_oc_bm['referencia_banco'],
                                        "descripcion": [f"Cobro Factura {f}" for f in df_oc_bm['n_factura']],
                                        "monto": df_oc_bm['monto_bruto'],
                                        "estado_conciliacion": "Conciliado",
                                        "asiento_id": None,
                                        "fecha_importacion": pd.Timestamp.now()
                                    })

                                    st.markdown("##### Frame con Estructura Oficial (`banco_movimientos`):")
                                    st.dataframe(df_frame_bm, use_container_width=True)
                                    
                                    sel_oc_id_bm = st.selectbox("Seleccione ID de Orden de Cobranza a guardar", df_oc_bm['id'].tolist(), key="sel_bm_id")
                                    selected_row_bm = df_frame_bm[df_frame_bm['id'] == sel_oc_id_bm].iloc[0]

                                    if st.button("💾 Guardar en Movimientos Bancarios", key="btn_save_bm_action"):
                                        try:
                                            conn_bm = conectar_db(db_actual)
                                            cur_bm = conn_bm.cursor()
                                            cur_bm.execute("""
                                                INSERT INTO banco_movimientos (banco_nombre, cuenta_numero, fecha_movimiento, referencia, descripcion, monto, estado_conciliacion, asiento_id, fecha_importacion)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                                            """, (
                                                banco_receptor if banco_receptor else "Banco Principal", "Principal",
                                                selected_row_bm['fecha_movimiento'], selected_row_bm['referencia'],
                                                f"Cobro Factura {selected_row_bm['referencia']}", selected_row_bm['monto'],
                                                "Conciliado", None
                                            ))
                                            conn_bm.commit()
                                            cur_bm.close()
                                            conn_bm.close()
                                            st.success("✅ ¡Movimiento bancario guardado con éxito con su estructura exacta!")
                                            st.rerun()
                                        except Exception as err_ins_bm:
                                            st.error(f"❌ Error al guardar en banco_movimientos: {err_ins_bm}")
                                else:
                                    st.info("No hay pagos con referencia bancaria registrados pendientes.")
                            except Exception as e_bm_err:
                                st.error(f"Error cargando frame: {e_bm_err}")

                        # Cerrar conexión de visualización general
                        conn_vis.close()
                else:
                    st.warning("⚠️ No se encontraron clientes comerciales registrados. Por favor, crea al menos un cliente primero.")
            except Exception as e_tab6:
                st.error(f"❌ Error general en la Pestaña 6: {e_tab6}")
