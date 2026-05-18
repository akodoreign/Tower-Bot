"""Dump Level VI content from the EBP docx - fixed syntax."""
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

# Level VI main content (5e section)
dump_range(2946, 3200, 'LEVEL VI MAIN PART 1')
dump_range(3200, 3385, 'LEVEL VI MAIN PART 2')

# Chapter 6 Level VI additional encounters
dump_range(3575, 3880, 'LEVEL VI CH6')
