"""Dump Level IV Appendix B creatures."""
import docx

doc = docx.Document(r'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx')

# Search appendix B more broadly for Level IV creatures
print('=== LEVEL IV APPENDIX B CREATURES ===')
creatures = [
    'PURPLE BLOSSOM', 'TRI-FLOWER', 'SNAPPER', 'HORRID PLANT',
    'GLOBE PALM', 'LEECHOID', 'BORING GRASS', 'LIZARDOID',
    'AURUMVORAX', 'BABOONOID', 'SQUEALER', 'WOLF-IN-SHEEP',
    'LIVING BURROW', 'FLAIL SNAIL', 'FROGHEMOTH', 'OTYUGH',
    'SHAMBLING MOUND', 'ROT GRUB', 'CHUUL', 'UMBER HULK',
    'BLACK PUDDING', 'GASBAT', 'GAS BAT'
]

for i, p in enumerate(doc.paragraphs[3884:5090]):
    idx = i + 3884
    text = p.text.strip()
    if not text:
        continue
    upper = text.upper()
    if any(kw in upper for kw in creatures):
        if len(text) < 200:  # likely a heading or short stat line
            print(f'[{idx}][{p.style.name}] {text}')

# Now dump full content of key stat blocks
print('\n\n=== DUMPING APPENDIX B RANGE 3884-4600 ===')
in_creature = False
for i, p in enumerate(doc.paragraphs[3884:4600]):
    idx = i + 3884
    text = p.text.strip()
    if not text:
        continue
    # Only print Heading styles (stat block headers) and content near them
    if 'Heading' in p.style.name or any(kw in text.upper() for kw in [
        'PURPLE BLOSSOM', 'TRI-FLOWER', 'SNAPPER-SAW', 'HORRID PLANT',
        'GLOBE PALM', 'LEECHOID', 'BORING GRASS', 'LIZARDOID',
        'AURUMVORAX', 'BABOONOID', 'SQUEALER', 'WOLF-IN-SHEEP',
        'LIVING BURROW', 'FLAIL SNAIL', 'FROGHEMOTH', 'OTYUGH',
        'SHAMBLING MOUND', 'ROT GRUB', 'CHUUL', 'UMBER HULK',
        'BLACK PUDDING', 'GASBAT', 'GAS BAT'
    ]):
        print(f'[{idx}][{p.style.name}] {text[:150]}')
        in_creature = True
    elif in_creature:
        print(f'[{idx}][{p.style.name}] {text[:150]}')
        # Stop after 30 lines per creature section
