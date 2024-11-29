#!/bin/bash

# Configuration
SOURCE_DIR="/workspaces/core/config/custom_components/manage_energy" # Path in devcontainer
DEST_DIR="/Users/peter/Documents/GitHub/manage_energy/custom_components/manage_energy" # Path on local PC
LOCAL_PC_USER="peter" # Local PC username
LOCAL_PC_HOST="mini.csure.me" # Local PC hostname/address
GIT_REPO_URL="git@github.com:yourusername/manage_energy.git" # GitHub repository URL
COMMIT_MESSAGE="Sync from devcontainer"

# Step 1: Copy source code to the local PC
echo "Copying files from $SOURCE_DIR to $LOCAL_PC_USER@$LOCAL_PC_HOST:$DEST_DIR ..."
scp -r $SOURCE_DIR $LOCAL_PC_USER@$LOCAL_PC_HOST:$DEST_DIR

# Step 2: SSH into the local PC to commit and push the changes
echo "Connecting to $LOCAL_PC_USER@$LOCAL_PC_HOST to commit and push changes ..."
ssh $LOCAL_PC_USER@$LOCAL_PC_HOST << EOF
  cd /Users/peter/Documents/GitHub/manage_energy
  git add .
  git commit -m "$COMMIT_MESSAGE"
  git push origin main
EOF

echo "Code synced and pushed to GitHub successfully!"