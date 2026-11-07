# --- SECCIÓN: CERTIFICADO DE SOLVENCIA FINANCIERA AUTOMATIZADO ---
    st.markdown("---")
    
    # Encabezado con diseño elegante
    st.markdown("""
        <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 20px; border-radius: 12px; color: white; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
            <h3 style="margin: 0; font-size: 1.4rem; color: #ffffff;">🏆 Certificación de Solvencia y Diagnóstico Financiero</h3>
            <p style="margin: 5px 0 0 0; font-size: 0.95rem; opacity: 0.9;">Evaluación automática basada en los saldos reales de los asientos contables del período fiscal.</p>
        </div>
    """, unsafe_allow_html=True)

    # 1. Diccionario de meses para traducir el texto de la barra lateral a número
    dic_meses = {
        "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, 
        "Mayo": 5, "Junio": 6, "Julio": 7, "Agosto": 8, 
        "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
    }

    # 2. Sincronizamos las variables con las claves exactas de tus selectores de la barra lateral
    año_int = int(st.session_state.get('año_seleccionado', 2026))
    mes_str = st.session_state.get('mes_seleccionado', 'Mayo')
    mes_int = dic_meses.get(mes_str, 5)  # Por defecto mes 5 (Mayo) si ocurre algún imprevisto

    # 3. Recuperamos la base de datos activa de forma segura
    db = st.session_state.get('DB_ACTUAL')

    if not db or db == "{db}" or db == "None" or str(db).strip() == "":
        st.markdown("""
            <div style="padding: 15px; background-color: #fff3cd; border-left: 5px solid #ffc107; border-radius: 4px; color: #856404;">
                <strong>⚠️ Atención:</strong> Por favor, selecciona una empresa o base de datos activa en la barra lateral para ver su diagnóstico de solvencia.
            </div>
        """, unsafe_allow_html=True)
    else:
        # 4. Ejecutamos la función de evaluación con el año y el mes exactos del selector
        resultado_solvencia = evaluar_salud_financiera(db, año_int, mes_int)

        # 5. Mostramos tarjetas visuales con HTML/CSS personalizado para los indicadores clave
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        
        def tarjeta_metrica(titulo, valor):
            return f"""
                <div style="background-color: #f8f9fa; border: 1px solid #e9ecef; border-radius: 8px; padding: 15px; text-align: center; box-shadow: 0 2px 5px rgba(0,0,0,0.02);">
                    <span style="font-size: 0.85rem; color: #6c757d; font-weight: 600; text-transform: uppercase;">{titulo}</span>
                    <div style="font-size: 1.1rem; font-weight: bold; color: #212529; margin-top: 5px;">Bs. {valor:,.2f}</div>
                </div>
            """
        
        with col_s1:
            st.markdown(tarjeta_metrica("Activo Total", resultado_solvencia['activo_total']), unsafe_allow_html=True)
        with col_s2:
            st.markdown(tarjeta_metrica("Pasivo Total", resultado_solvencia['pasivo_total']), unsafe_allow_html=True)
        with col_s3:
            st.markdown(tarjeta_metrica("Patrimonio", resultado_solvencia['patrimonio']), unsafe_allow_html=True)
        with col_s4:
            st.markdown(tarjeta_metrica("Utilidad Neta", resultado_solvencia['utilidad_neta']), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # 6. Panel de Estado y Diagnóstico con Estética CSS Avanzada
        estado_actual = resultado_solvencia['estado']
        puntaje_actual = resultado_solvencia['puntaje']
        motivos_actual = resultado_solvencia['motivos']

        # Definir colores según el estado
        if "SOLVENTE" in estado_actual:
            bg_color = "#d4edda"
            border_color = "#28a745"
            text_color = "#155724"
        elif "OBSERVACIÓN" in estado_actual:
            bg_color = "#fff3cd"
            border_color = "#ffc107"
            text_color = "#856404"
        else:
            bg_color = "#f8d7da"
            border_color = "#dc3545"
            text_color = "#721c24"

        st.markdown(f"""
            <div style="background-color: {bg_color}; border-left: 6px solid {border_color}; border-radius: 6px; padding: 16px; color: {text_color}; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size: 1.1rem; font-weight: bold; margin-bottom: 5px;">
                    Estado del Diagnóstico ({mes_str} {año_int}): {estado_actual} &nbsp;|&nbsp; <span style="font-size: 0.95rem;">Puntaje: {puntaje_actual}/100</span>
                </div>
                <div style="font-size: 0.9rem; opacity: 0.9;"><strong>Factores analizados:</strong> {motivos_actual}</div>
            </div>
        """, unsafe_allow_html=True)

        # 7. Botón de Acción y Nota Informativa
        col_btn1, col_btn2 = st.columns([2, 1])
        with col_btn1:
            if "SOLVENTE" in estado_actual:
                st.markdown(f"""
                    <div style="padding: 10px 0; color: #495057; font-size: 0.95rem;">
                        💡 La empresa cumple satisfactoriamente con los parámetros saludables requeridos hasta el período <strong>{mes_str} {año_int}</strong>. Puede emitir su documento corporativo oficial.
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                    <div style="padding: 10px 0; color: #856404; font-size: 0.95rem;">
                        ⚠️ La empresa presenta alertas financieras para el período seleccionado. El certificado se emitirá incluyendo las observaciones correspondientes.
                    </div>
                """, unsafe_allow_html=True)
                
        with col_btn2:
            if st.button("📄 Generar Certificado PDF", use_container_width=True, key="btn_generar_certificado_solvencia"):
                if puntaje_actual >= 40:
                    st.toast(f"✅ ¡Certificado de {mes_str} {año_int} generado con éxito!", icon="🎉")
                else:
                    st.error("❌ No es posible emitir certificado de solvencia para empresas en nivel no apto.")
