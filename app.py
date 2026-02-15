import streamlit as st
import fitz  # PyMuPDF
from anthropic import Anthropic
import json
import re
import base64
import io
import subprocess
import tempfile
import os

# ── CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚", layout="wide")

# ── CLIENTE API ─────────────────────────────────────────────────────────
if "ANTHROPIC_API_KEY" in st.secrets:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("⚠️ No se encontró la API Key.")
    st.stop()

# ── SESSION STATE ───────────────────────────────────────────────────────
if "sources" not in st.session_state:
    st.session_state.sources = []
if "combined_text" not in st.session_state:
    st.session_state.combined_text = ""
if "full_summary" not in st.session_state:
    st.session_state.full_summary = ""
if "analysis_done" not in st.session_state:
    st.session_state.analysis_done = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "doc_info" not in st.session_state:
    st.session_state.doc_info = {}

# ── UTILIDADES ──────────────────────────────────────────────────────────
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

# ── EXTRACTORES ─────────────────────────────────────────────────────────
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

# ── BUILD TEXT ──────────────────────────────────────────────────────────
def build_combined_text():
    return "\n\n".join([
        f"\n{'='*60}\n📁 FUENTE: {s['name']} ({s['type']})\n{'='*60}\n{s['text']}"
        for s in st.session_state.sources
    ])

# ── RESUMEN ─────────────────────────────────────────────────────────────
def generate_full_summary(combined_text):
    total_pages = sum(s["pages"] for s in st.session_state.sources)

    if total_pages <= 10:
        max_tok = 1200
    elif total_pages <= 50:
        max_tok = 2500
    else:
        max_tok = 4000

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=max_tok,
        messages=[{
            "role": "user",
            "content": f"""
Analiza profundamente este contenido.
Genera un resumen estructurado con:

- Ideas principales
- Conceptos clave
- Conexiones importantes
- Aplicaciones prácticas
- Conclusión final

Contenido:
{smart_truncate(combined_text, 60000)}
"""
        }]
    )
    return r.content[0].text

# ── PRESENTACIÓN ─────────────────────────────────────────────────────────
def generate_presentation_data(combined_text, num_slides):
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=min(8000, 500 * num_slides),
        messages=[{
            "role": "user",
            "content": f"""
Eres un diseñador experto en presentaciones universitarias.

Crea una presentación profunda y progresiva de {num_slides} diapositivas.

Reglas:
- Máximo 6 bullets por slide
- Alterna tipos: titulo, concepto, cita, tabla, conclusion
- Notas del orador amplían la explicación
- Contenido sustancial

Devuelve SOLO JSON válido con estructura:

{{
"titulo":"...",
"autor":"AI Study Buddy",
"color_primario":"1E2761",
"color_secundario":"CADCFC",
"color_acento":"F96167",
"slides":[ ... ]
}}

Contenido:
{smart_truncate(combined_text, 60000)}
"""
        }]
    )

    raw = r.content[0].text
    return safe_json_parse(raw)

# ── INTERFAZ ────────────────────────────────────────────────────────────
st.title("📚 AI Study Buddy")

st.markdown("### 📥 Cargar fuentes")

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

st.markdown("### ⚡ Analizar")

if st.button("Analizar contenido", disabled=not bool(st.session_state.sources)):
    combined = build_combined_text()
    st.session_state.combined_text = combined

    with st.spinner("Generando resumen..."):
        st.session_state.full_summary = generate_full_summary(combined)

    st.session_state.analysis_done = True
    st.success("Análisis completo.")
    st.rerun()

# ── RESULTADOS ───────────────────────────────────────────────────────────
if st.session_state.analysis_done:

    tab1, tab2, tab3 = st.tabs([
        "📋 Resumen",
        "🎯 Presentación PPT",
        "💬 Chat"
    ])

    # RESUMEN
    with tab1:
        st.markdown(st.session_state.full_summary)
        st.download_button(
            "Descargar resumen",
            st.session_state.full_summary,
            "resumen.md"
        )

    # PPT
    with tab2:
        num_slides = st.slider(
            "Número de diapositivas",
            min_value=8,
            max_value=60,
            value=20
        )

        if st.button("Generar PPT"):
            with st.spinner("Claude diseñando presentación..."):
                prs_data = generate_presentation_data(
                    st.session_state.combined_text,
                    num_slides
                )

            st.success(f"{len(prs_data['slides'])} diapositivas creadas.")
            st.json(prs_data)

    # CHAT
    with tab3:
        question = st.text_input("Pregunta sobre el contenido")

        if st.button("Enviar") and question:
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": f"""
Responde usando exclusivamente este contenido:

{smart_truncate(st.session_state.combined_text, 60000)}

Pregunta:
{question}
"""
                }]
            )

            st.markdown(response.content[0].text)
