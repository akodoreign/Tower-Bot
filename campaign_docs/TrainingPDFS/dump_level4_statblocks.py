"""Dump Level IV Appendix B creature stat blocks - focused dump."""
import docx

doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    out = []
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            out.append({'idx': idx, 'style': p.style.name, 'text': text})
    print(f'\n=== {label} ===')
    for p in out:
        print(f'[{p["idx"]}][{p["style"]}] {p["text"][:160]}')
    return out

# First find headings in appendix B to locate creatures
print('=== APPENDIX B HEADINGS (3884-4600) ===')
for i, p in enumerate(doc.paragraphs[3884:4600]):
    idx = i + 3884
    if 'Heading' in p.style.name and p.text.strip():
        print(f'[{idx}][{p.style.name}] {p.text.strip()}')

print('\n=== APPENDIX B HEADINGS (4600-4800) ===')
for i, p in enumerate(doc.paragraphs[4600:4800]):
    idx = i + 4600
    if ('Heading' in p.style.name or 'heading' in p.style.name.lower()) and p.text.strip():
        print(f'[{idx}][{p.style.name}] {p.text.strip()}')
