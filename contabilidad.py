                    st.markdown("#### 2️⃣ Frame: Retención de IVA")
                    col_f2_1, col_f2_2 = st.columns(2)
                    with col_f2_1:
                        # Colocamos el 0.0 de PRIMERO en la lista y cambiamos la key a v2 para forzar el refresco de Streamlit
                        porcentaje_ret_iva = st.selectbox(
                            "Porcentaje Retención IVA", 
                            options=[0.0, 75.0, 100.0, 50.0, 25.0], 
                            format_func=lambda x: f"{x}% (Sin retención / Exento)" if x == 0.0 else f"{x}%", 
                            key="f2_porc_ret_iva_v2"
                        )
                    with col_f2_2:
                        anular_iva_manual = st.checkbox("Forzar Retención IVA a 0.00", value=False, key="chk_anular_iva")
                                        
