-- Shapeshift camera: while you are a form, the camera may pull back as far as the client allows,
-- so a huge form (Ragnaros, C'Thun) does not leave it inside the model, and the mouse wheel zooms
-- at the client's fastest. Your own settings are saved on the first transform and put back on
-- revert. They live in ShapeshifterDB, so a /reload or a crash mid-form still restores them at the
-- next revert.
--
-- A large form (user, 2026-09-24: "pop the camera out to max view on large forms") pulls the camera
-- all the way out when you become it: the model at its current size stands LARGE_YARDS or taller.

local UNLOCKED = { cameraDistanceMax = "50", cameraDistanceMaxFactor = "4", cameraZoomSpeed = "50" }
local SAVED = { cameraDistanceMax = "max", cameraDistanceMaxFactor = "factor", cameraZoomSpeed = "speed" }
local LARGE_YARDS = 8           -- about three times a human's height
local ALL_THE_WAY = 200         -- more than the farthest the client allows; it stops at its limit

local function Set(name, value)
    pcall(SetCVar, name, value)
end

local function HeightOf(state)
    for _, form in ipairs(Shapeshift.Forms or {}) do
        if form.entry == state.entry and form.height then
            return form.height * (state.size or 100) / 100
        end
    end
    return 0
end

local wasLarge, lastEntry = false, nil

local function Update(state)
    if not ShapeshifterDB then
        return
    end
    if state.active then
        local saved = ShapeshifterDB.camera
        if not saved then
            saved = {}
            ShapeshifterDB.camera = saved
        end
        for name, key in pairs(SAVED) do
            if saved[key] == nil then       -- a DB from 0.5.9 has no speed yet
                saved[key] = GetCVar(name)
            end
        end
        for name, value in pairs(UNLOCKED) do
            Set(name, value)
        end
        local large = HeightOf(state) >= LARGE_YARDS
        -- On becoming a large form, or growing into one with the size slider; not on every resize.
        if large and (not wasLarge or state.entry ~= lastEntry) and CameraZoomOut then
            CameraZoomOut(ALL_THE_WAY)
        end
        wasLarge, lastEntry = large, state.entry
    else
        wasLarge, lastEntry = false, nil
        if ShapeshifterDB.camera then
            local saved = ShapeshifterDB.camera
            ShapeshifterDB.camera = nil
            for name, key in pairs(SAVED) do
                if saved[key] then
                    Set(name, saved[key])
                end
            end
        end
    end
end

Shapeshift.OnStateChange(Update)
