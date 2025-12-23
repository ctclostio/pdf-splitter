# PDF Splitter

Split PDFs into size-based chunks and compress them into ZIP files.

## How It Works

1. Select a PDF file via file explorer
2. See the file size and enter your target chunk size (in MB)
3. The program analyzes each page's size contribution
4. Pages are grouped into chunks that approximate your target size
5. Each chunk is saved as a PDF, then compressed to ZIP
6. All ZIPs are placed in a single output folder

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python pdf_splitter.py
```

## Output

- Creates `<filename>_chunks/` folder next to your source PDF
- Each chunk named: `document_chunk001_pages001-025.zip`
- Shows compression ratio for each chunk
- Auto-opens the output folder when complete

## Technical Notes

- Page sizes are estimated by extracting each page individually
- Because PDFs share resources (fonts, images), actual chunks will typically be slightly smaller than the target size
- Single pages that exceed the target size become their own chunk

## Building Standalone Executable

```bash
pip install pyinstaller
pyinstaller --onefile --windowed pdf_splitter.py
```

The `.exe` will be in `dist/` - no Python installation required to run it.
