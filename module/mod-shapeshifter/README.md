# mod-shapeshifter

Lets a GM become a creature for a while: its model at a chosen share of its true size, its
name, a kit of its abilities, passives and a stat block, then come back exactly as before. The
catalogue lives in the `Shapeshift` addon, which sends the whole kit on one command line.

## Commands (GM)

- `.shapeshifter apply <entry> <b|u> <size 10-200> <tank|bruiser|caster|glass> <kit csv> <passives csv|-> <flags|->`
  where flags are `fly=0|1`, `vis=<SpellVisualKit>`, `st=<transform sound>`, `sd=<death sound>`, and for
  class-grade forms `res=0|1|3` (mana, rage, energy), `gs=<gear set 1-499>`, `mp=<mana % 1-1000>`,
  `mr=<regen per mille per 5 s, 0-200, default 20>`. Kit and passive tokens are spell ids or `f<k>`
  (class-grade family k, spell id 14,000,000 + 20k); a raw id in 14,000,000-14,199,999 is refused.
  Each class-grade subsystem is on only when its flag is sent, so any of them can be switched off
  from the addon without a rebuild.
- `.shapeshifter look <entry> <size>`: model, size and name only.
- `.shapeshifter revert`, `.shapeshifter status` (also prints the band, power type, mana delta, regen,
  form weapons and every gear ledger entry with its level).
- `.shapeshifter prime <entry csv, 1-40>`: sends the client the creature query answers it never asked
  for, through the core's own handler, so the catalogue's 3D preview (SetCreature, the only model
  call this client has) can draw creatures the player has never seen. Silent on success.
- `.shapeshifter size <10-200>`: resizes the current form in place (no revert, no relearning) and
  answers with a fresh `ON;...`. The menu's size slider sends it while dragging.
- `.shapeshifter stance <1-3>`: a class-grade form with weapon stances (world table `shapeshifter_stance`,
  filled by the class-grade build; created by `data/sql/db-world/base/shapeshifter_stance.sql`) swaps to
  that stance's weapons, bonus aura and own abilities in place, in or out of combat (1.5 s cooldown).
  A stanced form starts in stance 1 and every `ON;...` is followed by `STANCE;<n>;<ids>`. Without the
  table the module logs it at startup and stances stay off.
- `.shapeshifter puppet <entry> <size>` / `.shapeshifter puppet off`: the menu preview's private puppet
  (see Preview puppet below). Silent; answers `PUPPET;on;<entry>` or `PUPPET;off`.

Replies go to the addon as a hidden whisper with prefix `SHSH`: `ON;...`, `OFF;<reason>`, `ERR;<code>;<text>`,
`PUPPET;...`, and after the state on `status`, `CAPS;prime,size,as,speed,puppet,size200,puppetsize,stance` (what
this build understands; the addon only sends what it has seen there, so a newer addon stays quiet on an
older module). `nocg` is added when the world database has no class-grade spell rows (spell 14,000,019
is missing); the addon then sends the creatures' own spells and no class-grade flags.

## What it changes, and how it undoes it

Model and size (held through scale auras and level ups), name override, temporary spells
(never saved), passive auras, flat health and armour modifiers, flight. All in memory; revert,
death and logout undo them, and the player keeps their current health percentage. Spells whose
effects would change the saved character (pets, items, skills, the bind point, learning) are
refused. Auras from the form's spells are also written to `acore_characters.shapeshifter_active`
so a login after a crash strips them; the listed guids are loaded once at startup.

While transformed, the player's own spells and all mounts are refused ("You can't do that while
shapeshifted"); item uses and triggered spells still work. A look-only form keeps the player's
own spells but still refuses mounts. In Balanced mode, damage and periodic ticks from the form's
own spells are scaled by player level over creature level; Unleashed scales melee by the
creature's swing instead.

Unleashed also puts the player at the creature's level (at most 83), so hit, resists and armour
mitigation work at it. Only the level field changes: no stats, talents or skills. Every save
writes the player's own level and the next update shows the form's again, so a crash never keeps
it; XP waits until revert, and a level command during the form sets the level the player returns
to.

## Class-grade forms

These need world data and a client patch built from your own client's DBC files (see the top-level
README). Without them the module reports `nocg` and the addon falls back to the creatures' own
spells by itself.

- **Spell bands.** Family k owns ids 14,000,000 + 20k to + 19: bands 0-15 for levels 5b+1 to 5b+5,
  Unleashed 16, 17-19 reserved (14,000,019 is the shared hidden mana regen passive). The engine
  learns the band for the player's level (`MapKitIds`); a level change swaps bands out of combat
  (deferred to leaving combat otherwise). Band rows carry their own numbers, so `SpellScale` is 1.
- **Resource.** `res` switches the power type after the shapeshift auras are cleared; rage starts at
  0, energy full. `mp` sizes a mana pool from a mage's base mana at the level (Unleashed: the
  creature's level, at most 80) as a flat `UNIT_MOD_MANA` delta; `mr` sets the regen passive's
  amount. Revert keeps the mana percentage and restores the power type only if it differs; the
  player's own pool is never written. Power type is never saved.
- **Gear.** `gs` means form gear (Balanced) plus form weapons (both modes). It puts gear set n's items (9,300,000 + 20n + slot, heirloom-scaled through our own
  ScalingStatDistribution rows 20,000 + 20n + slot) in place of the real gear's template stats,
  through a ledger (`src/ShapeshiftLedger.h`) of `Player::_ApplyItemBonuses` calls, each with the
  level pinned to the level it was applied at. Enchants, gems, set bonuses and equip spells stay.
  Any level change undoes and re-applies; revert re-adds every lifted real item. Equipping and
  unequipping are refused while a form's gear is on (both modes).
- **Weapons.** With `patches/core-weapon-override.patch` applied (`COA_WEAPON_OVERRIDE`),
  `Player::SetWeaponOverride` hands the core the form's weapon templates: a dual-wield form swings both
  hands, a two-hander form never an off hand, whatever the character wears; weapon skill is full for
  the level and form swings train no real skill. Unleashed applies the form weapons' damage and speed
  (not their stats) and then computes its melee scale. Without the patch the module still builds, logs
  an error at startup and `.shapeshifter status` says the patch is missing.
- **Hands.** Every form, look-only too, shows what it holds: a form with a gear set shows that set's
  main hand, off hand (shields and held items too) and ranged items; any other form shows its
  creature's `creature_equip_template` (the `as=` creature's when the model's has none); an unarmed
  creature shows empty hands. Only the PLAYER_VISIBLE_ITEM fields change; revert re-shows the real items.
- **Speed.** With `patches/core-form-speed.patch` applied (`COA_FORM_SPEED`), a full form runs
  at `FormRunRate`: the faster of the creature's `speed_run` and a size rule (100% at 2.5 yards tall,
  200% at 20 yards, from the `ht=` model height times the size slider), never above 250% or below the
  player's own. A flying form (`fly=1`) flies at +280%, like an epic flying mount. Speed auras add on
  top; slows still apply. The addon sends `ht=` only once `CAPS` lists `speed`.
- **Fly animation.** A flying form's anim tier (UNIT_FIELD_BYTES_1 byte 3) is FLY while the movement
  flags say flying and GROUND otherwise (movement hook), and GROUND again on revert.
- **Form summons.** Guardians a form's own class-grade spell calls are defensive (set in
  `OnCreatureAddWorld`, after `Guardian::InitStats` forces aggressive): they fight what the player
  attacks or what attacks the player, and never pull what walks past. They end with the form.
- **Preview puppet.** `puppet <entry> <size>` (caps word `puppet`) summons, or reuses, one
  Rabbit (721) per player, visible to that player only, with a null AI, friendly, unselectable,
  rooted and weightless, 91 yards under the lower of the player and the ground (`PuppetZ`; the
  tallest model standing is about 70 yards, and visibility is 2D, so it never shows and is never out
  of range), and dresses it in the creature's first visible model. It reaches the client as a unit a
  model frame can draw: as the client's pet (a private SMSG_UPDATE_OBJECT of the player's own
  UNIT_FIELD_SUMMON, told to that client only; the server keeps its value), or, when the player has a
  real pet there, as boss1 (SMSG_UPDATE_INSTANCE_ENCOUNTER_UNIT ENGAGE; never taken by this client
  outside instances, 2026-09-24). Replies `PUPPET;on;<entry>;pet|boss`, and logs whether the puppet
  was already at the client. `puppet off`, logout and leaving the map restore the client's real pet
  field and despawn it; it despawns on its own after 10 minutes.
- **Re-assertion.** Shapeshift and disarm auras, and `.reset`, run `InitDataForForm`, which resets the
  power type and swing speeds; the aura hooks put the form's back.
- **Accepted drift** (a relog rebuilds every stat): a real heirloom in a slot the core skips on a
  level up keeps its old-level stats; an item repaired mid-form shows its stats until revert.
  `.reset stats` has no hook: revert first.
- A logout revert clears every band's cooldown of the form's families before the save.

## Build

Apply `patches/core-name-override.patch` to the core first (it provides `NameOverride.h`);
`core-weapon-override.patch` and `core-form-speed.patch` are optional (the module builds without
them, minus form weapons and form speed). Copy this folder to your core's `modules/`, re-run the
CMake configure step and build worldserver. `data/sql/db-characters/base/shapeshifter_active.sql`
goes into the characters database; the core's updater applies it when database updates are on,
otherwise run it by hand.

## Tests

`tests/args_test.cpp` (repo root) tests the pure layer (`src/ShapeshiftArgs.h`,
`src/ShapeshiftLedger.h`, no AzerothCore includes), including the gear ledger against a fake core
that replays the core's level-up, `.reset level`, break, repair and destroy sequences. Build it with
any C++17 compiler, for example `cl /std:c++17 /EHsc testsrgs_test.cpp`; it prints `ALL PASS`.
