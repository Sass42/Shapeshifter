/*
 * mod-shapeshifter, the gear ledger: which item bonuses to take off and put on so a class-grade
 * form's gear replaces the real gear's template stats, and how to undo it exactly. Pure (no
 * AzerothCore includes); tools/test_shapeshift_cpp.py tests it against a fake core that replays
 * the core's own level-up, .reset level, break, repair and destroy sequences.
 *
 * The engine executes each ItemOp as Player::_ApplyItemBonuses(template(entry), slot, apply) with
 * UNIT_FIELD_LEVEL pinned to op.level for that one call (adjudication D2 in
 * docs/superpowers/plans/2026-09-23-shapeshift-c1-c2-class-grade.md), then UpdateAllStats once.
 *
 * Rules:
 *   - Lift only real items that are unbroken and usable (the core skips the others itself).
 *   - Undo replays the ledger in reverse, each entry at the level it was applied, and re-adds EVERY
 *     lifted real item, even one that broke, moved or was destroyed since: the core balances its own
 *     break, repair and remove pairs separately.
 *   - A level change (however it happened) is Undo then Lift at the new level.
 */

#ifndef SHAPESHIFT_LEDGER_H
#define SHAPESHIFT_LEDGER_H

#include <array>
#include <cstdint>
#include <vector>

namespace Shapeshift
{
    constexpr uint8_t SlotMainHand = 15;
    constexpr uint8_t SlotOffHand = 16;
    constexpr uint8_t SlotRanged = 17;

    struct RealItem
    {
        uint8_t slot = 0;
        uint32_t entry = 0;
        uint64_t guid = 0;
        bool broken = false;
        bool usable = true;          // CanUseAttackType(GetAttackBySlot(slot))
    };

    struct FormItem
    {
        uint8_t slot = 0;
        uint32_t entry = 0;
        bool weapon = false;         // ITEM_CLASS_WEAPON: this hand swings (core weapon override)
    };

    struct ItemOp
    {
        uint8_t slot = 0;
        uint32_t entry = 0;
        uint32_t level = 0;
        bool apply = false;

        bool operator==(ItemOp const& other) const
        {
            return slot == other.slot && entry == other.entry && level == other.level && apply == other.apply;
        }
    };

    struct LedgerEntry
    {
        uint8_t slot = 0;
        uint32_t entry = 0;
        uint64_t guid = 0;           // 0 for form items
        uint32_t level = 0;
        bool form = false;
    };

    class Ledger
    {
    public:
        bool Active() const { return !_entries.empty(); }
        std::vector<LedgerEntry> const& Entries() const { return _entries; }

        // Take the real gear's bonuses off and put the form's on, at `level`.
        std::vector<ItemOp> Lift(std::vector<RealItem> const& real, std::vector<FormItem> const& form, uint32_t level)
        {
            std::vector<ItemOp> ops;
            for (RealItem const& item : real)
            {
                if (item.broken || !item.usable || !item.entry)
                    continue;
                _entries.push_back({ item.slot, item.entry, item.guid, level, false });
                ops.push_back({ item.slot, item.entry, level, false });
            }
            for (FormItem const& item : form)
            {
                if (!item.entry)
                    continue;
                _entries.push_back({ item.slot, item.entry, 0, level, true });
                ops.push_back({ item.slot, item.entry, level, true });
            }
            return ops;
        }

        // Everything back, in reverse, each at the level it was applied.
        std::vector<ItemOp> Undo()
        {
            std::vector<ItemOp> ops;
            for (auto it = _entries.rbegin(); it != _entries.rend(); ++it)
                ops.push_back({ it->slot, it->entry, it->level, !it->form });
            _entries.clear();
            return ops;
        }

        // Any level change: undo at the old levels, lift again at the new one.
        std::vector<ItemOp> Relevel(std::vector<RealItem> const& real, std::vector<FormItem> const& form, uint32_t level)
        {
            std::vector<ItemOp> ops = Undo();
            std::vector<ItemOp> lift = Lift(real, form, level);
            ops.insert(ops.end(), lift.begin(), lift.end());
            return ops;
        }

    private:
        std::vector<LedgerEntry> _entries;
    };

    // The form's weapons by attack type (main, off, ranged, as WeaponAttackType), 0 for an empty hand:
    // what Player::SetWeaponOverride gets, so a dual-wield form swings both hands and a two-hander
    // never an off hand, whatever the character wears (the user's Q2, architect's ruling).
    inline std::array<uint32_t, 3> FormWeapons(std::vector<FormItem> const& form)
    {
        std::array<uint32_t, 3> out{ 0, 0, 0 };
        for (FormItem const& item : form)
        {
            if (!item.weapon)
                continue;
            if (item.slot == SlotMainHand)
                out[0] = item.entry;
            else if (item.slot == SlotOffHand)
                out[1] = item.entry;
            else if (item.slot == SlotRanged)
                out[2] = item.entry;
        }
        return out;
    }

    // What the form holds in its hands for all to see (main, off, ranged; 0 for an empty hand): a
    // form with gear shows its gear set's hand items, shields and held items too; any other form
    // shows its creature's own equipment (user, 2026-09-24: the form's weapon, not the character's).
    inline std::array<uint32_t, 3> FormHands(std::vector<FormItem> const& form, std::array<uint32_t, 3> const& creature)
    {
        if (form.empty())
            return creature;
        std::array<uint32_t, 3> out{ 0, 0, 0 };
        for (FormItem const& item : form)
        {
            if (item.slot == SlotMainHand)
                out[0] = item.entry;
            else if (item.slot == SlotOffHand)
                out[1] = item.entry;
            else if (item.slot == SlotRanged)
                out[2] = item.entry;
        }
        return out;
    }
}

#endif
