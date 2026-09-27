/*
 * mod-shapeshifter engine. See Shapeshift.h.
 */

#include "Shapeshift.h"

#include "Chat.h"
#include "CreatureData.h"
#include "DatabaseEnv.h"
#include "Item.h"
#include "Log.h"
#include "NameOverride.h"
#include "ObjectAccessor.h"
#include "ObjectMgr.h"
#include "PassiveAI.h"
#include "Player.h"
#include "QueryPackets.h"
#include "SpellAuraDefines.h"
#include "SpellAuraEffects.h"
#include "SpellAuras.h"
#include "SpellInfo.h"
#include "SpellMgr.h"
#include "TemporarySummon.h"
#include "UpdateData.h"
#include "UpdateMask.h"
#include "WorldPacket.h"
#include "WorldSession.h"

#include <algorithm>
#include <array>
#include <cmath>

#ifndef COA_WEAPON_OVERRIDE
#pragma message("mod-shapeshifter: core-weapon-override.patch is not applied; form weapons will not decide which hands swing")
#endif

namespace
{
    constexpr uint32 SPELL_SLOW_FALL = 130;
    constexpr uint8 FORM_GEAR_SLOTS = 19;     // EQUIPMENT_SLOT_HEAD to EQUIPMENT_SLOT_TABARD
    constexpr uint8 MAX_CLASS_LEVEL = 80;

    void SendAddon(Player* player, std::string const& payload)
    {
        WorldPacket data;
        ChatHandler::BuildChatPacket(data, CHAT_MSG_WHISPER, LANG_ADDON, player, player, "SHSH\t" + payload);
        player->SendDirectMessage(&data);
    }

    // Tell every client that can see the player, and the player's own, what to call it.
    void PushName(Player* player, std::string const& name)
    {
        WorldPackets::Query::NameQueryResponse response;
        response.Guid = player->GetGUID().WriteAsPacked();
        response.NameUnknown = false;
        response.Name = name;
        response.Race = player->getRace();
        response.Sex = player->GetByteValue(PLAYER_BYTES_3, 0);
        response.Class = player->getClass();
        response.Declined = false;
        player->SendMessageToSet(response.Write(), true);
    }

    // SetDisplayId copies the model's gender into the unit bytes; the player keeps their own.
    void KeepGender(Player* player)
    {
        player->SetByteValue(UNIT_FIELD_BYTES_0, 2, player->GetByteValue(PLAYER_BYTES_3, 0));
    }

    char const* ReasonWord(Shapeshift::RevertReason reason)
    {
        switch (reason)
        {
            case Shapeshift::RevertReason::Command: return "revert";
            case Shapeshift::RevertReason::Death: return "death";
            case Shapeshift::RevertReason::Logout: return "logout";
            case Shapeshift::RevertReason::Replace: return "replace";
        }
        return "revert";
    }

    // A spell whose effects would change the saved character (a pet, items, skills, the bind
    // point, learned spells, reputation) can never be part of a form.
    bool WritesToCharacter(SpellInfo const* info)
    {
        if (sSpellMgr->GetSpellLearnSkill(info->Id))
            return true;
        SkillLineAbilityMapBounds bounds = sSpellMgr->GetSkillLineAbilityMapBounds(info->Id);
        if (bounds.first != bounds.second)
            return true;
        for (SpellEffectInfo const& effect : info->GetEffects())
        {
            switch (effect.Effect)
            {
                case SPELL_EFFECT_BIND:
                case SPELL_EFFECT_QUEST_COMPLETE:
                case SPELL_EFFECT_CREATE_ITEM:
                case SPELL_EFFECT_CREATE_ITEM_2:
                case SPELL_EFFECT_CREATE_RANDOM_ITEM:
                case SPELL_EFFECT_CREATE_MANA_GEM:
                case SPELL_EFFECT_LEARN_SPELL:
                case SPELL_EFFECT_LEARN_PET_SPELL:
                case SPELL_EFFECT_DUAL_WIELD:
                case SPELL_EFFECT_SKILL_STEP:
                case SPELL_EFFECT_SKILL:
                case SPELL_EFFECT_TRADE_SKILL:
                case SPELL_EFFECT_PROFICIENCY:
                case SPELL_EFFECT_ADD_HONOR:
                case SPELL_EFFECT_ENCHANT_ITEM:
                case SPELL_EFFECT_ENCHANT_ITEM_TEMPORARY:
                case SPELL_EFFECT_ENCHANT_ITEM_PRISMATIC:
                case SPELL_EFFECT_TAMECREATURE:
                case SPELL_EFFECT_SUMMON_PET:
                case SPELL_EFFECT_APPLY_GLYPH:
                case SPELL_EFFECT_REPUTATION:
                case SPELL_EFFECT_UNLEARN_SPECIALIZATION:
                case SPELL_EFFECT_TALENT_SPEC_COUNT:
                case SPELL_EFFECT_TALENT_SPEC_SELECT:
                    return true;
                default:
                    break;
            }
        }
        return false;
    }

    // The spell and the spells its effects trigger, one level down.
    std::vector<uint32> WithTriggers(uint32 spellId)
    {
        std::vector<uint32> out{ spellId };
        if (SpellInfo const* info = sSpellMgr->GetSpellInfo(spellId))
            for (SpellEffectInfo const& effect : info->GetEffects())
                if (effect.TriggerSpell && sSpellMgr->GetSpellInfo(effect.TriggerSpell)
                    && std::find(out.begin(), out.end(), effect.TriggerSpell) == out.end())
                    out.push_back(effect.TriggerSpell);
        return out;
    }

    // Empty when every spell exists and none of them (or what they trigger) writes to the character.
    std::string CheckSpells(std::vector<uint32> const& ids)
    {
        for (uint32 id : ids)
        {
            if (!sSpellMgr->GetSpellInfo(id))
                return "Spell " + std::to_string(id) + " does not exist on this server.";
            for (uint32 part : WithTriggers(id))
                if (WritesToCharacter(sSpellMgr->GetSpellInfo(part)))
                    return "Spell " + std::to_string(id) + " can't be part of a form.";
        }
        return "";
    }

    Powers PowerOf(Shapeshift::Resource resource)
    {
        switch (resource)
        {
            case Shapeshift::Resource::Rage: return POWER_RAGE;
            case Shapeshift::Resource::Energy: return POWER_ENERGY;
            default: return POWER_MANA;
        }
    }

    // The real equipment, as the ledger sees it.
    std::vector<Shapeshift::RealItem> RealGear(Player* player)
    {
        std::vector<Shapeshift::RealItem> out;
        for (uint8 slot = 0; slot < FORM_GEAR_SLOTS; ++slot)
        {
            Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
            if (!item || !item->GetTemplate())
                continue;
            WeaponAttackType attack = Player::GetAttackBySlot(slot);
            Shapeshift::RealItem real;
            real.slot = slot;
            real.entry = item->GetEntry();
            real.guid = item->GetGUID().GetRawValue();
            real.broken = item->IsBroken();
            real.usable = attack == MAX_ATTACK || player->CanUseAttackType(attack);
            out.push_back(real);
        }
        return out;
    }

    // Current health and power percentages, kept across stat changes that move the maxima.
    struct Percentages
    {
        float health;
        float power;
        Powers type;

        explicit Percentages(Player* player)
            : health(player->GetHealthPct()), type(player->getPowerType())
        {
            uint32 max = player->GetMaxPower(type);
            power = max ? float(player->GetPower(type)) / float(max) : 0.0f;
        }

        void Restore(Player* player) const
        {
            if (player->IsAlive())
                player->SetHealth(std::max<uint32>(1, uint32(float(player->GetMaxHealth()) * health / 100.0f)));
            if (player->getPowerType() == type)
                player->SetPower(type, uint32(float(player->GetMaxPower(type)) * power));
        }
    };
}

namespace Shapeshift
{
    Engine& Engine::Instance()
    {
        static Engine engine;
        return engine;
    }

    std::optional<ActiveForm> Engine::Copy(ObjectGuid guid)
    {
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        if (it == _active.end())
            return std::nullopt;
        return it->second;
    }

    // Write a worked-on copy back, unless the form was reverted meanwhile.
    void Engine::Store(ObjectGuid guid, ActiveForm const& form)
    {
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        if (it != _active.end())
            it->second = form;
    }

    std::optional<Hot> Engine::Get(ObjectGuid guid)
    {
        if (!AnyActive())
            return std::nullopt;
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        if (it == _active.end())
            return std::nullopt;
        ActiveForm const& form = it->second;
        return Hot{ form.displayId, form.scale, form.meleeScale, form.args.fly && !form.lookOnly };
    }

    // A flying form plays its fly animation while airborne and its ground one on landing (the
    // anim tier, as creature_template_addon bytes1 sets it for creatures; seen working in game with
    // `.debug setvalue 74 50331648`, 2026-09-24). Every movement packet lands here, so it is cheap.
    void Engine::OnMove(Player* player, bool flying)
    {
        std::optional<Hot> hot = Get(player->GetGUID());
        if (!hot || !hot->flies)
            return;
        uint8 want = flying ? UNIT_BYTE1_FLAG_FLY : UNIT_BYTE1_FLAG_GROUND;
        if (player->GetByteValue(UNIT_FIELD_BYTES_1, UNIT_BYTES_1_OFFSET_ANIM_TIER) != want)
            player->SetByteValue(UNIT_FIELD_BYTES_1, UNIT_BYTES_1_OFFSET_ANIM_TIER, want);
    }

    // A form's gear, weapons included, is fixed in both modes (user call; ruling change 15).
    bool Engine::GearFixed(ObjectGuid guid)
    {
        if (!AnyActive())
            return false;
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        return it != _active.end() && it->second.HasFormWeapons();
    }

    float Engine::SpellScale(ObjectGuid guid, uint32 spellId)
    {
        if (!AnyActive() || IsClassGrade(spellId))      // band rows already carry the level's numbers
            return 1.0f;
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        if (it == _active.end() || it->second.lookOnly || it->second.args.mode != Mode::Balanced)
            return 1.0f;
        return it->second.formSpellSet.count(spellId) ? it->second.spellScale : 1.0f;
    }

    CastVerdict Engine::CheckCast(ObjectGuid guid, uint32 spellId, bool fromItem, bool triggered, bool mounts,
                                  bool shapeshifts)
    {
        if (!AnyActive())
            return CastVerdict::Allow;
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        if (it == _active.end())
            return CastVerdict::Allow;
        if (mounts)
            return CastVerdict::Refuse;            // full and look-only forms alike
        if (shapeshifts && it->second.ClassGrade() && !it->second.lookOnly)
            return CastVerdict::Refuse;            // even triggered or from an item (ruling change 6)
        if (it->second.lookOnly || triggered || fromItem)
            return CastVerdict::Allow;
        std::vector<uint32> const& kit = it->second.mappedKit;
        std::vector<uint32> const& stance = it->second.stanceKit;
        bool own = std::find(kit.begin(), kit.end(), spellId) != kit.end()
            || std::find(stance.begin(), stance.end(), spellId) != stance.end();
        return own ? CastVerdict::Allow : CastVerdict::Refuse;
    }

    // The model's height at its current size, for FormRunRate (0: unknown, the size rule adds nothing).
    static float HeightYards(ApplyArgs const& args)
    {
        return float(args.heightTenths) / 10.0f * float(args.sizePct) / 100.0f;
    }

    std::string Engine::Apply(Player* player, ApplyArgs const& args, bool lookOnly)
    {
        if (player->IsInCombat())
            return "You can't transform in combat.";
        if (!player->IsAlive())
            return "You can't transform while dead.";
        if (player->IsInFlight() || player->GetVehicle())
            return "You can't transform on a flight path or in a vehicle.";

        CreatureTemplate const* info = sObjectMgr->GetCreatureTemplate(args.entry);
        if (!info)
            return "No creature has entry " + std::to_string(args.entry) + ".";
        // GetFirstVisibleModel never returns null: with no usable model it falls back to a default.
        CreatureModel const* model = info->GetFirstVisibleModel();
        if (model == &CreatureModel::DefaultVisibleModel || !model->CreatureDisplayID)
            return info->Name + " has no visible model.";
        // as=: a second shape whose model sits on a stand-in creature ("... Transform Visual")
        // takes its name, level and stats from the real one.
        CreatureTemplate const* self = args.identity ? sObjectMgr->GetCreatureTemplate(args.identity) : info;
        if (!self)
            return "No creature has entry " + std::to_string(args.identity) + ".";

        bool balanced = args.mode == Mode::Balanced;
        std::vector<uint32> mappedKit = MapKitIds(args.kit, player->GetLevel(), balanced);
        std::vector<uint32> mappedPassives = MapKitIds(args.passives, player->GetLevel(), balanced);
        if (!lookOnly)
        {
            std::string problem = CheckSpells(mappedKit);
            if (problem.empty())
                problem = CheckSpells(mappedPassives);
            if (StanceRow const* first = StanceOf(args.gearSet, 1); first && problem.empty())
            {
                std::vector<uint32> bases{ FamilyBase(first->bonus) };
                for (uint32 k : first->abilities)
                    bases.push_back(FamilyBase(k));
                problem = CheckSpells(MapKitIds(bases, player->GetLevel(), balanced));
            }
            if (!problem.empty())
                return problem;
        }

        Revert(player, RevertReason::Replace);

        ActiveForm form;
        form.args = args;
        form.lookOnly = lookOnly;
        form.name = self->Name;
        form.displayId = model->CreatureDisplayID;
        form.creatureLevel = self->maxlevel;
        form.scale = (model->DisplayScale > 0.0f ? model->DisplayScale : 1.0f) * float(args.sizePct) / 100.0f;
        form.gmFly = player->CanFly() && !player->HasFlyAura() && !player->HasIncreaseMountedFlightSpeedAura();
        form.mappedKit = std::move(mappedKit);
        form.mappedPassives = std::move(mappedPassives);
        form.band = BandOf(player->GetLevel());
        form.runCreature = self->speed_run;
        form.runRate = FormRunRate(form.runCreature, HeightYards(args));

        player->RemoveAurasByType(SPELL_AURA_MOUNTED);
        player->RemoveAurasByType(SPELL_AURA_MOD_SHAPESHIFT);
        player->SetDisplayId(form.displayId, form.scale);
        KeepGender(player);
        HandsOn(player, form);

        if (!lookOnly)
        {
            LevelOn(player, form);
            LearnKit(player, form);
            ApplyStats(player, self, form);
            WeaponsOn(player, form);
            GearOn(player, form);
            UpdateMeleeScale(player, form);
            ResourceOn(player, form);
            ManaOn(player, form);
            if (args.fly)
                player->SetCanFly(true);
            SpeedOn(player, form);
            if (StanceRow const* first = StanceOf(args.gearSet, 1))
            {
                form.stance = 1;                   // stance 1's weapons are the form's own gear set's
                StanceSpellsOn(player, form, *first);
            }
        }

        NameOverride::Set(player->GetGUID(), form.name);
        PushName(player, form.name);
        if (args.visualKit)
            player->SendPlaySpellVisual(args.visualKit);
        if (args.soundTransform)
            player->PlayDirectSound(args.soundTransform);
        WriteActive(player, form);

        LOG_INFO("module", "[Shapeshifter] {} became {} ({}, {}%{})", player->GetName(), form.name,
            lookOnly ? "look" : (args.mode == Mode::Unleashed ? "unleashed" : "balanced"), args.sizePct,
            form.ClassGrade() ? ", class-grade" : "");
        ActiveForm stored = form;                  // what the replies describe, kept past the move
        {
            std::lock_guard<std::mutex> guard(_lock);
            if (!form.formSpells.empty() || !form.stanceSpells.empty())
                _leftovers.insert(player->GetGUID().GetCounter());
            _active[player->GetGUID()] = std::move(form);
            _count.store(uint32(_active.size()));
        }
        ReassertScale(player);
        SendOn(player, stored);
        return "";
    }

    // Learn the mapped kit and add the mapped passives; record every spell and trigger as a form spell.
    void Engine::LearnKit(Player* player, ActiveForm& form)
    {
        std::vector<uint32> ids = form.mappedKit;
        ids.insert(ids.end(), form.mappedPassives.begin(), form.mappedPassives.end());
        if (form.args.manaPct && form.args.resource == Resource::Mana)
            ids.push_back(ManaRegenPassive);
        for (uint32 id : ids)
            for (uint32 part : WithTriggers(id))
                if (!form.formSpellSet.count(part) && !player->HasAura(part))
                {
                    form.formSpellSet.insert(part);
                    form.formSpells.push_back(part);
                }

        // Never touch a spell the player has in any state: updateActive would run the rank
        // chain, and reviving a removed entry would get it saved.
        for (uint32 id : form.mappedKit)
        {
            if (player->GetSpellMap().count(id))
                continue;
            player->addSpell(id, SPEC_MASK_ALL, false, true);
            auto it = player->GetSpellMap().find(id);
            if (it != player->GetSpellMap().end() && it->second->State == PLAYERSPELL_TEMPORARY)
                form.learned.push_back(id);
        }
        for (uint32 id : form.mappedPassives)
            player->AddAura(id, player);
    }

    void Engine::UnlearnKit(Player* player, ActiveForm& form)
    {
        for (uint32 id : form.learned)
            player->removeSpell(id, SPEC_MASK_ALL, true);
        for (uint32 id : form.formSpells)
            player->RemoveAurasDueToSpell(id);
        form.learned.clear();
        form.formSpells.clear();
        form.formSpellSet.clear();
    }

    // A new level band: the old band's spells go, the new band's come (never in combat).
    void Engine::SwapBand(Player* player, ActiveForm& form)
    {
        bool keepRegen = form.regenAmount != 0;
        StanceSpellsOff(player, form);
        UnlearnKit(player, form);
        form.band = BandOf(player->GetLevel());
        form.mappedKit = MapKitIds(form.args.kit, player->GetLevel(), true);
        form.mappedPassives = MapKitIds(form.args.passives, player->GetLevel(), true);
        form.pendingBand = false;
        LearnKit(player, form);
        if (keepRegen)
            ManaOn(player, form);
        if (StanceRow const* row = StanceOf(form.args.gearSet, form.stance))
            StanceSpellsOn(player, form, *row);
        WriteActive(player, form);
    }

    // ---- Weapon stances (deep pass B2) --------------------------------------------------------
    static std::vector<FormItem> GearSetItems(uint32 gearSet);

    // Loaded once at startup. A missing table would abort the core (MySQL error 1146), so its
    // columns are counted first; without all six, stances stay off (adjudication B2-3).
    void Engine::LoadStances()
    {
        _stances.clear();
        QueryResult columns = WorldDatabase.Query("SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'shapeshifter_stance'");
        if (!columns || columns->Fetch()[0].Get<uint64>() != 6)
        {
            LOG_INFO("server.loading", ">> Shapeshifter: no shapeshifter_stance table, weapon stances are off");
            return;
        }
        QueryResult rows = WorldDatabase.Query(
            "SELECT gear_set, stance, name, weapon_set, bonus, abilities FROM shapeshifter_stance ORDER BY gear_set, stance");
        uint32 count = 0;
        if (rows)
        {
            do
            {
                Field* field = rows->Fetch();
                StanceRow row;
                row.gearSet = field[0].Get<uint32>();
                row.stance = field[1].Get<uint32>();
                row.name = field[2].Get<std::string>();
                row.weaponSet = field[3].Get<uint32>();
                row.bonus = field[4].Get<uint32>();
                std::optional<std::vector<uint32_t>> abilities = ParseFamilies(field[5].Get<std::string>());
                if (!row.gearSet || row.gearSet > MaxGearSet || !row.weaponSet || row.weaponSet > MaxGearSet
                    || row.stance < 1 || row.stance > MaxStances || row.bonus > MaxFamily || !abilities)
                {
                    LOG_ERROR("module", "[Shapeshifter] shapeshifter_stance row {}/{} is out of range, skipped",
                        row.gearSet, row.stance);
                    continue;
                }
                row.abilities = *abilities;
                _stances[row.gearSet].push_back(std::move(row));
                ++count;
            } while (rows->NextRow());
        }
        LOG_INFO("server.loading", ">> Shapeshifter: {} weapon stance(s) loaded", count);
    }

    StanceRow const* Engine::StanceOf(uint32 gearSet, uint32 stance) const
    {
        auto it = _stances.find(gearSet);
        if (!gearSet || !stance || it == _stances.end())
            return nullptr;
        for (StanceRow const& row : it->second)
            if (row.stance == stance)
                return &row;
        return nullptr;
    }

    // The stance's bonus aura and its own abilities, at the player's band (in memory, like the kit).
    void Engine::StanceSpellsOn(Player* player, ActiveForm& form, StanceRow const& row)
    {
        bool balanced = form.args.mode == Mode::Balanced;
        std::vector<uint32> bases;
        for (uint32 k : row.abilities)
            bases.push_back(FamilyBase(k));
        form.stanceKit = MapKitIds(bases, player->GetLevel(), balanced);
        uint32 bonus = MapKitIds({ FamilyBase(row.bonus) }, player->GetLevel(), balanced).front();
        std::vector<uint32> ids = form.stanceKit;
        ids.push_back(bonus);
        for (uint32 id : ids)
            for (uint32 part : WithTriggers(id))
                if (!form.formSpellSet.count(part) && !player->HasAura(part)
                    && std::find(form.stanceSpells.begin(), form.stanceSpells.end(), part) == form.stanceSpells.end())
                    form.stanceSpells.push_back(part);
        for (uint32 id : form.stanceKit)
        {
            if (player->GetSpellMap().count(id))
                continue;
            player->addSpell(id, SPEC_MASK_ALL, false, true);
            auto it = player->GetSpellMap().find(id);
            if (it != player->GetSpellMap().end() && it->second->State == PLAYERSPELL_TEMPORARY)
                form.stanceLearned.push_back(id);
        }
        player->AddAura(bonus, player);
    }

    void Engine::StanceSpellsOff(Player* player, ActiveForm& form)
    {
        for (uint32 id : form.stanceLearned)
            player->removeSpell(id, SPEC_MASK_ALL, true);
        for (uint32 id : form.stanceSpells)
            player->RemoveAurasDueToSpell(id);
        form.stanceKit.clear();
        form.stanceLearned.clear();
        form.stanceSpells.clear();
    }

    // Guardians the form's own spells called end with the form (deep pass B3): anything controlled
    // that a class-grade spell created. Collected first: unsummoning changes the set.
    void Engine::DismissSummons(Player* player)
    {
        std::vector<TempSummon*> gone;
        for (Unit* unit : player->m_Controlled)
            if (unit && unit->IsSummon() && IsFormSummon(unit->GetUInt32Value(UNIT_CREATED_BY_SPELL)))
                gone.push_back(unit->ToTempSummon());
        for (TempSummon* summon : gone)
            summon->UnSummon();
    }

    // The crash-cleanup row: every aura a form's spells may leave, the stance's included.
    void Engine::WriteActive(Player* player, ActiveForm const& form)
    {
        std::vector<uint32> all = form.formSpells;
        all.insert(all.end(), form.stanceSpells.begin(), form.stanceSpells.end());
        if (!all.empty())
            CharacterDatabase.Execute("REPLACE INTO shapeshifter_active (guid, auras) VALUES ({}, '{}')",
                player->GetGUID().GetCounter(), JoinIds(all));
    }

    std::string Engine::OnReply(ActiveForm const& form) const
    {
        return FormatOn(form.args.entry, form.args.mode == Mode::Unleashed, form.args.sizePct,
            form.lookOnly ? std::vector<uint32>() : form.mappedKit, form.lookOnly, form.name);
    }

    // ON, then for a stanced form its STANCE: the addon's ON handler starts its state afresh.
    void Engine::SendOn(Player* player, ActiveForm const& form)
    {
        SendAddon(player, OnReply(form));
        if (form.stance && !form.lookOnly)
            SendAddon(player, FormatStance(form.stance, form.stanceKit));
    }

    // `.shapeshifter stance <n>`: the stance's weapons, bonus and abilities, in place (ruling 5).
    std::string Engine::Stance(Player* player, uint32 stance)
    {
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (!copy)
            return "You are not transformed.";
        ActiveForm& form = *copy;
        if (form.lookOnly || !form.stance)
            return "This form has no stances.";
        StanceRow const* row = StanceOf(form.args.gearSet, stance);
        if (!row)
            return "This form has no stance " + std::to_string(stance) + ".";
        if (!player->IsAlive())
            return "You can't change stance while dead.";
        if (player->IsInFlight() || player->GetVehicle())
            return "You can't change stance on a flight path or in a vehicle.";
        if (stance == form.stance)
            return "";
        uint32 now = getMSTime();
        if (form.stanceSwitchedMs && getMSTimeDiff(form.stanceSwitchedMs, now) < StanceCooldownMs)
            return "You can't change stance yet.";

        // Weapons: undo the old set as a revert would, then the new one as an apply would.
        WeaponsOff(player, form);
        std::vector<FormItem> items;
        for (FormItem const& item : form.formItems)
            if (!item.weapon)
                items.push_back(item);
        for (FormItem const& item : GearSetItems(row->weaponSet))
            if (item.weapon)
                items.push_back(item);
        form.formItems = std::move(items);
        WeaponsOn(player, form);
        GearOn(player, form);
        UpdateMeleeScale(player, form);
        HandsOn(player, form);

        StanceSpellsOff(player, form);
        form.stance = stance;
        form.stanceSwitchedMs = now;
        StanceSpellsOn(player, form, *row);
        WriteActive(player, form);
        Store(player->GetGUID(), form);
        LOG_INFO("module", "[Shapeshifter] {} takes stance {} ({})", player->GetName(), stance, row->name);
        SendAddon(player, FormatStance(form.stance, form.stanceKit));
        return "";
    }

    // Unleashed: the player takes the creature's level (user call, 2026-09-27), so hit, resists and
    // armour mitigation work at it. SetLevel alone changes no stats, talents or skills, and every save
    // writes the player's own level (OnSave), so a crash never keeps the form's.
    void Engine::LevelOn(Player* player, ActiveForm& form)
    {
        if (form.args.mode != Mode::Unleashed)
            return;
        form.realLevel = player->GetLevel();
        uint8 level = uint8(UnleashedLevel(form.creatureLevel));
        if (level != form.realLevel)
            player->SetLevel(level, true);
    }

    // Autosave, logout and .save all come through here before the character row is written.
    void Engine::OnSave(Player* player)
    {
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (!copy || !copy->realLevel || player->GetLevel() == copy->realLevel)
            return;
        player->SetLevel(copy->realLevel, false);          // not sent: the client keeps the form's level
        std::lock_guard<std::mutex> guard(_lock);
        if (_levelRestore.insert(player->GetGUID()).second)
            _restoreCount.fetch_add(1, std::memory_order_relaxed);
    }

    // The update after a save: the form's level again.
    void Engine::OnUpdate(Player* player)
    {
        if (_restoreCount.load(std::memory_order_relaxed) == 0)
            return;
        {
            std::lock_guard<std::mutex> guard(_lock);
            if (!_levelRestore.erase(player->GetGUID()))
                return;
            _restoreCount.fetch_sub(1, std::memory_order_relaxed);
        }
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (copy && copy->realLevel)
            player->SetLevel(uint8(UnleashedLevel(copy->creatureLevel)), true);
    }

    // XP waits while the level is the form's: it would be counted at the wrong level.
    bool Engine::LevelBorrowed(ObjectGuid guid)
    {
        std::lock_guard<std::mutex> guard(_lock);
        auto it = _active.find(guid);
        return it != _active.end() && it->second.realLevel != 0;
    }

    void Engine::ApplyStats(Player* player, CreatureTemplate const* info, ActiveForm& form)
    {
        float healthPct = player->GetHealthPct();
        float maxHealth = float(player->GetMaxHealth());
        float armor = float(player->GetArmor());
        float healthTarget = maxHealth;
        float armorTarget = armor;

        if (form.args.mode == Mode::Balanced)
        {
            // Forms with gear take their stats from it; the profile multipliers are for the rest.
            if (!form.HasGear())
            {
                float multiplier = ProfileMultiplier(form.args.profile);
                healthTarget = maxHealth * multiplier;
                armorTarget = armor * multiplier;
            }
            form.spellScale = BalancedSpellScale(player->GetLevel(), info->maxlevel);
        }
        else if (CreatureBaseStats const* stats = sObjectMgr->GetCreatureBaseStats(info->maxlevel, uint8(info->unit_class)))
        {
            healthTarget = float(stats->GenerateHealth(info));
            armorTarget = stats->GenerateArmor(info);
        }

        // Flat modifiers undo exactly; percent modifiers are recomputed from auras by the core and
        // would be lost or mis-restored.
        form.healthFlat = FlatDelta(maxHealth, healthTarget);
        form.armorFlat = FlatDelta(armor, armorTarget);
        player->HandleStatFlatModifier(UNIT_MOD_HEALTH, TOTAL_VALUE, form.healthFlat, true);
        player->HandleStatFlatModifier(UNIT_MOD_ARMOR, TOTAL_VALUE, form.armorFlat, true);
        player->SetHealth(std::max<uint32>(1, uint32(float(player->GetMaxHealth()) * healthPct / 100.0f)));
    }

    // Unleashed: the creature's swing over the player's, read after the form's weapons are on.
    void Engine::UpdateMeleeScale(Player* player, ActiveForm& form)
    {
        if (form.args.mode != Mode::Unleashed)
            return;
        CreatureTemplate const* info = sObjectMgr->GetCreatureTemplate(form.args.identity ? form.args.identity : form.args.entry);
        CreatureBaseStats const* stats = info ? sObjectMgr->GetCreatureBaseStats(info->maxlevel, uint8(info->unit_class)) : nullptr;
        if (!stats)
            return;
        form.meleeScale = UnleashedMeleeMultiplier(stats->GenerateBaseDamage(info), info->DamageModifier,
            info->BaseAttackTime, player->GetFloatValue(UNIT_FIELD_MINDAMAGE), player->GetFloatValue(UNIT_FIELD_MAXDAMAGE));
    }

    // A gear set's items that exist.
    static std::vector<FormItem> GearSetItems(uint32 gearSet)
    {
        std::vector<FormItem> items;
        if (!gearSet)
            return items;
        for (uint8 slot = 0; slot < FORM_GEAR_SLOTS; ++slot)
        {
            uint32 entry = GearItemId(gearSet, slot);
            if (ItemTemplate const* proto = sObjectMgr->GetItemTemplate(entry))
                items.push_back({ slot, entry, proto->Class == ITEM_CLASS_WEAPON });
        }
        return items;
    }

    void Engine::BuildFormItems(ActiveForm& form)
    {
        if (form.formItems.empty())
            form.formItems = GearSetItems(form.args.gearSet);
    }

    // What everyone sees in the form's hands (FormHands), look-only forms too. Only the visible-item
    // fields change: the real items stay equipped, and HandsOff shows them again.
    void Engine::HandsOn(Player* player, ActiveForm const& form)
    {
        std::array<uint32_t, 3> creature{ 0, 0, 0 };
        for (uint32 entry : { form.args.entry, form.args.identity })
        {
            int8 id = 1;
            if (EquipmentInfo const* equipment = entry ? sObjectMgr->GetEquipmentInfo(entry, id) : nullptr)
            {
                for (uint8 hand = 0; hand < 3; ++hand)
                    creature[hand] = equipment->ItemEntry[hand];
                break;
            }
        }
        std::array<uint32_t, 3> hands = FormHands(form.formItems.empty() ? GearSetItems(form.args.gearSet)
                                                                          : form.formItems, creature);
        for (uint8 hand = 0; hand < 3; ++hand)
        {
            uint8 slot = EQUIPMENT_SLOT_MAINHAND + hand;
            player->SetUInt32Value(PLAYER_VISIBLE_ITEM_1_ENTRYID + (slot * 2), hands[hand]);
            player->SetUInt32Value(PLAYER_VISIBLE_ITEM_1_ENCHANTMENT + (slot * 2), 0);
        }
    }

    void Engine::HandsOff(Player* player)
    {
        for (uint8 slot = EQUIPMENT_SLOT_MAINHAND; slot <= EQUIPMENT_SLOT_RANGED; ++slot)
            player->SetVisibleItemSlot(slot, player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot));
    }

    // Run and flight at the form's own speed (core-form-speed.patch); slows and speed auras still apply.
    void Engine::SpeedOn(Player* player, ActiveForm const& form)
    {
#ifdef COA_FORM_SPEED
        player->SetFormSpeedRate(MOVE_RUN, form.runRate);
        player->SetFormSpeedRate(MOVE_FLIGHT, form.args.fly ? FlightRate : 1.0f);
        player->UpdateSpeed(MOVE_RUN, true);
        player->UpdateSpeed(MOVE_FLIGHT, true);
#else
        (void)player;
        (void)form;
#endif
    }

    void Engine::SpeedOff(Player* player)
    {
#ifdef COA_FORM_SPEED
        player->SetFormSpeedRate(MOVE_RUN, 1.0f);
        player->SetFormSpeedRate(MOVE_FLIGHT, 1.0f);
        player->UpdateSpeed(MOVE_RUN, true);
        player->UpdateSpeed(MOVE_FLIGHT, true);
#else
        (void)player;
#endif
    }

    // The form's weapons decide which hands swing, in both modes (core-weapon-override.patch).
    // Set before anything applies a form weapon; cleared before anything re-adds a real one.
    void Engine::WeaponsOn(Player* player, ActiveForm& form)
    {
        if (!form.HasFormWeapons())
            return;
        BuildFormItems(form);
        std::array<uint32_t, 3> weapons = FormWeapons(form.formItems);
#ifdef COA_WEAPON_OVERRIDE
        player->SetWeaponOverride(sObjectMgr->GetItemTemplate(weapons[0]), sObjectMgr->GetItemTemplate(weapons[1]),
            sObjectMgr->GetItemTemplate(weapons[2]));
#endif
        // Unleashed carries no gear stats, but its hands still swing the form's weapons.
        if (form.args.mode == Mode::Unleashed)
            for (FormItem const& item : form.formItems)
                if (item.weapon)
                    if (ItemTemplate const* proto = sObjectMgr->GetItemTemplate(item.entry))
                        player->_ApplyWeaponDamage(item.slot, proto, nullptr, true);
        player->UpdateAllCritPercentages();
    }

    void Engine::WeaponsOff(Player* player, ActiveForm& form)
    {
#ifdef COA_WEAPON_OVERRIDE
        player->ClearWeaponOverride();
#endif
        GearOff(player, form);
        if (!form.formItems.empty())
            RestoreWeapons(player, form);
        player->UpdateAllCritPercentages();
    }

    // Each op is the core's own equip maths with the level pinned to the op's level (ruling D2 b).
    void Engine::RunItemOps(Player* player, std::vector<ItemOp> const& ops)
    {
        if (ops.empty())
            return;
        uint32 level = player->GetLevel();
        for (ItemOp const& op : ops)
        {
            ItemTemplate const* proto = sObjectMgr->GetItemTemplate(op.entry);
            if (!proto)
                continue;
            player->SetUInt32Value(UNIT_FIELD_LEVEL, op.level);
            player->_ApplyItemBonuses(proto, op.slot, op.apply);
            player->SetUInt32Value(UNIT_FIELD_LEVEL, level);
            LOG_DEBUG("module", "[Shapeshifter] {} item {} slot {} at level {} {}", player->GetName(), op.entry,
                uint32(op.slot), op.level, op.apply ? "on" : "off");
        }
        player->UpdateAllStats();
    }

    // Weapon damage and swing are set, not added: after an undo, put back whatever is really held.
    void Engine::RestoreWeapons(Player* player, ActiveForm const& form)
    {
        for (uint8 slot : { SlotMainHand, SlotOffHand, SlotRanged })
        {
            Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
            WeaponAttackType attack = Player::GetAttackBySlot(slot);
            if (item && item->GetTemplate() && !item->IsBroken() && player->CanUseAttackType(attack))
            {
                player->_ApplyWeaponDamage(slot, item->GetTemplate(), nullptr, true);
                continue;
            }
            for (FormItem const& formItem : form.formItems)
                if (formItem.slot == slot && formItem.weapon)
                    if (ItemTemplate const* proto = sObjectMgr->GetItemTemplate(formItem.entry))
                        player->_ApplyWeaponDamage(slot, proto, nullptr, false);
        }
    }

    // The form's gear replaces the real gear's template stats (Balanced class-grade forms only).
    void Engine::GearOn(Player* player, ActiveForm& form)
    {
        if (!form.HasGear())
            return;
        BuildFormItems(form);
        Percentages keep(player);
        RunItemOps(player, form.ledger.Lift(RealGear(player), form.formItems, player->GetLevel()));
        keep.Restore(player);
        LOG_INFO("module", "[Shapeshifter] {} wears gear set {} ({} items, {} ledger entries)", player->GetName(),
            form.args.gearSet, form.formItems.size(), form.ledger.Entries().size());
    }

    void Engine::GearOff(Player* player, ActiveForm& form)
    {
        if (!form.ledger.Active())
            return;
        Percentages keep(player);
        RunItemOps(player, form.ledger.Undo());
        keep.Restore(player);
    }

    void Engine::ResourceOn(Player* player, ActiveForm& form)
    {
        if (form.args.resource == Resource::Default)
            return;
        Powers want = PowerOf(form.args.resource);
        form.oldPower = uint8(player->getPowerType());
        form.powerSwitched = true;
        if (player->getPowerType() != want)
            player->setPowerType(want);
        if (want == POWER_RAGE)
            player->SetPower(POWER_RAGE, 0);                  // rage starts at 0 (user call)
        else if (want == POWER_ENERGY)
            player->SetPower(POWER_ENERGY, player->GetMaxPower(POWER_ENERGY));
    }

    void Engine::ResourceOff(Player* player, ActiveForm& form)
    {
        if (!form.powerSwitched)
            return;
        // Never write the player's own pool when the types differ: every power keeps regenerating
        // or decaying in the background (ruling D4 d).
        if (uint8(player->getPowerType()) != form.oldPower)
            player->setPowerType(Powers(form.oldPower));
        form.powerSwitched = false;
    }

    // Mana forms: a pool sized from a mage's base mana at the level, and a hidden regen passive.
    void Engine::ManaOn(Player* player, ActiveForm& form)
    {
        if (!form.args.manaPct || form.args.resource != Resource::Mana)
            return;
        uint32 level = form.Balanced() ? player->GetLevel() : form.creatureLevel;
        PlayerClassLevelInfo info;
        sObjectMgr->GetPlayerClassLevelInfo(CLASS_MAGE, uint8(std::min<uint32>(std::max<uint32>(level, 1), MAX_CLASS_LEVEL)), &info);
        form.manaTarget = ManaTarget(info.basemana, form.args.manaPct);
        bool full = form.manaFlat == 0.0f;
        float pct = player->GetMaxPower(POWER_MANA) ? float(player->GetPower(POWER_MANA)) / float(player->GetMaxPower(POWER_MANA)) : 1.0f;
        if (form.manaFlat != 0.0f)
            player->HandleStatFlatModifier(UNIT_MOD_MANA, TOTAL_VALUE, form.manaFlat, false);
        form.manaFlat = FlatDelta(float(player->GetMaxPower(POWER_MANA)), float(form.manaTarget));
        player->HandleStatFlatModifier(UNIT_MOD_MANA, TOTAL_VALUE, form.manaFlat, true);
        player->SetPower(POWER_MANA, full ? player->GetMaxPower(POWER_MANA) : uint32(float(player->GetMaxPower(POWER_MANA)) * pct));

        form.regenAmount = ManaRegenAmount(form.manaTarget, form.args.manaRegenPermille);
        Aura* regen = player->GetAura(ManaRegenPassive);
        if (!regen)
            regen = player->AddAura(ManaRegenPassive, player);
        if (regen && regen->GetEffect(0))
            regen->GetEffect(0)->ChangeAmount(form.regenAmount);
    }

    void Engine::ManaOff(Player* player, ActiveForm& form)
    {
        player->RemoveAurasDueToSpell(ManaRegenPassive);
        form.regenAmount = 0;
        if (form.manaFlat == 0.0f)
            return;
        float pct = player->GetMaxPower(POWER_MANA) ? float(player->GetPower(POWER_MANA)) / float(player->GetMaxPower(POWER_MANA)) : 1.0f;
        player->HandleStatFlatModifier(UNIT_MOD_MANA, TOTAL_VALUE, form.manaFlat, false);
        player->SetPower(POWER_MANA, uint32(float(player->GetMaxPower(POWER_MANA)) * pct));
        form.manaFlat = 0.0f;
    }

    void Engine::Revert(Player* player, RevertReason reason)
    {
        ActiveForm form;
        {
            std::lock_guard<std::mutex> guard(_lock);
            auto it = _active.find(player->GetGUID());
            if (it == _active.end())
                return;
            form = std::move(it->second);
            _active.erase(it);
            _leftovers.erase(player->GetGUID().GetCounter());
            _count.store(uint32(_active.size()));
        }

        if (reason == RevertReason::Death && form.args.soundDeath)
            player->PlayDirectSound(form.args.soundDeath);

        DismissSummons(player);

        // A logout saves next: no form cooldown may reach the character (ruling change 10).
        if (reason == RevertReason::Logout)
        {
            std::vector<uint32> families = form.args.kit;
            if (auto it = _stances.find(form.args.gearSet); it != _stances.end())
                for (StanceRow const& row : it->second)
                    for (uint32 k : row.abilities)
                        families.push_back(FamilyBase(k));
            for (uint32 id : families)
                if (IsClassGrade(id))
                    for (uint32 offset = 0; offset <= UnleashedOffset; ++offset)
                        player->RemoveSpellCooldown(id + offset);
        }

        // Damage taken in the form carries over (user call, 2026-09-23).
        float healthPct = player->GetHealthPct();
        WeaponsOff(player, form);
        if (!form.lookOnly)
            SpeedOff(player);
        ManaOff(player, form);
        ResourceOff(player, form);
        StanceSpellsOff(player, form);
        UnlearnKit(player, form);
        if (form.healthFlat != 0.0f)
            player->HandleStatFlatModifier(UNIT_MOD_HEALTH, TOTAL_VALUE, form.healthFlat, false);
        if (form.armorFlat != 0.0f)
            player->HandleStatFlatModifier(UNIT_MOD_ARMOR, TOTAL_VALUE, form.armorFlat, false);
        if (player->IsAlive())
            player->SetHealth(std::max<uint32>(1, uint32(float(player->GetMaxHealth()) * healthPct / 100.0f)));

        if (form.args.fly && !form.lookOnly)
        {
            if (player->GetByteValue(UNIT_FIELD_BYTES_1, UNIT_BYTES_1_OFFSET_ANIM_TIER) == UNIT_BYTE1_FLAG_FLY)
                player->SetByteValue(UNIT_FIELD_BYTES_1, UNIT_BYTES_1_OFFSET_ANIM_TIER, UNIT_BYTE1_FLAG_GROUND);
            bool airborne = player->IsFlying();
            bool keep = form.gmFly || player->HasFlyAura() || player->HasIncreaseMountedFlightSpeedAura();
            player->SetCanFly(keep);
            if (airborne && !keep && (reason == RevertReason::Command || reason == RevertReason::Replace))
                player->AddAura(SPELL_SLOW_FALL, player);
        }

        if (form.realLevel)
        {
            {
                std::lock_guard<std::mutex> guard(_lock);
                if (_levelRestore.erase(player->GetGUID()))
                    _restoreCount.fetch_sub(1, std::memory_order_relaxed);
            }
            player->SetLevel(form.realLevel, true);
        }

        player->RestoreDisplayId();
        player->RecalculateObjectScale();
        KeepGender(player);
        HandsOff(player);

        NameOverride::Clear(player->GetGUID());
        PushName(player, player->GetName());

        CharacterDatabase.Execute("DELETE FROM shapeshifter_active WHERE guid = {}", player->GetGUID().GetCounter());
        if (form.args.visualKit && reason != RevertReason::Logout && reason != RevertReason::Replace)
            player->SendPlaySpellVisual(form.args.visualKit);

        LOG_INFO("module", "[Shapeshifter] {} is no longer {} ({})", player->GetName(), form.name, ReasonWord(reason));
        if (reason != RevertReason::Logout && reason != RevertReason::Replace)
            SendAddon(player, FormatOff(ReasonWord(reason)));
    }

    // Any level change (GiveLevel, .character level, .reset level): gear and mana follow at once,
    // spell bands swap out of combat (ruling D2 c, change 7).
    void Engine::OnLevelChanged(Player* player)
    {
        ReassertScale(player);
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (!copy || copy->lookOnly)
            return;
        ActiveForm& form = *copy;
        if (form.realLevel)
        {
            // A level command while the level is the form's sets the level the player returns to.
            form.realLevel = player->GetLevel();
            player->SetLevel(uint8(UnleashedLevel(form.creatureLevel)), true);
        }
        if (form.ledger.Active())
        {
            Percentages keep(player);
            RunItemOps(player, form.ledger.Relevel(RealGear(player), form.formItems, player->GetLevel()));
            keep.Restore(player);
        }
        ManaOn(player, form);
        bool swapped = false;
        if (form.Balanced() && form.ClassGrade() && BandOf(player->GetLevel()) != form.band)
        {
            if (player->IsInCombat())
                form.pendingBand = true;
            else
            {
                SwapBand(player, form);
                swapped = true;
            }
        }
        Store(player->GetGUID(), form);
        ReassertForm(player);
        if (form.args.mode == Mode::Unleashed && form.HasFormWeapons())
            if (std::optional<ActiveForm> again = Copy(player->GetGUID()))
            {
                UpdateMeleeScale(player, *again);          // the form's weapons scale with level
                Store(player->GetGUID(), *again);
            }
        if (swapped)
            SendState(player);
    }

    void Engine::OnLeaveCombat(Player* player)
    {
        if (!AnyActive())
            return;
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (!copy || !copy->pendingBand)
            return;
        SwapBand(player, *copy);
        Store(player->GetGUID(), *copy);
        SendState(player);
    }

    // Shapeshift auras and .reset run InitDataForForm, which resets the power type and swing
    // speeds: put the form's back (ruling D2 h).
    void Engine::ReassertForm(Player* player)
    {
        static thread_local bool busy = false;
        if (busy || !AnyActive())
            return;
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (!copy || copy->lookOnly)
            return;
        busy = true;
        ActiveForm& form = *copy;
        if (form.powerSwitched)
        {
            Powers want = PowerOf(form.args.resource);
            if (player->getPowerType() != want)
            {
                uint32 value = player->GetPower(want);
                player->setPowerType(want);
                player->SetPower(want, value);
            }
        }
        for (FormItem const& item : form.formItems)
            if (item.weapon)
                if (ItemTemplate const* proto = sObjectMgr->GetItemTemplate(item.entry))
                    player->_ApplyWeaponDamage(item.slot, proto, nullptr, true);
        busy = false;
    }

    void Engine::SendState(Player* player)
    {
        std::optional<ActiveForm> form = Copy(player->GetGUID());
        if (form)
            SendOn(player, *form);
        else
            SendAddon(player, FormatOff("status"));
    }

    void Engine::SendError(Player* player, std::string const& code, std::string const& text)
    {
        SendAddon(player, FormatError(code, text));
    }

    // The menu's size slider: change the current form's size and nothing else (no revert, no
    // relearning), then report the new state so the addon's slider and bars agree.
    std::string Engine::Resize(Player* player, uint32 sizePct)
    {
        std::optional<ActiveForm> speed;       // copied out under the lock, applied after it
        std::optional<ActiveForm> shown;
        {
            std::lock_guard<std::mutex> guard(_lock);
            auto it = _active.find(player->GetGUID());
            if (it == _active.end())
                return "You are not transformed.";
            ActiveForm& form = it->second;
            if (form.args.sizePct == sizePct)
                return "";
            form.scale = form.scale / float(form.args.sizePct) * float(sizePct);
            form.args.sizePct = sizePct;
            form.runRate = FormRunRate(form.runCreature, HeightYards(form.args));
            shown = form;
            if (!form.lookOnly)
                speed = form;
        }
        if (speed)
            SpeedOn(player, *speed);
        ReassertScale(player);
        SendOn(player, *shown);
        return "";
    }

    // The menu preview's puppet (user, 2026-09-24): a plain creature under the ground below the
    // player, visible to them only, wearing the picked form's model, handed to their client as the
    // boss1 unit so the preview draws it as the world does (a model frame drew humanoid NPCs as a
    // white body). Boss units belong to encounters inside instances, so there is no puppet there.
    static constexpr uint32 PuppetCarrier = 721;            // Rabbit: no script, no AI of its own
    static constexpr uint32 PuppetLifeMs = 10 * MINUTE * IN_MILLISECONDS;
    static constexpr float PuppetReach = 40.0f;             // farther than this, summon a new one
    static constexpr uint32 EncounterEngage = 0, EncounterDisengage = 1;   // EncounterFrameType

    // One field of the player's own object, told to their client only: the server keeps its value,
    // and no one else hears. The pet route: UNIT_FIELD_SUMMON pointing at the puppet makes it the
    // client's "pet" unit, which a model frame draws as the world does (boss1 was never taken).
    static void SendOwnGuidField(Player* player, uint16 index, ObjectGuid value)
    {
        WorldPacket data(SMSG_UPDATE_OBJECT, 64);
        data << uint32(1);                                  // one block
        data << uint8(UPDATETYPE_VALUES);
        data << player->GetPackGUID();
        UpdateMask mask;
        mask.SetCount(player->GetValuesCount());
        mask.SetBit(index);
        mask.SetBit(index + 1);
        data << uint8(mask.GetBlockCount());
        mask.AppendToPacket(&data);
        data << uint32(value.GetRawValue() & 0xFFFFFFFF);
        data << uint32(value.GetRawValue() >> 32);
        player->SendDirectMessage(&data);
    }

    static void SendEncounterUnit(Player* player, uint32 type, Unit* unit)
    {
        WorldPacket data(SMSG_UPDATE_INSTANCE_ENCOUNTER_UNIT, 15);
        data << uint32(type);
        data << unit->GetPackGUID();
        data << uint8(0);
        player->SendDirectMessage(&data);
    }

    void Engine::Puppet(Player* player, uint32 entry, uint32 sizePct)
    {
        Map* map = player->GetMap();
        CreatureTemplate const* info = sObjectMgr->GetCreatureTemplate(entry);
        CreatureModel const* model = info ? info->GetFirstVisibleModel() : nullptr;
        if (!map || !model || model == &CreatureModel::DefaultVisibleModel || !model->CreatureDisplayID)
        {
            PuppetOff(player);
            SendAddon(player, FormatPuppet(0, ""));
            return;
        }

        ObjectGuid known;
        {
            std::lock_guard<std::mutex> guard(_lock);
            auto it = _puppets.find(player->GetGUID());
            if (it != _puppets.end())
                known = it->second;
        }
        Creature* puppet = known ? ObjectAccessor::GetCreature(*player, known) : nullptr;
        if (known && (!puppet || !puppet->IsInWorld() || !puppet->IsInDist2d(player, PuppetReach)))
        {
            PuppetOff(player);
            puppet = nullptr;
        }
        if (!puppet)
        {
            float ground = map->GetHeight(player->GetPhaseMask(), player->GetPositionX(), player->GetPositionY(),
                player->GetPositionZ());
            Position pos(player->GetPositionX(), player->GetPositionY(), PuppetZ(player->GetPositionZ(), ground), 0.0f);
            TempSummon* summon = player->SummonCreature(PuppetCarrier, pos, TEMPSUMMON_TIMED_DESPAWN, PuppetLifeMs,
                0, nullptr, true);
            if (!summon)
            {
                SendAddon(player, FormatPuppet(0, ""));
                return;
            }
            summon->AIM_Initialize(new NullCreatureAI(summon));
            summon->SetReactState(REACT_PASSIVE);
            summon->SetFaction(35);                             // friendly to all
            summon->SetUnitFlag(UNIT_FLAG_NON_ATTACKABLE | UNIT_FLAG_NOT_SELECTABLE);
            summon->SetImmuneToAll(true);
            summon->SetDisableGravity(true);
            summon->SetControlled(true, UNIT_STATE_ROOT);
            {
                std::lock_guard<std::mutex> guard(_lock);
                _puppets[player->GetGUID()] = summon->GetGUID();
            }
            puppet = summon;
        }
        puppet->SetDisplayId(model->CreatureDisplayID,
            (model->DisplayScale > 0.0f ? model->DisplayScale : 1.0f) * float(sizePct) / 100.0f);
        // The pet route unless the player really has a pet, charm or minion there; boss1 otherwise
        // (outside instances only: there the boss units are the encounter's).
        bool petRoute = player->GetGuidValue(UNIT_FIELD_SUMMON).IsEmpty();
        if (petRoute)
            SendOwnGuidField(player, UNIT_FIELD_SUMMON, puppet->GetGUID());
        else if (!map->Instanceable())
            SendEncounterUnit(player, EncounterEngage, puppet);
        else
        {
            PuppetOff(player);
            SendAddon(player, FormatPuppet(0, ""));
            return;
        }
        LOG_INFO("module", "[Shapeshifter] puppet for {}: entry {}, {}, at client {}", player->GetName(), entry,
            petRoute ? "pet" : "boss1", player->HaveAtClient(puppet) ? "yes" : "not yet");
        SendAddon(player, FormatPuppet(entry, petRoute ? "pet" : "boss"));
    }

    void Engine::PuppetOff(Player* player)
    {
        ObjectGuid known;
        {
            std::lock_guard<std::mutex> guard(_lock);
            auto it = _puppets.find(player->GetGUID());
            if (it == _puppets.end())
                return;
            known = it->second;
            _puppets.erase(it);
        }
        // The client's pet goes back to the server's real value, whichever route was used.
        SendOwnGuidField(player, UNIT_FIELD_SUMMON, player->GetGuidValue(UNIT_FIELD_SUMMON));
        if (Creature* puppet = ObjectAccessor::GetCreature(*player, known))
        {
            if (!player->GetMap()->Instanceable())
                SendEncounterUnit(player, EncounterDisengage, puppet);
            puppet->DespawnOrUnsummon();
        }
    }

    void Engine::SendCaps(Player* player)
    {
        SendAddon(player, FormatCaps(sSpellMgr->GetSpellInfo(ManaRegenPassive) != nullptr));
    }

    // The catalogue's 3D preview can only draw a creature the client has cached, and this client
    // has no SetDisplayInfo: answer the query it never sent, through the core's own handler.
    void Engine::Prime(Player* player, std::vector<uint32> const& entries)
    {
        WorldSession* session = player->GetSession();
        for (uint32 entry : entries)
        {
            if (!sObjectMgr->GetCreatureTemplate(entry))
                continue;
            WorldPacket query(CMSG_CREATURE_QUERY, 4 + 8);
            query << entry << ObjectGuid::Empty;
            session->HandleCreatureQueryOpcode(query);
        }
    }

    // For `.shapeshifter status`: everything the engine holds for this player (ruling change 11).
    std::string Engine::Describe(Player* player)
    {
        std::optional<ActiveForm> copy = Copy(player->GetGUID());
        if (!copy)
            return "Shapeshifter: not transformed.";
        ActiveForm const& form = *copy;
        std::string out = "Shapeshifter: " + form.name + (form.lookOnly ? " (look only)" : "")
            + (form.Balanced() ? ", balanced" : ", unleashed") + ", level " + std::to_string(uint32(player->GetLevel()))
            + (form.realLevel ? " (own " + std::to_string(uint32(form.realLevel)) + ")" : "")
            + ", band " + std::to_string(form.band)
            + (form.pendingBand ? " (swap pending)" : "") + ", power type " + std::to_string(uint32(player->getPowerType()))
            + (form.powerSwitched ? " (switched from " + std::to_string(uint32(form.oldPower)) + ")" : "")
            + ", mana delta " + std::to_string(int32(form.manaFlat)) + ", regen " + std::to_string(form.regenAmount)
            + ", kit " + JoinIds(form.mappedKit);
        std::array<uint32_t, 3> weapons = FormWeapons(form.formItems);
        out += "\n  form weapons: main " + std::to_string(weapons[0]) + ", off " + std::to_string(weapons[1])
            + ", ranged " + std::to_string(weapons[2]);
#ifndef COA_WEAPON_OVERRIDE
        out += " (core patch missing: hands swing the real weapons)";
#endif
        for (LedgerEntry const& entry : form.ledger.Entries())
            out += "\n  ledger: slot " + std::to_string(uint32(entry.slot)) + " item " + std::to_string(entry.entry)
                + (entry.form ? " (form, on)" : " (real, off)") + " at level " + std::to_string(entry.level);
        return out;
    }

    // At startup: which characters still have a row, so logins only query when there is something to strip.
    void Engine::LoadLeftovers()
    {
        std::lock_guard<std::mutex> guard(_lock);
        _leftovers.clear();
        if (QueryResult result = CharacterDatabase.Query("SELECT guid FROM shapeshifter_active"))
        {
            do
            {
                _leftovers.insert((*result)[0].Get<uint32>());
            } while (result->NextRow());
        }
        LOG_INFO("server.loading", "[Shapeshifter] {} character(s) to clean up at next login", _leftovers.size());
    }

    // A login is never transformed: drop any stale state, and strip auras a crash may have left saved.
    void Engine::OnLogin(Player* player)
    {
        bool strip = false;
        {
            std::lock_guard<std::mutex> guard(_lock);
            if (_active.erase(player->GetGUID()))
                _count.store(uint32(_active.size()));
            if (_levelRestore.erase(player->GetGUID()))
                _restoreCount.fetch_sub(1, std::memory_order_relaxed);
            strip = _leftovers.erase(player->GetGUID().GetCounter()) > 0;
        }
        NameOverride::Clear(player->GetGUID());
        if (!strip)
            return;

        QueryResult result = CharacterDatabase.Query("SELECT auras FROM shapeshifter_active WHERE guid = {}",
            player->GetGUID().GetCounter());
        if (result)
        {
            std::string auras = (*result)[0].Get<std::string>();
            std::vector<uint32> ids;
            if (Detail::NumberList(auras.empty() ? std::string_view("-") : std::string_view(auras), ids))
                for (uint32 id : ids)
                    player->RemoveAurasDueToSpell(id);
            LOG_INFO("module", "[Shapeshifter] stripped leftover form auras ({}) from {}", auras, player->GetName());
        }
        CharacterDatabase.Execute("DELETE FROM shapeshifter_active WHERE guid = {}", player->GetGUID().GetCounter());
    }

    // A map change can reset movement flags; keep a flying form flying.
    void Engine::OnMapChanged(Player* player)
    {
        bool fly = false;
        {
            std::lock_guard<std::mutex> guard(_lock);
            auto it = _active.find(player->GetGUID());
            fly = it != _active.end() && it->second.args.fly && !it->second.lookOnly;
        }
        if (fly)
            player->SetCanFly(true);
    }

    // Scale auras and level ups reset the object scale; put the form's size back on top of them.
    void Engine::ReassertScale(Player* player)
    {
        float scale = 0.0f;
        {
            std::lock_guard<std::mutex> guard(_lock);
            auto it = _active.find(player->GetGUID());
            if (it == _active.end())
                return;
            scale = it->second.scale;
        }
        int32 mods = player->GetTotalAuraModifier(SPELL_AURA_MOD_SCALE) + player->GetTotalAuraModifier(SPELL_AURA_MOD_SCALE_2);
        player->SetObjectScale(std::max(scale * (1.0f + float(mods) / 100.0f), 0.01f));
    }
}
