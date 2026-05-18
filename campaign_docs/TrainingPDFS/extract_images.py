"""
Extract images from the EBP docx.
- Deduplicates by SHA256 hash (book contains original scan + 5e reprint = duplicate images)
- Large images (>=500KB) -> maps/
- Medium images (5KB-500KB) -> images/
- Tiny (<5KB) -> skipped (decorative elements / borders)
- Files named with leading zero-padded number + context slug
"""
import zipfile, os, re, hashlib
from lxml import etree

DOCX       = 'Original Adventures Reincarnated #3 - Expedition to Barrier Peaks.docx'
OUT_MAPS   = 'maps'
OUT_IMAGES = 'images'
SIZE_MAP   = 500_000   # >= this -> maps/  (proper floor plans and full-page art)
SIZE_MIN   = 5_000     # < this  -> skip   (bullets, borders, decorative dots)

os.makedirs(OUT_MAPS,   exist_ok=True)
os.makedirs(OUT_IMAGES, exist_ok=True)

# ── 1. Read all media bytes ──────────────────────────────────────────────────
with zipfile.ZipFile(DOCX) as z:
    media_bytes = {}
    for name in z.namelist():
        if name.startswith('word/media/'):
            media_bytes[name] = z.read(name)
    doc_xml  = z.read('word/document.xml')
    try:
        rels_xml = z.read('word/_rels/document.xml.rels')
    except KeyError:
        rels_xml = b''

# ── 2. Build rId -> media filename map ──────────────────────────────────────
rId_to_media = {}
if rels_xml:
    root = etree.fromstring(rels_xml)
    for rel in root:
        rid    = rel.get('Id', '')
        target = rel.get('Target', '')
        if 'media/' in target:
            rId_to_media[rid] = 'word/' + target.lstrip('/')

# ── 3. Parse document XML ────────────────────────────────────────────────────
NS = {
    'w':   'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'a':   'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r':   'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'v':   'urn:schemas-microsoft-com:vml',
}

doc_root = etree.fromstring(doc_xml)
body     = doc_root.find('.//w:body', NS)

para_records = []
recent_text  = ''

for para in body.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
    para_text = ' '.join(t.strip() for t in para.itertext() if t.strip())

    rids = []
    for blip in para.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}blip'):
        rid = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
        if rid:
            rids.append(rid)
    for imgdata in para.iter('{urn:schemas-microsoft-com:vml}imagedata'):
        rid = imgdata.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        if rid:
            rids.append(rid)

    if para_text:
        recent_text = para_text
    if rids:
        para_records.append((recent_text, rids))

# ── 4. Flatten to (media_path, context_text) pairs ──────────────────────────
image_contexts = []
seen_media     = set()
for ctx_text, rids in para_records:
    for rid in rids:
        media = rId_to_media.get(rid)
        if media and media not in seen_media:
            seen_media.add(media)
            image_contexts.append((media, ctx_text))

for media_path in sorted(media_bytes.keys()):
    if media_path not in seen_media:
        image_contexts.append((media_path, ''))

# ── 5. Helpers ───────────────────────────────────────────────────────────────
def file_hash(data):
    return hashlib.sha256(data).hexdigest()

def slugify(text, maxlen=55):
    text = re.sub(r'[^\w\s\-]', ' ', text)
    text = re.sub(r'\s+', '_', text).strip('_')
    return text[:maxlen] if text else 'unnamed'

used_slugs = {}
def unique_slug(raw_slug):
    if raw_slug not in used_slugs:
        used_slugs[raw_slug] = 0
        return raw_slug
    used_slugs[raw_slug] += 1
    return f'{raw_slug}_{used_slugs[raw_slug]:02d}'

# ── 6. Extract (skip duplicates by hash) ────────────────────────────────────
seen_hashes  = set()
maps_count   = 0
images_count = 0
skipped_size = 0
skipped_dup  = 0

for media_path, ctx_text in image_contexts:
    data = media_bytes.get(media_path, b'')
    size = len(data)
    ext  = os.path.splitext(media_path)[1].lower() or '.bin'

    if size < SIZE_MIN:
        skipped_size += 1
        continue

    h = file_hash(data)
    if h in seen_hashes:
        skipped_dup += 1
        continue
    seen_hashes.add(h)

    orig_name = os.path.basename(media_path)
    num_match = re.search(r'(\d+)', orig_name)
    num_str   = num_match.group(1).zfill(4) if num_match else '0000'

    ctx_slug  = slugify(ctx_text) if ctx_text else 'no_context'
    raw_slug  = f'{num_str}_{ctx_slug}'
    slug      = unique_slug(raw_slug)
    filename  = f'{slug}{ext}'

    if size >= SIZE_MAP:
        dest = os.path.join(OUT_MAPS, filename)
        maps_count += 1
    else:
        dest = os.path.join(OUT_IMAGES, filename)
        images_count += 1

    with open(dest, 'wb') as f:
        f.write(data)

print(f'Maps    : {maps_count:>4}  -> {OUT_MAPS}/')
print(f'Images  : {images_count:>4}  -> {OUT_IMAGES}/')
print(f'Skipped : {skipped_size:>4}  (< {SIZE_MIN//1000}KB decorative)')
print(f'Dupes   : {skipped_dup:>4}  (hash-deduped — book prints each image twice)')
print(f'Total   : {len(media_bytes)}')
