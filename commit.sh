#!/bin/bash

# Configuration
REPO_PATH="/workspaces/core/config/custom_components/manage_energy"  # Repository root in the devcontainer
COMMIT_MESSAGE=$1                                                   # Commit message describing the changes

# Validate commit message
if [ -z "$COMMIT_MESSAGE" ]; then
  echo "Usage: ./commit.sh <commit_message>"
  exit 1
fi

# Step 1: Navigate to the repository
echo "Navigating to repository: $REPO_PATH"
pushd .
cd $REPO_PATH

# Step 2: Pull the latest changes
echo "Pulling latest changes from the remote repository..."
git fetch origin main
if ! git merge --no-edit origin/main; then
  echo "Merge conflict detected. Please resolve conflicts manually."
  popd
  exit 1
fi

# Step 3: Stage and commit changes
echo "Staging changes..."
git add .
echo "Committing changes with message: $COMMIT_MESSAGE"
if ! git commit -m "$COMMIT_MESSAGE"; then
  echo "No changes to commit."
fi

# Step 4: Push changes to GitHub
echo "Pushing changes to the remote repository..."
if ! git push origin main; then
  echo "Push failed. Ensure the repository is in sync and retry."
  popd
  exit 1
fi

echo "Changes successfully committed and pushed to GitHub!"
popd