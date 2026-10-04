# Online chat: selection, scrolling and UI work

These changes affect the online clients only; the Bluetooth chat and server data
are unchanged.

## Selection

- iPhone: long press → Select. Mac: right click → Select.
- Stock circle/checkmark icons live in a fixed gutter, so bubble positions do not
  jump when selection starts. Selected rows have a subtle theme-coloured tint.
- A separate action bar shows the count, Copy, Forward and Cancel. Zero selected
  messages disables actions, but does not silently exit selection.
- Selection intercepts taps before links, photo viewers and audio/video players.
- iPhone does not allow entering selection while a recording or recording draft
  is active, to avoid destroying the recording composer.

## Scroll policy

- First opening starts at the bottom, including when history arrives after the
  first layout. Mac repeats tail placement after delayed preview sizing.
- Incoming messages follow the tail only while the reader is already near the
  bottom (64 pixels/points). Reading older messages does not force a scroll.
- Sending a new message returns to the bottom. Receipt updates do not scroll.
- Moving up exposes a small down-arrow button above the composer. Clicking it
  returns to the latest message; at the bottom it disappears.
- Mac trackpad deltas are pixel-based and coalesced over 16 ms rather than
  scrolling by a fraction of the window height for every event.

## Performance changes

- iOS sync merges a batch before publishing messages/profiles/peers. Unchanged
  typing, connection and message values no longer trigger redundant publications.
- Duplicate events and older receipt states are ignored. Status-only changes
  do not sort the entire history again. Read acknowledgements update only the
  IDs included in that request, not messages arriving during the request.
- Equatable iPhone bubbles avoid re-evaluating unchanged media during selection
  and parent updates. Photo/avatar decoding runs off the main thread with ImageIO
  downsampling and a bounded 32 MiB / 64-entry thumbnail cache.
- Mac photo decoding and videonote thumbnail generation share a two-worker pool.
  Opening a history no longer launches an ffmpeg process for every videonote at
  the same time. All Tk updates remain on its UI thread.
- Presence-only Mac profile updates no longer invalidate/rebuild the chat list
  or write the profile cache; name, bio and avatar edits still refresh it.

## Checks

Run Python regressions with the Mac environment and `PYTHONPATH=macos`:

```sh
python -m unittest discover -s tests -v
sh scripts/test-ios-message-merge.sh
```

Build the synchronized Xcode target after running
`sh scripts/sync-ios-workspace.sh`. On a real iPhone check empty-cache opening,
keyboard opening/closing, dragging history while messages arrive, selecting a
photo/link/voice message, and returning down after media finishes loading.

Automated checks and successful compilation do not measure scrolling frame rate
on a physical iPhone or real server/network latency.
