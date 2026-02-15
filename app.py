import streamlit as st
import fitz  # PyMuPDF
from anthropic import Anthropic
import json
import re

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚", layout="wide")

st.markdown("""
<style>
.chapter-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-radius: 12px; padding: 20px; color: white;
    margin: 10px 0; border-left: 4px solid #e94560;
}
.chapter-title { font-size: 18px; font-weight: bold; color: #e94560; margin-bottom: 8px; }
.metric-box {
    background: #f8f9fa; border-radius: 10px;
    padding: 15px; text-align: center; border: 1px solid #dee2e6;
}
.chat-user {
    background: #e3f2fd; border-radius: 12px 12px 2px 12px;
    padding: 12px 16px; margin: 8px 0; margin-left: 20%;
    border: 1px solid #90caf9;
}
.chat-claude {
    background: #f3e5f5; border-radius: 12px 12px 12px 2px;
    padding: 12px 16px; margin: 8px 0; margin-right: 20%;
    border: 1px solid #ce93d8;
}
.chat-label-user { font-size: 11px; color: #1565c0; font-weight: bold; margin-bottom: 4px; }
.chat-label-claude { font-size: 11px; color: #6a1b9a; font-weight: bold; margin-bottom: 4px; }
.stButton > button { border-radius: 10px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ── CLIENTE API ────────────────────────────────────────────────────────────────
if "ANTHROPIC_API_KEY" in st.secrets:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("⚠️ No se encontró la API Key en los Secrets de Streamlit.")
    st.stop()

# ── ESTADO DE SESIÓN ───────────────────────────────────────────────────────────
defaults = {
    "pdf_text": "",
    "num_pages": 0,
    "filename": "",
    "chapters": [],
    "chapter_summaries": {},
    "full_summary": "",
    "analysis_done": False,
    "chat_history": [],
    "active_tab": 0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── EXTRACCIÓN DE TEXTO ────────────────────────────────────────────────────────
def extract_text(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    pages_text = []
    for i, page in enumerate(doc):
        t = page.get_text()
        if t.strip():
            pages_text.append({"page": i + 1, "text": t})
    return pages_text, len(doc)

def pages_to_full_text(pages_text):
    return "\n\n".join([f"[Página {p['page']}]\n{p['text']}" for p in pages_text])

# ── DETECCIÓN DE CAPÍTULOS ─────────────────────────────────────────────────────
def detect_chapters(full_text, num_pages):
    """Usa Claude para detectar capítulos o secciones del documento."""
    sample = full_text[:20000]
    prompt = f"""Analiza este documento y detecta sus capítulos o secciones principales.

Texto (primeras páginas):
{sample}

El documento tiene {num_pages} páginas en total.

Devuelve ÚNICAMENTE un JSON válido (sin markdown) con esta estructura:
{{
  "titulo_documento": "...",
  "tipo": "libro|articulo|informe|manual|otro",
  "capitulos": [
    {{"numero": 1, "titulo": "...", "pagina_inicio": 1, "pagina_fin": 10, "descripcion_breve": "..."}}
  ]
}}

Si no hay capítulos claros, crea divisiones lógicas por bloques temáticos.
Máximo 15 capítulos/secciones."""

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"```json|```", "", r.content[0].text).strip()
    return json.loads(raw)

# ── RESUMEN GENERAL ────────────────────────────────────────────────────────────
def generate_full_summary(full_text, doc_info, num_pages):
    """Genera un resumen ejecutivo completo proporcional al tamaño."""
    if num_pages <= 5:
        depth = "CONCISO (el documento es muy corto): idea principal, 5 conceptos clave, conclusión."
        max_tok = 800
    elif num_pages <= 20:
        depth = "MODERADO: resumen ejecutivo, 10 conceptos clave, ideas secundarias, conclusiones."
        max_tok = 1500
    elif num_pages <= 80:
        depth = "COMPLETO: resumen extenso, estructura, 15 conceptos, argumentos principales, conexiones entre ideas, conclusiones."
        max_tok = 2500
    else:
        depth = "EXHAUSTIVO: resumen profundo, tesis central del autor, mapa de conceptos (20+), ideas por sección, aplicaciones prácticas, valoración crítica."
        max_tok = 4000

    prompt = f"""Analiza este documento y genera un análisis {depth}

Título: {doc_info.get('titulo_documento', 'Documento')}
Tipo: {doc_info.get('tipo', 'documento')}
Páginas: {num_pages}

Contenido:
{full_text[:20000]}

Usa formato Markdown bien estructurado con headers, tablas y listas.
Sé exhaustivo y útil para el estudio."""

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=max_tok,
        messages=[{"role": "user", "content": prompt}]
    )
    return r.content[0].text

# ── RESUMEN POR CAPÍTULO ───────────────────────────────────────────────────────
def summarize_chapter(chapter, full_text, pages_text):
    """Genera un análisis detallado de un capítulo específico."""
    # Extraer texto del capítulo según páginas
    p_start = chapter.get("pagina_inicio", 1)
    p_end = chapter.get("pagina_fin", p_start + 5)
    chapter_pages = [p for p in pages_text if p_start <= p["page"] <= p_end]
    chapter_text = "\n".join([p["text"] for p in chapter_pages]) if chapter_pages else full_text[:8000]

    prompt = f"""Analiza en detalle este capítulo/sección del documento.

Capítulo: {chapter.get('titulo', 'Sin título')} (págs. {p_start}-{p_end})

Contenido:
{chapter_text[:10000]}

Genera un análisis completo en Markdown con:
## 📋 Resumen del capítulo
(3-5 frases que capturen la esencia)

## 🔑 Conceptos clave
| Concepto | Definición | Importancia |
|----------|-----------|-------------|
(5-10 conceptos del capítulo)

## 💡 Ideas principales
(Lista detallada de las ideas más importantes)

## 🔗 Conexiones
(Cómo se relaciona con el resto del documento o con conocimiento previo)

## ❓ Preguntas de reflexión
(3 preguntas para comprobar la comprensión del capítulo)"""

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return r.content[0].text

# ── CHAT SOBRE EL CONTENIDO ────────────────────────────────────────────────────
def ask_question(question, full_text, chat_history, doc_title):
    """Responde preguntas sobre el documento manteniendo contexto de conversación."""
    # Construir historial para la API
    messages = []

    # Añadir historial previo (últimas 6 interacciones para no exceder límite)
    for msg in chat_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Añadir pregunta actual
    messages.append({"role": "user", "content": question})

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        system=f"""Eres un tutor experto en el documento "{doc_title}".
Tienes acceso completo al contenido del documento:

---
{full_text[:18000]}
---

Responde preguntas de forma clara, precisa y didáctica.
Cita siempre de qué parte del documento sacas la información.
Si la pregunta no está relacionada con el documento, indícalo amablemente.
Usa formato Markdown cuando sea útil.""",
        messages=messages
    )
    return r.content[0].text

# ── INTERFAZ PRINCIPAL ─────────────────────────────────────────────────────────
st.title("📚 AI Study Buddy")
st.markdown("Análisis profundo por capítulos + chat interactivo sobre el contenido.")
st.markdown("---")

# ── CARGA DE PDF ───────────────────────────────────────────────────────────────
with st.expander("📥 Cargar documento PDF", expanded=not st.session_state.analysis_done):
    uploaded_file = st.file_uploader("Selecciona tu PDF", type="pdf")

    if uploaded_file:
        if uploaded_file.name != st.session_state.filename:
            # Nuevo archivo — resetear estado
            for k, v in defaults.items():
                st.session_state[k] = v

        pages_text, num_pages = extract_text(uploaded_file)
        full_text = pages_to_full_text(pages_text)
        st.session_state.pdf_text = full_text
        st.session_state.num_pages = num_pages
        st.session_state.filename = uploaded_file.name
        st.session_state.pages_text = pages_text

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📄 Páginas", num_pages)
        with col2:
            st.metric("📝 Caracteres", f"{len(full_text):,}")
        with col3:
            tipo = "📄 Artículo" if num_pages <= 5 else "📑 Medio" if num_pages <= 20 else "📘 Extenso" if num_pages <= 80 else "📚 Libro"
            st.metric("📊 Tipo", tipo)

        st.markdown("")
        if st.button("⚡ Analizar documento completo", use_container_width=True):
            if not full_text.strip():
                st.warning("⚠️ No se pudo extraer texto.")
            else:
                # 1. Detectar capítulos
                with st.spinner("🔍 Detectando capítulos y estructura..."):
                    doc_info = detect_chapters(full_text, num_pages)
                    st.session_state.chapters = doc_info.get("capitulos", [])
                    st.session_state.doc_info = doc_info

                # 2. Resumen general
                with st.spinner("📝 Generando resumen general..."):
                    st.session_state.full_summary = generate_full_summary(
                        full_text, doc_info, num_pages
                    )

                st.session_state.analysis_done = True
                st.success(f"✅ Análisis listo. {len(st.session_state.chapters)} capítulos detectados.")
                st.rerun()

# ── CONTENIDO PRINCIPAL ────────────────────────────────────────────────────────
if st.session_state.analysis_done:
    doc_info = st.session_state.get("doc_info", {})
    doc_title = doc_info.get("titulo_documento", st.session_state.filename)

    st.subheader(f"📖 {doc_title}")
    st.caption(f"{st.session_state.num_pages} páginas · {doc_info.get('tipo', 'documento').capitalize()}")
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📋 Resumen general", "📑 Capítulos", "💬 Preguntar al libro"])

    # ── TAB 1: RESUMEN GENERAL ─────────────────────────────────────────────────
    with tab1:
        st.markdown(st.session_state.full_summary)
        st.download_button(
            "⬇️ Descargar resumen completo",
            st.session_state.full_summary,
            file_name="resumen_completo.md",
            mime="text/markdown"
        )

    # ── TAB 2: CAPÍTULOS ───────────────────────────────────────────────────────
    with tab2:
        chapters = st.session_state.chapters

        if not chapters:
            st.info("No se detectaron capítulos en este documento.")
        else:
            # Índice de capítulos
            st.markdown("### 📌 Índice")
            for ch in chapters:
                st.markdown(f"**{ch['numero']}.** {ch['titulo']} *(págs. {ch.get('pagina_inicio','?')}-{ch.get('pagina_fin','?')})*")
                if ch.get("descripcion_breve"):
                    st.caption(ch["descripcion_breve"])

            st.markdown("---")
            st.markdown("### 🔍 Análisis por capítulo")

            # Selector de capítulo
            chapter_names = [f"{ch['numero']}. {ch['titulo']}" for ch in chapters]
            selected = st.selectbox("Selecciona un capítulo:", chapter_names)
            ch_idx = chapter_names.index(selected)
            chapter = chapters[ch_idx]
            ch_key = f"ch_{ch_idx}"

            col_an, col_dl = st.columns([3, 1])
            with col_an:
                if st.button(f"⚡ Analizar: {chapter['titulo']}", use_container_width=True):
                    with st.spinner(f"Analizando capítulo {chapter['numero']}..."):
                        summary = summarize_chapter(
                            chapter,
                            st.session_state.pdf_text,
                            st.session_state.get("pages_text", [])
                        )
                        st.session_state.chapter_summaries[ch_key] = summary
                        st.rerun()

            # Mostrar análisis si existe
            if ch_key in st.session_state.chapter_summaries:
                with col_dl:
                    st.download_button(
                        "⬇️ Descargar",
                        st.session_state.chapter_summaries[ch_key],
                        file_name=f"capitulo_{chapter['numero']}.md",
                        mime="text/markdown"
                    )
                st.markdown(st.session_state.chapter_summaries[ch_key])

                # Capítulos ya analizados
                analyzed = [k for k in st.session_state.chapter_summaries]
                if len(analyzed) > 1:
                    with st.expander(f"📚 Ver otros {len(analyzed)-1} capítulos ya analizados"):
                        for k in analyzed:
                            if k != ch_key:
                                idx = int(k.split("_")[1])
                                ch_name = chapters[idx]["titulo"]
                                with st.expander(f"📄 {chapters[idx]['numero']}. {ch_name}"):
                                    st.markdown(st.session_state.chapter_summaries[k])
            else:
                st.info("👆 Pulsa el botón para analizar este capítulo en detalle.")

    # ── TAB 3: CHAT ────────────────────────────────────────────────────────────
    with tab3:
        st.markdown("### 💬 Pregunta lo que quieras sobre el documento")
        st.caption("Claude tiene acceso al contenido completo y recuerda el contexto de la conversación.")

        # Mostrar historial del chat
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(f"<div class='chat-user'><div class='chat-label-user'>👤 Tú</div>{msg['content']}</div>",
                            unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='chat-claude'><div class='chat-label-claude'>🤖 Claude</div>{msg['content']}</div>",
                            unsafe_allow_html=True)

        # Sugerencias rápidas
        if not st.session_state.chat_history:
            st.markdown("**💡 Preguntas sugeridas:**")
            sugerencias = [
                "¿Cuál es la idea principal del documento?",
                "¿Qué conceptos son los más importantes?",
                "Explícame el capítulo más complejo",
                "¿Qué aplicaciones prácticas tiene este contenido?",
                "Hazme un test de 5 preguntas"
            ]
            cols = st.columns(2)
            for i, sug in enumerate(sugerencias):
                with cols[i % 2]:
                    if st.button(sug, key=f"sug_{i}", use_container_width=True):
                        st.session_state.chat_history.append({"role": "user", "content": sug})
                        with st.spinner("Claude está pensando..."):
                            respuesta = ask_question(
                                sug,
                                st.session_state.pdf_text,
                                st.session_state.chat_history[:-1],
                                doc_title
                            )
                        st.session_state.chat_history.append({"role": "assistant", "content": respuesta})
                        st.rerun()

        # Input de pregunta libre
        st.markdown("")
        pregunta = st.chat_input("Escribe tu pregunta sobre el documento...")
        if pregunta:
            st.session_state.chat_history.append({"role": "user", "content": pregunta})
            with st.spinner("Claude está pensando..."):
                respuesta = ask_question(
                    pregunta,
                    st.session_state.pdf_text,
                    st.session_state.chat_history[:-1],
                    doc_title
                )
            st.session_state.chat_history.append({"role": "assistant", "content": respuesta})
            st.rerun()

        # Botón limpiar chat
        if st.session_state.chat_history:
            if st.button("🗑️ Limpiar conversación"):
                st.session_state.chat_history = []
                st.rerun()

# ── PIE DE PÁGINA ──────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("📚 AI Study Buddy · Impulsado por Claude · Análisis inteligente de documentos")
