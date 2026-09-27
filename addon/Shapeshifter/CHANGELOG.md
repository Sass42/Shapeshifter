# Shapeshifter changelog

## 1.0.0 (2026-09-27)
- First release as Shapeshifter 1.0: 533 forms (about 475 characters, 54 extra shapes, 162 skins), weapon stances, summons, class-grade spells, gear and talents, and a one-click Setup that installs, updates and uninstalls everything.
- FIX: Unleashed now puts you at the creature's level (up to 83) as well as its health, armour and melee, so hits, resists and armour work at its level. Your own level comes back on revert, death or logout and is always the one saved; XP waits while you are Unleashed.
- CHANGE: The Unleashed tooltip reads "Unleashed: Become the NPC at full power".
- IMPROVE: Setup rebuilds the server only when its code changed, builds with three quarters of the CPU, starts the server on its own (Task Manager no longer lists it under Setup), and has a Check for updates button.

## 0.15.0 (2026-09-27)
- CHANGE: Shapeshift is now Shapeshifter: the addon folder (Interface/AddOns/Shapeshifter), its title, the server module (mod-shapeshifter), the GM command (.shapeshifter; .shapeshift still works) and its database tables (shapeshifter_active, shapeshifter_stance). /ss, /shapeshift and /shapeshifter all open the catalogue. The installer carries your favorites and chosen skins over to the new name.

## 0.14.0 (2026-09-26)
- ADD: Archetype skins: 49 archetypes offer 162 more looks (up to six buttons each) as buttons over the preview (its own, other skins of its kind, and variants with their own abilities). A skin keeps the archetype's abilities, talents and gear; the choice is remembered per archetype. Skins never appear on the stance bar. Hover a button to see which creature the look comes from.

## 0.13.0 (2026-09-26)
- ADD: Sneed, the Deadmines Lumbermaster, as two shapes: Sneed's Shredder (rage, Buzz Saw, whirling saws) and Sneed on foot (energy, Disarm, dynamite, and two Goblin Woodcarvers called "Back to Work").
- Needs the matching class-grade server data (shapeshift_class.sql and patch-Y.MPQ built 2026-09-26 evening).

## 0.12.4 (2026-09-26)
- CHANGE: Preview framing is built in: every form you centred shows that way for everyone. The move, zoom and reset controls and their tooltip are gone; drag or the arrows still turn the model.

## 0.12.3 (2026-09-26)
- FIX: The catalogue preview appears already framed instead of showing off-centre and jumping into place.

## 0.12.2 (2026-09-26)
- FIX: The catalogue shows each ability as the form's bar will: its own icon, name and tooltip at your level, not the borrowed spell's (Voidwalker no longer shows three identical icons).

## 0.12.1 (2026-09-26)
- FIX: Cast-time abilities stop when you move, like any cast; they used to go off on the run.
- FIX: Mr. Smite fights like the real First Mate: one scimitar, then two of Smite's Reavers (axes), then his Mighty Hammer. He wears a harness, and it shows a harness icon.
- FIX: Malchezaar's first stance and all of Mimiron's stances are bare-handed, as in their fights.
- CHANGE: Every form has at least one damaging ability that costs nothing (on a stanced form, every stance does). Lorekeeper Polkelt gains Acid Spit, the Clefthoof Bull Gore, Rhahk'Zor and Houndmaster Grebmar Strike.
- CHANGE: No two abilities on one form share an icon.
- CHANGE: Gear and weapon icons on the character sheet match the item; 127 items that showed no icon now have one.
- CHANGE: 19 forms that looked the same as another now have their own look, keeping their name and level (the gnoll next to Hogger is a Riverpaw Overseer now, Rethilgore a white Shadowfang worgen, Saragosa a Coldarra blue dragon, and more).
- ADD: Thrown weapons for the Dragonflayer vrykul (harpoon), the Kolkar centaur (spear) and Thora Feathermoon (knife), who throw them in their fights.
- FIX: The catalogue shows a stand-in form's real name and level.
- Needs the matching class-grade server data. If a weapon still looks like an old one, close the game and delete the client's Cache folder: the client remembers items by number, and some numbers now hold different weapons.

## 0.12.0 (2026-09-26)
- ADD: 153 new forms: every classic dungeon boss that was missing (Ragefire Chasm through Stratholme, from Aku'mai to the Seven of Shadowforge), plus 26 rare elites with their own story, each a full class with its own kit, gear and talents. Shape pairs where the creature really changes: Theka the Martyr's scarab, Celebras cursed and redeemed, Alzzin the Wildshaper's wolf and tree, Magistrate Barthilas and his disguise.
- ADD: A "Rare Elites" tab after Classic Dungeons; the tabs sit a little closer so all ten fit.
- CHANGE: Silent creatures no longer carry a made-up quote on their signature ability.
- Needs the matching class-grade server data and the 2026-09-26 worldserver (it allows up to 1000 gear sets).

## 0.11.0 (2026-09-26)
- CHANGE: Every form reworked after a full audit of all 378: signature abilities that did nothing now work or are remade, twins and copy-paste kits split into their own heroes (Grom the Blademaster, Muradin the Mountain King, Magni the Ironforge king, Mal'Ganis the Dreadlord, and many more), tanks get a taunt, and remade abilities show their own names instead of the borrowed spell's.
- CHANGE: Balance: chain spells hit a few targets and never grow per jump, debuffs and damage over time on enemies no longer stack, stuns, fears, sleeps and silences follow set cooldowns, talents no longer fire stuns or fears, bursts last at most 10 sec, and absorbs and damage shields scale with your level.
- CHANGE: A form's damage now scales with the stat its gear carries: spell power for mana forms, attack power for rage and energy forms.
- CHANGE: Jewellery goes on anything with hands; animals and handless creatures wear none (dragons in dragon form get a themed passive instead).
- FIX: Tooltips now say what an ability really does: how many targets it reaches, whether it hits an area around you, its real school.
- Needs the matching class-grade server data (shapeshift_class.sql and patch-Y.MPQ built 2026-09-26).

## 0.10.1 (2026-09-25)
- ADD: Summon abilities: a form can call helpers that fight at your side for a while and leave when you change back (Princess: Call the Entourage, two boars for 20 sec). They need the class-grade server data; elsewhere the ability is simply left out of the form.

## 0.10.0 (2026-09-25)
- ADD: Weapon stances: a form with stances shows them on the stance bar after its shapes (same keys). A stance swaps the form's weapons, its stance bonus and its own extra abilities, and works in combat; the boss bar picks up a stance's abilities once combat ends. Needs a server whose Shapeshift module lists `stance`; older servers never get the command.
- ADD: The character sheet shows the current stance's weapons.
- FIX: The shape buttons on the stance bar now draw their slot border, highlight and checked glow (the texture paths had lost their backslashes).

## 0.9.1 (2026-09-25)
- CHANGE: Ragnaros's talents: Lava Surge (a chance to hurl a Magma Blast when your abilities hit, once every 6 sec) replaces Living Flame, and Wrath of the Firelord now cuts Wrath of Ragnaros's cooldown by 2 sec instead of raising spell crit. Needs the matching class-grade server data.

## 0.9.0 (2026-09-25)
- ADD: A Group button above the tabs sorts the catalogue by Type, Dungeon/Raid, Zone, Expansion or A-Z (right-click goes back). Dungeon/Raid lists the forms from each dungeon and raid under its name, Zone the open-world forms under their zone, both in game order (raids of the same level in release order); Expansion splits Classic, The Burning Crusade and Wrath of the Lich King; A-Z goes by letter. The tabs still filter, and search works in every grouping.
- ADD: An All Forms tab, so every form can be grouped at once.
- ADD: The mouse wheel over the grid scrolls it a row at a time; the page buttons still move four rows.
- IMPROVE: The catalogue opens on the tab and grouping you last used.

## 0.8.7 (2026-09-25)
- FIX: On a server without the class-grade data (the module answers CAPS with nocg), forms use the creatures' own spells and no form gear, with no /run line needed. A server that never says nocg keeps class-grade on.

## 0.8.6 (2026-09-24)
- FIX: The Naxxramas bosses (Kel'Thuzad, Sapphiron, Patchwerk, the Four Horsemen and the rest) are under Wrath of the Lich King and Doom Lord Kazzak under The Burning Crusade: the versions in this game are those expansions' remakes (levels 83 and 73). Onyxia stays under Classic Raids.

## 0.8.5 (2026-09-24)
- ADD: Frame the preview yourself: right-drag moves the model, the mouse wheel zooms, left-drag still turns it, and a middle click goes back to the automatic framing. Your framing is kept for each form. The automatic framing (camera distance 1.5, lift 0.11, measured in game) is the starting point; the preview camera treats some models its own way (Gortok, Onyxia, Ragnaros), which this is for.

## 0.8.4 (2026-09-24)
- ADD: The preview frames each creature by itself: the model's bounding box, from the game data, is centred where Hogger's sits, and big models are pulled back from the camera until they fit. The camera distance is being calibrated in game (`/run Shapeshift.PreviewCalibrate()` steps through it on the preview).

## 0.8.3 (2026-09-24)
- FIX: Preview models are back in the frame (0.8.2's scaling moved them out of view). Big creatures still spill over until the zoom is tuned: `/run Shapeshift.PreviewFit(back, down)` tries a camera distance on the current preview.

## 0.8.2 (2026-09-24)
- FIX: Big creatures fit the preview. The frame draws the puppet at its natural size whatever size the puppet is, so the frame now scales the drawn model itself: its bigger dimension comes out about two yards, like Hogger's.

## 0.8.1 (2026-09-24)
- FIX: The preview puppet is sized to fit the frame: its bigger dimension comes out about two yards, like Hogger's, so Chromaggus, Sartura and Gortok no longer overflow. Giants and dragons need the rebuilt bots worldserver, which lets the puppet go below 10% (a 90-yard dragon needs 2%); until then they stop at 10%.

## 0.8.0 (2026-09-24)
- CHANGE (needs the rebuilt bots worldserver): The menu preview's puppet now reaches your client as your pet, told to your client alone (your real pet state on the server is untouched, and nobody else sees anything), because the client never took it as a boss unit. The pet frame stays hidden while you browse. With a real pet out, the preview falls back to the boss unit, then to loading by creature.

## 0.7.9 (2026-09-24)
- FIX: The puppet preview asks a second time when your client missed the hand-over (it can arrive before the puppet itself), and if the client still does not take it, the menu stops trying for the rest of the session, so picks no longer wait 3-4 seconds for it.

## 0.7.8 (2026-09-24)
- FIX: No more blue checkered cube in the menu preview, and previews load again. 0.7.5 blanked the frame with a model file that does not exist, which this client draws as its error cube and would not load over. The preview now stays invisible while it loads and shows the new model once it is really on.
- FIX: Tall creatures are shrunk more gently in the preview, by height rather than length (Buru was a speck).

## 0.7.7 (2026-09-24)
- FIX: The puppet preview is full size again. A live model is already framed to its own size, and the shrink meant for loaded models made Buru a speck.
- CHANGE (needs the rebuilt bots worldserver): The size slider goes up to 200% of true size. On an older server it stays at 100%.

## 0.7.6 (2026-09-24)
- ADD (needs the rebuilt bots worldserver): The menu preview shows every form exactly as it looks in the world, humanoids included. The server dresses a private puppet, hidden far under the ground below you and visible to nobody else, as the form you pick and hands it to your client to draw; closing the menu removes it. Inside dungeons and raids, where the boss frames are in use, and on an older server, the preview loads models as before.

## 0.7.5 (2026-09-24)
- FIX: The menu preview no longer shows the previous form when the new one has not loaded yet (Buru showed a skeleton). This client's ClearModel leaves the old model up, so each preview now starts from an empty placeholder and only counts as loaded once the new model is really on.
- FIX: Large models are shrunk to fit the preview (Mekgineer Thermaplugg overflowed it).
- CHANGE: Humanoid characters drawn from player-race models (Herod and 87 others) show their icon in the preview: this client draws them in a model frame as a white body in the wrong clothes. They still look right in the world.

## 0.7.4 (2026-09-24)
- FIX: Your own stance bar is hidden in every form, not only in forms with several shapes, and stays hidden when the client tries to show it mid-form. On revert it follows the client's own rule, so it comes back whenever you have stances (it stayed gone after Alexstrasza's shapes).
- FIX: An open talent window now follows the form you pick in the menu, and closes for a plain creature.

## 0.7.3 (2026-09-24)
- FIX: The menu's 3D preview shows the creature again. This client has a SetDisplayInfo that loads nothing, and an empty model frame reports itself instead of an empty path, so the preview thought a model was loaded and never fell back to the creature (or to the big icon).
- ADD (needs the rebuilt bots worldserver): Forms run at their own speed and flying forms fly like an epic flying mount. The addon sends each form's model height, and only to a server that says it understands it.

## 0.7.2 (2026-09-24)
- FIX: The form's abilities dim on the boss bar like the stock bar's: blue when you are short of rage, energy or mana, grey when they cannot be used for another reason, and a red key label when your target is out of range.
- CHANGE: While you are a form, your other action bars (bottom left, bottom right, right and right 2) are hidden, so only the form's abilities show. The bars that were showing come back on revert.
- ADD: Becoming a large form (about three times a human's height or taller at its current size, e.g. Gruul, Onyxia, Alexstrasza) pulls the camera all the way out, and every form zooms with the mouse wheel at the client's fastest. Your own zoom speed comes back on revert with your other camera settings.

## 0.7.1 (2026-09-24)
- CHANGE: A character's shapes now sit on a stance bar, like a druid's forms: one button per shape where your own stance bar is (hidden while you are the form), the shape you wear highlighted, your stance keys (Ctrl+F1 and on by default) picking a shape directly, and the 10 second cooldown shown on every button. Each button's tooltip lists that shape's abilities and bonuses. The single change-shape button at the end of the boss bar is gone; its key binding still steps to the next shape.
- CHANGE: Arlokk, Thekal, Mar'li, Gal'darah and Nalorakk now have troll bonuses in their troll shape (priestess or warrior), so their panther, tiger, spider, rhino and bear shapes' beast bonuses are their own.

## 0.7.0 (2026-09-24)
- FIX: Vaelastrasz's Essence of the Red is gone from his kit: it buffed the enemies around you, not your allies.
- ADD: Wave 4 brings 64 new characters: the holiday bosses (Headless Horseman, Coren Direbrew, Ahune), lore figures (Alexstrasza, Rexxar, Maiev, Akama, Khadgar, Rhonin, High Overlord Saurfang, A'dal, Koltira, Thassarian and more), raid, dungeon and classic bosses the roster lacked (Lady Deathwhisper, the Iron Council, the twilight drakes, the Val'kyr Twins, the Emerald Dragons, Gandling, Balnazzar and more), and new creature types (succubus, felhunter, pit lord, nether and proto-drakes, sporebat, clefthoof, nightsaber, dryad, moonkin, wisp, iron dwarf, ancient protector).
- ADD (needs the rebuilt bots worldserver): Characters with more than one shape have them all, 48 new shapes in all: dragons and their mortal guises (Alexstrasza, Korialstrasz and Krasus, Kalecgos and Kalec, Onyxia and Lady Katrana Prestor, Nefarian and Lord Victor Nefarius, Ysera, Eranikus, Chromie, Vaelastrasz, Keristrasza, Saragosa, Anachronos, Caelestrasz, Cyanigosa) and the bosses that transform in their fights (the Zul'Gurub priests' animal forms, Zul'jin's four aspects, Nalorakk, Halazzi, Gal'darah, Illidan and Leotheras' demons, Solarian, M'uru and Entropius, Ingvar, Hydross, Putricide, Attumen, the Big Bad Wolf's Grandmother, Felmyst and Madrigosa, C'Thun, the Devourer's faces, Yogg-Saron, Acidmaw, Buru, the unhorsed Horseman, Balnazzar's Dathrohan, the Black Knight's three phases). Each character is one menu entry with a toggle over the preview naming its shapes; while you wear any of them, a button at the end of the boss bar (bindable under Key Bindings, Shapeshift) changes to the next shape in place, keeping your health, mode and size. 10 second cooldown; not in combat. A shape drawn from a stand-in creature keeps the real character's name, level and stats.

## 0.6.2 (2026-09-24)
- ADD: In a form, the character sheet's "Level 20 Orc Barbarian" line reads "Level 20" and the form's title instead, e.g. "Level 20 The Firelord" or "Level 20 Queen of the Frostbrood". 36 titles are the creatures' own from the game data; the other 230 are drafted from lore and other versions of the game (review list: data/shapeshift/research/titles-draft.md).

## 0.6.1 (2026-09-24)
- FIX: Form gear now shows on the character sheet. Ascension replaces the stock paper doll with its own panel and slot buttons, and the form gear was being drawn on the stock sheet, which is never shown; it now uses Ascension's.

## 0.6.0 (2026-09-23)
- ADD (needs the rebuilt bots worldserver, deployed with it): class-grade forms are live. Every form's kit and talents are real player spells scaled to your level in 5-level bands, the form uses its own resource (Ragnaros casts with mana even on an energy class), and it wears its own gear, shown on the character sheet with heirloom tooltips. Form armour carries no armour type, so no red "Mail" or "Plate" line on a class that cannot wear it.

## 0.5.9 (2026-09-23)
- ADD: While you are a form, the camera can pull back as far as the client allows, so a huge form like Ragnaros no longer leaves the camera inside the model. Your own zoom settings are put back on revert, even after a /reload mid-form.

## 0.5.8 (2026-09-23)
- FIX: The boss bar's spells now stay on your main bar while you are transformed. The client re-showed your own buttons on top of the boss bar whenever the bar refreshed (learning the form's spells does that); your buttons are now held hidden the way the client's own vehicle bar does it, restored exactly on revert, and the boss bar sits above the stance bar.
- ADD (needs the rebuilt bots worldserver): Dragging the size slider on the form you are wearing resizes you as you drag, without re-transforming (at most five updates a second, the final size always sent). The "You are now ..." chat line is not repeated for a size change.

## 0.5.7 (2026-09-23)
- FIX (needs the rebuilt bots worldserver): The menu's 3D model now shows creatures you have never seen. This client can only draw a creature it has cached, so when the preview comes up empty the addon asks the server to send that creature (`.shapeshift prime`), then draws it; the big icon remains the last fallback. The addon only does this once the server says it supports it, so nothing changes on today's server.

## 0.5.6 (2026-09-23)
- ADD (inactive until the class-grade data ships): a class-grade form's talents travel on the apply line after its passives, so the server grants them with the form.

## 0.5.5 (2026-09-23)
- FIX: Ten forms failed to apply at all because their kit used a player class spell, which the server refuses: Murloc, Cobrahn, Serpentis, Thalnos, Mograine, Voidwalker (Torment, again), Lor'themar, Brann, Medivh and the Trogg. Each now uses the creature version of the same ability (Healing Wave, Healing Touch, Flame Shock, Hammer of Justice, Taunt, Aimed Shot, Arcane Explosion, Frost Nova, Sunder Armor). The generator now applies the server's rule, so this cannot ship again.
- FIX: Kit audit of every form (1,199 abilities): 72 abilities replaced, 34 dropped, 6 added. Gone: buttons that stunned, rooted, slept or killed you (Knockdown on Gamon, Greenskin, Morladim and Rend; Web Wrap, Garrote, Evocation, Energize, Vanish, Soulstorm, Iron Roots, Fade, Burn, Armageddon), passives that hurt you (the Infernal's Immolation, the Spider's Poison, the Ogre Mauler's Bash), instant kills (Void Blast, Rocket Strike, Hand of Death, Big Bang, Sapphiron's raid Frost Breath, Decimate, Enfeeble), Arugal's mind control, bites that hit your allies, and encounter-only pieces that do nothing outside their fight.
- FIX: C'Thun's Spit Out (the exit from his stomach, with no text) is now Eye Beam. The swallow half is a scripted teleport into the stomach, not a spell a player can cast.
- ADD: More abilities for the thinnest kits: Water Elemental (Frostbolt), Defias (Frost Nova), Fel Reaver (Earthquake), Spider (Poison), Viscidus (Toxin), Morogrim (Watery Grave).
- FIX: A kit ability the client has no description for now shows the form's own description in its tooltip, with the creature spell's numbers.
- FIX (inactive until the class-grade data ships): Form gear now uses this client's item appearance numbers, so each piece shows its own model and icon (Sulfuras had been showing as a belt).

## 0.5.4 (2026-09-23)
- ADD: Every form has its own fixed set of 4 to 6 themed talents (names, icons and exact values), shown in Form Talents after the creature's own passives. They are granted by the form and take effect with the class-grade server update (the one rebuild); until then the panel shows what each form will have.
- CHANGE: The empty talent panel now says the form has no talents (not passives).

## 0.5.3 (2026-09-23)
- ADD: Each menu tab shows its own dungeon-finder artwork behind the grid (Molten Core for Classic Raids, the Deadmines for Classic Dungeons, the Black Temple for The Burning Crusade, Icecrown Citadel for Wrath, the Wailing Caverns for Archetypes, the Halls of Reflection for Faction Leaders, quest paper for Favorites and Any Creature).
- ADD: Form Talents uses class-talent artwork matching the form's school (fire, frost, shadow, nature, holy, physical, arcane).

## 0.5.2 (2026-09-23)
- FIX: The detail pane's 3D model now loads by display id, so creatures your client has never seen still show as a model instead of the icon (when this client can load by display id; otherwise it asks the server twice before falling back).
- ADD: Rotate buttons under the model (hold to turn), as in the dressing room; dragging still works.
- CHANGE: Form Talents opens beside the window it came from: right of the menu, or right of the character sheet, never on top of other Shapeshift windows.
- ADD (inactive until the class-grade data ships):
  - ADD: Class-grade apply lines: a class-grade form's kit travels as family tokens (f<k>) with its resource, gear set and mana flags, and each part can be switched off in the saved settings (`ShapeshiftDB.classGrade`: spells, resource, gear, mana). Nothing sends them until the class-grade data ships.
  - ADD: Form gear on the character sheet: while a class-grade form is active (either mode), all 19 slots show the form's own items with quality borders, their tooltips and shift-click links; a slot the form has no item for shows empty; a "Form gear" label sits under the model.
  - ADD: The Form Talents panel shows a class-grade form's passives as the band the player's level uses (or the Unleashed row).

## 0.5.1 (2026-09-23)
- FIX: The Voidwalker form's Torment used the pet-teaching version of the spell (7881), which the server refuses, so the whole form failed to apply; it now uses Torment itself (3716).
- ADD: Class-grade band maths (Core/Bands.lua): spell band, family and form-gear ids, shared with the generator and the server module. Nothing uses it yet.

## 0.5.0 (2026-09-23)
- ADD: Roster expansion: 118 more forms (264 in all: 62 classic raid, 26 classic dungeon, 55 TBC, 47 WotLK, 53 archetypes, 21 leaders and heroes). The rest of Molten Core, Blackwing Lair, Zul'Gurub, Ahn'Qiraj and Naxxramas; Serpentshrine, Tempest Keep, Hyjal, Zul'Aman, Sunwell, the Illidari Council, Karazhan and more; Ulduar, the Coliseum, Vault of Archavon, the Frozen Halls, Ruby Sanctum and Utgarde; Vol'jin, Cairne, Magni, Muradin, Tyrande, Velen, Lor'themar, Tirion, Darion Mograine, Medivh, young Thrall and Brann; and 20 new archetypes. Shared boss scripts are split per member by lore; thin kits are filled from their own kind's spells or their Warcraft III hero kit, always as real in-game spells. All untested.

## 0.4.0 (2026-09-23)
- ADD: The whole roster: 116 more forms (146 in all: 24 classic raid, 26 classic dungeon, 31 TBC, 23 WotLK, 33 archetypes, 9 faction leaders), kits from each creature's own spells and, where thin, its own kind or lore spells found by name. Skipped on purpose: instant kills, mind control, force-casts, summons, transforms and timed-death debuffs. All untested.

## 0.3.1 (2026-09-23)
- ADD: Form Talents panel: a form's passives shown like the talent frame (read-only, rank filled in, talent tooltips); opens from the menu's detail pane, a Form Talents button on the character sheet while transformed, or `/ss talents`.

## 0.3.0 (2026-09-23)
- ADD: Wave 1: 30 forms across the six pools (five each), with kits taken from each creature's own spells and, where a creature has few on record, researched from its own kind or its other appearances. Icons checked against the client files; voice lines from the creature's own sounds. Every ability is marked untested until tried in game.

## 0.2.0 (2026-09-23)
- ADD: Catalogue window: pool tabs, search, a paged icon grid of forms, a name list for Any Creature, and a detail pane with the 3D model (icon when the model will not load), abilities, passives, Balanced/Unleashed, a size slider, Favorite, Flag for curation and Transform/Revert.
- ADD: Minimap button showing the current form; left-click opens the menu, right-click reverts, drag to move.
- ADD: Boss bar: while transformed, the form's abilities replace the main bar and take its keys; the real bar and keys come back on revert (after combat if you revert mid-fight).
- ADD: Favorites, flags and each form's last mode and size are remembered.
- CHANGE: Nothing but one status probe is sent until the server has answered on the character, so a non-GM character never says Shapeshift commands aloud. `/ss status` retries.
- CHANGE: `/ss` with no arguments opens the menu.

## 0.1.0 (2026-09-23)
- ADD: Core protocol: builds `.shapeshift` GM commands from a form and parses the server's replies.
- ADD: `/ss apply | look | revert | status | spike` slash command.
- ADD: Generated form and creature data (tools/gen_shapeshift.py).
- ADD: Wave 0 spike harness (temporary, removed once the spike is answered).
