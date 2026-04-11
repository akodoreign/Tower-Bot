"""Extract text from training PDFs for analysis."""
import os
from pathlib import Path

# pip install pypdf if not installed
try:
    from pypdf import PdfReader
except ImportError:
    print("Installing pypdf...")
    os.system("pip install pypdf")
    from pypdf import PdfReader

PDF_DIR = Path(__file__).parent.parent / "campaign_docs" / "TrainingPDFS"
OUTPUT_DIR = PDF_DIR / "extracted"
OUTPUT_DIR.mkdir(exist_ok=True)

print(f"Looking for PDFs in: {PDF_DIR}")
print(f"Output directory: {OUTPUT_DIR}")
print()

for pdf_path in PDF_DIR.glob("*.pdf"):
    print(f"Processing: {pdf_path.name}")
    try:
        reader = PdfReader(pdf_path)
        text = ""
        # Extract first 20 pages (enough to see patterns)
        page_count = min(20, len(reader.pages))
        for i in range(page_count):
            page = reader.pages[i]
            text += f"\n\n--- PAGE {i+1} ---\n\n"
            extracted = page.extract_text()
            text += extracted if extracted else "[No text extracted]"
        
        output_path = OUTPUT_DIR / f"{pdf_path.stem}.txt"
        output_path.write_text(text, encoding="utf-8")
        print(f"  -> Saved to {output_path.name} ({page_count} pages)")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone! Text files saved to campaign_docs/TrainingPDFS/extracted/")
input("Press Enter to close...")
