"""
Generate test PDFs for testing the PDF splitter.
Creates larger files suitable for testing size-based chunking.
"""

import os
import random
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from io import BytesIO
from PIL import Image


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "test_pdfs")


def create_text_page(c, page_num, text_amount="normal"):
    """Add a text-only page."""
    c.setFont("Helvetica", 10)

    if text_amount == "minimal":
        lines = 5
    elif text_amount == "normal":
        lines = 60
    else:  # heavy
        lines = 100

    y = 770
    for i in range(lines):
        text = f"Page {page_num} Line {i+1}: " + "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore. " * 2
        c.drawString(40, y, text[:110])
        y -= 12
        if y < 30:
            break

    c.showPage()


def create_image_page(c, page_num, size_multiplier=1):
    """Add a page with a large uncompressed-style image."""
    # Bigger images = bigger PDF
    base_size = 1500
    img_width = int(base_size * size_multiplier)
    img_height = int(base_size * 0.75 * size_multiplier)

    # Create complex image (harder to compress)
    img = Image.new('RGB', (img_width, img_height))
    pixels = img.load()

    random.seed(page_num)  # Different but reproducible per page
    for x in range(img_width):
        for y in range(img_height):
            # Add noise to make it less compressible
            noise = random.randint(-30, 30)
            r = (int((x / img_width) * 200) + noise) % 256
            g = (int((y / img_height) * 200) + noise) % 256
            b = (int(((x * y) / (img_width * img_height)) * 200) + noise) % 256
            pixels[x, y] = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

    # Save as PNG (lossless)
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 770, f"Page {page_num} - Image ({img_width}x{img_height})")

    img_reader = ImageReader(buffer)
    c.drawImage(img_reader, 40, 100, width=530, height=400)
    c.showPage()


def create_test_10mb():
    """Create ~10MB PDF with mixed content."""
    print("Creating: test_10mb.pdf (~10MB target, mixed content)")
    path = os.path.join(OUTPUT_DIR, "test_10mb.pdf")
    c = canvas.Canvas(path, pagesize=letter)

    # Mix of text and images to hit ~10MB
    for i in range(60):
        if i % 4 == 0:
            create_image_page(c, i + 1, size_multiplier=1.5)
        else:
            create_text_page(c, i + 1, "heavy")

    c.save()
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  -> Created: {size_mb:.2f} MB, 60 pages")
    return path


def create_test_25mb():
    """Create ~25MB PDF with mostly images."""
    print("Creating: test_25mb.pdf (~25MB target, image-heavy)")
    path = os.path.join(OUTPUT_DIR, "test_25mb.pdf")
    c = canvas.Canvas(path, pagesize=letter)

    for i in range(80):
        if i % 3 == 0:
            create_text_page(c, i + 1, "normal")
        else:
            create_image_page(c, i + 1, size_multiplier=1.2)

    c.save()
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  -> Created: {size_mb:.2f} MB, 80 pages")
    return path


def create_test_variable():
    """Create PDF with highly variable page sizes."""
    print("Creating: test_variable.pdf (variable page sizes)")
    path = os.path.join(OUTPUT_DIR, "test_variable.pdf")
    c = canvas.Canvas(path, pagesize=letter)

    random.seed(42)

    # Pattern: small, small, small, HUGE, small, small, HUGE, etc.
    for i in range(50):
        if i % 7 == 0:
            # Big image page
            create_image_page(c, i + 1, size_multiplier=2.0)
        elif i % 7 == 3:
            # Medium image
            create_image_page(c, i + 1, size_multiplier=1.0)
        else:
            # Small text page
            create_text_page(c, i + 1, "minimal")

    c.save()
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  -> Created: {size_mb:.2f} MB, 50 pages")
    return path


def create_test_one_giant():
    """Create PDF where one page is much larger than others."""
    print("Creating: test_one_giant.pdf (1 huge page + 29 tiny)")
    path = os.path.join(OUTPUT_DIR, "test_one_giant.pdf")
    c = canvas.Canvas(path, pagesize=letter)

    # Page 1: Giant 4K-ish noisy image
    img_width, img_height = 3000, 2000
    img = Image.new('RGB', (img_width, img_height))
    pixels = img.load()
    random.seed(999)
    for x in range(img_width):
        for y in range(img_height):
            pixels[x, y] = (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255)
            )

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, 770, "Page 1 - GIANT IMAGE (3000x2000 noisy)")
    img_reader = ImageReader(buffer)
    c.drawImage(img_reader, 40, 100, width=530, height=350)
    c.showPage()

    # Rest: tiny text pages
    for i in range(2, 31):
        create_text_page(c, i, "minimal")

    c.save()
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  -> Created: {size_mb:.2f} MB, 30 pages")
    return path


def create_test_uniform():
    """Create PDF with uniform page sizes."""
    print("Creating: test_uniform.pdf (all pages same size)")
    path = os.path.join(OUTPUT_DIR, "test_uniform.pdf")
    c = canvas.Canvas(path, pagesize=letter)

    for i in range(100):
        create_image_page(c, i + 1, size_multiplier=0.8)

    c.save()
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  -> Created: {size_mb:.2f} MB, 100 pages")
    return path


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("Creating Test PDFs for PDF Splitter")
    print("=" * 60)
    print()

    create_test_10mb()
    create_test_25mb()
    create_test_variable()
    create_test_one_giant()
    create_test_uniform()

    print()
    print("=" * 60)
    print(f"Test PDFs created in: {OUTPUT_DIR}")
    print("=" * 60)

    # Summary
    print()
    print("Test Cases:")
    print("-" * 60)
    total = 0
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f.endswith('.pdf'):
            path = os.path.join(OUTPUT_DIR, f)
            size = os.path.getsize(path)
            total += size
            print(f"  {f:30} {size / (1024*1024):>8.2f} MB")
    print("-" * 60)
    print(f"  {'Total':30} {total / (1024*1024):>8.2f} MB")
    print()
    print("Suggested tests:")
    print("  - test_10mb.pdf with 3MB chunks -> expect ~3-4 chunks")
    print("  - test_25mb.pdf with 5MB chunks -> expect ~5 chunks")
    print("  - test_variable.pdf with 2MB chunks -> tests uneven pages")
    print("  - test_one_giant.pdf with 2MB chunks -> tests oversized single page")
    print("  - test_uniform.pdf with 5MB chunks -> baseline comparison")


if __name__ == "__main__":
    main()
