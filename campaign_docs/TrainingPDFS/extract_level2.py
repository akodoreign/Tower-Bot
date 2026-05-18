import docx, json

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

# Level II core: 2533-2572
level2_core = dump_range(2533, 2572, 'LEVEL II CORE')

# Chapter 6 Level II supplement: 3478-3484
level2_supp = dump_range(3478, 3485, 'LEVEL II CH6 SUPPLEMENT')

# Intellect devourer stat block in appendix B
# Search for it
print('\n=== SEARCHING FOR INTELLECT DEVOURER ===')
for i, p in enumerate(doc.paragraphs[3884:4800]):
    idx = i + 3884
    text = p.text.strip()
    if 'INTELLECT' in text.upper() or 'DEVOURER' in text.upper():
        print(f'[{idx}][{p.style.name}] {text[:120]}')

# Also look for wheely sled in appendix C
print('\n=== SEARCHING FOR WHEELY SLED ===')
for i, p in enumerate(doc.paragraphs[4798:5090]):
    idx = i + 4798
    text = p.text.strip()
    if 'WHEELY' in text.upper() or 'SLED' in text.upper():
        print(f'[{idx}][{p.style.name}] {text[:120]}')
