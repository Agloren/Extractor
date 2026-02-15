import streamlit as st
import fitz  # PyMuPDF
from anthropic import Anthropic
import json
import re
import base64
import io

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚", layout="wide")

st.markdown("""
<style>
.source-card {
    background: #f8f9fa; border-radius: 10px; padding: 12px 16px;
    margin: 6px 0; border-left: 4px solid #667eea;
    display: flex; align-items: center; justify-content: space-between;
}
.source-name { font-weight: bold; font-size: 14px; color: #333; }
.source-meta { font-size: 12px; color: #888; }
.chat-user {
    background: #e3f2fd; border-radius: 12px 12px 2px 12px;
    padding: 12px 16px; margin: 8px 0; margin-left: 15%;
    border: 1px solid #90caf9;
}
.chat-claude {
    background: #f3e5f5; border-radius: 12px 12px 12px 2px;
    padding: 12px 16px; margin: 8px 0; margin-right: 15%;
    border: 1px solid #ce93d8;
}
.chat-label-user { font-size: 11px; color: #1565c0; font-weight: bold; margin-bottom: 4px; }
.chat-label-claude { font-size: 11px; color: #6a1b9a; font-weight: bold; margin-bottom: 4px; }
.format-pill {
    display: inline-block; background: #667eea; color: white;
    border-radius: 20px; padding: 2px 10px; font-size: 11px; margin: 2px;
}
.stButton > button { border-radius: 10px; font-weight: bold; }
.big-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px; padding: 24px; color: white; margin-bottom: 20px;
}
</style>
""", unsafe_allow_html=True)

# ── CLIENTE API ────────────────────────────────────────────────────────────────
if "ANTHROPIC_API_KEY" in st.secrets:
    client = Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("⚠️ No se encontró la API Key en los Secrets de Streamlit.")
    st.stop()

# ── ESTADO DE SESIÓN ───────────────────────────────────────────────────────────
if "sources" not in st.session_state:
    st.session_state.sources = []          # Lista de {name, type, text, pages}
if "combined_text" not in st.session_state:
    st.session_state.combined_text = ""
if "chapters" not in st.session_state:
    st.session_state.chapters = []
if "chapter_summaries" not in st.session_state:
    st.session_state.chapter_summaries = {}
if "full_summary" not in st.session_state:
    st.session_state.full_summary = ""
if "analysis_done" not in st.session_state:
    st.session_state.analysis_done = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "doc_info" not in st.session_state:
    st.session_state.doc_info = {}

# ── EXTRACTORES POR FORMATO ────────────────────────────────────────────────────

def extract_pdf(file_bytes, name):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages, text = len(doc), ""
    for page in doc:
        t = page.get_text()
        if t.strip():
            text += t + "\n\n"
    return {"name": name, "type": "PDF", "text": text, "pages": pages, "icon": "📄"}

def extract_docx(file_bytes, name):
    import docx
    doc = docx.Document(io.BytesIO(file_bytes))
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    pages = max(1, len(text) // 2000)
    return {"name": name, "type": "Word", "text": text, "pages": pages, "icon": "📝"}

def extract_txt(file_bytes, name):
    text = file_bytes.decode("utf-8", errors="ignore")
    pages = max(1, len(text) // 2000)
    return {"name": name, "type": "Texto", "text": text, "pages": pages, "icon": "📃"}

def extract_pptx(file_bytes, name):
    from pptx import Presentation
    prs = Presentation(io.BytesIO(file_bytes))
    slides_text = []
    for i, slide in enumerate(prs.slides):
        slide_content = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_content.append(shape.text.strip())
        if slide_content:
            slides_text.append(f"[Diapositiva {i+1}]\n" + "\n".join(slide_content))
    text = "\n\n".join(slides_text)
    return {"name": name, "type": "PowerPoint", "text": text, "pages": len(prs.slides), "icon": "📊"}

def extract_audio(file_bytes, mime_type, name):
    """Transcribe audio enviándolo a Claude."""
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
    with st.spinner(f"🎙️ Transcribiendo {name}..."):
        r = client.messages.create(
            model="claude-sonnet-4-5-20250929", max_tokens=4000,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                {"type": "text", "text": "Transcribe este audio de forma completa y fiel. Devuelve solo la transcripción."}
            ]}]
        )
    text = r.content[0].text
    duration_est = max(1, len(text) // 800)
    return {"name": name, "type": "Audio", "text": text, "pages": duration_est, "icon": "🎙️"}

def process_file(uploaded_file):
    """Detecta el tipo y extrae el texto del archivo."""
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
    elif ext in ["mp3", "wav", "m4a", "mp4", "webm", "ogg"]:
        mime_map = {
            "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
            "mp4": "audio/mp4", "webm": "audio/webm", "ogg": "audio/ogg"
        }
        return extract_audio(file_bytes, mime_map.get(ext, "audio/mpeg"), name)
    else:
        st.warning(f"Formato .{ext} no soportado.")
        return None

# ── ANÁLISIS ───────────────────────────────────────────────────────────────────

def build_combined_text():
    """Combina el texto de todas las fuentes con separadores claros."""
    parts = []
    for src in st.session_state.sources:
        parts.append(f"\n{'='*60}\n📁 FUENTE: {src['name']} ({src['type']})\n{'='*60}\n{src['text']}")
    return "\n\n".join(parts)

def detect_chapters(combined_text, total_pages):
    sample = combined_text[:20000]
    num_sources = len(st.session_state.sources)
    prompt = f"""Analiza este contenido y detecta sus capítulos o secciones principales.
Proviene de {num_sources} fuente(s) distintas con {total_pages} páginas/unidades en total.

Contenido:
{sample}

Devuelve ÚNICAMENTE JSON válido (sin markdown):
{{
  "titulo_documento": "...",
  "tipo": "libro|articulo|informe|presentacion|mixto|otro",
  "capitulos": [
    {{"numero": 1, "titulo": "...", "pagina_inicio": 1, "pagina_fin": 10, "descripcion_breve": "...", "fuente": "nombre del archivo"}}
  ]
}}
Máximo 15 secciones. Si hay varias fuentes, crea una sección por fuente o por tema."""

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"```json|```", "", r.content[0].text).strip()
    return json.loads(raw)

def generate_full_summary(combined_text, doc_info, total_pages):
    if total_pages <= 5:
        depth, max_tok = "CONCISO (documento corto): idea principal, 5 conceptos, conclusión.", 800
    elif total_pages <= 20:
        depth, max_tok = "MODERADO: resumen ejecutivo, 10 conceptos, ideas secundarias, conclusiones.", 1500
    elif total_pages <= 80:
        depth, max_tok = "COMPLETO: resumen extenso, estructura, 15 conceptos, argumentos, conexiones.", 2500
    else:
        depth, max_tok = "EXHAUSTIVO: resumen profundo, tesis, 20+ conceptos, ideas por sección, aplicaciones.", 4000

    fuentes_str = ", ".join([f"{s['icon']} {s['name']}" for s in st.session_state.sources])

    prompt = f"""Analiza este contenido y genera un análisis {depth}

Título: {doc_info.get('titulo_documento', 'Contenido de estudio')}
Tipo: {doc_info.get('tipo', 'mixto')}
Fuentes: {fuentes_str}

Contenido:
{combined_text[:20000]}

Usa Markdown estructurado con headers, tablas y listas. Sé exhaustivo."""

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=max_tok,
        messages=[{"role": "user", "content": prompt}]
    )
    return r.content[0].text

def summarize_chapter(chapter, combined_text):
    fuente = chapter.get("fuente", "")
    # Buscar texto de la fuente específica si se indica
    chapter_text = combined_text
    for src in st.session_state.sources:
        if fuente and fuente.lower() in src["name"].lower():
            chapter_text = src["text"]
            break

    prompt = f"""Analiza en detalle esta sección del contenido.

Sección: {chapter.get('titulo', 'Sin título')}
Fuente: {fuente or 'general'}

Contenido:
{chapter_text[:10000]}

Genera en Markdown:

## 📋 Resumen de la sección
(3-5 frases esenciales)

## 🔑 Conceptos clave
| Concepto | Definición | Importancia |
|----------|-----------|-------------|
(5-10 filas)

## 💡 Ideas principales
(Lista detallada)

## 🔗 Conexiones con otras secciones
(Relaciones con el resto del contenido)

## ❓ Preguntas de comprensión
(3-5 preguntas para autoevaluarse)"""

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return r.content[0].text

def ask_question(question, chat_history):
    doc_title = st.session_state.doc_info.get("titulo_documento", "el documento")
    fuentes_str = "\n".join([f"- {s['icon']} {s['name']} ({s['type']})" for s in st.session_state.sources])

    messages = []
    for msg in chat_history[-8:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=1500,
        system=f"""Eres un tutor experto en el siguiente contenido de estudio.

Fuentes disponibles:
{fuentes_str}

Contenido completo:
---
{st.session_state.combined_text[:18000]}
---

Responde con precisión y cita siempre de qué fuente o sección viene la información.
Si preguntan algo no relacionado con el contenido, indícalo amablemente.
Usa Markdown cuando sea útil.""",
        messages=messages
    )
    return r.content[0].text

# ── INTERFAZ PRINCIPAL ─────────────────────────────────────────────────────────
st.markdown("""
<div class='big-header'>
    <h2 style='margin:0'>📚 AI Study Buddy</h2>
    <p style='margin:4px 0 0 0; opacity:0.85'>
        Sube PDFs, Word, PowerPoint, TXT, audios o escribe texto.
        Claude analizará todo junto y podrás hacer preguntas.
    </p>
</div>
""", unsafe_allow_html=True)

# Formatos soportados
st.markdown("""
<div style='margin-bottom:16px'>
<span class='format-pill'>📄 PDF</span>
<span class='format-pill'>📝 Word</span>
<span class='format-pill'>📊 PowerPoint</span>
<span class='format-pill'>📃 TXT / MD</span>
<span class='format-pill'>🎙️ MP3 / WAV / M4A</span>
<span class='format-pill'>🎬 MP4 / WEBM</span>
</div>
""", unsafe_allow_html=True)

# ── PANEL DE CARGA ─────────────────────────────────────────────────────────────
with st.expander("📥 Gestionar fuentes de contenido", expanded=not st.session_state.analysis_done):

    col_upload, col_text = st.columns([1, 1])

    with col_upload:
        st.markdown("**Subir archivos**")
        uploaded_files = st.file_uploader(
            "Selecciona uno o varios archivos",
            type=["pdf", "docx", "txt", "md", "pptx", "mp3", "wav", "m4a", "mp4", "webm", "ogg"],
            accept_multiple_files=True,
            help="Puedes subir múltiples archivos de diferentes formatos"
        )
        if uploaded_files:
            if st.button("➕ Añadir archivos a la sesión", use_container_width=True):
                existing_names = [s["name"] for s in st.session_state.sources]
                added = 0
                for f in uploaded_files:
                    if f.name not in existing_names:
                        with st.spinner(f"Procesando {f.name}..."):
                            source = process_file(f)
                        if source and source["text"].strip():
                            st.session_state.sources.append(source)
                            added += 1
                if added:
                    st.session_state.analysis_done = False
                    st.session_state.full_summary = ""
                    st.session_state.chapters = []
                    st.session_state.chapter_summaries = {}
                    st.success(f"✅ {added} fuente(s) añadidas.")
                    st.rerun()

    with col_text:
        st.markdown("**Pegar texto directamente**")
        text_name = st.text_input("Nombre para este texto:", placeholder="Ej: Mis apuntes de clase")
        text_input = st.text_area("Escribe o pega el texto:", height=150,
                                  placeholder="Pega aquí tus apuntes, artículos, notas...")
        if st.button("➕ Añadir texto", use_container_width=True):
            if text_input.strip() and text_name.strip():
                existing_names = [s["name"] for s in st.session_state.sources]
                if text_name not in existing_names:
                    source = {
                        "name": text_name,
                        "type": "Texto",
                        "text": text_input,
                        "pages": max(1, len(text_input) // 2000),
                        "icon": "📃"
                    }
                    st.session_state.sources.append(source)
                    st.session_state.analysis_done = False
                    st.success(f"✅ Texto '{text_name}' añadido.")
                    st.rerun()
            else:
                st.warning("Escribe un nombre y algún contenido.")

    # Lista de fuentes cargadas
    if st.session_state.sources:
        st.markdown("---")
        st.markdown(f"**📚 Fuentes cargadas ({len(st.session_state.sources)})**")

        total_pages = sum(s["pages"] for s in st.session_state.sources)
        total_chars = sum(len(s["text"]) for s in st.session_state.sources)

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("📁 Fuentes", len(st.session_state.sources))
        col_m2.metric("📄 Páginas totales", total_pages)
        col_m3.metric("📝 Caracteres", f"{total_chars:,}")

        for i, src in enumerate(st.session_state.sources):
            col_s, col_del = st.columns([5, 1])
            with col_s:
                st.markdown(
                    f"<div class='source-card'>"
                    f"<div><span class='source-name'>{src['icon']} {src['name']}</span>"
                    f"<span class='source-meta'> · {src['type']} · {src['pages']} págs · {len(src['text']):,} chars</span></div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with col_del:
                if st.button("🗑️", key=f"del_{i}", help="Eliminar esta fuente"):
                    st.session_state.sources.pop(i)
                    st.session_state.analysis_done = False
                    st.rerun()

        st.markdown("")
        col_an, col_reset = st.columns([3, 1])
        with col_an:
            if st.button("⚡ Analizar todo el contenido", use_container_width=True):
                combined = build_combined_text()
                st.session_state.combined_text = combined

                with st.spinner("🔍 Detectando estructura y capítulos..."):
                    doc_info = detect_chapters(combined, total_pages)
                    st.session_state.chapters = doc_info.get("capitulos", [])
                    st.session_state.doc_info = doc_info

                with st.spinner("📝 Generando resumen general..."):
                    st.session_state.full_summary = generate_full_summary(combined, doc_info, total_pages)

                st.session_state.analysis_done = True
                st.session_state.chapter_summaries = {}
                st.session_state.chat_history = []
                st.success(f"✅ Análisis listo. {len(st.session_state.chapters)} secciones detectadas.")
                st.rerun()

        with col_reset:
            if st.button("🔄 Limpiar todo", use_container_width=True):
                for k in ["sources", "combined_text", "chapters", "chapter_summaries",
                          "full_summary", "analysis_done", "chat_history", "doc_info"]:
                    st.session_state[k] = [] if k in ["sources", "chapters", "chat_history"] else \
                                          {} if k in ["chapter_summaries", "doc_info"] else \
                                          "" if k in ["combined_text", "full_summary"] else False
                st.rerun()

# ── CONTENIDO ANALIZADO ────────────────────────────────────────────────────────
if st.session_state.analysis_done:
    doc_info = st.session_state.doc_info
    doc_title = doc_info.get("titulo_documento", "Contenido de estudio")

    st.subheader(f"📖 {doc_title}")
    fuentes_icons = " · ".join([f"{s['icon']} {s['name']}" for s in st.session_state.sources])
    st.caption(fuentes_icons)
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📋 Resumen general", "📑 Secciones y capítulos", "💬 Preguntar al contenido"])

    # ── TAB 1: RESUMEN ─────────────────────────────────────────────────────────
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
            st.info("No se detectaron secciones.")
        else:
            st.markdown("### 📌 Estructura del contenido")
            for ch in chapters:
                fuente_badge = f" `{ch.get('fuente', '')}`" if ch.get("fuente") else ""
                st.markdown(f"**{ch['numero']}.** {ch['titulo']}{fuente_badge}")
                if ch.get("descripcion_breve"):
                    st.caption(ch["descripcion_breve"])

            st.markdown("---")
            st.markdown("### 🔍 Análisis por sección")

            chapter_names = [f"{ch['numero']}. {ch['titulo']}" for ch in chapters]
            selected = st.selectbox("Selecciona una sección:", chapter_names)
            ch_idx = chapter_names.index(selected)
            chapter = chapters[ch_idx]
            ch_key = f"ch_{ch_idx}"

            col_btn, col_dl = st.columns([3, 1])
            with col_btn:
                if st.button(f"⚡ Analizar: {chapter['titulo']}", use_container_width=True):
                    with st.spinner(f"Analizando sección {chapter['numero']}..."):
                        summary = summarize_chapter(chapter, st.session_state.combined_text)
                        st.session_state.chapter_summaries[ch_key] = summary
                    st.rerun()

            if ch_key in st.session_state.chapter_summaries:
                with col_dl:
                    st.download_button(
                        "⬇️ Descargar",
                        st.session_state.chapter_summaries[ch_key],
                        file_name=f"seccion_{chapter['numero']}.md",
                        mime="text/markdown"
                    )
                st.markdown(st.session_state.chapter_summaries[ch_key])

                analyzed_keys = list(st.session_state.chapter_summaries.keys())
                if len(analyzed_keys) > 1:
                    with st.expander(f"📚 Ver otras {len(analyzed_keys)-1} secciones analizadas"):
                        for k in analyzed_keys:
                            if k != ch_key:
                                idx = int(k.split("_")[1])
                                with st.expander(f"📄 {chapters[idx]['numero']}. {chapters[idx]['titulo']}"):
                                    st.markdown(st.session_state.chapter_summaries[k])
            else:
                st.info("👆 Pulsa el botón para analizar esta sección en detalle.")

    # ── TAB 3: CHAT ────────────────────────────────────────────────────────────
    with tab3:
        st.markdown("### 💬 Pregunta lo que quieras sobre el contenido")
        st.caption(f"Claude tiene acceso a todas las fuentes: {fuentes_icons}")

        # ── INPUT SIEMPRE VISIBLE ARRIBA ──
        pregunta_input = st.text_input(
            "Tu pregunta:",
            key="pregunta_input",
            placeholder="Ej: ¿Cuál es la idea principal? ¿Explícame el capítulo 2...",
        )
        col_env, col_clear2 = st.columns([3, 1])
        with col_env:
            enviar = st.button("📨 Enviar pregunta", key="btn_enviar",
                               use_container_width=True, type="primary",
                               disabled=not bool(pregunta_input and pregunta_input.strip()))
        with col_clear2:
            if st.button("🗑️ Limpiar chat", key="btn_clear", use_container_width=True):
                st.session_state.chat_history = []
                st.rerun()

        if enviar and pregunta_input and pregunta_input.strip():
            texto_pregunta = pregunta_input.strip()
            st.session_state.chat_history.append({"role": "user", "content": texto_pregunta})
            with st.spinner("Claude está pensando..."):
                respuesta = ask_question(texto_pregunta, st.session_state.chat_history[:-1])
            st.session_state.chat_history.append({"role": "assistant", "content": respuesta})
            st.rerun()

        st.markdown("---")

        # ── SUGERENCIAS (solo si no hay historial) ──
        if not st.session_state.chat_history:
            st.markdown("**💡 Preguntas sugeridas para empezar:**")
            sugerencias = [
                "¿Cuál es la idea principal de todo el contenido?",
                "¿Qué conceptos son los más importantes?",
                "Compara las ideas de las diferentes fuentes",
                "¿Qué aplicaciones prácticas tiene este contenido?",
                "Hazme un test de 5 preguntas sobre todo",
                "¿Qué debo repasar más en profundidad?"
            ]
            cols = st.columns(2)
            for i, sug in enumerate(sugerencias):
                with cols[i % 2]:
                    if st.button(sug, key=f"sug_{i}", use_container_width=True):
                        st.session_state.chat_history.append({"role": "user", "content": sug})
                        with st.spinner("Claude está pensando..."):
                            respuesta = ask_question(sug, st.session_state.chat_history[:-1])
                        st.session_state.chat_history.append({"role": "assistant", "content": respuesta})
                        st.rerun()

        # ── HISTORIAL ──
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(
                    f"<div class='chat-user'><div class='chat-label-user'>👤 Tú</div>{msg['content']}</div>",
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"<div class='chat-claude'><div class='chat-label-claude'>🤖 Claude</div>{msg['content']}</div>",
                    unsafe_allow_html=True
                )

        # ── DESCARGAR CONVERSACIÓN ──
        if st.session_state.chat_history:
            chat_md = "\n\n".join([
                f"**{'Tú' if m['role']=='user' else 'Claude'}:** {m['content']}"
                for m in st.session_state.chat_history
            ])
            st.download_button("⬇️ Descargar conversación", chat_md, "conversacion.md", "text/markdown")

# ── PIE DE PÁGINA ──────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("📚 AI Study Buddy · Impulsado por Claude · Multi-formato · Multi-fuente")
