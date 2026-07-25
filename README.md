# Arch Hyprland Dotfiles

Personal configuration files for my Arch Linux setup running the Hyprland Wayland compositor.

![Arch](https://img.shields.io/badge/Arch_Linux-1793D1?style=flat&logo=arch-linux&logoColor=white)
![Hyprland](https://img.shields.io/badge/Hyprland-58E1FF?style=flat&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## Overview

| Component | Tool |
|-----------|------|
| WM | [Hyprland](https://hyprland.org/) |
| Bar | [HyprPanel](https://hyprpanel.com/) |
| Terminal | [Kitty](https://sw.kovidgoyal.net/kitty/) |
| Launcher | [Rofi](https://github.com/davatorium/rofi) |
| Shell Prompt | [Starship](https://starship.rs/) |
| Lock Screen | [Hyprlock](https://github.com/hyprwm/hyprlock) |
| Idle Daemon | [Hypridle](https://github.com/hyprwm/hypridle) |
| Wallpaper | [Hyprpaper](https://github.com/hyprwm/hyprpaper) |
| Multiplexer | [Tmux](https://github.com/tmux/tmux) |
| Editor | [Neovim](https://neovim.io/) |
| Audio Visualizer | [Cava](https://github.com/karlstav/cava) |
| Color Scheme | Rosé Pine / Catppuccin Mocha |

## Structure

Managed with [GNU Stow](https://www.gnu.org/software/stow/). Each top-level directory is a stow package.

```
dotfiles/
├── bash/              # Shell configuration
├── cava/              # Audio visualizer + shaders
├── hypr/              # Hyprland, hyprlock, hypridle, hyprpaper
├── hyprpanel/         # Bar config, custom modules, styling
├── kitty/             # Terminal emulator
├── nvim/              # Neovim (git submodule -> Neovim-Configuration)
├── rofi/              # Application launcher theme
├── scripts/           # Utility scripts (VPN, screen keyboard, etc.)
├── starship/          # Shell prompt
└── tmux/              # Terminal multiplexer
```

Each package mirrors the layout it gets linked into, so `kitty/.config/kitty`
lands at `~/.config/kitty`. The `nvim` package is a
[git submodule](https://github.com/pmacoutinho/Neovim-Configuration) rather than
plain files — it lives in its own repository so it can be cloned standalone.

## Installation

### Prerequisites

```bash
sudo pacman -S stow hyprland kitty rofi starship tmux cava neovim tree-sitter-cli
```

`tree-sitter-cli` is required by the Neovim config — `nvim-treesitter` needs it
to build parsers. Neovim 0.12+ is also required.

### Clone and stow

```bash
cd ~/Documents
git clone --recurse-submodules https://github.com/pmacoutinho/Arch-Hyprland-Dotfiles.git
cd Arch-Hyprland-Dotfiles

# Stow everything
stow -t ~ bash hypr hyprpanel kitty nvim rofi cava starship scripts tmux

# Or stow individual packages
stow -t ~ hypr
stow -t ~ kitty
```

`--recurse-submodules` matters: without it the `nvim` package clones as an empty
directory. If you already cloned without it, run `git submodule update --init`.

`-t ~` also matters. Stow defaults its target to the *parent of the stow
directory*, so running plain `stow hypr` from `~/Documents/Arch-Hyprland-Dotfiles`
creates symlinks in `~/Documents` instead of `~`, and nothing in your real home
directory ends up managed. Always pass `-t ~`.

To remove symlinks for a package:

```bash
stow -D -t ~ hypr
```

## Post-install

- **HyprPanel weather**: Replace `YOUR_API_KEY_HERE` in `hyprpanel/.config/hyprpanel/config.json` with your [OpenWeatherMap](https://openweathermap.org/api) API key.
- **Wallpaper**: Place your wallpaper at `~/.config/wallpapers/sushi-dark.png` or update the path in `hypr/.config/hypr/hyprpaper.conf`.
- **Tmux plugins**: Install [TPM](https://github.com/tmux-plugins/tpm), then press `prefix + I` to install plugins.
- **Neovim**: On first launch [lazy.nvim](https://github.com/folke/lazy.nvim) installs the plugins and `nvim-treesitter` compiles its parsers. Let it finish, then restart. Check with `:checkhealth`.

## Updating the Neovim submodule

The `nvim` package points at a specific commit of
[Neovim-Configuration](https://github.com/pmacoutinho/Neovim-Configuration).
Editing config files through `~/.config/nvim` edits the submodule, so changes are
committed there first, then the pointer is bumped here:

```bash
cd ~/.config/nvim
git add -A && git commit -m "..." && git push

cd ~/Documents/dotfiles
git add nvim/.config/nvim && git commit -m "Bump nvim config" && git push
```

Skipping the second step leaves this repo pointing at the old commit. To pull
someone else's newer nvim config instead:

```bash
git submodule update --remote nvim/.config/nvim
```

## Custom VPN Module

HyprPanel includes a custom VPN module with three states:

| State | Color | Description |
|-------|-------|-------------|
| Proton VPN | `#a6e3a1` | Connected via Proton VPN |
| Custom VPN | `#b4befe` | Connected via OpenVPN |
| Disconnected | `#f38ba8` | No VPN active |

Clicking the module connects/disconnects automatically.

## Acknowledgments

- [Hyprland](https://hyprland.org/)
- [HyprPanel](https://hyprpanel.com/)
- [Catppuccin](https://github.com/catppuccin)
- [Rosé Pine](https://rosepinetheme.com/)
