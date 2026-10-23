# ==============================================================================
# 2. PANEL DE ADMINISTRACIÓN DE EMPRESAS (Exclusivo Super Admin)
# ==============================================================================
def panel_administracion_empresas(conn):
    st.header("⚙️ Gestión Global de Empresas y Despachos (Super Admin)")
    st.info("💡 Desde este panel maestro, tú (como dueño de Gylfi Software) registras los despachos contables y sus bases de datos asignadas.")

    with st.expander("➕ Registrar Nueva Empresa / Despacho Cliente", expanded=True):
        with st.form("registro_empresa_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                nombre_empresa = st.text_input("Razón Social de la Empresa", placeholder="Ej: Despacho Contable Oviedo, C.A.")
                rif = st.text_input("R.I.F.", placeholder="Ej: J-57894514-9")
                direccion_fiscal = st.text_area("Dirección Fiscal", placeholder="Ej: Av. Principal...")
                tipo_contribuyente = st.selectbox("Tipo de Contribuyente", options=["Contribuyente Ordinario", "Contribuyente Especial"])

            with col2:
                db_nombre = st.text_input("Nombre de la Base de Datos (MySQL)", placeholder="Ej: db_despacho_oviedo")
                estado_empresa = st.selectbox("Estado Inicial", options=["Activo", "Suspendido"])
                fecha_vencimiento = st.date_input("Fecha de Vencimiento de Licencia")
                ultimo_digito = st.number_input("Último Dígito del RIF", min_value=0, max_value=9, step=1, value=0)

            btn_guardar_empresa = st.form_submit_button("💾 Guardar Empresa en Base de Datos", type="primary")

            if btn_guardar_empresa:
                if not nombre_empresa or not rif or not db_nombre:
                    st.error("❌ Los campos Razón Social, RIF y Nombre de Base de Datos son obligatorios.")
                else:
                    try:
                        cursor = conn.cursor()
                        query_insert_empresa = """
                            INSERT INTO clientes 
                            (nombre_empresa, rif, db_nombre, estado, fecha_vencimiento, tipo_contribuyente, ultimo_digito, direccion_fiscal)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        valores = (
                            nombre_empresa.strip(),
                            rif.strip(),
                            db_nombre.strip(),
                            estado_empresa,
                            fecha_vencimiento.strftime("%Y-%m-%d"),
                            tipo_contribuyente,
                            int(ultimo_digito),
                            direccion_fiscal.strip()
                        )
                        cursor.execute(query_insert_empresa, valores)
                        conn.commit()
                        cursor.close()
                        st.success(f"✅ ¡Empresa **{nombre_empresa}** registrada con éxito!")
                    except Exception as e:
                        st.error(f"❌ Error al registrar: {e}")

    st.markdown("---")
    st.subheader("📋 Listado General de Clientes y Despachos")

    try:
        df_clientes = ejecutar_consulta("SELECT * FROM clientes ORDER BY id DESC", conn)
    except Exception as e:
        st.error(f"Error al consultar la tabla clientes: {e}")
        df_clientes = pd.DataFrame()

    if not df_clientes.empty:
        key_editor_clientes = "editor_tabla_clientes_admin"
        df_editado_clientes = st.data_editor(
            df_clientes,
            key=key_editor_clientes,
            num_rows="fixed",
            width="stretch",
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "nombre_empresa": st.column_config.TextColumn("Razón Social"),
                "rif": st.column_config.TextColumn("RIF"),
                "db_nombre": st.column_config.TextColumn("Base de Datos (MySQL)"),
                "estado": st.column_config.SelectboxColumn("Estado", options=["Activo", "Suspendido"], required=True),
                "fecha_vencimiento": st.column_config.DateColumn("Vencimiento", format="DD/MM/YYYY"),
                "tipo_contribuyente": st.column_config.SelectboxColumn("Tipo Contribuyente", options=["Contribuyente Ordinario", "Contribuyente Especial"], required=True),
            }
        )

        if st.button("💾 Guardar Cambios en Empresas", type="primary", key="btn_guardar_cambios_clientes"):
            cambios_cli = st.session_state.get(key_editor_clientes, {})
            try:
                cursor_upd = conn.cursor()
                cursor_upd.execute("START TRANSACTION")
                for idx_str, dict_mod in cambios_cli.get("edited_rows", {}).items():
                    id_row = int(df_clientes.iloc[int(idx_str)]["id"])
                    if dict_mod:
                        cols_sql = [f"{k} = %s" for k in dict_mod.keys()]
                        vals_sql = list(dict_mod.values())
                        sql_u = f"UPDATE clientes SET {', '.join(cols_sql)} WHERE id = %s"
                        cursor_upd.execute(sql_u, vals_sql + [id_row])
                for idx_del in cambios_cli.get("deleted_rows", []):
                    id_del = int(df_clientes.iloc[idx_del]["id"])
                    cursor_upd.execute("DELETE FROM clientes WHERE id = %s", (id_del,))
                conn.commit()
                cursor_upd.close()
                st.success("✅ ¡Cambios guardados correctamente!")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"❌ Error al guardar: {e}")
    else:
        st.warning("⚠️ No hay empresas registradas actualmente.")
