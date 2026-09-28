-- Shapeshift catalogue window: pool tabs down the left, a search box over an icon grid (or a
-- name list for Any Creature) in the middle, and the selected form's detail pane on the right.
-- All choosing, filtering and paging is done by Core/Catalogue.lua; this file only draws.

local C = Shapeshift.Catalogue

local NEUTRAL_ICON = "Interface\\Icons\\Spell_Nature_Polymorph"
local STAR = "Interface\\COMMON\\ReputationStar"
local GRID_COLS, GRID_ROWS = 5, 4
local LIST_ROWS = 14
local SEARCH_LIMIT = 500

local view = {
    pool = nil,           -- the saved tab, read on the first Refresh (saved variables load after this file)
    search = "",
    page = 1,             -- the creature list's page
    top = 1,              -- the form grid's first row; the mouse wheel moves it one row, the page buttons four
    selected = nil,       -- { kind = "form", form = ... } or { kind = "creature", entry, name, level }
}

local frame = CreateFrame("Frame", "ShapeshiftCatalogue", UIParent)
frame:SetSize(720, 470)
frame:SetPoint("CENTER")
frame:SetFrameStrata("DIALOG")
frame:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background-Dark",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 32,
    insets = { left = 11, right = 12, top = 12, bottom = 11 },
})
frame:SetMovable(true)
frame:EnableMouse(true)
frame:SetClampedToScreen(true)
frame:RegisterForDrag("LeftButton")
frame:SetScript("OnDragStart", frame.StartMoving)
frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
frame:Hide()
tinsert(UISpecialFrames, "ShapeshiftCatalogue")

-- The tab's own dungeon-finder artwork, dimmed behind the grid (user call, 2026-09-23).
local art = frame:CreateTexture("ShapeshiftCatalogueArt", "BORDER")
art:SetPoint("TOPLEFT", 12, -12)
art:SetPoint("BOTTOMRIGHT", -12, 12)
art:SetAlpha(0.35)

local header = frame:CreateTexture(nil, "ARTWORK")
header:SetTexture("Interface\\DialogFrame\\UI-DialogBox-Header")
header:SetSize(300, 64)
header:SetPoint("TOP", 0, 12)

local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
title:SetPoint("TOP", header, "TOP", 0, -14)
title:SetText("Shapeshifter")

local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", -6, -6)

local Refresh -- forward declaration

-- Region:SetShown does not exist in the 3.3.5 client.
local function ShowIf(region, shown)
    if shown then
        region:Show()
    else
        region:Hide()
    end
end

-- ------------------------------------------------------------------ pool tabs

local tabs = {}
for i, pool in ipairs(C.POOLS) do
    local tab = CreateFrame("CheckButton", nil, frame)
    tab:SetSize(36, 36)
    tab:SetPoint("TOPLEFT", 18, -58 - (i - 1) * 40)       -- 10 tabs fit the 470 px frame (user, 2026-09-26)
    tab:SetNormalTexture(pool.icon)
    tab:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
    tab:SetCheckedTexture("Interface\\Buttons\\CheckButtonHilight", "ADD")
    tab.pool = pool
    tab:SetScript("OnClick", function(self)
        view.pool = self.pool.key
        ShapeshifterDB.pool = self.pool.key
        view.page, view.top = 1, 1
        Refresh()
    end)
    tab:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText(self.pool.label)
        GameTooltip:Show()
    end)
    tab:SetScript("OnLeave", function() GameTooltip:Hide() end)
    tabs[i] = tab
end

-- The Group button above the tabs cycles how the grid is grouped (deep pass A, user 2026-09-25):
-- the button shows the short mode name, the tooltip the full one.
local groupButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
groupButton:SetSize(56, 20)
groupButton:SetPoint("TOPLEFT", 14, -32)
groupButton:SetNormalFontObject("GameFontNormalSmall")
groupButton:SetHighlightFontObject("GameFontHighlightSmall")
groupButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
groupButton:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Group by: " .. C.GroupingLabel(ShapeshifterDB.grouping))
    GameTooltip:AddLine("Click for the next grouping, right-click for the one before.", 1, 1, 1, true)
    GameTooltip:Show()
end)
groupButton:SetScript("OnLeave", function() GameTooltip:Hide() end)
groupButton:SetScript("OnClick", function(self, button)
    ShapeshifterDB.grouping = C.NextGrouping(ShapeshifterDB.grouping, button == "RightButton" and -1 or 1)
    view.top = 1
    Refresh()
    if GameTooltip:IsOwned(self) then
        self:GetScript("OnEnter")(self)
    end
end)

-- ------------------------------------------------------------------ middle column

local poolTitle = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
poolTitle:SetPoint("TOPLEFT", 70, -30)
poolTitle:SetJustifyH("LEFT")

local search = CreateFrame("EditBox", "ShapeshiftCatalogueSearch", frame, "InputBoxTemplate")
search:SetSize(190, 20)
search:SetPoint("TOPLEFT", 76, -48)
search:SetAutoFocus(false)
search:SetScript("OnTextChanged", function(self)
    view.search = self:GetText() or ""
    view.page, view.top = 1, 1
    Refresh()
end)
search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)

local searchLabel = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
searchLabel:SetPoint("LEFT", search, "RIGHT", 8, 0)
searchLabel:SetText("search")

local empty = frame:CreateFontString(nil, "OVERLAY", "GameFontDisable")
empty:SetPoint("TOPLEFT", 74, -90)
empty:SetWidth(290)
empty:SetJustifyH("LEFT")

-- The mouse wheel over the grid moves it one row (user, 2026-09-25). The area behind the cells
-- catches the wheel in the gaps; each cell passes it on too.
local function Wheel(_, delta)
    if view.pool ~= "creature" then
        view.top = view.top - delta
        Refresh()
    end
end

local wheelArea = CreateFrame("Frame", nil, frame)
wheelArea:SetPoint("TOPLEFT", 70, -76)
wheelArea:SetSize(300, 4 * 78)
wheelArea:EnableMouseWheel(true)
wheelArea:SetScript("OnMouseWheel", Wheel)

-- Grid of forms
local cells = {}
for i = 1, GRID_COLS * GRID_ROWS do
    local col, row = (i - 1) % GRID_COLS, math.floor((i - 1) / GRID_COLS)
    local cell = CreateFrame("Button", nil, frame)
    cell:SetSize(58, 74)
    cell:SetPoint("TOPLEFT", 70 + col * 60, -76 - row * 78)

    cell.icon = cell:CreateTexture(nil, "ARTWORK")
    cell.icon:SetSize(40, 40)
    cell.icon:SetPoint("TOP", 0, -2)

    cell.selected = cell:CreateTexture(nil, "OVERLAY")
    cell.selected:SetTexture("Interface\\Buttons\\CheckButtonHilight")
    cell.selected:SetBlendMode("ADD")
    cell.selected:SetAllPoints(cell.icon)

    cell.star = cell:CreateTexture(nil, "OVERLAY")
    cell.star:SetTexture(STAR)
    cell.star:SetTexCoord(0, 0.5, 0, 0.5)
    cell.star:SetSize(14, 14)
    cell.star:SetPoint("TOPLEFT", cell.icon, "TOPLEFT", -4, 4)

    cell.lookOnly = cell:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cell.lookOnly:SetPoint("BOTTOM", cell.icon, "BOTTOM", 0, 1)
    cell.lookOnly:SetText("look only")

    cell.name = cell:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cell.name:SetPoint("TOP", cell.icon, "BOTTOM", 0, -2)
    cell.name:SetWidth(58)
    cell.name:SetHeight(26)
    cell.name:SetJustifyV("TOP")

    cell:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
    cell:GetHighlightTexture():SetAllPoints(cell.icon)
    cell:EnableMouseWheel(true)
    cell:SetScript("OnMouseWheel", Wheel)
    cell:SetScript("OnClick", function(self)
        -- base: the listed form; form: the shape shown, the worn one if you wear its visage.
        local worn = Shapeshift.CurrentForm()
        local shown = C.ShownFor(Shapeshift.Forms, self.form, worn, view.search,
            ShapeshifterDB.skins and ShapeshifterDB.skins[self.form.id])
        view.selected = { kind = "form", form = shown, base = self.form }
        Refresh()
    end)
    cells[i] = cell
end

-- A header row takes a whole grid row (user, 2026-09-25); one label per grid row.
local headers = {}
for row = 1, GRID_ROWS do
    local label = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    label:SetPoint("TOPLEFT", 74, -76 - (row - 1) * 78 - 28)
    label:SetWidth(290)
    label:SetJustifyH("LEFT")
    headers[row] = label
end

-- List of creatures
local rows = {}
for i = 1, LIST_ROWS do
    local row = CreateFrame("Button", nil, frame)
    row:SetSize(296, 20)
    row:SetPoint("TOPLEFT", 72, -76 - (i - 1) * 21)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    row.name:SetPoint("LEFT", 4, 0)
    row.name:SetWidth(240)
    row.name:SetJustifyH("LEFT")
    row.level = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    row.level:SetPoint("RIGHT", -4, 0)
    row.selected = row:CreateTexture(nil, "BACKGROUND")
    row.selected:SetTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight")
    row.selected:SetBlendMode("ADD")
    row.selected:SetAllPoints()
    row:SetScript("OnClick", function(self)
        view.selected = { kind = "creature", entry = self.creature.entry, name = self.creature.name,
                          level = self.creature.level, display = self.creature.display }
        Refresh()
    end)
    rows[i] = row
end

-- Paging
local prev = CreateFrame("Button", nil, frame)
prev:SetSize(28, 28)
prev:SetPoint("TOPLEFT", 150, -392)
prev:SetNormalTexture("Interface\\Buttons\\UI-SpellbookIcon-PrevPage-Up")
prev:SetPushedTexture("Interface\\Buttons\\UI-SpellbookIcon-PrevPage-Down")
prev:SetDisabledTexture("Interface\\Buttons\\UI-SpellbookIcon-PrevPage-Disabled")
prev:SetHighlightTexture("Interface\\Buttons\\UI-Common-MouseHilight", "ADD")
prev:SetScript("OnClick", function()
    if view.pool == "creature" then view.page = view.page - 1 else view.top = view.top - GRID_ROWS end
    Refresh()
end)

local pageText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
pageText:SetPoint("LEFT", prev, "RIGHT", 8, 0)

local nextPage = CreateFrame("Button", nil, frame)
nextPage:SetSize(28, 28)
nextPage:SetPoint("LEFT", pageText, "RIGHT", 8, 0)
nextPage:SetNormalTexture("Interface\\Buttons\\UI-SpellbookIcon-NextPage-Up")
nextPage:SetPushedTexture("Interface\\Buttons\\UI-SpellbookIcon-NextPage-Down")
nextPage:SetDisabledTexture("Interface\\Buttons\\UI-SpellbookIcon-NextPage-Disabled")
nextPage:SetHighlightTexture("Interface\\Buttons\\UI-Common-MouseHilight", "ADD")
nextPage:SetScript("OnClick", function()
    if view.pool == "creature" then view.page = view.page + 1 else view.top = view.top + GRID_ROWS end
    Refresh()
end)

local status = frame:CreateFontString(nil, "OVERLAY", "GameFontRedSmall")
status:SetPoint("BOTTOMLEFT", 70, 22)
status:SetWidth(300)
status:SetJustifyH("LEFT")

-- ------------------------------------------------------------------ detail pane

local detail = CreateFrame("Frame", nil, frame)
detail:SetPoint("TOPLEFT", 386, -30)
detail:SetPoint("BOTTOMRIGHT", -18, 18)

local model = CreateFrame("PlayerModel", nil, detail)
model:SetSize(220, 200)
model:SetPoint("TOP", 0, -4)
model:EnableMouse(true)

local bigIcon = detail:CreateTexture(nil, "ARTWORK")
bigIcon:SetSize(96, 96)
bigIcon:SetPoint("CENTER", model, "CENTER")
bigIcon:Hide()

-- Drag to turn the model, or hold the rotate buttons under it (as the dressing room does).
-- Right-drag moves it, the wheel zooms and a middle click goes back to the baked or automatic
-- framing (back again at the user's ask, 2026-09-27: some forms still need framing). A framing is
-- kept for its form the moment the drag or the wheel lets go, over the baked one (Forms.lua `view`).
local facing, dragX, spin = 0, nil, 0
local panX, panY = nil, nil
local SaveView, ResetView           -- set once the framing code exists, below
model:EnableMouseWheel(true)
model:SetScript("OnMouseDown", function(self, button)
    if button == "RightButton" then
        panX, panY = GetCursorPosition()
    elseif button == "MiddleButton" then
        if ResetView then
            ResetView(self)
        end
    else
        dragX = GetCursorPosition()
    end
end)
model:SetScript("OnMouseUp", function(self, button)
    if button == "RightButton" then
        panX, panY = nil, nil
        if SaveView then
            SaveView(self)
        end
    else
        dragX = nil
    end
end)
model:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Preview", 1, 1, 1)
    GameTooltip:AddLine("Left-drag: turn. Right-drag: move. Wheel: zoom. Middle-click: reset.", 0.8, 0.8, 0.8, true)
    GameTooltip:AddLine("Your framing is kept for each form as soon as you let go.", 0.6, 0.6, 0.6, true)
    GameTooltip:Show()
end)
model:SetScript("OnLeave", function() GameTooltip:Hide() end)

local function RotateButton(direction, point, x)
    local b = CreateFrame("Button", nil, detail)
    b:SetSize(35, 35)
    b:SetPoint("TOP", model, "BOTTOM", x, 30)
    local name = direction > 0 and "Left" or "Right"
    b:SetNormalTexture("Interface\\Buttons\\UI-Rotation" .. name .. "-Button-Up")
    b:SetPushedTexture("Interface\\Buttons\\UI-Rotation" .. name .. "-Button-Down")
    b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Round", "ADD")
    b:SetScript("OnMouseDown", function() spin = direction end)
    b:SetScript("OnMouseUp", function() spin = 0 end)
    b:SetScript("OnHide", function() spin = 0 end)
    return b
end
RotateButton(1, "LEFT", -86)
RotateButton(-1, "RIGHT", 86)

-- What this client does in a model frame (user's /run tests, 2026-09-24): SetDisplayInfo loads
-- nothing; SetCreature loads only a creature it has cached; ClearModel does not clear, so a
-- creature that fails to load leaves the previous preview up (Buru showed Mor'Ladim's skeleton);
-- an empty frame's GetModel() returns the frame itself; a model path to a missing file draws the
-- blue error cube. So the frame stays invisible while it loads, and a load counts only when the
-- model path changed, or, once the server has sent the creature, whatever it now holds.
local FIT_YARDS = 3             -- a model this tall fills the frame (Hogger, 2 yards, fits)

local function PathOf(frame)
    local path = frame:GetModel()
    return type(path) == "string" and path ~= "" and string.lower(path) or nil
end

local function Loaded(frame)
    local path = PathOf(frame)
    return path ~= nil and (path ~= frame.before or frame.afterPrime)
end

-- Tall models are shrunk, gently: the frame's own camera already pulls back part of the way
-- (Thermaplugg, 5 yards, overflowed at full scale; Buru, 11, was a speck at 3/11).
local function Fit(frame)
    if frame.height and frame.height > FIT_YARDS then
        frame:SetModelScale(math.sqrt(FIT_YARDS / frame.height))
    end
end

local ApplyView                     -- the player's framing, defined with the puppet code below

local function Reveal(frame)
    Fit(frame)
    if ApplyView then
        ApplyView(frame)
    end
    frame:SetAlpha(1)
end

-- The model loads by creature entry, which only draws once the client has the creature: if the
-- first try does not change the model, have the server send the creature (Shapeshift.Prime) and
-- try again, then show the icon. A character model (a humanoid NPC such as Herod) goes straight
-- to the icon here: this client draws those as a white body in the wrong clothes.
local function LoadByCreature(entry, form)
    model:SetAlpha(0)
    model:SetModelScale(1)
    model.height = form and form.height or 0
    model.retried, model.primed, model.afterPrime = false, false, false
    model.checkIn = nil
    if form and form.charModel then
        bigIcon:Show()
        return
    end
    model.before = PathOf(model)
    model:SetCreature(entry)
    model:SetFacing(0)
    if Loaded(model) then
        Reveal(model)
    else
        model.checkIn = 0.6
    end
end

-- Best of all (user, 2026-09-24): the server's private puppet, dressed as the picked creature and
-- handed to this client as boss1, drawn as a unit, so it looks exactly as it does in the world.
-- The preview asks for it and waits; with no answer, a refusal (in an instance) or no boss1 unit,
-- it falls back to loading by creature.
local PUPPET_WAIT = 2.0         -- seconds to wait for the server's answer
local PUPPET_DRAWS = { 0.2, 0.8 }   -- after the answer: draw, then draw again once the model is on

-- The client may drop the boss1 hand-over when it arrives before the puppet itself (both are sent
-- in one server tick): ask once more, when the puppet exists. If boss1 still does not come, the
-- puppet is given up for the session, so no later pick waits for it (user, 2026-09-24: 3-4 s).
local puppetBroken = false

local function LoadModel(entry, form)
    model.form = form
    model.puppetWait, model.puppetDraws, model.puppetRetried = nil, nil, false
    if not puppetBroken and Shapeshift.Puppet(entry, 100) then
        model:SetAlpha(0)
        model:SetModelScale(1)
        model.checkIn = nil
        model.puppetWait = PUPPET_WAIT
        return
    end
    LoadByCreature(entry, form)
end

-- Auto-framing (user, 2026-09-24: "some need to be moved up, some forward, down and left"). The
-- frame draws a unit at its natural size and ignores its scale, and SetModelScale moved it out of
-- view, so each model is placed instead: its bounding box's centre (Forms.lua box, from the game
-- data) goes where Hogger's sits, about a yard up, and it is pulled back along the camera axis
-- (SetPosition x, as Blizzard's Model_OnMouseWheel zooms) until its bigger dimension looks
-- PUPPET_FIT_YARDS big. CAMERA_DISTANCE is the frame camera's distance, measured in game with
-- Shapeshift.PreviewCalibrate.
local CAMERA_DISTANCE = 1.5         -- second sweep, 2026-09-24: Chromaggus whole from 2, cut at 1
local LIFT = 0.11                   -- yards up per yard over FIT (lift sweep, 2026-09-24: 0 low, 0.2 high)

local fitLabel = detail:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
fitLabel:SetPoint("TOPLEFT", model, "TOPLEFT", 4, -4)
fitLabel:Hide()

local function PlaceUnit(frame)
    local form = frame.form
    local extent = form and math.max(form.height or 0, form.span or 0) or 0
    local box = form and form.box
    if extent <= 0 or not box then
        frame:SetPosition(0, 0, 0)
        return
    end
    local fit = Shapeshift.Protocol.PUPPET_FIT_YARDS
    local back = CAMERA_DISTANCE * (extent / fit - 1)
    back = math.max(back, -CAMERA_DISTANCE * 0.5)             -- small ones come closer, not into the lens
    -- The frame centres a unit on its own (the first sweep, 2026-09-24: shifting by the box centre
    -- pushed Chromaggus out of view), so only the distance changes.
    frame:SetPosition(-back, 0, LIFT * math.max(0, extent - fit))
end

-- One command, and the preview steps through camera distances on its own, the value shown on it.
function Shapeshift.PreviewCalibrate(values)
    values = values or { 0.25, 0.5, 0.75, 1, 1.5, 2, 3 }
    local i, wait = 0, 0
    fitLabel:Show()
    local stepper = CreateFrame("Frame")
    stepper:SetScript("OnUpdate", function(self, elapsed)
        wait = wait - elapsed
        if wait > 0 then
            return
        end
        i = i + 1
        if not values[i] then
            self:SetScript("OnUpdate", nil)
            fitLabel:Hide()
            print("Shapeshifter preview calibration done.")
            return
        end
        CAMERA_DISTANCE = values[i]
        fitLabel:SetText("D = " .. CAMERA_DISTANCE)
        PlaceUnit(model)
        wait = 4
    end)
end

-- The same for the lift, at the current distance.
function Shapeshift.PreviewCalibrateLift(values)
    values = values or { 0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.3 }
    local i, wait = 0, 0
    fitLabel:Show()
    local stepper = CreateFrame("Frame")
    stepper:SetScript("OnUpdate", function(self, elapsed)
        wait = wait - elapsed
        if wait > 0 then
            return
        end
        i = i + 1
        if not values[i] then
            self:SetScript("OnUpdate", nil)
            fitLabel:Hide()
            print("Shapeshifter preview lift calibration done.")
            return
        end
        LIFT = values[i]
        fitLabel:SetText("D = " .. CAMERA_DISTANCE .. ", lift = " .. LIFT)
        PlaceUnit(model)
        wait = 4
    end)
end

function Shapeshift.PreviewDistance(distance)
    CAMERA_DISTANCE = tonumber(distance) or CAMERA_DISTANCE
    PlaceUnit(model)
end

-- The player's framing for the shown form, else its baked one (views.json), over the auto-framing.
ApplyView = function(frame)
    local views = ShapeshifterDB and ShapeshifterDB.previewViews
    local view = views and frame.viewKey and views[frame.viewKey] or (frame.form and frame.form.view)
    if view then
        frame:SetPosition(view[1], view[2], view[3])
    end
end

SaveView = function(frame)
    if not (ShapeshifterDB and frame.viewKey) then
        return
    end
    ShapeshifterDB.previewViews = ShapeshifterDB.previewViews or {}
    local x, y, z = frame:GetPosition()
    ShapeshifterDB.previewViews[frame.viewKey] = { x, y, z }
end

ResetView = function(frame)
    if ShapeshifterDB and ShapeshifterDB.previewViews and frame.viewKey then
        ShapeshifterDB.previewViews[frame.viewKey] = nil
    end
    if frame.puppetUnit and UnitExists(frame.puppetUnit) then
        PlaceUnit(frame)
    else
        frame:SetPosition(0, 0, 0)
    end
    ApplyView(frame)
end

-- How far a wheel notch or a pixel of drag moves the model: more for big ones.
local function Reach(frame)
    local form = frame.form
    return math.max(2, form and math.max(form.height or 0, form.span or 0) or 0)
end

model:SetScript("OnMouseWheel", function(self, delta)
    local x, y, z = self:GetPosition()
    self:SetPosition(x + delta * 0.08 * Reach(self), y, z)
    SaveView(self)
end)

-- The first draw often lands before the model has loaded, which drops its placement, so it showed
-- off-centre and jumped into place on the second draw (user, 2026-09-26). It stays invisible until
-- the last draw, which is placed.
local function DrawPuppet(frame, reveal)
    frame:SetModelScale(1)
    frame:SetUnit(frame.puppetUnit)
    frame:SetFacing(facing)
    PlaceUnit(frame)
    ApplyView(frame)
    if reveal then
        frame:SetAlpha(1)
    end
end

Shapeshift.OnPuppet(function(entry, unit)
    if not model.puppetWait then
        return
    end
    model.puppetWait = nil
    model.puppetUnit = unit or "boss1"
    if entry and entry == model.entry then
        model.puppetDraws = { PUPPET_DRAWS[1], PUPPET_DRAWS[2] }
        model.puppetClock = 0
    elseif model.entry then
        LoadByCreature(model.entry, model.form)
    end
end)

local function UpdatePuppet(self, elapsed)
    if self.puppetWait then
        self.puppetWait = self.puppetWait - elapsed
        if self.puppetWait <= 0 then
            self.puppetWait = nil
            LoadByCreature(self.entry, self.form)
        end
    elseif self.puppetDraws then
        self.puppetClock = self.puppetClock + elapsed
        local nextAt = self.puppetDraws[1]
        if self.puppetClock >= nextAt then
            table.remove(self.puppetDraws, 1)
            local last = #self.puppetDraws == 0
            if UnitExists(self.puppetUnit) then
                DrawPuppet(self, last)
            elseif last and not self.puppetRetried and Shapeshift.Puppet(self.entry, 100) then
                self.puppetRetried = true               -- the puppet exists now: hand it over again
                self.puppetWait = PUPPET_WAIT
            elseif last then
                puppetBroken = true                     -- the client does not take the boss unit
                LoadByCreature(self.entry, self.form)
            end
            if last then
                self.puppetDraws = nil
            end
        end
    end
end

-- The pet and boss frames would show the puppet; they stay down while it is up, and the pet frame
-- comes back by the client's own rule after (a real pet shows again).
local puppetFrames = { "PetFrame", "Boss1TargetFrame", "Boss2TargetFrame", "Boss3TargetFrame", "Boss4TargetFrame" }
for _, name in ipairs(puppetFrames) do
    local unitFrame = _G[name]
    if unitFrame then
        unitFrame:HookScript("OnShow", function(self)
            if Shapeshift.puppetOn and not InCombatLockdown() then
                self:Hide()
            end
        end)
    end
end
Shapeshift.OnPuppet(function(entry)
    if not entry and type(PetFrame_Update) == "function" and PetFrame and not InCombatLockdown() then
        PetFrame_Update(PetFrame)
    end
end)

model:SetScript("OnUpdate", function(self, elapsed)
    UpdatePuppet(self, elapsed)
    if panX then
        local cx, cy = GetCursorPosition()
        local x, y, z = self:GetPosition()
        local k = 0.004 * Reach(self)
        if cx ~= panX or cy ~= panY then
            self:SetPosition(x, y + (cx - panX) * k, z + (cy - panY) * k)
            panX, panY = cx, cy
            SaveView(self)          -- kept as it moves: a release outside the preview loses nothing
        end
    end
    if dragX then
        local x = GetCursorPosition()
        facing = facing + (x - dragX) / 80
        dragX = x
        self:SetFacing(facing)
    elseif spin ~= 0 then
        facing = facing + spin * elapsed * 2.5
        self:SetFacing(facing)
    end
    if self.checkIn then
        self.checkIn = self.checkIn - elapsed
        if self.checkIn <= 0 then
            self.checkIn = nil
            if Loaded(self) then
                Reveal(self)
            else
                if not self.retried and self.entry then
                    self.retried = true
                    self.primed = Shapeshift.Prime({ self.entry })
                    if self.primed then
                        self.checkIn = 0.4
                    else
                        self:SetCreature(self.entry)   -- the server's answer may have arrived by now
                        self.checkIn = 1.2
                    end
                elseif self.primed then
                    self.primed = false
                    self.afterPrime = true
                    self:SetCreature(self.entry)       -- the primed answer is in the cache now
                    self.checkIn = 0.6
                else
                    bigIcon:Show()
                end
            end
        end
    end
end)

-- A character with several shapes (user, 2026-09-24) is one entry with this toggle: the chosen
-- shape is what the preview shows and what Transform becomes. The chosen button is the disabled one.
-- An archetype's skins (user, 2026-09-26) use the same row, in a smaller font (up to 6 buttons),
-- each naming its creature in a tooltip; the chosen look is remembered by its creature entry.
local SHAPE_ROW = 308           -- the detail pane is about 316 wide; the buttons share it
local function ShapeButton()
    local b = CreateFrame("Button", nil, detail, "UIPanelButtonTemplate")
    b:SetHeight(20)
    b:SetFrameLevel(model:GetFrameLevel() + 2)
    b:SetScript("OnClick", function(self)
        local s = view.selected
        if s and s.kind == "form" and self.form and s.form ~= self.form then
            s.form = self.form
            if self.skinRow then
                ShapeshifterDB.skins = ShapeshifterDB.skins or {}
                ShapeshifterDB.skins[C.SkinBase(Shapeshift.Forms, self.form).id] = self.form.entry
            end
            Refresh()
        end
    end)
    b:SetScript("OnEnter", function(self)
        if self.skinRow and self.creature then
            GameTooltip:SetOwner(self, "ANCHOR_TOP")
            GameTooltip:SetText(self.creature, 1, 1, 1)
            GameTooltip:Show()
        end
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    b:Hide()
    return b
end
local function SetButtonFont(b, small)
    b:SetNormalFontObject(small and "GameFontNormalSmall" or "GameFontNormal")
    b:SetHighlightFontObject(small and "GameFontHighlightSmall" or "GameFontHighlight")
    b:SetDisabledFontObject(small and "GameFontDisableSmall" or "GameFontDisable")
end
local shapeButtons = {}
for i = 1, 6 do
    shapeButtons[i] = ShapeButton()
end

local nameText = detail:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
nameText:SetPoint("TOP", model, "BOTTOM", 0, -4)
nameText:SetWidth(300)

local subText = detail:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
subText:SetPoint("TOP", nameText, "BOTTOM", 0, -2)
subText:SetWidth(300)

local kitButtons = {}
for i = 1, 12 do
    local b = CreateFrame("Button", nil, detail)
    b:SetSize(24, 24)
    local col, row = (i - 1) % 6, math.floor((i - 1) / 6)
    b:SetPoint("TOPLEFT", detail, "TOPLEFT", 78 + col * 26, -244 - row * 26)
    b.icon = b:CreateTexture(nil, "ARTWORK")
    b.icon:SetAllPoints()
    b:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetHyperlink("spell:" .. self.spellId)
        if self.tip then                                 -- the client has no text for this spell
            GameTooltip:AddLine(self.tip, 1, 0.82, 0, true)
        end
        GameTooltip:Show()
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    kitButtons[i] = b
end

local infoText = detail:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
infoText:SetPoint("TOPLEFT", detail, "TOPLEFT", 10, -300)
infoText:SetWidth(296)
infoText:SetJustifyH("LEFT")

local function Radio(name, label, x)
    local radio = CreateFrame("CheckButton", name, detail, "UIRadioButtonTemplate")
    radio:SetPoint("TOPLEFT", detail, "TOPLEFT", x, -326)
    _G[name .. "Text"]:SetText(label)
    return radio
end
local balanced = Radio("ShapeshiftModeBalanced", "Balanced", 40)
local unleashed = Radio("ShapeshiftModeUnleashed", "Unleashed", 160)
local mode = "balanced"
local function SetMode(value)
    mode = value
    balanced:SetChecked(value == "balanced")
    unleashed:SetChecked(value == "unleashed")
end
local PickMode                  -- set below, once SelectedKey exists
balanced:SetScript("OnClick", function() PickMode("balanced") end)
unleashed:SetScript("OnClick", function() PickMode("unleashed") end)
local function ModeTip(button, text)
    button:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText(text, 1, 1, 1, 1, true)
        GameTooltip:Show()
    end)
    button:SetScript("OnLeave", function() GameTooltip:Hide() end)
end
ModeTip(balanced, "Balanced: your own health and armour shaped by the form, and its spells scaled to your level.")
ModeTip(unleashed, "Unleashed: Become the NPC at full power")

local slider = CreateFrame("Slider", "ShapeshiftSizeSlider", detail, "OptionsSliderTemplate")
slider:SetWidth(200)
slider:SetPoint("TOP", detail, "TOP", 0, -366)
slider:SetMinMaxValues(10, 100)
slider:SetValueStep(5)
_G["ShapeshiftSizeSliderLow"]:SetText("10%")
_G["ShapeshiftSizeSliderHigh"]:SetText("100%")

-- The slider reaches as far as the server takes (Protocol.MAX_SIZE: 200% on a size200 server).
local function SizeRange()
    local _, high = slider:GetMinMaxValues()
    if high ~= Shapeshift.Protocol.MAX_SIZE then
        slider:SetMinMaxValues(10, Shapeshift.Protocol.MAX_SIZE)
        _G["ShapeshiftSizeSliderHigh"]:SetText(Shapeshift.Protocol.MAX_SIZE .. "%")
    end
end
local size = 100
local settingSlider = false     -- true while the menu itself moves the slider
local SliderMoved               -- set below, once IsCurrent exists
slider:SetScript("OnValueChanged", function(self, value)
    size = math.floor(value / 5 + 0.5) * 5
    _G["ShapeshiftSizeSliderText"]:SetText("Size: " .. size .. "% of true size")
    if not settingSlider and SliderMoved then
        SliderMoved(size)
    end
end)

local function ActionButton(label, width, x)
    local b = CreateFrame("Button", nil, detail, "UIPanelButtonTemplate")
    b:SetSize(width, 22)
    b:SetPoint("BOTTOMLEFT", detail, "BOTTOMLEFT", x, 4)
    b:SetText(label)
    return b
end
local favorite = ActionButton("Favorite", 96, 4)
local talents = CreateFrame("Button", nil, detail, "UIPanelButtonTemplate")
talents:SetSize(70, 20)
talents:SetPoint("TOPRIGHT", detail, "TOPRIGHT", -2, -296)
talents:SetText("Talents")
local flag = ActionButton("Flag for curation", 116, 102)
local transform = ActionButton("Transform", 96, 220)

-- ------------------------------------------------------------------ behaviour

local function SelectedKey()
    local s = view.selected
    if not s then
        return nil
    end
    return s.kind == "form" and C.FormKey(s.form) or C.CreatureKey(s.entry)
end

local function SelectedEntry()
    local s = view.selected
    return s and (s.kind == "form" and s.form.entry or s.entry)
end

local function IsFull()
    local s = view.selected
    return s and s.kind == "form" and C.IsReleased(s.form, Shapeshift.ReleaseWave)
end

local function IsCurrent()
    local state = Shapeshift.state
    return state.active and state.entry == SelectedEntry()
end

PickMode = function(value)
    SetMode(value)
    C.RememberMode(ShapeshifterDB, SelectedKey(), value)
    Refresh()                   -- the ability row shows the mode's spells
end

-- Dragging the slider on the form you are wearing resizes you as it moves (servers that can).
SliderMoved = function(newSize)
    if IsCurrent() and Shapeshift.Resize(newSize) then
        C.Remember(ShapeshifterDB, SelectedKey(), mode, newSize)
    end
end

favorite:SetScript("OnClick", function()
    local key = SelectedKey()
    if key then
        C.ToggleFavorite(ShapeshifterDB, key)
        Refresh()
    end
end)

flag:SetScript("OnClick", function()
    local s = view.selected
    if s and s.kind == "creature" then
        local now = C.ToggleFlag(ShapeshifterDB, s.entry, s.name, time())
        Shapeshift.Print(s.name .. (now and " flagged for curation." or " is no longer flagged."))
        Refresh()
    end
end)

transform:SetScript("OnClick", function()
    local s = view.selected
    if not s then
        return
    end
    if IsCurrent() then
        Shapeshift.Revert()
        return
    end
    C.Remember(ShapeshifterDB, SelectedKey(), mode, size)
    if IsFull() then
        Shapeshift.Apply(s.form, mode, size)
    else
        Shapeshift.Look(SelectedEntry(), size)
    end
end)

talents:SetScript("OnClick", function()
    local s = view.selected
    if s and s.kind == "form" then
        Shapeshift.ToggleTalents(s.form)
    end
end)

transform:SetScript("OnEnter", function(self)
    if not self:IsEnabled() then
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        if not Shapeshift.ServerReady() then
            GameTooltip:SetText(Shapeshift.NOT_READY, 1, 1, 1, 1, true)
        else
            GameTooltip:SetText("Not in combat.", 1, 1, 1, 1, true)
        end
        GameTooltip:Show()
    end
end)
transform:SetScript("OnLeave", function() GameTooltip:Hide() end)

local function ShowDetail()
    local s = view.selected
    if not s then
        detail:Hide()
        return
    end
    detail:Show()

    local entry = SelectedEntry()
    if model.entry ~= entry then
        model.entry = entry
        model.viewKey = C.ViewKey(s)
        facing = 0
        bigIcon:Hide()
        bigIcon:SetTexture(s.kind == "form" and s.form.icon or NEUTRAL_ICON)
        LoadModel(entry, s.kind == "form" and s.form or nil)
    end

    local base = s.kind == "form" and (s.base or s.form)
    local shapes = base and C.Shapes(Shapeshift.Forms, base) or {}
    local skinRow = false
    if base and #shapes < 2 then                 -- shapes and skins never share an archetype
        local looks = C.Skins(Shapeshift.Forms, base)
        if #looks > 1 then
            shapes, skinRow = looks, true
        end
    end
    local width = math.min(84, math.floor(SHAPE_ROW / math.max(1, #shapes)) - 4)
    for i, b in ipairs(shapeButtons) do
        local shape = #shapes > 1 and shapes[i]
        if shape then
            b:SetWidth(width)
            b:ClearAllPoints()
            b:SetPoint("TOP", model, "TOP", (i - (#shapes + 1) / 2) * (width + 4), 0)
            b.form = shape
            b.skinRow = skinRow
            SetButtonFont(b, skinRow)
            if skinRow then
                b:SetText(C.SkinLabel(C.SkinBase(Shapeshift.Forms, shape), shape))
                b.creature = shape.skinCreature or shape.name
            else
                b:SetText(shape.shape or shape.label)
                b.creature = nil
            end
            if shape == s.form then
                b:Disable()
            else
                b:Enable()
            end
            b:Show()
        else
            b.form = nil
            b:Hide()
        end
    end

    local full = IsFull()
    local lines = {}
    if s.kind == "form" then
        nameText:SetText(s.form.label)
        subText:SetText("Level " .. s.form.level .. ", " .. C.PoolLabel(s.form.pool))
        if full then
            lines[#lines + 1] = "Profile: " .. string.gsub(s.form.profile, "_", " ")
            if #s.form.passives > 0 then
                local names = {}
                for _, id in ipairs(s.form.passives) do
                    names[#names + 1] = (GetSpellInfo(id)) or ("spell " .. id)
                end
                lines[#lines + 1] = "Passives: " .. table.concat(names, ", ")
            end
            if s.form.flies then
                lines[#lines + 1] = "Flies."
            end
        else
            lines[#lines + 1] = "Look only until this form's wave is released."
        end
    else
        nameText:SetText(s.name)
        subText:SetText("Level " .. s.level .. ", creature " .. s.entry)
        lines[#lines + 1] = "Look only: model, size and name."
        if ShapeshifterDB.flagged[s.entry] then
            lines[#lines + 1] = "Flagged for curation."
        end
    end
    infoText:SetText(table.concat(lines, "\n"))

    -- A class-grade form shows each ability's own spell at the player's band, as its bar will: the
    -- form's icon, name and tooltip, not the borrowed source spell's.
    local cg = full and Shapeshift.ClassGradeFor(s.form)
    for i, b in ipairs(kitButtons) do
        local id = full and s.form.kit[i]
        if id then
            local shown = C.Mapped(id, cg, UnitLevel("player"), mode ~= "unleashed")
            local _, _, texture = GetSpellInfo(shown)
            if not texture then                          -- the client patch is older than the data
                shown = id
                _, _, texture = GetSpellInfo(id)
            end
            b.spellId = shown
            b.tip = shown == id and s.form.tips and s.form.tips[id] or nil
            b.icon:SetTexture(texture or "Interface\\Icons\\INV_Misc_QuestionMark")
            b:Show()
        else
            b:Hide()
        end
    end

    local choice = C.Choice(ShapeshifterDB, SelectedKey())
    if detail.key ~= SelectedKey() then
        detail.key = SelectedKey()
        SetMode(choice.mode)
        settingSlider = true
        slider:SetValue(IsCurrent() and Shapeshift.state.size or choice.size)
        settingSlider = false
    end
    ShowIf(balanced, full)
    ShowIf(unleashed, full)

    favorite:SetText(ShapeshifterDB.favorites[SelectedKey()] and "Unfavorite" or "Favorite")
    ShowIf(flag, s.kind == "creature")
    ShowIf(talents, full)
    -- An open talent window follows the selection (user, 2026-09-24); a plain creature has none.
    if Shapeshift.TalentsShown and Shapeshift.TalentsShown() then
        if full then
            Shapeshift.ShowTalents(s.form)
        else
            Shapeshift.HideTalents()
        end
    end
    flag:SetText(s.kind == "creature" and ShapeshifterDB.flagged[s.entry] and "Unflag" or "Flag for curation")

    transform:SetText(IsCurrent() and "Revert" or "Transform")
    if Shapeshift.ServerReady() and not InCombatLockdown() then
        transform:Enable()
    else
        transform:Disable()
    end
end

-- The grid in rows: header rows between icon rows, GRID_ROWS of them from view.top. Returns the
-- page shown, the page count and whether it can move back and on.
local function ShowGrid(forms)
    local all = C.Rows(C.Group(forms, ShapeshifterDB.grouping), GRID_COLS)
    local slice
    slice, view.top = C.Window(all, view.top, GRID_ROWS)
    for i, cell in ipairs(cells) do
        local r, c = math.floor((i - 1) / GRID_COLS) + 1, (i - 1) % GRID_COLS + 1
        local line = slice[r]
        local form = line and line.forms and line.forms[c]
        if form then
            cell.form = form
            cell.icon:SetTexture(form.icon)
            local released = C.IsReleased(form, Shapeshift.ReleaseWave)
            cell.icon:SetDesaturated(not released)
            ShowIf(cell.lookOnly, not released)
            local starred = false
            for _, shape in ipairs(C.Members(Shapeshift.Forms, form)) do
                starred = starred or (ShapeshifterDB.favorites[C.FormKey(shape)] and true or false)
            end
            ShowIf(cell.star, starred)
            ShowIf(cell.selected, view.selected and view.selected.kind == "form"
                and (view.selected.base or view.selected.form) == form)
            cell.name:SetText(form.label)
            cell:Show()
        else
            cell:Hide()
        end
    end
    for r, label in ipairs(headers) do
        local line = slice[r]
        label:SetText(line and line.header or "")
        ShowIf(label, line and line.header)
    end
    for _, row in ipairs(rows) do
        row:Hide()
    end
    local pages = math.max(1, math.ceil(#all / GRID_ROWS))
    local last = view.top + GRID_ROWS - 1 >= #all
    local page = last and pages or math.floor((view.top - 1) / GRID_ROWS) + 1
    return page, pages, view.top > 1, not last
end

local function ShowList(creatures)
    local slice, pages = C.Page(creatures, view.page, LIST_ROWS)
    view.page = math.min(math.max(1, view.page), pages)
    for i, row in ipairs(rows) do
        local creature = slice[i]
        if creature then
            row.creature = creature
            local star = ShapeshifterDB.favorites[C.CreatureKey(creature.entry)]
                and "|T" .. STAR .. ":12:12:0:0:32:32:0:16:0:16|t " or ""
            row.name:SetText(star .. creature.name)
            row.level:SetText(creature.level)
            ShowIf(row.selected, view.selected and view.selected.kind == "creature"
                and view.selected.entry == creature.entry)
            row:Show()
        else
            row:Hide()
        end
    end
    for _, cell in ipairs(cells) do
        cell:Hide()
    end
    for _, label in ipairs(headers) do
        label:Hide()
    end
    return pages
end

Refresh = function()
    if not frame:IsShown() then
        return
    end
    view.pool = view.pool or C.ValidPool(ShapeshifterDB.pool)
    SizeRange()
    groupButton:SetText(C.GroupingShort(ShapeshifterDB.grouping))
    ShowIf(groupButton, view.pool ~= "creature")
    for _, tab in ipairs(tabs) do
        tab:SetChecked(tab.pool.key == view.pool)
    end
    poolTitle:SetText(C.PoolLabel(view.pool))
    art:SetTexture(C.PoolArt(view.pool))

    local page, pages, canPrev, canNext
    if view.pool == "creature" then
        local list
        if view.search == "" then
            list = C.FavoriteCreatures(Shapeshift.Creatures, ShapeshifterDB.favorites)
            empty:SetText(#list == 0 and "Type at least two letters to search every creature. Favorites show here." or "")
        else
            list = C.SearchCreatures(Shapeshift.Creatures, view.search, SEARCH_LIMIT)
            empty:SetText(#list == 0 and "No creature matches." or "")
        end
        pages = ShowList(list)
        page = view.page
        canPrev, canNext = page > 1, page < pages
    else
        local forms = C.FormsFor(Shapeshift.Forms, view.pool, view.search, ShapeshifterDB.favorites, Shapeshift.ReleaseWave)
        empty:SetText(C.EmptyText(view.pool, view.search, forms, C.Group(forms, ShapeshifterDB.grouping)))
        page, pages, canPrev, canNext = ShowGrid(forms)
    end
    pageText:SetText("Page " .. page .. " / " .. pages)
    if canPrev then prev:Enable() else prev:Disable() end
    if canNext then nextPage:Enable() else nextPage:Disable() end

    status:SetText(Shapeshift.ServerReady() and "" or "Not confirmed on this character: /ss status to retry.")
    ShowDetail()
end

function Shapeshift.ToggleCatalogue()
    if frame:IsShown() then
        frame:Hide()
    else
        frame:Show()
        Refresh()
    end
end

frame:SetScript("OnShow", function() Refresh() end)
-- Closing the menu drops the puppet; the next open loads the preview afresh.
frame:SetScript("OnHide", function()
    Shapeshift.PuppetOff()
    model.entry = nil
    model.puppetWait, model.puppetDraws = nil, nil
end)
Shapeshift.OnStateChange(function()
    -- A shape switched from the boss bar: the open detail pane follows it.
    local s, worn = view.selected, Shapeshift.CurrentForm()
    if s and s.base and worn and (worn == s.base or worn.visageOf == s.base.id
            or C.SkinBase(Shapeshift.Forms, worn) == s.base) then                     -- one of its shapes or looks
        s.form = worn
    end
    Refresh()
end)

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_REGEN_DISABLED")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:SetScript("OnEvent", function() Refresh() end)
