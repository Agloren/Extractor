import streamlit as st
import fitz
from anthropic import Anthropic
import json
import re
import io
from pptx import Presentation
from pptx.util import Pt
from pptx.dml.color import RGBColor

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚", layout="wide")

# ─────────────────────────────────────────
# API
# ─────────────────────────────────────────
if "ANTHROPIC_API_KEY" in st.secrets:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("⚠️ No se encontró ANTHROPIC_API_KEY en secrets.")
    st.stop()

# ─────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────
for key, default in {
    "sources": [],
    "combined_text": "",
    "full_summary": "",
    "analysis_done": False,
    "chat_history": []
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ─────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────
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

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return RGBColor(
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16)
    )

# ─────────────────────────────────────────
# EXTRACTORES
# ─────────────────────────────────────────
def extract_pdf(file_bytes, name):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = "".join([p.get_text() for p in doc if p.get_text().strip()])
    return {"name": name, "type": "PDF", "text": text}

def extract_docx(file_bytes, name):
    import docx
    doc = docx.Document(io.BytesIO(file_bytes))
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    return {"name": name, "type": "Word", "text": text}

def extract_txt(file_bytes, name):
    text = file_bytes.decode("utf-8", errors="ignore")
    return {"name": name, "type": "Texto", "text": text}

def extract_pptx(file_bytes, name):
    from pptx import Presentation
    prs = Presentation(io.BytesIO(file_bytes))
    slides = []
    for i, slide in enumerate(prs.slides):
        parts = [s.text.strip() for s in slide.shapes if hasattr(s, "text") and s.text.strip()]
        if parts:
            slides.append(f"[Diapositiva {i+1}]\n" + "\n".join(parts))
    text = "\n\n".join(slides)
    return {"name": name, "type": "PowerPoint", "text": text}

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

# ─────────────────────────────────────────
# BUILD TEXT
# ─────────────────────────────────────────
def build_combined_text():
    return "\n\n".join([
        f"\n{'='*50}\nFUENTE: {s['name']} ({s['type']})\n{'='*50}\n{s['text']}"
        for s in st.session_state.sources
    ])

# ─────────────────────────────────────────
# RESUMEN
# ─────────────────────────────────────────
def generate_full_summary(combined_text):
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"""
Analiza profundamente este contenido.
Genera un resumen estructurado con:
- Ideas principales
- Conceptos clave
- Conexiones
- Aplicaciones prácticas

Contenido:
{smart_truncate(combined_text)}
"""
        }]
    )
    return r.content[0].text

# ─────────────────────────────────────────
# PRESENTACIÓN JSON
# ─────────────────────────────────────────
def generate_presentation_data(combined_text, num_slides):
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=min(8000, 500 * num_slides),
        messages=[{
            "role": "user",
            "content": f"""
Crea una presentación universitaria de {num_slides} diapositivas.
Máximo 6 bullets por slide.

Devuelve SOLO JSON válido:

{{
"titulo":"...",
"color_primario":"1E2761",
"color_acento":"F96167",
"slides":[
    {{
      "titulo":"...",
      "puntos":["...","..."]
    }}
]
}}

Contenido:
{smart_truncate(combined_text)}
"""
        }]
    )
    return safe_json_parse(r.content[0].text)

# ─────────────────────────────────────────
# GENERAR PPTX
# ─────────────────────────────────────────
def build_pptx_file(prs_data):

    prs = Presentation()

    primary = hex_to_rgb(prs_data.get("color_primario", "1E2761"))
    accent = hex_to_rgb(prs_data.get("color_acento", "F96167"))

    for slide_data in prs_data.get("slides", []):
        slide_layout = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout)

        title = slide.shapes.title
        title.text = slide_data.get("titulo", "")

        for paragraph in title.text_frame.paragraphs:
            paragraph.font.size = Pt(28)
            paragraph.font.bold = True
            paragraph.font.color.rgb = primary

        content = slide.placeholders[1]
        tf = content.text_frame
        tf.clear()

        for i, point in enumerate(slide_data.get("puntos", [])):
            if i == 0:
                tf.text = point
            else:
                p = tf.add_paragraph()
                p.text = point
                p.level = 1

        for paragraph in tf.paragraphs:
            paragraph.font.size = Pt(18)
            paragraph.font.color.rgb = accent

    pptx_io = io.BytesIO()
    prs.save(pptx_io)
    pptx_io.seek(0)
    return pptx_io.read()

# ─────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────
def chat_with_context(user_message):

    context = smart_truncate(st.session_state.combined_text, 40000)

    messages = [
        {
            "role": "user",
            "content": f"""
Eres un asistente académico.
Responde SOLO usando el contenido proporcionado.
Si algo no aparece, dilo claramente.

CONTENIDO:
{context}
"""
        }
    ]

    for msg in st.session_state.chat_history:
        messages.append(msg)

    messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        messages=messages
    )

    return response.content[0].text

# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────
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
    st.metric("Fuentes cargadas", len(st.session_state.sources))

if st.button("Analizar contenido", disabled=not bool(st.session_state.sources)):
    combined = build_combined_text()
    st.session_state.combined_text = combined

    with st.spinner("Generando resumen..."):
        st.session_state.full_summary = generate_full_summary(combined)

    st.session_state.analysis_done = True
    st.success("Análisis completo.")
    st.rerun()

if st.session_state.analysis_done:

    tab1, tab2, tab3 = st.tabs(["📋 Resumen", "🎯 Presentación PPT", "💬 Chat"])

    with tab1:
        st.markdown(st.session_state.full_summary)

    with tab2:
        num_slides = st.slider("Número de diapositivas", 8, 60, 20)

        if st.button("Generar PPT"):
            with st.spinner("Generando estructura..."):
                prs_data = generate_presentation_data(
                    st.session_state.combined_text,
                    num_slides
                )

            with st.spinner("Construyendo PowerPoint..."):
                pptx_bytes = build_pptx_file(prs_data)

            st.download_button(
                label="⬇️ Descargar presentación",
                data=pptx_bytes,
                file_name="presentacion.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )

    with tab3:

        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.chat_message("user").write(msg["content"])
            else:
                st.chat_message("assistant").write(msg["content"])

        user_input = st.chat_input("Haz una pregunta sobre el contenido...")

        if user_input:

            st.chat_message("user").write(user_input)

            st.session_state.chat_history.append({
                "role": "user",
                "content": user_input
            })

            with st.spinner("Pensando..."):
                answer = chat_with_context(user_input)

            st.chat_message("assistant").write(answer)

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": answer
            })
