from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

def hex_to_rgb(hex_color):
    """Convierte '1E2761' a un objeto RGBColor."""
    hex_color = hex_color.lstrip('#')
    return RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))

def build_pptx_file(prs_data):
    """Genera el .pptx usando python-pptx en lugar de Node.js."""
    prs = Presentation()
    
    # Colores desde el JSON de Claude
    c1 = hex_to_rgb(prs_data.get("color_primario", "1E2761"))
    acc = hex_to_rgb(prs_data.get("color_acento", "F96167"))

    for sd in prs_data.get("slides", []):
        tipo = sd.get("tipo", "concepto")
        
        # Seleccionar layout (0: Titulo, 1: Contenido, 6: Blanco)
        if tipo == "titulo":
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = sd.get("titulo", "")
            slide.placeholders[1].text = sd.get("subtitulo", "")
        
        elif tipo == "cita":
            slide = prs.slides.add_slide(prs.slide_layouts[6]) # Blanco
            # Rectángulo de fondo para la cita
            txBox = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3))
            tf = txBox.text_frame
            tf.text = f"\"{sd.get('cita', '')}\""
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            p.font.italic = True
            p.font.size = Pt(28)
            
        elif tipo == "tabla":
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = sd.get("titulo", "")
            rows = len(sd.get("filas", [])) + 1
            cols = len(sd.get("cabeceras", []))
            table = slide.shapes.add_table(rows, cols, Inches(0.5), Inches(1.5), Inches(9), Inches(4)).table
            # Llenar cabeceras
            for i, h in enumerate(sd.get("cabeceras", [])):
                table.cell(0, i).text = str(h)
            # Llenar filas
            for r, fila in enumerate(sd.get("filas", [])):
                for c, valor in enumerate(fila):
                    table.cell(r+1, c).text = str(valor)

        else: # concepto o conclusion
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = sd.get("titulo", "")
            tf = slide.placeholders[1].text_frame
            for punto in sd.get("puntos", []):
                p = tf.add_paragraph()
                p.text = str(punto)
                p.level = 0

    # Guardar en un buffer de memoria
    pptx_io = io.BytesIO()
    prs.save(pptx_io)
    return pptx_io.getvalue()
