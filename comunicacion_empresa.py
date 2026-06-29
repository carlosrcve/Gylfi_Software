def obtener_datos_agente_db(valor_busqueda):
    conn_central = conectar_db("control_central")
    if not conn_central: return None

    try:
        cursor = conn_central.cursor(dictionary=True)
        # Si es un string, busca por db_nombre. Si es int, busca por id.
        if isinstance(valor_busqueda, str):
            query = "SELECT id, nombre_empresa, rif, domicilio_fiscal FROM clientes WHERE db_nombre = %s"
        else:
            query = "SELECT id, nombre_empresa, rif, domicilio_fiscal FROM clientes WHERE id = %s"
        
        cursor.execute(query, (valor_busqueda,))
        datos = cursor.fetchone()
        cursor.close()
        return datos
    except Exception as e:
        # Aquí es donde ocurre el error 1292. Si ves esto en pantalla, 
        # sabrás exactamente qué valor está fallando.
        st.error(f"Error en consulta DB: {e} | Valor buscado: {valor_busqueda}")
        return None
    finally:
        if conn_central and conn_central.is_connected():
            conn_central.close()


TE RECUERDO QUE ESTO VA EN CADA TABLA O MENU! 
# 1. Obtenemos los datos (Esto puede ir fuera del formulario)
db_actual = st.session_state.get('DB_ACTUAL')
empresa_data = obtener_datos_agente_db(db_actual)

if not empresa_data:
    st.error("⚠️ No se pudieron cargar los datos de la empresa.")
else:
    # 2. ABRIMOS EL FORMULARIO
    with st.form("form_generacion_retencion"):
        
        # Selectbox DENTRO del form
        empresa_seleccionada = st.selectbox(
            "Empresa", 
            options=[empresa_data], 
            format_func=lambda x: x['nombre_empresa'],
            key="selector_empresa_unico"
        )
        
        # Guardamos en sesión
        st.session_state['id_empresa_seleccionada'] = empresa_seleccionada
        
        # Otros campos (fechas, etc.) irían aquí...
        
        # 3. EL BOTÓN DENTRO DEL FORM
        enviado = st.form_submit_button("💾 Guardar y Generar Documentos")

    # 4. PROCESAMIENTO FUERA DEL FORM (Para que no se borre al hacer clic)
    if enviado:
        if 'id_empresa_seleccionada' in st.session_state:
            st.success(f"Procesando para: {st.session_state['id_empresa_seleccionada']['nombre_empresa']}")
            # ... AQUÍ VA TU LÓGICA DE GENERACIÓN ...
        else:
            st.warning("Debe seleccionar una empresa válida.")





###315/06/2026
# 1. Recuperamos lo necesario
db_actual = st.session_state.get('DB_ACTUAL')
cliente_id = st.session_state.get('cliente_id')
rol = st.session_state.get('rol')

# 2. VALIDACIÓN DE SEGURIDAD (Esto evita que el 'None' rompa la consulta)
# Si no hay db_actual, redirigimos o paramos.
if not db_actual:
    st.error("No se ha seleccionado una base de datos de empresa.")
    st.stop()

# Obtenemos los datos con la función que ya conoces
empresa_data = obtener_datos_agente_db(db_actual)

# 3. FILTRO DE ACCESO (Aquí bloqueamos a quienes intenten saltarse permisos)
if empresa_data and rol != 'admin':
    if empresa_data['id'] != cliente_id:
        st.error("⚠️ Acceso denegado: No tienes permisos para esta empresa.")
        st.stop()

# 4. AHORA SÍ: Procesamos el formulario
if not empresa_data:
    st.error("⚠️ No se pudieron cargar los datos de la empresa.")
else:
    with st.form("form_generacion_retencion"):
        # ... (Tu selectbox y lógica anterior)