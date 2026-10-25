"""Hand-checked gameplay features for every card used in the battlebox.

P/T, mana value and card types come from the deckdoctor card mirror; the
fields below are what the mirror's tags get wrong or don't have. Keep this in
sync when a round adds a card: metrics.py refuses decks with unknown cards.

Fields (all optional):
  kill   removal: ("dmg", n, "any"|"creature"), "destroy", "exile", "edict",
         "steal" (gain control), "lock" (can't attack/block or doesn't untap),
         "bounce", ("fight", own-power), "tapall" (Sleep)
  cards  net cards gained over a typical game (ETB draw = 1, cantrip = 0,
         flashback draw = 1, Clue = 1, rummage = 0, 2-for-1 effects = 1)
  counter  "hard" | "soft" (taxing / conditional)
  evasive  flying or can't be blocked; reach = blocks flyers
  bodies   extra creature bodies made over a game (tokens, persist, recursion)
  cast_trigger  grows or makes value from casting instants/sorceries (prowess too)
  anthem   +N/+N to other creatures (permanent) ; pump = temporary team pump
  life     life gained or drained from the opponent over a typical game
  ramp     extra mana per turn
  recursion  returns cards from the graveyard
  ai_weak  the Forge AI plays it badly (from the misplay scans)
"""

F = {
    # --- black
    "Barren Moor": dict(cards=0.3),
    "Bone Shards": dict(kill="destroy", cards=-1, ai_weak=True),
    "Cryptbreaker": dict(bodies=1),
    "Echoing Decay": dict(kill=("dmg", 2, "creature"), ai_weak=True),
    "Fleshbag Marauder": dict(kill="edict"),
    "Gray Merchant of Asphodel": dict(life=8),
    "Headless Rider": dict(bodies=1),
    "Infernal Grasp": dict(kill="destroy", life=-2),
    "Knight of Malice": dict(first_strike=True),
    "Macabre Waltz": dict(cards=1, recursion=True),
    "Midnight Reaper": dict(cards=1),
    "Murder": dict(kill="destroy"),
    "Necromancer's Stockpile": dict(cards=1, ai_weak=True),
    "Putrid Goblin": dict(bodies=1),
    "Putrid Imp": dict(ai_weak=True),
    "Ravenous Chupacabra": dict(kill="destroy", cards=1),
    "Reassembling Skeleton": dict(bodies=1, recursion=True),
    "Scourge of Nel Toth": dict(evasive=True, recursion=True),
    "Stitcher's Supplier": dict(),
    "Dread Wanderer": dict(bodies=1, recursion=True),
    "Gifted Aetherborn": dict(deathtouch=True, life=3),
    "Vampire Nighthawk": dict(evasive=True, deathtouch=True, life=4),
    # --- blue
    "Augur of Bolas": dict(cards=0.7),
    "Baral, Chief of Compliance": dict(cast_trigger=True),
    "Catalog": dict(cards=1),
    "Claustrophobia": dict(kill="lock"),
    "Cloudkin Seer": dict(evasive=True, cards=1),
    "Consider": dict(cards=0),
    "Control Magic": dict(kill="steal"),
    "Convolute": dict(counter="soft"),
    "Counterspell": dict(counter="hard"),
    "Curate": dict(cards=0),
    "Dismiss": dict(counter="hard", cards=1),
    "Haughty Djinn": dict(evasive=True, power_est=3, cast_trigger=True, ai_weak=True),
    "Liquify": dict(counter="soft"),
    "Mana Leak": dict(counter="soft"),
    "Murmuring Mystic": dict(bodies=3, cast_trigger=True),
    "Negate": dict(counter="soft", ai_weak=True),  # r22: cast 34x in 695 castable end steps
    "Remote Isle": dict(cards=0.3),
    "Sleep": dict(kill="tapall"),
    "Think Twice": dict(cards=1),
    "Divination": dict(cards=1),
    "Wind Drake": dict(evasive=True),
    "Unsummon": dict(kill="bounce"),
    # --- green
    "Abundant Harvest": dict(cards=0, ai_weak=True),
    "Arbor Elf": dict(ramp=1),
    "Carnage Tyrant": dict(uncounterable=True, hexproof=True),
    "Centaur Courser": dict(),
    "Eternal Witness": dict(cards=1, recursion=True),
    "Gaea's Herald": dict(),
    "Kraul Harpooner": dict(reach=True, kill=("fight", 3), ai_weak=True),
    "Leatherback Baloth": dict(),
    "Llanowar Elves": dict(ramp=1),
    "Llanowar Visionary": dict(ramp=1, cards=1),
    "Netcaster Spider": dict(reach=True),
    "Pelakka Wurm": dict(life=7, cards=1),
    "Pounce": dict(kill=("fight", 3), ai_weak=True),
    "Rabid Bite": dict(kill=("fight", 3)),
    "Scavenging Ooze": dict(life=2, grows=True),
    "Shifting Ceratops": dict(uncounterable=True),
    "Thrashing Brontodon": dict(kill_ench=True, ai_weak=True),  # AI never sacrifices it (r16)
    "Tranquil Thicket": dict(cards=0.3),
    "Thragtusk": dict(life=5, bodies=1),
    "Gnarlid Colony": dict(),
    "Wild Growth": dict(ramp=1, ai_weak=True),
    # --- red
    "Act of Treason": dict(kill="steal_eot"),
    "Bedlam Reveler": dict(cards=1, cast_trigger=True),
    "Burst Lightning": dict(kill=("dmg", 2, "any")),
    "Dreadhorde Arcanist": dict(cards=1, cast_trigger=True),
    "Expedite": dict(cards=0, ai_weak=True),
    "Festival Crasher": dict(cast_trigger=True),
    "Fists of Flame": dict(cards=0),
    "Flame Slash": dict(kill=("dmg", 4, "creature")),
    "Forgotten Cave": dict(cards=0.3),
    "Goblin Wizardry": dict(bodies=2, cast_trigger=True),
    "Keldon Raider": dict(cards=0),
    "Lightning Bolt": dict(kill=("dmg", 3, "any")),
    "Lightning Strike": dict(kill=("dmg", 3, "any")),
    "Monastery Swiftspear": dict(cast_trigger=True, haste=True),
    "Queen Brahne": dict(cast_trigger=True, bodies=1),
    "Searing Spear": dict(kill=("dmg", 3, "any")),
    "Firebrand Archer": dict(cast_trigger=True, reach_dmg=True),
    "Shivan Fire": dict(kill=("dmg", 2, "creature")),
    "Thrill of Possibility": dict(cards=1),
    "Young Pyromancer": dict(bodies=2, cast_trigger=True),
    # --- white
    "Aeronaut Cavalry": dict(evasive=True),
    "Ampryn Tactician": dict(pump=1),
    "Banishment": dict(kill="exile", ai_weak=True),
    "Benalish Marshal": dict(anthem=1),
    "Elspeth's Smite": dict(kill=("dmg", 3, "creature")),
    "Elite Vanguard": dict(),
    "Greatsword": dict(equip=3, ai_weak=True),  # card impact -25..-40 every round; AI spends 6 mana on it
    "Icatian Priest": dict(),
    "Knight of Grace": dict(first_strike=True, hexproof_from="black"),
    "Lightwalker": dict(),
    "Mikaeus, the Lunarch": dict(anthem=1),
    "Militia Bugler": dict(cards=1),
    "Pearled Unicorn": dict(),
    "Pacifism": dict(kill="lock"),
    "Secluded Steppe": dict(cards=0.3),
    "Silver Knight": dict(first_strike=True, protection_from="red"),
    "Swords to Plowshares": dict(kill="exile"),
    "Thalia's Lieutenant": dict(grows=True),
    "Thalia, Guardian of Thraben": dict(first_strike=True),
    "Raise the Alarm": dict(bodies=2),
    "Healer's Hawk": dict(life=2),
    "Thraben Inspector": dict(cards=1),
}
