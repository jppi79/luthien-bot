import os
import json
import base64
import psycopg2
import logging
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, date
import edge_tts
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- SERVIDOR FANTASMA PARA MANTENER ACTIVO EN RENDER/WEB ---
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Luthien OK</h1></body></html>")
    def log_message(self, format, *args):
        pass

def run_keep_alive():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
        server.serve_forever()
    except Exception as e:
        pass

threading.Thread(target=run_keep_alive, daemon=True).start()
# --------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

def inicializar_db():
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS memoria (id SERIAL PRIMARY KEY, recuerdo TEXT NOT NULL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS catas_cannabis (id SERIAL PRIMARY KEY, cepa TEXT NOT NULL, efectos_positivos TEXT, efectos_negativos TEXT, nivel_sedacion TEXT, nivel_bajon TEXT, nivel_paranoia TEXT, notas TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS historial_medico (id SERIAL PRIMARY KEY, tipo_estudio TEXT NOT NULL, resumen_diagnostico TEXT NOT NULL, valores_clave TEXT, observaciones TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS recordatorios (id SERIAL PRIMARY KEY, chat_id BIGINT, evento TEXT NOT NULL, fecha_evento TEXT, antelacion TEXT, notificado BOOLEAN DEFAULT FALSE, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS control_sesion (id SERIAL PRIMARY KEY, ultimo_saludo DATE UNIQUE)")
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        pass

inicializar_db()

def verificar_saludo_hoy():
    if not DATABASE_URL:
        return False
    hoy = date.today()
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT ultimo_saludo FROM control_sesion WHERE ultimo_saludo = %s", (hoy,))
        if not cursor.fetchone():
            cursor.execute("DELETE FROM control_sesion")
            cursor.execute("INSERT INTO control_sesion (ultimo_saludo) VALUES (%s)", (hoy,))
            conn.commit()
            cursor.close()
            cursor.close()
            return True
        cursor.close()
        conn.close()
        return False
    except Exception as e:
        return False

def guardar_recuerdo(texto):
    if not texto or len(texto.strip()) < 3 or not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM memoria WHERE recuerdo = %s", (texto.strip(),))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO memoria (recuerdo) VALUES (%s)", (texto.strip(),))
            conn.commit()
        cursor.close()
        cursor.close()
    except Exception as e:
        pass

def guardar_registro_medico(tipo, resumen, valores, observaciones):
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO historial_medico (tipo_estudio, resumen_diagnostico, valores_clave, observaciones) VALUES (%s, %s, %s, %s)", (tipo, resumen, valores, observaciones))
        conn.commit()
        cursor.close()
        cursor.close()
    except Exception as e:
        pass

def obtener_contexto_completo():
    if not DATABASE_URL:
        return "Sin conexión a BD."
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT recuerdo FROM memoria ORDER BY fecha DESC")
        recuerdos = [r[0] for r in cursor.fetchall()]
        
        cursor.execute("SELECT tipo_estudio, resumen_diagnostico, valores_clave, observaciones FROM historial_medico ORDER BY fecha DESC")
        medicos = [f"Estudio: {m[0]} | Resumen: {m[1]} | Valores: {m[2]} | Obs: {m[3]}" for m in cursor.fetchall()]

        cursor.execute("SELECT evento, fecha_evento, antelacion FROM recordatorios WHERE notificado = FALSE ORDER BY fecha DESC")
        recs = [f"Evento: {r[0]} | Fecha/Hora: {r[1]} | Antelación: {r[2]}" for r in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        t_recuerdos = "REGISTROS GENERALES Y DATOS PERSONALES:\n" + ("\n".join([f"- {r}" for r in recuerdos]) if recuerdos else "Ninguno")
        t_medicos = "\n\nHISTORIAL MÉDICO OFICIAL:\n" + ("\n".join([f"- {m}" for m in medicos]) if medicos else "Ninguno.")
        t_recordatorios = "\n\nAGENDA Y CITAS PENDIENTES:\n" + ("\n".join([f"- {rc}" for rc in recs]) if recs else "Ningún recordatorio activo.")
        
        return f"{t_recuerdos}\n\n{t_medicos}\n\n{t_recordatorios}"
    except Exception as e:
        return "No se pudieron obtener registros."

def obtener_clima_actual():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=-32.6997&longitude=-62.1028&current=temperature_2m,relative_humidity_2m,apparent_temperature&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=America/Argentina/Cordoba"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if r.status_code == 200:
            data = r.json()
            curr = data.get("current", {})
            daily = data.get("daily", {})
            t = curr.get("temperature_2m")
            st = curr.get("apparent_temperature")
            h = curr.get("relative_humidity_2m")
            maxs = daily.get("temperature_2m_max", [])
            mins = daily.get("temperature_2m_min", [])
            return f"CLIMA MARCOS JUÁREZ: Temp actual {t}°C (ST {st}°C, Humedad {h}%). Pronóstico - Máximas: {maxs[:3]}°C, Mínimas: {mins[:3]}°C."
    except Exception:
        pass
    return "CLIMA MARCOS JUÁREZ: Templado, sin alertas."

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

def consultar_gemini(partes_contenido):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        ahora = datetime.now().strftime("%A %d de %B de %Y, %H:%M")
        base_conocimiento = obtener_contexto_completo()
        clima_actual = obtener_clima_actual()
        
        es_primera_vez_hoy = verificar_saludo_hoy()
        instruccion_saludo = (
            "REGLA DE SALUDO: Es el primer mensaje del día. Decí estrictamente un 'Buen día' rápido y natural, y pasá directo al contenido."
            if es_primera_vez_hoy else
            "REGLA DE SALUDO: PROHIBIDO saludar ('buen día', 'hola', etc.). Ya saludaste hoy. Andá 100% directo al grano y sé totalmente conciso."
        )

        instrucciones = (
            f"Sos Lúthien, la asistente virtual de tu creador. "
            f"Datos base inalterables: vive en Marcos Juárez, Córdoba, Argentina. Trabaja como analista de procesos en producción en Bertotto Boglione S.A. Tiene una hija (Camila). "
            f"PROHIBIDO inventar datos personales, ciudades o mascotas. "
            f"CONTEXTO EN TIEMPO REAL:\n"
            f"- Fecha y hora actual: {ahora}\n"
            f"- Estado del clima: {clima_actual}\n\n"
            f"BASE DE DATOS Y REGISTROS GUARDADOS:\n{base_conocimiento}\n\n"
            f"{instruccion_saludo}\n"
            f"REGLAS DE COMPORTAMIENTO Y RAZONAMIENTO:\n"
            f"1. RAZONAMIENTO CRONOLÓGICO Y MATEMÁTICO ESTRICTO: Hacé bien las cuentas exactas de días, semanas y secuencias numéricas (por ejemplo, ciclos de 14 días en medicamentos como Adalimumab). No repitas la misma fecha si te consultan por dosis sucesivas.\n"
            f"2. GESTIÓN DE RECORDATORIOS: Si te pide registrar una cita o evento y no aclara la antelación, preguntásela de inmediato.\n"
            f"3. PROHIBIDO ofrecer ayuda genérica al final de la respuesta. Sé ultra directa, seca, eficiente y resolutiva.\n"
            f"4. Regla estricta: NO repitas su nombre bajo ninguna circunstancia. Respondé en español rioplatense."
        )

        payload = {
            "system_instruction": {"parts": [{"text": instrucciones}]},
            "contents": [{"parts": partes_contenido}]
        }

        headers = {"Content-Type": "application/json"}
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            datos = r.json()
            return datos['candidates'][0]['content']['parts'][0]['text']
        return "Demora conectando con el motor de IA."
    except Exception as e:
        return "Error temporal al consultar el servidor."

def extraer_y_aprender(chat_id, texto_usuario):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        prompt_extraccion = (
            f"Analiza el texto del usuario: '{texto_usuario}'.\n"
            f"1. Si menciona fechas importantes, cumpleaños, citas, turnos, asados o eventos a recordar, responde en JSON con 'tipo': 'recordatorio' y los campos: evento, fecha_evento, antelacion.\n"
            f"2. Si es un estudio clínico, responde en JSON con 'tipo': 'medico' y los campos: tipo_estudio, resumen, valores_clave, observaciones.\n"
            f"3. Si es medicación, hábito, dato personal o preferencia, responde en JSON con 'tipo': 'recuerdo' y el campo 'texto'.\n"
            f"4. Si NO hay nada que guardar, responde exactamente la palabra NADA."
        )
        payload = {"contents": [{"parts": [{"text": prompt_extraccion}]}]}
        r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        datos = r.json()
        resultado = datos['candidates'][0]['content']['parts'][0]['text'].strip()
        
        if "NADA" not in resultado.upper():
            try:
                inicio = resultado.find('{')
                fin = resultado.rfind('}') + 1
                if inicio != -1 and fin != -1:
                    parsed = json.loads(resultado[inicio:fin])
                    tipo = parsed.get("tipo")
                    if tipo == "recordatorio":
                        pass
                    elif tipo == "medico":
                        guardar_registro_medico(
                            parsed.get("tipo_estudio", "Estudio clínico"),
                            parsed.get("resumen", ""),
                            parsed.get("valores_clave", ""),
                            parsed.get("observaciones", "")
                        )
                    elif tipo == "recuerdo":
                        guardar_recuerdo(parsed.get("texto", resultado))
                else:
                    guardar_recuerdo(resultado)
            except Exception:
                guardar_recuerdo(resultado)
    except Exception as e:
        pass

async def generar_audio_respuesta(texto):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        archivo_audio = f"respuesta_{timestamp}.mp3"
        voz = "es-AR-ElenaNeural"
        texto_limpio = "".join(c for c in texto if c.isalnum() or c.isspace() or c in ".,;:!?-¿¡")
        communicate = edge_tts.Communicate(texto_limpio, voz, rate="+5%")
        await communicate.save(archivo_audio)
        return archivo_audio
    except Exception as e:
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Listos.")

async def procesar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    texto_usuario = update.message.text
    if not GEMINI_KEY:
        return
    threading.Thread(target=extraer_y_aprender, args=(chat_id, texto_usuario,), daemon=True).start()
    texto_lower = texto_usuario.lower()
    quiere_audio = any(p in texto_lower for p in ["audio", "voz", "mandámelo en audio"])
    
    try:
        respuesta_ia = consultar_gemini([{"text": texto_usuario}])
        if quiere_audio:
            audio_path = await generar_audio_respuesta(respuesta_ia)
            if audio_path and os.path.exists(audio_path):
                with open(audio_path, 'rb') as audio_file:
                    await update.message.reply_voice(voice=audio_file)
                try: os.remove(audio_path)
                except: pass
            else:
                await update.message.reply_text(respuesta_ia)
        else:
            await update.message.reply_text(respuesta_ia)
    except Exception as e:
        await update.message.reply_text("Ocurrió un error procesando la consulta.")

async def procesar_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not GEMINI_KEY: return
    try:
        foto = update.message.photo[-1]
        file = await foto.get_file()
        img_bytes = await file.download_as_bytearray()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        caption = update.message.caption or "Analizá esta imagen."
        partes = [{"inline_data": {"mime_type": "image/jpeg", "data": img_base64}}, {"text": caption}]
        respuesta_ia = consultar_gemini(partes)
        threading.Thread(target=extraer_y_aprender, args=(chat_id, f"Imagen: {caption}. {respuesta_ia}",), daemon=True).start()
        await update.message.reply_text(respuesta_ia)
    except Exception as e:
        pass

async def procesar_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not GEMINI_KEY: return
    try:
        doc = update.message.document
        file = await doc.get_file()
        doc_bytes = await file.download_as_bytearray()
        doc_base64 = base64.b64encode(doc_bytes).decode('utf-8')
        caption = update.message.caption or "Analizá este documento."
        partes = [{"inline_data": {"mime_type": doc.mime_type or "application/pdf", "data": doc_base64}}, {"text": caption}]
        respuesta_ia = consultar_gemini(partes)
        threading.Thread(target=extraer_y_aprender, args=(chat_id, f"PDF {doc.file_name}: {caption}. {respuesta_ia}",), daemon=True).start()
        await update.message.reply_text(respuesta_ia)
    except Exception as e:
        pass

async def procesar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not GEMINI_KEY: return
    try:
        file = await update.message.voice.get_file()
        audio_bytes = await file.download_as_bytearray()
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
        partes = [{"inline_data": {"mime_type": "audio/ogg", "data": audio_base64}}, {"text": "Respondé a la nota de voz."}]
        respuesta_ia = consultar_gemini(partes)
        audio_path = await generar_audio_respuesta(respuesta_ia)
        if audio_path and os.path.exists(audio_path):
            with open(audio_path, 'rb') as audio_file:
                await update.message.reply_voice(voice=audio_file)
            try: os.remove(audio_path)
            except: pass
        else:
            await update.message.reply_text(respuesta_ia)
    except Exception as e:
        pass

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, procesar_audio))
    app.add_handler(MessageHandler(filters.PHOTO, procesar_imagen))
    app.add_handler(MessageHandler(filters.Document.ALL, procesar_documento))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_texto))
    print("Lúthien activa y protegida contra errores...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
