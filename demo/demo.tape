# Demo recording for the README. Re-render with:  make demo  (vhs → PNG frames → ffmpeg GIF)
# `make demo` points KRYSTAL_DATA_DIR at a scratch copy of the local history db so
# sparklines / deltas show; no wallet or keys, so nothing personal is on screen.
# Needs network (Krystal + rhpools feeds).

Output demo/frames/

Set Shell zsh
Set FontSize 12
Set Width 1880
Set Height 940
Set Padding 8
Set TypingSpeed 40ms
Set PlaybackSpeed 1.0

Env KRYSTAL_WALLET ""
Env KRYSTAL_CLOUD_KEY ""
Env TELEGRAM_BOT_TOKEN ""

Type "uv run krystal-curator tui --images halfcell --reconcile"
Sleep 800ms
Enter
Sleep 22s

# browse: cursor moves, detail pane follows
Down Sleep 700ms
Down Sleep 700ms
Down Sleep 1500ms

# risk profiles 1-4
Type "4" Sleep 2s
Type "3" Sleep 2s
Type "2" Sleep 2s

# sort: cycle column (SCORE → RK → AGE), flip direction
Type "s" Sleep 1500ms
Type "s" Sleep 1500ms
Type "S" Sleep 2s
Type "S" Sleep 800ms

# star a pool, show starred only, back
Type "*" Sleep 1200ms
Type "W" Sleep 2s
Type "W" Sleep 1200ms

# find
Type "/" Sleep 500ms
Type "ETH" Sleep 2500ms
Escape Sleep 1500ms

# links popup for the selected pool
Type "l" Sleep 2500ms
Escape Sleep 1200ms

# position size drives MY$/D and NET$/D
Type "$" Sleep 500ms
Ctrl+U
Type "20000" Sleep 500ms
Enter Sleep 2500ms

Type "q"
Sleep 1s
