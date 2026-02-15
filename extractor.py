import os
import fitz  # PyMuPDF
from anthropic import Anthropic
from dotenv import load_dotenv

# Cargar configuración
load_dotenv()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def extract_text_from_pdf(pdf_path):
    """Extrae texto de un PDF página por página."""
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

def get_key_concepts(text):
    """Envía el texto a Claude para extraer conceptos clave."""
    
    system_prompt = (
        "Eres un experto en pedagogía y aprendizaje acelerado. "
        "Tu tarea es extraer los conceptos más importantes del texto proporcionado. "
        "Formatea la respuesta como una tabla de Markdown con tres columnas: "
        "Concepto, Definición Simplificada y Ejemplo/Analogía."
    )

    message = client.messages.create(
        model="claude-3-5-sonnet-20240620", # O el modelo más reciente
        max_tokens=2000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Extrae los conceptos clave de este texto:\n\n{text[:15000]}"} 
            # Limitamos caracteres por el contexto inicial
        ]
    )
    return message.content[0].text

def save_to_markdown(content, output_file="conceptos_clave.md"):
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# 📚 Resumen de Conceptos Clave\n\n")
        f.write(content)
    print(f"✅ Archivo guardado como {output_file}")

if __name__ == "__main__":
    archivo = "tu_libro.pdf" # Cambia esto por tu archivo
    print(f"📖 Procesando {archivo}...")
    
    raw_text = extract_text_from_pdf(archivo)
    conceptos = get_key_concepts(raw_text)
    save_to_markdown(conceptos)
