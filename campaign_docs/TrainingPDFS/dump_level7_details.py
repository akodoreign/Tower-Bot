"""Get Level VII missing details."""
import docx
doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

def dump_range(start, end, label):
    for i, p in enumerate(doc.paragraphs[start:end]):
        idx = i + start
        text = p.text.strip()
        if text:
            print(f'[{idx}][{p.style.name}] {text[:200]}')
    print()

# Android programming center d4 table (3692 area)
print('=== AREA 11 ANDROID PROGRAMMING d4 TABLE (3690-3702) ===')
dump_range(3690, 3702, 'AREA 11 TABLE')

# Area 12 colonization housing with phase spiders (3695-3702)
print('=== AREA 12 COLONIZATION HOUSING (3695-3703) ===')
dump_range(3695, 3703, 'AREA 12')

# Area 27 behir (3806-3818)
print('=== AREA 27 BEHIR (3806-3818) ===')
dump_range(3806, 3818, 'AREA 27')

# Check for monoblade fire axe description
print('=== MONOBLADE FIRE AXE / SAMPLE COLLECTION PISTOL ===')
for i, p in enumerate(doc.paragraphs[4798:5090]):
    idx = i + 4798
    text = p.text.strip()
    if not text: continue
    upper = text.upper()
    if any(kw in upper for kw in ['MONOBLADE', 'SAMPLE', 'COLLECTION', 'HOLOGRAM EMITTER', 'ALL-WEATHER', 'WEATHER SHELTER']):
        print(f'[{idx}][{p.style.name}] {text[:160]}')

# Also get the area numbering for the death-drinker missing table item
print('\n=== AREA 19 DEVELOPMENT d4 TABLE ===')
dump_range(3760, 3775, 'AREA 19 DEVELOPMENT')
