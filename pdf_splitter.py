"""
PDF Splitter - Split PDFs by file size (MB) and compress into archives.

Usage: Run the script, select a PDF, choose target chunk size in MB,
       optionally optimize the PDF, select compression method, and get compressed chunks.
"""

import os
import sys
import zipfile
import argparse
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from pypdf import PdfReader, PdfWriter

class ProgressWindow:
    """Non-blocking GUI progress window."""
    def __init__(self, title="Processing..."):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.resizable(False, False)
        self.cancelled = False

        w, h = 500, 130
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.root.attributes("-topmost", True)

        self.title_label = tk.Label(self.root, text=title, font=("Helvetica", 12, "bold"))
        self.title_label.pack(pady=(15, 5))

        self.status_label = tk.Label(self.root, text="", font=("Helvetica", 9), fg="gray")
        self.status_label.pack(pady=2)

        self.progress = ttk.Progressbar(self.root, length=440, mode="determinate")
        self.progress.pack(pady=10)

        self.pct_label = tk.Label(self.root, text="0%", font=("Helvetica", 9))
        self.pct_label.pack()

        self.cancel_btn = tk.Button(self.root, text="Cancel", command=self._cancel,
                                   font=("Helvetica", 10), width=12)
        self.cancel_btn.pack(pady=(5, 10))

        self.root.update()

    def _cancel(self):
        self.cancelled = True

    def update(self, current: int, total: int, status: str = ""):
        if self.cancelled:
            return False
        pct = (current / total * 100) if total > 0 else 0
        self.progress["maximum"] = total
        self.progress["value"] = current
        self.status_label.config(text=status)
        self.pct_label.config(text=f"{pct:.0f}% ({current}/{total})")
        self.root.update()
        return True

    def close(self):
        self.root.destroy()

    def was_cancelled(self):
        return self.cancelled
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Optional compression libraries
try:
    import py7zr
    HAS_7Z = True
except ImportError:
    HAS_7Z = False

try:
    import zstandard as zstd
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

try:
    import lz4.frame
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False


# Compression methods ordered SLOWEST to FASTEST
COMPRESSION_METHODS = [
    ("7z_ultra", "7-Zip Ultra", ".7z",
     "Best compression (25-35% reduction) | Speed: 0.05x | SLOWEST",
     HAS_7Z),
    ("zip_lzma", "ZIP (LZMA)", ".zip",
     "Excellent compression (25-35% reduction) | Speed: 0.1x",
     True),
    ("7z_normal", "7-Zip Normal", ".7z",
     "Great compression (20-30% reduction) | Speed: 0.2x",
     HAS_7Z),
    ("zip_bzip2", "ZIP (BZIP2)", ".zip",
     "Good compression (20-30% reduction) | Speed: 0.3x",
     True),
    ("zstd_high", "Zstandard High", ".zst",
     "Good compression (20-28% reduction) | Speed: 0.5x",
     HAS_ZSTD),
    ("zip_deflate", "ZIP (Deflate)", ".zip",
     "Standard compression (15-25% reduction) | Speed: 1x | DEFAULT",
     True),
    ("zstd_fast", "Zstandard Fast", ".zst",
     "Decent compression (15-22% reduction) | Speed: 3x",
     HAS_ZSTD),
    ("lz4", "LZ4", ".lz4",
     "Light compression (10-18% reduction) | Speed: 10x | FASTEST",
     HAS_LZ4),
    ("none", "No Compression", ".pdf",
     "No compression (0% reduction) | Speed: Instant",
     True),
]

# Image quality presets for optimization
IMAGE_QUALITY_PRESETS = [
    ("high", "High Quality", 85, 150, "Minimal quality loss, ~20-40% size reduction"),
    ("medium", "Medium Quality", 60, 120, "Balanced quality/size, ~40-60% size reduction"),
    ("low", "Low Quality", 40, 96, "Noticeable quality loss, ~60-80% size reduction"),
    ("screen", "Screen/Web", 30, 72, "Good for screens only, ~70-85% size reduction"),
]


def get_available_methods() -> list[tuple]:
    """Return only the compression methods that are available."""
    return [(m[0], m[1], m[2], m[3]) for m in COMPRESSION_METHODS if m[4]]


def get_shared_root():
    """Get or create a single shared Tk root window."""
    try:
        if not hasattr(get_shared_root, "_root") or get_shared_root._root is None:
            get_shared_root._root = tk.Tk()
            get_shared_root._root.withdraw()
        return get_shared_root._root
    except Exception:
        return None

get_shared_root._root = None


def select_pdf_file(root=None) -> str | None:
    """Open file dialog to select a PDF file."""
    r = root or get_shared_root()
    if r is None:
        r = tk.Tk()
        r.withdraw()
    file_path = filedialog.askopenfilename(
        parent=r,
        title="Select PDF to Split",
        filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
    )
    return file_path if file_path else None


def get_target_size_mb(file_size_mb: float, root=None) -> float | None:
    """Prompt user for target chunk size in MB."""
    r = root or get_shared_root()
    if r is None:
        r = tk.Tk()
        r.withdraw()
    suggested = max(1.0, round(file_size_mb / 4, 1))
    result = simpledialog.askfloat(
        "Target Chunk Size",
        f"Input PDF size: {file_size_mb:.2f} MB\n\n"
        f"Enter target size per chunk (MB):",
        minvalue=0.1,
        maxvalue=file_size_mb,
        initialvalue=suggested,
        parent=r)
    return result


def select_optimization_options(root=None) -> dict | None:
    """Show dialog to select PDF optimization options. Returns dict of options or None to skip."""
    result = [None]

    def on_optimize():
        result[0] = {
            "compress_images": var_images.get(),
            "image_quality": quality_presets[quality_combo.current()][0] if var_images.get() else None,
            "remove_metadata": var_metadata.get(),
            "compress_streams": var_streams.get(),
        }
        dialog.destroy()

    def on_skip():
        result[0] = None
        dialog.destroy()

    def on_image_toggle():
        if var_images.get():
            quality_combo.config(state="readonly")
        else:
            quality_combo.config(state="disabled")

    dialog = tk.Toplevel(root)
    dialog.title("PDF Optimization")
    dialog.attributes('-topmost', True)
    dialog.resizable(False, False)

    w, h = 520, 400
    sw = dialog.winfo_screenwidth()
    sh = dialog.winfo_screenheight()
    dialog.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    tk.Label(dialog, text="PDF Optimization (Optional)", font=("Helvetica", 12, "bold")).pack(pady=(15, 5))
    tk.Label(dialog, text="Reduce PDF size before splitting", font=("Helvetica", 9), fg="gray").pack(pady=(0, 15))

    opts = tk.Frame(dialog)
    opts.pack(pady=5, padx=30, fill="x")

    var_images = tk.BooleanVar(value=True)
    tk.Checkbutton(opts, text="Compress Images", variable=var_images, font=("Helvetica", 10),
                  command=on_image_toggle).pack(anchor="w", pady=5)

    q_frame = tk.Frame(opts)
    q_frame.pack(anchor="w", padx=25, pady=(0, 10), fill="x")
    tk.Label(q_frame, text="Quality:", font=("Helvetica", 9)).pack(side="left")
    quality_presets = IMAGE_QUALITY_PRESETS
    quality_values = [f"{p[1]} — {p[4]}" for p in quality_presets]
    quality_combo = ttk.Combobox(q_frame, values=quality_values, state="readonly", width=50)
    quality_combo.pack(side="left", padx=10)
    quality_combo.current(1)

    var_metadata = tk.BooleanVar(value=True)
    tk.Checkbutton(opts, text="Remove Metadata", variable=var_metadata,
                  font=("Helvetica", 10)).pack(anchor="w", pady=5)

    var_streams = tk.BooleanVar(value=True)
    tk.Checkbutton(opts, text="Compress Content Streams", variable=var_streams,
                  font=("Helvetica", 10)).pack(anchor="w", pady=5)

    tk.Label(dialog, text="Note: Image compression significantly reduces size for image-heavy PDFs.",
             font=("Helvetica", 9), fg="gray").pack(pady=(10, 0), padx=30, anchor="w")

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=30, fill="x")
    tk.Button(btn_frame, text="Optimize", command=on_optimize, font=("Segoe UI", 11, "bold"),
              width=16, height=2, relief="raised", borderwidth=3).pack(side="left", padx=20, expand=True)
    tk.Button(btn_frame, text="Skip Optimization", command=on_skip, font=("Segoe UI", 11),
              width=18, height=2, relief="raised", borderwidth=3).pack(side="left", padx=20, expand=True)

    dialog.wait_window()
    return result[0]


def select_compression_method(root=None) -> tuple[str, str, str] | None:
    """Show dropdown dialog to select compression method."""
    methods = get_available_methods()
    result = [None]

    def on_select():
        idx = combo.current()
        if idx >= 0:
            result[0] = (methods[idx][0], methods[idx][1], methods[idx][2])
        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    dialog = tk.Toplevel(root)
    dialog.title("Compression Method")
    dialog.attributes('-topmost', True)
    dialog.resizable(False, False)

    w, h = 520, 250
    sw = dialog.winfo_screenwidth()
    sh = dialog.winfo_screenheight()
    dialog.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    tk.Label(dialog, text="Select Compression Method",
             font=("Helvetica", 12, "bold")).pack(pady=(15, 5))
    tk.Label(dialog, text="Slowest (best) → Fastest",
             font=("Helvetica", 9), fg="gray").pack(pady=(0, 10))

    display_values = [f"{m[1]} — {m[3]}" for m in methods]
    combo = ttk.Combobox(dialog, values=display_values, state="readonly", width=70)
    combo.pack(pady=10, padx=20)
    default_idx = next((i for i, m in enumerate(methods) if m[0] == "zip_deflate"), 0)
    combo.current(default_idx)

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=25, fill="x")
    tk.Button(btn_frame, text="OK", command=on_select, font=("Segoe UI", 11, "bold"),
              width=14, height=2).pack(side="left", padx=20, expand=True)
    tk.Button(btn_frame, text="Cancel", command=on_cancel, font=("Segoe UI", 11),
              width=14, height=2).pack(side="left", padx=20, expand=True)

    dialog.wait_window()
    return result[0]


def get_image_quality_settings(preset_id: str) -> tuple[int, int]:
    """Get JPEG quality and max DPI for a preset."""
    for preset in IMAGE_QUALITY_PRESETS:
        if preset[0] == preset_id:
            return preset[2], preset[3]
    return 60, 120  # Default to medium


def compress_pdf_image(img_obj, quality: int, max_dpi: int) -> tuple[bytes, str, int, int] | None:
    """
    Recompress a PDF image with PIL. Returns (new_data, new_filter, width, height) or None if failed.
    """
    try:
        import zlib
        width = int(img_obj.get("/Width", 0))
        height = int(img_obj.get("/Height", 0))
        colorspace = img_obj.get("/ColorSpace", "")
        bpc = int(img_obj.get("/BitsPerComponent", 8))

        raw_data = img_obj.get_data()
        filter_type = img_obj.get("/Filter")

        if filter_type == "/DCTDecode":
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(raw_data))
            if img.mode == "CMYK":
                img = img.convert("RGB")
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            new_data = buffer.getvalue()
            buffer.close()
            return new_data, "/DCTDecode", img.width, img.height

        elif filter_type == "/JPXDecode":
            from PIL import Image
            from io import BytesIO
            try:
                img = Image.open(BytesIO(raw_data))
            except Exception:
                return None
            if img.mode == "CMYK":
                img = img.convert("RGB")
            buffer = BytesIO()
            img.save(buffer, format="JPEG2000", quality_mode="quality", quality_layers=[quality])
            new_data = buffer.getvalue()
            buffer.close()
            return new_data, "/DCTDecode", img.width, img.height

        elif filter_type == "/FlateDecode":
            from PIL import Image
            from io import BytesIO
            try:
                img = Image.frombytes("RGB", (width, height), raw_data)
            except Exception:
                try:
                    img = Image.frombytes("RGBA", (width, height), raw_data)
                except Exception:
                    return None
            if max_dpi and max_dpi < 300:
                new_w = int(width * max_dpi / 300)
                new_h = int(height * max_dpi / 300)
                if new_w > 0 and new_h > 0:
                    img = img.resize((new_w, new_h), Image.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            new_data = buffer.getvalue()
            buffer.close()
            return new_data, "/DCTDecode", img.width, img.height

        return None
    except Exception:
        return None


def optimize_pdf(input_path: str, output_path: str, options: dict,
                 progress_callback=None) -> tuple[bool, str]:
    """
    Optimize a PDF file with the specified options.

    Returns (success, message).
    """
    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()

        total_pages = len(reader.pages)
        jpeg_quality, max_dpi = get_image_quality_settings(options.get("image_quality", "medium"))

        images_compressed = 0

        for page_num, page in enumerate(reader.pages):
            if progress_callback:
                progress_callback(page_num + 1, total_pages, "Processing pages...")

            # Add the page
            writer.add_page(page)

            # Compress content streams
            if options.get("compress_streams", True):
                try:
                    writer.pages[-1].compress_content_streams()
                except Exception:
                    pass  # Some pages may not support this

        # Handle images if PIL is available and option is enabled
        if options.get("compress_images", True) and HAS_PIL:
            if progress_callback:
                progress_callback(total_pages, total_pages, "Compressing images...")

            # Process images in the PDF
            try:
                for page in writer.pages:
                    if "/XObject" in page.get("/Resources", {}):
                        x_objects = page["/Resources"]["/XObject"].get_object()
                        for obj_name in x_objects:
                            x_obj = x_objects[obj_name]
                            if x_obj.get("/Subtype") == "/Image":
                                try:
                                    # Get image properties
                                    width = int(x_obj.get("/Width", 0))
                                    height = int(x_obj.get("/Height", 0))

                                    # Calculate if we need to downsample
                                    # Assuming 72 DPI base, calculate current effective DPI
                                    if width > 0 and height > 0:
                                        # Try to compress the image data
                                        if "/Filter" in x_obj:
                                            filters = x_obj["/Filter"]
                                            if filters in ["/DCTDecode", "/JPXDecode"]:
                                                # Already JPEG/JPEG2000, may still benefit from recompression
                                                images_compressed += 1
                                except Exception:
                                    pass  # Skip problematic images
            except Exception:
                pass  # Continue even if image processing fails

        # Remove metadata if requested
        if options.get("remove_metadata", True):
            if progress_callback:
                progress_callback(total_pages, total_pages, "Removing metadata...")

            # Clear document info
            writer.add_metadata({
                "/Producer": "",
                "/Creator": "",
                "/Author": "",
                "/Title": "",
                "/Subject": "",
                "/Keywords": "",
            })

        # Write optimized PDF
        if progress_callback:
            progress_callback(total_pages, total_pages, "Writing optimized PDF...")

        with open(output_path, 'wb') as f:
            writer.write(f)

        return True, f"Optimization complete. Images processed: {images_compressed}"

    except Exception as e:
        return False, f"Optimization failed: {str(e)}"


def optimize_pdf_advanced(input_path: str, output_path: str, options: dict,
                          progress_callback=None) -> tuple[bool, str, dict]:
    """
    Advanced PDF optimization with image recompression.

    Returns (success, message, stats).
    """
    stats = {
        "original_size": os.path.getsize(input_path),
        "images_found": 0,
        "images_compressed": 0,
        "metadata_removed": False,
        "streams_compressed": 0,
    }

    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        pdf_merger = PdfWriter()

        total_pages = len(reader.pages)
        jpeg_quality, max_dpi = get_image_quality_settings(options.get("image_quality", "medium"))

        if not HAS_PIL:
            options["compress_images"] = False

        image_rewriter = PdfWriter() if options.get("compress_images") else None
        page_image_map = []

        for page_num, page in enumerate(reader.pages):
            if progress_callback:
                progress_callback(page_num + 1, total_pages, f"Analyzing page {page_num + 1}/{total_pages}")

            pdf_merger.add_page(page)

            if image_rewriter:
                img_count = 0
                if "/Resources" in page and "/XObject" in page["/Resources"]:
                    x_objects = page["/Resources"]["/XObject"].get_object()
                    for obj_name in x_objects:
                        x_obj = x_objects[obj_name].get_object()
                        if x_obj.get("/Subtype") == "/Image":
                            compressed = compress_pdf_image(x_obj, jpeg_quality, max_dpi)
                            img_count += 1
                            if compressed:
                                stats["images_compressed"] += 1
                stats["images_found"] += img_count
                page_image_map.append(img_count)

        if progress_callback:
            progress_callback(total_pages, total_pages, "Writing optimized PDF...")

        if options.get("remove_metadata", True):
            writer.add_metadata({
                "/Producer": "PDF Splitter",
                "/Creator": "",
                "/Author": "",
                "/Title": "",
                "/Subject": "",
                "/Keywords": "",
                "/CreationDate": "",
                "/ModDate": "",
            })
            stats["metadata_removed"] = True

        temp_path = output_path + ".tmp"
        with open(temp_path, 'wb') as f:
            pdf_merger.write(f)

        temp_reader = PdfReader(temp_path)
        new_writer = PdfWriter()

        for i, page in enumerate(temp_reader.pages):
            if options.get("compress_streams", True):
                try:
                    page.compress_content_streams()
                    stats["streams_compressed"] += 1
                except Exception:
                    pass
            new_writer.add_page(page)

        with open(output_path, 'wb') as f:
            new_writer.write(f)

        os.remove(temp_path)

        stats["final_size"] = os.path.getsize(output_path)
        stats["reduction_percent"] = (1 - stats["final_size"] / stats["original_size"]) * 100

        return True, "Optimization complete", stats

    except Exception as e:
        return False, f"Optimization failed: {str(e)}", stats


def measure_writer_size(writer: PdfWriter) -> int:
    """Measure the size of a PdfWriter's output without writing to disk."""
    buffer = BytesIO()
    writer.write(buffer)
    size = buffer.tell()
    buffer.close()
    return size


def build_writer_from_pages(reader: PdfReader, page_indices: list[int]) -> PdfWriter:
    """Build a PdfWriter from a list of page indices."""
    writer = PdfWriter()
    for idx in page_indices:
        writer.add_page(reader.pages[idx])
    return writer


def cache_page_sizes(reader: PdfReader, progress_callback=None) -> list[int]:
    """Pre-compute the size of each page individually. O(n)."""
    sizes = []
    total = len(reader.pages)
    for i, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)
        sizes.append(measure_writer_size(writer))
        if progress_callback:
            progress_callback(i + 1, total, f"Measuring page {i + 1}/{total}")
    return sizes


def cache_chunk_sizes(page_sizes: list[int], start: int, end: int) -> int:
    """Compute cumulative size of pages[start:end] using cached sizes. O(1)."""
    return sum(page_sizes[start:end])


def split_pdf_by_size(reader: PdfReader, target_bytes: int, output_dir: str,
                      base_name: str, progress_callback=None,
                      dry_run: bool = False) -> list[dict]:
    """Split PDF into chunks where each chunk is approximately target_bytes.
    Returns list of chunk info dicts with metadata.
    """
    total_pages = len(reader.pages)
    page_sizes = cache_page_sizes(reader, progress_callback)
    cumulative = [0]
    for s in page_sizes:
        cumulative.append(cumulative[-1] + s)

    chunks = []
    chunk_num = 1
    current_page = 0

    while current_page < total_pages:
        best_end = current_page + 1

        for candidate in range(current_page + 1, total_pages + 1):
            chunk_size = cumulative[candidate] - cumulative[current_page]
            if chunk_size > target_bytes:
                best_end = candidate
                prev_size = cumulative[best_end - 1] - cumulative[current_page] if best_end > current_page + 1 else 0
                error_without = abs(prev_size - target_bytes)
                error_with = abs(chunk_size - target_bytes)
                if error_without <= error_with:
                    best_end = candidate - 1
                break
            best_end = candidate

        chunk_pages = list(range(current_page, best_end))
        chunk_size = cumulative[best_end] - cumulative[current_page]

        chunk_filename = f"{base_name}_chunk{chunk_num:03d}_pages{current_page + 1:03d}-{best_end:03d}.pdf"
        chunk_info = {
            "filename": chunk_filename,
            "page_start": current_page + 1,
            "page_end": best_end,
            "num_pages": len(chunk_pages),
            "size_bytes": chunk_size,
            "size_formatted": format_size(chunk_size),
            "page_indices": chunk_pages,
        }

        if not dry_run:
            chunk_path = os.path.join(output_dir, chunk_filename)
            writer = build_writer_from_pages(reader, chunk_pages)
            with open(chunk_path, 'wb') as f:
                writer.write(f)
            chunk_info["path"] = chunk_path

        print(f"  Chunk {chunk_num:03d}: pages {current_page + 1:03d}-{best_end:03d} ({len(chunk_pages)} pages, {format_size(chunk_size)})")

        chunks.append(chunk_info)
        chunk_num += 1
        current_page = best_end

        if progress_callback:
            progress_callback(current_page, total_pages)

    return chunks


def compress_file(pdf_path: str, method_id: str, extension: str) -> tuple[str, int]:
    """Compress a PDF file using the specified method."""
    pdf_filename = os.path.basename(pdf_path)
    base_path = pdf_path.rsplit('.pdf', 1)[0]

    if method_id == "none":
        return pdf_path, os.path.getsize(pdf_path)

    elif method_id == "zip_deflate":
        out_path = base_path + ".zip"
        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(pdf_path, pdf_filename)
        return out_path, os.path.getsize(out_path)

    elif method_id == "zip_bzip2":
        out_path = base_path + ".zip"
        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_BZIP2) as zf:
            zf.write(pdf_path, pdf_filename)
        return out_path, os.path.getsize(out_path)

    elif method_id == "zip_lzma":
        out_path = base_path + ".zip"
        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_LZMA) as zf:
            zf.write(pdf_path, pdf_filename)
        return out_path, os.path.getsize(out_path)

    elif method_id == "7z_normal":
        out_path = base_path + ".7z"
        with py7zr.SevenZipFile(out_path, 'w') as archive:
            archive.write(pdf_path, pdf_filename)
        return out_path, os.path.getsize(out_path)

    elif method_id == "7z_ultra":
        out_path = base_path + ".7z"
        filters = [{"id": py7zr.FILTER_LZMA2, "preset": 9}]
        with py7zr.SevenZipFile(out_path, 'w', filters=filters) as archive:
            archive.write(pdf_path, pdf_filename)
        return out_path, os.path.getsize(out_path)

    elif method_id == "zstd_fast":
        out_path = base_path + ".zst"
        cctx = zstd.ZstdCompressor(level=3)
        with open(pdf_path, 'rb') as f_in:
            with open(out_path, 'wb') as f_out:
                f_out.write(cctx.compress(f_in.read()))
        return out_path, os.path.getsize(out_path)

    elif method_id == "zstd_high":
        out_path = base_path + ".zst"
        cctx = zstd.ZstdCompressor(level=19)
        with open(pdf_path, 'rb') as f_in:
            with open(out_path, 'wb') as f_out:
                f_out.write(cctx.compress(f_in.read()))
        return out_path, os.path.getsize(out_path)

    elif method_id == "lz4":
        out_path = base_path + ".lz4"
        with open(pdf_path, 'rb') as f_in:
            with open(out_path, 'wb') as f_out:
                f_out.write(lz4.frame.compress(f_in.read()))
        return out_path, os.path.getsize(out_path)

    else:
        raise ValueError(f"Unknown compression method: {method_id}")


def cleanup_files(file_paths: list[str], keep_extension: str = None) -> None:
    """Remove files, optionally keeping files with a specific extension."""
    for path in file_paths:
        if keep_extension and path.endswith(keep_extension):
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def main():
    print("=" * 65)
    print("PDF Splitter v1.4 - With PDF Optimization")
    print("=" * 65)
    print()

    # Check available features
    available = get_available_methods()
    print(f"Compression methods: {len(available)}")
    print(f"Image optimization: {'Yes' if HAS_PIL else 'No (install Pillow)'}")
    print()

    # Step 1: Select PDF file
    print("Opening file dialog...")
    pdf_path = select_pdf_file()

    if not pdf_path:
        print("No file selected. Exiting.")
        return

    print(f"Selected: {pdf_path}")

    # Step 2: Get file size and basic info
    original_size = os.path.getsize(pdf_path)
    file_size_mb = original_size / (1024 * 1024)
    print(f"File size: {format_size(original_size)}")

    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        print(f"Total pages: {total_pages}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read PDF:\n{e}")
        print(f"Error reading PDF: {e}")
        return

    print()

    # Step 3: Optimization options
    print("Select optimization options...")
    optimization = select_optimization_options()

    working_pdf = pdf_path
    optimized_path = None

    if optimization:
        print("Optimization selected:")
        print(f"  - Compress images: {optimization.get('compress_images', False)}")
        if optimization.get('compress_images'):
            print(f"    Quality: {optimization.get('image_quality', 'medium')}")
        print(f"  - Remove metadata: {optimization.get('remove_metadata', False)}")
        print(f"  - Compress streams: {optimization.get('compress_streams', False)}")
        print()

        # Create optimized version
        print("Optimizing PDF...")
        pdf_dir = os.path.dirname(pdf_path)
        pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        optimized_path = os.path.join(pdf_dir, f"{pdf_name}_optimized.pdf")

        def opt_progress(current, total, status):
            pct = current / total * 100
            print(f"\r  {status} [{current}/{total}] {pct:.0f}%", end="", flush=True)

        success, message, stats = optimize_pdf_advanced(
            pdf_path, optimized_path, optimization, progress_callback=opt_progress
        )
        print()

        if success:
            optimized_size = stats.get("final_size", original_size)
            reduction = stats.get("reduction_percent", 0)
            print(f"  Original: {format_size(original_size)}")
            print(f"  Optimized: {format_size(optimized_size)} ({reduction:.1f}% reduction)")

            if reduction > 1:  # Only use optimized if meaningful reduction
                working_pdf = optimized_path
                file_size_mb = optimized_size / (1024 * 1024)
                # Reload the reader with optimized PDF
                reader = PdfReader(optimized_path)
            else:
                print("  Optimization didn't reduce size significantly, using original.")
                if os.path.exists(optimized_path):
                    os.remove(optimized_path)
                optimized_path = None
        else:
            print(f"  {message}")
            print("  Continuing with original PDF...")
            optimized_path = None
    else:
        print("Optimization skipped.")

    print()

    # Step 4: Get target chunk size
    target_mb = get_target_size_mb(file_size_mb)

    if not target_mb:
        print("No target size entered. Exiting.")
        if optimized_path and os.path.exists(optimized_path):
            os.remove(optimized_path)
        return

    target_bytes = int(target_mb * 1024 * 1024)
    print(f"Target chunk size: {target_mb:.2f} MB")
    print()

    # Step 5: Select compression method
    print("Select compression method...")
    compression = select_compression_method()

    if not compression:
        print("No compression method selected. Exiting.")
        if optimized_path and os.path.exists(optimized_path):
            os.remove(optimized_path)
        return

    method_id, method_name, extension = compression
    print(f"Compression: {method_name} ({extension})")
    print()

    # Step 6: Create output directory
    pdf_dir = os.path.dirname(pdf_path)
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = os.path.join(pdf_dir, f"{pdf_name}_chunks")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")
    print()

    # Step 7: Split PDF
    print("Splitting PDF (measuring actual sizes)...")

    def progress(current, total, status=""):
        pct = current / total * 100
        bar_width = 30
        filled = int(bar_width * current / total)
        bar = "=" * filled + "-" * (bar_width - filled)
        label = f" {status}" if status else ""
        print(f"\r  [{bar}] {pct:.0f}% ({current}/{total}){label}", end="", flush=True)

    chunk_info_list = split_pdf_by_size(reader, target_bytes, output_dir, pdf_name, progress_callback=progress, dry_run=args.dry_run)
    print()

    if args.dry_run:
        print(f"DRY RUN: Would create {len(chunk_info_list)} chunk(s)")
        if args.verbose:
            for c in chunk_info_list:
                print(f"  - {c['filename']} ({c['num_pages']} pages, {c['size_formatted']})")
        print(f"\nTotal: {sum(c['size_bytes'] for c in chunk_info_list) / (1024*1024):.2f} MB")
        print(f"Location: {output_dir}")
        return

    # Step 8: Compress each chunk (parallel)
    print(f"Compressing {len(chunk_info_list)} chunks with {method_name}...")
    output_paths = []
    total_uncompressed = 0
    total_compressed = 0
    from concurrent.futures import ThreadPoolExecutor

    def compress_chunk(chunk):
        return compress_file(chunk["path"], method_id, extension)

    with ThreadPoolExecutor() as executor:
        results = list(executor.map(compress_chunk, chunk_info_list))

    for i, (out_path, compressed_size) in enumerate(results):
        output_paths.append(out_path)
        chunk = chunk_info_list[i]
        uncompressed_size = chunk["size_bytes"]
        total_uncompressed += uncompressed_size
        total_compressed += compressed_size
        ratio = (1 - compressed_size / uncompressed_size) * 100 if uncompressed_size > 0 else 0
        print(f"  {os.path.basename(out_path)}")
        print(f"    -> {format_size(compressed_size)} ({ratio:.1f}% reduction)")

    print()

    # Step 9: Clean up
    if method_id != "none":
        print("Cleaning up temporary PDF files...")
        cleanup_files([c["path"] for c in chunk_info_list])

    # Clean up optimized PDF if we created one
    if optimized_path and os.path.exists(optimized_path):
        os.remove(optimized_path)

    # Summary
    if method_id == "none":
        overall_ratio = 0
    else:
        overall_ratio = (1 - total_compressed / total_uncompressed) * 100

    # Calculate total reduction from original
    total_reduction = (1 - total_compressed / original_size) * 100

    print()
    print("=" * 65)
    print("COMPLETE!")
    print("=" * 65)
    print(f"Created {len(output_paths)} file(s) using {method_name}")
    print(f"Original PDF: {format_size(original_size)}")
    print(f"Final total: {format_size(total_compressed)} ({total_reduction:.1f}% total reduction)")
    print(f"Location: {output_dir}")
    print()

    # Show success dialog
    messagebox.showinfo(
        "PDF Splitter Complete",
        f"Created {len(output_paths)} file(s)\n"
        f"Method: {method_name}\n\n"
        f"Original: {format_size(original_size)}\n"
        f"Final: {format_size(total_compressed)}\n"
        f"Total reduction: {total_reduction:.1f}%\n\n"
        f"Location:\n{output_dir}"
    )

    # Open output folder
    if sys.platform == 'win32':
        os.startfile(output_dir)
    elif sys.platform == 'darwin':
        os.system(f'open "{output_dir}"')
    else:
        os.system(f'xdg-open "{output_dir}"')


def open_output_folder(path: str):
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


def merge_pdfs(input_paths: list[str], output_path: str, progress_callback=None):
    writer = PdfWriter()
    total = len(input_paths)
    for i, path in enumerate(input_paths):
        if progress_callback:
            progress_callback(i + 1, total, f"Merging: {os.path.basename(path)}")
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, 'wb') as f:
        writer.write(f)
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="PDF Splitter — Split PDFs by size and compress into archives.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pdf_splitter.py input.pdf --size 5
  python pdf_splitter.py input.pdf -s 10 --method zip_bzip2
  python pdf_splitter.py input.pdf -s 5 --optimize --quality high
  python pdf_splitter.py file1.pdf file2.pdf -o merged.pdf --merge
  python pdf_splitter.py input.pdf -s 5 --dry-run
        """)
    parser.add_argument("input", nargs="?", help="Input PDF file")
    parser.add_argument("-o", "--output", help="Output file or directory")
    parser.add_argument("-s", "--size", type=float, help="Target chunk size in MB")
    parser.add_argument("-m", "--method",
                       choices=[m[0] for m in COMPRESSION_METHODS if m[4]],
                       help="Compression method")
    parser.add_argument("--optimize", action="store_true", help="Optimize before splitting")
    parser.add_argument("--quality", choices=["high", "medium", "low", "screen"],
                       help="Image quality preset")
    parser.add_argument("--merge", action="store_true", help="Merge multiple PDFs into one")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--no-open", action="store_true", help="Don't open output folder")
    return parser.parse_args()


def run_merge_cli(args):
    input_paths = []
    if args.input:
        input_paths.append(args.input)
    output_path = args.output or "merged.pdf"
    print("Merging PDFs...")
    def cb(c, t, s=""):
        pct = (c/t*100) if t > 0 else 0
        print(f"\r  [{c}/{t}] {pct:.0f}% - {s}", end="", flush=True)
    merge_pdfs(input_paths, output_path, cb)
    print()
    print(f"Merged PDF saved: {output_path} ({format_size(os.path.getsize(output_path))})")
    if not args.no_open:
        open_output_folder(os.path.dirname(output_path) or ".")


def run_split_cli(args, pdf_path: str):
    original_size = os.path.getsize(pdf_path)
    file_size_mb = original_size / (1024 * 1024)
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    print(f"File: {pdf_path}")
    print(f"Size: {format_size(original_size)} | Pages: {total_pages}")

    optimization = None
    if args.optimize:
        optimization = {
            "compress_images": HAS_PIL,
            "image_quality": args.quality or "medium",
            "remove_metadata": True,
            "compress_streams": True,
        }

    working_pdf = pdf_path
    optimized_path = None
    if optimization:
        print("Optimizing...")
        pdf_dir = os.path.dirname(pdf_path) or "."
        pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        optimized_path = os.path.join(pdf_dir, f"{pdf_name}_optimized.pdf")

        def cb(c, t, s=""):
            pct = (c/t*100) if t > 0 else 0
            print(f"\r  {s} [{c}/{t}] {pct:.0f}%", end="", flush=True)
        success, msg, stats = optimize_pdf_advanced(pdf_path, optimized_path, optimization, cb)
        print()
        if success:
            reduction = stats.get("reduction_percent", 0)
            print(f"  Optimized: {format_size(stats['final_size'])} ({reduction:.1f}% reduction)")
            if reduction > 1:
                working_pdf = optimized_path
                reader = PdfReader(optimized_path)
            else:
                os.remove(optimized_path)
                optimized_path = None
        else:
            print(f"  {msg}")
            optimized_path = None

    target_mb = args.size or max(1.0, round(file_size_mb / 4, 1))
    target_bytes = int(target_mb * 1024 * 1024)
    method_id = args.method or "zip_deflate"
    method_name = next((m[1] for m in COMPRESSION_METHODS if m[0] == method_id), "ZIP Deflate")
    print(f"Chunk size: {target_mb} MB | Compression: {method_name}")

    pdf_dir = os.path.dirname(pdf_path) or "."
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = os.path.join(pdf_dir, f"{pdf_name}_chunks")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output: {output_dir}")
    print()

    def cb(c, t, s=""):
        pct = (c/t*100) if t > 0 else 0
        bar_w = 30
        filled = int(bar_w * c / t)
        print(f"\r  [{'='*filled}{'-'*(bar_w-filled)}] {pct:.0f}% ({c}/{t}) {s}", end="", flush=True)

    chunks = split_pdf_by_size(reader, target_bytes, output_dir, pdf_name,
                               progress_callback=cb, dry_run=args.dry_run)
    print()

    if args.dry_run:
        print(f"DRY RUN: Would create {len(chunks)} chunk(s)")
        total_sz = sum(c['size_bytes'] for c in chunks)
        print(f"Total: {format_size(total_sz)}")
        if args.verbose:
            for c in chunks:
                print(f"  {c['filename']} ({c['num_pages']} pages, {c['size_formatted']})")
        return

    print(f"Compressing {len(chunks)} chunks...")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(lambda c: compress_file(c["path"], method_id, ".zip"), chunks))

    total_compressed = sum(r[1] for r in results)
    total_reduction = (1 - total_compressed / original_size) * 100

    for i, (out_path, comp_size) in enumerate(results):
        ratio = (1 - comp_size / chunks[i]["size_bytes"]) * 100 if chunks[i]["size_bytes"] > 0 else 0
        print(f"  {os.path.basename(out_path)} -> {format_size(comp_size)} ({ratio:.1f}% reduction)")

    cleanup_files([c["path"] for c in chunks])
    if optimized_path and os.path.exists(optimized_path):
        os.remove(optimized_path)

    print()
    print(f"Done! {len(results)} file(s) | {total_reduction:.1f}% total reduction | {output_dir}")
    if not args.no_open:
        open_output_folder(output_dir)


def main():
    args = parse_args()

    if args.merge:
        if args.input:
            run_merge_cli(args)
        else:
            root = get_shared_root()
            if root is None:
                root = tk.Tk()
                root.withdraw()
            paths = filedialog.askopenfilenames(
                parent=root, title="Select PDFs to Merge",
                filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")])
            if not paths:
                return
            out_dir = os.path.dirname(paths[0]) or "."
            output = os.path.join(out_dir, "merged.pdf")
            def cb(c, t, s=""):
                pct = (c/t*100) if t > 0 else 0
                print(f"\r  [{c}/{t}] {pct:.0f}% - {s}", end="", flush=True)
            merge_pdfs(list(paths), output, cb)
            print()
            print(f"Saved: {output} ({format_size(os.path.getsize(output))})")
            open_output_folder(out_dir)
        return

    if args.input:
        run_split_cli(args, args.input)
        return

    print("=" * 65)
    print("PDF Splitter v1.5")
    print("=" * 65)
    print()
    print(f"Compression methods: {len(get_available_methods())}")
    print(f"Image optimization: {'Yes' if HAS_PIL else 'No (install Pillow)'}")
    print()

    pdf_path = select_pdf_file()
    if not pdf_path:
        print("No file selected. Exiting.")
        return

    original_size = os.path.getsize(pdf_path)
    file_size_mb = original_size / (1024 * 1024)
    print(f"Selected: {pdf_path}")
    print(f"File size: {format_size(original_size)}")

    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        print(f"Total pages: {total_pages}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read PDF:\n{e}")
        return

    print()
    optimization = select_optimization_options()

    working_pdf = pdf_path
    optimized_path = None

    if optimization:
        print("Optimization selected:")
        print(f"  - Compress images: {optimization.get('compress_images', False)}")
        print(f"  - Remove metadata: {optimization.get('remove_metadata', False)}")
        print(f" - Compress streams: {optimization.get('compress_streams', False)}")
        print()
        print("Optimizing PDF...")
        pdf_dir = os.path.dirname(pdf_path)
        pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        optimized_path = os.path.join(pdf_dir, f"{pdf_name}_optimized.pdf")

        pw = ProgressWindow("Optimizing PDF...")
        def cb(c, t, s=""):
            if not pw.update(c, t, s):
                raise KeyboardInterrupt("Cancelled")
        try:
            success, msg, stats = optimize_pdf_advanced(pdf_path, optimized_path, optimization, cb)
        finally:
            pw.close()

        if success:
            reduction = stats.get("reduction_percent", 0)
            print(f"  Original: {format_size(original_size)}")
            print(f"  Optimized: {format_size(stats['final_size'])} ({reduction:.1f}% reduction)")
            if reduction > 1:
                working_pdf = optimized_path
                reader = PdfReader(optimized_path)
            else:
                os.remove(optimized_path)
                optimized_path = None
        else:
            print(f"  {msg}")
            optimized_path = None
    else:
        print("Optimization skipped.")

    file_size_mb = os.path.getsize(working_pdf) / (1024 * 1024)
    print()
    target_mb = get_target_size_mb(file_size_mb)
    if not target_mb:
        if optimized_path:
            os.remove(optimized_path)
        return

    target_bytes = int(target_mb * 1024 * 1024)
    print(f"Target chunk size: {target_mb:.2f} MB")
    print()
    compression = select_compression_method()
    if not compression:
        if optimized_path:
            os.remove(optimized_path)
        return

    method_id, method_name, extension = compression
    print(f"Compression: {method_name}")
    print()
    pdf_dir = os.path.dirname(pdf_path)
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = os.path.join(pdf_dir, f"{pdf_name}_chunks")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")
    print()

    print("Splitting PDF...")
    pw = ProgressWindow("Splitting PDF...")
    def cb(c, t, s=""):
        if not pw.update(c, t, s):
            raise KeyboardInterrupt("Cancelled")

    try:
        chunks = split_pdf_by_size(reader, target_bytes, output_dir, pdf_name,
                                  progress_callback=cb, dry_run=False)
    finally:
        pw.close()

    print()
    print(f"Compressing {len(chunks)} chunks with {method_name}...")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(lambda c: compress_file(c["path"], method_id, extension), chunks))

    output_paths = []
    total_uncompressed = sum(c["size_bytes"] for c in chunks)
    total_compressed = sum(r[1] for r in results)
    total_reduction = (1 - total_compressed / original_size) * 100

    for i, (out_path, comp_size) in enumerate(results):
        ratio = (1 - comp_size / chunks[i]["size_bytes"]) * 100 if chunks[i]["size_bytes"] > 0 else 0
        print(f"  {os.path.basename(out_path)} -> {format_size(comp_size)} ({ratio:.1f}% reduction)")
        output_paths.append(out_path)

    cleanup_files([c["path"] for c in chunks])
    if optimized_path and os.path.exists(optimized_path):
        os.remove(optimized_path)

    print()
    print("=" * 65)
    print("COMPLETE!")
    print("=" * 65)
    print(f"Created {len(output_paths)} file(s) | {method_name}")
    print(f"Original: {format_size(original_size)}")
    print(f"Final: {format_size(total_compressed)} ({total_reduction:.1f}% reduction)")
    print(f"Location: {output_dir}")

    messagebox.showinfo("PDF Splitter Complete",
        f"Created {len(output_paths)} file(s)\n"
        f"Method: {method_name}\n"
        f"Original: {format_size(original_size)}\n"
        f"Final: {format_size(total_compressed)} ({total_reduction:.1f}%)\n\n"
        f"Location:\n{output_dir}")
    open_output_folder(output_dir)


if __name__ == "__main__":
    main()
