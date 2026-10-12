"""Command-line entry point: ``swarmbly-app``.

Default: start the backend and open the local web UI. ``headless`` runs the
service without a browser — the engine and the UI are separate processes
(user requirement E: a node must work without a window).
"""

from __future__ import annotations

import argparse
import sys
import webbrowser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="swarmbly-app",
        description="Swarmbly App — decentralized AI client and network dashboard")
    parser.add_argument("command", nargs="?", default="serve",
                        choices=["serve", "headless", "status", "init"],
                        help="serve (default, opens the UI) | headless (no UI) | status | init")
    parser.add_argument("--data-dir", default=None,
                        help="override the per-OS data directory")
    parser.add_argument("--port", type=int, default=None,
                        help="override the API port (default 8765)")
    parser.add_argument("--host", default=None,
                        help="API bind address (default 127.0.0.1)")
    args = parser.parse_args(argv)

    from .state import AppState

    if args.command == "init":
        state = AppState(args.data_dir)
        print(f"Swarmbly App initialized.")
        print(f"  data directory: {state.dirs.root}")
        print(f"  node id:        {state.identity.node_id}")
        print(f"  config:         {state.dirs.config_path()}")
        return 0

    state = AppState(args.data_dir)
    if args.command == "status":
        for key, value in state.health().items():
            print(f"{key:14} {value}")
        return 0

    api_cfg = state.config.get("api")
    host = args.host or api_cfg.get("host", "127.0.0.1")
    port = args.port or api_cfg.get("port", 8765)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("Warning: binding the admin interface to a non-loopback address "
              "exposes it to the local network. The P2P service has its own "
              "independent access limits.", file=sys.stderr)

    from .api import create_app
    app = create_app(state)

    if args.command == "serve":
        url = f"http://{host}:{port}/"
        webbrowser.open(url)

    import uvicorn
    print(f"Swarmbly App {__import__('swarmbly_app').__version__} "
          f"— http://{host}:{port}/ (node {state.identity.short_id(12)})")
    try:
        uvicorn.run(app, host=host, port=port, log_level="info",
                    access_log=False)
    except KeyboardInterrupt:
        pass
    finally:
        state.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
