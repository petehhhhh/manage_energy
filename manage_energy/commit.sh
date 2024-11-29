#!/bin/bash

# Configuration
REPO_PATH="/workspaces/core/config/custom_components/manage_energy"  # Path to your repository
HACS_FILE="$REPO_PATH/hacs.json"                                  # Path to hacs.json
COMMIT_MESSAGE=$1                                                 # Commit message describing the changes
LOCAL_PC_USER="peter"                                             # Local PC username
LOCAL_PC_HOST="mini.csure.me"                                     # Local PC hostname/address
DEST_DIR="/Users/peter/Documents/GitHub/manage_energy"            # Path to local Git repo

# Validate commit message
if [ -z "$COMMIT_MESSAGE" ]; then
  echo "Usage: ./commit_and_release.sh <commit_message>"
  exit 1
fi

# Step 1: Auto-increment version in hacs.json
if [ -f "$HACS_FILE" ]; then
  echo "Reading current version from $HACS_FILE..."
  CURRENT_VERSION=$(jq -r ".version" "$HACS_FILE")
  echo "Current version: $CURRENT_VERSION"

  # Increment the version (e.g., 1.1.0 -> 1.1.1)
  IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
  NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
  echo "New version: $NEW_VERSION"

  # Update the version in hacs.json
  jq ".version = \"$NEW_VERSION\"" "$HACS_FILE" > temp.json && mv temp.json "$HACS_FILE"
else
  echo "Error: $HACS_FILE not found in $REPO_PATH"
  exit 1
fi

# Step 2: Copy files to local PC
echo "Copying files to local PC ($LOCAL_PC_USER@$LOCAL_PC_HOST)..."
rsync -avz --exclude="__pycache__" "$REPO_PATH" "$LOCAL_PC_USER@$LOCAL_PC_HOST:$DEST_DIR"

# Step 3: Commit and push changes from the local PC
echo "Connecting to $LOCAL_PC_HOST to commit and push changes..."
ssh $LOCAL_PC_USER@$LOCAL_PC_HOST << EOF
  cd $DEST_DIR
  git add .
  git commit -m "Release v$NEW_VERSION: $COMMIT_MESSAGE"
  git tag -a "v$NEW_VERSION" -m "$COMMIT_MESSAGE"
  git push origin main
  git push origin "v$NEW_VERSION"
EOF

echo "Release v$NEW_VERSION successfully committed and pushed!"