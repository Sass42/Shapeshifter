-- Shapeshift soundboard (user, 2026-09-27): above the chat window, while you are a form whose
-- creature really speaks, one button per spoken line, labelled with its text. The server plays the
-- line and says or yells it as you, so everyone near hears and reads it. A line cannot start until
-- the last one has finished (its length comes from the sound file, Forms.lua `voices`).

local P = Shapeshift.Protocol
local ROW, GAP, PAD = 16, 1, 6

local board = CreateFrame("Frame", "ShapeshiftVoiceBoard", UIParent)
board:SetFrameStrata("LOW")
board:SetBackdrop({
    bgFile = "Interface\\ChatFrame\\ChatFrameBackground",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    tile = true, tileSize = 16, edgeSize = 12,
    insets = { left = 3, right = 3, top = 3, bottom = 3 },
})
board:SetBackdropColor(0, 0, 0, 0.55)
board:SetBackdropBorderColor(0.4, 0.4, 0.4, 0.8)
board:Hide()

local title = board:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
title:SetPoint("TOPLEFT", PAD, -PAD)
title:SetJustifyH("LEFT")

local busyUntil = nil
local buttons = {}

local function Button(i)
    if buttons[i] then
        return buttons[i]
    end
    local b = CreateFrame("Button", "ShapeshiftVoiceButton" .. i, board)
    b:SetHeight(ROW)
    b:SetPoint("TOPLEFT", PAD, -(PAD + ROW + (i - 1) * (ROW + GAP)))
    b:SetPoint("RIGHT", board, "RIGHT", -PAD, 0)
    b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    b.text = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    b.text:SetPoint("LEFT", 4, 0)
    b.text:SetPoint("RIGHT", -4, 0)
    b.text:SetJustifyH("LEFT")
    b.text:SetHeight(ROW)                    -- one line: a long one is cut, the tooltip has it all
    if b.text.SetWordWrap then
        b.text:SetWordWrap(false)
    end
    b:SetScript("OnClick", function(self)
        Shapeshift.PlayVoice(self.line)
    end)
    b:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:SetText(self.line[3] and "Yell" or "Say", 1, 0.82, 0)
        GameTooltip:AddLine(self.line[4], 1, 1, 1, true)
        GameTooltip:AddLine(string.format("%.1f sec", self.line[2]), 0.6, 0.6, 0.6)
        GameTooltip:Show()
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
    buttons[i] = b
    return b
end

-- Greyed while a line plays, white again once it has finished.
local function Dim()
    local ready = P.VoiceReady(busyUntil, GetTime())
    for _, b in ipairs(buttons) do
        if ready then
            b.text:SetTextColor(1, 1, 1)
        else
            b.text:SetTextColor(0.5, 0.5, 0.5)
        end
    end
    return ready
end

board:SetScript("OnUpdate", function(self)
    if busyUntil and Dim() then
        busyUntil = nil
    end
end)

function Shapeshift.PlayVoice(line)
    local ready, left = P.VoiceReady(busyUntil, GetTime())
    if not ready then
        Shapeshift.ShowError(string.format("Wait for the line to finish (%d sec).", math.ceil(left)))
        return
    end
    if not Shapeshift.ServerReady() or not Shapeshift.caps.voice then
        Shapeshift.ShowError("This server's Shapeshifter cannot play voice lines yet.")
        return
    end
    Shapeshift.Send(P.BuildVoice(line[1]))
    busyUntil = GetTime() + line[2]
    Dim()
end

local function Refresh()
    local form = Shapeshift.CurrentForm()
    local lines = form and form.voices
    if not lines or #lines == 0 or not Shapeshift.caps.voice then
        board:Hide()
        return
    end
    title:SetText(form.label .. ": voice lines")
    for i, line in ipairs(lines) do
        local b = Button(i)
        b.line = line
        b.text:SetText(line[4])
        b:Show()
    end
    for i = #lines + 1, #buttons do
        buttons[i]:Hide()
    end
    local anchor = ChatFrame1 or DEFAULT_CHAT_FRAME
    board:ClearAllPoints()
    board:SetPoint("BOTTOMLEFT", anchor, "TOPLEFT", -4, 28)
    board:SetPoint("BOTTOMRIGHT", anchor, "TOPRIGHT", 4, 28)
    board:SetHeight(PAD * 2 + ROW + #lines * (ROW + GAP))
    Dim()
    board:Show()
end

Shapeshift.OnStateChange(Refresh)
Shapeshift.OnCaps(Refresh)                  -- the server's CAPS come after its ON on login
