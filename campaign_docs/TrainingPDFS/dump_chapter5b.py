"""Dump Chapter 5 areas 1-3, 1-4A, and 1-7A."""
import docx
doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            print(f'[{idx}][{p.style.name}] {text[:200]}')
    print()

# Scan 3185-3225 for Area 1-3 and 1-4
print('=== AREA 1-2 through 1-4A (3205-3225) ===')
dump_range(3205, 3225, 'AREAS 1-2 TO 1-4A')

# Area 1-7 main (between galeb duhr end and 1-7B)
print('=== AREA 1-7 MAIN + FRUMMACH (3268-3302) ===')
dump_range(3268, 3302, 'AREA 1-7 MAIN')

# Check invaders' encampment full text including Stealth consequence
print('=== INVADERS ENCAMPMENT DEVELOPMENTS (3276-3285) ===')
dump_range(3276, 3284, 'INVADERS ENCAMPMENT DEV')
