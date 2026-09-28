-- Shapeshift Form Talents: a form's passives shown the way the 3.3.5 talent frame shows talents,
-- read-only (they come with the form; no points are spent). Opened from the catalogue's detail
-- pane, from the character sheet while transformed, or with /ss talents.

local C = Shapeshift.Catalogue
local COLS = 4
local SLOT = 52

local frame = CreateFrame("Frame", "ShapeshiftTalents", UIParent)
frame:SetSize(COLS * SLOT + 60, 300)
frame:SetPoint("CENTER", 220, 0)
frame:SetFrameStrata("HIGH")
-- Class-talent artwork by the form's school (user call, 2026-09-23); the client has no Mage Arcane art.
local SCHOOL_ART = {
    fire = "Interface\\TalentFrame\\MageFire-TopLeft",
    frost = "Interface\\TalentFrame\\MageFrost-TopLeft",
    shadow = "Interface\\TalentFrame\\WarlockCurses-TopLeft",
    nature = "Interface\\TalentFrame\\ShamanElementalCombat-TopLeft",
    holy = "Interface\\TalentFrame\\PriestHoly-TopLeft",
    physical = "Interface\\TalentFrame\\WarriorArms-TopLeft",
    arcane = "Interface\\TalentFrame\\WarlockDestruction-TopLeft",
}

local function Backdrop(school)
    frame:SetBackdrop({
        bgFile = SCHOOL_ART[school] or SCHOOL_ART.holy,
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
        tile = false, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 },
    })
end
Backdrop("holy")
frame:SetMovable(true)
frame:EnableMouse(true)
frame:SetClampedToScreen(true)
frame:RegisterForDrag("LeftButton")
frame:SetScript("OnDragStart", frame.StartMoving)
frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
frame:Hide()
tinsert(UISpecialFrames, "ShapeshiftTalents")

local shade = frame:CreateTexture(nil, "BORDER")
shade:SetPoint("TOPLEFT", 12, -12)
shade:SetPoint("BOTTOMRIGHT", -12, 12)
shade:SetTexture(0, 0, 0, 0.55)

local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
title:SetPoint("TOP", 0, -20)

local points = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
points:SetPoint("BOTTOM", 0, 20)

local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", -6, -6)

local empty = frame:CreateFontString(nil, "OVERLAY", "GameFontDisable")
empty:SetPoint("CENTER")
empty:SetWidth(COLS * SLOT)
empty:SetText("This form has no talents.")

local buttons = {}
local function Button(i)
    if buttons[i] then
        return buttons[i]
    end
    local b = CreateFrame("Button", nil, frame)
    b:SetSize(37, 37)
    local col, row = (i - 1) % COLS, math.floor((i - 1) / COLS)
    b:SetPoint("TOPLEFT", 36 + col * SLOT, -52 - row * SLOT)
    b.icon = b:CreateTexture(nil, "ARTWORK")
    b.icon:SetAllPoints()
    b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
    b.border = b:CreateTexture(nil, "OVERLAY")
    b.border:SetTexture("Interface\\TalentFrame\\TalentFrame-RankBorder")
    b.border:SetSize(32, 32)
    b.border:SetPoint("CENTER", b, "BOTTOMRIGHT", 0, 0)
    b.rank = b:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    b.rank:SetPoint("CENTER", b.border, "CENTER", 0, 0)
    b:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        if self.spell then
            GameTooltip:SetHyperlink("spell:" .. self.spell)
        else
            GameTooltip:SetText(self.info.name, 1, 1, 1)
            GameTooltip:AddLine(self.info.text, 1, 0.82, 0, true)
        end
        GameTooltip:AddLine("Rank " .. self.talentRank .. "/" .. self.talentMax, 1, 1, 1)
        GameTooltip:Show()
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    buttons[i] = b
    return b
end

-- Always beside the window it was opened from, never over or behind other Shapeshift UI (user,
-- 2026-09-23): right of the catalogue, else right of the character sheet, else screen centre.
local function Place()
    frame:ClearAllPoints()
    if ShapeshiftCatalogue and ShapeshiftCatalogue:IsShown() then
        frame:SetPoint("TOPLEFT", ShapeshiftCatalogue, "TOPRIGHT", 4, 0)
    elseif CharacterFrame and CharacterFrame:IsShown() then
        frame:SetPoint("TOPLEFT", CharacterFrame, "TOPRIGHT", -28, -12)
    else
        frame:SetPoint("CENTER", 220, 0)
    end
end

function Shapeshift.ShowTalents(form)
    if not form then
        Shapeshift.ShowError("No form to show talents for.")
        return
    end
    Place()
    Backdrop(form.school)
    local current = Shapeshift.state and Shapeshift.state.active and Shapeshift.state.entry == form.entry
    local balanced = not (current and Shapeshift.state.mode == "unleashed")
    local talents = C.TalentsFor(form, Shapeshift.ClassGradeFor(form),
        UnitLevel("player"), balanced)
    title:SetText(form.label .. " Talents")
    local spent = 0
    for i, talent in ipairs(talents) do
        local b = Button(i)
        local texture = talent.icon
        if talent.spell then
            texture = select(3, GetSpellInfo(talent.spell))
        end
        b.spell, b.info, b.talentRank, b.talentMax = talent.spell, talent, talent.rank, talent.max
        b.icon:SetTexture(texture or "Interface\\Icons\\INV_Misc_QuestionMark")
        b.rank:SetText(talent.rank)
        b:Show()
        spent = spent + talent.rank
    end
    for i = #talents + 1, #buttons do
        buttons[i]:Hide()
    end
    if #talents == 0 then
        empty:Show()
    else
        empty:Hide()
    end
    points:SetText("Points: " .. spent .. " (granted by the form)")
    frame.form = form
    frame:Show()
end

-- The Talents buttons open the window and close it again (user, 2026-09-27).
function Shapeshift.ToggleTalents(form)
    if frame:IsShown() and (not form or frame.form == form) then
        frame:Hide()
    else
        Shapeshift.ShowTalents(form)
    end
end

function Shapeshift.TalentsShown()
    return frame:IsShown()
end

function Shapeshift.HideTalents()
    frame:Hide()
end

-- A button on the character sheet while you are a curated form.
local sheetButton = CreateFrame("Button", "ShapeshiftSheetTalents", PaperDollFrame, "UIPanelButtonTemplate")
sheetButton:SetSize(96, 20)
sheetButton:SetPoint("TOPRIGHT", PaperDollFrame, "TOPRIGHT", -40, -40)
sheetButton:SetText("Form Talents")
sheetButton:SetScript("OnClick", function() Shapeshift.ToggleTalents(Shapeshift.CurrentForm()) end)
sheetButton:Hide()

Shapeshift.OnStateChange(function()
    if Shapeshift.CurrentForm() then
        sheetButton:Show()
    else
        sheetButton:Hide()
        frame:Hide()
    end
end)
