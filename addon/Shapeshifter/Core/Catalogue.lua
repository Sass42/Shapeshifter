-- Shapeshift catalogue logic: which forms a tab lists, searching, paging, favorites, flags and
-- remembered choices. Pure (no WoW API), so tools/test_shapeshift_lua.py runs it outside the
-- client. The window in UI/Catalogue.lua only draws what this returns.

Shapeshift = Shapeshift or {}
local C = {}
Shapeshift.Catalogue = C

-- Tab order. "favorites" spans every pool; "creature" is the look-only list of every creature.
-- art: the client's own dungeon-finder artwork behind each tab (user call, 2026-09-23).
C.POOLS = {
    { key = "favorites", label = "Favorites", icon = "Interface\\Icons\\INV_Misc_Note_02", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-QuestPaper" },
    { key = "all", label = "All Forms", icon = "Interface\\Icons\\INV_Misc_Book_09", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-QuestPaper" },
    { key = "classic_raid", label = "Classic Raids", icon = "Interface\\Icons\\Achievement_Boss_Ragnaros", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-MoltenCore" },
    { key = "classic_dungeon", label = "Classic Dungeons", icon = "Interface\\Icons\\INV_Misc_Head_Gnoll_01", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-Deadmines" },
    { key = "rare", label = "Rare Elites", icon = "Interface\\Icons\\Ability_Tracking", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-QuestPaper" },
    { key = "tbc", label = "The Burning Crusade", icon = "Interface\\Icons\\Achievement_Boss_Illidan", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-BlackTemple" },
    { key = "wotlk", label = "Wrath of the Lich King", icon = "Interface\\Icons\\Achievement_Boss_LichKing", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-IcecrownCitadel" },
    { key = "archetype", label = "Archetypes", icon = "Interface\\Icons\\Spell_Shadow_SummonFelGuard", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-WailingCaverns" },
    { key = "leader", label = "Faction Leaders", icon = "Interface\\Icons\\Achievement_Leader_Thrall", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-HallsOfReflection" },
    { key = "creature", label = "Any Creature (look only)", icon = "Interface\\Icons\\INV_Misc_Spyglass_03", art = "Interface\\LFGFrame\\UI-LFG-BACKGROUND-QuestPaper" },
}

function C.PoolArt(key)
    for _, pool in ipairs(C.POOLS) do
        if pool.key == key then
            return pool.art
        end
    end
    return nil
end

function C.PoolLabel(key)
    for _, pool in ipairs(C.POOLS) do
        if pool.key == key then
            return pool.label
        end
    end
    return key
end

function C.FormKey(form)
    return "form:" .. form.id
end

function C.CreatureKey(entry)
    return "creature:" .. entry
end

-- A form's kit is live once its wave is released; later waves are look-only for now, and
-- wave 0 is the spike's and never listed.
function C.IsReleased(form, releaseWave)
    return form.wave >= 1 and form.wave <= (releaseWave or 0)
end

local function matches(text, search)
    return string.find(string.lower(text or ""), search, 1, true) ~= nil
end

local function byLevelThenLabel(a, b)
    if a.level ~= b.level then
        return a.level < b.level
    end
    return a.label < b.label
end

-- A form's shapes (user, 2026-09-24): the listed form carries `visages`, each other shape
-- `visageOf`. Shapes gives the listed form first, then its visages in order.
local function byId(forms, id)
    for _, candidate in ipairs(forms) do
        if candidate.id == id then
            return candidate
        end
    end
    return nil
end

function C.Shapes(forms, form)
    local base = form.visageOf and byId(forms, form.visageOf) or form
    local out = { base }
    for _, id in ipairs(base.visages or {}) do
        local shape = byId(forms, id)
        if shape then
            out[#out + 1] = shape
        end
    end
    return out
end

-- Archetype skins (spec 2026-09-26). An archetype's looks: its own first, then each cosmetic skin as
-- a skin form (the archetype with another model: same id, so its class-grade data still applies;
-- `as` keeps the archetype's name, level and stats on the server), then its variant forms (full forms
-- listed in `variants`, each naming it in `skinOf`). Skins never reach the stance bar: C.Shapes of a
-- skin form is just itself.
-- The cache is load-bearing: the catalogue, boss bar and sheet compare forms by identity
-- (`shape == s.form`, `CurrentForm() ~= form`), so a skin must come back as the same table.
-- Every model field is set, never nil, or the archetype's would show through __index.
local skinCache = setmetatable({}, { __mode = "k" })

function C.SkinBase(forms, form)
    if form.skinBase then
        return form.skinBase
    end
    return form.skinOf and byId(forms, form.skinOf) or form
end

function C.Skins(forms, form)
    local base = C.SkinBase(forms, form)
    local out = { base }
    if base.skins then
        local made = skinCache[base] or {}
        skinCache[base] = made
        for i, skin in ipairs(base.skins) do
            made[i] = made[i] or setmetatable({
                entry = skin.entry, as = base.as or base.entry, display = skin.display or 0,
                height = skin.height or 0, span = skin.span or 0, box = skin.box or false,
                charModel = skin.charModel or false, view = false, skinName = skin.name, skinBase = base,
                skinCreature = skin.creature,
            }, { __index = base })
            out[#out + 1] = made[i]
        end
    end
    for _, id in ipairs(base.variants or {}) do
        local variant = byId(forms, id)
        if variant then
            out[#out + 1] = variant
        end
    end
    return out
end

-- The label on a skin button: the archetype's own look is "Classic" unless it names itself.
function C.SkinLabel(base, form)
    if form == base then
        return base.skinName or "Classic"
    end
    return form.skinName or form.label
end

-- Everything a grid cell stands for: its shapes and its variants (search, favorites, the star).
function C.Members(forms, form)
    local out = C.Shapes(forms, form)
    for _, id in ipairs(form.variants or {}) do
        local variant = byId(forms, id)
        if variant then
            out[#out + 1] = variant
        end
    end
    return out
end

local function wantedBy(form, wanted)
    return wanted == "" or matches(form.label, wanted) or matches(form.name, wanted)
end

-- What clicking a grid cell opens: a variant the search found (when the cell itself does not
-- match), else the worn look if it is one of this cell's, else the look saved for it (by creature
-- entry), else the form.
function C.ShownFor(forms, form, worn, search, savedEntry)
    local wanted = string.lower(search or "")
    if wanted ~= "" and not wantedBy(form, wanted) then
        for _, id in ipairs(form.variants or {}) do
            local variant = byId(forms, id)
            if variant and wantedBy(variant, wanted) then
                return variant
            end
        end
    end
    if worn and (worn.visageOf == form.id or C.SkinBase(forms, worn) == form) then
        return worn
    end
    if savedEntry then
        for _, look in ipairs(C.Skins(forms, form)) do
            if look.entry == savedEntry then
                return look
            end
        end
    end
    return form
end

-- The shape after this one, round the cycle; nil for a form with one shape.
function C.Visage(forms, form)
    local shapes = C.Shapes(forms, form)
    if #shapes < 2 then
        return nil
    end
    for i, shape in ipairs(shapes) do
        if shape.id == form.id then
            return shapes[i % #shapes + 1]
        end
    end
    return nil
end

-- Switching shape has a cooldown so the two kits cannot be alternated to skip their cooldowns.
C.VISAGE_COOLDOWN = 10

-- Ready to switch, and the seconds left when not.
function C.SwitchReady(lastSwitch, now)
    if not lastSwitch then
        return true, 0
    end
    local left = lastSwitch + C.VISAGE_COOLDOWN - now
    if left <= 0 then
        return true, 0
    end
    return false, left
end

-- One entry per character: another shape is listed as its form, and found by its own name too.
function C.FormsFor(forms, pool, search, favorites, releaseWave)
    local wanted = string.lower(search or "")
    local out = {}
    for _, form in ipairs(forms) do
        if form.wave >= 1 and not form.visageOf and not form.skinOf then
            local shapes = (form.visages or form.variants) and C.Members(forms, form) or { form }
            local favorite, found = false, false
            for _, shape in ipairs(shapes) do
                favorite = favorite or (favorites[C.FormKey(shape)] and true or false)
                found = found or wantedBy(shape, wanted)
            end
            local inPool
            if pool == "favorites" then
                inPool = favorite
            else
                inPool = pool == "all" or form.pool == pool
            end
            if inPool and found then
                out[#out + 1] = form
            end
        end
    end
    table.sort(out, byLevelThenLabel)
    return out
end

-- ------------------------------------------------------------------ groupings (deep pass A)
-- The Group button's modes (user, 2026-09-25). `short` fits the button; `label` is the tooltip's.
C.GROUPINGS = {
    { key = "type", short = "Type", label = "Type" },
    { key = "instance", short = "Instance", label = "Dungeon/Raid" },
    { key = "zone", short = "Zone", label = "Zone" },
    { key = "expansion", short = "Expansion", label = "Expansion" },
    { key = "az", short = "A-Z", label = "A-Z" },
}

C.EXPANSIONS = { [0] = "Classic", [1] = "The Burning Crusade", [2] = "Wrath of the Lich King" }

local function groupingOf(key)
    for i, grouping in ipairs(C.GROUPINGS) do
        if grouping.key == key then
            return grouping, i
        end
    end
    return C.GROUPINGS[1], nil
end

-- The next grouping in the cycle (step 1) or the one before (step -1); an unknown key restarts.
function C.NextGrouping(key, step)
    local _, i = groupingOf(key)
    if not i then
        return "type"
    end
    return C.GROUPINGS[(i - 1 + step) % #C.GROUPINGS + 1].key
end

function C.GroupingLabel(key)
    return groupingOf(key).label
end

function C.GroupingShort(key)
    return groupingOf(key).short
end

local function headerOf(form, grouping)
    if grouping == "instance" then
        return form.instance
    elseif grouping == "zone" then
        return form.zone
    elseif grouping == "expansion" then
        return C.EXPANSIONS[form.expansion or 0]
    end
    return string.upper(string.sub(form.label, 1, 1))     -- az
end

local function byOrder(a, b)
    return a.order < b.order
end

local function byLabel(a, b)
    if a.label ~= b.label then
        return a.label < b.label
    end
    return a.entry < b.entry
end

-- forms: already filtered by C.FormsFor. Dungeon/Raid, Zone and Expansion follow the generator's
-- game order (Forms.lua `order`); A-Z goes by letter, then label; Type is one group with no header.
function C.Group(forms, grouping)
    if grouping ~= "instance" and grouping ~= "zone" and grouping ~= "expansion" and grouping ~= "az" then
        return { { header = nil, forms = forms } }
    end
    local sorted = {}
    for i, form in ipairs(forms) do
        sorted[i] = form
    end
    table.sort(sorted, grouping == "az" and byLabel or byOrder)
    local byHeader, out = {}, {}
    for _, form in ipairs(sorted) do
        local header = headerOf(form, grouping)
        if header then
            local group = byHeader[header]
            if not group then
                group = { header = header, forms = {} }
                byHeader[header] = group
                out[#out + 1] = group
            end
            group.forms[#group.forms + 1] = form
        end
    end
    if grouping == "az" then
        table.sort(out, function(a, b) return a.header < b.header end)
    end
    return out
end

-- The grid's rows: a header row before each group's icon rows of `cols` forms.
function C.Rows(groups, cols)
    local rows = {}
    for _, group in ipairs(groups) do
        if group.header then
            rows[#rows + 1] = { header = group.header }
        end
        for i = 1, #group.forms, cols do
            local row = { forms = {} }
            for j = i, math.min(i + cols - 1, #group.forms) do
                row.forms[#row.forms + 1] = group.forms[j]
            end
            rows[#rows + 1] = row
        end
    end
    return rows
end

-- `count` items from `top` (the mouse wheel moves it one row, the page buttons `count`), with top
-- clamped so the window never runs past the end; returns the slice and the clamped top.
function C.Window(list, top, count)
    top = math.min(math.max(1, top or 1), math.max(1, #list - count + 1))
    local slice = {}
    for i = top, math.min(#list, top + count - 1) do
        slice[#slice + 1] = list[i]
    end
    return slice, top
end

-- The saved tab while it still exists; Classic Raids otherwise.
function C.ValidPool(key)
    for _, pool in ipairs(C.POOLS) do
        if pool.key == key then
            return key
        end
    end
    return "classic_raid"
end

-- The grid's empty line; "" when there is something to show.
function C.EmptyText(pool, search, forms, groups)
    if #forms == 0 then
        if pool == "favorites" then
            return "No favorites yet. Select a form and press Favorite."
        elseif search ~= "" then
            return "No form matches."
        end
        return "No forms in this pool yet."
    end
    if #groups == 0 then
        return "No forms here in this grouping."
    end
    return ""
end

local function byName(a, b)
    if a.name ~= b.name then
        return a.name < b.name
    end
    return a.entry < b.entry
end

-- Creatures.lua rows are { entry, name, level, display }.
function C.SearchCreatures(creatures, text, limit)
    local wanted = string.lower(text or "")
    local out = {}
    if string.len(wanted) < 2 then
        return out
    end
    for _, row in ipairs(creatures) do
        if matches(row[2], wanted) then
            out[#out + 1] = { entry = row[1], name = row[2], level = row[3], display = row[4] }
        end
    end
    table.sort(out, byName)
    while #out > limit do
        table.remove(out)
    end
    return out
end

function C.FavoriteCreatures(creatures, favorites)
    local out = {}
    for _, row in ipairs(creatures) do
        if favorites[C.CreatureKey(row[1])] then
            out[#out + 1] = { entry = row[1], name = row[2], level = row[3], display = row[4] }
        end
    end
    table.sort(out, byName)
    return out
end

-- One page of a list, with the page number clamped; there is always at least one page.
function C.Page(list, page, perPage)
    local count = math.max(1, math.ceil(#list / perPage))
    page = math.min(math.max(1, page or 1), count)
    local slice = {}
    for i = (page - 1) * perPage + 1, math.min(#list, page * perPage) do
        slice[#slice + 1] = list[i]
    end
    return slice, count
end

function C.ToggleFavorite(db, key)
    if db.favorites[key] then
        db.favorites[key] = nil
        return false
    end
    db.favorites[key] = true
    return true
end

function C.ToggleFlag(db, entry, name, now)
    if db.flagged[entry] then
        db.flagged[entry] = nil
        return false
    end
    db.flagged[entry] = { name = name, at = now }
    return true
end

-- A form's talents: its authored ones ({ spell, rank, max }), else each passive at 1/1.
-- A form's talents; for a class-grade form (cg = its Shapeshift.ClassGrade entry) each passive
-- shows as the band the player's level uses (or the Unleashed row).
local function Mapped(spell, cg, level, balanced)
    local k = cg and cg.families and cg.families[spell]
    if not k or not Shapeshift.Bands then
        return spell
    end
    return Shapeshift.Bands.Id(Shapeshift.Bands.Base(k), level, balanced ~= false)
end
C.Mapped = Mapped   -- the catalogue's ability row shows the same spell the bar gets (own icon and name)

function C.TalentsFor(form, cg, level, balanced)
    local out = {}
    if form.talents and #form.talents > 0 then
        for _, talent in ipairs(form.talents) do
            out[#out + 1] = { spell = talent.spell, rank = talent.rank, max = talent.max }
        end
        return out
    end
    for _, spell in ipairs(form.passives or {}) do
        out[#out + 1] = { spell = Mapped(spell, cg, level, balanced), rank = 1, max = 1 }
    end
    -- The form's own fixed talents (user call, 2026-09-23): shown by name, icon and text.
    for _, info in ipairs(form.talentInfo or {}) do
        out[#out + 1] = { name = info.name, icon = info.icon, text = info.text, rank = 1, max = 1 }
    end
    return out
end

function C.Choice(db, key)
    local saved = db.lastChoice[key]
    if saved then
        return { mode = saved.mode, size = saved.size }
    end
    return { mode = "balanced", size = 100 }
end

function C.Remember(db, key, mode, size)
    db.lastChoice[key] = { mode = mode, size = size }
end
