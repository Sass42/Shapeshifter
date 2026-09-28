# Shapeshifter changelog

## 1.1.2 (2026-09-28)
- FIX: Setup finds a stopped server in a repack unpacked deep in Downloads, Desktop or Documents (Downloads\CoA-Repack-<date>\CoA-Repack\CoA-Bots\Core). Before, it was found only while running.
- FIX: When the server you pick needs a build tool the first check did not (the exact MySQL client its repack ships), Install names it and opens the build tools window, instead of pointing at a window that was not there.
- FIX: A repack whose Core folder lost its MySQL library is still built against the MySQL client the repack shipped.

## 1.1.1 (2026-09-28)
- FIX: On a CoA repack running CoA-Bots, the new server no longer stops at startup ("world stopped during startup") when the PC already had another MySQL installed. CoA-Bots puts the repack's own MySQL library back at every start, so Setup now builds against the exact MySQL client the repack ships (and downloads it when the PC lacks it). Setup also refuses to put in a server that would stop that way, and leaves yours untouched.
- ADD: Setup keeps the whole log of its last run in setup.log beside it, to send along when something goes wrong.

## 1.1.0 Beta (2026-09-28)
- ADD: Archetype types: 15 archetypes gain 36 real types with their own abilities, talents and gear, as buttons on the archetype's look row. Necromancer (Bone, Frost, Plague, Shadow), bear (Plagued, Grizzly, Ice, War bear), spider (Crystal, Widow, Plague, Trapper), dragonspawn (Black, Blue, Green, Bronze), ancient protector (Ancient, Stonebark, Brightleaf, Ironbranch), giant (Stone, Frost), air (Gale, Storm, Dust), earth (Rock, Ice, Crystal) and water elementals (Tide, Fouled, Mojo), defias (Pillager, Footpad, Pirate, Overseer), vrykul (Berserker, Rune-Seer, Ymirjar, Harpooner), ghoul (Frigid, Volatile), treant (Oak, Withered, Crystal, Tender), dryad (Nymph) and moonkin (Owlbeast, Wildkin). Recolour-only looks were trimmed to make room.
- ADD: Voice lines: in a form whose creature really speaks, a board above the chat window lists its lines (203 forms, up to 12 each). Click one and everyone near hears it and reads it, said or yelled as the creature does. A line can't start until the last one has finished.
- ADD: Arrange the form's bar: drag an ability onto another slot to swap them (out of combat). The layout is kept for each form; `/ss bar reset` puts it back.
- ADD: Right-click the minimap button when you are yourself to become your last form again, with its look, size and Balanced or Unleashed.
- ADD: Move the preview again: right-drag moves the model, the wheel zooms, a middle click goes back to the built-in framing. Your framing is kept for that form (and each skin) the moment you let go.
- ADD: Companion pets can be called, and chests, herbs, ore and quest objects used, while in a form (items already could be).
- FIX: You can't revert in combat any more: your own bar could not come back until combat ended. Death and logout still revert.
- FIX: In a form, the keys of your other bars and bar pages no longer reach your own abilities.
- FIX: Only forms that fly can fly: a GM's own flying is off while a walking form is worn and back on revert. Illidan (both forms), Huhuran, Netherspite, the spore bat and the Doomguard now fly; Razorgore no longer does.
- FIX: No two talents of one form share an icon (401 icons changed on 302 forms).
- FIX: Gear icons match the gear: 886 icons on the character sheet changed so plate looks like plate, robes like robes, and so on. The Lich King wears his Scourgelord plate, Icecrown cloak, necklace and ring, and Frostmourne shows as Frostmourne.
- CHANGE: The Gnoll Mystic is now a type of the Gnoll archetype (the Mystic button on the gnoll).
- CHANGE: The Silithid is a real silithid now (a Hive'Ashi Defender, not a scorpion): Toxic Spit, Cripple and Disarm join its stingers, chitin, burrowing and swarm, and its looks are the hive's own castes (Hive'Zora, Hive'Regal, Drone).
- FIX: The menu remembers Balanced or Unleashed: the last one you picked is the default for forms you have not worn yet.
- FIX: The Talents buttons close the talent window again when it is open.
- CHANGE: The Wave 0 test window (/ss spike) is gone.
- ADD: Setup checks for the build tools first (Git, CMake, Visual Studio Build Tools with C++, Boost, OpenSSL, the MySQL client library). When Setup opens, missing ones come up in a window of their own before it looks for your server, each with a link; tick the ones Setup should download and install, or install them yourself and click Check again. Continue, and later Install, stay off until they are all there. Nothing is bundled.
- FIX: Setup finds git and CMake even when they are not on its PATH (installed while Setup was open, GitHub Desktop's git, the CMake inside Visual Studio), and a missing program is named in words instead of "[WinError 2] The system cannot find the file specified".
- FIX: The new server gets the DLLs it loads beside it (an OpenSSL 4 library, a newer Visual C++ runtime): before, it only started on the PC that built it.
- FIX: Uninstall on a PC that compiled from the repack's own source puts the repack's own server back (kept beside it in shapeshifter-original) instead of compiling again.

## 1.0.0 (2026-09-27)
- First release as Shapeshifter 1.0: 533 forms (about 475 characters, 54 extra shapes, 162 skins), weapon stances, summons, class-grade spells, gear and talents, and a one-click Setup that installs, updates and uninstalls everything.
- FIX: Unleashed now puts you at the creature's level (up to 83) as well as its health, armour and melee, so hits, resists and armour work at its level. Your own level comes back on revert, death or logout and is always the one saved; XP waits while you are Unleashed.
- CHANGE: The Unleashed tooltip reads "Unleashed: Become the NPC at full power".
- IMPROVE: Setup rebuilds the server only when its code changed, builds with three quarters of the CPU, starts the server on its own (Task Manager no longer lists it under Setup), and has a Check for updates button.