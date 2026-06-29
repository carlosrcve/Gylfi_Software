# lanzador.py
import webview
import subprocess
import time
import os

# 1. Ahora arrancamos el MAIN que contiene ambos módulos
server = subprocess.Popen(["streamlit", "run", "main.py", "--server.headless", "true"])

time.sleep(2)

# 3. Ventana profesional única para King Driver, C.A.
window = webview.create_window(
    'King Driver ERP v1.0', 
    'http://localhost:8501',
    width=1300, # Un poco más ancho para ver bien el Mayor Analítico
    height=900,
    resizable=True
)

webview.start()

server.kill()