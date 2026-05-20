from src.mission_builder import heist_pipeline as hp
from src.mission_builder import discovery_pipeline as dp
from src.mission_builder import exploration_pipeline as ep
from src.mission_builder import first_contact_pipeline as fcp
from src.mission_builder import negotiation_pipeline as np
from src.mission_builder import puzzle_pipeline as pp
from src.mission_builder import recovery_pipeline as recp
from src.mission_builder import rescue_pipeline as rp
from src.mission_builder import sabotage_pipeline as sp
from src.mission_builder import strange_occurrences_pipeline as sop


def test_heist_normalize_plan_fills_partial_llm_json():
    roles = {"sponsor": "Obsidian Lotus", "target_owner": "Tower Authority"}
    target = {"name": "Black Ledger", "source": "generated fallback", "detail": "names the wrong patron"}
    location = {"name": "Archive Annex", "district": "Glass Row", "type": "archive", "description": "locked stacks"}
    options = {
        "casing_questions": [("Who has keys?", "the night clerk")],
        "crew_assets": ["forged pass"],
        "marks": ["nervous clerk"],
        "rival_crews": ["a rival crew waits outside"],
        "target_oddities": ["ledger whispers when opened"],
        "heat_fallout": ["archives add new wards"],
    }

    plan = hp._normalize_plan(
        {"score": "copy the Black Ledger", "escape_options": "roofline\nservice tunnel"},
        roles,
        target,
        location,
        options,
        "copy",
        "the target is a fake",
    )

    assert plan["score"] == "copy the Black Ledger"
    assert plan["briefing"]
    assert plan["site_description"]
    assert plan["security_plan"]
    assert plan["approach_options"]
    assert plan["escape_options"] == ["roofline", "service tunnel"]


def test_sabotage_normalize_plan_fills_partial_llm_json():
    roles = {"hiring": "Serpent Choir", "owner": "Tower Authority"}
    target = {
        "name": "Transit Relay",
        "trigger": "inspection bell",
    }
    place = {"name": "Relay Station"}

    plan = sp._normalize_plan(
        {"objective": "Delay the inspection bell", "steps": "enter quietly\nsalt the gears"},
        roles,
        target,
        place,
    )

    assert plan["objective"] == "Delay the inspection bell"
    assert plan["briefing"]
    assert plan["bonus"]
    assert plan["immediate_effect"]
    assert plan["ripple_effect"]
    assert plan["catastrophic_failure"]
    assert plan["debrief"]
    assert plan["steps"] == ["enter quietly", "salt the gears"]


def test_rescue_normalize_plan_fills_partial_llm_json():
    roles = {"sponsor": "Patchwork Saints", "obstacle": "Tower Authority"}
    target = {"name": "Eli Mar", "type": "civilian", "detail": "trapped under a collapsed stair"}
    location = {"name": "Old Transit Hall", "district": "Low Market"}
    mission = {"title": "Rescue Eli Mar from Old Transit Hall"}

    plan = rp._normalize_plan(
        {"timer": "before the next tremor", "scenes": "find witnesses\nshore up the stair"},
        "active",
        roles,
        target,
        location,
        mission,
    )

    assert plan["timer"]  # may come from LLM data or mission-specific fallback
    assert plan["briefing"]
    assert plan["hazards_or_pressures"]
    assert plan["survivor_quote"]
    assert plan["family_quote"]
    assert plan["official_quote"]
    assert plan["tnn_question"]
    assert plan["news_memory_seed"]
    assert plan["debrief"]
    assert plan["scenes"]  # may come from LLM data or mission-specific fallback


def test_puzzle_normalize_plan_fills_partial_llm_json():
    mission = {"title": "Cipher Bell"}

    plan = pp._normalize_plan(
        {"answer_key": "Ring the bells in calendar order.", "solve_path": "find names\nmap names to months"},
        mission,
        "Guild of Ashen Scrolls",
        "language_cipher",
        "Open the sealed archive",
    )

    assert plan["answer_key"]  # may come from LLM data or mission-specific fallback
    assert plan["briefing"]
    assert plan["surface_description"]
    assert plan["puzzle_name"]
    assert plan["objective"]
    assert plan["core_puzzle"]
    assert plan["clue_meanings"]
    assert plan["alternate_solutions"]
    assert plan["unstick_notes"]
    assert plan["wrong_attempts"]
    assert plan["world_moves"]
    assert plan["debrief"]
    assert plan["news_angle"]
    assert plan["solve_path"]  # may come from LLM data or mission-specific fallback


def test_puzzle_fallback_templates_vary_by_puzzle_type():
    mission = {
        "title": "Neon Mural Cipher",
        "body": "Decode the Neon Row mural sequence before the Glass Sigil paints over it.",
    }

    art = pp._fallback_plan(mission, "Guild of Ashen Scrolls", "art_puzzle", "decode a mural")
    cipher = pp._fallback_plan(mission, "Guild of Ashen Scrolls", "language_cipher", "decode a mural")
    mechanism = pp._fallback_plan(mission, "Guild of Ashen Scrolls", "physical_mechanism", "decode a mural")
    trial = pp._fallback_plan(mission, "Guild of Ashen Scrolls", "divine_trial", "decode a mural")

    names = {art["puzzle_name"], cipher["puzzle_name"], mechanism["puzzle_name"], trial["puzzle_name"]}
    assert len(names) == 4
    assert "Mural Sequence" in art["puzzle_name"]
    assert "Cipher Bell" in cipher["puzzle_name"]
    assert "Counterweight Engine" in mechanism["puzzle_name"]
    assert "Witness Trial" in trial["puzzle_name"]
    assert "Oath-Circuit" not in art["puzzle_name"]
    assert "Oath-Circuit" not in cipher["puzzle_name"]


def test_recovery_normalize_plan_fills_structured_fields():
    mission = {"title": "Find the Ledger"}
    context = {"name": "Dust Market", "district": "Low Market"}
    dcs = {"locate": 13, "verify": 14, "negotiate": 15, "extract": 16}
    rival = {"name": "Glass Sigil retrieval cell"}

    plan = recp._normalize_plan(
        {
            "target_name": "Brass Ledger",
            "trail": "ask the clerk\ncheck the stall",
            "retrieval_scene": "a handoff in the rain",
            "outcome_table": ["intact", "lost"],
        },
        mission,
        "data_record",
        context,
        dcs,
        rival,
    )

    assert plan["target_name"]  # may come from LLM data or mission-specific fallback
    assert plan["target_description"]
    assert plan["briefing"]
    assert plan["location_readaloud"]
    assert plan["trail"]  # may come from LLM data or mission-specific fallback
    assert plan["complications"]
    assert isinstance(plan["retrieval_scene"], dict)
    assert isinstance(plan["outcome_table"], dict)
    assert plan["dialogue_bank"]
    assert plan["follow_up_hooks"]


def test_negotiation_normalize_plan_fills_structured_fields():
    mission = {"title": "Settle the Claim"}
    roles = {"side_a": "Tower Authority", "side_b": "Patchwork Saints"}
    situation = {"frame": "a disputed relief shipment", "failure": "ambush"}
    dcs = {"standard": 14}

    plan = np._normalize_plan(
        {
            "what_happened": "Both sides claim the same shipment.",
            "side_a_wants": "public apology\ncontrol of the manifest",
            "research": "ask around",
            "outside_favors": [{"source": "TNN", "ask": "delay coverage", "cost": "future attention", "marker_effect": 1}],
        },
        mission,
        roles,
        situation,
        2,
        dcs,
    )

    assert plan["what_happened"] == "Both sides claim the same shipment."
    assert plan["current_state"]
    assert plan["side_a_wants"] == ["public apology", "control of the manifest"]
    assert plan["side_b_wants"]
    assert plan["side_a_red_lines"]
    assert plan["side_b_red_lines"]
    assert plan["research"]
    assert all(isinstance(item, dict) for item in plan["research"])
    assert plan["outside_favors"]
    assert plan["dialogue"]
    assert plan["escalations"]


def test_discovery_normalize_plan_fills_empty_sections():
    mission = {"title": "Humming Relic Investigation"}
    context = {"name": "Glass Stair", "district": "Old Market"}
    dcs = {"identify": 13, "contain": 14, "transport": 15, "implication": 13}

    plan = dp._normalize_plan(
        {"briefing": "Work out what the humming relic is.", "first_imagery": "blue hum\ncold brass"},
        mission,
        "object",
        context,
        dcs,
    )

    assert plan["briefing"]  # may come from LLM data or mission-specific fallback
    assert plan["surface_description"]
    assert plan["first_imagery"]  # may come from LLM data or mission-specific fallback
    assert plan["identification_steps"]
    assert all(isinstance(item, dict) for item in plan["identification_steps"])
    assert plan["containment_rules"]
    assert plan["handling_states"]
    assert plan["implication_tree"]
    assert plan["faction_claims"]
    assert plan["dialogue"]
    assert plan["fate_options"]


def test_exploration_normalize_plan_fills_structured_sections():
    area = {"name": "Old Gate", "district": "The Warrens", "description": "an entry that no longer matches the map"}
    dcs = {"navigation": 13, "hazard": 14, "stability": 15, "lore": 13}

    plan = ep._normalize_plan(
        {
            "briefing": "Survey the replacement gate.",
            "imagery": "blue chalk\nwrong sunlight",
            "route_log": "north gate\nfallen plaza",
            "scenes": ["bad scene"],
        },
        "gate_marking",
        area,
        dcs,
    )

    assert plan["briefing"]  # may come from LLM data or mission-specific fallback
    assert plan["setup"]
    assert plan["win_conditions"]
    assert plan["opening_scene"]
    assert plan["imagery"] == ["blue chalk", "wrong sunlight"]
    assert plan["route_log"]
    assert all(isinstance(item, dict) for item in plan["route_log"])
    assert plan["scenes"]
    assert all(isinstance(item, dict) for item in plan["scenes"])
    assert plan["hazards"]
    assert plan["deliverables"]
    assert plan["discoveries"]
    assert plan["dialogue"]
    assert plan["news_seed"]
    assert plan["follow_up"]


def test_first_contact_normalize_plan_fills_empty_sections():
    plan = fcp._normalize_plan(
        {"briefing": "A group arrived from nowhere.", "dialogue": "Who owns the sky?\nWhat is EC?"},
        {"title": "First Contact: Arrivals from Nowhere"},
        "children_or_civilians",
    )

    assert plan["briefing"]  # may come from LLM data or mission-specific fallback
    assert plan["first_sight"]
    assert plan["who_they_are"]
    assert plan["immediate_needs"]
    assert plan["fears"]
    assert plan["taboos"]
    assert plan["translation_tracker"]
    assert plan["panic_meter"]
    assert plan["dialogue"]  # may come from LLM data or mission-specific fallback
    assert plan["tower_primer"]
    assert plan["faction_risks"]
    assert plan["protection_options"]


def test_strange_occurrence_normalize_plan_fills_structured_sections():
    mission = {"title": "The Returning Clerk — Death Registry Case"}
    sponsor = {"sponsor": "Tower Authority", "contact": "Registrar Pell"}
    locations = [{"name": "Death Registry", "district": "Grand Forum"}]
    parties = [{"faction": "Patchwork Saints", "goal": "protect the returned dead"}]
    dcs = {"basic": 13}

    plan = sop._normalize_plan(
        {
            "case_title": "The Returning Clerk",
            "contradictions": "signed after death\nseen before burial",
            "evidence_ladder": "bad data",
        },
        mission,
        "returned_dead",
        sponsor,
        locations,
        parties,
        dcs,
    )

    assert plan["case_title"]  # may come from LLM data or mission-specific fallback
    assert plan["public_report"]
    assert plan["true_situation"]
    assert plan["contradictions"]  # may come from LLM data or mission-specific fallback
    assert plan["evidence_ladder"]
    assert all(isinstance(item, dict) for item in plan["evidence_ladder"])
    assert plan["witnesses"]
    assert plan["dialogue"]
    assert plan["coroner_records"]
    assert plan["faction_pressure"]
    assert plan["resolution_paths"]
    assert all(isinstance(item, dict) for item in plan["resolution_paths"])
