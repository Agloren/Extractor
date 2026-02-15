import streamlit as st
import fitz
from anthropic import Anthropic
import json
import re
import io
import subprocess
import tempfile
import os

# ── CONFIG ─────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚", layout="wide")

# ── API CLIENT ─────────────────────────────────────
if "ANTHROPIC_API_KEY" in st.secrets:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("⚠️ No se encontró ANTHROPIC_API_KEY en secrets.")
    st.stop()

# ── SESSION STATE ──────────────────────────────────
for key, default in {
    "sources": [],
    "combined_text": "",
    "full_summary": "",
    "analysis_done": False,
    "chat_history": []
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ── UTILIDADES ─────────────────────────────────────
def smart_truncate(text, max_chars=60000):
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[Contenido truncado automáticamente]"

def safe_json_parse(raw):
    try:
        return json.loads(raw)
    except:
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)

# ── EXTRACTORES ────────────────────────────────────
def extract_pdf(file_bytes, name):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = "".join([p.get_text() for p in doc if p.get_text().strip()])
    return {"name": name, "type": "PDF", "text": text, "pages": len(doc), "icon": "📄"}

def extract_docx(file_bytes, name):
    import docx
    doc = docx.Document(io.BytesIO(file_bytes))
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    return {"name": name, "type": "Word", "text": text, "pages": max(1, len(text)//2000), "icon": "📝"}

def extract_txt(file_bytes, name):
    text = file_bytes.decode("utf-8", errors="ignore")
    return {"name": name, "type": "Texto", "text": text, "pages": max(1, len(text)//2000), "icon": "📃"}

def extract_pptx(file_bytes, name):
    from pptx import Presentation
    prs = Presentation(io.BytesIO(file_bytes))
    slides = []
    for i, slide in enumerate(prs.slides):
        parts = [s.text.strip() for s in slide.shapes if hasattr(s, "text") and s.text.strip()]
        if parts:
            slides.append(f"[Diapositiva {i+1}]\n" + "\n".join(parts))
    text = "\n\n".join(slides)
    return {"name": name, "type": "PowerPoint", "text": text, "pages": len(prs.slides), "icon": "📊"}

def process_file(uploaded_file):
    name = uploaded_file.name
    ext = name.split(".")[-1].lower()
    file_bytes = uploaded_file.read()

    if ext == "pdf":
        return extract_pdf(file_bytes, name)
    elif ext == "docx":
        return extract_docx(file_bytes, name)
    elif ext in ["txt", "md"]:
        return extract_txt(file_bytes, name)
    elif ext == "pptx":
        return extract_pptx(file_bytes, name)
    else:
        st.warning(f"Formato .{ext} no soportado.")
        return None

# ── BUILD TEXT ─────────────────────────────────────
def build_combined_text():
    return "\n\n".join([
        f"\n{'='*60}\n📁 FUENTE: {s['name']} ({s['type']})\n{'='*60}\n{s['text']}"
        for s in st.session_state.sources
    ])

# ── RESUMEN ────────────────────────────────────────
def generate_full_summary(combined_text):
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"""
Analiza profundamente este contenido.
Genera resumen estructurado con ideas principales,
conceptos clave, conexiones y aplicaciones prácticas.

Contenido:
{smart_truncate(combined_text)}
"""
        }]
    )
    return r.content[0].text

# ── PRESENTACIÓN JSON ──────────────────────────────
def generate_presentation_data(combined_text, num_slides):
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=min(8000, 500 * num_slides),
        messages=[{
            "role": "user",
            "content": f"""
Crea una presentación universitaria de {num_slides} diapositivas.
Máximo 6 bullets por slide.
Alterna tipos: titulo, concepto, cita, tabla, conclusion.

Devuelve SOLO JSON válido:

{{
"titulo":"...",
"autor":"AI Study Buddy",
"color_primario":"1E2761",
"color_secundario":"CADCFC",
"color_acento":"F96167",
"slides":[ ... ]
}}

Contenido:
{smart_truncate(combined_text)}
"""
        }]
    )
    return safe_json_parse(r.content[0].text)

# ── CONSTRUIR PPTX CON NODE ───────────────────────
def build_pptx_file(prs_data):

    if len(prs_data.get("slides", [])) > 70:
        raise RuntimeError("Máximo recomendado 70 diapositivas.")

    js_code = f"""
const pptxgen = require('pptxgenjs');
let pptx = new pptxgen();

pptx.title = "{prs_data.get('titulo','Presentación')}";

{generate_js_slides(prs_data)}

pptx.writeFile({{ fileName: "output.pptx" }});
"""

    tmp_js = tempfile.mktemp(suffix=".js")
    with open(tmp_js, "w", encoding="utf-8") as f:
        f.write(js_code)

    subprocess.run(["node", tmp_js], timeout=120)

    with open("output.pptx", "rb") as f:
        data = f.read()

    os.remove(tmp_js)
    os.remove("output.pptx")

    return data

def generate_js_slides(prs_data):
    js = ""
    for slide in prs_data.get("slides", []):
        js += "let slide = pptx.addSlide();\n"
        js += f"slide.addText('{slide.get('titulo','')}', {{ x:1, y:0.5, fontSize:24, bold:true }});\n"
        if "puntos" in slide:
            content = "\\n".join(slide["puntos"])
            js += f"slide.addText('{content}', {{ x:1, y:1.5, fontSize:18 }});\n"
    return js

# ── UI ─────────────────────────────────────────────
st.title("📚 AI Study Buddy")

uploaded_files = st.file_uploader(
    "Sube archivos",
    type=["pdf","docx","txt","md","pptx"],
    accept_multiple_files=True
)

if uploaded_files:
    if st.button("➕ Añadir archivos"):
        for f in uploaded_files:
            src = process_file(f)
            if src:
                st.session_state.sources.append(src)
        st.success("Fuentes añadidas.")
        st.rerun()

if st.session_state.sources:
    st.metric("Fuentes", len(st.session_state.sources))

if st.button("Analizar contenido", disabled=not bool(st.session_state.sources)):
    combined = build_combined_text()
    st.session_state.combined_text = combined
    with st.spinner("Generando resumen..."):
        st.session_state.full_summary = generate_full_summary(combined)
    st.session_state.analysis_done = True
    st.success("Análisis completo.")
    st.rerun()

if st.session_state.analysis_done:

    tab1, tab2 = st.tabs(["📋 Resumen", "🎯 Presentación PPT"])

    with tab1:
        st.markdown(st.session_state.full_summary)

    with tab2:
        num_slides = st.slider("Número de diapositivas", 8, 60, 20)

        if st.button("Generar PPT"):
            with st.spinner("Claude generando estructura..."):
                prs_data = generate_presentation_data(
                    st.session_state.combined_text,
                    num_slides
                )

            with st.spinner("Construyendo archivo .pptx..."):
                pptx_bytes = build_pptx_file(prs_data)

            st.success("Presentación lista.")

            st.download_button(
                label="⬇️ Descargar presentación",
                data=pptx_bytes,
                file_name="presentacion.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )
