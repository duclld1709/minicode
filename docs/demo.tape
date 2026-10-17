# Record the README demo GIF with vhs (https://github.com/charmbracelet/vhs), from the repo root:
#   vhs docs/demo.tape
# Requires a configured .env (MINICODE_PROVIDER, MINICODE_MODEL, API key); one run costs about $0.10.
# The demo edits files, so it works on a throwaway copy of buggy_calculator in .demo/ (git-ignored).
#
# Shell: on Windows, vhs resolves "bash" to WSL (C:\Windows\System32\bash.exe), which does not see
# the Windows uv, so this tape uses PowerShell. On Linux/macOS, change it to `Set Shell bash`;
# every command below works in both shells.

Output docs/demo.gif
Set Shell powershell
Set FontSize 15
Set Width 1300
Set Height 760
Set TypingSpeed 35ms

Hide
Type `uv run python -c "import shutil; shutil.rmtree('.demo', ignore_errors=True); shutil.copytree('examples/buggy_calculator', '.demo', ignore=shutil.ignore_patterns('.pytest_cache', '__pycache__', 'traces'))"`
Enter
Sleep 3s
Type "clear"
Enter
Show

Type "uv run minicode run 'Fix the failing tests' --cwd .demo --mode accept-edits --verify 'pytest -q'"
Sleep 500ms
Enter
# accept-edits still asks before running commands: answer "always" for run_bash.
# Wait on the cursor line (+Line), not +Screen: long output scrolls and +Screen stops seeing new text.
Wait+Line@1m /\[y\]es/
Type "a"
Enter
# Plain Wait = until the shell prompt returns, i.e. the run (and its --verify check) has finished.
Wait@3m
Sleep 4s

Type "uv run minicode replay --cwd .demo"
Enter
Sleep 6s
