// Tests for ShapeshiftArgs.h. Built and run by tools/test_shapeshift_cpp.py with MSVC.
#include "../module/mod-shapeshifter/src/ShapeshiftArgs.h"
#include "../module/mod-shapeshifter/src/ShapeshiftLedger.h"

#include <cmath>
#include <cstdio>
#include <array>
#include <functional>
#include <map>

using namespace Shapeshift;

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL line %d: %s\n", __LINE__, #cond); ++failures; } } while (0)

static void ParsesAFullApplyLine()
{
    std::string error;
    auto args = ParseApply("11502 u 60 caster 20566,20565 21388 fly=1,vis=286,st=8046,sd=7555", error);
    CHECK(args.has_value());
    if (!args)
        return;
    CHECK(args->entry == 11502);
    CHECK(args->mode == Mode::Unleashed);
    CHECK(args->sizePct == 60);
    CHECK(args->profile == Profile::Caster);
    CHECK((args->kit == std::vector<uint32_t>{ 20566, 20565 }));
    CHECK((args->passives == std::vector<uint32_t>{ 21388 }));
    CHECK(args->fly);
    CHECK(args->visualKit == 286);
    CHECK(args->soundTransform == 8046);
    CHECK(args->soundDeath == 7555);
}

static void DashMeansNoneAndSpacesAreTolerated()
{
    std::string error;
    auto args = ParseApply("  4275  b 100 glass 9053 - -  ", error);
    CHECK(args.has_value());
    if (!args)
        return;
    CHECK(args->mode == Mode::Balanced);
    CHECK(args->profile == Profile::GlassCannon);
    CHECK(args->passives.empty());
    CHECK(!args->fly);
    CHECK(args->visualKit == 0);
}

static void RejectsBadApplyLines()
{
    char const* bad[] = {
        "",
        "11502 x 100 caster 1 - -",
        "11502 b 5 caster 1 - -",
        "11502 b 201 caster 1 - -",
        "11502 b 100 wizard 1 - -",
        "11502 b 100 caster - - -",
        "11502 b 100 caster 1,2,3,4,5,6,7,8,9,10,11,12,13 - -",
        "11502 b 100 caster 1,,2 - -",
        "11502 b 100 caster 1 1,2,3,4,5,6,7,8,9 -",
        "11502 b 100 caster 1 - wings=1",
        "11502 b 100 caster 1 - fly",
        "0 b 100 caster 1 - -",
        "11502 b 100 caster 1 - - extra",
        "11502 b 100 caster 1x - -",
    };
    for (char const* line : bad)
    {
        std::string error;
        bool rejected = !ParseApply(line, error).has_value();
        if (!rejected || error.empty())
        {
            std::printf("FAIL: accepted or no error for '%s'\n", line);
            ++failures;
        }
    }
}

static void ParsesLook()
{
    std::string error;
    auto look = ParseLook("11502 50", error);
    CHECK(look && look->entry == 11502 && look->sizePct == 50);
    CHECK(!ParseLook("11502", error));
    CHECK(!ParseLook("11502 5", error));
    CHECK(!ParseLook("abc 50", error));
}

static void ParsesPrime()
{
    std::string error;
    auto one = ParsePrime("11502", error);
    CHECK(one && (*one == std::vector<uint32_t>{ 11502 }));
    auto many = ParsePrime(" 11502,15727,36597 ", error);
    CHECK(many && (*many == std::vector<uint32_t>{ 11502, 15727, 36597 }));
    std::string forty = "1";
    for (int i = 2; i <= 40; ++i)
        forty += "," + std::to_string(i);
    CHECK(ParsePrime(forty, error).has_value());
    CHECK(!ParsePrime(forty + ",41", error));
    CHECK(!ParsePrime("", error));
    CHECK(!ParsePrime("-", error));
    CHECK(!ParsePrime("0", error));
    CHECK(!ParsePrime("11502 15727", error));
    CHECK(!ParsePrime("11502,abc", error));
    CHECK(FormatCaps() == "CAPS;prime,size,as,speed,puppet,size200,puppetsize,stance,voice");
    CHECK(FormatCaps(false) == "CAPS;prime,size,as,speed,puppet,size200,puppetsize,stance,voice,nocg");
}

static void ParsesSize()
{
    std::string error;
    CHECK(ParseSize("35", error) == std::optional<uint32_t>(35));
    CHECK(ParseSize(" 100 ", error) == std::optional<uint32_t>(100));
    CHECK(ParseSize("10", error) == std::optional<uint32_t>(10));
    CHECK(!ParseSize("5", error));
    CHECK(!ParseSize("201", error));
    CHECK(ParseSize("200", error) == std::optional<uint32_t>(200));   // up to twice true size (user, 2026-09-24)
    CHECK(!ParseSize("", error));
    CHECK(!ParseSize("50 60", error));
    CHECK(!ParseSize("big", error));
}

static void Maths()
{
    CHECK(ProfileMultiplier(Profile::Tank) == 1.6f);
    CHECK(ProfileMultiplier(Profile::Bruiser) == 1.25f);
    CHECK(ProfileMultiplier(Profile::Caster) == 0.9f);
    CHECK(ProfileMultiplier(Profile::GlassCannon) == 0.75f);

    CHECK(std::fabs(BalancedSpellScale(20, 63) - 0.1789f) < 0.001f);
    CHECK(BalancedSpellScale(63, 63) == 1.0f);
    CHECK(BalancedSpellScale(80, 63) == 1.0f);
    CHECK(BalancedSpellScale(1, 0) == 1.0f);

    // creature average 100 * 1.25 * 2 * 2.0 s = 500 against a player average of 100
    CHECK(std::fabs(UnleashedMeleeMultiplier(100.0f, 2.0f, 2000, 50.0f, 150.0f) - 5.0f) < 0.001f);
    CHECK(UnleashedMeleeMultiplier(100.0f, 2.0f, 2000, 0.0f, 0.0f) == 1.0f);
    CHECK(UnleashedMeleeMultiplier(1.0f, 0.01f, 1000, 1000.0f, 1000.0f) == 0.05f);

    // Unleashed puts the player at the creature's level, 1 to 83
    CHECK(UnleashedLevel(75) == 75);
    CHECK(UnleashedLevel(83) == 83);
    CHECK(UnleashedLevel(255) == 83);
    CHECK(UnleashedLevel(0) == 1);

    CHECK(FlatDelta(1000.0f, 1600.0f) == 600.0f);
    CHECK(FlatDelta(1000.0f, 0.0f) == -999.0f);

    CHECK(ScaleAmount(1000, 0.1789f) == 179);
    CHECK(ScaleAmount(7, 1.0f) == 7);
}

static void Replies()
{
    CHECK(FormatOn(11502, true, 60, { 20566, 20565 }, false, "Ragnaros") == "ON;11502;u;60;20566,20565;0;Ragnaros");
    CHECK(FormatOn(448, false, 100, {}, true, "Hogger") == "ON;448;b;100;-;1;Hogger");
    CHECK(FormatOff("death") == "OFF;death");
    CHECK(FormatError("combat", "a;b") == "ERR;combat;a,b");
}

static void ClassGradeIds()
{
    CHECK(FamilyBase(1) == 14000020);
    CHECK(FamilyBase(9999) == 14199980);
    CHECK(IsClassGrade(14000000) && IsClassGrade(14199999) && !IsClassGrade(13999999) && !IsClassGrade(14200000));
    CHECK(BandOf(0) == 0 && BandOf(1) == 0 && BandOf(5) == 0 && BandOf(6) == 1);
    CHECK(BandOf(75) == 14 && BandOf(76) == 15 && BandOf(80) == 15 && BandOf(99) == 15);
    CHECK(BandId(14000020, 80, true) == 14000035);
    CHECK(BandId(14000020, 1, true) == 14000020);
    CHECK(BandId(14000020, 40, false) == 14000036);
    CHECK(GearItemId(1, 15) == 9300035);
    CHECK(GearSsdId(1, 15) == 20035);
    CHECK((MapKitIds({ 14000020, 20565, 14000040 }, 80, true) == std::vector<uint32_t>{ 14000035, 20565, 14000055 }));
    CHECK((MapKitIds({ 14000020 }, 80, false) == std::vector<uint32_t>{ 14000036 }));
    CHECK(ManaTarget(3268, 600) == 19608);
    CHECK(ManaTarget(0, 150) == 0);
    CHECK(ManaRegenAmount(4248, 20) == 85);
    CHECK(ManaRegenAmount(4248, 0) == 0);
}

static void ParsesClassGradeTokensAndFlags()
{
    std::string error;
    auto args = ParseApply("11502 b 100 caster f1,20565,f9999 f3 res=1,gs=3,mp=600,mr=25", error);
    CHECK(args.has_value());
    if (!args)
        return;
    CHECK((args->kit == std::vector<uint32_t>{ 14000020, 20565, 14199980 }));
    CHECK((args->passives == std::vector<uint32_t>{ 14000060 }));
    CHECK(args->resource == Resource::Rage);
    CHECK(args->gearSet == 3);
    CHECK(args->manaPct == 600);
    CHECK(args->manaRegenPermille == 25);

    auto plain = ParseApply("11502 b 100 caster 20565 - -", error);
    CHECK(plain.has_value());
    if (plain)
    {
        CHECK(plain->resource == Resource::Default);
        CHECK(plain->gearSet == 0);
        CHECK(plain->manaPct == 0);
        CHECK(plain->manaRegenPermille == DefaultManaRegenPermille);
    }
    auto mana = ParseApply("11502 b 100 caster f1 - res=0", error);
    CHECK(mana.has_value() && mana->resource == Resource::Mana);
    auto energy = ParseApply("11502 b 100 caster f1 - res=3", error);
    CHECK(energy.has_value() && energy->resource == Resource::Energy);
}

// A second shape whose model lives on a stand-in creature ("... Transform Visual") takes its name,
// level and stats from the real one: as=<entry> (visages, 2026-09-24).
static void ParsesTheIdentityFlag()
{
    std::string error;
    auto args = ParseApply("14966 b 100 bruiser 20565 - fly=0,as=14509", error);
    CHECK(args.has_value() && args->entry == 14966 && args->identity == 14509);
    auto plain = ParseApply("14966 b 100 bruiser 20565 - -", error);
    CHECK(plain.has_value() && plain->identity == 0);
    CHECK(!ParseApply("14966 b 100 bruiser 20565 - as=0", error).has_value());
}

static void RejectsBadClassGradeInput()
{
    char const* bad[] = {
        "11502 b 100 caster 14000020 - -",       // class-grade ids travel as f<k>
        "11502 b 100 caster f0 - -",
        "11502 b 100 caster f10000 - -",
        "11502 b 100 caster f - -",
        "11502 b 100 caster fx1 - -",
        "11502 b 100 caster 1 - res=2",
        "11502 b 100 caster 1 - gs=0",
        "11502 b 100 caster 1 - gs=1000",
        "11502 b 100 caster 1 - mp=0",
        "11502 b 100 caster 1 - mp=1001",
        "11502 b 100 caster 1 - mr=201",
    };
    for (char const* line : bad)
    {
        std::string error;
        bool rejected = !ParseApply(line, error).has_value();
        CHECK(rejected);
        if (!rejected)
            std::printf("  accepted: %s\n", line);
    }
}

// ---- The gear ledger against a fake core ----------------------------------------------------
// One number stands for all of a player's stats. An item's bonus depends on its entry and, for an
// heirloom (odd entry), on the level it is applied at, as _ApplyItemBonuses does with GetLevel().
static long long Bonus(uint32_t entry, uint32_t level)
{
    return (entry % 2) ? (long long)entry * level : (long long)entry * 100;
}

struct FakeItem
{
    uint32_t entry = 0;
    bool broken = false;
};

struct FakeCore
{
    long long stats = 1000;                 // base stats with no items
    uint32_t level = 10;
    std::map<uint8_t, FakeItem> slots;
    std::function<void(FakeCore&)> onLevelChanged;

    void Bonuses(uint32_t entry, uint32_t atLevel, bool apply) { stats += (apply ? 1 : -1) * Bonus(entry, atLevel); }
    void Run(std::vector<ItemOp> const& ops)
    {
        for (ItemOp const& op : ops)
            Bonuses(op.entry, op.level, op.apply);
    }
    void Equip(uint8_t slot, uint32_t entry)
    {
        slots[slot] = { entry, false };
        Bonuses(entry, level, true);
    }
    std::vector<RealItem> Snapshot() const
    {
        std::vector<RealItem> out;
        for (auto const& [slot, item] : slots)
            out.push_back({ slot, item.entry, uint64_t(slot) + 1, item.broken, true });
        return out;
    }
    // Player::GiveLevel and .reset level: every unbroken item off at the old level, the new level,
    // every unbroken item on at the new level, then OnPlayerLevelChanged.
    void SetLevelLikeTheCore(uint32_t newLevel)
    {
        for (auto const& [slot, item] : slots)
            if (!item.broken)
                Bonuses(item.entry, level, false);
        level = newLevel;
        for (auto const& [slot, item] : slots)
            if (!item.broken)
                Bonuses(item.entry, level, true);
        if (onLevelChanged)
            onLevelChanged(*this);
    }
    void Break(uint8_t slot)
    {
        FakeItem& item = slots[slot];
        if (!item.broken)
        {
            Bonuses(item.entry, level, false);
            item.broken = true;
        }
    }
    void Repair(uint8_t slot)
    {
        FakeItem& item = slots[slot];
        if (item.broken)
        {
            item.broken = false;
            Bonuses(item.entry, level, true);
        }
    }
    void Destroy(uint8_t slot)
    {
        if (!slots[slot].broken)
            Bonuses(slots[slot].entry, level, false);
        slots.erase(slot);
    }
};

struct Pair
{
    FakeCore player, twin;                  // the same events; only `player` transforms
    Ledger ledger;
    std::vector<FormItem> form{ { 0, 9300021 }, { 4, 9300024 }, { 15, 9300035 } };

    Pair()
    {
        for (FakeCore* core : { &player, &twin })
        {
            core->Equip(0, 101);              // an heirloom helm
            core->Equip(4, 200);              // a plain chest
            core->Equip(15, 303);             // an heirloom main hand
            core->Equip(16, 400);             // a plain off-hand weapon
        }
        player.onLevelChanged = [this](FakeCore& core) {
            if (ledger.Active())
                core.Run(ledger.Relevel(core.Snapshot(), form, core.level));
        };
    }
    void Transform() { player.Run(ledger.Lift(player.Snapshot(), form, player.level)); }
    void Revert() { player.Run(ledger.Undo()); }
    template <typename F> void Both(F event) { event(player); event(twin); }
    long long FormOnly(uint32_t level) const
    {
        long long total = 1000;
        for (FormItem const& item : form)
            total += Bonus(item.entry, level);
        return total;
    }
};

static void LedgerTransformAndRevert()
{
    Pair p;
    long long before = p.player.stats;
    p.Transform();
    CHECK(p.player.stats == p.FormOnly(10));
    CHECK(p.ledger.Active());
    p.Revert();
    CHECK(p.player.stats == before);
    CHECK(!p.ledger.Active());
}

static void LedgerLevelChanges()
{
    Pair p;
    p.Transform();
    p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(11); });       // .levelup
    CHECK(p.player.stats == p.FormOnly(11));
    p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(40); });       // .character level up
    CHECK(p.player.stats == p.FormOnly(40));
    p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(25); });       // .character level down
    CHECK(p.player.stats == p.FormOnly(25));
    p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(1); });        // .reset level
    CHECK(p.player.stats == p.FormOnly(1));
    p.Revert();
    CHECK(p.player.stats == p.twin.stats);
}

static void LedgerBreakRepairDestroy()
{
    {
        Pair p;
        p.Transform();
        p.Both([](FakeCore& c) { c.Break(4); });
        p.Revert();
        CHECK(p.player.stats == p.twin.stats);
    }
    {
        Pair p;
        p.Transform();
        p.Both([](FakeCore& c) { c.Break(0); });
        p.Both([](FakeCore& c) { c.Repair(0); });
        p.Revert();
        CHECK(p.player.stats == p.twin.stats);
    }
    {
        Pair p;
        p.Transform();
        p.Both([](FakeCore& c) { c.Break(0); });                   // a broken heirloom
        p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(30); });
        CHECK(p.player.stats == p.FormOnly(30));
        p.Both([](FakeCore& c) { c.Repair(0); });                  // repaired mid-form: shows until revert
        p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(31); });
        CHECK(p.player.stats == p.FormOnly(31));
        p.Revert();
        CHECK(p.player.stats == p.twin.stats);
    }
    {
        Pair p;
        p.Transform();
        p.Both([](FakeCore& c) { c.Destroy(4); });
        p.Revert();
        CHECK(p.player.stats == p.twin.stats);
    }
    {
        Pair p;
        p.Both([](FakeCore& c) { c.Break(4); });                   // broken before the transform
        p.Transform();
        CHECK(p.player.stats == p.FormOnly(10));
        p.Both([](FakeCore& c) { c.Repair(4); });
        p.Both([](FakeCore& c) { c.SetLevelLikeTheCore(12); });
        CHECK(p.player.stats == p.FormOnly(12));
        p.Revert();
        CHECK(p.player.stats == p.twin.stats);
    }
}

static void LedgerOpsAndOffhand()
{
    Ledger ledger;
    std::vector<RealItem> real{ { 0, 101, 1, false, true }, { 4, 200, 2, true, true },
                                { 16, 400, 3, false, false } };
    std::vector<ItemOp> lift = ledger.Lift(real, { { 15, 9300035 } }, 20);
    CHECK((lift == std::vector<ItemOp>{ { 0, 101, 20, false }, { 15, 9300035, 20, true } }));   // broken and unusable skipped
    CHECK((ledger.Undo() == std::vector<ItemOp>{ { 15, 9300035, 20, false }, { 0, 101, 20, true } }));
    CHECK(ledger.Undo().empty());
}

static void FormWeaponsByHand()
{
    using W = std::array<uint32_t, 3>;
    CHECK((FormWeapons({ { 15, 1, true }, { 16, 2, true } }) == W{ 1, 2, 0 }));        // one-hand + one-hand
    CHECK((FormWeapons({ { 15, 3, true } }) == W{ 3, 0, 0 }));                         // a two-hander alone
    CHECK((FormWeapons({ { 15, 4, true }, { 16, 5, false } }) == W{ 4, 0, 0 }));       // main hand + shield
    CHECK((FormWeapons({ { 15, 6, true }, { 16, 7, false } }) == W{ 6, 0, 0 }));       // main hand + held item
    CHECK((FormWeapons({ { 15, 8, true }, { 17, 9, true } }) == W{ 8, 0, 9 }));        // a bow
    CHECK((FormWeapons({ { 15, 8, true }, { 17, 10, false } }) == W{ 8, 0, 0 }));      // a relic is no weapon
    CHECK((FormWeapons({ { 0, 11, true }, { 15, 12, true } }) == W{ 12, 0, 0 }));      // weapon flag off a weapon slot
    CHECK((FormWeapons({}) == W{ 0, 0, 0 }));
}

static void Puppets()
{
    std::string error;
    auto on = ParsePuppet("448 60", error);
    CHECK(on && on->entry == 448 && on->sizePct == 60 && !on->off);
    auto off = ParsePuppet(" off ", error);
    CHECK(off && off->off);
    CHECK(!ParsePuppet("", error) && !error.empty());
    CHECK(!ParsePuppet("448", error));
    CHECK(!ParsePuppet("448 0", error));
    CHECK(!ParsePuppet("448 201", error));
    auto tiny = ParsePuppet("31333 3", error);          // a 90-yard dragon at 3% frames like Hogger
    CHECK(tiny && tiny->sizePct == 3);
    CHECK(!ParsePuppet("0 50", error));
    CHECK(!ParsePuppet("x 50", error));
    CHECK(FormatPuppet(448, "pet") == "PUPPET;on;448;pet");
    CHECK(FormatPuppet(448, "boss") == "PUPPET;on;448;boss");
    CHECK(FormatPuppet(0, "pet") == "PUPPET;off");
    // Feet 91 yards under the lower of the player and the ground (user, 2026-09-24): the tallest
    // model standing is about 70 yards (Kologarn), so none reaches the surface.
    CHECK(PuppetZ(50.0f, 48.0f) == 48.0f - PuppetDepth);
    CHECK(PuppetZ(50.0f, 70.0f) == 50.0f - PuppetDepth);       // under a roof: below the player
    CHECK(PuppetZ(50.0f, -200000.0f) == 50.0f - PuppetDepth);  // no ground found
    CHECK(PuppetDepth == 91.0f && PuppetDepth > 70.3f);
}

static void FormSpeeds()
{
    auto near = [](float a, float b) { return std::fabs(a - b) < 0.001f; };
    CHECK(near(FormRunRate(0.99206f, 2.0f), 1.0f));           // human-sized, slow data: never below your own
    CHECK(near(FormRunRate(1.14286f, 2.0f), 1.14286f));       // the creature's own speed when faster
    CHECK(near(FormRunRate(1.0f, 11.25f), 1.5f));             // halfway to 20 yd: 150%
    CHECK(near(FormRunRate(0.99206f, 43.4f), 2.0f));          // Alexstrasza: size rule, capped at 200%
    CHECK(near(FormRunRate(2.57143f, 19.6f), 2.5f));          // Gruul: his own 257%, capped at 250%
    CHECK(near(FormRunRate(1.0f, 0.0f), 1.0f));               // unknown height
    CHECK(FlightRate == 3.8f);                                 // an epic flying mount's +280%

    std::string error;
    auto args = ParseApply("11502 b 100 caster 20566 - ht=434,fly=1", error);
    CHECK(args.has_value() && args->heightTenths == 434 && args->fly);
    CHECK(!ParseApply("11502 b 100 caster 20566 - ht=0", error).has_value());
    CHECK(!ParseApply("11502 b 100 caster 20566 - ht=20001", error).has_value());
}

static void FormHandsShowTheFormsItems()
{
    using W = std::array<uint32_t, 3>;
    W const creature{ 21, 22, 23 };
    CHECK((FormHands({ { 15, 4, true }, { 16, 5, false } }, creature) == W{ 4, 5, 0 }));   // weapon + shield
    CHECK((FormHands({ { 1, 6, false }, { 17, 9, true } }, creature) == W{ 0, 0, 9 }));    // armour is not held
    CHECK((FormHands({ { 1, 6, false } }, creature) == W{ 0, 0, 0 }));                     // gear, bare hands
    CHECK((FormHands({}, creature) == creature));                                           // no gear: the creature's
    CHECK((FormHands({}, W{ 0, 0, 0 }) == W{ 0, 0, 0 }));                                   // an unarmed creature
}

// Deep pass B2: weapon stances.
static void Stances()
{
    CHECK(ParseStance("1") == std::optional<uint32_t>(1));
    CHECK(ParseStance(" 3 ") == std::optional<uint32_t>(3));
    CHECK(!ParseStance("0"));
    CHECK(!ParseStance("4"));
    CHECK(!ParseStance("x"));
    CHECK(!ParseStance(""));
    CHECK(FormatStance(2, { 14000140, 14000160 }) == "STANCE;2;14000140,14000160");
    CHECK(FormatStance(1, {}) == "STANCE;1;-");
    CHECK(ParseFamilies("1240,1241") == std::optional<std::vector<uint32_t>>(std::vector<uint32_t>{ 1240, 1241 }));
    CHECK(ParseFamilies("") == std::optional<std::vector<uint32_t>>(std::vector<uint32_t>{}));
    CHECK(!ParseFamilies("12,x"));
    CHECK(!ParseFamilies("10000"));                  // above MaxFamily
    CHECK(StanceCooldownMs == 1500);
}

static void Voices()
{
    CHECK(ParseVoice("17366") == std::optional<uint32_t>(17366));
    CHECK(ParseVoice(" 8043 ") == std::optional<uint32_t>(8043));
    CHECK(!ParseVoice("0"));
    CHECK(!ParseVoice(""));
    CHECK(!ParseVoice("12 13"));
    CHECK(!ParseVoice("abc"));
}

// Deep pass B3: guardians summoned by a form's spells end with the form.
static void FormSummons()
{
    CHECK(IsFormSummon(14000040));
    CHECK(IsFormSummon(14199999));
    CHECK(!IsFormSummon(261));                       // the template spell itself, cast by anyone
    CHECK(!IsFormSummon(0));
}

int main()
{
    ParsesAFullApplyLine();
    DashMeansNoneAndSpacesAreTolerated();
    RejectsBadApplyLines();
    ParsesLook();
    ParsesPrime();
    ParsesSize();
    Maths();
    Replies();
    ClassGradeIds();
    ParsesClassGradeTokensAndFlags();
    ParsesTheIdentityFlag();
    RejectsBadClassGradeInput();
    LedgerTransformAndRevert();
    LedgerLevelChanges();
    LedgerBreakRepairDestroy();
    LedgerOpsAndOffhand();
    FormWeaponsByHand();
    FormHandsShowTheFormsItems();
    FormSpeeds();
    Puppets();
    Stances();
    Voices();
    FormSummons();
    if (failures)
    {
        std::printf("%d FAILED\n", failures);
        return 1;
    }
    std::printf("ALL PASS\n");
    return 0;
}
