"""Optional HTTP API entry point for Memty's temporal memory ledger."""

from memoryport.api import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
