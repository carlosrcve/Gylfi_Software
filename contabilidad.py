with tab4:
    # --- SECCIÓN: ASIENTO CONTABLE COMPLETO POR COMPROBANTE ---
    st.divider()
    st.subheader("👥 Detalle de Comprobantes - Cuentas por Pagar Accionistas")

    db_actual = st.session_state.get('DB_ACTUAL')

    if db_actual and db_actual != "{db}" and db_actual != "None":
        df_comps = pd.DataFrame()
        
        # Recuperamos o validamos las variables globales de fecha (f_i y f_f)
        f_i = st.session_state.get('fecha_inicio', st.session_state.get('f_i'))
        f_f = st.session_state.get('fecha_fin', st.session_state.get('f_f'))

        if not f_i or not f_f:
            st.warning("⚠️ Por favor, define el rango de fechas en los filtros principales para consultar los comprobantes.")
        else:
            conn_tmp = conectar_db(db_actual)
            
            if conn_tmp:
                try:
                    # Consulta filtrada por cuenta de accionistas y rango de fechas compatible con TiDB Cloud
                    query_comps = f"""
                        SELECT DISTINCT n_comprobante, fecha 
                        FROM `{db_actual}`.asientos_contables 
                        WHERE plan_cuentas LIKE '2.2.1.01.001%'
                        AND STR_TO_DATE(fecha, '%Y-%m-%d') BETWEEN STR_TO_DATE(%s, '%Y-%m-%d') AND STR_TO_DATE(%s, '%Y-%m-%d')
                        ORDER BY fecha DESC, n_comprobante DESC
                    """
                    df_comps = pd.read_sql(query_comps, conn_tmp, params=(str(f_i), str(f_f)))
                except Exception as e:
                    st.error(f"Error al consultar comprobantes en TiDB: {e}")
                finally:
                    try:
                        conn_tmp.close()
                    except Exception:
                        pass

            if not df_comps.empty:
                # Función local para formatear los números al estilo latino (ej: 257.896,45)
                def formato_latino(val):
                    try:
                        s = f"{float(val):,.2f}"
                        return s.replace(",", "X").replace(".", ",").replace("X", ".")
                    except:
                        return val

                # --- MÉTRICAS GLOBALES DEL PERIODO ---
                total_debe_periodo = 0.0
                total_haber_periodo = 0.0
                
                conn_totales = conectar_db(db_actual)
                if conn_totales and 'n_comprobante' in df_comps.columns:
                    try:
                        lista_n_comps = tuple(df_comps['n_comprobante'].astype(str).unique())
                        if lista_n_comps:
                            placeholders = ','.join(['%s'] * len(lista_n_comps))
                            query_totales = f"""
                                SELECT SUM(CAST(debe AS DECIMAL(18,2))) as total_debe, SUM(CAST(haber AS DECIMAL(18,2))) as total_haber 
                                FROM `{db_actual}`.asientos_contables 
                                WHERE n_comprobante IN ({placeholders})
                            """
                            df_t = pd.read_sql(query_totales, conn_totales, params=lista_n_comps)
                            if not df_t.empty:
                                total_debe_periodo = float(df_t['total_debe'].iloc[0] or 0.0)
                                total_haber_periodo = float(df_t['total_haber'].iloc[0] or 0.0)
                    except Exception as e:
                        st.error(f"Error al calcular totales globales: {e}")
                    finally:
                        try:
                            conn_totales.close()
                        except Exception:
                            pass

                # Mostramos las métricas generales del rango de fechas arriba
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("Comprobantes en el Periodo", len(df_comps))
                col_m2.metric("Total Debe Global", f"Bs. {formato_latino(total_debe_periodo)}")
                col_m3.metric("Total Haber Global", f"Bs. {formato_latino(total_haber_periodo)}")
                
                st.divider()

                # Creamos opciones claras combinando número de comprobante y fecha
                df_comps['opcion'] = df_comps['n_comprobante'].astype(str) + " (Fecha: " + df_comps['fecha'].astype(str) + ")"
                lista_opciones = df_comps['opcion'].tolist()
                
                seleccion_opcion = st.selectbox("📂 Selecciona el comprobante a visualizar:", lista_opciones, key="select_accionistas")
                
                if seleccion_opcion:
                    comprobante_activo = seleccion_opcion.split(" ")[0]
                    df_asiento = obtener_asiento_por_comprobante(db_actual, comprobante_activo)
                    
                    if df_asiento is not None and not df_asiento.empty:
                        st.markdown(f"**Asiento Contable Completo del Comprobante N°: `{comprobante_activo}`**")
                        
                        df_mostrar = df_asiento.copy()
                        df_mostrar['debe'] = df_mostrar['debe'].apply(formato_latino)
                        df_mostrar['haber'] = df_mostrar['haber'].apply(formato_latino)
                        
                        st.dataframe(
                            df_mostrar,
                            use_container_width=True,
                            height=350,
                            column_config={
                                "id": st.column_config.NumberColumn("id", format="%d"),
                                "n_comprobante": st.column_config.TextColumn("N° Comprobante"),
                                "descripcion": st.column_config.TextColumn("Descripción"),
                                "fecha": st.column_config.DateColumn("Fecha"),
                                "plan_cuentas": st.column_config.TextColumn("Plan de Cuentas"),
                                "cuenta_contable": st.column_config.TextColumn("Cuenta Contable"),
                                "referencia": st.column_config.TextColumn("Referencia"),
                                "debe": st.column_config.TextColumn("Debe"),
                                "haber": st.column_config.TextColumn("Haber")
                            }
                        )
                        
                        total_debe = df_asiento['debe'].sum()
                        total_haber = df_asiento['haber'].sum()
                        
                        col1, col2 = st.columns(2)
                        col1.metric("Total Debe (Comprobante)", f"Bs. {formato_latino(total_debe)}")
                        col2.metric("Total Haber (Comprobante)", f"Bs. {formato_latino(total_haber)}")
                    else:
                        st.info("No se encontraron detalles para este comprobante.")
            else:
                st.info("No hay comprobantes asociados al filtro seleccionado para esta cuenta en el periodo indicado.")
    else:
        st.warning("⚠️ Selecciona una empresa.")
