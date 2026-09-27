-- Shapeshift core: holds the current form, sends commands, listens for the server's replies
-- and owns the /ss slash command. The pure parts are in Protocol.lua.
--
-- Commands travel as /say, so on a character that is not a GM (or a server without
-- mod-shapeshifter) they would be said aloud. The addon therefore sends one status probe per
-- character and nothing else until the server has answered on that character.

local P = Shapeshift.Protocol

Shapeshift.state = { active = false }
Shapeshift.caps = {}        -- from the server's CAPS reply to `.shapeshift status`
local listeners = {}
local statusAsked = false

local function Print(text)
    DEFAULT_CHAT_FRAME:AddMessage("|cffd4a017Shapeshifter|r: " .. text)
end
Shapeshift.Print = Print

function Shapeshift.ShowError(text)
    UIErrorsFrame:AddMessage(text, 1.0, 0.1, 0.1, 1.0)
end

-- GM commands travel as chat, exactly as if typed.
function Shapeshift.Send(command)
    SendChatMessage(command, "SAY")
end

-- True once the server has answered on this character (a GM with mod-shapeshifter).
function Shapeshift.ServerReady()
    return ShapeshifterCharDB ~= nil and ShapeshifterCharDB.confirmed == true
end

Shapeshift.NOT_READY = "Shapeshifter has not heard from the server on this character (GM and mod-shapeshifter needed). Try /ss status."

local function SendIfReady(command)
    if not Shapeshift.ServerReady() then
        Shapeshift.ShowError(Shapeshift.NOT_READY)
        return false
    end
    Shapeshift.Send(command)
    return true
end

-- The form's class-grade entry, or nil on a server without the class-grade data (CAPS nocg).
function Shapeshift.ClassGradeFor(form)
    return P.ClassGradeFor(Shapeshift.ClassGrade and Shapeshift.ClassGrade[form.id], Shapeshift.caps)
end

function Shapeshift.FormById(id)
    for _, form in ipairs(Shapeshift.Forms) do
        if form.id == id then
            return form
        end
    end
    return nil
end

function Shapeshift.Apply(form, mode, sizePct)
    if InCombatLockdown() then
        Shapeshift.ShowError("You can't transform in combat.")
        return
    end
    Shapeshift.appliedForm = form       -- two shapes may share a stand-in model entry; a skin form is not in Forms
    local classGrade = Shapeshift.ClassGradeFor(form)
    local command, err = P.BuildApply(form, mode, sizePct, classGrade, ShapeshifterDB and ShapeshifterDB.classGrade,
        Shapeshift.caps)
    if not command then
        Shapeshift.ShowError(err)
        return
    end
    SendIfReady(command)
end

function Shapeshift.Look(entry, sizePct)
    if InCombatLockdown() then
        Shapeshift.ShowError("You can't transform in combat.")
        return
    end
    SendIfReady(P.BuildLook(entry, sizePct))
end

function Shapeshift.Revert()
    SendIfReady(P.REVERT)
end

-- Key Bindings menu entry for the switch below (Bindings.xml).
BINDING_HEADER_SHAPESHIFT = "Shapeshifter"
BINDING_NAME_SHAPESHIFT_SWITCH_VISAGE = "Change to the form's next shape"

-- A form's shapes (user, 2026-09-24): from one, become another in place, keeping mode and
-- size. The server's replace path keeps your health; a 10 second cooldown stops the two kits being
-- alternated to skip their cooldowns. Out of combat only: the boss bar cannot be rebuilt in combat.
Shapeshift.visageSwitchedAt = nil

-- target: the shape to become (a stance bar button); nil for the next one round the cycle.
function Shapeshift.SwitchVisage(target)
    local form = Shapeshift.CurrentForm()
    local other = target or (form and Shapeshift.Catalogue.Visage(Shapeshift.Forms, form))
    if not form or not other or other == form then
        return
    end
    if InCombatLockdown() then
        Shapeshift.ShowError("You can't change shape in combat.")
        return
    end
    local ready, left = Shapeshift.Catalogue.SwitchReady(Shapeshift.visageSwitchedAt, GetTime())
    if not ready then
        Shapeshift.ShowError(string.format("You can change shape again in %d sec.", math.ceil(left)))
        return
    end
    Shapeshift.visageSwitchedAt = GetTime()
    Shapeshift.Apply(other, Shapeshift.state.mode, Shapeshift.state.size)
end

-- A weapon stance of the current form (deep pass B2): its weapons, bonus and own abilities. The
-- server allows it in combat; the boss bar then shows the stance's abilities after combat.
function Shapeshift.SwitchStance(n)
    local state = Shapeshift.state
    if not state.active or state.look or not state.stance or state.stance == n then
        return
    end
    if not Shapeshift.ServerReady() or not Shapeshift.caps.stance then
        return
    end
    SendIfReady(P.BuildStance(n))
end

function Shapeshift.OnStateChange(fn)
    listeners[#listeners + 1] = fn
end

-- Asks the server to send this client the given creatures, so the model preview can draw them.
-- Only once the server has said it understands `prime` (older modules would reject it aloud).
-- The menu preview's puppet: a private creature the server dresses as the picked form and hands
-- this client as boss1 (user, 2026-09-24). False when the server cannot, so the caller falls back.
-- Shapeshift.OnPuppet(fn) hears every answer: fn(entry) when boss1 wears it, fn(nil) when there is none.
local puppetListeners = {}
Shapeshift.puppetOn = false

function Shapeshift.OnPuppet(fn)
    puppetListeners[#puppetListeners + 1] = fn
end

function Shapeshift.Puppet(entry, sizePct)
    if not Shapeshift.ServerReady() or not Shapeshift.caps.puppet then
        return false
    end
    Shapeshift.Send(P.BuildPuppet(entry, sizePct))
    return true
end

function Shapeshift.PuppetOff()
    local was = Shapeshift.puppetOn
    if was and Shapeshift.ServerReady() and Shapeshift.caps.puppet then
        Shapeshift.Send(P.BuildPuppet(nil))
    end
    Shapeshift.puppetOn = false
    if was then
        for _, fn in ipairs(puppetListeners) do     -- the server says nothing back to "off"
            fn(nil, nil)
        end
    end
end

function Shapeshift.Prime(entries)
    if not Shapeshift.ServerReady() or not Shapeshift.caps.prime then
        return false
    end
    for _, command in ipairs(P.BuildPrime(entries)) do
        Shapeshift.Send(command)
    end
    return true
end

-- The size slider resizes the current form live: at most one command per RESIZE_GAP seconds
-- while it moves, and the last value is always sent once it stops.
local RESIZE_GAP = 0.2
local resizeWanted, resizeWait, resizeSent = nil, 0, nil
local resizer = CreateFrame("Frame")
resizer:Hide()
resizer:SetScript("OnUpdate", function(self, elapsed)
    resizeWait = resizeWait - elapsed
    if resizeWait > 0 then
        return
    end
    -- Against the last size sent, not the last reply: a reply can still be on its way.
    if resizeWanted and Shapeshift.state.active and resizeWanted ~= (resizeSent or Shapeshift.state.size) then
        Shapeshift.Send(P.BuildSize(resizeWanted))
        resizeSent = resizeWanted
        resizeWait = RESIZE_GAP
    else
        self:Hide()
    end
    resizeWanted = nil
end)

-- True when the server can resize in place (a newer module); the caller keeps its value otherwise.
function Shapeshift.Resize(sizePct)
    if not Shapeshift.state.active or not Shapeshift.ServerReady() or not Shapeshift.caps.size then
        return false
    end
    resizeWanted = P.ClampSize(sizePct)
    resizer:Show()
    return true
end

local function HandleReply(reply)
    ShapeshifterCharDB.confirmed = true
    if reply.kind == "puppet" then
        Shapeshift.puppetOn = reply.entry ~= nil
        for _, fn in ipairs(puppetListeners) do
            fn(reply.entry, reply.unit)
        end
        return
    elseif reply.kind == "caps" then
        Shapeshift.caps = reply.caps
        P.MAX_SIZE = reply.caps.size200 and 200 or 100
        P.PUPPET_MIN = reply.caps.puppetsize and 1 or 10
        return
    elseif reply.kind == "err" then
        Shapeshift.ShowError(reply.text)
        return
    elseif reply.kind == "stance" then
        -- follows its form's ON, which starts the state afresh; ignored without a full form
        if not Shapeshift.state.active or Shapeshift.state.look then
            return
        end
        Shapeshift.state.stance = reply.stance
        Shapeshift.state.stanceKit = reply.kit
    elseif reply.kind == "on" then
        local was = Shapeshift.state
        Shapeshift.state = {
            active = true, entry = reply.entry, mode = reply.mode, size = reply.size,
            kit = reply.kit, look = reply.look, name = reply.name,
        }
        -- A resize comes back as the same form at a new size: no chat line for that.
        if not (was.active and was.entry == reply.entry and was.mode == reply.mode and was.look == reply.look) then
            resizeSent = nil
            Print("You are now " .. reply.name .. (reply.look and " (look only)." or " (" .. reply.mode .. ")."))
        end
    else
        local was = Shapeshift.state.active
        resizeSent, resizeWanted = nil, nil
        Shapeshift.state = { active = false, reason = reply.reason }
        if was then
            Print("You are yourself again.")
        end
    end
    for _, fn in ipairs(listeners) do
        fn(Shapeshift.state)
    end
end

-- The curated form for the current state, if the entry is one. The form last applied wins when
-- two forms share the entry (after a /reload, the first one does).
function Shapeshift.CurrentForm()
    if not Shapeshift.state.active or Shapeshift.state.look then
        return nil
    end
    local entry = Shapeshift.state.entry
    local applied = Shapeshift.appliedForm
    if applied and applied.entry == entry then
        return applied
    end
    for _, form in ipairs(Shapeshift.Forms) do
        if form.entry == entry then
            Shapeshift.appliedForm = form
            return form
        end
    end
    -- A cosmetic skin (after a /reload): scan the raw rows, build its skin form only on a match.
    for _, form in ipairs(Shapeshift.Forms) do
        for i, skin in ipairs(form.skins or {}) do
            if skin.entry == entry then
                local made = Shapeshift.Catalogue.Skins(Shapeshift.Forms, form)[i + 1]
                Shapeshift.appliedForm = made
                return made
            end
        end
    end
    return nil
end

local USAGE = "/ss (open the menu), /ss apply <form id> [b|u] [size 10-100], /ss look <creature entry> [size], /ss revert, /ss talents, /ss status, /ss spike"

SLASH_SHAPESHIFT1 = "/ss"
SLASH_SHAPESHIFT2 = "/shapeshift"
SLASH_SHAPESHIFT3 = "/shapeshifter"
SlashCmdList.SHAPESHIFT = function(input)
    local parsed = P.ParseSlash(input)
    local args = parsed.args
    if parsed.cmd == "" and Shapeshift.ToggleCatalogue then
        Shapeshift.ToggleCatalogue()
    elseif parsed.cmd == "apply" then
        local form = args[1] and Shapeshift.FormById(args[1])
        if not form then
            Print("No form called '" .. tostring(args[1]) .. "'.")
            return
        end
        Shapeshift.Apply(form, args[2] == "u" and "unleashed" or "balanced", args[3] or 100)
    elseif parsed.cmd == "look" then
        local entry = tonumber(args[1])
        if not entry then
            Print("Usage: /ss look <creature entry> [size]")
            return
        end
        Shapeshift.Look(entry, args[2] or 100)
    elseif parsed.cmd == "revert" then
        Shapeshift.Revert()
    elseif parsed.cmd == "status" then
        -- The manual retry: always sent.
        ShapeshifterCharDB.probed = true
        Shapeshift.Send(P.STATUS)
    elseif parsed.cmd == "talents" and Shapeshift.ShowTalents then
        Shapeshift.ShowTalents(Shapeshift.CurrentForm())
    elseif parsed.cmd == "spike" and Shapeshift.ToggleSpike then
        Shapeshift.ToggleSpike()
    else
        Print(USAGE)
    end
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("CHAT_MSG_ADDON")
frame:SetScript("OnEvent", function(self, event, ...)
    if event == "ADDON_LOADED" then
        if ... == "Shapeshifter" then
            ShapeshifterDB = P.DefaultDB(ShapeshifterDB or {})
            ShapeshifterCharDB = ShapeshifterCharDB or {}
        end
    elseif event == "PLAYER_ENTERING_WORLD" then
        -- Once per session, so a /reload mid-form rebuilds the state; and on a character the
        -- server never answered, only the very first time.
        if not statusAsked then
            statusAsked = true
            if ShapeshifterCharDB.confirmed or not ShapeshifterCharDB.probed then
                ShapeshifterCharDB.probed = true
                Shapeshift.Send(P.STATUS)
            end
        end
    elseif event == "CHAT_MSG_ADDON" then
        -- The sender name is not checked: while transformed it is the creature's name.
        local prefix, message, channel = ...
        if prefix == P.PREFIX and channel == "WHISPER" then
            local reply = P.ParseReply(message)
            if reply then
                HandleReply(reply)
            end
        end
    end
end)
