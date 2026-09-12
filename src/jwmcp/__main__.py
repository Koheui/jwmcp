"""python -m jwmcp            → MCP server (stdio)
python -m jwmcp settings   → local settings UI (http://127.0.0.1:8765)
"""
import sys


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "settings":
        from .settings_ui import run
        port = 8765
        host = "127.0.0.1"
        open_browser = "--no-browser" not in args
        for i, a in enumerate(args):
            if a == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
            if a == "--host" and i + 1 < len(args):
                host = args[i + 1]
        run(host=host, port=port, open_browser=open_browser)
        return
    from .server import main as serve
    serve()


main()
