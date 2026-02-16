import streamlit as st
import anthropic
import os
import io
import tempfile
import pandas as pd
from PyPDF2 import PdfReader
from docx import Document
from pptx import Presentation
from pptx.util import Inches, Pt
from moviepy import VideoFileClip
import pypandoc

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
st.set_page_config(page_title="AI Study Assistant", layout="wide")

client = anthropic.Anthropic(
    api_key=st.secrets["ANTHROPIC_API_KEY"]
)

# ─────────────────────────────────────────
# TEXT EXTRACTORS
# ─────────────────────────────────────────
def extract_pdf(file_bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def extract_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def extract_txt(file_bytes):
    return file_bytes.decode("utf-8", errors="ignore")

def extract_rtf(file_bytes):
    text = file_bytes.decode("utf-8", errors="ignore")
    return pypandoc.convert_text(text, "plain", format="rtf", extra_args=["--standalone"])

def extract_odt(file_bytes):
    from odf.opendocument import load
    from odf import text as odf_text

    with tempfile.NamedTemporaryFile(delete=False, suffix=".odt") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    doc = load(tmp_path)
    paragraphs = doc.getElementsByType(odf_text.P)
    return "\n".join([p.firstChild.data if p.firstChild else "" for p in paragraphs])

def extract_pptx(file_bytes):
    prs = Presentation(io.BytesIO(file_bytes))
    text = ""
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text += shape.text + "\n"
    return text

def extract_csv(file_bytes):
    df = pd.read_csv(io.BytesIO(file_bytes))
    return df.to_string()

def extract_xlsx(file_bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    return df.to_string()

# ─────────────────────────────────────────
# AUDIO / VIDEO
# ─────────────────────────────────────────
def transcribe_audio(file_bytes, filename):
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": "Transcribe fielmente el siguiente audio."
        }],
        attachments=[{
            "file_name": filename,
            "mime_type": "audio/mpeg",
            "data": file_bytes
        }]
    )
    return response.content[0].text

def extract_audio_from_video(file_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
        tmp_video.write(file_bytes)
        tmp_video_path = tmp_video.name

    clip = VideoFileClip(tmp_video_path)
    tmp_audio_path = tmp_video_path.replace(".mp4", ".mp3")
    clip.audio.write_audiofile(tmp_audio_path)

    with open(tmp_audio_path, "rb") as f:
        audio_bytes = f.read()

    clip.close()
    return audio_bytes

# ─────────────────────────────────────────
# FILE PROCESSOR
# ─────────────────────────────────────────
def process_file(uploaded_file):
    name = uploaded_file.name
    ext = name.split(".")[-1].lower()
    file_bytes = uploaded_file.read()

    if ext == "pdf":
        return extract_pdf(file_bytes)

    if ext in ["docx", "doc"]:
        return extract_docx(file_bytes)

    if ext in ["txt", "md"]:
        return extract_txt(file_bytes)

    if ext == "rtf":
        return extract_rtf(file_bytes)

    if ext == "odt":
        return extract_odt(file_bytes)

    if ext == "pptx":
        return extract_pptx(file_bytes)

    if ext == "csv":
        return extract_csv(file_bytes)

    if ext == "xlsx":
        return extract_xlsx(file_bytes)

    if ext in ["mp3", "wav", "m4a", "ogg"]:
        return transcribe_audio(file_bytes, name)

    if ext in ["mp4", "mov", "webm"]:
        audio_bytes = extract_audio_from_video(file_bytes)
        return transcribe_audio(audio_bytes, name)

    return ""

# ─────────────────────────────────────────
# AI FUNCTIONS
# ─────────────────────────────────────────
def summarize_text(text):
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"Resume este contenido de forma estructurada y clara:\n\n{text}"
        }]
    )
    return response.content[0].text

def generate_presentation_content(text):
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"""
Crea una presentación profesional.
Formato:

SLIDE: Título
- Punto
- Punto
- Punto

Contenido:
{text}
"""
        }]
    )
    return response.content[0].text

# ─────────────────────────────────────────
# BUILD PPT
# ─────────────────────────────────────────
def build_ppt(content):
    prs = Presentation()

    slides_raw = content.split("SLIDE:")
    for slide_block in slides_raw:
        if slide_block.strip() == "":
            continue

        lines = slide_block.strip().split("\n")
        title = lines[0]
        bullets = lines[1:]

        slide_layout = prs.slide_layouts[1]
        slide = prs.slides.add_slide(slide_layout)
        slide.shapes.title.text = title

        content_placeholder = slide.placeholders[1]
        content_placeholder.text = ""

        for bullet in bullets:
            if bullet.strip():
                p = content_placeholder.text_frame.add_paragraph()
                p.text = bullet.replace("-", "").strip()
                p.level = 1

    ppt_io = io.BytesIO()
    prs.save(ppt_io)
    ppt_io.seek(0)
    return ppt_io

# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────
st.title("📚 AI Study Assistant PRO")

uploaded_files = st.file_uploader(
    "Sube archivos",
    type=[
        "pdf","docx","doc","txt","md","rtf","odt",
        "pptx","csv","xlsx",
        "mp3","wav","m4a","ogg",
        "mp4","mov","webm"
    ],
    accept_multiple_files=True
)

if uploaded_files:
    full_text = ""
    for file in uploaded_files:
        with st.spinner(f"Procesando {file.name}..."):
            full_text += process_file(file) + "\n\n"

    st.success("Archivos procesados")

    if st.button("Generar Resumen"):
        with st.spinner("Generando resumen..."):
            summary = summarize_text(full_text)
            st.write(summary)

    if st.button("Generar Presentación PPT"):
        with st.spinner("Creando presentación..."):
            ppt_content = generate_presentation_content(full_text)
            ppt_file = build_ppt(ppt_content)

            st.download_button(
                "Descargar PPT",
                ppt_file,
                file_name="presentacion_generada.pptx"
            )

    st.divider()
    st.subheader("Chat sobre el contenido")

    question = st.text_input("Haz una pregunta")

    if question:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"Contenido:\n{full_text}\n\nPregunta:\n{question}"
            }]
        )
        st.write(response.content[0].text)
