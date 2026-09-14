"""Shared TTRPG vocabulary (ported from routes/monsters.py): the 5e condition
one-liners and the SRD-text upgrade from the synced conditions library."""

CONDITIONS = {
    'Blinded':       "Can't see. Auto-fails checks requiring sight. Attacks against: advantage. Own attacks: disadvantage.",
    'Charmed':       "Can't attack the charmer or target them with harmful effects. Charmer has advantage on social checks against you.",
    'Deafened':      "Can't hear. Auto-fails checks requiring hearing.",
    'Exhaustion':    "1: Disadvantage on ability checks  2: Speed halved  3: Disadvantage on attacks & saves  4: HP max halved  5: Speed = 0  6: Death",
    'Frightened':    "Disadvantage on ability checks and attack rolls while the source of fear is in line of sight. Can't willingly move closer to the source.",
    'Grappled':      "Speed becomes 0. Ends if the grappler is incapacitated or you are moved out of their reach.",
    'Incapacitated': "Can't take actions or reactions.",
    'Invisible':     "Can't be seen without magic or special senses. Own attack rolls: advantage. Attacks against: disadvantage.",
    'Paralyzed':     "Incapacitated; can't move or speak. Auto-fails STR & DEX saves. Attacks against: advantage. Hits within 5 ft are critical hits.",
    'Petrified':     "Transformed to a solid object. Incapacitated; unaware of surroundings. Auto-fails STR & DEX saves. Resistance to all damage; immune to poison and disease.",
    'Poisoned':      "Disadvantage on attack rolls and ability checks.",
    'Prone':         "Can only crawl. Disadvantage on attack rolls. Melee attacks against: advantage. Ranged attacks against: disadvantage.",
    'Restrained':    "Speed = 0. Own attack rolls: disadvantage. Attacks against: advantage. DEX saves: disadvantage.",
    'Stunned':       "Incapacitated; can't move; can only speak falteringly. Auto-fails STR & DEX saves. Attacks against: advantage.",
    'Unconscious':   "Incapacitated; can't move or speak; unaware of surroundings. Falls prone. Auto-fails STR & DEX saves. Attacks against: advantage. Hits within 5 ft are critical hits.",
}


def condition_texts():
    """Condition name -> rule text. Prefers the full SRD text synced into
    tblConditionsLibrary; the hardcoded one-liners remain the fallback."""
    out = dict(CONDITIONS)
    try:
        from models.ttrpg import tblConditionsLibrary
        for c in tblConditionsLibrary.query.all():
            if c.description:
                out[c.name] = c.description
    except Exception:
        pass
    return out
