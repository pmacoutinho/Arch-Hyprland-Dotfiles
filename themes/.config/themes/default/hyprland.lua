-- Default theme: window borders and the compositor background (see colors in
-- ~/.config/hypr/hyprland.lua). Applied at startup and live by theme-set.
hl.config({
    general = {
        col = {
            active_border   = { colors = { "rgb(F5C2E7)", "rgba(26233aff)" }, angle = 30 },
            inactive_border = "rgba(1f1d2eff)",
        },
    },
    -- sushi-dark.png is ~80% #1D1C28: matches the gap shown before hyprpaper attaches.
    misc = { background_color = "rgb(1d1c28)" },
})
