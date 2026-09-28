/*
 * mod-shapeshifter, the pure half: parsing the `.shapeshift` command line, the stat maths and the
 * reply format. No AzerothCore includes, so tools/test_shapeshift_cpp.py can build and test it
 * without the worldserver.
 *
 * The command line is built by addons/Shapeshifter/Core/Protocol.lua (Protocol.BuildApply):
 *   apply <entry> <b|u> <size 10-200> <tank|bruiser|caster|glass> <kit csv> <passives csv|-> <flags|->
 *   kit and passive tokens: a spell id, or f<k> for class-grade family k (14,000,000 + 20k)
 *   flags: comma-separated fly=0|1, vis=<SpellVisualKit>, st=<sound>, sd=<sound>, as=<entry> (name,
 *   level and stats from that creature, the model from <entry>), and for class-grade
 *   forms res=0|1|3 (mana, rage, energy), gs=<gear set 1-499>, mp=<mana % 1-1000>, mr=<regen per mille 0-200>;
 *   ht=<model height at size 100%, tenths of a yard, 1-20000> (the form's speed; caps word "speed")
 *   prime <entry csv>: answer creature queries the client never sent (Protocol.BuildPrime)
 *   size <10-200>: resize the current form in place (Protocol.BuildSize)
 *   puppet <entry> <10-200> | puppet off: the menu preview's private puppet (Protocol.BuildPuppet)
 * Replies go back as a hidden addon whisper (prefix SHSH) parsed by Protocol.ParseReply.
 */

#ifndef SHAPESHIFT_ARGS_H
#define SHAPESHIFT_ARGS_H

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace Shapeshift
{
    enum class Mode { Balanced, Unleashed };
    enum class Profile { Tank, Bruiser, Caster, GlassCannon };

    constexpr std::size_t MaxKit = 12;
    constexpr std::size_t MaxPassives = 8;
    constexpr uint32_t MinSizePct = 10;
    constexpr uint32_t MinPuppetPct = 1;
    constexpr uint32_t MaxSizePct = 200;                 // twice true size (user, 2026-09-24; caps size200)
    constexpr std::size_t MaxPrime = 40;

    // Class-grade ids (docs/superpowers/plans/2026-09-23-shapeshift-c1-c2-class-grade.md). Family k
    // owns 20 spell ids: bands 0-15 (5 levels each), Unleashed 16, 17-19 reserved. Family 0 and gear
    // set 0 belong to the spike; 14,000,019 is the shared hidden mana regen passive.
    constexpr uint32_t FamilyFirst = 14000000;
    constexpr uint32_t FamilyLast = 14199999;
    constexpr uint32_t FamilySize = 20;
    constexpr uint32_t MaxFamily = 9999;
    constexpr uint32_t Bands = 16;
    constexpr uint32_t UnleashedOffset = 16;
    constexpr uint32_t ManaRegenPassive = 14000019;
    constexpr uint32_t GearItemFirst = 9300000;
    constexpr uint32_t GearSsdFirst = 20000;
    constexpr uint32_t GearSlots = 20;
    constexpr uint32_t MaxGearSet = 999;
    constexpr uint32_t MaxManaPct = 1000;                // Q8: pools sized like a geared caster
    constexpr uint32_t MaxManaRegenPermille = 200;
    constexpr uint32_t DefaultManaRegenPermille = 20;
    constexpr uint32_t MaxHeightTenths = 20000;

    // A form's run speed (user's choice a, 2026-09-24): the faster of the creature's own run speed
    // and a size rule, 100% at a human's height rising to 200% at 20 yards, never above 250% and
    // never below the player's own. Flying forms fly like an epic flying mount (+280%).
    constexpr float HumanHeight = 2.5f;
    constexpr float FullStrideHeight = 20.0f;
    constexpr float MaxSizeRate = 2.0f;
    constexpr float MaxRunRate = 2.5f;
    constexpr float FlightRate = 3.8f;

    inline float FormRunRate(float creatureRun, float heightYards)
    {
        float bySize = 1.0f + (heightYards - HumanHeight) / (FullStrideHeight - HumanHeight);
        bySize = std::clamp(bySize, 1.0f, MaxSizeRate);
        return std::clamp(std::max(creatureRun, bySize), 1.0f, MaxRunRate);
    }

    enum class Resource { Default, Mana, Rage, Energy };

    inline bool IsClassGrade(uint32_t id) { return id >= FamilyFirst && id <= FamilyLast; }
    inline uint32_t FamilyBase(uint32_t k) { return FamilyFirst + FamilySize * k; }
    // A guardian summoned by a form's own spell (deep pass B3): it ends with the form.
    inline bool IsFormSummon(uint32_t createdBySpell) { return IsClassGrade(createdBySpell); }
    inline uint32_t BandOf(uint32_t level) { return std::min<uint32_t>((level > 0 ? level - 1 : 0) / 5, Bands - 1); }
    inline uint32_t BandId(uint32_t base, uint32_t level, bool balanced)
    {
        return balanced ? base + BandOf(level) : base + UnleashedOffset;
    }
    inline uint32_t GearItemId(uint32_t set, uint32_t slot) { return GearItemFirst + GearSlots * set + slot; }
    inline uint32_t GearSsdId(uint32_t set, uint32_t slot) { return GearSsdFirst + GearSlots * set + slot; }

    // A mana form's pool: a mage's base mana at the level times the form's percentage (mp flag).
    inline uint32_t ManaTarget(uint32_t mageBaseMana, uint32_t manaPct)
    {
        return uint32_t((uint64_t(mageBaseMana) * manaPct + 50) / 100);
    }

    // The hidden regen passive's amount per 5 s: per mille of the pool (mr flag).
    inline int32_t ManaRegenAmount(uint32_t target, uint32_t permille)
    {
        return int32_t((uint64_t(target) * permille + 500) / 1000);
    }

    // Family bases become the band for the level (Balanced) or the Unleashed row; other ids stay.
    inline std::vector<uint32_t> MapKitIds(std::vector<uint32_t> const& ids, uint32_t level, bool balanced)
    {
        std::vector<uint32_t> out;
        out.reserve(ids.size());
        for (uint32_t id : ids)
            out.push_back(IsClassGrade(id) ? BandId(id, level, balanced) : id);
        return out;
    }

    struct ApplyArgs
    {
        uint32_t entry = 0;
        Mode mode = Mode::Balanced;
        uint32_t sizePct = 100;
        Profile profile = Profile::Bruiser;
        std::vector<uint32_t> kit;
        std::vector<uint32_t> passives;
        bool fly = false;
        uint32_t visualKit = 0;
        uint32_t soundTransform = 0;
        uint32_t soundDeath = 0;
        Resource resource = Resource::Default;
        uint32_t gearSet = 0;                               // 0: no form gear
        uint32_t manaPct = 0;                               // 0: no mana target
        uint32_t manaRegenPermille = DefaultManaRegenPermille;
        uint32_t identity = 0;                              // as=: name, level, stats; 0: the model's own
        uint32_t heightTenths = 0;                          // ht=: the model's height (speed); 0: unknown
    };

    struct LookArgs
    {
        uint32_t entry = 0;
        uint32_t sizePct = 100;
    };

    namespace Detail
    {
        inline std::vector<std::string_view> Split(std::string_view text, char sep)
        {
            std::vector<std::string_view> out;
            std::size_t start = 0;
            while (true)
            {
                std::size_t end = text.find(sep, start);
                if (end == std::string_view::npos)
                {
                    out.push_back(text.substr(start));
                    return out;
                }
                out.push_back(text.substr(start, end - start));
                start = end + 1;
            }
        }

        inline std::vector<std::string_view> Words(std::string_view text)
        {
            std::vector<std::string_view> out;
            std::size_t i = 0;
            while (i < text.size())
            {
                while (i < text.size() && text[i] == ' ')
                    ++i;
                std::size_t start = i;
                while (i < text.size() && text[i] != ' ')
                    ++i;
                if (i > start)
                    out.push_back(text.substr(start, i - start));
            }
            return out;
        }

        inline std::optional<uint32_t> Number(std::string_view text)
        {
            if (text.empty() || text.size() > 9)
                return std::nullopt;
            uint32_t value = 0;
            for (char c : text)
            {
                if (c < '0' || c > '9')
                    return std::nullopt;
                value = value * 10 + uint32_t(c - '0');
            }
            return value;
        }

        // "-" is an empty list; anything else is comma-separated positive numbers.
        inline bool NumberList(std::string_view text, std::vector<uint32_t>& out)
        {
            out.clear();
            if (text == "-")
                return true;
            for (std::string_view part : Split(text, ','))
            {
                std::optional<uint32_t> value = Number(part);
                if (!value || *value == 0)
                    return false;
                out.push_back(*value);
            }
            return true;
        }

        // Kit and passive tokens: "-", or comma-separated spell ids and f<k> class-grade families.
        // A raw id inside the class-grade range is refused: those travel as f<k> only.
        inline bool KitList(std::string_view text, std::vector<uint32_t>& out)
        {
            out.clear();
            if (text == "-")
                return true;
            for (std::string_view part : Split(text, ','))
            {
                bool family = !part.empty() && part[0] == 'f';
                std::optional<uint32_t> value = Number(family ? part.substr(1) : part);
                if (!value || *value == 0)
                    return false;
                if (family)
                {
                    if (*value > MaxFamily)
                        return false;
                    out.push_back(FamilyBase(*value));
                }
                else
                {
                    if (IsClassGrade(*value))
                        return false;
                    out.push_back(*value);
                }
            }
            return true;
        }

        inline std::optional<uint32_t> Size(std::string_view text)
        {
            std::optional<uint32_t> size = Number(text);
            if (!size || *size < MinSizePct || *size > MaxSizePct)
                return std::nullopt;
            return size;
        }
    }

    inline std::optional<ApplyArgs> ParseApply(std::string_view text, std::string& error)
    {
        using namespace Detail;
        std::vector<std::string_view> words = Words(text);
        if (words.size() != 7)
        {
            error = "expected: <entry> <b|u> <size> <profile> <kit> <passives> <flags>";
            return std::nullopt;
        }

        ApplyArgs args;
        std::optional<uint32_t> entry = Number(words[0]);
        if (!entry || *entry == 0)
        {
            error = "bad creature entry";
            return std::nullopt;
        }
        args.entry = *entry;

        if (words[1] == "b")
            args.mode = Mode::Balanced;
        else if (words[1] == "u")
            args.mode = Mode::Unleashed;
        else
        {
            error = "mode must be b or u";
            return std::nullopt;
        }

        std::optional<uint32_t> size = Size(words[2]);
        if (!size)
        {
            error = "size must be 10 to 100";
            return std::nullopt;
        }
        args.sizePct = *size;

        if (words[3] == "tank")
            args.profile = Profile::Tank;
        else if (words[3] == "bruiser")
            args.profile = Profile::Bruiser;
        else if (words[3] == "caster")
            args.profile = Profile::Caster;
        else if (words[3] == "glass")
            args.profile = Profile::GlassCannon;
        else
        {
            error = "profile must be tank, bruiser, caster or glass";
            return std::nullopt;
        }

        if (!KitList(words[4], args.kit) || args.kit.empty())
        {
            error = "kit must be one or more spell ids or f<family>";
            return std::nullopt;
        }
        if (args.kit.size() > MaxKit)
        {
            error = "at most 12 kit spells";
            return std::nullopt;
        }
        if (!KitList(words[5], args.passives))
        {
            error = "passives must be spell ids, f<family> or -";
            return std::nullopt;
        }
        if (args.passives.size() > MaxPassives)
        {
            error = "at most 8 passives";
            return std::nullopt;
        }

        if (words[6] != "-")
        {
            for (std::string_view flag : Split(words[6], ','))
            {
                std::vector<std::string_view> pair = Split(flag, '=');
                std::optional<uint32_t> value = pair.size() == 2 ? Number(pair[1]) : std::nullopt;
                if (!value)
                {
                    error = "bad flag";
                    return std::nullopt;
                }
                if (pair[0] == "fly")
                    args.fly = *value != 0;
                else if (pair[0] == "vis")
                    args.visualKit = *value;
                else if (pair[0] == "st")
                    args.soundTransform = *value;
                else if (pair[0] == "sd")
                    args.soundDeath = *value;
                else if (pair[0] == "as" && *value >= 1)
                    args.identity = *value;
                else if (pair[0] == "res" && (*value == 0 || *value == 1 || *value == 3))
                    args.resource = *value == 0 ? Resource::Mana : (*value == 1 ? Resource::Rage : Resource::Energy);
                else if (pair[0] == "gs" && *value >= 1 && *value <= MaxGearSet)
                    args.gearSet = *value;
                else if (pair[0] == "mp" && *value >= 1 && *value <= MaxManaPct)
                    args.manaPct = *value;
                else if (pair[0] == "mr" && *value <= MaxManaRegenPermille)
                    args.manaRegenPermille = *value;
                else if (pair[0] == "ht" && *value >= 1 && *value <= MaxHeightTenths)
                    args.heightTenths = *value;
                else
                {
                    error = "unknown flag or value out of range";
                    return std::nullopt;
                }
            }
        }
        return args;
    }

    inline std::optional<LookArgs> ParseLook(std::string_view text, std::string& error)
    {
        using namespace Detail;
        std::vector<std::string_view> words = Words(text);
        std::optional<uint32_t> entry = words.size() == 2 ? Number(words[0]) : std::nullopt;
        std::optional<uint32_t> size = words.size() == 2 ? Size(words[1]) : std::nullopt;
        if (!entry || *entry == 0 || !size)
        {
            error = "expected: <entry> <size 10-200>";
            return std::nullopt;
        }
        return LookArgs{ *entry, *size };
    }

    // prime <entry,entry,...>: the creatures whose query answers the client should cache.
    inline std::optional<std::vector<uint32_t>> ParsePrime(std::string_view text, std::string& error)
    {
        using namespace Detail;
        std::vector<std::string_view> words = Words(text);
        std::vector<uint32_t> entries;
        if (words.size() != 1 || words[0] == "-" || !NumberList(words[0], entries)
            || entries.empty() || entries.size() > MaxPrime)
        {
            error = "expected: <entry,entry,...> (1 to 40 creature entries)";
            return std::nullopt;
        }
        return entries;
    }

    // size <10-200>: resize the current form in place (the menu's slider, while dragging).
    inline std::optional<uint32_t> ParseSize(std::string_view text, std::string& error)
    {
        using namespace Detail;
        std::vector<std::string_view> words = Words(text);
        std::optional<uint32_t> size = words.size() == 1 ? Size(words[0]) : std::nullopt;
        if (!size)
            error = "expected: <size 10-200>";
        return size;
    }

    struct PuppetArgs
    {
        bool off = false;
        uint32_t entry = 0;
        uint32_t sizePct = 100;
    };

    // `puppet <entry> <size>` or `puppet off`.
    inline std::optional<PuppetArgs> ParsePuppet(std::string_view text, std::string& error)
    {
        using namespace Detail;
        std::vector<std::string_view> words = Words(text);
        PuppetArgs args;
        if (words.size() == 1 && words[0] == "off")
        {
            args.off = true;
            return args;
        }
        // The puppet goes down to 1%: the preview scales each one to about Hogger's size, and a
        // 90-yard dragon needs 3% (user, 2026-09-24; caps word puppetsize).
        std::optional<uint32_t> entry = words.size() == 2 ? Number(words[0]) : std::nullopt;
        std::optional<uint32_t> size = words.size() == 2 ? Number(words[1]) : std::nullopt;
        if (size && (*size < MinPuppetPct || *size > MaxSizePct))
            size.reset();
        if (!entry || !*entry || !size)
        {
            error = "expected: <entry> <size 1-200>, or off";
            return std::nullopt;
        }
        args.entry = *entry;
        args.sizePct = *size;
        return args;
    }

    // The preview puppet stands this far under the lower of the player and the ground below them
    // (user, 2026-09-24: 91 yards), so no model (the tallest standing is about 70 yards, Kologarn)
    // reaches the surface. The server's visibility range is 2D, so depth does not hide it.
    constexpr float PuppetDepth = 91.0f;

    inline float PuppetZ(float playerZ, float groundZ)
    {
        // The core answers "no ground here" with INVALID_HEIGHT (-100000) or the vmap's -200000.
        bool noGround = groundZ <= -50000.0f;
        return (noGround ? playerZ : std::min(playerZ, groundZ)) - PuppetDepth;
    }

    // Balanced mode multiplies the player's own health and armour by this.
    inline float ProfileMultiplier(Profile profile)
    {
        switch (profile)
        {
            case Profile::Tank: return 1.6f;
            case Profile::Bruiser: return 1.25f;
            case Profile::Caster: return 0.9f;
            case Profile::GlassCannon: return 0.75f;
        }
        return 1.0f;
    }

    // Balanced mode: a higher-level creature's spells land like the player's own level would.
    inline float BalancedSpellScale(uint32_t playerLevel, uint32_t creatureLevel)
    {
        if (creatureLevel == 0 || playerLevel >= creatureLevel)
            return 1.0f;
        return std::pow(float(playerLevel) / float(creatureLevel), 1.5f);
    }

    // Unleashed mode: the creature's average swing over the player's, clamped to a sane range.
    // A creature's weapon damage runs from base to 1.5 x base (Creature.cpp), times its damage
    // modifier and swing time.
    inline float UnleashedMeleeMultiplier(float baseDamage, float damageModifier, uint32_t attackTimeMs,
                                          float playerMin, float playerMax)
    {
        float creatureAverage = baseDamage * 1.25f * damageModifier * (float(attackTimeMs) / 1000.0f);
        float playerAverage = (playerMin + playerMax) / 2.0f;
        if (playerAverage <= 0.0f || creatureAverage <= 0.0f)
            return 1.0f;
        return std::clamp(creatureAverage / playerAverage, 0.05f, 1000.0f);
    }

    // Unleashed mode: the level the player takes on, the creature's own. 83 is the highest WotLK
    // creature level (a raid boss); the core's per-level tables stop at 100.
    constexpr uint32_t MaxFormLevel = 83;
    inline uint32_t UnleashedLevel(uint32_t creatureLevel)
    {
        return std::clamp<uint32_t>(creatureLevel, 1, MaxFormLevel);
    }

    // The flat amount that takes `current` to `target`, never aiming below 1.
    inline float FlatDelta(float current, float target)
    {
        return std::max(target, 1.0f) - current;
    }

    inline uint32_t ScaleAmount(uint32_t amount, float scale)
    {
        return uint32_t(std::lround(double(amount) * double(scale)));
    }

    inline std::string JoinIds(std::vector<uint32_t> const& ids)
    {
        if (ids.empty())
            return "-";
        std::string out;
        for (std::size_t i = 0; i < ids.size(); ++i)
        {
            if (i)
                out += ',';
            out += std::to_string(ids[i]);
        }
        return out;
    }

    inline std::string FormatOn(uint32_t entry, bool unleashed, uint32_t sizePct,
                                std::vector<uint32_t> const& kit, bool lookOnly, std::string const& name)
    {
        return "ON;" + std::to_string(entry) + ";" + (unleashed ? "u" : "b") + ";" + std::to_string(sizePct)
            + ";" + JoinIds(kit) + ";" + (lookOnly ? "1" : "0") + ";" + name;
    }

    inline std::string FormatOff(std::string_view reason)
    {
        return "OFF;" + std::string(reason);
    }

    // Sent after the state on `.shapeshifter status`: what this server understands beyond the
    // first protocol, so a newer addon never sends a command an older module would reject.
    // nocg: this server has no class-grade spell rows, so the addon sends the creatures' own spells.
    inline std::string FormatCaps(bool classGrade = true)
    {
        std::string caps = "CAPS;prime,size,as,speed,puppet,size200,puppetsize,stance,voice";
        return classGrade ? caps : caps + ",nocg";
    }

    // The puppet the preview may draw: the creature it wears and the unit it is handed over as
    // ("pet" or "boss"), or PUPPET;off when there is none.
    inline std::string FormatPuppet(uint32_t entry, std::string_view unit)
    {
        return entry ? "PUPPET;on;" + std::to_string(entry) + ";" + std::string(unit) : std::string("PUPPET;off");
    }

    // ---- Weapon stances (deep pass B2) -------------------------------------------------------
    constexpr uint32_t MaxStances = 3;
    constexpr uint32_t StanceCooldownMs = 1500;

    // `.shapeshifter stance <1-3>`.
    inline std::optional<uint32_t> ParseStance(std::string_view text)
    {
        std::vector<std::string_view> words = Detail::Words(text);
        std::optional<uint32_t> n = words.size() == 1 ? Detail::Number(words[0]) : std::nullopt;
        if (!n || *n < 1 || *n > MaxStances)
            return std::nullopt;
        return n;
    }

    // ---- The soundboard (user, 2026-09-27) --------------------------------------------------
    constexpr uint32_t VoiceGapMs = 1000;                   // the addon waits for the line itself

    // `.shapeshifter voice <sound id>`: one of the form's creature's own spoken lines.
    inline std::optional<uint32_t> ParseVoice(std::string_view text)
    {
        std::vector<std::string_view> words = Detail::Words(text);
        std::optional<uint32_t> n = words.size() == 1 ? Detail::Number(words[0]) : std::nullopt;
        if (!n || *n == 0)
            return std::nullopt;
        return n;
    }

    // The shapeshifter_stance abilities column: family numbers k, comma separated; "" is none.
    inline std::optional<std::vector<uint32_t>> ParseFamilies(std::string_view csv)
    {
        std::vector<uint32_t> out;
        if (Detail::Words(csv).empty())
            return out;
        for (std::string_view part : Detail::Split(csv, ','))
        {
            std::optional<uint32_t> k = Detail::Number(part);
            if (!k || *k > MaxFamily)
                return std::nullopt;
            out.push_back(*k);
        }
        return out;
    }

    // One shapeshifter_stance row: a stance of the form whose gear set is `gearSet`.
    struct StanceRow
    {
        uint32_t gearSet = 0;
        uint32_t stance = 0;
        std::string name;
        uint32_t weaponSet = 0;                 // stance 1: the form's own gear set
        uint32_t bonus = 0;                     // family k
        std::vector<uint32_t> abilities;        // family k each
    };

    // Sent after ON for a stanced form, and after each swap: the stance and its abilities' ids.
    inline std::string FormatStance(uint32_t stance, std::vector<uint32_t> const& ids)
    {
        return "STANCE;" + std::to_string(stance) + ";" + JoinIds(ids);
    }

    inline std::string FormatError(std::string_view code, std::string_view text)
    {
        std::string clean(text);
        std::replace(clean.begin(), clean.end(), ';', ',');
        return "ERR;" + std::string(code) + ";" + clean;
    }
}

#endif
