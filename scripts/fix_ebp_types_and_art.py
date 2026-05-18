"""
fix_ebp_types_and_art.py

Two tasks per creature in one pass:
  1. Fix wrong monster types (plant→ooze, ooze→monstrosity submitted in early run)
  2. Generate 256x256 portrait art via OpenAI gpt-image-1, upload to DDB icon fields

Run from project root:
    python scripts/fix_ebp_types_and_art.py

Skips art generation if OPENAI_KEY is not set.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import base64
import httpx
from PIL import Image

from src.ddb_homebrew import SESSION, _CR_OPTIONS, _TYPE_OPTIONS, _SIZE_OPTIONS
from src.log import logger

LOG_FILE = ROOT / "logs" / "ebp_fix_art.log"
ART_DIR  = ROOT / "campaign_docs" / "npc_appearances" / "ebp_monsters"
ART_DIR.mkdir(parents=True, exist_ok=True)

A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860").split()[0]

_NEG = (
    "ugly, deformed, extra limbs, blurry, watermark, text, signature, border, frame, "
    "white background, low quality, jpeg artifacts, multiple creatures, duplicate, "
    "cropped, out of frame, worst quality, bad anatomy, bad proportions"
)

BASE_URL = "https://www.dndbeyond.com"

# ── Which creatures need type correction ────────────────────────────────────
WRONG_TYPE = {
    # name → (wrong-type, correct-type-option-id, edit-slug)
    "EBP Vegepygmy":            ("ooze", "15", "6453200-ebp-vegepygmy"),
    "EBP Vegepygmy Elite":      ("ooze", "15", "6453202-ebp-vegepygmy-elite"),
    "EBP Vegepygmy Sub-Chief":  ("ooze", "15", "6453203-ebp-vegepygmy-sub-chief"),
    "EBP Vegepygmy Chief":      ("ooze", "15", "6453204-ebp-vegepygmy-chief"),
    "EBP Horrid Plant":         ("ooze", "15", "6453217-ebp-horrid-plant"),
    "EBP Greater Slithering Tracker": ("monstrosity", "14", "6453220-ebp-greater-slithering-tracker"),
    "EBP Strangle Vine":        ("ooze", "15", "6453244-ebp-strangle-vine"),
    "EBP Vampire Thorn":        ("ooze", "15", "6453245-ebp-vampire-thorn"),
    "EBP Boring Grass":         ("ooze", "15", "6453247-ebp-boring-grass"),
    "EBP Globe Palm":           ("ooze", "15", "6453249-ebp-globe-palm"),
    "EBP Purple Blossom Plant": ("ooze", "15", "6453252-ebp-purple-blossom-plant"),
    "EBP Snapper-Saw":          ("ooze", "15", "6453253-ebp-snapper-saw"),
    "EBP Tri-Flower Frond":     ("ooze", "15", "6453257-ebp-tri-flower-frond"),
    "EBP Wolf-in-Sheep's-Clothing": ("ooze", "15", "6453259-ebp-wolf-in-sheeps-clothing"),
}

# ── All 46 creatures: name → edit slug ──────────────────────────────────────
EDIT_SLUGS: dict[str, str] = {
    "EBP Vegepygmy":                      "6453200-ebp-vegepygmy",
    "EBP Vegepygmy Elite":                "6453202-ebp-vegepygmy-elite",
    "EBP Vegepygmy Sub-Chief":            "6453203-ebp-vegepygmy-sub-chief",
    "EBP Vegepygmy Chief":                "6453204-ebp-vegepygmy-chief",
    "EBP Police Robot":                   "6453206-ebp-police-robot",
    "EBP Worker Robot":                   "6453207-ebp-worker-robot",
    "EBP Repair Robot":                   "6453209-ebp-repair-robot",
    "EBP Android":                        "6453210-ebp-android",
    "EBP Dining Servo Robot":             "6453212-ebp-dining-servo-robot",
    "EBP Baboonoid":                      "6453215-ebp-baboonoid",
    "EBP Horrid Plant":                   "6453217-ebp-horrid-plant",
    "EBP Greater Slithering Tracker":     "6453220-ebp-greater-slithering-tracker",
    "EBP Boxing Training Android":        "6453221-ebp-boxing-training-android",
    "EBP Fencing Training Android":       "6453222-ebp-fencing-training-android",
    "EBP Karate Training Android":        "6453223-ebp-karate-training-android",
    "EBP Weightlifting Training Android": "6453224-ebp-weightlifting-training-android",
    "EBP Stunted Eye of the Deep":        "6453225-ebp-stunted-eye-of-the-deep",
    "EBP Pacifier Robot":                 "6453227-ebp-pacifier-robot",
    "EBP Type One Biological Entity":     "6453228-ebp-type-one-biological-entity",
    "EBP Type Two Biological Entity":     "6453229-ebp-type-two-biological-entity",
    "EBP Vampoid":                        "6453230-ebp-vampoid",
    "EBP Thorny":                         "6453242-ebp-thorny",
    "EBP Grell Brood-Mother":             "6453243-ebp-grell-brood-mother",
    "EBP Strangle Vine":                  "6453244-ebp-strangle-vine",
    "EBP Vampire Thorn":                  "6453245-ebp-vampire-thorn",
    "EBP Aurumvorax":                     "6453246-ebp-aurumvorax",
    "EBP Boring Grass":                   "6453247-ebp-boring-grass",
    "EBP Flail Snail":                    "6453248-ebp-flail-snail",
    "EBP Globe Palm":                     "6453249-ebp-globe-palm",
    "EBP Leechoid":                       "6453250-ebp-leechoid",
    "EBP Lizardoid":                      "6453251-ebp-lizardoid",
    "EBP Purple Blossom Plant":           "6453252-ebp-purple-blossom-plant",
    "EBP Snapper-Saw":                    "6453253-ebp-snapper-saw",
    "EBP Squealer":                       "6453254-ebp-squealer",
    "EBP Squealer Adolescent":            "6453255-ebp-squealer-adolescent",
    "EBP Swarm of Rot Grubs":             "6453256-ebp-swarm-of-rot-grubs",
    "EBP Tri-Flower Frond":               "6453257-ebp-tri-flower-frond",
    "EBP Wolf-in-Sheep's-Clothing":       "6453259-ebp-wolf-in-sheeps-clothing",
    "EBP Gasbat":                         "6453262-ebp-gasbat",
    "EBP Greater Slithering Tracker":     "6453220-ebp-greater-slithering-tracker",
    "EBP Boxing Training Android":        "6453221-ebp-boxing-training-android",
    "EBP Trapper":                        "6453268-ebp-trapper",
    "EBP Dwarf Phase Spider":             "6453269-ebp-dwarf-phase-spider",
    "EBP Froghemoth":                     "6453270-ebp-froghemoth",
    "EBP Living Burrow":                  "6453271-ebp-living-burrow",
    "EBP Mutant Two-Headed Umber Hulk":   "6453272-ebp-mutant-two-headed-umber-hulk",
    "EBP Shedu":                          "6453274-ebp-shedu",
    "EBP Death-Drinker":                  "6453275-ebp-death-drinker",
}

# ── Art prompts ──────────────────────────────────────────────────────────────
# Style suffix applied to every prompt — tuned for Juggernaut-XL
_STYLE = (
    "D&D monster token art, fantasy RPG creature portrait, "
    "dramatic dark background, centered composition, "
    "highly detailed digital illustration, cinematic lighting, "
    "8k uhd, sharp focus, vibrant colors, professional concept art"
)

ART_PROMPTS: dict[str, str] = {
    # ── VEGEPYGMIES
    "EBP Vegepygmy":
        f"Small plant-humanoid creature, mossy green skin, fungal growths on body, clutching a crude bone spear, glowing amber eyes. {_STYLE}",
    "EBP Vegepygmy Elite":
        f"Stronger plant-humanoid soldier, dense green moss armor, mushroom cap helmet, dual bone weapons, fierce expression. {_STYLE}",
    "EBP Vegepygmy Sub-Chief":
        f"Plant-humanoid leader with elaborate fungal crown, releasing a cloud of orange spores, commanding pose. {_STYLE}",
    "EBP Vegepygmy Chief":
        f"Imposing plant-humanoid chieftain, thick bark-like skin, glowing bioluminescent markings, raised spear, cloud of spores. {_STYLE}",
    "EBP Thorny":
        f"Small vicious plant creature resembling a thorny green dog, dense spiky hide, bared fangs, coiled to spring. {_STYLE}",
    "EBP Trapper":
        f"Flat manta-ray-shaped creature camouflaged as a dungeon floor, edges curling up to reveal a gaping maw, acidic saliva dripping. {_STYLE}",
    # ── LEVEL I ROBOTS
    "EBP Police Robot":
        f"Battered chrome humanoid robot, domed head with red sensor eye, extendable pincers, shoulder-mounted grenade launcher, authority insignia. {_STYLE}",
    "EBP Worker Robot":
        f"Massive industrial robot, rusted yellow chassis, enormous crushing hydraulic arms, heavy treads, cargo bay markings worn with age. {_STYLE}",
    "EBP Repair Robot":
        f"Compact repair droid, multiple manipulator arms holding welding tools, electric arc from chest welder, efficient utilitarian design. {_STYLE}",
    "EBP Android":
        f"Humanoid android with cracked synthetic skin revealing metallic skeleton beneath, glowing circuit eyes, combat stance, sci-fi design. {_STYLE}",
    "EBP Dwarf Phase Spider":
        f"Phase spider the size of a dog, translucent flickering body partially phased between planes, ethereal blue glow, venom-dripping fangs. {_STYLE}",
    # ── LEVEL III
    "EBP Grell Brood-Mother":
        f"Enormous floating brain-like creature, dozens of crackling electrified tentacles spreading wide, single massive cyclopean eye, alien and terrifying. {_STYLE}",
    "EBP Strangle Vine":
        f"Massive carnivorous vine network, whipping luminous tendrils snaking toward a light source, thorned stems, pale alien flowers. {_STYLE}",
    "EBP Vampire Thorn":
        f"Large thorned plant creature, blood-red flowers, razor thorns dripping with absorbed blood, pulsing with stolen vitality. {_STYLE}",
    "EBP Dining Servo Robot":
        f"Malfunctioning silver serving robot with a tuxedo-painted chassis, multiple whipping tentacle arms tipped with forks and force-feeders, deranged grin panel. {_STYLE}",
    # ── LEVEL IV
    "EBP Aurumvorax":
        f"Compact eight-legged golden badger-like predator, dense metallic hide gleaming, multiple sets of razor claws, muscular and low-slung. {_STYLE}",
    "EBP Baboonoid":
        f"Bipedal ape-humanoid alien, orange and grey fur, intelligent dark eyes, holding a pheromone globe ready to throw, alert posture. {_STYLE}",
    "EBP Boring Grass":
        f"Innocent-looking alien meadow grass with hidden carnivorous tendrils erupting upward, translucent boring filaments, a half-dissolved victim shape visible. {_STYLE}",
    "EBP Flail Snail":
        f"Large snail with an iridescent magical shell, five heavy crystalline flail-tipped tentacles extended and spinning, shell radiating scintillating light. {_STYLE}",
    "EBP Froghemoth":
        f"Enormous alien frog-beast, four eyes on stalks, three prehensile tongues, massive webbed hands, swamp water dripping from its bulk. {_STYLE}",
    "EBP Globe Palm":
        f"Alien palm tree with round pheromone-globe fruit clusters, innocent appearance concealing the predator lure, bioluminescent pods glowing softly. {_STYLE}",
    "EBP Horrid Plant":
        f"Hideous but benevolent alien plant, twisted asymmetric form with shimmering leaves, gentle bioluminescent glow, telepathic warning fronds extended. {_STYLE}",
    "EBP Leechoid":
        f"Giant leech the size of a dog, translucent grey-green body, circular tooth-lined sucker mouth, coiled to lunge from swamp water. {_STYLE}",
    "EBP Living Burrow":
        f"Massive creature disguised as a dirt burrow opening, enormous hidden maw with reflective lure tongue, tentacles erupting from the earth. {_STYLE}",
    "EBP Lizardoid":
        f"Six-foot bipedal alien reptile, teal and copper spotted hide, three-pronged fleshy head crest flared, mid-pounce with claws extended. {_STYLE}",
    "EBP Mutant Two-Headed Umber Hulk":
        f"Massive radiation-mutated umber hulk with two grotesque insectoid heads, each with disorienting swirling eyes, four clawed arms, chitinous black armor. {_STYLE}",
    "EBP Purple Blossom Plant":
        f"Alien carnivorous plant with deep purple cup-shaped flowers tilted downward, dripping virulent yellow poison sap, innocently beautiful and lethal. {_STYLE}",
    "EBP Snapper-Saw":
        f"Alien decorative bush concealing carnivorous saw-edged snap-trap leaves, bright edible berries visible as lure, leaves snapping shut mid-action. {_STYLE}",
    "EBP Squealer":
        f"Six-limbed alien predator, spotted yellow-green hide, shoulder arms raised and grasping, opened mouth mimicking animal sounds, gorilla-sized bulk. {_STYLE}",
    "EBP Squealer Adolescent":
        f"Juvenile six-limbed alien predator, spotted yellow-green hide, smaller and leaner, defensive posture near its den burrow. {_STYLE}",
    "EBP Swarm of Rot Grubs":
        f"Roiling mass of pale writhing maggot-grubs erupting from decayed matter, a seething carpet of pestilence and ruin. {_STYLE}",
    "EBP Tri-Flower Frond":
        f"Alien three-stalk plant, orange stalk releasing sleep spores, yellow stalk paralyzing, red stalk with grasping leafy tendrils, each bloom distinct. {_STYLE}",
    "EBP Wolf-in-Sheep's-Clothing":
        f"Ancient tree stump with a convincingly adorable small rabbit perched on top -- the rabbit is a lure appendage of the carnivorous stump, grasping root tendrils visible beneath. {_STYLE}",
    "EBP Gasbat":
        f"Bloated bat-like creature, swollen translucent gas sacs visible through thin skin, tiny vestigial wings, near an open flame that draws it fatally. {_STYLE}",
    # ── LEVEL V
    "EBP Greater Slithering Tracker":
        f"Nearly invisible ooze creature shimmering like a disturbed puddle, hints of a flowing shape with reaching pseudopods, victim-shaped depression visible inside. {_STYLE}",
    # ── LEVEL VI
    "EBP Boxing Training Android":
        f"Humanoid android in a boxing stance, gleaming padded fists raised, cracked visor displaying a training program HUD, tuxedo-era paint scheme. {_STYLE}",
    "EBP Fencing Training Android":
        f"Elegant android fencer, crackling electrified epee extended in a lunge, precise athletic posture, lightning arcing along the blade. {_STYLE}",
    "EBP Karate Training Android":
        f"Combat android mid-karate-strike, palm heel thrust forward, uniform-painted chassis, disarmed weapons flying through the air around it. {_STYLE}",
    "EBP Weightlifting Training Android":
        f"Stocky android heaving a massive barbell overhead, cheerful painted face, weights spinning to throw at intruders, gym insignia on chest. {_STYLE}",
    "EBP Shedu":
        f"Majestic celestial creature, body of a bull, wings of an eagle, noble human-bearded face, golden light emanating from its form, ancient and wise. {_STYLE}",
    "EBP Stunted Eye of the Deep":
        f"Alien aquatic creature, body like a warped manta ray, triple eye-stalks each shooting different colored beams, camouflaged as a pile of bones underwater. {_STYLE}",
    # ── LEVEL VII
    "EBP Death-Drinker":
        f"Apex alien predator, chameleon-skin shifting to match surroundings, six powerful limbs tipped with scything claws, fanged maw gaping, utterly terrifying. {_STYLE}",
    "EBP Pacifier Robot":
        f"Oval floating combat platform bristling with weapons -- laser batteries, grenade launchers, tentacle arms, and tractor beam emitter, red threat-assessment lights blazing. {_STYLE}",
    "EBP Type One Biological Entity":
        f"Hairless shock-trooper humanoid, dog-like canine rear legs, bat-like ears, short muzzle, plastic-rigid grey skin, wielding a battleaxe, feral intensity. {_STYLE}",
    "EBP Type Two Biological Entity":
        f"Massive gorilla-muscled bioengineered soldier, rhino-hide skin, hulking frame towering over human scale, carrying an enormous greatclub. {_STYLE}",
    "EBP Vampoid":
        f"Sleek stellar vampire, coal-black skin with silver veins, extended clawed hands, echolocation mouth open in a shriek, void of space visible behind it. {_STYLE}",
}


def _ascii(s: str) -> str:
    return s.replace("—", "--").replace("–", "-")


async def generate_art(name: str, prompt: str) -> Optional[bytes]:
    """
    Generate a 256x256 PNG via A1111 txt2img.
    Generates at 512x512 for quality then resizes to 256x256.
    Returns PNG bytes or None.
    """
    safe_name = name.replace(" ", "_").replace("/", "_").replace("'", "")
    out_path  = ART_DIR / f"{safe_name}.png"
    if out_path.exists():
        return out_path.read_bytes()

    payload = {
        "prompt":          prompt,
        "negative_prompt": _NEG,
        "width":           512,
        "height":          512,
        "steps":           25,
        "cfg_scale":       7.5,
        "sampler_name":    "DPM++ 2M Karras",
        "n_iter":          1,
        "batch_size":      1,
        "restore_faces":   False,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            img_b64 = resp.json()["images"][0]

        img_bytes = base64.b64decode(img_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        img = img.resize((256, 256), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        out_path.write_bytes(png_bytes)
        return png_bytes

    except Exception as exc:
        logger.warning("[ART] A1111 failed for %r: %s", name, exc)
        return None


async def edit_monster_ddb(
    edit_slug: str,
    creature: dict,
    correct_type_id: Optional[str],
    image_bytes: Optional[bytes],
) -> bool:
    """
    Edit a DDB homebrew monster entry.
    - correct_type_id: if provided, override the monster-type field
    - image_bytes: if provided, upload as both small and large avatar
    Returns True on success (303 redirect or 200 with no errors).
    """
    edit_url = f"{BASE_URL}/homebrew/creations/monsters/{edit_slug}/edit"

    hdrs = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124",
        "Origin": BASE_URL,
        "Referer": edit_url,
    }

    # ── GET form ──────────────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as getter:
            r = await getter.get(edit_url, headers=hdrs, cookies={"CobaltSession": SESSION})
            if r.status_code not in (200, 302, 303):
                logger.warning("[EDIT] GET %s for %r", r.status_code, edit_slug)
                return False
            awsalb     = r.cookies.get("AWSALB", "")
            awsalbcors = r.cookies.get("AWSALBCORS", "")
            html       = r.text

        def _hidden(field):
            m = re.search(r'name="' + re.escape(field) + r'"[^>]*value="([^"]*?)"', html)
            if not m:
                m = re.search(r'value="([^"]*?)"[^>]*name="' + re.escape(field) + r'"', html)
            return m.group(1) if m else ""

        # Obfuscated field map (same as create form)
        obf = {}
        for m in re.finditer(r"<input[^>]+>", html, re.IGNORECASE):
            inp = m.group()
            nm  = re.search(r'name="(f[a-f0-9]{30,})"', inp)
            idm = re.search(r'id="([^"]+)"', inp)
            if nm and idm:
                obf[idm.group(1)] = nm.group(1)

        # Avatar field names (may be under different pattern on edit page)
        def _obf_by_id(field_id):
            m = re.search(
                r'id="' + re.escape(field_id) + r'"[^>]*name="([^"]+)"', html, re.IGNORECASE)
            if not m:
                m = re.search(
                    r'name="([^"]+)"[^>]*id="' + re.escape(field_id) + r'"', html, re.IGNORECASE)
            return m.group(1) if m else None

        avatar_field       = _obf_by_id("field-avatar")
        large_avatar_field = _obf_by_id("field-large-avatar")

    except Exception as exc:
        logger.warning("[EDIT] GET error for %r: %s", edit_slug, exc)
        return False

    # ── Build form fields ─────────────────────────────────────────────────────
    name           = _ascii(creature["name"])
    cr             = creature.get("cr", "1")
    creature_type  = creature.get("creature_type", "humanoid")
    size           = creature.get("size", "M")
    ac             = creature.get("ac", 12)
    hp             = creature.get("hp", 15)
    hp_die         = creature.get("hp_die", "8")
    hp_die_count   = creature.get("hp_die_count", 2)
    str_           = creature.get("str_", 10)
    dex            = creature.get("dex", 10)
    con            = creature.get("con", 10)
    int_           = creature.get("int_", 10)
    wis            = creature.get("wis", 10)
    cha            = creature.get("cha", 10)
    passive_perc   = creature.get("passive_perc", 10)
    languages      = _ascii(creature.get("languages", "Common"))
    actions        = _ascii(creature.get("actions", ""))
    notes          = _ascii(creature.get("notes", ""))

    cr_option      = _CR_OPTIONS.get(str(cr), "5")
    # Use corrected type if provided, otherwise look up from map
    if correct_type_id:
        type_option = correct_type_id
    else:
        type_option = _TYPE_OPTIONS.get(creature_type.lower(), "11")
    size_option    = _SIZE_OPTIONS.get(size, "4")
    die_option     = hp_die if hp_die in ("4","6","8","10","12","20") else "8"

    text_data = {
        "security-token":    _hidden("security-token"),
        "authenticity-token": _hidden("authenticity-token"),
        "Name":              name,
        "stat-block-type":   "1",
        "monster-type":      type_option,
        "size":              size_option,
        "challenge-rating":  cr_option,
        "armor-class":       str(ac),
        "passive-perception": str(passive_perc),
        "average-hit-points": str(hp),
        "hit-points-die-count": str(hp_die_count),
        "hit-points-die-value": die_option,
        "hit-points-modifier": "",
        "languages-note":    languages,
        "special-traits-description-type":           "1",
        "actions-description-type":                  "1",
        "bonus-actions-description-type":            "1",
        "reactions-description-type":                "1",
        "monster-characteristics-description-type":  "1",
        "legendary-actions-description-type":        "1",
        "mythic-actions-description-type":           "1",
        "lair-description-type":                     "1",
        "actions-description":                        actions,
        "monster-characteristics-description":        notes,
    }
    # Ability scores
    score_ids = {
        "field-strength": str(str_), "field-dexterity": str(dex),
        "field-constitution": str(con), "field-intelligence": str(int_),
        "field-wisdom": str(wis), "field-charisma": str(cha),
        "field-initiative-bonus": str(dex - 10),
    }
    for fid, val in score_ids.items():
        if fid in obf:
            text_data[obf[fid]] = val

    # ── Build multipart files ─────────────────────────────────────────────────
    file_data = {}
    if image_bytes and avatar_field:
        file_data[avatar_field]       = ("avatar.png",       image_bytes, "image/png")
    if image_bytes and large_avatar_field:
        file_data[large_avatar_field] = ("large_avatar.png", image_bytes, "image/png")

    # ── POST ──────────────────────────────────────────────────────────────────
    post_cookies = {"CobaltSession": SESSION}
    if awsalb:
        post_cookies["AWSALB"]     = awsalb
        post_cookies["AWSALBCORS"] = awsalbcors

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30) as poster:
            resp = await poster.post(
                edit_url,
                data=text_data,
                files=file_data if file_data else None,
                headers=hdrs,
                cookies=post_cookies,
            )

        if resp.status_code in (301, 302, 303, 307, 308):
            return True
        # DDB sometimes returns 200 with the updated page (not a redirect) on edits
        if resp.status_code == 200:
            # Check if we're on the edit page vs an error page
            if "ddb-homebrew-create-form" in resp.text:
                # Stayed on form — likely a validation error
                return False
            return True  # 200 but on a different page = success
        logger.warning("[EDIT] POST %s for %r", resp.status_code, edit_slug)
        return False

    except Exception as exc:
        logger.warning("[EDIT] POST error for %r: %s", edit_slug, exc)
        return False


async def main():
    log_entries: list[str] = []

    def log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        log_entries.append(line)
        with open(LOG_FILE, "a", encoding="utf-8") as _f:
            _f.write(line + "\n")

    # Load creature data from the import script
    from scripts.import_ebp_to_ddb import CREATURES as ALL_CREATURES
    creature_by_name = {c["name"]: c for c in ALL_CREATURES}

    total = len(EDIT_SLUGS)
    log(f"EBP Fix Types + Art — {total} creatures")
    log(f"Art dir: {ART_DIR}")
    log(f"A1111: {A1111_URL}")
    log(f"Type fixes needed: {len(WRONG_TYPE)}")
    log("")

    fixed_types = []
    failed_types = []
    art_ok = []
    art_fail = []

    # De-dup (EDIT_SLUGS has one duplicate entry from copy-paste)
    seen = set()
    ordered_names = []
    for name in EDIT_SLUGS:
        if name not in seen:
            ordered_names.append(name)
            seen.add(name)

    for i, name in enumerate(ordered_names, 1):
        slug = EDIT_SLUGS[name]
        creature = creature_by_name.get(name)
        if not creature:
            log(f"[{i:02d}/{total}] SKIP {name} — not in CREATURES list")
            continue

        needs_type_fix = name in WRONG_TYPE
        correct_type   = WRONG_TYPE[name][1] if needs_type_fix else None
        prompt         = ART_PROMPTS.get(name, "")

        log(f"[{i:02d}/{len(ordered_names)}] {name}  (type_fix={needs_type_fix})")

        # ── Generate art ──────────────────────────────────────────────────────
        image_bytes = None
        if prompt:
            log(f"  Generating 256x256 art...")
            image_bytes = await generate_art(name, prompt)
            if image_bytes:
                log(f"  Art OK ({len(image_bytes)//1024}KB)")
                art_ok.append(name)
            else:
                log(f"  Art FAIL (no image generated)")
                art_fail.append(name)
        else:
            log(f"  No art prompt defined — skipping art")

        # ── Edit DDB entry ────────────────────────────────────────────────────
        if needs_type_fix or image_bytes:
            log(f"  Editing DDB entry (type={'fix->'+correct_type if needs_type_fix else 'keep'}, art={'yes' if image_bytes else 'no'})...")
            ok = await edit_monster_ddb(slug, creature, correct_type, image_bytes)
            if ok:
                log(f"  Edit OK")
                if needs_type_fix:
                    fixed_types.append(name)
            else:
                log(f"  Edit FAIL")
                if needs_type_fix:
                    failed_types.append(name)
        else:
            log(f"  No changes needed (type correct, no art)")

        # Polite delay
        await asyncio.sleep(2)

    log("")
    log("=" * 60)
    log(f"Type fixes: {len(fixed_types)}/{len(WRONG_TYPE)} succeeded")
    if failed_types:
        log(f"  Failed: {', '.join(failed_types)}")
    log(f"Art generated: {len(art_ok)}/{len(ordered_names)}")
    if art_fail:
        log(f"  Failed: {', '.join(art_fail)}")
    log(f"Full log: {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
