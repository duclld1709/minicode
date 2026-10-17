# Record the README demo GIF with vhs (https://github.com/charmbracelet/vhs):
#   vhs docs/demo.tape
# Requires a configured .env (MINICODE_PROVIDER, MINICODE_MODEL, API key).
# The demo edits files, so it works on a throwaway copy of buggy_calculator.

Output docs/demo.gif
Set Shell bash
Set FontSize 15
Set Width 1300
Set Height 760
Set TypingSpeed 35ms

Hide
Type "rm -rf /tmp/demo && cp -r examples/buggy_calculator /tmp/demo && clear"
Enter
Show

Type "uv run minicode run 'Fix the failing tests' --cwd /tmp/demo --mode accept-edits --verify 'pytest -q'"
Sleep 500ms
Enter
# accept-edits still asks before running commands: answer "always" for run_bash
Wait+Screen /\[y\]es/
Type "a"
Enter
Wait+Screen@3m /verified after/
Sleep 4s

Type "uv run minicode replay --cwd /tmp/demo"
Enter
Sleep 6s
