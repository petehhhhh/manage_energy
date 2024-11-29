#!/bin/bash

# Configuration
REPO_PATH="/workspaces/core/config/custom_components/manage_energy"  # Repository root in the devcontainer
HACS_FILE="$REPO_PATH/hacs.json"            # Path to hacs.json
MANIFEST_FILE="$REPO_PATH/manifest.json"    # Path to manifest.json
COMMIT_MESSAGE=$1                           # Commit message describing the changes

# Validate commit message
if [ -z "$COMMIT_MESSAGE" ]; then
  echo "Usage: ./commit_and_release.sh <commit_message>"
  exit 1
fi

# Step 1: Auto-increment version
if [ -f "$HACS_FILE" ]; then
  CURRENT_VERSION=$(jq -r ".version" "$HACS_FILE")
  if [ -z "$CURRENT_VERSION" ] || [ "$CURRENT_VERSION" = "null" ]; then
    echo "No valid version found in hacs.json. Initializing version to 1.0.0."
    CURRENT_VERSION="1.0.0"
  fi
  echo "Current version: $CURRENT_VERSION"

  # Increment the patch version (e.g., 1.1.0 -> 1.1.1)
  IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
  NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
  echo "New version: $NEW_VERSION"

  # Update versions in hacs.json and manifest.json
  jq ".version = \"$NEW_VERSION\"" "$HACS_FILE" > temp_hacs.json && mv temp_hacs.json "$HACS_FILE"
  jq ".version = \"$NEW_VERSION\"" "$MANIFEST_FILE" > temp_manifest.json && mv temp_manifest.json "$MANIFEST_FILE"
else
  echo "Error: $HACS_FILE not found in $REPO_PATH"
  exit 1
fi

# Step 2: Commit, tag, and push changes
cd $REPO_PATH
git add .
git commit -m "Release v$NEW_VERSION: $COMMIT_MESSAGE"
git tag -a "v$NEW_VERSION" -m "$COMMIT_MESSAGE"
git push origin main
git push origin "v$NEW_VERSION"

# Step 3: Create GitHub release using GitHub CLI (gh)
echo "Creating GitHub release..."
gh release create "v$NEW_VERSION" --title "v$NEW_VERSION" --notes "$COMMIT_MESSAGE"

echo "Release v$NEW_VERSION successfully committed, tagged, and published to GitHub!"