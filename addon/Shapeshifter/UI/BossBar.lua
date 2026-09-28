-- Shapeshift boss bar: while you are a full form, twelve secure buttons take the place of your
-- main action bar and your 1 to = keys (whatever is bound to ACTIONBUTTON1-12) press them.
-- Nothing on your real bars is written or moved: the real buttons are only hidden, and the keys
-- are only overridden, both undone on revert. Secure frames cannot change in combat, so a
-- change that arrives in combat waits for PLAYER_REGEN_ENABLED.

local CastPlan = Shapeshift.CastPlan
local SIZE, GAP = 36, 6

local bar = CreateFrame("Frame", "ShapeshiftBossBar", UIParent)
bar:SetSize(12 * SIZE + 11 * GAP, SIZE)
bar:SetPoint("BOTTOMLEFT", ActionButton1, "BOTTOMLEFT")
-- Above the stance and possess bar (BonusActionBarFrame is HIGH): whatever else appears there
-- while you are the boss, these buttons stay on top.
bar:SetFrameStrata("HIGH")
bar:SetFrameLevel(BonusActionBarFrame:GetFrameLevel() + 10)
bar:Hide()

local buttons = {}
for i = 1, 12 do
    local b = CreateFrame("Button", "ShapeshiftBossButton" .. i, bar, "SecureActionButtonTemplate")
    b:SetSize(SIZE, SIZE)
    b:SetPoint("LEFT", (i - 1) * (SIZE + GAP), 0)
    b:RegisterForClicks("AnyUp")

    b.icon = b:CreateTexture(nil, "BACKGROUND")
    b.icon:SetAllPoints()

    local normal = b:CreateTexture(nil, "ARTWORK")
    normal:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    normal:SetSize(SIZE * 66 / 36, SIZE * 66 / 36)
    normal:SetPoint("CENTER", 0, -1)
    b:SetNormalTexture(normal)
    b:SetPushedTexture("Interface\\Buttons\\UI-Quickslot-Depress")
    b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")

    b.cooldown = CreateFrame("Cooldown", nil, b, "CooldownFrameTemplate")
    b.cooldown:SetAllPoints()

    b.hotkey = b:CreateFontString(nil, "OVERLAY", "NumberFontNormalSmallGray")
    b.hotkey:SetPoint("TOPRIGHT", -2, -2)

    b:SetScript("OnEnter", function(self)
        if self.spellId then
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:SetHyperlink("spell:" .. self.spellId)
            GameTooltip:Show()
        end
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    -- Drag an ability onto another slot to swap them (user, 2026-09-27: customise the hotbar), out of
    -- combat; the layout is kept per form. A click still casts: only a drag moves.
    b:RegisterForDrag("LeftButton")
    b.index = i
    buttons[i] = b
end

local Layout                        -- set below: swaps two slots of the current form's layout
local dragFrom = nil
local dragIcon = UIParent:CreateTexture(nil, "OVERLAY")
dragIcon:SetSize(SIZE, SIZE)
dragIcon:Hide()
local dragger = CreateFrame("Frame")
dragger:Hide()
dragger:SetScript("OnUpdate", function()
    local x, y = GetCursorPosition()
    local scale = UIParent:GetEffectiveScale()
    dragIcon:ClearAllPoints()
    dragIcon:SetPoint("CENTER", UIParent, "BOTTOMLEFT", x / scale, y / scale)
end)

for _, b in ipairs(buttons) do
    b:SetScript("OnDragStart", function(self)
        if InCombatLockdown() or not self.spellId then
            return
        end
        dragFrom = self.index
        dragIcon:SetTexture(self.icon:GetTexture())
        dragIcon:Show()
        dragger:Show()
    end)
    b:SetScript("OnDragStop", function(self)
        local from = dragFrom
        dragFrom = nil
        dragIcon:Hide()
        dragger:Hide()
        local over = GetMouseFocus and GetMouseFocus()
        if from and over and over.index and buttons[over.index] == over and over.index ~= from then
            Layout(from, over.index)
        end
    end)
end

-- A form's shapes (user, 2026-09-24): like a druid's forms, one button per shape on a stance bar
-- where the player's own stance bar sits (hidden meanwhile). The worn shape is checked; the
-- player's stance keys (SHAPESHIFTBUTTON1-5) pick a shape; the 10 s switch cooldown shows on all.
-- Not secure: a click only sends a command, and the switch refuses in combat.
-- Weapon stances (deep pass B2) follow the shapes on the same bar and keys.
local STANCE_SIZE, STANCE_GAP, MAX_SHAPES, MAX_STANCES = 30, 7, 5, 3
local MAX_BUTTONS = MAX_SHAPES + MAX_STANCES
local stanceBar = CreateFrame("Frame", "ShapeshiftStanceBar", UIParent)
stanceBar:SetSize(MAX_BUTTONS * (STANCE_SIZE + STANCE_GAP), STANCE_SIZE)
if ShapeshiftButton1 then
    stanceBar:SetPoint("BOTTOMLEFT", ShapeshiftButton1, "BOTTOMLEFT")
else
    stanceBar:SetPoint("BOTTOMLEFT", bar, "TOPLEFT", 0, 12)
end
stanceBar:SetFrameStrata("HIGH")
stanceBar:Hide()

local function AddTalents(form)
    local talents = form.talentInfo or {}
    if #talents == 0 then
        return
    end
    GameTooltip:AddLine("Bonuses", 1, 0.82, 0)
    for _, talent in ipairs(talents) do
        GameTooltip:AddLine(talent.name .. ": " .. talent.text, 1, 1, 1, true)
    end
end

local function AddKit(form)
    local names = {}
    for _, id in ipairs(form.kit or {}) do
        names[#names + 1] = (GetSpellInfo(id)) or ("spell " .. id)
    end
    if #names > 0 then
        GameTooltip:AddLine("Abilities", 1, 0.82, 0)
        GameTooltip:AddLine(table.concat(names, ", "), 1, 1, 1, true)
    end
end

local stanceButtons = {}
for i = 1, MAX_BUTTONS do
    local b = CreateFrame("CheckButton", "ShapeshiftStanceButton" .. i, stanceBar)
    b:SetSize(STANCE_SIZE, STANCE_SIZE)
    b:SetPoint("LEFT", (i - 1) * (STANCE_SIZE + STANCE_GAP), 0)
    b:RegisterForClicks("AnyUp")
    b.icon = b:CreateTexture(nil, "BACKGROUND")
    b.icon:SetAllPoints()
    local normal = b:CreateTexture(nil, "ARTWORK")
    normal:SetTexture("Interface\\Buttons\\UI-Quickslot2")
    normal:SetSize(STANCE_SIZE * 64 / 36, STANCE_SIZE * 64 / 36)
    normal:SetPoint("CENTER", 0, -1)
    b:SetNormalTexture(normal)
    b:SetPushedTexture("Interface\\Buttons\\UI-Quickslot-Depress")
    b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
    b:SetCheckedTexture("Interface\\Buttons\\CheckButtonHilight", "ADD")
    b.cooldown = CreateFrame("Cooldown", nil, b, "CooldownFrameTemplate")
    b.cooldown:SetAllPoints()
    b.hotkey = b:CreateFontString(nil, "OVERLAY", "NumberFontNormalSmallGray")
    b.hotkey:SetPoint("TOPRIGHT", -1, -2)
    b:SetScript("OnClick", function(self)
        -- A CheckButton toggles itself on click; the state follows the worn shape instead.
        self:SetChecked(self.worn)
        if self.stance then
            Shapeshift.SwitchStance(self.stance)
        elseif self.form and not self.worn then
            Shapeshift.SwitchVisage(self.form)
        end
    end)
    b:SetScript("OnEnter", function(self)
        if self.stance then
            GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
            GameTooltip:SetText(self.stanceName, 1, 1, 1)
            if self.worn then
                GameTooltip:AddLine("Your current stance.", 0.5, 1, 0.5)
            else
                GameTooltip:AddLine("Take this stance: its weapons, bonus and abilities. Works in combat.",
                    0.8, 0.8, 0.8, true)
            end
            GameTooltip:Show()
            return
        end
        if not self.form then
            return
        end
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText(self.form.label .. (self.form.shape and (" (" .. self.form.shape .. ")") or ""), 1, 1, 1)
        if self.worn then
            GameTooltip:AddLine("Your current shape.", 0.5, 1, 0.5)
        else
            GameTooltip:AddLine("Change to this shape. 10 sec cooldown; not in combat.", 0.8, 0.8, 0.8, true)
        end
        AddKit(self.form)
        AddTalents(self.form)
        GameTooltip:Show()
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    stanceButtons[i] = b
end

-- The player's own stance bar is hidden in every full form with their other bars (HideOwnBars).
local function HideStances()
    ClearOverrideBindings(stanceBar)
    stanceBar:Hide()
end

-- The bar's entries: the form's shapes (when it has two or more), then its weapon stances.
local function StanceEntries(form)
    local entries = {}
    local shapes = form and Shapeshift.Catalogue and Shapeshift.Catalogue.Shapes(Shapeshift.Forms, form) or {}
    if #shapes >= 2 then
        for _, shape in ipairs(shapes) do
            entries[#entries + 1] = { form = shape, icon = shape.icon, worn = shape == form }
        end
    end
    local cg = form and Shapeshift.ClassGradeFor and Shapeshift.ClassGradeFor(form)
    local current = (Shapeshift.state or {}).stance
    if cg and cg.stances and current then
        for n, stance in ipairs(cg.stances) do
            entries[#entries + 1] = { stance = n, name = stance.name, icon = stance.icon, worn = n == current }
        end
    end
    return entries
end

-- Only the checks: safe in combat, where a stance may change (no bindings are touched).
local function CheckStances(state)
    local current = state.stance
    for _, b in ipairs(stanceButtons) do
        if b.stance then
            b.worn = b.stance == current
            b:SetChecked(b.worn)
        end
    end
end

local function ShowStances()
    local form = Shapeshift.CurrentForm and Shapeshift.CurrentForm()
    local entries = StanceEntries(form)
    if #entries == 0 then
        HideStances()
        return
    end
    ClearOverrideBindings(stanceBar)
    for i, b in ipairs(stanceButtons) do
        local entry = entries[i]
        b.form, b.stance, b.stanceName = entry and entry.form, entry and entry.stance, entry and entry.name
        if entry then
            b.worn = entry.worn
            b.icon:SetTexture(entry.icon)
            b:SetChecked(b.worn)
            local key = GetBindingKey("SHAPESHIFTBUTTON" .. i)
            b.hotkey:SetText(key and GetBindingText(key, "KEY_", true) or "")
            if key then
                SetOverrideBindingClick(stanceBar, true, key, b:GetName())
            end
            if entry.form and Shapeshift.visageSwitchedAt then
                CooldownFrame_SetTimer(b.cooldown, Shapeshift.visageSwitchedAt, Shapeshift.Catalogue.VISAGE_COOLDOWN, 1)
            end
            b:Show()
        else
            b.worn = false
            b:Hide()
        end
    end
    stanceBar:Show()
end

-- What the spellbook holds right now: each spell id's slot, and every name.
local function ScanSpellbook()
    local slotOf, names = {}, {}
    local i = 1
    while true do
        local name = GetSpellName(i, BOOKTYPE_SPELL)
        if not name then
            break
        end
        local link = GetSpellLink(i, BOOKTYPE_SPELL)
        local id = link and tonumber(string.match(link, "Hspell:(%d+)"))
        if id then
            slotOf[id] = i
        end
        names[i] = { id = id, name = name }
        i = i + 1
    end
    return slotOf, names
end

local hidBonusBar = false
local realHidden = nil          -- each real button's own statehidden while ours cover it

-- Your other bars and your stance bar hold your own abilities, which a form cannot cast (user,
-- 2026-09-24: "you just see the forms"). All are hidden while ours show. On revert the bars that
-- were showing come back, and the stance bar follows the client's own rule (ShapeshiftBar_Update:
-- shown whenever you have stances), so a stance bar the client re-showed or re-hid mid-form does
-- not stay lost (user as Alexstrasza, 2026-09-24).
local OWN_BARS = { "MultiBarBottomLeft", "MultiBarBottomRight", "MultiBarRight", "MultiBarLeft", "ShapeshiftBarFrame" }
local inForm = false
local hidBars = {}              -- name -> true for each bar that was showing when we hid it

for _, name in ipairs(OWN_BARS) do
    local frame = _G[name]
    if frame then
        -- The client re-shows these (bar options, UPDATE_SHAPESHIFT_FORMS); keep them down in form.
        frame:HookScript("OnShow", function(self)
            if inForm and not InCombatLockdown() then
                self:Hide()
            end
        end)
    end
end

local function HideOwnBars()
    if not inForm then
        hidBars = {}
    end
    inForm = true
    for _, name in ipairs(OWN_BARS) do
        local frame = _G[name]
        if frame and frame:IsShown() then
            hidBars[name] = true
            frame:Hide()
        end
    end
end

local function ShowOwnBars()
    if not inForm then
        return
    end
    inForm = false
    for name in pairs(hidBars) do
        if name ~= "ShapeshiftBarFrame" and _G[name] then
            _G[name]:Show()
        end
    end
    if ShapeshiftBarFrame then
        if type(ShapeshiftBar_Update) == "function" then
            ShapeshiftBar_Update()
        elseif hidBars.ShapeshiftBarFrame then
            ShapeshiftBarFrame:Show()
        end
    end
    hidBars = {}
end

-- The client's ActionButton_Update and ActionButton_ShowGrid show any main-bar button that holds
-- an action (learning the form's spells fires them) unless its "statehidden" attribute is set,
-- so a plain Hide() does not last. statehidden is what the client's own vehicle bar uses.
local function ShowRealBar()
    for i = 1, 12 do
        local b = _G["ActionButton" .. i]
        if realHidden then
            b:SetAttribute("statehidden", realHidden[i])
        end
        if ActionButton_Update then
            ActionButton_Update(b)     -- shows or hides it by the client's own rules
        else
            b:Show()
        end
    end
    realHidden = nil
    if hidBonusBar then
        hidBonusBar = false
        BonusActionBarFrame:Show()
    end
    ShowOwnBars()
end

local function HideRealBar()
    if not realHidden then
        realHidden = {}
        for i = 1, 12 do
            realHidden[i] = _G["ActionButton" .. i]:GetAttribute("statehidden") or false
        end
    end
    for i = 1, 12 do
        local b = _G["ActionButton" .. i]
        b:SetAttribute("statehidden", true)
        b:Hide()
    end
    if BonusActionBarFrame:IsShown() then
        hidBonusBar = true
        BonusActionBarFrame:Hide()
    end
    HideOwnBars()
end

-- The keys of your other bars and bar pages still reach your own abilities while those bars are
-- hidden (user, 2026-09-27: none of your own abilities in a form): in form they press a button
-- that does nothing.
local noop = CreateFrame("Button", "ShapeshiftBossNoop", bar)
local BLOCKED = { "NEXTACTIONPAGE", "PREVIOUSACTIONPAGE" }
for i = 1, 12 do
    for _, name in ipairs({ "MULTIACTIONBAR1BUTTON", "MULTIACTIONBAR2BUTTON", "MULTIACTIONBAR3BUTTON",
                            "MULTIACTIONBAR4BUTTON", "BONUSACTIONBUTTON" }) do
        BLOCKED[#BLOCKED + 1] = name .. i
    end
end
for i = 1, 6 do
    BLOCKED[#BLOCKED + 1] = "ACTIONPAGE" .. i
end

local function BlockOwnKeys()
    for _, name in ipairs(BLOCKED) do
        local key1, key2 = GetBindingKey(name)
        if key1 then
            SetOverrideBindingClick(bar, true, key1, "ShapeshiftBossNoop")
        end
        if key2 then
            SetOverrideBindingClick(bar, true, key2, "ShapeshiftBossNoop")
        end
    end
end

local function Clear()
    ClearOverrideBindings(bar)
    bar:Hide()
    HideStances()
    for _, b in ipairs(buttons) do
        b.spellId, b.spellName, b.slot = nil, nil, nil
        b:SetAttribute("type", nil)
        b:SetAttribute("spell", nil)
        b:SetAttribute("macrotext", nil)
    end
    ShowRealBar()
end

local function Build(kit)
    local slotOf, book = ScanSpellbook()
    local inKit = {}
    for _, id in pairs(kit) do          -- slot -> spell id; a laid-out bar may leave gaps
        inKit[id] = true
    end
    local ownNames = {}
    for _, entry in pairs(book) do
        if not (entry.id and inKit[entry.id]) then
            ownNames[entry.name] = true
        end
    end
    local info = { ownNames = ownNames, hasCastByID = type(CastSpellByID) == "function" }

    ClearOverrideBindings(bar)
    BlockOwnKeys()                  -- first, so a key also bound to an ACTIONBUTTON ends on ours
    for i, b in ipairs(buttons) do
        local id = kit[i]
        if id then
            local name, _, texture = GetSpellInfo(id)
            info.slot = slotOf[id]
            local attrs = CastPlan.Choose({ id = id, name = name or "" }, info)
            b:SetAttribute("type", attrs.type)
            b:SetAttribute("spell", attrs.spell)
            b:SetAttribute("macrotext", attrs.macrotext)
            b.spellId, b.spellName, b.slot = id, name, info.slot
            b.icon:SetTexture(texture or "Interface\\Icons\\INV_Misc_QuestionMark")
            b:Show()
        else
            b.spellId, b.spellName, b.slot = nil, nil, nil
            b:SetAttribute("type", nil)
            b:Hide()
        end
        -- Every key of the real button presses ours, used or not: while you are the boss, the
        -- bar's empty slots stay empty rather than falling through to your own spells.
        local key1, key2 = GetBindingKey("ACTIONBUTTON" .. i)
        b.hotkey:SetText(key1 and GetBindingText(key1, "KEY_", true) or "")
        if key1 then
            SetOverrideBindingClick(bar, true, key1, b:GetName())
        end
        if key2 then
            SetOverrideBindingClick(bar, true, key2, b:GetName())
        end
    end
    HideRealBar()
    bar:Show()
    ShowStances()
end

local pending = nil

-- The bar holds the kit, then the current weapon stance's own abilities (deep pass B2), in the
-- player's own layout for this form where they set one (ShapeshifterDB.barLayout[form id]: slot ->
-- spell id). An ability the layout does not place fills the first free slot.
local function LayoutKey()
    local form = Shapeshift.CurrentForm and Shapeshift.CurrentForm()
    return form and form.id
end

local function BarKit(state)
    local kit = {}
    for _, id in ipairs(state.kit or {}) do
        kit[#kit + 1] = id
    end
    for _, id in ipairs(state.stanceKit or {}) do
        kit[#kit + 1] = id
    end
    return CastPlan.ArrangeBar(kit, ShapeshifterDB and ShapeshifterDB.barLayout
        and ShapeshifterDB.barLayout[LayoutKey() or ""], #buttons)
end

local function Update(state)
    CheckStances(state)
    if InCombatLockdown() then
        pending = state
        return
    end
    pending = nil
    local kit = BarKit(state)
    if state.active and not state.look and next(kit) then
        Build(kit)
    else
        Clear()
    end
end

local function UpdateCooldowns()
    for _, b in ipairs(buttons) do
        if b.spellName and b:IsShown() then
            local start, duration, enable = GetSpellCooldown(b.spellName)
            if start then
                CooldownFrame_SetTimer(b.cooldown, start, duration, enable)
            end
        end
    end
end

-- Dimmed like the stock bar (ActionButton_UpdateUsable, ActionButton_OnUpdate): blue when the
-- resource is short, grey when unusable for another reason, a red hotkey when the target is out
-- of range. By spellbook slot when the spell has one, so a same-named spell of your own is not read.
local RANGE_RED, HOTKEY_GREY = { 1, 0.1, 0.1 }, { 0.6, 0.6, 0.6 }

local function UpdateUsable()
    for _, b in ipairs(buttons) do
        if b.spellName and b:IsShown() then
            local usable, noPower, inRange
            if b.slot then
                usable, noPower = IsUsableSpell(b.slot, BOOKTYPE_SPELL)
                inRange = IsSpellInRange(b.slot, BOOKTYPE_SPELL, "target")
            else
                usable, noPower = IsUsableSpell(b.spellName)
                inRange = IsSpellInRange(b.spellName, "target")
            end
            if usable then
                b.icon:SetVertexColor(1, 1, 1)
            elseif noPower then
                b.icon:SetVertexColor(0.5, 0.5, 1)
            else
                b.icon:SetVertexColor(0.4, 0.4, 0.4)
            end
            local color = inRange == 0 and RANGE_RED or HOTKEY_GREY
            b.hotkey:SetVertexColor(color[1], color[2], color[3])
        end
    end
end

Shapeshift.OnStateChange(Update)

Layout = function(from, to)
    local key = LayoutKey()
    if not key or InCombatLockdown() then
        return
    end
    ShapeshifterDB.barLayout = ShapeshifterDB.barLayout or {}
    local slots = {}
    for i, b in ipairs(buttons) do
        slots[i] = b.spellId
    end
    slots[from], slots[to] = slots[to], slots[from]
    local layout = {}
    for i = 1, #buttons do
        if slots[i] then
            layout[i] = slots[i]
        end
    end
    ShapeshifterDB.barLayout[key] = layout
    Update(Shapeshift.state)
end

-- Back to the form's own order: /ss bar reset.
function Shapeshift.ResetBarLayout()
    local key = LayoutKey()
    if key and ShapeshifterDB.barLayout then
        ShapeshifterDB.barLayout[key] = nil
        Update(Shapeshift.state)
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:RegisterEvent("SPELL_UPDATE_COOLDOWN")
for _, event in ipairs({ "SPELL_UPDATE_USABLE", "ACTIONBAR_UPDATE_USABLE", "PLAYER_TARGET_CHANGED",
                         "UNIT_MANA", "UNIT_RAGE", "UNIT_ENERGY" }) do
    pcall(events.RegisterEvent, events, event)
end
events:SetScript("OnEvent", function(self, event, unit)
    if event == "PLAYER_REGEN_ENABLED" then
        if pending then
            Update(pending)
        end
    elseif event == "SPELL_UPDATE_COOLDOWN" then
        UpdateCooldowns()
    elseif not unit or unit == "player" or event == "PLAYER_TARGET_CHANGED" then
        UpdateUsable()
    end
end)

-- Range changes as you move, with no event: checked five times a second while the bar shows.
local sinceRange = 0
bar:SetScript("OnUpdate", function(self, elapsed)
    sinceRange = sinceRange + elapsed
    if sinceRange >= 0.2 then
        sinceRange = 0
        UpdateUsable()
    end
end)
