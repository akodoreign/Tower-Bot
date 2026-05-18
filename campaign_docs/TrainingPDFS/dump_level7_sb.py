"""Get Level VII stat blocks."""
import docx
doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            print(f'[{idx}][{p.style.name}] {text[:160]}')
    print()

print('=== DEATH-DRINKER (3982-4012) ===')
dump_range(3982, 4012, 'DEATH-DRINKER')

print('=== TYPE ONE BIOLOGICAL ENTITY (4541-4565) ===')
dump_range(4541, 4565, 'TYPE ONE BE')

print('=== TYPE TWO BIOLOGICAL ENTITY (4560-4600) ===')
dump_range(4560, 4600, 'TYPE TWO BE')

print('=== PACIFIER ROBOT (4294-4325) ===')
dump_range(4294, 4325, 'PACIFIER ROBOT')

# Check what's in area 12 of Level VII
print('=== LEVEL VII AREA 12 (3692-3702) ===')
dump_range(3692, 3705, 'AREA 12')
