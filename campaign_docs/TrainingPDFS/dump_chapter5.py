"""Dump Chapter 5 missing sections."""
import docx
doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            print(f'[{idx}][{p.style.name}] {text[:200]}')
    print()

# Chapter 5 overview + general features
print('=== CHAPTER 5 START (3120-3135) ===')
dump_range(3120, 3135, 'CH5 START')

# Area 1-3 sacked keep and 1-4A cloakers
print('=== SEARCHING FOR AREA 1-3 AND 1-4A ===')
for i, p in enumerate(doc.paragraphs[3120:3340]):
    idx = i + 3120
    text = p.text.strip()
    if not text: continue
    if any(kw in text.upper() for kw in ['AREA 1-3', 'AREA 1-4', '1-4A', 'CLOAKER', 'SACKED', 'RUINED', 'ATTACKED']):
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# Full Chapter 5 area headings
print('\n=== CHAPTER 5 ALL HEADINGS ===')
for i, p in enumerate(doc.paragraphs[3120:3340]):
    idx = i + 3120
    text = p.text.strip()
    if not text: continue
    if 'Heading' in p.style.name or 'AREA' in text.upper():
        print(f'[{idx}][{p.style.name}] {text[:120]}')

# Area 1-3 detailed search
print('\n=== AREA 1-3 RANGE ===')
dump_range(3153, 3200, 'AREA 1-3 AND 1-4')

# Area 1-4A cloakers
print('\n=== AREA 1-4A RANGE (3218-3235) ===')
dump_range(3218, 3240, 'AREA 1-4A')

# Area 1-7A stone giant main area
print('\n=== AREA 1-7 STONE GIANT ===')
for i, p in enumerate(doc.paragraphs[3260:3305]):
    idx = i + 3260
    text = p.text.strip()
    if text:
        print(f'[{idx}][{p.style.name}] {text[:160]}')
