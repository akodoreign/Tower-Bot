"""Get weightlifting android and karate continuation."""
import docx
doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            print(f'[{idx}][{p.style.name}] {text[:160]}')
    print()

print('=== WEIGHTLIFTING ANDROID (4730-4760) ===')
dump_range(4730, 4760, 'WEIGHTLIFTING')

print('=== KARATE ANDROID CONTINUATION (4218-4226) ===')
dump_range(4218, 4226, 'KARATE')

print('=== VAMPOID STAT BLOCK ===')
dump_range(4597, 4618, 'VAMPOID')
