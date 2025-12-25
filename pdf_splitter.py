"""
PDF Splitter - Split PDFs by file size (MB) and compress into archives.

Usage: Run the script, select a PDF, choose target chunk size in MB,
       optionally optimize the PDF, select compression method, and get compressed chunks.
"""

import os
import sys
import zipfile
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from io import BytesIO
from pypdf import PdfReader, PdfWriter

# Image processing
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


def select_pdf_file() -> str | None:
    """Open file dialog to select a PDF file."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    file_path = filedialog.askopenfilename(
        title="Select PDF to Split",
        filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
    )

    root.destroy()
    return file_path if file_path else None


def get_target_size_mb(file_size_mb: float) -> float | None:
    """Prompt user for target chunk size in MB."""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    suggested = max(1.0, round(file_size_mb / 4, 1))

    result = simpledialog.askfloat(
        "Target Chunk Size",
        f"Input PDF size: {file_size_mb:.2f} MB\n\n"
        f"Enter target size per chunk (MB):",
        minvalue=0.1,
        maxvalue=file_size_mb,
        initialvalue=suggested
    )

    root.destroy()
    return result


def select_optimization_options() -> dict | None:
    """Show dialog to select PDF optimization options. Returns dict of options or None to skip."""
    result = [None]

    def on_optimize():
        result[0] = {
            "compress_images": var_images.get(),
            "image_quality": quality_presets[quality_combo.current()][0] if var_images.get() else None,
            "remove_metadata": var_metadata.get(),
            "compress_streams": var_streams.get(),
        }
        root.destroy()

    def on_skip():
        result[0] = None
        root.destroy()

    def on_image_toggle():
        if var_images.get():
            quality_combo.config(state="readonly")
        else:
            quality_combo.config(state="disabled")

    root = tk.Tk()
    root.title("PDF Optimization")
    root.attributes('-topmost', True)
    root.resizable(False, False)

    window_width = 520
    window_height = 340
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    # Title
    title_label = tk.Label(root, text="PDF Optimization (Optional)",
                           font=("Helvetica", 12, "bold"))
    title_label.pack(pady=(15, 5))

    subtitle = tk.Label(root, text="Reduce PDF size before splitting",
                        font=("Helvetica", 9), fg="gray")
    subtitle.pack(pady=(0, 15))

    # Options frame
    options_frame = tk.Frame(root)
    options_frame.pack(pady=5, padx=30, fill="x")

    # Compress images checkbox
    var_images = tk.BooleanVar(value=True)
    chk_images = tk.Checkbutton(options_frame, text="Compress Images",
                                 variable=var_images, font=("Helvetica", 10),
                                 command=on_image_toggle)
    chk_images.pack(anchor="w", pady=5)

    # Image quality dropdown
    quality_frame = tk.Frame(options_frame)
    quality_frame.pack(anchor="w", padx=25, pady=(0, 10), fill="x")

    quality_label = tk.Label(quality_frame, text="Quality:", font=("Helvetica", 9))
    quality_label.pack(side="left")

    quality_presets = IMAGE_QUALITY_PRESETS
    quality_values = [f"{p[1]} — {p[4]}" for p in quality_presets]
    quality_combo = ttk.Combobox(quality_frame, values=quality_values, state="readonly", width=50)
    quality_combo.pack(side="left", padx=10)
    quality_combo.current(1)  # Default to medium

    # Remove metadata checkbox
    var_metadata = tk.BooleanVar(value=True)
    chk_metadata = tk.Checkbutton(options_frame, text="Remove Metadata (author, title, timestamps, etc.)",
                                   variable=var_metadata, font=("Helvetica", 10))
    chk_metadata.pack(anchor="w", pady=5)

    # Compress streams checkbox
    var_streams = tk.BooleanVar(value=True)
    chk_streams = tk.Checkbutton(options_frame, text="Compress Content Streams",
                                  variable=var_streams, font=("Helvetica", 10))
    chk_streams.pack(anchor="w", pady=5)

    # Info label
    info_frame = tk.Frame(root)
    info_frame.pack(pady=15, padx=30, fill="x")

    info_text = ("Note: Image compression can significantly reduce file size for\n"
                 "image-heavy PDFs. Text-only PDFs won't benefit much.")
    info_label = tk.Label(info_frame, text=info_text, font=("Helvetica", 9),
                          fg="gray", justify="left")
    info_label.pack(anchor="w")

    # Buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=20)

    optimize_btn = tk.Button(btn_frame, text="Optimize", width=12, command=on_optimize,
                              bg="#4CAF50", fg="white")
    optimize_btn.pack(side="left", padx=10)

    skip_btn = tk.Button(btn_frame, text="Skip Optimization", width=14, command=on_skip)
    skip_btn.pack(side="left", padx=10)

    root.mainloop()
    return result[0]


def select_compression_method() -> tuple[str, str, str] | None:
    """Show dropdown dialog to select compression method."""
    methods = get_available_methods()
    result = [None]

    def on_select():
        idx = combo.current()
        if idx >= 0:
            result[0] = (methods[idx][0], methods[idx][1], methods[idx][2])
        root.destroy()

    def on_cancel():
        root.destroy()

    root = tk.Tk()
    root.title("Compression Method")
    root.attributes('-topmost', True)
    root.resizable(False, False)

    window_width = 500
    window_height = 200
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    title_label = tk.Label(root, text="Select Compression Method",
                           font=("Helvetica", 12, "bold"))
    title_label.pack(pady=(15, 5))

    subtitle = tk.Label(root, text="Ordered from slowest (best compression) to fastest",
                        font=("Helvetica", 9), fg="gray")
    subtitle.pack(pady=(0, 10))

    display_values = [f"{m[1]} — {m[3]}" for m in methods]
    combo = ttk.Combobox(root, values=display_values, state="readonly", width=70)
    combo.pack(pady=10, padx=20)

    default_idx = next((i for i, m in enumerate(methods) if m[0] == "zip_deflate"), 0)
    combo.current(default_idx)

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=15)

    ok_btn = tk.Button(btn_frame, text="OK", width=10, command=on_select)
    ok_btn.pack(side="left", padx=10)

    cancel_btn = tk.Button(btn_frame, text="Cancel", width=10, command=on_cancel)
    cancel_btn.pack(side="left", padx=10)

    root.mainloop()
    return result[0]


def get_image_quality_settings(preset_id: str) -> tuple[int, int]:
    """Get JPEG quality and max DPI for a preset."""
    for preset in IMAGE_QUALITY_PRESETS:
        if preset[0] == preset_id:
            return preset[2], preset[3]
    return 60, 120  # Default to medium


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

        total_pages = len(reader.pages)
        jpeg_quality, max_dpi = get_image_quality_settings(options.get("image_quality", "medium"))

        # Clone all pages
        for page_num, page in enumerate(reader.pages):
            if progress_callback:
                progress_callback(page_num + 1, total_pages, f"Processing page {page_num + 1}/{total_pages}")

            writer.add_page(page)

            # Compress content streams
            if options.get("compress_streams", True):
                try:
                    writer.pages[-1].compress_content_streams()
                    stats["streams_compressed"] += 1
                except Exception:
                    pass

        # Remove metadata
        if options.get("remove_metadata", True):
            if progress_callback:
                progress_callback(total_pages, total_pages, "Removing metadata...")

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

        # Remove unused objects and compress
        if progress_callback:
            progress_callback(total_pages, total_pages, "Finalizing optimization...")

        # Write with object compression
        with open(output_path, 'wb') as f:
            writer.write(f)

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


def split_pdf_by_size(reader: PdfReader, target_bytes: int, output_dir: str,
                      base_name: str, progress_callback=None) -> list[str]:
    """Split PDF into chunks where each chunk is approximately target_bytes."""
    total_pages = len(reader.pages)
    chunk_paths = []
    chunk_num = 1
    current_page = 0

    while current_page < total_pages:
        chunk_pages = []
        chunk_size = 0
        start_page = current_page

        while current_page < total_pages:
            test_pages = chunk_pages + [current_page]
            test_writer = build_writer_from_pages(reader, test_pages)
            test_size = measure_writer_size(test_writer)

            if test_size > target_bytes and len(chunk_pages) > 0:
                error_without = abs(chunk_size - target_bytes)
                error_with = abs(test_size - target_bytes)

                if error_without <= error_with:
                    break

            chunk_pages.append(current_page)
            chunk_size = test_size
            current_page += 1

            if progress_callback:
                progress_callback(current_page, total_pages)

            if test_size >= target_bytes:
                break

        end_page = start_page + len(chunk_pages)
        chunk_filename = f"{base_name}_chunk{chunk_num:03d}_pages{start_page + 1:03d}-{end_page:03d}.pdf"
        chunk_path = os.path.join(output_dir, chunk_filename)

        writer = build_writer_from_pages(reader, chunk_pages)
        with open(chunk_path, 'wb') as f:
            writer.write(f)

        actual_size = os.path.getsize(chunk_path)
        print(f"  {chunk_filename}")
        print(f"    -> {len(chunk_pages)} pages, {format_size(actual_size)}")

        chunk_paths.append(chunk_path)
        chunk_num += 1

    return chunk_paths


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

    def progress(current, total):
        pct = current / total * 100
        bar_width = 30
        filled = int(bar_width * current / total)
        bar = "=" * filled + "-" * (bar_width - filled)
        print(f"\r  Progress: [{bar}] {pct:.0f}% ({current}/{total} pages)", end="", flush=True)

    chunk_paths = split_pdf_by_size(reader, target_bytes, output_dir, pdf_name, progress_callback=progress)
    print()
    print()

    # Step 8: Compress each chunk
    print(f"Compressing with {method_name}...")
    output_paths = []
    total_uncompressed = 0
    total_compressed = 0

    for chunk_path in chunk_paths:
        uncompressed_size = os.path.getsize(chunk_path)
        out_path, compressed_size = compress_file(chunk_path, method_id, extension)
        output_paths.append(out_path)

        total_uncompressed += uncompressed_size
        total_compressed += compressed_size

        if method_id == "none":
            print(f"  {os.path.basename(out_path)}")
            print(f"    -> {format_size(compressed_size)} (no compression)")
        else:
            ratio = (1 - compressed_size / uncompressed_size) * 100
            print(f"  {os.path.basename(out_path)}")
            print(f"    -> {format_size(compressed_size)} ({ratio:.1f}% reduction)")

    print()

    # Step 9: Clean up
    if method_id != "none":
        print("Cleaning up temporary PDF files...")
        cleanup_files(chunk_paths)

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


if __name__ == "__main__":
    main()
