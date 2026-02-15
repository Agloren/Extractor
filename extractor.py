import streamlit as st
import fitz  # PyMuPDF
from anthropic import Anthropic
import os
from dotenv import load_dotenv

# Configuración de la página
st.set_page_config(page_title="AI Study Buddy", page_icon="📚")
load_dotenv()

# Inicializar cliente de Claude
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def extract_text(pdf_file):
    """Lee el PDF desde el cargador de Streamlit."""
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def get_claude_response(text):
    """Envía el texto a Claude."""
    with st.spinner("Claude está analizando el libro... 🧠"):
        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=2000,
            system="Eres un experto en aprendizaje acelerado. Extrae los conceptos clave en una tabla de Markdown.",
            messages=[{"role": "user", "content": text[:15000]}]
        )
        return message.content[0].text

# --- INTERFAZ DE USUARIO ---
st.title("🚀 Extractor de Conceptos con IA")
st.markdown("Sube tu PDF y deja que Claude resuma lo esencial por ti.")

uploaded_file = st.file_uploader("Elige un archivo PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Analizar Libro"):
        # 1. Extraer texto
        texto_completo = extract_text(uploaded_file)
        
        # 2. Obtener respuesta de la IA
        resultado = get_claude_response(texto_completo)
        
        # 3. Mostrar resultados
        st.subheader("📌 Conceptos Clave")
        st.markdown(resultado)
        
        # Botón para descargar el resumen
        st.download_button("Descargar Resumen (.md)", resultado, file_name="resumen_estudio.md")
