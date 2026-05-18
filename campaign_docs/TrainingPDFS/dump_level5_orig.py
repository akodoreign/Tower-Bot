"""Find original Level V and all its areas."""
import docx

doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

# Search for original Level V section
print('=== SEARCHING FOR TWEEN DECKS / LEVEL V ===')
for i, p in enumerate(doc.paragraphs):
    text = p.text.strip()
    if not text: continue
    upper = text.upper()
    if 'TWEEN DECK' in upper or ('SERVICE DECK 6' in upper) or ('LEVEL V' in upper and i < 700):
        print(f'[{i}][{p.style.name}] {text[:160]}')

# Dump original section ~620-640
print('\n=== ORIGINAL LEVEL V SECTION ===')
for i, p in enumerate(doc.paragraphs[620:700]):
    idx = i + 620
    text = p.text.strip()
    if text:
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# Also check the 5e re-print section around para 1374 for Level V
print('\n=== 5E REPRINT LEVEL V SEARCH ===')
for i, p in enumerate(doc.paragraphs[1450:1600]):
    idx = i + 1450
    text = p.text.strip()
    if not text: continue
    upper = text.upper()
    if 'TWEEN' in upper or 'SERVICE DECK 6' in upper or 'LEVEL V' in upper:
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# Dump the second reprint Level V section if it exists
print('\n=== REPRINT LEVEL V DUMP ===')
for i, p in enumerate(doc.paragraphs[1468:1560]):
    idx = i + 1468
    text = p.text.strip()
    if text:
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# What's the AREA numbering on level V? Look for areas 6-12
print('\n=== LEVEL V AREA 6-12 SEARCH ===')
for i, p in enumerate(doc.paragraphs[2908:2960]):
    idx = i + 2908
    text = p.text.strip()
    if text:
        print(f'[{idx}][{p.style.name}] {text[:160]}')
