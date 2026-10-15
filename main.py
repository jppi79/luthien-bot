import os
import json
import base64
import urllib.request
import psycopg2
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
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
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memoria (
                id SERIAL PRIMARY KEY,
                recuerdo TEXT NOT NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS catas_cannabis (
                id SERIAL PRIMARY KEY,
                cepa TEXT NOT NULL,
                efectos_positivos TEXT,
                efectos_negativos TEXT,
                nivel_sedacion TEXT,
                nivel_bajon TEXT,
                nivel_paranoia TEXT,
                notas TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diario_habitos (
                id SERIAL PRIMARY KEY,
                categoria TEXT NOT NULL,
                detalle TEXT NOT NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historial_medico (
                id SERIAL PRIMARY KEY,
                tipo_estudio TEXT NOT NULL,
                resumen_diagnostico TEXT NOT NULL,
                valores_clave TEXT,
                observaciones TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error inicializando la base de datos: {e}")

inicializar_db()

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
        conn.close()
    except Exception as e:
        pass

def guardar_cata(cepa, ef_pos, ef_neg, sedacion, bajon, paranoia, notas):
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO catas_cannabis (cepa, efectos_positivos, efectos_negativos, nivel_sedacion, nivel_bajon, nivel_paranoia, notas)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (cepa, ef_pos, ef_neg, sedacion, bajon, paranoia, notas))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        pass

def guardar_registro_medico(tipo, resumen, valores, observaciones):
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO historial_medico (tipo_estudio, resumen_diagnostico, valores_clave, observaciones)
            VALUES (%s, %s, %s, %s)
        """, (tipo, resumen, valores, observaciones))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        pass

def obtener_memoria_y_registros():
    if not DATABASE_URL:
        return "Sin conexión a BD."
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("SELECT recuerdo FROM memoria ORDER BY fecha DESC LIMIT 15")
        recuerdos = cursor.fetchall()
        
        cursor.execute("SELECT cepa, efectos_positivos, nivel_sedacion, fecha FROM catas_cannabis ORDER BY fecha DESC LIMIT 5")
        catas = cursor.fetchall()
        
        cursor.execute("SELECT tipo_estudio, resumen_diagnostico, fecha FROM historial_medico ORDER BY fecha DESC LIMIT 5")
        medicos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        texto_memoria = "RECUERDOS GENERALES:\n" + ("\n".join([f"- {r[0]}" for r in recuerdos]) if recuerdos else "Ninguno")
        texto_catas = "\n\nÚLTIMAS CATAS:\n" + ("\n".join([f"- {c[0]}: {c[1]} (Sedación: {c[2]})" for c in catas]) if catas else "Ninguna")
        texto_medico = "\n\nHISTORIAL MÉDICO RECIENTE:\n" + ("\n".join([f"- {m[0]}: {m[1]}" for m in medicos]) if medicos else "Ninguno")
        
        return f"{texto_memoria}{texto_catas}{texto_medico}"
    except Exception as e:
        return "No se pudieron obtener registros previos."

# --------------------------------------------------------------------

# --- FUNCIÓN ORIGINAL ROBUSTA DE CLIMA ---
def obtener_clima_actual():
    try:
        url_clima = "https://api.open-meteo.com/v1/forecast?latitude=-32.6997&longitude=-62.1028&current=temperature_2m,relative_humidity_2m,apparent_temperature&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=America/Argentina/Cordoba"
        req = urllib.request.Request(url_clima, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            current = data.get('current', {})
            daily = data.get('daily', {})

            temp = current.get('temperature_2m')
            sensacion = current.get('apparent_temperature')
            humedad = current.get('relative_humidity_2m')
            maxs = daily.get('temperature_2m_max', [])
            mins = daily.get('temperature_2m_min', [])
            lluvia = daily.get('precipitation_probability_max', [])

            return f"CLIMA EN MARCOS JUÁREZ: Actual: {temp}°C (ST {sensacion}°C, Humedad {humedad}%). Pronóstico próximos 3 días - Máximas: {maxs[:3]}°C, Mínimas: {mins[:3]}°C, Lluvia prob: {lluvia[:3]}%."
    except Exception as e:
        return "Datos de clima no disponibles temporalmente."

# --------------------------------------------------------------------

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

def consultar_gemini(partes_contenido):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={GEMINI_KEY}"
    ahora = datetime.now().strftime("%A %d de %B de %Y, %H:%M")
    memoria_actual = obtener_memoria_y_registros()
    clima_actual = obtener_clima_actual()

    instrucciones = (
        f"Sos Lúthien, la asistente virtual de tu creador. "
        f"Datos base inalterables: vive en Marcos Juárez, Córdoba, Argentina. Trabaja como analista de procesos en producción en Bertotto Boglione S.A. "
        f"PROHIBIDO inventar datos personales, ciudades o mascotas. "
        f"CONTEXTO EN TIEMPO REAL:\n"
        f"- Fecha y hora actual: {ahora}\n"
        f"- Estado del clima: {clima_actual}\n"
        f"- Base de memoria y registros:\n{memoria_actual}\n\n"
        f"REGLA DE INTERPRETACIÓN: Tenés siempre a disposición la información del clima actual y pronóstico. Si el usuario pregunta de cualquier forma directa o implícita sobre la temperatura, el pronóstico, si va a llover o cómo estará mañana, respondé usando los datos de clima del contexto.\n"
        f"REGLA CRÍTICA PARA AUDIOS: Al responder con notas de voz, comenzá siempre con una breve introducción natural y conversacional, seguida directamente de la respuesta. "
        f"PROHIBIDO recitar, enumerar o hacer alarde de los datos de su vida. "
        f"Regla estricta: NO repitas su nombre bajo ninguna circunstancia. "
        f"Respondé en español rioplatense, de forma directa y cálida."
    )

    payload = {
        "system_instruction": {"parts": [{"text": instrucciones}]},
        "contents": [{"parts": partes_contenido}]
    }

    data = json.dumps(payload).encode('utf-8')
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=10) as response:
        datos = json.loads(response.read().decode('utf-8'))
        return datos['candidates'][0]['content']['parts'][0]['text']

def extraer_y_aprender(texto_usuario):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={GEMINI_KEY}"
        prompt_extraccion = (
            f"Analiza el siguiente texto: '{texto_usuario}'.\n"
            f"1. Si es una CATA DE CANNABIS, responde en JSON con la clave 'tipo': 'cata' y los campos: cepa, efectos_positivos, efectos_negativos, sedacion, bajon, paranoia, notas.\n"
            f"2. Si es un REGISTRO MÉDICO O SÍNTOMA, responde en JSON con la clave 'tipo': 'medico' y los campos: tipo_estudio, resumen, valores_clave, observaciones.\n"
            f"3. Si es un dato personal o preferencia general, responde en JSON con la clave 'tipo': 'recuerdo' y el campo 'texto'.\n"
            f"4. Si NO hay nada que guardar, responde exactamente la palabra NADA."
        )
        payload = {"contents": [{"parts": [{"text": prompt_extraccion}]}]}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            datos = json.loads(response.read().decode('utf-8'))
            resultado = datos['candidates'][0]['content']['parts'][0]['text'].strip()
            
            if "NADA" not in resultado.upper():
                try:
                    inicio = resultado.find('{')
                    fin = resultado.rfind('}') + 1
                    if inicio != -1 and fin != -1:
                        parsed = json.loads(resultado[inicio:fin])
                        tipo = parsed.get("tipo")
                        if tipo == "cata":
                            guardar_cata(
                                parsed.get("cepa", "Desconocida"),
                                parsed.get("efectos_positivos", ""),
                                parsed.get("efectos_negativos", ""),
                                str(parsed.get("sedacion", "")),
                                str(parsed.get("bajon", "")),
                                str(parsed.get("paranoia", "")),
                                parsed.get("notas", "")
                            )
                        elif tipo == "medico":
                            guardar_registro_medico(
                                parsed.get("tipo_estudio", "Consulta/Síntoma"),
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archivo_audio = f"respuesta_{timestamp}.mp3"
    voz = "es-AR-ElenaNeural"
    texto_limpio = "".join(c for c in texto if c.isalnum() or c.isspace() or c in ".,;:!?-¿¡")
    communicate = edge_tts.Communicate(texto_limpio, voz, rate="+5%")
    await communicate.save(archivo_audio)
    return archivo_audio

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola. Mis capacidades de voz, texto, visión de imágenes/estudios médicos, cata de cannabis y memoria están listas.")

async def procesar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    if not GEMINI_KEY:
        await update.message.reply_text("Error: Falta la clave de Gemini.")
        return

    threading.Thread(target=extraer_y_aprender, args=(texto_usuario,), daemon=True).start()

    texto_lower = texto_usuario.lower()

    if texto_lower.startswith("anotá que ") or texto_lower.startswith("aprendé que "):
        nuevo_conocimiento = texto_usuario.split(" ", 2)[2]
        guardar_recuerdo(nuevo_conocimiento)
        await update.message.reply_text("Entendido. Ya lo guardé en mi memoria.")
        return

    quiere_audio = any(palabra in texto_lower for palabra in ["audio", "voz", "mandámelo en audio", "respondeme en audio", "mandame un audio"])

    try:
        respuesta_ia = consultar_gemini([{"text": texto_usuario}])

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

async def procesar_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GEMINI_KEY:
        await update.message.reply_text("Error: Falta la clave.")
        return

    try:
        foto = update.message.photo[-1]
        file = await foto.get_file()
        img_bytes = await file.download_as_bytearray()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        caption = update.message.caption or "Analizá esta imagen o estudio médico y extraé la información relevante."

        partes = [
            {"inline_data": {"mime_type": "image/jpeg", "data": img_base64}},
            {"text": f"El usuario envió una imagen con este mensaje: '{caption}'. Si es un análisis médico, receta o informe, analizá los valores, diagnóstico y conclusiones principales."}
        ]

        respuesta_ia = consultar_gemini(partes)

        prompt_medico = f"Imagen analizada. Mensaje: '{caption}'. Respuesta IA: '{respuesta_ia}'. Extraé el estudio médico si aplica."
        threading.Thread(target=extraer_y_aprender, args=(prompt_medico,), daemon=True).start()

        await update.message.reply_text(respuesta_ia)

    except Exception as e:
        await update.message.reply_text(f"Error procesando la imagen: {str(e)}")

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

        respuesta_ia = consultar_gemini(partes)

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
    app.add_handler(MessageHandler(filters.PHOTO, procesar_imagen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_texto))
    print("Lúthien activa con clima nativo (Open-Meteo), BD y memoria...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
