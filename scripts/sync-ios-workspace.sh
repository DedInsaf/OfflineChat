#!/bin/sh
# Copy the iOS sources into the actual synchronized Xcode target folder.
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
workspace_dir=${1:-/Users/insafnurtdinov/OfflineChat}
test -f "$workspace_dir/OfflineChat.xcodeproj/project.pbxproj"
test -d "$workspace_dir/OfflineChat"
rsync -a --exclude='.DS_Store' "$repo_dir/ios/OfflineChat/" "$workspace_dir/OfflineChat/"
