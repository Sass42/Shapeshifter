-- Shapeshift protocol: the pure half of the addon. Builds the `.shapeshift` chat commands,
-- parses the server's addon whispers, and parses the slash command. No WoW API is used here,
-- so tools/test_shapeshift_lua.py can run all of it outside the client.

Shapeshift = Shapeshift or {}
local P = {}
Shapeshift.Protocol = P

P.PREFIX = "SHSH"
P.MAX_COMMAND = 255
P.REVERT = ".shapeshifter revert"
P.STATUS = ".shapeshifter status"

-- forms.json profile -> the word the server command uses
local PROFILE_WORD = { tank = "tank", bruiser = "bruiser", caster = "caster", glass_cannon = "glass" }

local function csv(list)
    if not list or #list == 0 then
        return "-"
    end
    local out = {}
    for i, value in ipairs(list) do
        out[i] = tostring(value)
    end
    return table.concat(out, ",")
end

local function split(text, sep)
    local out = {}
    local start = 1
    while true do
        local at = string.find(text, sep, start, true)
        if not at then
            out[#out + 1] = string.sub(text, start)
            return out
        end
        out[#out + 1] = string.sub(text, start, at - 1)
        start = at + 1
    end
end

local function numbers(text)
    local out = {}
    if text == "-" or text == "" then
        return out
    end
    for _, part in ipairs(split(text, ",")) do
        local value = tonumber(part)
        if not value then
            return nil
        end
        out[#out + 1] = value
    end
    return out
end

-- The largest size the server takes: 200% once it says "size200" (user, 2026-09-24), else 100%.
P.MAX_SIZE = 100

function P.ClampSize(pct)
    pct = tonumber(pct) or 100
    pct = math.floor(pct + 0.5)
    if pct < 10 then
        return 10
    elseif pct > P.MAX_SIZE then
        return P.MAX_SIZE
    end
    return pct
end

-- Power type numbers the server's res= flag takes.
local RESOURCE_NUMBER = { mana = 0, rage = 1, energy = 3 }

-- A class-grade form's kit and passives travel as f<k> (family k); anything without a family,
-- or everything when the spells subsystem is off, goes as its plain id.
-- summons: the form's summon abilities (deep pass B3). They exist only as class-grade data: sent
-- raw, their template spell would call its own creature, so without a family they are left out.
local function tokens(list, cg, on, summons)
    local out = {}
    for _, id in ipairs(list or {}) do
        local k = on and cg and cg.families and cg.families[id]
        if k then
            out[#out + 1] = "f" .. k
        elseif not (summons and summons[id]) then
            out[#out + 1] = tostring(id)
        end
    end
    if #out == 0 then
        return "-"
    end
    return table.concat(out, ",")
end

-- A form's class-grade entry, unless the server said it lacks the class-grade data (CAPS nocg:
-- no player-grade spell rows, as on a server that never ran the class-grade build). A server that
-- never says nocg keeps class-grade on.
function P.ClassGradeFor(cg, caps)
    if caps and caps.nocg then
        return nil
    end
    return cg
end

-- Must stay identical to worst_case_command in tools/gen_shapeshift.py.
-- cg: the form's Shapeshift.ClassGrade entry, or nil; toggles: ShapeshifterDB.classGrade, where
-- false switches a subsystem off (ruling change 12: any runtime failure is an addon toggle).
-- caps: what the server said it understands; ht= (the form's speed) only goes to a "speed" server.
-- A weapon stance of the current form (deep pass B2); sent only to a server whose CAPS say `stance`.
function P.BuildStance(n)
    return ".shapeshifter stance " .. n
end

function P.BuildApply(form, mode, sizePct, cg, toggles, caps)
    toggles = toggles or {}
    cg = P.ClassGradeFor(cg, caps)
    local flags = {}
    if form.flies then
        flags[#flags + 1] = "fly=1"
    end
    if form.visualKit and form.visualKit > 0 then
        flags[#flags + 1] = "vis=" .. form.visualKit
    end
    if form.soundTransform and form.soundTransform > 0 then
        flags[#flags + 1] = "st=" .. form.soundTransform
    end
    if form.soundDeath and form.soundDeath > 0 then
        flags[#flags + 1] = "sd=" .. form.soundDeath
    end
    if form.as and form.as > 0 then            -- a stand-in's model, the real creature's name and stats
        flags[#flags + 1] = "as=" .. form.as
    end
    if caps and caps.speed and form.height and form.height > 0 then
        flags[#flags + 1] = "ht=" .. math.min(math.floor(form.height * 10 + 0.5), 20000)
    end
    if cg then
        local resource = RESOURCE_NUMBER[cg.resource]
        if resource and toggles.resource ~= false then
            flags[#flags + 1] = "res=" .. resource
        end
        if cg.gearSet and toggles.gear ~= false then
            flags[#flags + 1] = "gs=" .. cg.gearSet
        end
        if cg.resource == "mana" and cg.manaPct and toggles.mana ~= false then
            flags[#flags + 1] = "mp=" .. cg.manaPct
            flags[#flags + 1] = "mr=" .. (cg.manaRegen or 20)
        end
    end
    local spells = toggles.spells ~= false
    local passives = tokens(form.passives, cg, spells)
    if spells and cg and cg.talents and #cg.talents > 0 then       -- talent families ride as passives
        local talents = {}
        for i, k in ipairs(cg.talents) do
            talents[i] = "f" .. k
        end
        passives = (passives == "-" and "" or passives .. ",") .. table.concat(talents, ",")
    end
    local command = string.format(".shapeshifter apply %d %s %d %s %s %s %s",
        form.entry,
        mode == "unleashed" and "u" or "b",
        P.ClampSize(sizePct),
        PROFILE_WORD[form.profile] or "bruiser",
        tokens(form.kit, cg, spells, form.summons),
        passives,
        #flags > 0 and table.concat(flags, ",") or "-")
    if #command > P.MAX_COMMAND then
        return nil, "That form's command is too long for one chat line."
    end
    return command
end

function P.BuildLook(entry, sizePct)
    return string.format(".shapeshifter look %d %d", entry, P.ClampSize(sizePct))
end

-- The menu preview's private puppet (server caps word "puppet"); "off" drops it.
-- The puppet may be smaller than a form: down to 1% on a "puppetsize" server, else 10%.
P.PUPPET_MIN = 10

function P.BuildPuppet(entry, sizePct)
    if not entry then
        return ".shapeshifter puppet off"
    end
    local pct = math.floor((tonumber(sizePct) or 100) + 0.5)
    pct = math.max(P.PUPPET_MIN, math.min(P.MAX_SIZE, pct))
    return string.format(".shapeshifter puppet %d %d", entry, pct)
end

-- The preview frame scales a drawn puppet so its bigger dimension is about Hogger's two yards.
P.PUPPET_FIT_YARDS = 2.2

function P.BuildSize(sizePct)
    return string.format(".shapeshifter size %d", P.ClampSize(sizePct))
end

function P.ParseReply(msg)
    local parts = split(msg or "", ";")
    local kind = parts[1]
    if kind == "ON" and #parts >= 7 then
        local entry, size, kit = tonumber(parts[2]), tonumber(parts[4]), numbers(parts[5])
        if not entry or not size or not kit then
            return nil
        end
        return {
            kind = "on",
            entry = entry,
            mode = parts[3] == "u" and "unleashed" or "balanced",
            size = size,
            kit = kit,
            look = parts[6] == "1",
            -- the name is last so a stray ';' in it cannot shift the fields before it
            name = table.concat(parts, ";", 7),
        }
    elseif kind == "OFF" and parts[2] then
        return { kind = "off", reason = parts[2] }
    elseif kind == "ERR" and parts[2] then
        return { kind = "err", code = parts[2], text = table.concat(parts, ";", 3) }
    elseif kind == "STANCE" then
        -- STANCE;<n>;<ids or ->: a stanced form's current weapon stance and its own abilities (B2)
        local stance, kit = tonumber(parts[2]), numbers(parts[3] or "")
        if not stance or not kit then
            return nil
        end
        return { kind = "stance", stance = stance, kit = kit }
    elseif kind == "PUPPET" then
        -- PUPPET;on;<entry>;<pet|boss>: the preview may draw that unit as the creature; PUPPET;off: none
        local on = parts[2] == "on"
        return { kind = "puppet", entry = on and tonumber(parts[3]) or nil,
                 unit = on and (parts[4] == "pet" and "pet" or "boss1") or nil }
    elseif kind == "CAPS" then
        local caps = {}
        for _, word in ipairs(split(parts[2] or "", ",")) do
            if word ~= "" then
                caps[word] = true
            end
        end
        return { kind = "caps", caps = caps }
    end
    return nil
end

-- The server takes at most 40 entries per prime line (ShapeshiftArgs.h MaxPrime), and every
-- line must fit one chat message.
P.MAX_PRIME = 40
local PRIME = ".shapeshifter prime "

function P.BuildPrime(entries)
    local commands, chunk, length = {}, {}, #PRIME
    local function flush()
        if #chunk > 0 then
            commands[#commands + 1] = PRIME .. table.concat(chunk, ",")
            chunk, length = {}, #PRIME
        end
    end
    for _, entry in ipairs(entries) do
        local text = tostring(entry)
        if #chunk == P.MAX_PRIME or length + #text + 1 > P.MAX_COMMAND then
            flush()
        end
        chunk[#chunk + 1] = text
        length = length + #text + (#chunk > 1 and 1 or 0)
    end
    flush()
    return commands
end

function P.ParseSlash(input)
    local words = {}
    for word in string.gmatch(input or "", "%S+") do
        words[#words + 1] = word
    end
    local cmd = string.lower(words[1] or "")
    local args = {}
    for i = 2, #words do
        args[#args + 1] = words[i]
    end
    return { cmd = cmd, args = args }
end

function P.DefaultDB(db)
    db.favorites = db.favorites or {}
    db.flagged = db.flagged or {}
    db.minimapAngle = db.minimapAngle or 200
    db.lastChoice = db.lastChoice or {}
    db.skins = db.skins or {}           -- archetype id -> the chosen look's creature entry
    db.grouping = db.grouping or "type"
    db.classGrade = db.classGrade or {}
    for _, key in ipairs({ "spells", "resource", "gear", "mana" }) do
        if db.classGrade[key] == nil then
            db.classGrade[key] = true
        end
    end
    return db
end
