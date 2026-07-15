#!/bin/bash

# Define the command used to run the On Screen Keyboard
ON_SCREEN_KEYBOARD_CMD="wvkbd-mobintl -L 200"

# Check if hyprsunset is running
if pgrep -x "wvkbd-mobintl" > /dev/null; then
    echo "On Screen Keyboard is running. Stopping it..."
    pkill -x "wvkbd-mobintl"
else
    echo "On Screen Keyboard is not running. Starting it..."
    $ON_SCREEN_KEYBOARD_CMD &
fi