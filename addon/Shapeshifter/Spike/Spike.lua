-- Wave 0 spike harness. Throwaway: answers the spec's open questions in the live client and is
-- removed in plan B. `/ss spike` toggles it.
--
-- Q2 (casting a kit spell that shares a name with one of your own): buttons A to D each try a
--    different way to cast the spike_fireball kit spell (9053, no rank). The chat line printed by
--    UNIT_SPELLCAST_SENT shows which spell actually went out: rank "" is the kit spell,
--    "Rank N" is your own Fireball.
-- Q3 (3D model of a creature the client has never seen): type an entry, press Show.

local frame = CreateFrame("Frame", "ShapeshiftSpikeFrame", UIParent)
frame:SetSize(360, 330)
frame:SetPoint("CENTER")
frame:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 32,
    insets = { left = 11, right = 12, top = 12, bottom = 11 },
})
frame:SetMovable(true)
frame:EnableMouse(true)
frame:RegisterForDrag("LeftButton")
frame:SetScript("OnDragStart", frame.StartMoving)
frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
frame:Hide()

local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
title:SetPoint("TOP", 0, -16)
title:SetText("Shapeshift wave 0 spike")

-- Q3: model preview
local model = CreateFrame("PlayerModel", nil, frame)
model:SetSize(160, 200)
model:SetPoint("TOPLEFT", 20, -40)

local entryBox = CreateFrame("EditBox", "ShapeshiftSpikeEntry", frame, "InputBoxTemplate")
entryBox:SetSize(90, 20)
entryBox:SetPoint("TOPLEFT", model, "BOTTOMLEFT", 6, -8)
entryBox:SetAutoFocus(false)
entryBox:SetNumeric(true)
entryBox:SetText("11502")

local show = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
show:SetSize(60, 22)
show:SetPoint("LEFT", entryBox, "RIGHT", 6, 0)
show:SetText("Show")
show:SetScript("OnClick", function()
    local entry = tonumber(entryBox:GetText())
    if entry then
        model:ClearModel()
        model:SetCreature(entry)
        Shapeshift.Print("Q3: SetCreature(" .. entry .. ") called; model path now: " .. tostring(model:GetModel()))
    end
end)

-- Q2: four ways to cast the kit spell
local function SpellbookSlot(spellId)
    local i = 1
    while true do
        local link = GetSpellLink(i, BOOKTYPE_SPELL)
        if not link then
            return nil
        end
        if string.find(link, "Hspell:" .. spellId .. "|", 1, true) then
            return i
        end
        i = i + 1
    end
end

local buttons = {}
local function CastButton(label, index, configure)
    local button = CreateFrame("Button", "ShapeshiftSpikeCast" .. index, frame, "SecureActionButtonTemplate,UIPanelButtonTemplate")
    button:SetSize(150, 22)
    button:SetPoint("TOPRIGHT", -20, -40 - (index - 1) * 28)
    button:SetText(label)
    button.configure = configure
    buttons[#buttons + 1] = button
    return button
end

CastButton("A: spell=Fireball", 1, function(b)
    b:SetAttribute("type", "spell")
    b:SetAttribute("spell", "Fireball")
end)
CastButton("B: spell=Fireball()", 2, function(b)
    b:SetAttribute("type", "spell")
    b:SetAttribute("spell", "Fireball()")
end)
CastButton("C: /cast Fireball()", 3, function(b)
    b:SetAttribute("type", "macro")
    b:SetAttribute("macrotext", "/cast Fireball()")
end)
CastButton("D: CastSpell(slot)", 4, function(b)
    local slot = SpellbookSlot(9053)
    b:SetAttribute("type", "macro")
    b:SetAttribute("macrotext", slot and ("/run CastSpell(" .. slot .. ", \"spell\")") or "/say no kit slot")
end)

local configure = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
configure:SetSize(150, 22)
configure:SetPoint("TOPRIGHT", -20, -160)
configure:SetText("Set up buttons")
configure:SetScript("OnClick", function()
    if InCombatLockdown() then
        Shapeshift.Print("Out of combat only.")
        return
    end
    for _, button in ipairs(buttons) do
        button.configure(button)
    end
    Shapeshift.Print("Q2: buttons armed. Kit slot for 9053: " .. tostring(SpellbookSlot(9053))
        .. ". CastSpellByID exists: " .. tostring(type(CastSpellByID) == "function"))
end)

local notes = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
notes:SetPoint("TOPRIGHT", -20, -190)
notes:SetWidth(150)
notes:SetJustifyH("LEFT")
notes:SetText("Transform first with /ss apply spike_fireball, then Set up buttons, then target a mob and press A to D.")

local watcher = CreateFrame("Frame")
watcher:RegisterEvent("UNIT_SPELLCAST_SENT")
watcher:SetScript("OnEvent", function(self, event, unit, spellName, spellRank)
    if unit == "player" and frame:IsShown() then
        Shapeshift.Print(string.format("Q2: cast sent: %s [%s]", tostring(spellName), tostring(spellRank)))
    end
end)

function Shapeshift.ToggleSpike()
    if frame:IsShown() then
        frame:Hide()
    else
        frame:Show()
    end
end
