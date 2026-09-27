-- Shapeshift cast plan: how one boss-bar button casts its kit spell. Pure (no WoW API).
--
-- Casting by name is the normal secure-button way, but a kit spell can share its name with one
-- of the player's own spells (a creature's Fireball against a mage's), and casting by name then
-- picks the player's own, which the server refuses while transformed. On a clash the button
-- casts by spell ID when the client has CastSpellByID, else by the kit spell's spellbook slot.
-- Wave 0 checks which of these the 3.3.5 client accepts from a secure macro.

Shapeshift = Shapeshift or {}
local CP = {}
Shapeshift.CastPlan = CP

-- spell = { id, name }; info = { ownNames = set of the player's own spell names,
-- hasCastByID = bool, slot = spellbook index of the kit spell or nil }
function CP.Choose(spell, info)
    if not info.ownNames[spell.name] then
        return { type = "spell", spell = spell.name }
    end
    if info.hasCastByID then
        return { type = "macro", macrotext = "/run CastSpellByID(" .. spell.id .. ")" }
    end
    if info.slot then
        return { type = "macro", macrotext = "/run CastSpell(" .. info.slot .. ", \"spell\")" }
    end
    return { type = "spell", spell = spell.name }
end
