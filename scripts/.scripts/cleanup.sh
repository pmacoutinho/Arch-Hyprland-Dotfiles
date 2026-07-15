#!/bin/bash
set -e

echo "=== Disk Cleanup Script ==="
echo "Current usage:"
df -h /
echo ""

# Docker: reclaim ~6.5G (removes unused images, build cache, networks)
echo "--- Pruning Docker ---"
docker system prune -a -f

# Pacman cache: reclaim ~3G (keep only 1 version of each package)
echo "--- Cleaning pacman cache (keeping 1 version) ---"
sudo paccache -rk1

# Journal logs: reclaim ~2.8G
echo "--- Vacuuming journal logs ---"
sudo journalctl --vacuum-size=200M

# Yay build cache: reclaim ~1.4G
echo "--- Cleaning yay build cache ---"
yay -Sc --noconfirm

# Orphan packages: reclaim variable space
echo "--- Removing orphan packages ---"
orphans=$(pacman -Qdtq 2>/dev/null) || true
if [ -n "$orphans" ]; then
    sudo pacman -Rns --noconfirm $orphans
else
    echo "No orphan packages found."
fi

echo ""
echo "=== Cleanup complete ==="
df -h /
