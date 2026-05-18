"""Dump Level V content from the EBP docx."""
import docx

doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    out = []
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            out.append({'idx': idx, 'style': p.style.name, 'text': text})
    print(f'\n=== {label} ({len(out)} paras) ===')
    for p in out:
        print(f'[{p["idx"]}][{p["style"]}] {p["text"]}')
    return out

# Level V main content
dump_range(2908, 2960, 'LEVEL V MAIN')

# Search for Chapter 6 Level V additional encounters
print('\n=== SEARCHING FOR LEVEL V CH6 ===')
for i, p in enumerate(doc.paragraphs[3400:3520]):
    idx = i + 3400
    text = p.text.strip()
    if text and ('LEVEL V' in text.upper() or 'GARDEN' in text.upper() and 'TWEEN' in text.upper()):
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# Also search broadly
print('\n=== SEARCHING FULL DOC FOR LEVEL V CH6 ===')
for i, p in enumerate(doc.paragraphs[3380:3515]):
    idx = i + 3380
    text = p.text.strip()
    if text:
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# Find original Level V section
print('\n=== ORIGINAL LEVEL V ===')
for i, p in enumerate(doc.paragraphs):
    text = p.text.strip()
    if 'LEVEL V' in text.upper() and 'SERVICE' in text.upper():
        print(f'[{i}][{p.style.name}] {text[:120]}')

# Check original ~633 area
dump_range(620, 640, 'ORIGINAL LEVEL V AREA')
