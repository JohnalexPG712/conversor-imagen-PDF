import streamlit as st
from PIL import Image
import io
from pypdf import PdfReader, PdfWriter, Transformation
import math

# ────────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN GENERAL
# ────────────────────────────────────────────────────────────────────────────────
LETTER_WIDTH  = 612
LETTER_HEIGHT = 792

st.set_page_config(page_title="Image ⇢ PDF • PDF Merger", page_icon="📄")

if "reset_token" not in st.session_state:
    st.session_state.reset_token = 0

def clear_interface():
    st.session_state.reset_token += 1

st.sidebar.button("🧹 Limpiar", on_click=clear_interface)

# ────────────────────────────────────────────────────────────────────────────────
# OPCIONES DE COMPRESIÓN (Sidebar)
# ────────────────────────────────────────────────────────────────────────────────
st.sidebar.header("Ajustes de compresión")

jpeg_initial = st.sidebar.slider("Calidad inicial", 10, 95, 80)
jpeg_min     = st.sidebar.slider("Calidad mínima permitida", 5, 60, 25)

max_dim = st.sidebar.slider(
    "Dimensión máxima (px)", 200, 4000, 1600, step=50
)

use_target = st.sidebar.checkbox(
    "Ajustar por tamaño objetivo (KB)", False
)

target_kb = None
if use_target:
    target_kb = st.sidebar.number_input(
        "Tamaño objetivo por imagen (KB)", 30, 5000, 300, step=10
    )

# ────────────────────────────────────────────────────────────────────────────────
# FUNCIONES AUXILIARES
# ────────────────────────────────────────────────────────────────────────────────
def ensure_rgb(img):
    """Convierte PNG con transparencia a fondo blanco."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB") if img.mode != "RGB" else img

def resize_keep_aspect(img, max_dim):
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    r = max_dim / max(w, h)
    return img.resize((int(w*r), int(h*r)), Image.LANCZOS)

def jpeg_buffer(img, quality):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", optimize=True, quality=int(quality))
    buf.seek(0)
    return buf, len(buf.getvalue())

def compress_to_target(img, initial_q, min_q, max_dim, target_kb=None):
    img = ensure_rgb(img)
    img = resize_keep_aspect(img, max_dim)

    if not target_kb:
        buf, size = jpeg_buffer(img, initial_q)
        return buf, initial_q, size / 1024

    # Búsqueda binaria entre [min_q, initial_q]
    low, high = min_q, initial_q
    best_buf, best_q, best_size = None, high, float("inf")
    target_bytes = target_kb * 1024

    for _ in range(10):  # 10 iteraciones ≈ precisión de ±1 KB
        mid = (low + high) // 2
        buf, size = jpeg_buffer(img, mid)

        if size <= target_bytes:
            best_buf, best_q, best_size = buf, mid, size
            high = mid - 1
        else:
            low = mid + 1

        if low > high:
            break

    if best_buf is None:
        # no pudo bajar lo suficiente: usar mínima
        best_buf, best_size = jpeg_buffer(img, min_q)
        best_q = min_q

    return best_buf, best_q, best_size / 1024

def render_on_letter(buf):
    img = Image.open(buf)

    canvas = Image.new("RGB", (LETTER_WIDTH, LETTER_HEIGHT), "white")
    cx = (LETTER_WIDTH - img.width) // 2
    cy = (LETTER_HEIGHT - img.height) // 2
    canvas.paste(img, (cx, cy))
    return canvas

# ────────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PDF
# ────────────────────────────────────────────────────────────────────────────────
def add_page_as_letter(writer, page):
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    s = min(LETTER_WIDTH / w, LETTER_HEIGHT / h)
    tx = (LETTER_WIDTH  - w*s) / 2
    ty = (LETTER_HEIGHT - h*s) / 2

    blank = writer.add_blank_page(width=LETTER_WIDTH, height=LETTER_HEIGHT)
    transform = Transformation().scale(s).translate(tx, ty)

    if hasattr(blank, "merge_transformed_page"):
        blank.merge_transformed_page(page, transform)
    else:
        blank.mergeTransformedPage(page, transform.ctm)

# ────────────────────────────────────────────────────────────────────────────────
# INTERFAZ — MODO
# ────────────────────────────────────────────────────────────────────────────────
st.title("📄 Image ⇢ PDF • PDF Merger")

mode = st.sidebar.radio(
    "Elija una opción",
    ("Convertir imágenes a PDF", "Unir PDFs"),
    key=f"mode_{st.session_state.reset_token}"
)

# ────────────────────────────────────────────────────────────────────────────────
# MODO 1 — IMÁGENES → PDF
# ────────────────────────────────────────────────────────────────────────────────
if mode == "Convertir imágenes a PDF":
    st.header("🖼️ → 📄 Convertir imágenes a PDF")

    imgs = st.file_uploader(
        "Sube imágenes",
        type=["png", "jpg", "jpeg", "bmp", "tiff"],
        accept_multiple_files=True,
        key=f"imgs_{st.session_state.reset_token}",
    )

    out_name = st.text_input(
        "Nombre del PDF",
        "imagenes.pdf"
    )

    if st.button("Crear PDF"):
        if not imgs:
            st.warning("Sube al menos una imagen.")
            st.stop()

        pages = []
        summary = []

        for uf in imgs:
            img = Image.open(uf)

            buf, q_used, sz_kb = compress_to_target(
                img,
                jpeg_initial,
                jpeg_min,
                max_dim,
                target_kb if use_target else None
            )

            canvas = render_on_letter(buf)
            pages.append(canvas)
            summary.append((uf.name, q_used, round(sz_kb, 2)))

        # exportar PDF
        pdf_bytes = io.BytesIO()
        pages[0].save(pdf_bytes, format="PDF", save_all=True, append_images=pages[1:])
        pdf_bytes.seek(0)

        st.success("PDF generado ✔️")
        st.download_button("📥 Descargar PDF", pdf_bytes, out_name, mime="application/pdf")

        st.subheader("Resultados de compresión")
        for name, q, size in summary:
            st.write(f"**{name}** → calidad final: **{q}**, tamaño: **{size} KB**")

# ────────────────────────────────────────────────────────────────────────────────
# MODO 2 — UNIR PDFs
# ────────────────────────────────────────────────────────────────────────────────
else:
    st.header("📚 → 📄 Unir PDFs")

    pdfs = st.file_uploader(
        "Sube archivos PDF",
        type=["pdf"],
        accept_multiple_files=True,
    )

    out_name = st.text_input(
        "Nombre del PDF combinado",
        "documento_unido.pdf"
    )

    if st.button("Unir PDFs"):
        if not pdfs:
            st.warning("Sube al menos un PDF.")
            st.stop()

        writer = PdfWriter()
        for pf in pdfs:
            reader = PdfReader(pf)
            for page in reader.pages:
                add_page_as_letter(writer, page)

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)

        st.success("PDF unido generado ✔️")
        st.download_button("📥 Descargar PDF", buf, out_name, mime="application/pdf")
