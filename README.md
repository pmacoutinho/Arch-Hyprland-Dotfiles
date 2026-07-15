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
├── rofi/              # Application launcher theme
├── scripts/           # Utility scripts (VPN, screen keyboard, etc.)
├── starship/          # Shell prompt
└── tmux/              # Terminal multiplexer
```

## Installation

### Prerequisites

```bash
sudo pacman -S stow hyprland kitty rofi starship tmux cava
```

### Clone and stow

```bash
cd ~/Documents
git clone https://github.com/pmacoutinho/Arch-Hyprland-Dotfiles.git
cd Arch-Hyprland-Dotfiles

# Stow everything
stow bash hypr hyprpanel kitty rofi cava starship scripts tmux

# Or stow individual packages
stow hypr
stow kitty
```

To remove symlinks for a package:

```bash
stow -D hypr
```

## Post-install

- **HyprPanel weather**: Replace `YOUR_API_KEY_HERE` in `hyprpanel/.config/hyprpanel/config.json` with your [OpenWeatherMap](https://openweathermap.org/api) API key.
- **Wallpaper**: Place your wallpaper at `~/.config/wallpapers/sushi-dark.png` or update the path in `hypr/.config/hypr/hyprpaper.conf`.
- **Tmux plugins**: Install [TPM](https://github.com/tmux-plugins/tpm), then press `prefix + I` to install plugins.

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
