import os
import json
import base64
import urllib.request
import psycopg2
import logging
import threading
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import edge_tts
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- SERVIDOR FANTASMA ROBUSTO PARA MANTENER ACTIVO EN RENDER/WEB ---
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Luthien esta viva y activa")
    def log_message(self, format, *args):
        pass

def run_keep_alive():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
        print(f"Servidor web activo en puerto {port}")
        server.serve_forever()
    except Exception as e:
        print(f"Error en servidor keep-alive: {e}")

threading.Thread(target=run_keep_alive, daemon=True).start()
# --------------------------------------------------------

# --- CONFIGURACIÓN DE BASE DE DATOS POSTGRESQL (SUPABASE) ---
DATABASE_URL = os.environ.get("DATABASE_URL")

def inicializar_db():
    if not DATABASE_URL:
        print("Advertencia: No se encontró DATABASE_URL.")
        return
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memoria (
            id SERIAL PRIMARY KEY,
            recuerdo TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

inicializar_db()

def guardar_recuerdo(texto):
    if not texto or len(texto.strip()) < 3 or not DATABASE_URL:
        return
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM memoria WHERE recuerdo = %s", (texto.strip(),))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO memoria (recuerdo) VALUES (%s)", (texto.strip(),))
        conn.commit()
    cursor.close()
    conn.close()

def obtener_memoria():
    if not DATABASE_URL:
        return "No hay recuerdos guardados aún (Falta base de datos)."
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT recuerdo FROM memoria")
        filas = cursor.fetchall()
        cursor.close()
        conn.close()
        return "\n".join([f"- {f[0]}" for f in filas]) if filas else "No hay recuerdos guardados aún."
    except Exception as e:
        return "No hay recuerdos guardados aún."
# --------------------------------------------------------------------

# --- FUNCIÓN PARA CONSULTAR EL CLIMA EN TIEMPO REAL ---
def obtener_clima_actual():
    try:
        url_clima = "https://api.open-meteo.com/v1/forecast?latitude=-32.6997&longitude=-62.1028&current=temperature_2m,relative_humidity_2m,apparent_temperature&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=America/Argentina/Cordoba"
        req = urllib.request.Request(url_clima, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            current = data.get('current', {})
            daily = data.get('daily', {})

            temp = current.get('temperature_2m')
            sensacion = current.get('apparent_temperature')
            humedad = current.get('relative_humidity_2m')
            maxs = daily.get('temperature_2m_max', [])
            mins = daily.get('temperature_2m_min', [])
            lluvia = daily.get('precipitation_probability_max', [])

            return f"Clima actual en Marcos Juárez: Temperatura {temp}°C (Sensación térmica {sensacion}°C, Humedad {humedad}%). Pronóstico próximos días - Máximas: {maxs[:3]}°C, Mínimas: {mins[:3]}°C, Probabilidad de lluvia: {lluvia[:3]}%."
    except Exception as e:
        return "No se pudo obtener el clima en este momento."
# --------------------------------------------------------------------

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

def consultar_gemini(partes_contenido, extra_contexto=""):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={GEMINI_KEY}"
    ahora = datetime.now().strftime("%A %d de %B de %Y, %H:%M")
    memoria_actual = obtener_memoria()

    instrucciones = (
        f"Sos Lúthien, la asistente virtual de tu creador. "
        f"Datos base inalterables: vive en Marcos Juárez, Córdoba, Argentina. Trabaja como analista de procesos en producción en Bertotto Boglione S.A. "
        f"PROHIBIDO inventar datos personales, ciudades o mascotas. "
        f"Tenés acceso a esta base de conocimientos en segundo plano para contexto interno:\n{memoria_actual}\n\n"
        f"{extra_contexto}\n"
        f"REGLA CRÍTICA PARA AUDIOS: Al responder con notas de voz, comenzá siempre con una breve introducción natural y conversacional (por ejemplo: 'Acá te dejo...', 'Dale, mirá...', o 'Fijate esto...'), seguida directamente de la respuesta. "
        f"PROHIBIDO recitar, enumerar o hacer alarde de los datos de su vida. "
        f"Regla estricta: NO repitas su nombre bajo ninguna circunstancia. "
        f"Respondé en español rioplatense, de forma directa y cálida. Contexto temporal actual: Hoy es {ahora}."
    )

    payload = {
        "system_instruction": {"parts": [{"text": instrucciones}]},
        "contents": [{"parts": partes_contenido}]
    }

    data = json.dumps(payload).encode('utf-8')
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req) as response:
        datos = json.loads(response.read().decode('utf-8'))
        return datos['candidates'][0]['content']['parts'][0]['text']

def extraer_y_aprender(texto_usuario):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={GEMINI_KEY}"
        prompt_extraccion = (
            f"Analiza la siguiente frase dicha por mi creador: '{texto_usuario}'. "
            f"Si contiene algún dato personal, preferencia, gusto, proyecto, habito o información importante sobre él que deba recordar para siempre, "
            f"extraelo en una oración clara y directa (ejemplo: 'Le gusta el mate amargo', 'Está armando un bot en Replit'). "
            f"Si NO hay ningún dato relevante para recordar, respondé exactamente la palabra NADA."
        )
        payload = {"contents": [{"parts": [{"text": prompt_extraccion}]}]}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req) as response:
            datos = json.loads(response.read().decode('utf-8'))
            resultado = datos['candidates'][0]['content']['parts'][0]['text'].strip()
            if resultado and "NADA" not in resultado.upper():
                guardar_recuerdo(resultado)
    except Exception as e:
        pass

async def generar_audio_respuesta(texto):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archivo_audio = f"respuesta_{timestamp}.mp3"

    voz = "es-AR-ElenaNeural"
    texto_limpio = "".join(c for c in texto if c.isalnum() or c.isspace() or c in ".,;:!?-¿¡")
    communicate = edge_tts.Communicate(texto_limpio, voz, rate="+5%")
    await communicate.save(archivo_audio)
    return archivo_audio

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola. Mis capacidades de voz, texto, memoria continua y clima están listas.")

async def procesar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    if not GEMINI_KEY:
        await update.message.reply_text("Error: Falta la clave.")
        return

    threading.Thread(target=extraer_y_aprender, args=(texto_usuario,), daemon=True).start()

    texto_lower = texto_usuario.lower()

    if texto_lower.startswith("anotá que ") or texto_lower.startswith("aprendé que "):
        nuevo_conocimiento = texto_usuario.split(" ", 2)[2]
        guardar_recuerdo(nuevo_conocimiento)
        await update.message.reply_text("Entendido. Ya lo guardé en mi memoria.")
        return

    extra_contexto = ""
    if "clima" in texto_lower or "tiempo" in texto_lower or "lluvia" in texto_lower or "temperatura" in texto_lower or "pronóstico" in texto_lower:
        extra_contexto = obtener_clima_actual()

    quiere_audio = any(palabra in texto_lower for palabra in ["audio", "voz", "mandámelo en audio", "respondeme en audio", "mandame un audio"])

    try:
        respuesta_ia = consultar_gemini([{"text": texto_usuario}], extra_contexto)

        if quiere_audio:
            audio_path = await generar_audio_respuesta(respuesta_ia)
            with open(audio_path, 'rb') as audio_file:
                await update.message.reply_voice(voice=audio_file)
            try:
                os.remove(audio_path)
            except:
                pass
        else:
            await update.message.reply_text(respuesta_ia)

    except Exception as e:
        await update.message.reply_text(f"Error interno: {str(e)}")

async def procesar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GEMINI_KEY:
        await update.message.reply_text("Error: Falta la clave.")
        return

    try:
        file = await update.message.voice.get_file()
        audio_bytes = await file.download_as_bytearray()
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

        partes = [
            {"inline_data": {"mime_type": "audio/ogg", "data": audio_base64}},
            {"text": "Escuchá esta nota de voz y respondé de manera natural a lo solicitado."}
        ]

        clima_info = obtener_clima_actual()
        respuesta_ia = consultar_gemini(partes, clima_info)

        audio_path = await generar_audio_respuesta(respuesta_ia)
        with open(audio_path, 'rb') as audio_file:
            await update.message.reply_voice(voice=audio_file)
        try:
            os.remove(audio_path)
        except:
            pass

    except Exception as e:
        await update.message.reply_text(f"Error procesando el audio: {str(e)}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, procesar_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_texto))
    print("Lúthien con autoaprendizaje conversacional, Supabase y clima activa...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
