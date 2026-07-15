#!/bin/bash

# Define the command used to run Hyprsunset
HYPRSUNSET_CMD="hyprsunset --temperature 5000"

# Check if hyprsunset is running
if pgrep -x "hyprsunset" > /dev/null; then
    echo "Hyprsunset is running. Stopping it..."
    pkill -x "hyprsunset"
else
    echo "Hyprsunset is not running. Starting it..."
    $HYPRSUNSET_CMD &
fi
