# Installation & first run

*[Español](#español) below.*

## Requirements

- Python ≥ 3.10 (tested with 3.11 on macOS; Linux and Windows supported)
- Optional but recommended: [Ollama](https://ollama.com) for local models,
  or any OpenAI-compatible server (llama.cpp `--server`, vLLM, …)

## Install (development)

```bash
git clone https://github.com/Sebastardito/SwarmblyApp.git
cd SwarmblyApp
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The install pulls `swarmbly-v0` and `swarmbly-lce` from GitHub at the exact
commits declared in `pyproject.toml`.

## First run

```bash
swarmbly-app                       # serves on http://127.0.0.1:8765 and opens the browser
```

The first-run assistant checks your system (OS, CPU, RAM, storage, GPU —
unknown when undetectable), shows detected models and recommendations, and
explains the privacy defaults (everything LOCAL). The app never downloads
models: install one with `ollama pull llama3.2:3b` if you want real inference.

## Headless (worker-friendly)

```bash
swarmbly-app headless              # node without a window
swarmbly-app init                  # show data dir and node identity
```

## Data locations

| OS | Data directory |
|---|---|
| macOS | `~/Library/Application Support/Swarmbly` |
| Linux | `~/.local/share/swarmbly` (or `$XDG_DATA_HOME/swarmbly`) |
| Windows | `%APPDATA%\Swarmbly` |

Override with `--data-dir` or the `SWARMBLY_DATA_DIR` environment variable.

## Troubleshooting

- **"No inference backend detected"** — start Ollama (`ollama serve`) or set
  an OpenAI-compatible URL in Settings → Models.
- **Port already in use** — `swarmbly-app --port 8766`.
- **Where are my conversations?** — SQLite at `<data>/app.db`; exports at
  `<data>/output/exports/`.

---

## Español

Requisitos: Python ≥ 3.10 y, recomendado, Ollama o un servidor compatible con
OpenAI. Instala con `pip install -e ".[dev]"` dentro de un entorno virtual y
ejecuta `swarmbly-app`; la interfaz queda en `http://127.0.0.1:8765`. El
asistente de primer arranque comprueba el sistema, muestra los modelos
detectados y explica los valores de privacidad (todo LOCAL por defecto). La
app nunca descarga modelos. Los datos viven en el directorio por sistema
operativo indicado arriba; usa `--data-dir` o `SWARMBLY_DATA_DIR` para
cambiarlo.
