"""Store and recall a fact in an isolated, temporary Memty vault."""
from pathlib import Path
from tempfile import TemporaryDirectory

from memty import open_ledger


def main() -> None:
    with TemporaryDirectory(prefix="memty-example-") as directory:
        vault = open_ledger(path=Path(directory) / "vault.sqlite3")
        try:
            vault.record("demo.project", "editor", "VS Code",
                         verification_state="USER_CONFIRMED")
            capsule = vault.context("editor", provider="openai",
                                    namespace="demo.project", strict_namespace=True)
            print("Cloud-filtered capsule:")
            print(capsule["text"])

            vault.record("demo.project", "editor", "Vim",
                         verification_state="USER_CONFIRMED")
            print("History entries:", len(vault.history("demo.project", "editor")))
            vault.forget("demo.project", "editor", purge_raw=True)
            print("Active facts after forgetting:", len(vault.list(namespace="demo.project")))
        finally:
            vault.close()


if __name__ == "__main__":
    main()
