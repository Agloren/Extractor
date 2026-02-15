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

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI Study Buddy", page_icon="📚", layout="wide")

st.markdown("""
<style>
.source-card {
    background: #f8f9fa; border-radius: 10px; padding: 12px 16px;
    margin: 6px 0; border-left: 4px solid #667eea;
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
if "sources"           not in st.session_state: st.session_state.sources = []
if "combined_text"     not in st.session_state: st.session_state.combined_text = ""
if "chapters"          not in st.session_state: st.session_state.chapters = []
if "chapter_summaries" not in st.session_state: st.session_state.chapter_summaries = {}
if "full_summary"      not in st.session_state: st.session_state.full_summary = ""
if "analysis_done"     not in st.session_state: st.session_state.analysis_done = False
if "chat_history"      not in st.session_state: st.session_state.chat_history = []
if "doc_info"          not in st.session_state: st.session_state.doc_info = {}

# ── EXTRACTORES ────────────────────────────────────────────────────────────────
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

def extract_audio(file_bytes, mime_type, name):
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
    with st.spinner(f"🎙️ Transcribiendo {name}..."):
        r = client.messages.create(
            model="claude-sonnet-4-5-20250929", max_tokens=4000,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                {"type": "text", "text": "Transcribe este audio completamente. Solo la transcripción."}
            ]}]
        )
    text = r.content[0].text
    return {"name": name, "type": "Audio", "text": text, "pages": max(1, len(text)//800), "icon": "🎙️"}

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
    elif ext in ["mp3", "wav", "m4a", "mp4", "webm", "ogg"]:
        mime_map = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
                    "mp4": "audio/mp4", "webm": "audio/webm", "ogg": "audio/ogg"}
        return extract_audio(file_bytes, mime_map.get(ext, "audio/mpeg"), name)
    else:
        st.warning(f"Formato .{ext} no soportado.")
        return None

# ── ANÁLISIS ───────────────────────────────────────────────────────────────────
def build_combined_text():
    return "\n\n".join([
        f"\n{'='*60}\n📁 FUENTE: {s['name']} ({s['type']})\n{'='*60}\n{s['text']}"
        for s in st.session_state.sources
    ])

def detect_chapters(combined_text, total_pages):
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=2000,
        messages=[{"role": "user", "content": (
            "Detecta capítulos o secciones de este contenido.\n"
            "Devuelve SOLO JSON válido (sin markdown):\n"
            '{"titulo_documento":"...","tipo":"libro|articulo|informe|presentacion|mixto|otro",'
            '"capitulos":[{"numero":1,"titulo":"...","pagina_inicio":1,"pagina_fin":10,"descripcion_breve":"...","fuente":"..."}]}\n'
            f"Máximo 15 secciones. Contenido ({total_pages} págs):\n{combined_text[:20000]}"
        )}]
    )
    return json.loads(re.sub(r"```json|```", "", r.content[0].text).strip())

def generate_full_summary(combined_text, doc_info, total_pages):
    if total_pages <= 5:
        depth, max_tok = "CONCISO: idea principal, 5 conceptos, conclusión.", 800
    elif total_pages <= 20:
        depth, max_tok = "MODERADO: resumen, 10 conceptos, ideas, conclusiones.", 1500
    elif total_pages <= 80:
        depth, max_tok = "COMPLETO: resumen extenso, 15 conceptos, argumentos, conexiones.", 2500
    else:
        depth, max_tok = "EXHAUSTIVO: resumen profundo, tesis, 20+ conceptos, aplicaciones.", 4000
    fuentes = ", ".join([f"{s['icon']} {s['name']}" for s in st.session_state.sources])
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=max_tok,
        messages=[{"role": "user", "content": (
            f"Analiza y genera un análisis {depth}\n"
            f"Título: {doc_info.get('titulo_documento','Contenido')} | Fuentes: {fuentes}\n"
            f"Contenido: {combined_text[:20000]}\n"
            "Usa Markdown estructurado con headers, tablas y listas."
        )}]
    )
    return r.content[0].text

def summarize_chapter(chapter, combined_text):
    fuente = chapter.get("fuente", "")
    chapter_text = combined_text
    for src in st.session_state.sources:
        if fuente and fuente.lower() in src["name"].lower():
            chapter_text = src["text"]
            break
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=2000,
        messages=[{"role": "user", "content": (
            f"Analiza en detalle: {chapter.get('titulo','Sin título')}\n"
            f"Fuente: {fuente or 'general'}\nContenido: {chapter_text[:10000]}\n\n"
            "Genera en Markdown:\n"
            "## 📋 Resumen de la sección\n"
            "## 🔑 Conceptos clave (tabla: Concepto | Definición | Importancia)\n"
            "## 💡 Ideas principales\n"
            "## 🔗 Conexiones con otras secciones\n"
            "## ❓ Preguntas de comprensión (3-5)"
        )}]
    )
    return r.content[0].text

def ask_question(question, chat_history):
    fuentes_str = "\n".join([f"- {s['icon']} {s['name']} ({s['type']})" for s in st.session_state.sources])
    messages = [{"role": m["role"], "content": m["content"]} for m in chat_history[-8:]]
    messages.append({"role": "user", "content": question})
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=1500,
        system=(
            "Eres tutor experto en este contenido.\n"
            f"Fuentes: {fuentes_str}\n"
            f"Contenido: {st.session_state.combined_text[:18000]}\n"
            "Cita siempre de qué fuente viene la info. Usa Markdown."
        ),
        messages=messages
    )
    return r.content[0].text

# ── PRESENTACIÓN PPT ───────────────────────────────────────────────────────────
def generate_presentation_data(combined_text, doc_info, num_slides):
    """Claude genera la estructura JSON de la presentación."""
    doc_title = doc_info.get("titulo_documento", "Presentación")
    fuentes = ", ".join([f"{s['icon']} {s['name']}" for s in st.session_state.sources])
    r = client.messages.create(
        model="claude-sonnet-4-5-20250929", max_tokens=4000,
        messages=[{"role": "user", "content": (
            f"Eres un diseñador experto en presentaciones educativas tipo clase maestra.\n"
            f"Analiza este contenido y genera una presentación de {num_slides} diapositivas.\n"
            f"Título: {doc_title} | Fuentes: {fuentes}\n\n"
            f"Contenido:\n{combined_text[:15000]}\n\n"
            "Devuelve ÚNICAMENTE JSON válido (sin markdown) con esta estructura:\n"
            '{"titulo":"...","subtitulo":"...","autor":"AI Study Buddy",'
            '"color_primario":"1E2761","color_secundario":"CADCFC","color_acento":"F96167",'
            '"slides":['
            '{"tipo":"titulo","titulo":"...","subtitulo":"..."},'
            '{"tipo":"concepto","titulo":"...","puntos":["punto1","punto2","punto3"],"nota_orador":"..."},'
            '{"tipo":"cita","titulo":"...","cita":"frase clave impactante","fuente":"origen"},'
            '{"tipo":"tabla","titulo":"...","cabeceras":["Col1","Col2","Col3"],"filas":[["a","b","c"]],"nota_orador":"..."},'
            '{"tipo":"conclusion","titulo":"Conclusiones","puntos":["c1","c2","c3"],"mensaje_final":"..."}'
            "]}\n"
            f"Crea exactamente {num_slides} slides variando tipos para una clase dinámica.\n"
            "Tipos disponibles: titulo, concepto, cita, tabla, conclusion"
        )}]
    )
    raw = re.sub(r"```json|```", "", r.content[0].text).strip()
    return json.loads(raw)


def build_pptx_file(prs_data):
    """Genera el .pptx con Node.js/PptxGenJS."""
    c1  = prs_data.get("color_primario",  "1E2761")
    c2  = prs_data.get("color_secundario","CADCFC")
    acc = prs_data.get("color_acento",    "F96167")

    lines = [
        "const pptxgen = require('pptxgenjs');",
        "const prs = new pptxgen();",
        "prs.layout = 'LAYOUT_16x9';",
        f"prs.title = {json.dumps(prs_data.get('titulo','Presentación'))};",
        "",
    ]

    for sd in prs_data.get("slides", []):
        tipo   = sd.get("tipo", "concepto")
        titulo = json.dumps(sd.get("titulo", ""))

        lines.append("{")
        lines.append("  const s = prs.addSlide();")

        if tipo == "titulo":
            sub = json.dumps(sd.get("subtitulo", ""))
            aut = json.dumps(prs_data.get("autor", ""))
            lines += [
                f"  s.background = {{ color: '{c1}' }};",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:0, w:0.18, h:5.625, fill:{{color:'{acc}'}}, line:{{color:'{acc}'}} }});",
                f"  s.addText({titulo}, {{ x:0.4, y:1.5, w:9.2, h:1.3, fontSize:44, bold:true, color:'FFFFFF', fontFace:'Calibri', align:'center', margin:0 }});",
                f"  s.addText({sub}, {{ x:0.4, y:3.0, w:9.2, h:0.9, fontSize:20, color:'{c2}', fontFace:'Calibri', align:'center', margin:0 }});",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:5.2, w:10, h:0.425, fill:{{color:'{acc}'}}, line:{{color:'{acc}'}} }});",
                f"  s.addText({aut}, {{ x:0.4, y:5.22, w:9.2, h:0.38, fontSize:12, color:'FFFFFF', fontFace:'Calibri', align:'center', margin:0 }});",
            ]

        elif tipo == "cita":
            cita   = json.dumps("\u201c" + sd.get("cita","") + "\u201d")
            fuente = json.dumps("— " + sd.get("fuente",""))
            lines += [
                f"  s.background = {{ color: '{c1}' }};",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:0, w:10, h:1.1, fill:{{color:'{acc}'}}, line:{{color:'{acc}'}} }});",
                f"  s.addText({titulo}, {{ x:0.4, y:0.15, w:9.2, h:0.8, fontSize:24, bold:true, color:'FFFFFF', fontFace:'Calibri', margin:0 }});",
                f"  s.addText({cita}, {{ x:0.8, y:1.4, w:8.4, h:2.8, fontSize:22, italic:true, color:'{c2}', fontFace:'Georgia', align:'center', valign:'middle', margin:0 }});",
                f"  s.addShape(prs.shapes.LINE, {{ x:3.5, y:4.4, w:3, h:0, line:{{color:'{acc}', width:2}} }});",
                f"  s.addText({fuente}, {{ x:0.4, y:4.55, w:9.2, h:0.5, fontSize:14, color:'{c2}', fontFace:'Calibri', align:'center', margin:0 }});",
            ]

        elif tipo == "tabla":
            cabeceras = sd.get("cabeceras", [])
            filas     = sd.get("filas", [])
            # Build table rows as JS
            header_parts = []
            for h in cabeceras:
                header_parts.append(
                    "{ text: " + json.dumps(str(h)) +
                    ", options: { bold:true, color:'FFFFFF', fill:{color:'" + c1 + "'}, fontSize:13 } }"
                )
            header_row = "  [" + ", ".join(header_parts) + "]"
            data_rows = []
            for fila in filas:
                cell_parts = []
                for c in fila:
                    cell_parts.append(
                        "{ text: " + json.dumps(str(c)) +
                        ", options: { fontSize:12, color:'333333' } }"
                    )
                data_rows.append("  [" + ", ".join(cell_parts) + "]")
            all_rows = ",\n".join([header_row] + data_rows)
            nota = sd.get("nota_orador", "")
            lines += [
                f"  s.background = {{ color: 'F8F9FA' }};",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:0, w:10, h:1.1, fill:{{color:'{c1}'}}, line:{{color:'{c1}'}} }});",
                f"  s.addText({titulo}, {{ x:0.4, y:0.15, w:9.2, h:0.8, fontSize:26, bold:true, color:'FFFFFF', fontFace:'Calibri', margin:0 }});",
                f"  s.addTable([\n{all_rows}\n  ], {{ x:0.4, y:1.3, w:9.2, colW:[3.0,3.0,3.2], border:{{pt:1, color:'DDDDDD'}}, fill:{{color:'FFFFFF'}}, rowH:0.45 }});",
            ]
            if nota:
                lines.append(f"  s.addNotes({json.dumps(nota)});")

        elif tipo == "conclusion":
            puntos = sd.get("puntos", [])
            msg    = json.dumps(sd.get("mensaje_final", ""))
            bullet_parts = []
            for p in puntos:
                bullet_parts.append(
                    "{ text: " + json.dumps(str(p)) +
                    ", options: { bullet:true, breakLine:true, fontSize:17, color:'333333' } }"
                )
            bullets_js = ", ".join(bullet_parts)
            lines += [
                f"  s.background = {{ color: 'FFFFFF' }};",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:0, w:10, h:1.1, fill:{{color:'{c1}'}}, line:{{color:'{c1}'}} }});",
                f"  s.addText({titulo}, {{ x:0.4, y:0.15, w:9.2, h:0.8, fontSize:26, bold:true, color:'FFFFFF', fontFace:'Calibri', margin:0 }});",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0.4, y:1.25, w:0.08, h:3.2, fill:{{color:'{acc}'}}, line:{{color:'{acc}'}} }});",
                f"  s.addText([{bullets_js}], {{ x:0.7, y:1.3, w:8.9, h:3.1, fontFace:'Calibri', valign:'top', margin:0 }});",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:4.8, w:10, h:0.825, fill:{{color:'{c1}'}}, line:{{color:'{c1}'}} }});",
                f"  s.addText({msg}, {{ x:0.4, y:4.85, w:9.2, h:0.7, fontSize:15, italic:true, color:'{c2}', fontFace:'Georgia', align:'center', margin:0 }});",
            ]

        else:  # concepto
            puntos = sd.get("puntos", [])
            nota   = sd.get("nota_orador", "")
            bullet_parts = []
            for p in puntos:
                bullet_parts.append(
                    "{ text: " + json.dumps(str(p)) +
                    ", options: { bullet:true, breakLine:true, fontSize:17, color:'333333' } }"
                )
            bullets_js = ", ".join(bullet_parts)
            lines += [
                f"  s.background = {{ color: 'FFFFFF' }};",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:0, w:10, h:1.1, fill:{{color:'{c1}'}}, line:{{color:'{c1}'}} }});",
                f"  s.addText({titulo}, {{ x:0.4, y:0.15, w:9.2, h:0.8, fontSize:26, bold:true, color:'FFFFFF', fontFace:'Calibri', margin:0 }});",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0, y:5.2, w:10, h:0.425, fill:{{color:'{acc}'}}, line:{{color:'{acc}'}} }});",
                f"  s.addShape(prs.shapes.RECTANGLE, {{ x:0.4, y:1.25, w:0.08, h:3.7, fill:{{color:'{acc}'}}, line:{{color:'{acc}'}} }});",
                f"  s.addText([{bullets_js}], {{ x:0.7, y:1.3, w:8.9, h:3.6, fontFace:'Calibri', valign:'top', margin:0 }});",
            ]
            if nota:
                lines.append(f"  s.addNotes({json.dumps(nota)});")

        lines.append("}")

    out_path = tempfile.mktemp(suffix=".pptx")
    lines.append(f"prs.writeFile({{ fileName: {json.dumps(out_path)} }}).then(() => console.log('OK'));")

    tmp_js = tempfile.mktemp(suffix=".js")
    with open(tmp_js, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    result = subprocess.run(["node", tmp_js], capture_output=True, text=True, timeout=60)
    os.unlink(tmp_js)

    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"Node error: {result.stderr[:500]}")

    with open(out_path, "rb") as f:
        pptx_bytes = f.read()
    os.unlink(out_path)
    return pptx_bytes


# ══════════════════════════════════════════════════════════════════════════════
# INTERFAZ
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class='big-header'>
    <h2 style='margin:0'>📚 AI Study Buddy</h2>
    <p style='margin:4px 0 0 0;opacity:0.85'>Sube PDFs, Word, PowerPoint, TXT o audios. Claude analiza todo junto.</p>
</div>""", unsafe_allow_html=True)

st.markdown("""<div style='margin-bottom:16px'>
<span class='format-pill'>📄 PDF</span><span class='format-pill'>📝 Word</span>
<span class='format-pill'>📊 PowerPoint</span><span class='format-pill'>📃 TXT/MD</span>
<span class='format-pill'>🎙️ MP3/WAV/M4A</span><span class='format-pill'>🎬 MP4/WEBM</span>
</div>""", unsafe_allow_html=True)

# ══ PASO 1: CARGAR ════════════════════════════════════════════════════════════
st.markdown("### 📥 Paso 1 · Cargar fuentes")

with st.expander("Gestionar archivos y texto", expanded=True):
    col_upload, col_text = st.columns([1, 1])

    with col_upload:
        st.markdown("**Subir archivos**")
        uploaded_files = st.file_uploader(
            "Selecciona archivos",
            type=["pdf","docx","txt","md","pptx","mp3","wav","m4a","mp4","webm","ogg"],
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        if uploaded_files:
            if st.button("➕ Añadir archivos", use_container_width=True):
                existing = [s["name"] for s in st.session_state.sources]
                added = 0
                for f in uploaded_files:
                    if f.name not in existing:
                        with st.spinner(f"Procesando {f.name}..."):
                            src = process_file(f)
                        if src and src["text"].strip():
                            st.session_state.sources.append(src)
                            added += 1
                if added:
                    st.session_state.analysis_done = False
                    st.success(f"✅ {added} fuente(s) añadidas.")
                    st.rerun()

    with col_text:
        st.markdown("**Pegar texto**")
        tname  = st.text_input("Nombre:", placeholder="Ej: Apuntes clase", label_visibility="collapsed")
        tinput = st.text_area("Texto:", height=120, placeholder="Pega aquí tus apuntes...", label_visibility="collapsed")
        if st.button("➕ Añadir texto", use_container_width=True):
            if tinput.strip() and tname.strip():
                if tname not in [s["name"] for s in st.session_state.sources]:
                    st.session_state.sources.append({
                        "name": tname, "type": "Texto", "icon": "📃",
                        "text": tinput, "pages": max(1, len(tinput)//2000)
                    })
                    st.session_state.analysis_done = False
                    st.success(f"✅ '{tname}' añadido.")
                    st.rerun()
            else:
                st.warning("Escribe un nombre y algún contenido.")

# Métricas y lista de fuentes
if st.session_state.sources:
    total_pages = sum(s["pages"] for s in st.session_state.sources)
    total_chars = sum(len(s["text"]) for s in st.session_state.sources)

    col1, col2, col3 = st.columns(3)
    col1.metric("📁 Fuentes", len(st.session_state.sources))
    col2.metric("📄 Páginas", total_pages)
    col3.metric("📝 Caracteres", f"{total_chars:,}")

    for i, src in enumerate(st.session_state.sources):
        c1, c2 = st.columns([6, 1])
        with c1:
            st.markdown(
                f"<div class='source-card'>"
                f"<span class='source-name'>{src['icon']} {src['name']}</span>"
                f" <span class='source-meta'>· {src['type']} · {src['pages']} págs</span>"
                f"</div>",
                unsafe_allow_html=True
            )
        with c2:
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.sources.pop(i)
                st.session_state.analysis_done = False
                st.rerun()

# ══ PASO 2: ANALIZAR ══════════════════════════════════════════════════════════
st.markdown("### ⚡ Paso 2 · Analizar")

col_btn, col_rst = st.columns([3, 1])
with col_btn:
    btn_analizar = st.button(
        "⚡ Analizar todo el contenido",
        use_container_width=True,
        type="primary",
        disabled=not bool(st.session_state.sources)
    )
with col_rst:
    if st.button("🔄 Limpiar todo", use_container_width=True):
        for k in ["sources","combined_text","chapters","chapter_summaries",
                  "full_summary","analysis_done","chat_history","doc_info"]:
            st.session_state[k] = (
                [] if k in ["sources","chapters","chat_history"] else
                {} if k in ["chapter_summaries","doc_info"] else
                "" if k in ["combined_text","full_summary"] else False
            )
        st.rerun()

if not st.session_state.sources:
    st.info("👆 Añade al menos una fuente para poder analizar.")

if btn_analizar and st.session_state.sources:
    combined = build_combined_text()
    st.session_state.combined_text = combined
    total_pages = sum(s["pages"] for s in st.session_state.sources)

    with st.spinner("🔍 Detectando estructura..."):
        doc_info = detect_chapters(combined, total_pages)
        st.session_state.chapters  = doc_info.get("capitulos", [])
        st.session_state.doc_info  = doc_info

    with st.spinner("📝 Generando resumen general..."):
        st.session_state.full_summary = generate_full_summary(combined, doc_info, total_pages)

    st.session_state.analysis_done    = True
    st.session_state.chapter_summaries = {}
    st.session_state.chat_history      = []
    st.success(f"✅ ¡Listo! {len(st.session_state.chapters)} secciones detectadas.")
    st.rerun()

# ══ PASO 3: RESULTADOS ════════════════════════════════════════════════════════
if st.session_state.analysis_done:
    st.markdown("---")
    doc_info  = st.session_state.doc_info
    doc_title = doc_info.get("titulo_documento", "Contenido de estudio")
    st.subheader(f"📖 {doc_title}")
    fuentes_icons = " · ".join([f"{s['icon']} {s['name']}" for s in st.session_state.sources])
    st.caption(fuentes_icons)

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Resumen general",
        "📑 Secciones",
        "🎯 Presentación PPT",
        "💬 Preguntar"
    ])

    # ── TAB 1: RESUMEN ─────────────────────────────────────────────────────────
    with tab1:
        st.markdown(st.session_state.full_summary)
        st.download_button("⬇️ Descargar resumen", st.session_state.full_summary,
                           "resumen.md", "text/markdown")

    # ── TAB 2: SECCIONES ───────────────────────────────────────────────────────
    with tab2:
        chapters = st.session_state.chapters
        if not chapters:
            st.info("No se detectaron secciones.")
        else:
            st.markdown("### 📌 Índice")
            for ch in chapters:
                badge = f" `{ch.get('fuente','')}`" if ch.get("fuente") else ""
                st.markdown(f"**{ch['numero']}.** {ch['titulo']}{badge}")
                if ch.get("descripcion_breve"):
                    st.caption(ch["descripcion_breve"])

            st.markdown("---")
            chapter_names = [f"{ch['numero']}. {ch['titulo']}" for ch in chapters]
            selected = st.selectbox("Selecciona una sección:", chapter_names)
            ch_idx  = chapter_names.index(selected)
            chapter = chapters[ch_idx]
            ch_key  = f"ch_{ch_idx}"

            c1b, c2b = st.columns([3, 1])
            with c1b:
                if st.button("⚡ Analizar sección", use_container_width=True, type="primary"):
                    with st.spinner("Analizando..."):
                        st.session_state.chapter_summaries[ch_key] = summarize_chapter(
                            chapter, st.session_state.combined_text)
                    st.rerun()

            if ch_key in st.session_state.chapter_summaries:
                with c2b:
                    st.download_button("⬇️ Descargar",
                                       st.session_state.chapter_summaries[ch_key],
                                       f"seccion_{chapter['numero']}.md", "text/markdown")
                st.markdown(st.session_state.chapter_summaries[ch_key])
            else:
                st.info("👆 Pulsa para analizar esta sección.")

    # ── TAB 3: PRESENTACIÓN PPT ────────────────────────────────────────────────
    with tab3:
        st.markdown("### 🎯 Generar presentación tipo clase maestra")
        st.markdown("Claude genera un `.pptx` profesional con portada, conceptos, citas, tablas y conclusiones.")

        col_sl, col_info = st.columns([2, 1])
        with col_sl:
            num_slides = st.slider("Número de diapositivas:", min_value=6, max_value=20, value=10)
        with col_info:
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption("Incluye: portada · conceptos · citas · tablas · conclusión")

        btn_ppt = st.button("🎨 Generar presentación PPT", use_container_width=True, type="primary")

        if btn_ppt:
            prs_data = None
            with st.spinner("🤖 Claude diseñando la presentación..."):
                try:
                    prs_data = generate_presentation_data(
                        st.session_state.combined_text,
                        st.session_state.doc_info,
                        num_slides
                    )
                    st.success(f"✅ Estructura lista: {len(prs_data['slides'])} diapositivas")
                except Exception as e:
                    st.error(f"Error generando estructura: {e}")

            if prs_data:
                with st.spinner("⚙️ Construyendo archivo .pptx..."):
                    try:
                        pptx_bytes = build_pptx_file(prs_data)
                        st.success("✅ ¡Presentación lista para descargar!")

                        st.markdown("**📋 Índice de diapositivas:**")
                        tipo_emoji = {"titulo":"🎯","concepto":"📌","cita":"💬","tabla":"📊","conclusion":"🏁"}
                        for i, s in enumerate(prs_data["slides"]):
                            em = tipo_emoji.get(s.get("tipo","concepto"),"📌")
                            st.markdown(f"{i+1}. {em} **{s.get('titulo','')}**")

                        st.download_button(
                            label="⬇️ Descargar presentación .pptx",
                            data=pptx_bytes,
                            file_name=f"{prs_data.get('titulo','presentacion')[:40]}.pptx",
                            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            use_container_width=True,
                        )
                    except Exception as e:
                        st.error(f"Error construyendo PPTX: {e}")

    # ── TAB 4: CHAT ────────────────────────────────────────────────────────────
    with tab4:
        st.markdown("### 💬 Pregunta sobre el contenido")
        st.caption(f"Claude tiene acceso a: {fuentes_icons}")

        pregunta_input = st.text_input(
            "Tu pregunta:",
            placeholder="Ej: ¿Cuál es la idea principal? ¿Explícame el capítulo 2..."
        )
        c_send, c_clear = st.columns([3, 1])
        with c_send:
            btn_send = st.button("📨 Enviar pregunta", use_container_width=True, type="primary")
        with c_clear:
            if st.button("🗑️ Limpiar", use_container_width=True):
                st.session_state.chat_history = []
                st.rerun()

        if btn_send and pregunta_input and pregunta_input.strip():
            st.session_state.chat_history.append({"role": "user", "content": pregunta_input.strip()})
            with st.spinner("Claude está pensando..."):
                respuesta = ask_question(pregunta_input.strip(), st.session_state.chat_history[:-1])
            st.session_state.chat_history.append({"role": "assistant", "content": respuesta})
            st.rerun()

        st.markdown("---")

        if not st.session_state.chat_history:
            st.markdown("**💡 Sugerencias:**")
            sugs = [
                "¿Cuál es la idea principal?",
                "¿Qué conceptos son los más importantes?",
                "Compara las ideas de las fuentes",
                "Hazme un test de 5 preguntas",
                "¿Qué aplicaciones prácticas tiene?",
                "¿Qué debo repasar más?"
            ]
            cols = st.columns(2)
            for i, sug in enumerate(sugs):
                with cols[i % 2]:
                    if st.button(sug, key=f"sug_{i}", use_container_width=True):
                        st.session_state.chat_history.append({"role": "user", "content": sug})
                        with st.spinner("Pensando..."):
                            resp = ask_question(sug, [])
                        st.session_state.chat_history.append({"role": "assistant", "content": resp})
                        st.rerun()

        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(
                    f"<div class='chat-user'><div class='chat-label-user'>👤 Tú</div>{msg['content']}</div>",
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<div class='chat-claude'><div class='chat-label-claude'>🤖 Claude</div>{msg['content']}</div>",
                    unsafe_allow_html=True)

        if st.session_state.chat_history:
            chat_md = "\n\n".join([
                f"**{'Tú' if m['role']=='user' else 'Claude'}:** {m['content']}"
                for m in st.session_state.chat_history
            ])
            st.download_button("⬇️ Descargar conversación", chat_md, "conversacion.md", "text/markdown")

# ── PIE ────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("📚 AI Study Buddy · Impulsado por Claude · Multi-formato · Multi-fuente · PPT")
