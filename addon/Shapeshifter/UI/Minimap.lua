-- Shapeshift minimap button: the bauble. Shows the current form's icon, drags around the
-- minimap ring, left-click toggles the catalogue, right-click reverts.

local NEUTRAL_ICON = "Interface\\Icons\\Spell_Nature_Polymorph"
local RADIUS = 80

local button = CreateFrame("Button", "ShapeshiftMinimapButton", Minimap)
button:SetSize(31, 31)
button:SetFrameStrata("MEDIUM")
button:SetFrameLevel(8)
button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
button:RegisterForDrag("LeftButton")
button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

local icon = button:CreateTexture(nil, "BACKGROUND")
icon:SetSize(20, 20)
icon:SetPoint("TOPLEFT", 7, -5)
icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
icon:SetTexture(NEUTRAL_ICON)

local border = button:CreateTexture(nil, "OVERLAY")
border:SetSize(53, 53)
border:SetPoint("TOPLEFT")
border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")

local function Place(angle)
    local radians = math.rad(angle)
    button:ClearAllPoints()
    button:SetPoint("CENTER", Minimap, "CENTER", math.cos(radians) * RADIUS, math.sin(radians) * RADIUS)
end

local function AngleFromCursor()
    local scale = Minimap:GetEffectiveScale()
    local cx, cy = GetCursorPosition()
    local mx, my = Minimap:GetCenter()
    return math.deg(math.atan2(cy / scale - my, cx / scale - mx))
end

button:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
        local angle = AngleFromCursor()
        ShapeshifterDB.minimapAngle = angle
        Place(angle)
    end)
end)

button:SetScript("OnDragStop", function(self)
    self:SetScript("OnUpdate", nil)
end)

button:SetScript("OnClick", function(self, mouse)
    if mouse == "RightButton" then
        if Shapeshift.state.active then
            Shapeshift.Revert()
        end
    elseif Shapeshift.ToggleCatalogue then
        Shapeshift.ToggleCatalogue()
    end
end)

button:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:AddLine("Shapeshifter")
    local state = Shapeshift.state
    if state.active then
        GameTooltip:AddLine(state.name .. (state.look and " (look only)" or " (" .. state.mode .. ")"), 1, 1, 1)
    else
        GameTooltip:AddLine("Not transformed", 1, 1, 1)
    end
    GameTooltip:AddLine("Left-click: open or close the menu", 0.7, 0.7, 0.7)
    if state.active then
        GameTooltip:AddLine("Right-click: revert", 0.7, 0.7, 0.7)
    end
    GameTooltip:AddLine("Drag: move around the minimap", 0.7, 0.7, 0.7)
    GameTooltip:Show()
end)

button:SetScript("OnLeave", function()
    GameTooltip:Hide()
end)

local function Refresh()
    local form = Shapeshift.CurrentForm()
    icon:SetTexture(form and form.icon or NEUTRAL_ICON)
end

Shapeshift.OnStateChange(Refresh)

local loader = CreateFrame("Frame")
loader:RegisterEvent("PLAYER_LOGIN")
loader:SetScript("OnEvent", function()
    Place(ShapeshifterDB.minimapAngle)
    Refresh()
end)
