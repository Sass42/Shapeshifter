/*
 * mod-shapeshifter: become a creature for a while, then come back exactly as you were.
 *
 * The addon owns the catalogue and sends the whole kit on one command line; this engine is
 * generic. Everything it changes on a player is held here and undone on revert, death or
 * logout. Map threads read the table from damage, cast and aura hooks, so it is guarded, and
 * the hooks return at once while nobody is transformed (bots are players too, and there are
 * a thousand of them). The lock is never held across a Player or Unit call: the core re-enters
 * our hooks and std::mutex is not recursive, so work is done on a copy and written back.
 *
 * Class-grade forms (docs/superpowers/plans/2026-09-23-shapeshift-c1-c2-class-grade.md) add band-
 * mapped kits that follow the player's level, the form's own resource, and form gear that
 * replaces the real gear's template stats through a Ledger (ShapeshiftLedger.h).
 */

#ifndef SHAPESHIFT_H
#define SHAPESHIFT_H

#include "ShapeshiftArgs.h"
#include "ShapeshiftLedger.h"

#include "Define.h"
#include "ObjectGuid.h"

#include <atomic>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

class Player;
class SpellInfo;
struct CreatureTemplate;

namespace Shapeshift
{
    enum class RevertReason { Command, Death, Logout, Replace };

    enum class CastVerdict { Allow, Refuse };

    // Refusal text for gear changes while transformed (Q6, recommended wording; the user may change it).
    constexpr char const* GearLockedText = "You can't change gear while transformed.";

    struct ActiveForm
    {
        ApplyArgs args;
        bool lookOnly = false;
        std::string name;
        uint32 displayId = 0;
        uint32 creatureLevel = 0;
        uint8 realLevel = 0;                   // Unleashed: the player's own level under the form's; 0: not borrowed
        float scale = 1.0f;                    // the form's size before scale auras
        bool gmFly = false;                    // could fly before, without a mount
        std::vector<uint32> mappedKit;         // what was learned and what the reply carries
        std::vector<uint32> mappedPassives;
        uint32 band = 0;
        bool pendingBand = false;              // a level change in combat: swap on leaving combat
        std::vector<uint32> learned;           // kit spells this form added (never ones already known)
        std::vector<uint32> formSpells;        // kit + passives + their triggered spells: auras to strip
        std::unordered_set<uint32> formSpellSet;
        float healthFlat = 0.0f;
        float armorFlat = 0.0f;
        float spellScale = 1.0f;               // Balanced: level-ratio scale on the form's own spells
        float meleeScale = 1.0f;               // Unleashed: creature swing over player swing
        float runRate = 1.0f;                  // the form's run speed (FormRunRate); 1: the player's own
        float runCreature = 1.0f;              // the creature's speed_run, kept for a resize
        // Class-grade
        Ledger ledger;
        std::vector<FormItem> formItems;       // the gear set's items that exist (both modes)
        bool powerSwitched = false;
        uint8 oldPower = 0;                    // Powers
        float manaFlat = 0.0f;
        uint32 manaTarget = 0;
        int32 regenAmount = 0;
        // Weapon stances (deep pass B2): the current stance (0: none) and what it added.
        uint32 stance = 0;
        uint32 stanceSwitchedMs = 0;
        uint32 voicedMs = 0;                   // the soundboard's last line
        std::vector<uint32> stanceKit;         // the stance's own abilities, band-mapped
        std::vector<uint32> stanceLearned;     // of those, the ones this stance added
        std::vector<uint32> stanceSpells;      // its abilities, bonus and triggers: auras to strip

        bool ClassGrade() const
        {
            if (args.resource != Resource::Default || args.gearSet)
                return true;
            for (uint32 id : args.kit)
                if (IsClassGrade(id))
                    return true;
            return false;
        }
        bool Balanced() const { return args.mode == Mode::Balanced; }
        bool HasGear() const { return !lookOnly && Balanced() && args.gearSet != 0; }      // the stat ledger
        bool HasFormWeapons() const { return !lookOnly && args.gearSet != 0; }             // both modes
    };

    // What the display hook needs, copied out under the lock.
    struct Hot
    {
        uint32 displayId;
        float scale;
        float meleeScale;
        bool flies;                            // a full form that flies: its fly animation in the air
    };

    class Engine
    {
    public:
        static Engine& Instance();

        // Empty on success, else a message for the player.
        std::string Apply(Player* player, ApplyArgs const& args, bool lookOnly);
        void Revert(Player* player, RevertReason reason);
        void SendState(Player* player);
        void SendError(Player* player, std::string const& code, std::string const& text);
        void SendCaps(Player* player);
        std::string Resize(Player* player, uint32 sizePct);
        std::string Stance(Player* player, uint32 stance);
        std::string Voice(Player* player, uint32 sound);
        void LoadStances();
        void Prime(Player* player, std::vector<uint32> const& entries);
        void Puppet(Player* player, uint32 entry, uint32 sizePct);
        void PuppetOff(Player* player);
        std::string Describe(Player* player);
        void LoadLeftovers();
        void OnLogin(Player* player);
        void OnMapChanged(Player* player);
        void OnLevelChanged(Player* player);
        void OnSave(Player* player);
        void OnUpdate(Player* player);
        bool LevelBorrowed(ObjectGuid guid);
        void OnLeaveCombat(Player* player);
        void OnMove(Player* player, bool flying);
        void ReassertScale(Player* player);
        void ReassertForm(Player* player);

        bool AnyActive() const { return _count.load(std::memory_order_relaxed) != 0; }
        std::optional<Hot> Get(ObjectGuid guid);
        bool GearFixed(ObjectGuid guid);
        float SpellScale(ObjectGuid guid, uint32 spellId);
        CastVerdict CheckCast(ObjectGuid guid, uint32 spellId, bool fromItem, bool triggered, bool mounts,
                              bool shapeshifts, bool utility);

    private:
        std::optional<ActiveForm> Copy(ObjectGuid guid);
        void Store(ObjectGuid guid, ActiveForm const& form);

        void LevelOn(Player* player, ActiveForm& form);
        void ApplyStats(Player* player, CreatureTemplate const* info, ActiveForm& form);
        void UpdateMeleeScale(Player* player, ActiveForm& form);
        void BuildFormItems(ActiveForm& form);
        void WeaponsOn(Player* player, ActiveForm& form);
        void WeaponsOff(Player* player, ActiveForm& form);
        void HandsOn(Player* player, ActiveForm const& form);
        void HandsOff(Player* player);
        void SpeedOn(Player* player, ActiveForm const& form);
        void SpeedOff(Player* player);
        void LearnKit(Player* player, ActiveForm& form);
        void UnlearnKit(Player* player, ActiveForm& form);
        void SwapBand(Player* player, ActiveForm& form);
        void GearOn(Player* player, ActiveForm& form);
        void GearOff(Player* player, ActiveForm& form);
        void RunItemOps(Player* player, std::vector<ItemOp> const& ops);
        void RestoreWeapons(Player* player, ActiveForm const& form);
        void ResourceOn(Player* player, ActiveForm& form);
        void ResourceOff(Player* player, ActiveForm& form);
        void ManaOn(Player* player, ActiveForm& form);
        void ManaOff(Player* player, ActiveForm& form);
        StanceRow const* StanceOf(uint32 gearSet, uint32 stance) const;
        void StanceSpellsOn(Player* player, ActiveForm& form, StanceRow const& row);
        void StanceSpellsOff(Player* player, ActiveForm& form);
        void WriteActive(Player* player, ActiveForm const& form);
        void DismissSummons(Player* player);
        std::string OnReply(ActiveForm const& form) const;
        void SendOn(Player* player, ActiveForm const& form);

        std::mutex _lock;
        std::unordered_map<ObjectGuid, ActiveForm> _active;
        std::unordered_map<ObjectGuid, ObjectGuid> _puppets;   // player -> their preview puppet
        std::unordered_set<uint32> _leftovers;  // guid counters with a shapeshifter_active row
        // gear set -> its stances in order; filled once at startup, read-only afterwards
        std::unordered_map<uint32, std::vector<StanceRow>> _stances;
        std::atomic<uint32> _count{ 0 };
        // Players a save put back at their own level: their next update shows the form's again.
        std::unordered_set<ObjectGuid> _levelRestore;
        std::atomic<uint32> _restoreCount{ 0 };
    };
}

#endif
