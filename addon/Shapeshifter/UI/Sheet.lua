-- Shapeshift form gear on the character sheet: while a class-grade form with a gear set is active
-- (Balanced or Unleashed, the user's Q1), plain buttons cover all 19 paper-doll slots. A slot the
-- form has an item for shows it (icon, a quality border, the item's own tooltip, shift-click to
-- link); a slot it has none for shows as an empty slot, since the real item's stats are off in form.
-- A "Form gear" label sits under the model. PaperDollFrame is not protected, so none of this is
-- secure. Layout approved by the user, 2026-09-23.
--
-- Ascension replaces the paper doll (patch-B FrameXML): the visible sheet is AscensionPaperDollPanel
-- with its own AscensionCharacter<Slot>Slot buttons and Model; the stock Character<Slot>Slot
-- frames still exist but are never shown. Each frame is looked up Ascension's way first.

local sheetButtons = {}

-- Equipment slot index (0-18, as the server's gear set uses) -> paper-doll slot frame name.
local SLOTS = {
    [0] = "Head", [1] = "Neck", [2] = "Shoulder", [3] = "Shirt", [4] = "Chest", [5] = "Waist",
    [6] = "Legs", [7] = "Feet", [8] = "Wrist", [9] = "Hands", [10] = "Finger0", [11] = "Finger1",
    [12] = "Trinket0", [13] = "Trinket1", [14] = "Back", [15] = "MainHand", [16] = "SecondaryHand",
    [17] = "Ranged", [18] = "Tabard",
}

local function SlotFrame(slotName)
    return _G["AscensionCharacter" .. slotName .. "Slot"] or _G["Character" .. slotName .. "Slot"]
end

-- Made on first use: Ascension's panel exists by then, whatever the load order.
local label
local function Label()
    if not label then
        local panel = AscensionPaperDollPanel or PaperDollFrame
        local model = (AscensionPaperDollPanel and AscensionPaperDollPanel.Model) or CharacterModelFrame
        label = panel:CreateFontString("ShapeshiftSheetLabel", "OVERLAY", "GameFontNormalSmall")
        label:SetPoint("TOP", model, "BOTTOM", 0, -2)
        label:SetText("Form gear")
        label:Hide()
    end
    return label
end

local warm = CreateFrame("GameTooltip", "ShapeshiftSheetWarmTooltip", UIParent, "GameTooltipTemplate")

local function Button(index)
    local slotName = SLOTS[index]
    local parent = SlotFrame(slotName)
    local b = CreateFrame("Button", nil, parent)
    b:SetAllPoints(parent)
    b:SetFrameLevel((parent:GetFrameLevel() or 1) + 2)
    b.sheetSlot = index
    b.icon = b:CreateTexture(nil, "ARTWORK")
    b.icon:SetAllPoints(b)
    b.border = b:CreateTexture(nil, "OVERLAY")
    b.border:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
    b.border:SetBlendMode("ADD")
    b.border:SetPoint("CENTER", b, "CENTER", 0, 0)
    b.border:SetSize(62, 62)
    local _, empty = GetInventorySlotInfo(slotName .. "Slot")
    b.emptyTexture = empty
    b:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        if self.itemID then
            GameTooltip:SetHyperlink("item:" .. self.itemID)
        else
            GameTooltip:SetText("No form gear in this slot")
        end
        GameTooltip:Show()
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    b:SetScript("OnClick", function(self)
        if self.itemID and IsModifiedClick("CHATLINK") then
            local _, link = GetItemInfo(self.itemID)
            if link then
                ChatEdit_InsertLink(link)
            end
        end
    end)
    b:Hide()
    sheetButtons[index] = b
    return b
end

-- The form's gear; while worn in weapon stance 2 or 3, that stance's weapons (deep pass B2).
local function GearFor(form)
    local cg = form and Shapeshift.ClassGradeFor(form)
    if not cg then
        return nil
    end
    local n = Shapeshift.state.stance
    local stance = cg.stances and n and n > 1 and cg.stances[n]
    if not stance or Shapeshift.CurrentForm() ~= form then
        return cg.gear
    end
    local gear = {}
    for slot, item in pairs(cg.gear) do
        gear[slot] = item
    end
    for slot = 15, 17 do
        gear[slot] = stance.gear[slot]
    end
    return gear
end

local function Refresh()
    local form = Shapeshift.CurrentForm()
    local gear = GearFor(form)
    for index = 0, 18 do
        local b = sheetButtons[index] or Button(index)
        if gear then
            local item = gear[index]
            b.itemID = item and item.id or nil
            if item then
                b.icon:SetTexture(item.icon)
                local color = ITEM_QUALITY_COLORS[item.quality or 1]
                b.border:SetVertexColor(color.r, color.g, color.b)
                b.border:Show()
                warm:SetOwner(UIParent, "ANCHOR_NONE")
                warm:SetHyperlink("item:" .. item.id)            -- ask the server now, not on hover
            else
                b.icon:SetTexture(b.emptyTexture)
                b.border:Hide()
            end
            b:Show()
        else
            b.itemID = nil
            b:Hide()
        end
    end
    if gear then
        Label():Show()
    elseif label then
        label:Hide()
    end
end

Shapeshift.OnStateChange(Refresh)

-- The sheet's "Level 20 Orc Barbarian" line (Ascension's AscensionCharacterFrame.ClassLevelLabel,
-- rewritten by its UpdateCharacterInfo on show and on every player event) reads "Level 20 <title>"
-- while a form with a title is worn (user, 2026-09-24). Reverting calls the client's own update.
local sheetFrame = AscensionCharacterFrame
if sheetFrame and sheetFrame.UpdateCharacterInfo and sheetFrame.ClassLevelLabel then
    hooksecurefunc(sheetFrame, "UpdateCharacterInfo", function(self)
        local form = Shapeshift.CurrentForm()
        if form and form.title then
            self.ClassLevelLabel:SetFormattedText("Level %d %s", UnitLevel("player"),
                "|cffffffff" .. form.title .. "|r")
        end
    end)
    Shapeshift.OnStateChange(function()
        if sheetFrame:IsShown() then
            sheetFrame:UpdateCharacterInfo()
        end
    end)
end
