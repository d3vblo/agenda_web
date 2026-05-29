from flask import Flask, request, jsonify, render_template
import re
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import os
import json

app = Flask(__name__)

# =========================
# MAPA PROYECTOS
# =========================
mapa_proyectos = {
    "TAP": "1. AIFA - PACHUCA",
    "TMQ": "2. MÉXICO - QUERÉTARO",
    "TQI": "3. QUERÉTARO - IRAPUATO",
    "SNL": "4. SALTILLO - NUEVO LAREDO"
}

meses = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
}

def procesar_agenda(texto):

    # --- PROYECTO ---
    proyecto_match = re.search(r"Proyecto\s*(.*)", texto, re.IGNORECASE)
    proyecto_raw = proyecto_match.group(1).strip() if proyecto_match else ""
    if proyecto_raw:
        clave = proyecto_raw.split()[-1].upper()
        proyecto_final = mapa_proyectos.get(clave, proyecto_raw)
    else:
        proyecto_final = "SIN PROYECTO"

    # --- FECHA ---
    fecha_match = re.search(
        r"(?:\w+\s+)?(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
        texto, re.IGNORECASE
    )
    if fecha_match:
        dia = fecha_match.group(1).zfill(2)
        mes_texto = fecha_match.group(2).lower()
        anio = fecha_match.group(3)
        mes = meses.get(mes_texto, "00")
        fecha = f"{dia}/{mes}/{anio}"
        fecha_dt = datetime.strptime(fecha, "%d/%m/%Y")
        fecha_solicitud = (fecha_dt - timedelta(days=1)).strftime("%d/%m/%Y")
    else:
        fecha = ""
        fecha_solicitud = ""

    # --- BLOQUES ---
    bloques = re.split(r"\n\d+[\.-]\s*", texto)[1:]
    filas = []

    for bloque in bloques:
        bloque = bloque.replace('\xa0', ' ').strip()

        # HORA
        match_hora = re.search(r"(\d{1,2}:\d{2})\s*hrs?\s*[-–—]", bloque, re.IGNORECASE)
        hora_label_match = re.search(r"Hora:\s*(\d{1,2}:\d{2})", bloque, re.IGNORECASE)
        if match_hora:
            hora_txt = match_hora.group(1).strip()
        elif hora_label_match:
            hora_txt = hora_label_match.group(1).strip()
        else:
            hora_txt = ""

        # LÍNEA PRINCIPAL
        match_inline = re.search(r"\d{1,2}:\d{2}\s*hrs?\s*[-–—]\s*(.*)", bloque, re.IGNORECASE)
        if match_inline:
            linea_principal = match_inline.group(1).strip()
        else:
            linea_principal = bloque.splitlines()[0].strip()

        linea_principal = re.sub(r'^\d{1,2}:\d{2}\s*hrs?\.?\s*[-–—]\s*', '', linea_principal, flags=re.IGNORECASE).strip()
        linea_principal = re.sub(r'^[-–—\s]+', '', linea_principal).strip()
        linea_principal = re.sub(r'\.$', '', linea_principal).strip()

        actividad_txt = linea_principal

        # CAMPO Actividad:
        actividad_field = re.search(r"Actividad:\s*(.*?)(?=\n\s*\w+:|$)", bloque, re.IGNORECASE | re.DOTALL)
        actividad_detalle = ""
        if actividad_field and actividad_field.group(1).strip():
            actividad_raw = actividad_field.group(1).strip()
            actividad_detalle = re.sub(r'\s*\n\s*[•\-]\s*', ' | ', actividad_raw)
            actividad_detalle = re.sub(r'^[•\-]\s*', '', actividad_detalle).strip()

        # FRENTE
        frente = re.search(r"Frente:\s*(.*)", bloque, re.IGNORECASE)

        # POLÍGONO
        poligono = re.search(r"Pol[ií]gono:\s*(.*)", bloque, re.IGNORECASE)

        # MUNICIPIO
        municipio_match = re.search(r"Municipio:\s*(.*)", bloque, re.IGNORECASE)
        municipio = municipio_match.group(1).strip() if municipio_match else ""

        # ASISTENTES
        asistentes = re.search(
            r"(?:Asiste(?:n|ntes)?|Participa(?:n|ntes)?):\s*(.*)",
            bloque, re.IGNORECASE
        )

        # UBICACIÓN
        ubicacion = re.search(
            r"(?:Ubicaci[oó]n|Punto de reuni[oó]n|Punto de encuentro):\s*[\n\r]*\s*(?:\[.*?\]\((https?://[^\)\s]+)\)|(https?://\S+))",
            bloque,
            re.IGNORECASE
        )
        url = ""
        if ubicacion:
            url = (ubicacion.group(1) or ubicacion.group(2) or "").strip()

        # BDTs
        bdts = re.search(r"BDTs?:\s*(.*)", bloque, re.IGNORECASE)

        # ACTIVIDADES DESARROLLADAS
        partes = []
        if bdts and bdts.group(1).strip():
            partes.append(bdts.group(1).strip())
        partes.append(linea_principal)
        if actividad_detalle and actividad_detalle != linea_principal:
            partes.append(actividad_detalle)
        actividades_desarrolladas = " | ".join(partes) if partes else ""

        # NÚCLEO AGRARIO
        nucleo = re.search(r"Núcleo Agrario:\s*(.*)", bloque, re.IGNORECASE)

        # PROPIETARIOS
        particular = re.search(r"Propietarios?:\s*(.*)|Particular:\s*(.*)", bloque, re.IGNORECASE)

        # EJIDO
        ejido_match = re.search(r"Ejido:?\s*(.*)", bloque, re.IGNORECASE)
        ejido = ejido_match.group(1).strip() if ejido_match else ""

        fila = {
            "FECHA DE SOLICITUD": fecha_solicitud,
            "SOLICITANTE": "SEDATU",
            "MEDIO DE SOLICITUD": "WhatsApp",
            "TIPO DE SOLICITUD": actividad_txt,
            "PROYECTO FERROVIARIO": proyecto_final,
            "UBICACIÓN": url,
            "TIPO DE PROPIEDAD": "",
            "FRENTE": (
                re.sub(r'\b(\d+)\b', r'F\1', frente.group(1).strip())
                if frente else ""
            ),
            "POLÍGONO": (poligono.group(1).strip() if poligono else ""),
            "ESTADO": "",
            "MUNICIPIO": municipio,
            "EJIDO": ejido,
            "NÚCLEO AGRARIO": (nucleo.group(1).strip() if nucleo else ""),
            "PROPIETARIOS PROPIEDAD PRIVADA": (
                (particular.group(1) or particular.group(2) or "").strip()
                if particular else ""
            ),
            "FECHA Y HORA": f"{fecha} {hora_txt}",
            "DEPENDENCIAS PARTICIPANTES": (
                asistentes.group(1).strip() if asistentes else ""
            ),
            "ACTIVIDADES  DESARROLLADAS": actividades_desarrolladas,
        }

        filas.append(fila)

    return filas

def subir_a_sheets(filas):
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    # Soporte para credenciales desde variable de entorno (Render) o archivo local
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credenciales.json", scopes=SCOPES)

    client = gspread.Client(auth=creds)
    SPREADSHEET_ID = "1xwnS8DiEB4rzs7I8BRGgUbtzDF8M_zn58qYUJS-Mvmk"
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.get_worksheet(0)
    headers = worksheet.row_values(1)
    columna_a = worksheet.col_values(1)

    ultimo = 0
    if len(columna_a) > 1:
        try:
            ultimo = int(columna_a[-1])
        except:
            ultimo = 0

    inicio = ultimo + 1
    datos = []
    for i, fila in enumerate(filas):
        nueva_fila = [inicio + i]
        for header in headers[1:]:
            nueva_fila.append(fila.get(header, ""))
        datos.append(nueva_fila)

    worksheet.append_rows(datos, value_input_option="USER_ENTERED")
    return len(filas)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/procesar", methods=["POST"])
def procesar():
    try:
        texto = request.json.get("texto", "")
        if not texto.strip():
            return jsonify({"error": "El texto está vacío"}), 400
        filas = procesar_agenda(texto)
        if not filas:
            return jsonify({"error": "No se encontraron actividades en el texto"}), 400
        total = subir_a_sheets(filas)
        return jsonify({"success": True, "total": total})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False)
