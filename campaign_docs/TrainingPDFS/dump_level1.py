import json

with open('ebp_extracted.json', encoding='utf-8') as f:
    data = json.load(f)

lines = []
for p in data['level1']:
    idx = p['idx']
    style = p['style']
    text = p['text']
    lines.append(f'[{idx}][{style}] {text}')

with open('level1_readable.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Written {len(lines)} lines')
