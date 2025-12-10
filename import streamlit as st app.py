import streamlit as st
from PIL import Image
import io
from pypdf import PdfReader, PdfWriter, Transformation

# ────────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN GENERAL
# ────────────────────────────────────────────────────────────────────────────────
LETTER_WIDTH  = 612   # ancho de "carta" en puntos/píxeles del canvas
LETTER_HEIGHT = 792   # alto de "carta"
st.set_page_config(page_title="Image ⇢ PDF • PDF Merger", page_icon="📄")

# token para forzar refresh de widgets
if "reset_token" not in st.session_state:
    st.session_state.reset_token = 0
def clear_interface():
    st.session_state.reset_token += 1
st.sidebar.button("🧹 Limpiar", on_click=clear_interface)

# ────────────────────────────────────────────────────────────────────────────────
# CONTROLES DE COMPRESIÓN (sidebar)
# ────────────────────────────────────────────────────────────────────────────────
st.sidebar.header("Ajustes de salida de imagen")
jpeg_initial = st.sidebar.slider("Calidad inicial (JPEG)", 10, 95, 80)
jpeg_min     = st.sidebar.slider("Calidad mínima permitida", 5, 60, 25)
max_dim = st.sidebar.slider("Dimensión máxima (px) — ancho/alto", 200, 4000, 1600, step=50)
use_target = st.sidebar.checkbox("Intentar ajustar a tamaño objetivo (KB)", value=False)
target_kb = None
if use_target:
    target_kb = st.sidebar.number_input("Tamaño objetivo por imagen (KB)", 30, 5000, 300, step=10)

# ────────────────────────────────────────────────────────────────────────────────
# FUNCIONES AUXILIARES DE IMAGEN
# ────────────────────────────────────────────────────────────────────────────────
def ensure_rgb(img: Image.Image) -> Image.Image:
    """Convierte imágenes con transparencia a RGB con fondo blanco."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img

def resize_keep_aspect(img: Image.Image, max_dim: int) -> Image.Image:
    """Redimensiona manteniendo aspecto hasta la dimensión máxima indicada."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    ratio = max_dim / float(max(w, h))
    new_size = (int(w * ratio), int(h * ratio))
    return img.resize(new_size, Image.LANCZOS)

def jpeg_buffer(img: Image.Image, quality: int):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", optimize=True, quality=int(quality))
    buf.seek(0)
    return buf, len(buf.getvalue())

def compress_to_target(img: Image.Image, initial_q: int, min_q: int, max_dim: int, target_kb):
    """
    Comprime la imagen:
    - si target_kb es None => guarda con initial_q
    - si target_kb definido => busca por binsearch la calidad que aprox. cumple el objetivo
    Devuelve (BytesIO_buffer, quality_used, size_kb)
    """
    img = ensure_rgb(img)
    img = resize_keep_aspect(img, max_dim)

    if not target_kb:
        buf, size = jpeg_buffer(img, initial_q)
        return buf, initial_q, size / 1024.0

    low, high = min_q, initial_q
    best_buf, best_q, best_size = None, None, float("inf")
    target_bytes = target_kb * 1024

    # búsqueda binaria sobre calidad (10 iteraciones suelen ser suficientes)
    for _ in range(10):
        mid = (low + high) // 2
        buf, size = jpeg_buffer(img, mid)

        if size <= target_bytes:
            # cumple objetivo: intentar bajar más calidad para acercarnos al objetivo
            best_buf, best_q, best_size = buf, mid, size
            high = mid - 1
        else:
            # demasiado grande: aumentar calidad mínima (bajar calidad produce menor tamaño, por eso subimos low)
            low = mid + 1

        if low > high:
            break

    if best_buf is None:
        # no encontramos calidad que deje la imagen por debajo del objetivo: usar calidad mínima
        best_buf, size = jpeg_buffer(img, min_q)
        best_q = min_q
        best_size = size

    return best_buf, best_q, best_size / 1024.0

# ────────────────────────────────────────────────────────────────────────────────
# RENDER EN HOJA CARTA (OPCIÓN A: escalar proporcionalmente sin recortar)
# ────────────────────────────────────────────────────────────────────────────────
def render_on_letter(buf: io.BytesIO) -> Image.Image:
    """
    Abre el buffer JPEG y lo centra en un canvas tamaño carta.
    Antes de pegarlo, escala proporcionalmente para que quepa entero (sin recortes).
    """
    img = Image.open(buf)

    # calcular factor de escala para que la imagen quepa en la página carta
    scale = min(LETTER_WIDTH / img.width, LETTER_HEIGHT / img.height, 1.0)
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)

    if (new_w, new_h) != img.size:
        img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (LETTER_WIDTH, LETTER_HEIGHT), "white")
    cx = (LETTER_WIDTH - img.width) // 2
    cy = (LETTER_HEIGHT - img.height) // 2
    canvas.paste(img, (cx, cy))
    return canvas

# ────────────────────────────────────────────────────────────────────────────────
# FUNCIONES PDF
# ────────────────────────────────────────────────────────────────────────────────
def add_page_as_letter(writer: PdfWriter, page) -> None:
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    scale = min(LETTER_WIDTH / w, LETTER_HEIGHT / h)
    tx = (LETTER_WIDTH  - w * scale) / 2
    ty = (LETTER_HEIGHT - h * scale) / 2
    blank = writer.add_blank_page(width=LETTER_WIDTH, height=LETTER_HEIGHT)
    transform = Transformation().scale(scale).translate(tx, ty)
    if hasattr(blank, "merge_transformed_page"):
        blank.merge_transformed_page(page, transform)
    else:
        blank.mergeTransformedPage(page, transform.ctm)

# ────────────────────────────────────────────────────────────────────────────────
# INTERFAZ — MODO
# ────────────────────────────────────────────────────────────────────────────────
st.title("📄 Image ⇢ PDF • PDF Merger")
mode = st.sidebar.radio(
    "Seleccione la función",
    ("Convertir imágenes a PDF", "Unir PDFs"),
    key=f"mode_{st.session_state.reset_token}",
)

# ────────────────────────────────────────────────────────────────────────────────
# MODO 1 — CONVERTIR IMÁGENES A PDF
# ────────────────────────────────────────────────────────────────────────────────
if mode == "Convertir imágenes a PDF":
    st.header("🖼️ → 📄 Convertir imágenes a PDF")

    imgs = st.file_uploader(
        "Sube imágenes",
        type=["png", "jpg", "jpeg", "bmp", "tiff"],
        accept_multiple_files=True,
        key=f"imgs_{st.session_state.reset_token}",
    )
    out_name = st.text_input("Nombre del PDF", "imagenes.pdf", key=f"out_{st.session_state.reset_token}")

    if st.button("Crear PDF", key=f"btn_imgpdf_{st.session_state.reset_token}"):
        if not imgs:
            st.warning("Sube al menos una imagen.")
            st.stop()

        pages = []
        summary = []
        with st.spinner("Procesando imágenes..."):
            for uf in imgs:
                try:
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
                except Exception as e:
                    st.error(f"❌ {uf.name}: {e}")

        if pages:
            out_buf = io.BytesIO()
            pages[0].save(out_buf, format="PDF", save_all=True, append_images=pages[1:])
            out_buf.seek(0)
            st.success("PDF generado ✔️")
            st.download_button("📥 Descargar PDF", out_buf, file_name=out_name, mime="application/pdf",
                               key=f"dl_imgpdf_{st.session_state.reset_token}")

            st.subheader("Resumen de compresión")
            for name, q, size in summary:
                st.write(f"- **{name}** → calidad final: **{q}**, tamaño aproximado: **{size} KB**")
        else:
            st.warning("No se generó ninguna página válida.")

# ────────────────────────────────────────────────────────────────────────────────
# MODO 2 — UNIR PDFs Y NORMALIZAR A CARTA
# ────────────────────────────────────────────────────────────────────────────────
else:
    st.header("📚 → 📄 Unir PDFs")

    pdfs = st.file_uploader(
        "Sube archivos PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdfs_{st.session_state.reset_token}",
    )
    merged_name = st.text_input("Nombre del PDF combinado", "documento_unido.pdf", key=f"merged_{st.session_state.reset_token}")

    if st.button("Unir PDFs", key=f"btn_merge_{st.session_state.reset_token}"):
        if not pdfs:
            st.warning("Sube al menos un PDF.")
            st.stop()

        writer = PdfWriter()
        with st.spinner("Unificando PDFs..."):
            for pf in pdfs:
                try:
                    reader = PdfReader(pf)
                    for page in reader.pages:
                        add_page_as_letter(writer, page)
                except Exception as e:
                    st.error(f"❌ {pf.name}: {e}")

        if writer.pages:
            buf = io.BytesIO()
            writer.write(buf)
            buf.seek(0)
            st.success("PDF combinado creado ✔️")
            st.download_button("📥 Descargar PDF unido", buf, file_name=merged_name, mime="application/pdf",
                               key=f"dl_merge_{st.session_state.reset_token}")
        else:
            st.warning("No se añadió ninguna página válida.")
