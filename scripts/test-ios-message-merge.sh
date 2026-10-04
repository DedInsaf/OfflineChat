#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_dir=$(mktemp -d /private/tmp/offlinechat-swift-tests.XXXXXX)
# Only our newly created temporary directory is cleaned up.
trap 'rm -f "$test_dir/message-merge"; rmdir "$test_dir"' EXIT
xcrun swiftc "$repo_dir/ios/OfflineChat/Online/OnlineModels.swift" \
    "$repo_dir/ios/OfflineChat/Online/OnlineMessageContent.swift" \
    "$repo_dir/ios/OfflineChat/Online/OnlineMessageMerge.swift" \
    "$repo_dir/tests/swift/message_merge/main.swift" -o "$test_dir/message-merge"
"$test_dir/message-merge"
