# Skill: D&D 5e 2024 Quick Rules Reference
**Keywords:** rules, spell, spells, combat, attack, damage, saving throw, ability check, condition, conditions, action, bonus action, reaction, concentration, death save, rest, short rest, long rest, initiative, AC, armor class, hit points, HP, level, class, feat, proficiency
**Category:** rules
**Version:** 1
**Source:** seed

## When to Use This Skill

This skill provides quick-reference rules for the most common questions. For detailed spell descriptions, class features, or complex interactions, the bot should use the full SRD RAG search via `/rules` or `/spell`.

## Core Mechanics

### Ability Checks
Roll d20 + ability modifier + proficiency bonus (if proficient). DC set by DM or spell.

### Saving Throws
Roll d20 + ability modifier + proficiency bonus (if proficient in that save). Against spells: DC = 8 + caster's proficiency + casting ability modifier.

### Attack Rolls
Roll d20 + ability modifier + proficiency bonus. Melee uses STR (or DEX for finesse). Ranged uses DEX. Spell attacks use spellcasting ability.

### Advantage / Disadvantage
Roll 2d20, take higher (advantage) or lower (disadvantage). They cancel each other out regardless of how many sources.

## Combat Quick Reference

### Turn Order
1. **Movement** — Move up to your speed.
2. **Action** — Attack, Cast a Spell, Dash, Disengage, Dodge, Help, Hide, Ready, Search, Use an Object.
3. **Bonus Action** — If you have a feature or spell that uses one.
4. **Reaction** — Opportunity attacks, Shield spell, Counterspell, etc. Once per round.
5. **Free Interaction** — Draw/sheathe weapon, open door, speak briefly.

### Conditions (Common)
- **Blinded** — Auto-fail sight checks, attacks have disadvantage, attacks against have advantage.
- **Charmed** — Can't attack charmer, charmer has advantage on social checks.
- **Frightened** — Disadvantage on ability checks/attacks while source is in sight. Can't willingly move closer.
- **Grappled** — Speed becomes 0. Ends if grappler is incapacitated or effect removes you.
- **Incapacitated** — Can't take actions or reactions.
- **Invisible** — Heavily obscured, advantage on attacks, attacks against have disadvantage.
- **Poisoned** — Disadvantage on attack rolls and ability checks.
- **Prone** — Disadvantage on attacks, melee attacks against have advantage, ranged have disadvantage. Stand up costs half movement.
- **Restrained** — Speed 0, attacks have disadvantage, attacks against have advantage, DEX saves have disadvantage.
- **Stunned** — Incapacitated, can't move, auto-fail STR/DEX saves, attacks against have advantage.
- **Unconscious** — Incapacitated, drop items, fall prone, auto-fail STR/DEX saves, attacks have advantage, melee hits within 5ft are critical.

### Death Saves
At 0 HP, roll d20 at start of turn. 10+ = success, 9- = failure. 3 successes = stabilize. 3 failures = death. Natural 20 = regain 1 HP. Natural 1 = two failures.

## Resting
- **Short Rest** — 1+ hours. Spend Hit Dice to heal. Some features recharge.
- **Long Rest** — 8+ hours (6 sleeping). Regain all HP, half total Hit Dice (minimum 1). Most features recharge.
