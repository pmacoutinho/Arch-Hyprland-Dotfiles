#!/bin/bash
set -e

echo "=== Disk Cleanup Script ==="
echo "Current usage:"
df -h /
echo ""

# Docker: reclaim ~6.5G (removes unused images, build cache, networks)
echo "--- Pruning Docker ---"
docker system prune -a -f

# Buildx builders: reclaim ~8.5G (docker system prune does not reach the
# cache of docker-container builders such as mec-builder)
echo "--- Pruning Docker buildx builder caches ---"
builders=$(docker buildx ls --format json 2>/dev/null \
    | python3 -c 'import sys, json; [print(json.loads(l)["Name"]) for l in sys.stdin if l.strip()]') || true
for builder in $builders; do
    echo "Builder: $builder"
    docker buildx prune --builder "$builder" --all -f || true
done

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
