"""Get Level V stat blocks."""
import docx
doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            print(f'[{idx}][{p.style.name}] {text[:160]}')
    print()

print('=== GREATER SLITHERING TRACKER ===')
dump_range(4138, 4165, 'GST')
