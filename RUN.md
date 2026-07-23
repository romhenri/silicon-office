# Run

## Run command

Starts the daemon in the background, then the frontend in the foreground; the daemon is stopped automatically when the frontend exits. Absolute paths, so this works from any folder — e.g. Desktop:

```bash
/Users/romuloduarte/GameDev/silicon-office/.venv/bin/claude-vo-daemon & pid=$!; /Users/romuloduarte/GameDev/silicon-office/.venv/bin/claude-vo-frontend; kill $pid
```

## Alias

Add to `~/.zshrc` to run both from any folder with a single command:

```bash
vo() {
  /Users/romuloduarte/GameDev/silicon-office/.venv/bin/claude-vo-daemon &
  local pid=$!
  /Users/romuloduarte/GameDev/silicon-office/.venv/bin/claude-vo-frontend
  kill $pid
}
```

`vo` is already installed in `~/.zshrc`. To reload it and launch in one shot from any folder:

```bash
source ~/.zshrc && vo
```
