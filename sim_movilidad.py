import customtkinter as ctk
import requests, json, webbrowser, os, smtplib, re, sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from fpdf import FPDF
from tavily import TavilyClient
from dotenv import load_dotenv

# 1. Función para encontrar el Escritorio real (OneDrive o Local)
def obtener_ruta_escritorio():
    home = os.path.expanduser("~")
    # Intentos comunes de rutas de escritorio en Windows
    posibles_rutas = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "OneDrive", "Escritorio"),
        os.path.join(home, "Escritorio")
    ]
    for ruta in posibles_rutas:
        if os.path.exists(ruta):
            return ruta
    return home # Si nada funciona, lo guarda en la carpeta de usuario

# 2. Cargar configuración
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
CORREO_EMISOR = os.getenv("CORREO_EMISOR")
CORREO_PASS = os.getenv("CORREO_PASS")

class sim_movilidad(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SIM v6.0 - Edición Estable")
        self.geometry("700x750")
        ctk.set_appearance_mode("dark")
        
        self.label = ctk.CTkLabel(self, text="SISTEMA DE MOVILIDAD INTELIGENTE", font=("Helvetica", 22, "bold"))
        self.label.pack(pady=20)

        self.city_entry = ctk.CTkEntry(self, placeholder_text="📍 Ciudad (Ej: Bogota)", width=450)
        self.city_entry.pack(pady=10)

        self.email_entry = ctk.CTkEntry(self, placeholder_text="📧 Correo destino", width=450)
        self.email_entry.pack(pady=10)

        self.btn_ejecutar = ctk.CTkButton(self, text="EJECUTAR ANÁLISIS", command=self.ejecutar_proceso, 
                                         font=("Helvetica", 14, "bold"), height=45)
        self.btn_ejecutar.pack(pady=20)

        self.textbox = ctk.CTkTextbox(self, width=650, height=350, font=("Consolas", 12))
        self.textbox.pack(pady=10)

    def log(self, mensaje):
        self.textbox.insert("end", mensaje + "\n")
        self.textbox.see("end")
        self.update_idletasks()

    def ejecutar_proceso(self):
        lugar = self.city_entry.get().strip()
        destino = self.email_entry.get().strip()
        
        if not lugar or "@" not in destino:
            self.log("❌ Error: Datos inválidos.")
            return

        self.btn_ejecutar.configure(state="disabled")
        self.textbox.delete("1.0", "end")
        
        try:
            # --- 1. TAVILY ---
            self.log(f"🌍 1. Buscando reportes para {lugar}...")
            tavily = TavilyClient(api_key=TAVILY_API_KEY)
            res = tavily.search(query=f"tráfico {lugar} incidentes hoy", max_results=5)
            noticias = [{"t": r['title'], "c": r['content'][:300]} for r in res.get('results', [])]

            # --- 2. IA ---
            self.log("🧠 2. Analizando con IA (Gemma)...")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemma-3-4b-it:generateContent?key={API_KEY}"
            prompt = f"Responde SOLO JSON: {{'resumen_general': '...', 'incidentes_lista': [{{'direccion': '...', 'descripcion': '...', 'gravedad': '...'}}]}} Datos: {json.dumps(noticias)}"
            
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30).json()
            texto_ia = resp['candidates'][0]['content']['parts'][0]['text']
            
            # Limpieza de JSON
            match = re.search(r'\{.*\}', texto_ia, re.DOTALL)
            if not match: raise ValueError("IA no generó JSON válido.")
            datos = json.loads(match.group(0))

            # --- 3. GENERACIÓN DE ARCHIVOS (Ruta Dinámica) ---
            escritorio = obtener_ruta_escritorio()
            ruta_pdf = os.path.join(escritorio, f"Reporte_{lugar}.pdf")
            ruta_mapa = os.path.join(escritorio, "mapa_movilidad.html")

            self.log(f"📄 3. Guardando PDF en: {ruta_pdf}")
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, txt=f"INFORME DE MOVILIDAD: {lugar.upper()}", ln=True, align='C')
            
            pdf.set_font("Arial", '', 11)
            # El secreto para las tildes: encode('latin-1', 'replace')
            resumen = datos['resumen_general'].encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 10, txt=resumen)

            for item in datos['incidentes_lista']:
                pdf.set_font("Arial", 'B', 10)
                linea = f"- {item['direccion']} ({item['gravedad']})".encode('latin-1', 'replace').decode('latin-1')
                pdf.cell(0, 8, txt=linea, ln=True)
                pdf.set_font("Arial", '', 9)
                desc = item['descripcion'].encode('latin-1', 'replace').decode('latin-1')
                pdf.multi_cell(0, 5, txt=f"{desc}\n")
            
            pdf.output(ruta_pdf)

            # --- 4. MAPA ---
            self.log("🗺️ 4. Generando mapa interactivo...")
            self.generar_mapa_html(ruta_mapa, lugar, datos['incidentes_lista'])

            # --- 5. CORREO ---
            self.log(f"📧 5. Enviando a {destino}...")
            msg = MIMEMultipart()
            msg['From'], msg['To'], msg['Subject'] = CORREO_EMISOR, destino, f"ALERTA SIM: {lugar}"
            msg.attach(MIMEText("Se adjunta el reporte de movilidad actualizado.", 'plain'))
            
            with open(ruta_pdf, "rb") as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f"attachment; filename=Reporte_{lugar}.pdf")
                msg.attach(part)
            
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(CORREO_EMISOR, CORREO_PASS)
                s.send_message(msg)

            webbrowser.open(f"file://{ruta_mapa}")
            self.log("\n✅ ¡SISTEMA FINALIZADO CON ÉXITO!")

        except Exception as e:
            self.log(f"❌ Error Crítico: {str(e)}")
        finally:
            self.btn_ejecutar.configure(state="normal")

    def generar_mapa_html(self, ruta, ciudad, incidentes):
        incidentes_json = json.dumps(incidentes)
        html = f"""
        <html><body style="margin:0;"><div id="map" style="height:100vh;"></div>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script>
            var map = L.map('map').setView([0,0], 2);
            L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png').addTo(map);
            
            async function init() {{
                // Buscamos la ciudad con el país para mayor precisión
                let rC = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q={ciudad}, Colombia`);
                let dC = await rC.json();
                if(dC.length > 0) map.setView([dC[0].lat, dC[0].lon], 13);

                const items = {incidentes_json};
                for(let i of items) {{
                    await new Promise(r => setTimeout(r, 1500)); // Aumentamos a 1.5s para evitar bloqueos
                    
                    // Buscamos la dirección específica dentro de la ciudad
                    let query = `${{i.direccion}}, {ciudad}, Colombia`;
                    let r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${{encodeURIComponent(query)}}`);
                    let d = await r.json();
                    
                    if(d.length > 0) {{
                        let c = i.gravedad === 'Alta' ? '#ff0000' : '#ffa500';
                        L.circleMarker([d[0].lat, d[0].lon], {{
                            color: 'white', 
                            weight: 2,
                            radius: 12, 
                            fillColor: c, 
                            fillOpacity: 0.9
                        }}).addTo(map).bindPopup(`<b>${{i.direccion}}</b><br>${{i.descripcion}}`);
                    }} else {{
                        console.log("No se encontró:", query);
                    }}
                }}
            }}
            init();
        </script></body></html>"""
        with open(ruta, "w", encoding="utf-8") as f: f.write(html)

if __name__ == "__main__":
    app = sim_movilidad()
    app.mainloop()