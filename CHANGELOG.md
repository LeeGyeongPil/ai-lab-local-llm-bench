# Changelog

## 0.2.1

- Fixed: `OLLAMA_HOST`/`--host` without a port (e.g. `127.0.0.1`, `localhost`) now uses Ollama's default port 11434 instead of 80, and `0.0.0.0` connects via `127.0.0.1`. An explicit `http://`/`https://` without a port keeps the default 80/443.

## 0.2.0

- Added: English and Korean screen language (`--lang en|ko`, `LLMBENCH_LANG`, then `LC_ALL`/`LC_MESSAGES`/`LANG`). Help, progress lines, the summary table and errors are translated; JSONL results and exit codes are unchanged.
- Added: English `README.md` and Korean `README.ko.md` with per-language screenshots.
- Changed: tests run with pytest.

## 0.1.1

- Added: check that the requested models exist on the server before measuring.

## 0.1.0

- First release: measures local Ollama speed split into queue, load, prefill and decode, with a mock mode.
