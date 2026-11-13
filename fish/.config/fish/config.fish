# Theme (theme-set / SUPER+CTRL+T): fish colours, bat theme and the starship
# palette follow the current theme, and running shells switch when it changes.
function __theme_apply --on-variable __theme_generation
    set -l theme "Rosé Pine"
    set -q __theme_fish[1]; and set theme $__theme_fish
    # Fish's built-in themes have [light]/[dark] sections (all our themes are
    # dark); theme files without sections only load without the option.
    fish_config theme choose $theme --color-theme=dark 2>/dev/null
    or fish_config theme choose $theme 2>/dev/null
    set -q __theme_bat[1]; and set -gx BAT_THEME "$__theme_bat"
    or set -gx BAT_THEME Catppuccin-mocha
end
__theme_apply
test -f ~/.local/state/theme/starship.toml
and set -gx STARSHIP_CONFIG ~/.local/state/theme/starship.toml
fish_add_path --path $HOME/.local/bin
fish_add_path --path $HOME/bin
starship init fish | source
zoxide init --cmd cd fish | source
set -x fish_greeting ""
if status --is-login    
    
end
fish_add_path $HOME/.spicetify

# bun
set --export BUN_INSTALL "$HOME/.bun"
set --export PATH $BUN_INSTALL/bin $PATH
