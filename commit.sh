#!/bin/bash

# Configuration
REPO_PATH="/workspaces/core/config/custom_components/manage_energy"  # Repository root in the devcontainer
COMMIT_MESSAGE=$1                                                   # Commit message describing the changes

# Validate commit message
if [ -z "$COMMIT_MESSAGE" ]; then
  echo "Usage: ./commit.sh <commit_message>"
  exit 1
fi

# Step 1: Stage and commit changes
echo "Staging changes..."
pushd .
cd $REPO_PATH
git add .
echo "Committing changes with message: $COMMIT_MESSAGE"
git commit -m "$COMMIT_MESSAGE"

# Step 2: Push changes to GitHub
echo "Pushing changes to the remote repository..."
git push origin main

echo "Changes successfully committed and pushed to GitHub!"
popd