"""Run the CrusaderBot FastAPI control plane."""


def main() -> None:
    """Entrypoint wrapper for `python -m ...scripts.run_api`."""
    from projects.polymarket.polyquantbot.server.main import main as run_server
    run_server()


if __name__ == "__main__":
    main()
