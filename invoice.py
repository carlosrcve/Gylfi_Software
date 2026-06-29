# Facturar
#cd Desktop
#streamlit run invoice.py
#streamlit run contabilidad.py
7928
#cd Desktop
#streamlit run app.py

#python lanzador.py

#invioce.py
import streamlit as st
import pandas as pd
from fpdf import FPDF
import base64

# --- FUNCIÓN PARA CREAR EL PDF (DISEÑO SEGÚN TU FORMATO FÍSICO) ---
def crear_pdf(nombre, cedula, ubicacion, monto, descripcion):
    pdf = FPDF()
    pdf.add_page()
    
    # Encabezado: King Driver, C.A.
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(100, 10, 'KING DRIVER, C.A.', 0, 0)
    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 10, 'RIF: J-50775718-8', 0, 1, 'R')
    
    pdf.set_font('Arial', '', 8)
    pdf.multi_cell(0, 4, 'Av. Jose Antonio Paez, Edif. 2000 Residencias Cecilia\nPiso PH, Apto 43, Urb. El Paraiso, Caracas.\nTelf: +58 424-189-96-22\nE-mail: jeanmarcoarroyov@gmail.com')
    pdf.ln(10)
    
    # Datos del Cliente / Chofer
    pdf.set_font('Arial', 'B', 11)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, f' NOMBRE O RAZÓN SOCIAL: {nombre.upper()}', 1, 1, 'L', True)
    
    pdf.set_font('Arial', '', 10)
    pdf.cell(100, 8, f' C.I. / RIF: {cedula}', 1, 0)
    pdf.cell(0, 8, f' FECHA: {pd.Timestamp.now().strftime("%d/%m/%Y")}', 1, 1)
    pdf.cell(0, 8, f' DIRECCIÓN: {ubicacion}', 1, 1)
    pdf.ln(5)
    
    # Tabla de Concepto
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(140, 8, 'DESCRIPCIÓN', 1, 0, 'C', True)
    pdf.cell(50, 8, 'MONTO Bs.', 1, 1, 'C', True)
    
    pdf.set_font('Arial', '', 10)
    pdf.cell(140, 40, f' {descripcion}', 1, 0, 'L')
    pdf.cell(50, 40, f' {monto:,.2f}', 1, 1, 'R')
    
    # Totales finales
    pdf.ln(5)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(140, 8, 'TOTAL A PAGAR Bs. ', 0, 0, 'R')
    pdf.cell(50, 8, f' {monto:,.2f}', 1, 1, 'R')
    
    # Nota al pie
    pdf.set_y(-30)
    pdf.set_font('Arial', 'I', 8)
    pdf.cell(0, 10, 'Esta factura va sin enmiendas ni tachaduras. Original Cliente.', 0, 0, 'C')
    
    return pdf.output(dest='S').encode('latin-1')

# --- FUNCIÓN PARA MOSTRAR PREVIA ---
def mostrar_pdf_previa(bin_file):
    base64_pdf = base64.b64encode(bin_file).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# --- CONFIGURACIÓN DE INTERFAZ ---
st.set_page_config(layout="wide", page_title="King Driver Facturación")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #e6e9ef; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; }
    </style>
    """, unsafe_allow_html=True)

st.title("📑 Sistema de Facturación King Driver, C.A.")

# --- SIDEBAR: CARGAR EXCEL ---
st.sidebar.header("Configuración")
archivo_excel = st.sidebar.file_uploader("Subir Excel de Choferes", type=["xlsx"])

# --- LÓGICA DE CARGA DE DATOS ---
data_choferes = None
if archivo_excel:
    try:
        df_temp = pd.read_excel(archivo_excel, skiprows=1)
        df_temp.columns = [str(c).strip() for c in df_temp.columns]
        df_temp = df_temp.dropna(subset=['Nombre'])
        df_temp = df_temp.rename(columns={
            'Monto a facturar': 'Monto a Facturar',
            'MONTO A FACTURAR': 'Monto a Facturar',
            'Monto': 'Monto a Facturar',
            'Ubicacion': 'Ubicación',
            'Cedula': 'Cedula',
            'Cédula': 'Cedula'
        })
        data_choferes = df_temp
    except Exception as e:
        st.sidebar.error(f"Error al leer el archivo: {e}")

# --- CUERPO PRINCIPAL ---
if data_choferes is not None:
    # KPIs Rápidos
    col1, col2, col3 = st.columns(3)
    total_bs = data_choferes['Monto a Facturar'].sum() if 'Monto a Facturar' in data_choferes.columns else 0
    col1.metric("Total a Facturar (Mes)", f"Bs. {total_bs:,.2f}")
    col2.metric("Choferes en Lista", len(data_choferes))
    col3.metric("Estatus", "Datos Cargados ✅")

    tab1, tab2 = st.tabs(["📋 Selección de Chofer", "🖨️ Generar Factura"])

    with tab1:
        st.subheader("Seleccione el chofer a facturar")
        opciones = data_choferes['Nombre'].astype(str) + " " + data_choferes['Apellido'].astype(str)
        seleccion = st.selectbox("Buscar Chofer:", opciones)
        fila = data_choferes[opciones == seleccion].iloc[0]
        st.dataframe(data_choferes, use_container_width=True)

    with tab2:
        st.subheader("Datos de la Factura Fiscal")
        c1, c2 = st.columns(2)
        nombre_f = c1.text_input("Nombre o Razón Social", value=f"{fila['Nombre']} {fila['Apellido']}")
        cedula_f = c2.text_input("C.I / RIF", value=str(fila['Cedula']))
        
        c3, c4 = st.columns(2)
        ubicacion_f = c3.text_input("Dirección (Ubicación)", value=fila['Ubicación'])
        monto_valor = float(fila['Monto a Facturar']) if 'Monto a Facturar' in fila else 0.0
        monto_f = c4.number_input("Monto a Facturar (Bs.)", value=monto_valor, format="%.2f")
        
        descripcion_f = st.text_area("Descripción", 
            value=f"Servicio de transporte correspondiente al mes de Enero 2026. Chofer: {fila['Nombre']} {fila['Apellido']}")

        # --- BOTÓN DE GENERACIÓN Y VISTA PREVIA ---
        if st.button("👁️ Generar Vista Previa"):
            with st.spinner("Preparando documento..."):
                pdf_bytes = crear_pdf(nombre_f, cedula_f, ubicacion_f, monto_f, descripcion_f)
                st.session_state['pdf_actual'] = pdf_bytes
                # Guardamos el nombre limpio para el archivo
                st.session_state['nombre_archivo'] = f"Factura_{nombre_f.replace(' ', '_')}.pdf"

        # --- SECCIÓN DE DESCARGA Y PREVIA ---
        if 'pdf_actual' in st.session_state:
            st.divider()
            
            # Botón de descarga con nombre dinámico
            st.download_button(
                label="⬇️ Descargar Factura PDF",
                data=st.session_state['pdf_actual'],
                file_name=st.session_state['nombre_archivo'],
                mime="application/pdf"
            )
            
            st.subheader("Vista Previa del Documento")
            mostrar_pdf_previa(st.session_state['pdf_actual'])

else:
    st.info("👋 Bienvenido. Por favor, sube el archivo Excel en la barra lateral para comenzar.")