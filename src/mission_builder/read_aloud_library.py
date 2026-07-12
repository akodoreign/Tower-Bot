"""
read_aloud_library.py — Live DB-fed read-aloud pool for mission pipelines.

Each function returns a single string picked from a pool of 10+ variants,
populated with live context (weather, location, NPC, faction) from DB.

Call pattern:
    from src.mission_builder.read_aloud_library import scene_read_aloud
    text = scene_read_aloud("briefing", contact=contact_name, ctx=ctx)
"""

from __future__ import annotations

import random
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# DB context loader — called once per module build, cheap
# ---------------------------------------------------------------------------

def _live_context() -> Dict[str, str]:
    """Pull ambient world detail from DB for template injection."""
    ctx: Dict[str, str] = {
        "weather":    "the dome light is doing something strange today",
        "condition":  "the air tastes like rain that never arrives",
        "npc":        "a figure nearby",
        "place":      "this part of the city",
        "district":   "the district",
        "market":     "the market",
        "faction_npc": "someone who knows the streets",
    }
    try:
        from src.db_api import raw_query

        # Current weather
        wrows = raw_query(
            "SELECT current_weather, effects_json FROM weather_state ORDER BY updated_at DESC LIMIT 1"
        )
        if wrows:
            cond = wrows[0].get("current_weather") or ""
            if cond:
                ctx["weather"] = cond.lower()
                ctx["condition"] = cond.lower()

        # Random live NPC
        nrows = raw_query(
            "SELECT name, role, faction FROM npcs "
            "WHERE status NOT IN ('dead','retired') ORDER BY RAND() LIMIT 1"
        )
        if nrows:
            ctx["npc"] = nrows[0].get("name") or ctx["npc"]
            ctx["faction_npc"] = (
                f"{nrows[0].get('name')} ({nrows[0].get('faction') or 'independent'})"
            )

        # Random gazetteer place
        prows = raw_query(
            "SELECT name, district, description FROM gazetteer_places ORDER BY RAND() LIMIT 2"
        )
        if prows:
            ctx["place"]    = prows[0].get("name") or ctx["place"]
            ctx["district"] = prows[0].get("district") or ctx["district"]
            if len(prows) > 1:
                ctx["market"] = prows[1].get("name") or ctx["market"]

    except Exception:
        pass
    return ctx


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pick(pool: list[str], **fmt: Any) -> str:
    template = random.choice(pool)
    try:
        return template.format(**fmt)
    except (KeyError, IndexError):
        return template


# ---------------------------------------------------------------------------
# Scene 1 — Briefing / contract handoff
# ---------------------------------------------------------------------------

_S1_SABOTAGE = [
    "{contact} spreads a rough diagram without greeting you. Three points are circled in red. One is already crossed out. 'The window is closing,' they say, without looking up.",
    "{contact} has memorised the layout — you can tell by the way their eyes move across blank wall space like there's a map there. They tell you where the weak point is before they explain why it matters.",
    "No pleasantries from {contact}. They push a schematic across the table and tap the circled section twice. 'Get it wrong here and the whole job echoes for a week.'",
    "The diagram {contact} shows you is hand-drawn on paper that's been wet before. The target site is marked in three colours — each one a different team that failed. 'Don't be the fourth,' they say.",
    "{contact} burns the briefing paper after you've read it. 'Nothing on paper after this.' The target window is tight and the exit tighter. You have one shot before the shift changes.",
    "{contact} is already watching the room when you walk in. They pass you a folded diagram without speaking. Two exits are marked. One of them has been scratched out.",
    "A list of names on the table. Most are crossed out. {contact} taps the one that isn't. 'This is the mechanism. Everything else is structure.' The job is to remove the mechanism.",
    "Under {weather} dome light, {contact} looks like they haven't slept. The target point is circled on a plan they've annotated in three different hands. They didn't draw all of this alone.",
    "{contact} says the job is simple. The diagram says otherwise. Four chokepoints, two timing windows, and a guard rotation that someone clearly spent money on.",
    "{contact} doesn't show you where the guards are. They show you where the guards aren't. 'That's your lane,' they say. 'It closes in forty minutes.'",
]

_S1_ESCORT = [
    "{contact} is already watching the door when you arrive. The person they want moved sits in the corner with their back to the wall, not eating. The contract has no destination — only a time.",
    "The principal is sitting exactly where {contact} said they'd be, doing exactly what someone does when they know they're being watched: nothing that could be used against them.",
    "{contact} introduces you to the person you're moving without using any names. 'They go where I say, you make sure they get there. Questions after.' Nobody asks questions.",
    "Under {weather} dome glow, the pickup point feels exposed. {contact} has been here long enough to count every exit. They hand you a route and a backup route and say nothing about a third option.",
    "The principal doesn't look at you when {contact} makes the introduction. They're looking at the door. 'How many ways out does {place} have?' they ask. You count four. They've already counted six.",
    "{contact} says the principal is cooperative. The principal says nothing that suggests they agree with that assessment. The contract gets signed anyway.",
    "Three people at {contact}'s table when you arrive. Two leave before you sit down. The one who stays is the one you're moving. They have one bag, already packed, which tells you this isn't the first time.",
    "The route {contact} hands you avoids every Warden checkpoint. That's either very careful planning or someone who knows which checkpoints to worry about. You don't ask which.",
    "{contact} gives you the route in pieces — each leg sealed in a separate fold. 'Open the next one when you've cleared the last.' Under {condition}. The job is designed so you can't be tortured for the full picture.",
    "The person you're escorting through {place} makes eye contact with {contact} and nods once. They don't explain what that means. You don't ask.",
]

_S1_HEIST = [
    "{contact} slides a folded floor plan across the table before you've sat down. Two rooms are marked: where the thing is, where the guards change. 'You have until the second bell,' they say. 'After that it moves.'",
    "The floor plan on the table has been handled by multiple people — the paper is soft at the fold points. {contact} taps the entry corridor. 'Everyone who's tried it came in this way. Don't.'",
    "{contact} doesn't tell you what's inside the target location. They tell you what comes out of it on a regular schedule, and what that schedule looks like when something valuable is there.",
    "Three maps from {contact}: the official layout, the actual layout, and what they think the actual layout looks like now. 'The third one is a guess,' they admit. 'The first one is a lie.'",
    "Under {weather} dome light, the target site looks ordinary. {contact} shows you what it looks like at the second bell: the guard rotation, the gap, and the six-minute window that only exists twice a week.",
    "{contact} shows you where the alarm is. Then they show you where the real alarm is. The second one is smaller and harder to find, which is the point.",
    "The model on the table is hand-built to scale. {contact} moves a small marker to show you the patrol pattern. 'This one stops for thirty seconds at the east corner. Every time. Don't be where it stops.'",
    "{contact} knows the inside of the target site the way people do when they've worked there. They describe it from memory, which is either useful or means you're being set up by someone with keys.",
    "No briefing paper. {contact} speaks the job once, then expects you to have it. Entry, timing, extraction, complications, and what happens if the complications compound. You have until they finish their drink to ask questions.",
    "The diagram is already memorised — {contact} has you read it and then takes it back. 'If you're carrying that when they find you, this conversation never happened.' The window is narrow. The margin is zero.",
]

_S1_COURIER = [
    "{contact} sets a sealed package on the table between you. No address — only a symbol in the wax you're not meant to recognise. 'Don't open it. Don't lose it. Don't be seen with it.' That's the whole brief.",
    "The package is small enough to disappear into a coat. {contact} doesn't explain the contents. They explain the consequence of it not arriving, which is enough.",
    "Under {condition}, the handoff feels fast — {contact} doesn't sit, doesn't offer anything. Package on the table, route in your hand, and a pickup name whispered once. 'If it doesn't reach them before third bell, don't come back.'",
    "{contact} uses a phrase to identify the recipient. You repeat it back. They correct the emphasis on the second word. This matters more than the contents, apparently.",
    "The package from {contact} weighs less than it should for something this important. They notice you notice. 'The value is in what's inside, not what it weighs.' They don't explain further.",
    "{contact} has three routes mapped. You take the one that wasn't their first choice. 'The obvious path has a problem,' they say. 'I don't know what yet. That's why it's not the obvious path anymore.'",
    "No labels on the package {contact} passes you. No marks that mean anything you can read. But the seal has been checked — twice, because you counted — before they let it leave the table.",
    "{contact} wants verbal confirmation you understand the route, the timing, and the single instruction about what to do if intercepted. The answer to that last part is not 'run'.",
    "The delivery point is in {place}. {contact} describes it from a direction you wouldn't naturally approach from. 'Come in from the back side,' they say. 'The front is being watched.'",
    "Three people have handled this package before it reached {contact}. You can tell by the wear on the sealing wax. They don't explain the chain. You don't ask.",
]

_S1_INVESTIGATION = [
    "{contact} doesn't offer you a seat. They push a page of notes across the table and let you read it while they watch your face. Most names are crossed out. One is circled twice.",
    "The case file {contact} hands you has redactions that aren't quite opaque enough. You can read two of the names underneath. One of them is someone you've heard of.",
    "Under {weather} dome light, the photographs {contact} spreads across the table look worse than they sounded in the brief. 'Someone knows something,' they say. 'Someone always does. Find them before the story hardens.'",
    "{contact} has a timeline. It starts three weeks ago and ends with something that hasn't happened yet. The gap between the last confirmed event and now is the job.",
    "The evidence {contact} shows you is what someone was willing to leave behind. Which means somewhere, there's evidence they weren't. 'Start with what's visible,' they say. 'The rest follows.'",
    "{contact} names three witnesses. Two of them have already moved. The third is still in {district}. 'That's either brave or compromised,' they say. 'Find out which before you trust anything they tell you.'",
    "There's a pattern in what {contact} shows you, but it's the absence of a pattern in one area that stands out. Three nights, same location, nothing logged. In this city, that means something happened.",
    "{contact} says the official version is mostly right. The part that isn't is the part that gets people hurt. They hand you the gap and expect you to fill it before anyone else does.",
    "The notes from {contact} are in two hands — whoever started this investigation and whoever inherited it. The handoff point is where the questions stopped and the instructions started. That's where you begin.",
    "A photograph, a ledger page, a name on a receipt that doesn't match the account. {contact} arranges them in order. 'Someone tried to clean this up,' they say. 'They were in a hurry.'",
]

_S1_BOUNTY = [
    "{contact} shows you one thing: a face. No name, no dossier, no reason. The coin is real enough. So is the warning at the bottom: 'This person is already running.'",
    "Under {condition}, the target profile {contact} hands you is light on detail and heavy on urgency. 'They were in {district} three days ago. After that the trail gets warm and then goes cold.'",
    "{contact} doesn't explain why the target needs to be found. They explain what happens to the contract price if the target reaches the outer districts. The number changes your timeline considerably.",
    "The face in the dossier {contact} shows you is unremarkable. That's the problem. 'They can be anyone,' {contact} says. 'Usually they're no one. That's how they've stayed ahead this long.'",
    "One condition on the contract from {contact} is underlined: the target comes back talking. 'Alive and coherent,' they say. 'Alive alone isn't enough.'",
    "{contact} puts three locations on the table. 'They've been in all three. They'll go back to one of them.' No indication which. That's the first thing you have to figure out.",
    "The target has a pattern. {contact} has mapped it out over six weeks. The pattern breaks once. That break is either a mistake or a trap. {contact} doesn't know which. Neither do you, yet.",
    "{contact} says the target isn't dangerous. Then they pause. 'They're not dangerous to you. They're dangerous to specific people for specific reasons. Don't be one of those people.'",
    "Under {weather} dome light, the contract price from {contact} looks like a mistake. It isn't. 'This person cost a lot of the wrong people a lot of the wrong things,' they say. 'Get them back.'",
    "The face {contact} shows you matches a name that's been crossed off three other contracts. 'People keep thinking they've handled it,' {contact} says. 'They haven't. You will.'",
]

_S1_RIFT = [
    "{contact} has burn marks on their left hand they're pretending not to favour. The diagram is half equations, half apology. 'It opened three nights ago. We don't know what came through.'",
    "Under {weather} dome conditions, Rift activity in {district} has been logged four times in the last six days. {contact} shows you the map. The points form a pattern that someone tried to mark as coincidence.",
    "The Rift isn't sealed. {contact} says it 'isn't actively threatening' which is a different statement and they know it. Whatever came through left enough residue that the Wizards Tower has stopped returning messages.",
    "{contact} was at the site when it opened. They're professionally calm about it now, which is the giveaway. 'The area is stable,' they say. 'The area was stable before it wasn't. Go find out which it is now.'",
    "The containment report {contact} hands you has three fields left blank. Not redacted — blank. Whatever the response team saw didn't have a category. 'That's what you're being paid to put a name to.'",
    "{contact} doesn't use the word 'Rift.' They say 'the event.' 'The site.' 'The situation.' When you say it directly, they flinch slightly. 'Call it what you want,' they say. 'Just fix it.'",
    "Under {condition}, the readings {contact} shows you are wrong in the right way — the kind of wrong that means instruments are picking up something real that doesn't have a proper classification yet.",
    "Three Tower Authority personnel have been near the site since the incident. Two of them were recalled. One of them {contact} can't locate. 'That's the detail that worries me,' they say.",
    "{contact} explains the containment protocol, then explains what happens when the containment protocol fails. The list of failures is longer than the list of successes. 'We're not doing this casually,' they say.",
    "The affected area in {place} has been marked and roped. Civilians moved. That level of response for something {contact} is calling 'preliminary' suggests a significant gap between what they're saying and what they know.",
]

_S1_BATTLE = [
    "{contact} is calm the way people get when they've accepted the outcome. They lay out a battle sketch — three approach vectors, two compromised. 'They'll come in waves. The first is just to count your swords.'",
    "Under {weather} dome light, the tactical map {contact} spreads out shows a situation that's worse than the brief implied. 'The numbers changed overnight,' they say. 'The job didn't.'",
    "{contact} has fought at {place} before. They describe the ground from memory, which tells you something useful: they know where the defensive lines broke last time.",
    "The engagement window {contact} gives you is narrow. 'You have until the second position collapses. After that the route out is contested.' Contested is doing a lot of work in that sentence.",
    "{contact} doesn't tell you how many are on the other side. They tell you what resources the other side has been moving for the last three days. You do the math.",
    "Three factions are operating in {district} right now. {contact} explains which two you're working with and why the third one is a problem regardless of what they say they want.",
    "Under {condition}, the area of operation is more complex than the posted mission suggested. {contact} walks you through the adjusted picture. The pay scale should probably be adjusted too, but that's not what they offer.",
    "The position {contact} needs taken is defensible once you have it. Getting there is the problem. They don't dress this up.",
    "{contact} shows you one satellite view of the area and one street-level account from someone who was there two days ago. The two accounts disagree on one detail. That detail is where the real danger is.",
    "{contact} is not a soldier. They brief like one anyway — objectives, phases, fallback point. 'The window closes when the third bell rings in {district},' they say. 'After that, it's a different kind of problem.'",
]

_S1_DEFENSE = [
    "{contact} has a map of the location pinned to the wall with a blade through the centre. Red marks ring three entry points. 'They'll probe first. Hit the soft spot in the second push. The third wave kills you if you let it.'",
    "Under {weather} dome light, the defensive position {contact} shows you has three good walls and one bad one. They're aware of which one. So is whoever is coming.",
    "{contact} has already positioned what resources they have. What they're missing is what you're here to provide. The gap between what they have and what they need is exactly the margin of the fight.",
    "The site {contact} is defending is not the most logical site to defend. They explain why it has to be this one anyway. The reasons are political in a way that will make the fight harder. They know it.",
    "Two previous attempts to hold this location, according to {contact}. Both failed at the same chokepoint. 'We know where it breaks,' they say. 'This time, we're not letting it.'",
    "{contact} talks through the expected approach vectors with the calm precision of someone who has been thinking about this for days. 'The problem is the fourth approach,' they say. 'We can't cover it.'",
    "Under {condition}, reinforcing {place} feels like exactly the kind of job where being right won't be enough. {contact} doesn't disagree. 'Enough' isn't the standard. 'Long enough' is.",
    "The structure {contact} needs defended has three things working in its favour and one thing working decisively against it. They lead with the three.",
    "{contact} names what's inside the defended position. Whatever it is, the number of people willing to take casualties to reach it tells you the value is real.",
    "The brief from {contact} includes a timeline that assumes the attack comes at night. 'If it comes in daylight,' they say, 'the timeline is wrong and everything adjusts.' They show you the adjusted version anyway.",
]

_S1_DEFAULT = [
    "{contact} waits at the far end of a table no one else is sitting at. The contract is already signed on their side. They slide it across without preamble. One clause near the bottom has been rewritten — the ink is still damp.",
    "Under {weather} dome light, {contact} looks like someone who has been waiting too long for this conversation. They don't waste time now that it's happening.",
    "{contact} doesn't explain the whole picture. They explain the part you need to act on, and what happens if you don't act on it fast enough.",
    "The contract {contact} puts in front of you has two signatures already on it. One of them you recognise. You don't say so.",
    "{contact} in {place}, at a table that has clearly been claimed for a while. The brief is short. The consequences of failure are not.",
    "Under {condition}, {contact} keeps the brief verbal. No paper. 'Plausible deniability runs both ways,' they say. You're not sure who that protects more.",
    "{contact} has already considered the obvious question and has a prepared answer. The prepared answer is correct but incomplete. That's the thing worth asking about.",
    "Three other people were offered this contract before {contact} reached out to you. {contact} doesn't say what happened to them. The job is still open, which tells you part of the story.",
    "The fee {contact} names is high enough to be suspicious and low enough to accept. They watch you weigh it. 'The risk is specific,' they say. 'If you know what to avoid, it's manageable.'",
    "{contact} says the timeline is flexible. The way they say it means the timeline is not flexible.",
]


# ---------------------------------------------------------------------------
# Scene 3 — The complication / bad turn
# ---------------------------------------------------------------------------

_S3_ESCORT = [
    "The route was supposed to be clear. It isn't. Something has been moved to block the natural path through, and whoever moved it is still close enough that you can hear them breathing.",
    "Under {condition}, the midpoint of the route has a problem that wasn't there on the walk-through. Someone anticipated the path. That means they either guessed well or were told.",
    "The target slows. Not from exhaustion — they've spotted something ahead that they recognise and you don't. 'That person wasn't supposed to be there,' they say quietly.",
    "The natural choke in the route through {place} is exactly where the pressure appears. Not a coincidence. Someone knew the geography.",
    "Three people falling into pace a block behind you. Not rushing, not speaking. Just maintaining distance with the patience of people who have done this before.",
    "The backup route is compromised too. That means whoever is moving against you had time to prepare — which means someone gave them the timeline.",
    "Under {weather} dome light, the secondary approach to {place} is blocked. Not formally — no faction markers, no authority presence. Just blocked in the way things get blocked when someone wants you to choose a different path.",
    "The target says one word under their breath when the situation changes. You file it away. It isn't a name you recognise yet.",
    "The path through {district} was clear on the approach. Coming back, the geometry of it has changed — a crowd where there wasn't one, a stall moved to cut the sightline.",
    "Someone has been one step ahead of this route since the second turning. Either they have a faster path or they knew where you were going before you did.",
]

_S3_COURIER = [
    "The handoff point has company that wasn't invited. Someone got here first — not to receive the package, but to intercept it. The city goes quiet the way it does when something is about to break.",
    "Under {condition}, the delivery location has changed since the brief. Not moved — changed. New people, new configuration, same address. Something is wrong with the intel or wrong with the recipient.",
    "The signal that was supposed to confirm the pickup is absent. Either the recipient isn't here yet, or they were here and left, or the signal means something different now.",
    "The approach to {place} has an obstacle that feels deliberate. Too specific to be maintenance, too recent to be established. Someone knew the delivery route.",
    "Two people are watching the handoff point from angles that cover both approaches. They're not together — different positions, different pretexts — but they're both watching the same door.",
    "The recipient's confirming phrase is wrong on the second word. Either they're under pressure or they're not the recipient. 'Again,' you say. They can't correct it.",
    "Under {weather} dome light, the path to the delivery point has a watcher at the corner who is trying very hard to look like they're not watching anything.",
    "The package responds to something in {place} — a sound, a proximity, a material. It shouldn't do anything. The fact that it's doing something now changes the calculation.",
    "The original route to the handoff has been cut off cleanly. Not violently — a crowd, a blocked vehicle, a faction checkpoint that appeared since the briefing. Clean cuts mean planning.",
    "Three routes to the delivery point, all of them now compromised in small specific ways. That level of coverage takes resources or foreknowledge. Probably both.",
]

_S3_INVESTIGATION = [
    "The lead that seemed solid has a shadow behind it. Someone has been following the same trail, and they're not interested in answers — they're interested in making sure you stop asking questions.",
    "Under {condition}, the witness you need is not at the location they're supposed to be. They left recently — the chair is still warm. Someone told them you were coming.",
    "The evidence from the earlier scene has been moved since you were last here. Not taken — moved. Slightly. Enough that someone wanted you to know it had been handled.",
    "The second source confirms the first source's account in every detail. Exact same details, exact same emphasis. Either both accounts are true, or one person wrote both of them.",
    "Under {weather} dome light, the lead in {place} terminates at a name that also terminates three other investigations in the city. Whatever that name means, it functions as an ending.",
    "The person you needed to talk to in {district} is no longer available for the reason that doesn't get recorded formally but everyone in the street knows.",
    "Two witnesses give you the same account. A third gives you an account that's almost the same, except for one detail — the detail that would change what everything else means.",
    "The trail goes back further than the briefing suggested. {contact} either didn't know or didn't tell you. Right now you're not sure which is worse.",
    "Someone has been one step ahead of this investigation since before you started. The only way to know that is to have access to the investigation itself.",
    "Under {condition}, the record that was supposed to be here isn't. The absence is the evidence. Someone cleaned this exactly enough to be obvious to someone who knew what to look for.",
]

_S3_BATTLE = [
    "The first contact is light — too light. A handful of fighters, hitting hard and pulling back before you can press. Something larger is still getting into position.",
    "Under {weather} dome light, the second engagement looks different from the first. More organised, more coordinated. Someone in the opposing force has had time to adjust.",
    "The position that was supposed to be held has a hole in it that wasn't in the briefing. Either the briefing was wrong or something has changed since the briefing.",
    "Three separate pressures at once — not enough force to break anything, but enough to stop any single point from supporting the others. Whoever is commanding knows how to split a defensive line.",
    "The opposition falls back with more order than a routed force would show. This is a tactical withdrawal, not a defeat. They're reforming somewhere you can't see yet.",
    "Under {condition}, the situation in {district} has changed since the last report. The positions that were cleared are contested again, which means either they weren't cleared or there were more than the count suggested.",
    "One of your support lines has gone quiet. Not eliminated — quiet. Radio discipline or worse.",
    "The commander on the other side has made one move you didn't predict. That's the dangerous kind of commander: they only need one.",
    "The engagement envelope is larger than the briefed area. They're pushing at the edges — not the centre — which is the correct thing to do against a prepared position.",
    "Under {weather} dome light, the delay in the third wave is wrong. Too long for regrouping, too short for a full repositioning. Something is being brought up.",
]

_S3_DEFENSE = [
    "They come without warning — not a charge but a probe. Scattered fighters testing the edges, counting how many swords swing back. Not trying to win yet. Learning where it hurts.",
    "Under {condition}, the first approach vector has contact before the anticipated window. Either the timeline was wrong or someone moved it up.",
    "The probe at the eastern approach is a distraction. You can tell because it's too visible. Something else is moving while everyone watches that.",
    "Two breach attempts at once — neither of them committed enough to be the real push. They're mapping the response, not mounting an attack. Yet.",
    "Under {weather} dome light, the gap in the outer coverage has been noticed. A small group is moving toward it with the deliberate pacing of people who have permission to be there.",
    "The fortification that was supposed to hold the first wave held it, but barely, and the wave wasn't full strength. The numbers don't match the intelligence.",
    "Three contacts in the {district} perimeter, none of them making a real push. They're watching the gaps respond. Someone is drawing a map of the defence from the outside.",
    "The anticipated attack pattern has changed. This is more mobile than expected, more willing to trade casualties for information about the defensive line.",
    "Under {condition}, the pressure has moved to the flank that was rated lowest priority. Either the intelligence was wrong or the other side has better intelligence.",
    "A runner from the outer position with a message that doesn't match what you're seeing from where you're standing. Someone's picture is wrong. You need to know whose.",
]

_S3_DEFAULT = [
    "The route narrows until conversation becomes a liability. A lantern has been left burning where no one should need light, and boot marks overlap in deliberate confusion. Then the city goes quiet before violence.",
    "Under {condition}, the obvious approach to {place} is no longer the right one. The situation has a new shape since the briefing, and the new shape has edges.",
    "Something has gone wrong at the point where the mission was supposed to get easier. The timing of it is too specific for coincidence.",
    "Under {weather} dome light, the ground between where you are and where you need to be has more problems than the briefing identified. Someone updated the difficulty without updating the contract.",
    "Three things are true that weren't true an hour ago. The job still needs doing, but the way through has changed.",
    "The complication arrives in the shape of a familiar problem in an unfamiliar location. Whoever set this up knows your habits.",
    "Under {condition}, the situation in {district} has a pressure on it that wasn't briefed. The job is the same. The landscape around the job has moved.",
    "Something that was passive has become active. The timing suggests it was waiting for this moment, which means someone was watching for the right trigger.",
    "The path forward has two options. One of them is faster and one of them is safer. The gap between those two choices is where the real decision is.",
    "Under {weather} dome light, {place} is wrong in a specific way — the kind of wrong that comes from careful preparation rather than chance.",
]


# ---------------------------------------------------------------------------
# Scene 2 — The lead / market scene
# ---------------------------------------------------------------------------

_S2_MARKET = [
    "{place} is busy enough to hide a crime and narrow enough to remember one. The air carries old smoke, wet stone, and the metallic tang of recent work. People glance away when you mention the job, but nobody looks surprised.",
    "Under {weather} dome light, {market} has the specific tension of a place that knows something it isn't saying. The stall holders aren't making eye contact.",
    "{district} in the middle of the day is loud enough to be anonymous. The lead is here somewhere — you can tell by the way the ambient noise dips when you ask the right questions.",
    "Under {condition}, {place} has the shape of a place where information travels. Three conversations stop when you pass. One of them resumes with different words.",
    "The lead runs through {market}, which is exactly the kind of place where people who have seen things go to be around people who haven't. {faction_npc} is somewhere in this crowd.",
    "{place} gives you three pieces of information before you've asked for any. The fourth is what you need, and it costs something.",
    "Under {weather} dome light, the approach to the lead in {district} goes through a location that has seen too much traffic recently. Footwear marks, displaced furniture, a smell that doesn't belong.",
    "The contact in {place} is where they're supposed to be, doing what they're supposed to be doing, which is suspicious in itself given what the briefing said about them.",
    "{market} is the kind of place where the information you need is available at a price that isn't money. Two witnesses, one account, three gaps that don't add up.",
    "Under {condition}, the trail through {place} is warm. Not fresh — warm. Someone was here recently and left just enough not to look like they were avoiding leaving a trace.",
]


# ---------------------------------------------------------------------------
# Scene 5 — Debrief / handoff
# ---------------------------------------------------------------------------

_S5_DEBRIEF = [
    "{contact} reads the report once, asks one question you weren't expecting, and then pays. The question isn't about the job. It's about what happened at the part you summarised quickly.",
    "Under {weather} dome light, the debrief with {contact} is shorter than the job deserved. They got what they needed. The rest is overhead.",
    "{contact} listens without interrupting. When you're done, they say, 'There's one thing you didn't mention.' They already know what it is. They want to know if you'll say it.",
    "The payment from {contact} is correct to the letter. No bonus, no complaint, no commentary. The efficiency of that tells you the job was only one part of something larger.",
    "Under {condition}, {contact} in {place} is different from the contact who briefed you. Slightly. The words are right but the emphasis is wrong. You file it.",
    "{contact} says the outcome was satisfactory. They use that word specifically. 'Satisfactory.' You've been paid exactly satisfactory money, which confirms the grade.",
    "Three questions from {contact} during the debrief. Two of them were about what you did. One was about what you didn't do, which is the question that matters.",
    "Under {weather} dome light, {contact} counts the payment in front of you, which is either a courtesy or a message. 'Clean work,' they say. In this city, that's a compliment with conditions.",
    "{contact} makes one note during the debrief. You can't read it from where you're sitting. They fold it before you can look.",
    "The debrief is professional and brief. {contact} thanks you without warmth and without irony. Whatever they hired you to do, it was worth doing. They don't say that, but the speed of the payment does.",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SCENE1_MAP = {
    "sabotage": _S1_SABOTAGE,
    "destroy":  _S1_SABOTAGE,
    "disable":  _S1_SABOTAGE,
    "escort":   _S1_ESCORT,
    "protect":  _S1_ESCORT,
    "guard":    _S1_ESCORT,
    "recover":  _S1_HEIST,
    "retrieve": _S1_HEIST,
    "heist":    _S1_HEIST,
    "theft":    _S1_HEIST,
    "steal":    _S1_HEIST,
    "courier":  _S1_COURIER,
    "delivery": _S1_COURIER,
    "transport":_S1_COURIER,
    "invest":   _S1_INVESTIGATION,
    "interrogat":_S1_INVESTIGATION,
    "find":     _S1_INVESTIGATION,
    "locate":   _S1_INVESTIGATION,
    "missing":  _S1_INVESTIGATION,
    "bounty":   _S1_BOUNTY,
    "hunt":     _S1_BOUNTY,
    "assassin": _S1_BOUNTY,
    "kill":     _S1_BOUNTY,
    "eliminate":_S1_BOUNTY,
    "rift":     _S1_RIFT,
    "arcane":   _S1_RIFT,
    "magical":  _S1_RIFT,
    "contain":  _S1_RIFT,
    "battle":   _S1_BATTLE,
    "assault":  _S1_BATTLE,
    "attack":   _S1_BATTLE,
    "raid":     _S1_BATTLE,
    "defense":  _S1_DEFENSE,
    "defend":   _S1_DEFENSE,
    "hold":     _S1_DEFENSE,
    "siege":    _S1_DEFENSE,
}

_SCENE3_MAP = {
    "escort":   _S3_ESCORT,
    "protect":  _S3_ESCORT,
    "guard":    _S3_ESCORT,
    "courier":  _S3_COURIER,
    "delivery": _S3_COURIER,
    "transport":_S3_COURIER,
    "invest":   _S3_INVESTIGATION,
    "find":     _S3_INVESTIGATION,
    "locate":   _S3_INVESTIGATION,
    "missing":  _S3_INVESTIGATION,
    "battle":   _S3_BATTLE,
    "assault":  _S3_BATTLE,
    "attack":   _S3_BATTLE,
    "raid":     _S3_BATTLE,
    "defense":  _S3_DEFENSE,
    "defend":   _S3_DEFENSE,
    "hold":     _S3_DEFENSE,
    "siege":    _S3_DEFENSE,
}


def scene_read_aloud(
    scene: str,
    *,
    mission_type: str = "",
    contact: str = "the contact",
    faction: str = "",
    title: str = "",
    location: str = "",
    extra: Optional[Dict[str, str]] = None,
) -> str:
    """
    Return a varied read-aloud string for the given scene ("briefing"/"s1",
    "complication"/"s3", "market"/"s2", "debrief"/"s5").

    All pools are fed with live DB context (weather, NPC, location).
    """
    db_ctx = _live_context()
    fmt = {
        "contact":    contact or "the contact",
        "faction":    faction or db_ctx["district"],
        "title":      title or "the job",
        "location":   location or db_ctx["place"],
        "place":      db_ctx["place"],
        "district":   db_ctx["district"],
        "market":     db_ctx["market"],
        "weather":    db_ctx["weather"],
        "condition":  db_ctx["condition"],
        "npc":        db_ctx["npc"],
        "faction_npc":db_ctx["faction_npc"],
    }
    if extra:
        fmt.update(extra)

    mtype = mission_type.lower()

    if scene in ("briefing", "s1", "scene1", "1"):
        pool = _S1_DEFAULT
        for key, p in _SCENE1_MAP.items():
            if key in mtype:
                pool = p
                break
        return _pick(pool, **fmt)

    if scene in ("complication", "s3", "scene3", "3", "bad_turn"):
        pool = _S3_DEFAULT
        for key, p in _SCENE3_MAP.items():
            if key in mtype:
                pool = p
                break
        return _pick(pool, **fmt)

    if scene in ("market", "leads", "s2", "scene2", "2"):
        return _pick(_S2_MARKET, **fmt)

    if scene in ("debrief", "s5", "scene5", "5", "handoff"):
        return _pick(_S5_DEBRIEF, **fmt)

    # Fallback: briefing pool
    return _pick(_S1_DEFAULT, **fmt)
