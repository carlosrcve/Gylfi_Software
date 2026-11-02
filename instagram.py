# instagram.py
import streamlit as st
import pandas as pd
import mysql.connector

def aplicar_estilo_publico():
    """Oculta la barra lateral y la barra flotante para dejar la pantalla 100% limpia."""
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none !important; width: 0 !important; }
            [data-testid="collapsedControl"] { display: none !important; }
            section.main { width: 100% !important; margin-left: 0 !important; }
        </style>
    """, unsafe_allow_html=True)

def modulo_compras():
    aplicar_estilo_publico()
    
    st.title("📖 Libro de Compras")
    st.markdown("### King Driver, C.A.")
    st.markdown("---")
    
    # Conexión directa a la base de datos de King Driver para los usuarios de Instagram
    try:
        # Coloca aquí los datos reales de tu conexión de base de datos
        conn = mysql.connector.connect(
            host="tu_host",
            user="tu_usuario",
            password="tu_password",
            database="kingdriver_ca"
        )
        
        # Ejemplo de consulta para tu libro de compras
        query = "SELECT * FROM libro_compras" # Ajusta el nombre de tu tabla real
        df = pd.read_sql(query, conn)
        conn.close()
        
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No hay registros disponibles en el libro de compras actualmente.")
            
    except Exception as e:
        st.error(f"Error al cargar los datos públicos: {e}")

def modulo_ventas():
    aplicar_estilo_publico()
    st.title("📊 Libro de Ventas - King Driver, C.A.")
    # Tu lógica para ventas aquí...

def modulo_retencion_islr():
    aplicar_estilo_publico()
    st.title("🧾 Comprobante de Retención ISLR")
    # Tu lógica para ISLR aquí...

def modulo_retencion_iva():
    aplicar_estilo_publico()
    st.title("🧾 Comprobante de Retención IVA")
    # Tu lógica para IVA aquí...
