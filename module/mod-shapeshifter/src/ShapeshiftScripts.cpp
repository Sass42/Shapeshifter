/*
 * mod-shapeshifter scripts: the GM command, and the hooks that keep a form honest (refusing the
 * player's own spells and mounts, scaling damage, holding the form's size and model, reverting
 * on death and logout). Class-grade forms add: following level changes, swapping spell bands on
 * leaving combat, refusing gear changes, and re-asserting the form's power type and weapon after
 * shapeshift and disarm auras. Every hook returns at once while nobody is transformed.
 */

#include "Shapeshift.h"

#include "Chat.h"
#include "ChatCommand.h"
#include "Creature.h"
#include "Log.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "Spell.h"
#include "SpellAuraDefines.h"
#include "SpellAuras.h"
#include "SpellInfo.h"

#include <limits>

using namespace Acore::ChatCommands;
using Shapeshift::Engine;

namespace
{
    Player* PlayerOf(Unit* unit)
    {
        return unit ? unit->ToPlayer() : nullptr;
    }

    bool Fail(ChatHandler* handler, Player* player, std::string const& code, std::string const& text)
    {
        Engine::Instance().SendError(player, code, text);
        handler->SendSysMessage(text);
        return true;   // handled: our own message, not the command's syntax help
    }

    bool ChangesScale(SpellInfo const* info)
    {
        return info && (info->HasAura(SPELL_AURA_MOD_SCALE) || info->HasAura(SPELL_AURA_MOD_SCALE_2));
    }

    // Auras whose handlers reset the power type, swing speeds or off-hand state (InitDataForForm, disarm).
    bool ResetsForm(SpellInfo const* info)
    {
        return info && (info->HasAura(SPELL_AURA_MOD_SHAPESHIFT) || info->HasAura(SPELL_AURA_MOD_DISARM)
            || info->HasAura(SPELL_AURA_MOD_DISARM_OFFHAND) || info->HasAura(SPELL_AURA_MOD_DISARM_RANGED));
    }

    bool GearLocked(Player* player)
    {
        if (!player || !Engine::Instance().AnyActive() || !Engine::Instance().GearFixed(player->GetGUID()))
            return false;
        ChatHandler(player->GetSession()).SendSysMessage(Shapeshift::GearLockedText);
        return true;
    }
}

class ShapeshiftCommandScript : public CommandScript
{
public:
    ShapeshiftCommandScript() : CommandScript("ShapeshiftCommandScript") {}

    ChatCommandTable GetCommands() const override
    {
        static ChatCommandTable shapeshiftTable =
        {
            { "apply",  HandleApply,  SEC_GAMEMASTER, Console::No },
            { "look",   HandleLook,   SEC_GAMEMASTER, Console::No },
            { "revert", HandleRevert, SEC_GAMEMASTER, Console::No },
            { "status", HandleStatus, SEC_GAMEMASTER, Console::No },
            { "prime",  HandlePrime,  SEC_GAMEMASTER, Console::No },
            { "size",   HandleSize,   SEC_GAMEMASTER, Console::No },
            { "puppet", HandlePuppet, SEC_GAMEMASTER, Console::No },
            { "stance", HandleStance, SEC_GAMEMASTER, Console::No },
        };
        static ChatCommandTable commandTable =
        {
            { "shapeshifter", shapeshiftTable },
            { "shapeshift", shapeshiftTable },          // the old name, for older addon copies
        };
        return commandTable;
    }

    static bool HandleApply(ChatHandler* handler, Tail rest)
    {
        Player* player = handler->GetPlayer();
        std::string error;
        std::optional<Shapeshift::ApplyArgs> args = Shapeshift::ParseApply(rest, error);
        if (!args)
            return Fail(handler, player, "args", "Shapeshifter: " + error);
        std::string problem = Engine::Instance().Apply(player, *args, false);
        if (!problem.empty())
            return Fail(handler, player, "apply", problem);
        return true;
    }

    static bool HandleLook(ChatHandler* handler, Tail rest)
    {
        Player* player = handler->GetPlayer();
        std::string error;
        std::optional<Shapeshift::LookArgs> look = Shapeshift::ParseLook(rest, error);
        if (!look)
            return Fail(handler, player, "args", "Shapeshifter: " + error);
        Shapeshift::ApplyArgs args;
        args.entry = look->entry;
        args.sizePct = look->sizePct;
        std::string problem = Engine::Instance().Apply(player, args, true);
        if (!problem.empty())
            return Fail(handler, player, "apply", problem);
        return true;
    }

    static bool HandleRevert(ChatHandler* handler)
    {
        Engine::Instance().Revert(handler->GetPlayer(), Shapeshift::RevertReason::Command);
        return true;
    }

    static bool HandleStatus(ChatHandler* handler)
    {
        Player* player = handler->GetPlayer();
        Engine::Instance().SendState(player);
        Engine::Instance().SendCaps(player);
        std::string text = Engine::Instance().Describe(player);
        std::size_t start = 0;
        while (start <= text.size())
        {
            std::size_t end = text.find('\n', start);
            handler->SendSysMessage(text.substr(start, end == std::string::npos ? std::string::npos : end - start));
            if (end == std::string::npos)
                break;
            start = end + 1;
        }
        return true;
    }

    // Silent on success: the catalogue sends it when a preview comes up empty.
    static bool HandlePrime(ChatHandler* handler, Tail rest)
    {
        Player* player = handler->GetPlayer();
        std::string error;
        std::optional<std::vector<uint32>> entries = Shapeshift::ParsePrime(rest, error);
        if (!entries)
            return Fail(handler, player, "args", "Shapeshifter: " + error);
        Engine::Instance().Prime(player, *entries);
        return true;
    }

    // Silent: the menu preview asks for its puppet on every pick and falls back when told PUPPET;off.
    static bool HandlePuppet(ChatHandler* handler, Tail rest)
    {
        Player* player = handler->GetPlayer();
        std::string error;
        std::optional<Shapeshift::PuppetArgs> args = Shapeshift::ParsePuppet(rest, error);
        if (!args)
            return Fail(handler, player, "args", "Shapeshifter: " + error);
        if (args->off)
            Engine::Instance().PuppetOff(player);
        else
            Engine::Instance().Puppet(player, args->entry, args->sizePct);
        return true;
    }

    // stance <1-3>: a stanced form's weapons, bonus and abilities (deep pass B2).
    static bool HandleStance(ChatHandler* handler, Tail rest)
    {
        Player* player = handler->GetPlayer();
        std::optional<uint32> stance = Shapeshift::ParseStance(rest);
        if (!stance)
            return Fail(handler, player, "args", "Shapeshifter: expected: stance <1-3>");
        std::string problem = Engine::Instance().Stance(player, *stance);
        if (!problem.empty())
            return Fail(handler, player, "stance", problem);
        return true;
    }

    static bool HandleSize(ChatHandler* handler, Tail rest)
    {
        Player* player = handler->GetPlayer();
        std::string error;
        std::optional<uint32> size = Shapeshift::ParseSize(rest, error);
        if (!size)
            return Fail(handler, player, "args", "Shapeshifter: " + error);
        std::string problem = Engine::Instance().Resize(player, *size);
        if (!problem.empty())
            return Fail(handler, player, "size", problem);
        return true;
    }
};

class ShapeshiftWorldScript : public WorldScript
{
public:
    ShapeshiftWorldScript() : WorldScript("ShapeshiftWorldScript", { WORLDHOOK_ON_STARTUP }) {}

    void OnStartup() override
    {
        Engine::Instance().LoadLeftovers();
        Engine::Instance().LoadStances();
#ifndef COA_WEAPON_OVERRIDE
        LOG_ERROR("server.loading", "[Shapeshifter] core-weapon-override.patch is not applied: form weapons will not "
            "decide which hands swing (see server/patches/)");
#endif
    }
};

class ShapeshiftPlayerScript : public PlayerScript
{
public:
    ShapeshiftPlayerScript() : PlayerScript("ShapeshiftPlayerScript",
        { PLAYERHOOK_ON_PLAYER_JUST_DIED, PLAYERHOOK_ON_BEFORE_LOGOUT, PLAYERHOOK_ON_LOGIN,
          PLAYERHOOK_ON_MAP_CHANGED, PLAYERHOOK_ON_BEFORE_TELEPORT, PLAYERHOOK_ON_LEVEL_CHANGED, PLAYERHOOK_ON_PLAYER_LEAVE_COMBAT,
          PLAYERHOOK_CAN_EQUIP_ITEM, PLAYERHOOK_CAN_UNEQUIP_ITEM, PLAYERHOOK_ON_SAVE, PLAYERHOOK_ON_UPDATE,
          PLAYERHOOK_ON_BEFORE_GET_LEVEL_FOR_XP_GAIN }) {}

    // Unleashed borrows the creature's level: every save writes the player's own, the next update
    // shows the form's again, and XP waits until the level is the player's.
    void OnPlayerSave(Player* player) override
    {
        if (Engine::Instance().AnyActive())
            Engine::Instance().OnSave(player);
    }

    void OnPlayerUpdate(Player* player, uint32 /*p_time*/) override
    {
        if (Engine::Instance().AnyActive())
            Engine::Instance().OnUpdate(player);
    }

    void OnPlayerBeforeGetLevelForXPGain(Player const* player, uint8& level) override
    {
        if (Engine::Instance().AnyActive() && Engine::Instance().LevelBorrowed(player->GetGUID()))
            level = std::numeric_limits<uint8>::max();     // at or past the level cap: GiveXP gives nothing
    }

    void OnPlayerJustDied(Player* player) override
    {
        Engine::Instance().Revert(player, Shapeshift::RevertReason::Death);
    }

    void OnPlayerBeforeLogout(Player* player) override
    {
        Engine::Instance().PuppetOff(player);
        Engine::Instance().Revert(player, Shapeshift::RevertReason::Logout);
    }

    void OnPlayerLogin(Player* player) override
    {
        Engine::Instance().OnLogin(player);
    }

    void OnPlayerMapChanged(Player* player) override
    {
        Engine::Instance().OnMapChanged(player);
    }

    // The preview puppet stays on its map; drop it before the player leaves that map.
    bool OnPlayerBeforeTeleport(Player* player, uint32 mapId, float /*x*/, float /*y*/, float /*z*/,
                                float /*orientation*/, uint32 /*options*/, Unit* /*target*/) override
    {
        if (mapId != player->GetMapId())
            Engine::Instance().PuppetOff(player);
        return true;
    }

    // Every level change (GiveLevel, .character level, .reset level) ends here: the object scale,
    // the form's gear and mana follow at once, spell bands out of combat.
    void OnPlayerLevelChanged(Player* player, uint8 /*oldLevel*/) override
    {
        if (Engine::Instance().AnyActive())
            Engine::Instance().OnLevelChanged(player);
    }

    void OnPlayerLeaveCombat(Player* player) override
    {
        if (Engine::Instance().AnyActive())
            Engine::Instance().OnLeaveCombat(player);
    }

    // A form's gear is fixed (user call): no equipping or unequipping while it is on.
    bool OnPlayerCanEquipItem(Player* player, uint8 /*slot*/, uint16& /*dest*/, Item* /*item*/, bool /*swap*/, bool notLoading) override
    {
        return !(notLoading && GearLocked(player));
    }

    bool OnPlayerCanUnequipItem(Player* player, uint16 /*pos*/, bool /*swap*/) override
    {
        return !GearLocked(player);
    }
};

class ShapeshiftSpellScript : public AllSpellScript
{
public:
    ShapeshiftSpellScript() : AllSpellScript("ShapeshiftSpellScript", { ALLSPELLHOOK_ON_SPELL_CHECK_CAST }) {}

    void OnSpellCheckCast(Spell* spell, bool /*strict*/, SpellCastResult& res) override
    {
        if (res != SPELL_CAST_OK || !Engine::Instance().AnyActive())
            return;
        Player* player = PlayerOf(spell->GetCaster());
        if (!player)
            return;
        SpellInfo const* info = spell->GetSpellInfo();
        if (Engine::Instance().CheckCast(player->GetGUID(), info->Id, spell->m_CastItem != nullptr,
                spell->IsTriggered(), info->HasAura(SPELL_AURA_MOUNTED),
                info->HasAura(SPELL_AURA_MOD_SHAPESHIFT)) == Shapeshift::CastVerdict::Refuse)
            res = SPELL_FAILED_NOT_SHAPESHIFT;
    }
};

class ShapeshiftMovementScript : public MovementHandlerScript
{
public:
    ShapeshiftMovementScript() : MovementHandlerScript("ShapeshiftMovementScript", { MOVEMENTHOOK_ON_PLAYER_MOVE }) {}

    void OnPlayerMove(Player* player, MovementInfo movementInfo, uint32 /*opcode*/) override
    {
        if (player && Engine::Instance().AnyActive())
            Engine::Instance().OnMove(player, movementInfo.HasMovementFlag(MOVEMENTFLAG_FLYING));
    }
};

class ShapeshiftUnitScript : public UnitScript
{
public:
    ShapeshiftUnitScript() : UnitScript("ShapeshiftUnitScript", true,
        { UNITHOOK_MODIFY_MELEE_DAMAGE, UNITHOOK_MODIFY_SPELL_DAMAGE_TAKEN, UNITHOOK_MODIFY_PERIODIC_DAMAGE_AURAS_TICK,
          UNITHOOK_ON_DISPLAYID_CHANGE, UNITHOOK_ON_AURA_APPLY, UNITHOOK_ON_AURA_REMOVE }) {}

    void ModifyMeleeDamage(Unit* /*target*/, Unit* attacker, uint32& damage) override
    {
        if (!Engine::Instance().AnyActive())
            return;
        if (Player* player = PlayerOf(attacker))
            if (std::optional<Shapeshift::Hot> hot = Engine::Instance().Get(player->GetGUID()))
                damage = Shapeshift::ScaleAmount(damage, hot->meleeScale);
    }

    void ModifySpellDamageTaken(Unit* /*target*/, Unit* attacker, int32& damage, SpellInfo const* spellInfo) override
    {
        if (damage <= 0 || !spellInfo || !Engine::Instance().AnyActive())
            return;
        if (Player* player = PlayerOf(attacker))
            damage = int32(Shapeshift::ScaleAmount(uint32(damage), Engine::Instance().SpellScale(player->GetGUID(), spellInfo->Id)));
    }

    // Called for periodic damage and, with the same argument order, periodic heals.
    void ModifyPeriodicDamageAurasTick(Unit* /*target*/, Unit* attacker, uint32& damage, SpellInfo const* spellInfo) override
    {
        if (!spellInfo || !Engine::Instance().AnyActive())
            return;
        if (Player* player = PlayerOf(attacker))
            damage = Shapeshift::ScaleAmount(damage, Engine::Instance().SpellScale(player->GetGUID(), spellInfo->Id));
    }

    // Something else (a transform aura ending, a vehicle) put a model on the player: put the form back.
    void OnDisplayIdChange(Unit* unit, uint32 displayId) override
    {
        static thread_local bool restoring = false;
        if (restoring || !Engine::Instance().AnyActive())
            return;
        Player* player = PlayerOf(unit);
        if (!player)
            return;
        std::optional<Shapeshift::Hot> hot = Engine::Instance().Get(player->GetGUID());
        if (!hot || hot->displayId == displayId)
            return;
        restoring = true;
        player->SetDisplayId(hot->displayId, hot->scale);
        player->SetByteValue(UNIT_FIELD_BYTES_0, 2, player->GetByteValue(PLAYER_BYTES_3, 0));
        Engine::Instance().ReassertScale(player);
        restoring = false;
    }

    void OnAuraApply(Unit* unit, Aura* aura) override
    {
        if (!Engine::Instance().AnyActive() || !aura)
            return;
        if (Player* player = PlayerOf(unit))
        {
            if (ChangesScale(aura->GetSpellInfo()))
                Engine::Instance().ReassertScale(player);
            if (ResetsForm(aura->GetSpellInfo()))
                Engine::Instance().ReassertForm(player);
        }
    }

    void OnAuraRemove(Unit* unit, AuraApplication* aurApp, AuraRemoveMode /*mode*/) override
    {
        if (!Engine::Instance().AnyActive() || !aurApp)
            return;
        if (Player* player = PlayerOf(unit))
        {
            if (ChangesScale(aurApp->GetBase()->GetSpellInfo()))
                Engine::Instance().ReassertScale(player);
            if (ResetsForm(aurApp->GetBase()->GetSpellInfo()))
                Engine::Instance().ReassertForm(player);
        }
    }
};

// A form's guardians are defensive, not aggressive (user, 2026-09-26): they fight what the player
// attacks or what attacks the player, and never pull whatever walks past. Guardian::InitStats forces
// REACT_AGGRESSIVE after the guardian stats hooks run, so this sets it once the summon joins the map,
// before its first look around (Map::SummonCreature: InitStats, AddToMap, then the sight sweep).
class ShapeshiftCreatureScript : public AllCreatureScript
{
public:
    ShapeshiftCreatureScript() : AllCreatureScript("ShapeshiftCreatureScript") {}

    void OnCreatureAddWorld(Creature* creature) override
    {
        if (!creature->IsSummon() || !Shapeshift::IsFormSummon(creature->GetUInt32Value(UNIT_CREATED_BY_SPELL)))
            return;
        if (!creature->GetOwnerGUID().IsPlayer())
            return;
        creature->SetReactState(REACT_DEFENSIVE);
    }
};

void AddShapeshiftScripts()
{
    new ShapeshiftCommandScript();
    new ShapeshiftWorldScript();
    new ShapeshiftPlayerScript();
    new ShapeshiftSpellScript();
    new ShapeshiftUnitScript();
    new ShapeshiftMovementScript();
    new ShapeshiftCreatureScript();
}
