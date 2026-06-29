from contextlib import contextmanager

@contextmanager
def obtener_conexion_activa():
    db_actual = st.session_state.get('DB_ACTUAL')
    
    if not db_actual:
        st.error("⚠️ Debes seleccionar una empresa en la barra lateral.")
        st.stop()
        
    conn = conectar_db(db_actual)
    
    if not conn or not conn.is_connected():
        st.error(f"❌ No se pudo conectar a: {db_actual}")
        st.stop()
        
    try:
        yield conn  # Aquí es donde ocurre la magia
    finally:
        # Esto se ejecuta SIEMPRE, incluso si hay error en la consulta
        conn.close() 
        # print("Conex



def consultar_saldos_iniciales_db():
    conn = obtener_conexion_activa()
    
    try:
        query = "SELECT * FROM saldos_iniciales ORDER BY id ASC"
        df = pd.read_sql(query, conn)
        return df
        
    except Exception as e:
        st.error(f"❌ Error al consultar saldos: {e}")
        return pd.DataFrame()
        
    finally:
        # Cierra la conexión siempre, ocurra o no el error
        if conn and conn.is_connected():
            conn.close()