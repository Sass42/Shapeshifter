# Shapeshifter

**Ever wanted to stomp through Elwynn Forest as Ragnaros? Terrorize Durotar as Hogger? Tank a raid as
the Lich King?** Shapeshifter turns you into the real thing: the boss's own model, name, size,
abilities, gear and talents, on its own action bar, and back to yourself with one click.

A GM tool for AzerothCore (WotLK 3.3.5a) servers, built and tested on Conquest of Azeroth.

- **533 Forms**, about 475 characters to become: 159 classic dungeon bosses, 50 classic raid bosses,
  59 from The Burning Crusade, 83 from Wrath of the Lich King, 34 faction leaders, 26 rare elites and
  66 creature types, from gnolls and murlocs to frost wyrms.
- **Actually become the character**: its own spells with player cast bars, cooldowns and tooltips, its
  own resource (rage, energy or mana), its own gear on your character sheet, and a talent panel.
- **Shapeshifts and stances**: dragons switch between their mortal and dragon forms, bosses that transform
  do it on your stance bar (Zul'jin's five aspects), and weapon-swapping bosses swap too (Mr. Smite's
  scimitar, twin axes and hammer).
- **162 skins** for the creature types: a white bear, a crimson harpy, a Frostwolf, a Defias pirate.
- **Summons** that fight at your side, a 3D catalogue to browse and preview every form, favorites,
  search, and a size slider from pocket-sized to towering.
- Balanced to your level, or Unleashed at the creature's full power.

## Install

1. Download `Shapeshifter-<version>.zip` from the [Releases](../../releases/latest) page and unzip it
   anywhere.
2. Double-click **`Shapeshifter Setup.exe`**.
3. Check what it found, tick **Install for CoA-Bots Server** if that is your server (it ticks itself
   when it sees one running), and click **Install**.

That's it. Setup does the rest, and tells you when it is done. Then log in on a GM account and click the minimap button (or type
`/ss`) to open the catalogue. The menu button or `/ss revert` turns you back; death and
logout do too.

### What Setup does for you

- Finds your server, its source code, your game client and the database login by itself (Browse
  buttons for anything it misses).
- If your server is newer than any source on the PC (a fresh repack, or a repack update), it prepares
  the repack's own source, and for the CoA-Bots server fetches the exact mod-playerbots it was built with.
- Adds Shapeshifter to the source, stops your running server, builds a new one (at low priority,
  so the PC stays usable), swaps it in, sets up the database, installs the class data and the addon,
  and starts your server again.
- Keeps a copy of everything it replaces in `backups/`, and carries your settings over from older
  versions.

**You need:** Windows, git and CMake, and the tools for building AzerothCore (Visual Studio, Boost,
OpenSSL and the MySQL libraries; if you have built your server before, you have them). An internet
connection for the CoA-Bots server. The first build may take a while.

**Uninstall:** open Setup and click **Uninstall**. Everything is put back the way it was, and what it
takes out is kept in `backups/`.

## Why it needs a server build

An addon can only type chat commands, and no server can turn a player into a creature out of the box:
the transforming, the spells and the clean change back all happen inside the worldserver. So
Shapeshifter comes with a server module, and adding a module means building the server. Setup does
that part for you.

## When your repack updates

- **Just run Setup again.** It notices the new server, prepares the matching source and rebuilds.
- **The addon** keeps working unless the update changes the game client's interface or the creatures
  and items its forms are made of.
- **The class data** (spells, gear and talents for every form) is made for the Conquest of Azeroth
  client of its release. On a newer client it puts that release's spell table back, so newer spells
  can go missing until a Shapeshifter release made for that client is out.

## What's inside

| Folder | What |
|---|---|
| `Shapeshifter Setup.exe` | The installer. |
| `addon/Shapeshifter/` | The in-game catalogue, action bar, character sheet and talent panel. |
| `module/mod-shapeshifter/` | The worldserver module (GM command `.shapeshifter`). Details in its own README. |
| `patches/` | Three small core patches the module uses (names, weapons, speed). |
| `classgrade/` | The class data for every form, made for the Conquest of Azeroth client. |
| `install.py` | Setup without the window, for the console (needs Python 3.8+; `--help` lists its options). |

## Disclaimer

- **Back up first:** your server, its databases and your client's AddOns folder. Setup keeps copies of
  what it replaces, but your own backup is the real safety net.
- A GM tool: every server command checks GM level; players without it cannot use it.
- Built and tested only on the Conquest of Azeroth repack (an Ascension client on AzerothCore). The module
  uses stock AzerothCore, and the addon the stock 3.3.5a interface, so other servers may work too.
- Provided as is, without warranty of any kind (see sections 15 and 16 of the `LICENSE`).
- A fan project, not affiliated with or endorsed by Blizzard Entertainment or the AzerothCore project.
  World of Warcraft is a trademark of Blizzard Entertainment.
- Please feel free to submit a PR if you happen to fix some bugs or add characters :D

## License

GNU AGPL v3 (see `LICENSE`). The files in `patches/` change AzerothCore's own source, which is
GPL-2.0-or-later, and those changes follow the core's license.
