-- Hyprland Lua config, converted from hyprland.conf (hyprlang).
-- hyprlang is deprecated since 0.55 and will be dropped in a coming release.
-- The old hyprland.conf is kept alongside this file as a fallback: Hyprland only
-- falls back to it if this file is absent, so `mv hyprland.lua hyprland.lua.bak`
-- reverts everything.
--
-- Wiki: https://wiki.hypr.land/Configuring/Start/

-- ------ Import Rosé Pine colors ------ --
-- Fallback colours only: the theme in ~/.local/state/theme/current overrides
-- them at the end of this file (switch themes with SUPER+CTRL+T / theme-set).
local rp = require("rose-pine")


------------------
---- MONITORS ----
------------------

-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })

-- External outputs mirror the laptop panel.
--
-- `mirror` is silently dropped if its target doesn't exist yet, and monitors are
-- not enumerated in a fixed order: on a boot where HDMI-A-1 comes up before
-- eDP-1, the mirror never applies and the external becomes an independent
-- monitor with its own workspaces. That is the intermittent "separate
-- workspaces" behaviour. Re-asserting on monitor.added makes it order-
-- independent, and also covers hotplug / dock / undock. A config reload adds no
-- monitors and a mirror set during the reload itself gets dropped, so reloads
-- re-assert it shortly after they finish.
local MIRROR_SRC  = "eDP-1"
local MIRROR_OUTS = { "HDMI-A-1", "DP-1" }

-- Display mode: "mirror" (default) or "extend" (externals become a second
-- screen to the right of the panel). Toggled with Fn+F3, which this HP OMEN's
-- firmware sends as SUPER+P. The mode is kept in $XDG_RUNTIME_DIR so it
-- survives config reloads but resets to mirror on a fresh login.
local MODE_FILE = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/hypr-display-mode"

local function read_display_mode()
    local f = io.open(MODE_FILE, "r")
    if not f then return "mirror" end
    local m = f:read("*l")
    f:close()
    return m == "extend" and "extend" or "mirror"
end

local display_mode = read_display_mode()

-- hl.get_monitor() returns nil for an output that is currently mirroring, so
-- look outputs up via get_monitors({ all = true }), which includes mirrors.
local function monitor_present(name)
    for _, m in ipairs(hl.get_monitors({ all = true })) do
        if m.name == name then return true end
    end
    return false
end

-- How apps see the external screen (tested 2026-11-14 with headless outputs):
--  * One that was a normal screen at some point stays known to apps through
--    mirroring: extending it (just a rule change, seamless) brings back its
--    wallpaper and bar.
--  * One that is a mirror from the moment it appears (replugged, or the
--    monitor waking up from suspend, while the mirror rule is in force) is
--    never announced: extended later it gets no wallpaper or bar, and
--    restarting the apps doesn't help. Only switching it off and on does
--    (the screen goes black ~2s).
--  * HyprPanel builds a bar ~0.5s after a screen appears. A bar built after
--    the screen became a mirror lands on the laptop panel (two bars there).
--    One built before stays with the screen, hidden while it's mirrored, and
--    shows up instantly when it's extended.
-- So a screen that goes away comes back as a normal one (login, replug,
-- waking up), and in mirror mode display-mode-refresh.sh mirrors it once its
-- bar and wallpaper are on it. SUPER+P only changes the rule. The script also
-- checks every screen has a wallpaper and one HyprPanel bar and repairs what's
-- missing (switching the screen off/on only when it was never announced).
local function mirror_rule(out)
    return { output = out, mode = "1920x1080@144", mirror = MIRROR_SRC, disabled = false }
end
local function extend_rule(out)
    -- mirror = "" is required; omitting it keeps the old mirror
    return { output = out, mode = "1920x1080@144", position = "auto-right", scale = 1,
             mirror = "", disabled = false }
end
local function mode_rule(out)
    return display_mode == "extend" and extend_rule(out) or mirror_rule(out)
end
local function is_external(name)
    for _, out in ipairs(MIRROR_OUTS) do
        if out == name then return true end
    end
    return false
end

local function apply_mirrors()
    if not monitor_present(MIRROR_SRC) then return end
    for _, out in ipairs(MIRROR_OUTS) do
        if monitor_present(out) then hl.monitor(mode_rule(out)) end
    end
end
-- For display-mode-refresh.sh: hyprctl eval 'apply_mirrors()'
_G.apply_mirrors = apply_mirrors

-- Switch a screen off, then on again as a normal screen (mirrored again in
-- mirror mode, see monitor.added), so apps get to know it.
-- For scripts: hyprctl eval 'reconnect_output("HDMI-A-1")'
local reconnecting = {}
_G.reconnect_output = function(out)
    reconnecting[out] = true
    hl.monitor({ output = out, disabled = true })
    hl.timer(function()
        reconnecting[out] = nil
        hl.monitor(extend_rule(out))
    end, { timeout = 300, type = "oneshot" })
end

-- Rebuild night mode's per-layout shader and check bars/wallpapers once the
-- monitors have settled (the script waits for that itself).
local function refresh_later(ms)
    hl.timer(function()
        hl.dispatch(hl.dsp.exec_cmd("bash ~/.scripts/display-mode-refresh.sh"))
    end, { timeout = ms, type = "oneshot" })
end

local function toggle_display_mode()
    display_mode = (display_mode == "extend") and "mirror" or "extend"
    local f = io.open(MODE_FILE, "w")
    if f then f:write(display_mode, "\n"); f:close() end
    apply_mirrors()
    refresh_later(100)
end
-- Also for scripts: hyprctl eval 'toggle_display_mode()'
_G.toggle_display_mode = toggle_display_mode

-- A screen that appeared as a normal one: in mirror mode the script mirrors
-- it once HyprPanel and hyprpaper are on it (it waits up to 5s; this timer is
-- only a safety net).
local function screen_appeared()
    if display_mode == "extend" then
        hl.timer(apply_mirrors, { timeout = 500, type = "oneshot" })
    else
        hl.timer(apply_mirrors, { timeout = 7000, type = "oneshot" })
    end
    refresh_later(300)
end
screen_appeared()
-- (Only for the real externals: display-mode-refresh.sh adds and removes a
-- headless output to make HyprPanel rebuild its bars.)
hl.on("monitor.added", function(m)
    if m and is_external(m.name) then screen_appeared() end
end)
-- Fires while the screen is still listed, hence its argument. Make it come
-- back as a normal screen (see above).
hl.on("monitor.removed", function(m)
    if not (m and is_external(m.name)) or reconnecting[m.name] then return end
    hl.monitor(extend_rule(m.name))
    refresh_later(1000)
end)
hl.on("config.reloaded", function()
    hl.timer(apply_mirrors, { timeout = 250, type = "oneshot" })
end)
-- hl.exec_cmd("hyprctl output create headless tab")
hl.monitor({ output = "tab", mode = "1920x1080@60", position = "auto-left", scale = 1 })


---------------------
---- MY PROGRAMS ----
---------------------

local terminal    = "kitty"
-- --new-window: plain `nautilus` only raises an already-open window.
local fileManager = "nautilus --new-window"
local menu        = "rofi -show drun -scroll-method 0 -terminal kitty -theme ~/.config/rofi/theme.rasi"


-------------------
---- AUTOSTART ----
-------------------

-- See https://wiki.hypr.land/Configuring/Basics/Autostart/
-- This replaces exec-once.
hl.on("hyprland.start", function()
    -- Backdrop behind the transparent bar while an app fills the screen. Started
    -- before the bar: of two surfaces in the same layer, the later one is on top.
    hl.exec_cmd("~/.scripts/bar-backdrop.py")
    -- The bar: Wayle, or HyprPanel if chosen with ~/.scripts/bar-switch
    -- (it keeps the choice in ~/.local/state/bar). A short delay keeps Wayle
    -- after the backdrop.
    local f = io.open((os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/bar", "r")
    local bar = f and f:read("*l") or "wayle"
    if f then f:close() end
    if bar == "hyprpanel" then
        hl.exec_cmd("hyprpanel")
    else
        hl.exec_cmd("sleep 0.5; wayle panel start")
    end
    hl.exec_cmd("hyprpaper")
    hl.exec_cmd("hypridle")
    -- VPN dropdown (right click on the bar's VPN buttons), kept ready so it opens at once
    hl.exec_cmd("~/.scripts/vpn-proton-menu.py --daemon")
    -- Calendar dropdown (left click on the clock), with Proton Calendar events
    hl.exec_cmd("~/.scripts/calendar-menu.py --daemon")
    -- Volume/brightness indicator, vertical like HyprPanel's (Wayle's is off).
    hl.exec_cmd("~/.scripts/osd.py")
end)


-------------------------------
---- ENVIRONMENT VARIABLES ----
-------------------------------

hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")

hl.env("LIBVA_DRIVER_NAME", "nvidia")
hl.env("MOZ_DISABLE_RDD_SANDBOX", "1")
hl.env("MOZ_ENABLE_WAYLAND", "1")


-----------------------
---- LOOK AND FEEL ----
-----------------------

-- Refer to https://wiki.hypr.land/Configuring/Basics/Variables/
hl.config({
    general = {
        -- Borders and Gaps
        border_size = 2,
        gaps_in     = 5,
        gaps_out    = 20,

        -- Colors
        col = {
            active_border   = { colors = { "rgb(F5C2E7)", rp.overlay }, angle = 30 },
            inactive_border = rp.surface,
        },
    },

    decoration = {
        rounding       = 10,
        rounding_power = 2,

        -- Change transparency of focused and unfocused windows
        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        shadow = {
            enabled      = true,
            range        = 4,
            render_power = 3,
            color        = "rgba(1a1a1aee)",
        },

        blur = {
            enabled  = true,
            size     = 3,
            passes   = 1,
            vibrancy = 0.1696,
        },
    },

    animations = {
        enabled = true,
    },
})

-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Animations/
hl.curve("easeOutQuint",   { type = "bezier", points = { {0.23, 1},    {0.32, 1}   } })
hl.curve("easeInOutCubic", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1}   } })
hl.curve("linear",         { type = "bezier", points = { {0, 0},       {1, 1}      } })
hl.curve("almostLinear",   { type = "bezier", points = { {0.5, 0.5},   {0.75, 1.0} } })
hl.curve("quick",          { type = "bezier", points = { {0.15, 0},    {0.1, 1}    } })

hl.animation({ leaf = "global",        enabled = true, speed = 10,   bezier = "default" })
hl.animation({ leaf = "border",        enabled = true, speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "windows",       enabled = true, speed = 3.55, bezier = "easeOutQuint" })
hl.animation({ leaf = "windowsIn",     enabled = true, speed = 4.1,  bezier = "easeOutQuint", style = "popin 87%" })
hl.animation({ leaf = "windowsOut",    enabled = true, speed = 1.49, bezier = "linear",       style = "popin 87%" })
hl.animation({ leaf = "fadeIn",        enabled = true, speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut",       enabled = true, speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade",          enabled = true, speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers",        enabled = true, speed = 3.81, bezier = "easeOutQuint" })
hl.animation({ leaf = "layersIn",      enabled = true, speed = 4,    bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "layersOut",     enabled = true, speed = 1.5,  bezier = "linear",       style = "fade" })
hl.animation({ leaf = "fadeLayersIn",  enabled = true, speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut", enabled = true, speed = 1.39, bezier = "almostLinear" })
hl.animation({ leaf = "workspaces",    enabled = true, speed = 1.94, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "workspacesIn",  enabled = true, speed = 1.21, bezier = "almostLinear", style = "fade" })
hl.animation({ leaf = "workspacesOut", enabled = true, speed = 1.94, bezier = "almostLinear", style = "fade" })

-- Ref https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/
-- "Smart gaps" / "No gaps when only"
hl.workspace_rule({ workspace = "w[tv1]", gaps_out = 0, gaps_in = 0 })
hl.workspace_rule({ workspace = "f[1]",   gaps_out = 0, gaps_in = 0 })

hl.window_rule({
    name        = "no-gaps-wtv1",
    match       = { float = false, workspace = "w[tv1]" },
    border_size = 0,
    rounding    = 0,
    -- No shadow either: it darkened the edge under the bar (bar-backdrop.py)
    no_shadow   = true,
})
hl.window_rule({
    name        = "no-gaps-f1",
    match       = { float = false, workspace = "f[1]" },
    border_size = 0,
    rounding    = 0,
    -- No shadow either: it darkened the edge under the bar (bar-backdrop.py)
    no_shadow   = true,
})

-- Bar backdrop (bar-backdrop.py): blur the wallpaper behind it exactly like
-- behind a translucent window (xray: wallpaper only, as windows' blur sees it),
-- so its colour matches the window under it; nothing while hidden (alpha 0).
hl.layer_rule({
    name         = "bar-backdrop",
    match        = { namespace = "^(bar-backdrop)$" },
    blur         = true,
    xray         = true,
    ignore_alpha = 0.01,
})

-- The same under the on-screen keyboard: bar-backdrop.py's strip under it
-- (the keyboard itself is transparent, see onScreenKeyboard.sh).
hl.layer_rule({
    name         = "keyboard-backdrop",
    match        = { namespace = "^(keyboard-backdrop)$" },
    blur         = true,
    xray         = true,
    ignore_alpha = 0.01,
})

-- See https://wiki.hypr.land/Configuring/Layouts/Dwindle-Layout/ for more
hl.config({
    dwindle = {
        preserve_split = true, -- You probably want this
    },
})

-- See https://wiki.hypr.land/Configuring/Layouts/Master-Layout/ for more
hl.config({
    master = {
        new_status = "master",
    },
})

hl.config({
    misc = {
        -- No default wallpaper/logo: it flashed on the external for ~0.5s when
        -- toggling mirror -> extend, before hyprpaper attached. Instead the
        -- compositor background matches the wallpaper's dominant colour
        -- (sushi-dark.png is ~80% #1D1C28), so the gap is barely visible.
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
        background_color        = "rgb(1d1c28)",
    },
})


---------------
---- INPUT ----
---------------

hl.config({
    input = {
        -- kb_layout = "us",
        kb_layout  = "pt",
        kb_variant = "",
        kb_model   = "",
        kb_options = "",
        kb_rules   = "",

        follow_mouse = 1,

        sensitivity = 0, -- -1.0 - 1.0, 0 means no modification.

        touchpad = {
            natural_scroll = true,
        },
    },
})

-- Gestures were rewritten in 0.51+; the old `gestures { workspace_swipe = false }`
-- block no longer exists. Swipe-to-switch-workspace is now opt-in per gesture:
-- hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

-- Example per-device config
-- See https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/ for more
hl.device({
    name        = "epic-mouse-v1",
    sensitivity = -0.5,
})


---------------------
---- KEYBINDINGS ----
---------------------

local mainMod = "SUPER" -- Sets "Windows" key as main modifier

-- See https://wiki.hypr.land/Configuring/Basics/Binds/ for more
hl.bind(mainMod .. " + T", hl.dsp.exec_cmd(terminal))
hl.bind(mainMod .. " + Q", hl.dsp.window.close())
hl.bind(mainMod .. " + M", hl.dsp.exit())
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(menu))
-- Fn+F3 arrives as SUPER+P (HP display-switch key): toggle mirror / extend.
-- Pseudo-tiling moved from SUPER+P to SUPER+SHIFT+P to make room.
hl.bind(mainMod .. " + P", toggle_display_mode)
hl.bind(mainMod .. " + SHIFT + P", hl.dsp.window.pseudo())

-- Themes, like Omarchy: theme picker and wallpaper picker (~/.scripts/theme-menu.py)
hl.bind(mainMod .. " + CTRL + T",             hl.dsp.exec_cmd("~/.scripts/theme-menu.py"))
hl.bind(mainMod .. " + SHIFT + CTRL + SPACE", hl.dsp.exec_cmd("~/.scripts/theme-menu.py"))
hl.bind(mainMod .. " + CTRL + SPACE",         hl.dsp.exec_cmd("~/.scripts/theme-menu.py --backgrounds"))
hl.bind(mainMod .. " + CTRL + W",             hl.dsp.exec_cmd("~/.scripts/theme-menu.py --backgrounds"))
hl.bind(mainMod .. " + G", hl.dsp.layout("swapsplit")) -- dwindle

-- ADDED BINDS
hl.bind(mainMod .. " + F", hl.dsp.exec_cmd("firefox"))
hl.bind(mainMod .. " + C", hl.dsp.exec_cmd("/home/pedro/.local/bin/hyprlock-logged"))
hl.bind(mainMod .. " + S", hl.dsp.exec_cmd("spotify-launcher"))
hl.bind("PRINT",           hl.dsp.exec_cmd("sh ~/.scripts/screenshot.sh -m region -o ~/Pictures/Screenshots/"))
-- NOTE: the .conf had `bind = $shiftMod, PRINT, ...` but $shiftMod was never defined,
-- so that bind never worked. Assuming SHIFT was intended.
hl.bind("SHIFT + PRINT",   hl.dsp.exec_cmd("sh ~/.scripts/screenshot.sh -m region -o ~/Pictures/Screenshots/"))
hl.bind(mainMod .. " + O", hl.dsp.exec_cmd("sh ~/.scripts/onScreenKeyboard.sh"))
hl.bind(mainMod .. " + D", hl.dsp.exec_cmd("gromit-mpx"))

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Move focus with mainMod + vim keys
hl.bind(mainMod .. " + H", hl.dsp.focus({ direction = "left" }))
hl.bind(mainMod .. " + L", hl.dsp.focus({ direction = "right" }))
hl.bind(mainMod .. " + K", hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + J", hl.dsp.focus({ direction = "down" }))

-- Switch workspaces with mainMod + [0-9]
-- Move active window to a workspace with mainMod + SHIFT + [0-9]
for i = 1, 10 do
    local key = i % 10 -- 10 maps to key 0
    hl.bind(mainMod .. " + " .. key,         hl.dsp.focus({ workspace = i }))
    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
end

-- Scroll through existing workspaces with mainMod + scroll
hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))

-- Move/resize windows with mainMod + LMB/RMB and dragging
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- The bar's VPN buttons shade while pressed (~/.scripts/vpn-button): stamp every
-- left-button release. Doesn't take the click (non_consuming); just a file
-- touched inside Hyprland, no process started.
local vpn_button_release = (os.getenv("XDG_RUNTIME_DIR") or "/tmp") .. "/vpn-button/release"
hl.bind("mouse:272", function()
    local f = io.open(vpn_button_release, "w")
    if f then f:close() end
end, { release = true, non_consuming = true })

-- Laptop multimedia keys for volume and LCD brightness
hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",      hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),   { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl s 10%+"),                           { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl s 10%-"),                           { locked = true, repeating = true })

-- Requires playerctl
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })


--------------------------------
---- WINDOWS AND WORKSPACES ----
--------------------------------

-- See https://wiki.hypr.land/Configuring/Basics/Window-Rules/

hl.window_rule({
    -- Ignore maximize requests from all apps. You'll probably like this.
    name  = "suppress-maximize-events",
    match = { class = ".*" },

    suppress_event = "maximize",
})

hl.window_rule({
    -- Fix some dragging issues with XWayland
    name  = "fix-xwayland-drags",
    match = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },

    no_focus = true,
})

-- GROMIT-MPX RULES
hl.workspace_rule({
    workspace = "special:gromit",
    gaps_in   = 0,
    gaps_out  = 0,
})

-- Replaces the deprecated on_created_empty workspace rule.
hl.on("workspace.created", function(ws)
    if ws.name == "special:gromit" and ws.is_empty then
        hl.exec_cmd("gromit-mpx -a")
    end
end)

hl.window_rule({
    name  = "gromit-mpx",
    match = { class = "^(Gromit-mpx)$" },

    no_blur          = true,
    no_shadow        = true,
    fullscreen_state = "0 2",
    size             = { "100%", "100%" },
    -- opacity       = "1 1",
})

-- Added window rules to make app backgrounds opaque
hl.window_rule({ name = "nautilus-opacity", match = { class = "^(org.gnome.Nautilus)$" }, opacity = "0.97 0.97" })
hl.window_rule({ name = "spotify-opacity",  match = { class = "^(Spotify.*)$" },          opacity = "0.95 0.95" })
hl.window_rule({ name = "obsidian-opacity", match = { class = "^(obsidian.*)$" },         opacity = "0.95 0.95" })


---------------
---- THEME ----
---------------

-- Window borders and background colour from the current theme (theme-set
-- applies it live with `hyprctl eval`). Skipped if no theme has been set.
local theme_colors = os.getenv("HOME") .. "/.local/state/theme/current/hyprland.lua"
local theme_file = io.open(theme_colors)
if theme_file then
    theme_file:close()
    dofile(theme_colors)
end
