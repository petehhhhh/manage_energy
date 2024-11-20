#!/bin/bash

# Ensure a commit message is provided
if [ -z "$1" ]; then
    echo "Error: Commit message is required."
    echo "Usage: $0 <commit_message>"
    exit 1
fi

# Stage and commit changes
git add /workspaces/manage_energy
git commit -m "$1"
if [ $? -ne 0 ]; then
    echo "Git commit failed. Exiting."
    exit 1
fi

# Push changes to GitHub
git push origin main
if [ $? -ne 0 ]; then
    echo "Git push failed. Exiting."
    exit 1
fi

# Copy files to Home Assistant's custom_components directory
sudo cp -r /workspaces/manage_energy/custom_components/manage_energy /tmp/supervisor_data/homeassistant/custom_components
if [ $? -ne 0 ]; then
    echo "Copy failed. Exiting."
    exit 1
fi

# for ha core restart to work, need to have supervisor_run running background...

ha core restart
if [ $? -ne 0 ]; then
    echo "ha core start failed. Make sure supervisor_run has been started in background."
    exit 1
fi



echo "Script completed successfully."



