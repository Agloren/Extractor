import streamlit as st
import fitz  # PyMuPDF
from anthropic import Anthropic

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚")

# API Key: usa Secrets de Streamlit Cloud (no .env, que no funciona en cloud)
if "ANTHROPIC_API_KEY" in st.secrets:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("⚠️ No se encontró la API Key en los Secrets de Streamlit.")
    st.stop()

# ── FUNCIONES ──────────────────────────────────────────────────────────────────
def extract_text(pdf_file):
    """Lee el PDF localmente con PyMuPDF (sin enviarlo a la API)."""
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def get_claude_response(text):
    """Envía el texto (truncado) a Claude y devuelve el análisis."""
    with st.spinner("Claude está analizando el documento... 🧠"):
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",  # ✅ Modelo actualizado
            max_tokens=2000,
            system="Eres un experto en aprendizaje acelerado. Extrae los conceptos clave en una tabla de Markdown.",
            messages=[{"role": "user", "content": text[:15000]}]
        )
        return message.content[0].text

# ── INTERFAZ ───────────────────────────────────────────────────────────────────
st.title("🚀 Extractor de Conceptos con IA")
st.markdown("Sube tu PDF y deja que Claude resuma lo esencial por ti.")

uploaded_file = st.file_uploader("Elige un archivo PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Analizar Libro"):
        texto_completo = extract_text(uploaded_file)

        if not texto_completo.strip():
            st.warning("⚠️ No se pudo extraer texto. El PDF puede ser una imagen escaneada.")
        else:
            resultado = get_claude_response(texto_completo)

            st.subheader("📌 Conceptos Clave")
            st.markdown(resultado)

            st.download_button(
                "⬇️ Descargar Resumen (.md)",
                resultado,
                file_name="resumen_estudio.md"
            )
