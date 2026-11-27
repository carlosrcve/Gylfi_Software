st.divider()
        st.markdown("#### 📋 Historial de Beneficios Sociales")
        try:
            emp_key_bs = str(db_actual).strip()
            conn_hist_bs = conectar_db(db_actual)
            if conn_hist_bs:
                with conn_hist_bs.cursor() as cur_hbs:
                    cur_hbs.execute("""
                        SELECT id, nombre_empleado, fecha_ingreso, fecha_egreso,
                               salario_diario, salario_mensual, utilidades,
                               bono_vacacional, prestaciones_sociales, observaciones, creado_en
                        FROM beneficios_sociales
                        WHERE LOWER(TRIM(empresa_db)) = LOWER(%s)
                        ORDER BY id DESC
                        LIMIT 200
                    """, (emp_key_bs,))
                    cols_hbs = [desc[0] for desc in cur_hbs.description]
                    filas_hbs = [dict(zip(cols_hbs, fila)) for fila in cur_hbs.fetchall()]
                conn_hist_bs.close()

                if filas_hbs:
                    df_hbs = pd.DataFrame(filas_hbs)

                    def _fmt_fecha(val, vacio="—"):
                        if val is None or pd.isna(val) or str(val).strip() in ("", "None", "NaT"):
                            return vacio
                        if hasattr(val, "strftime"):
                            return val.strftime("%Y-%m-%d")
                        return str(val)[:10]

                    if "fecha_ingreso" in df_hbs.columns:
                        df_hbs["fecha_ingreso"] = df_hbs["fecha_ingreso"].apply(lambda v: _fmt_fecha(v, "—"))
                    if "fecha_egreso" in df_hbs.columns:
                        df_hbs["fecha_egreso"] = df_hbs["fecha_egreso"].apply(lambda v: _fmt_fecha(v, "Activo"))
                    if "creado_en" in df_hbs.columns:
                        df_hbs["creado_en"] = df_hbs["creado_en"].apply(lambda v: _fmt_fecha(v, "—"))

                    for col_num in ["salario_diario", "salario_mensual", "utilidades", "bono_vacacional", "prestaciones_sociales"]:
                        if col_num in df_hbs.columns:
                            df_hbs[col_num] = df_hbs[col_num].apply(lambda x: f"{float(x or 0.0):,.2f}")

                    st.dataframe(df_hbs, use_container_width=True, hide_index=True)
                else:
                    st.info("Aún no hay cálculos guardados en `beneficios_sociales` para esta empresa.")
        except Exception as err_hbs:
            st.error(f"❌ Error consultando `beneficios_sociales`: {err_hbs}")
