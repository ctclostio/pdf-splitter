"""
PDF Splitter - Split PDFs by file size (MB) and compress into ZIP files.

Usage: Run the script, select a PDF, choose target chunk size in MB,
       and get zipped chunks that each approximate your target size.
"""

import os
import sys
import zipfile
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from pypdf import PdfReader, PdfWriter


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

    # Suggest a reasonable default (split into ~4-5 chunks, min 1 MB)
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


def plan_chunks(total_pages: int, file_size_bytes: int, target_bytes: int) -> list[tuple[int, int]]:
    """
    Plan chunks by distributing pages proportionally to achieve target sizes.

    Uses actual file size for calculation - avoids the overestimation problem
    caused by shared PDF resources (fonts, images) when measuring pages individually.

    Returns list of (start_page, end_page) tuples (0-indexed, end exclusive).
    """
    # Calculate number of chunks needed
    num_chunks = max(1, round(file_size_bytes / target_bytes))

    # Distribute pages evenly across chunks
    pages_per_chunk = total_pages / num_chunks

    chunks = []
    for i in range(num_chunks):
        start = round(i * pages_per_chunk)
        end = round((i + 1) * pages_per_chunk)
        if start < total_pages:
            chunks.append((start, min(end, total_pages)))

    return chunks


def create_chunk_pdf(reader: PdfReader, start_page: int, end_page: int, output_path: str) -> int:
    """
    Create a PDF chunk from the specified page range.

    Returns the actual file size in bytes.
    """
    writer = PdfWriter()
    for i in range(start_page, end_page):
        writer.add_page(reader.pages[i])

    with open(output_path, 'wb') as f:
        writer.write(f)

    return os.path.getsize(output_path)


def compress_to_zip(pdf_path: str) -> tuple[str, int]:
    """
    Compress a PDF file into a ZIP archive.

    Returns (zip_path, zip_size_bytes).
    """
    zip_path = pdf_path.replace('.pdf', '.zip')
    pdf_filename = os.path.basename(pdf_path)

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(pdf_path, pdf_filename)

    return zip_path, os.path.getsize(zip_path)


def cleanup_pdfs(pdf_paths: list[str]) -> None:
    """Remove intermediate PDF chunk files after zipping."""
    for path in pdf_paths:
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
    print("=" * 60)
    print("PDF Splitter v1.0 - Split by Size")
    print("=" * 60)
    print()

    # Step 1: Select PDF file
    print("Opening file dialog...")
    pdf_path = select_pdf_file()

    if not pdf_path:
        print("No file selected. Exiting.")
        return

    print(f"Selected: {pdf_path}")

    # Step 2: Get file size and basic info
    file_size_bytes = os.path.getsize(pdf_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    print(f"File size: {format_size(file_size_bytes)}")

    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        print(f"Total pages: {total_pages}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to read PDF:\n{e}")
        print(f"Error reading PDF: {e}")
        return

    print()

    # Step 3: Get target chunk size from user
    target_mb = get_target_size_mb(file_size_mb)

    if not target_mb:
        print("No target size entered. Exiting.")
        return

    target_bytes = int(target_mb * 1024 * 1024)
    print(f"Target chunk size: {target_mb:.2f} MB")

    # Step 4: Plan chunks using proportional distribution
    chunks = plan_chunks(total_pages, file_size_bytes, target_bytes)
    estimated_per_chunk = file_size_bytes / len(chunks)
    print(f"Planned {len(chunks)} chunk(s) (~{format_size(int(estimated_per_chunk))} each)")
    print()

    # Step 5: Create output directory
    pdf_dir = os.path.dirname(pdf_path)
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = os.path.join(pdf_dir, f"{pdf_name}_chunks")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")
    print()

    # Step 6: Create chunk PDFs
    print("Creating PDF chunks...")
    chunk_paths = []

    for chunk_num, (start, end) in enumerate(chunks, 1):
        chunk_filename = f"{pdf_name}_chunk{chunk_num:03d}_pages{start + 1:03d}-{end:03d}.pdf"
        chunk_path = os.path.join(output_dir, chunk_filename)

        actual_size = create_chunk_pdf(reader, start, end, chunk_path)
        chunk_paths.append(chunk_path)

        pages_in_chunk = end - start
        print(f"  {chunk_filename}")
        print(f"    -> {pages_in_chunk} pages, {format_size(actual_size)}")

    print()

    # Step 7: Compress each chunk to ZIP
    print("Compressing to ZIP...")
    zip_paths = []
    total_uncompressed = 0
    total_compressed = 0

    for chunk_path in chunk_paths:
        uncompressed_size = os.path.getsize(chunk_path)
        zip_path, compressed_size = compress_to_zip(chunk_path)
        zip_paths.append(zip_path)

        total_uncompressed += uncompressed_size
        total_compressed += compressed_size

        ratio = (1 - compressed_size / uncompressed_size) * 100
        print(f"  {os.path.basename(zip_path)}")
        print(f"    -> {format_size(compressed_size)} ({ratio:.1f}% reduction)")

    print()

    # Step 8: Clean up intermediate PDFs
    print("Cleaning up temporary PDF files...")
    cleanup_pdfs(chunk_paths)

    # Summary
    overall_ratio = (1 - total_compressed / total_uncompressed) * 100
    print()
    print("=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print(f"Created {len(zip_paths)} ZIP file(s)")
    print(f"Total size: {format_size(total_compressed)} ({overall_ratio:.1f}% compression)")
    print(f"Location: {output_dir}")
    print()

    # Show success dialog
    messagebox.showinfo(
        "PDF Splitter Complete",
        f"Created {len(zip_paths)} ZIP file(s)\n\n"
        f"Total: {format_size(total_compressed)}\n"
        f"Compression: {overall_ratio:.1f}%\n\n"
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
