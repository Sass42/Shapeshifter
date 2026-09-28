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

-- The boss bar's slots (slot -> spell id): the player's layout where its spells are still in the
-- kit, then every other kit spell in the first free slot, in kit order.
function CP.ArrangeBar(kit, layout, slots)
    local out, placed = {}, {}
    local inKit = {}
    for _, id in ipairs(kit) do
        inKit[id] = true
    end
    for slot, id in pairs(layout or {}) do
        if inKit[id] and not placed[id] and slot >= 1 and slot <= slots and not out[slot] then
            out[slot], placed[id] = id, true
        end
    end
    local free = 1
    for _, id in ipairs(kit) do
        if not placed[id] then
            while out[free] do
                free = free + 1
            end
            if free > slots then
                break
            end
            out[free], placed[id] = id, true
        end
    end
    return out
end
