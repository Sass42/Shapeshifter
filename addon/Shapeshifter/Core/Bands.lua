-- Shapeshift bands: class-grade spell and item ids. Pure (no WoW API); the same numbers as
-- band_of in tools/shapeshift_class.py, tools/class_ids.py and BandOf/FamilyBase/GearItemId in
-- server/modules/mod-shapeshifter/src/ShapeshiftArgs.h.
--
-- Family k owns spell ids 14,000,000 + 20k: bands 0-15 (5 levels each), Unleashed 16. Gear set n
-- owns item ids 9,300,000 + 20n + slot. Class-grade kits travel to the server as "f<k>".

Shapeshift = Shapeshift or {}
local B = {}
Shapeshift.Bands = B

B.FAMILY_FIRST = 14000000
B.FAMILY_LAST = 14199999
B.FAMILY_SIZE = 20
B.MAX_FAMILY = 9999
B.BANDS = 16
B.UNLEASHED = 16
B.GEAR_FIRST = 9300000
B.GEAR_SLOTS = 20

function B.Of(level)
    level = math.floor(tonumber(level) or 1)
    if level < 1 then
        level = 1
    end
    return math.min(math.floor((level - 1) / 5), B.BANDS - 1)
end

function B.Base(k)
    return B.FAMILY_FIRST + B.FAMILY_SIZE * k
end

function B.IsClassGrade(id)
    return id >= B.FAMILY_FIRST and id <= B.FAMILY_LAST
end

-- The id a family base maps to at a level; any other id is returned unchanged.
function B.Id(base, level, balanced)
    if not B.IsClassGrade(base) then
        return base
    end
    if balanced then
        return base + B.Of(level)
    end
    return base + B.UNLEASHED
end

function B.Token(k)
    return "f" .. k
end

function B.Item(set, slot)
    return B.GEAR_FIRST + B.GEAR_SLOTS * set + slot
end
