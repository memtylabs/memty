"""Show cloud redaction and a local-routing refusal using fictional data."""
from pathlib import Path
from tempfile import TemporaryDirectory

from memty import LocalRoutingRequired, open_ledger


def main() -> None:
    with TemporaryDirectory(prefix="memty-privacy-") as directory:
        vault = open_ledger(path=Path(directory) / "vault.sqlite3")
        try:
            vault.record("demo.client", "client_name", "Example Company",
                         sensitivity="CONFIDENTIAL")
            capsule = vault.context("client", provider="openai",
                                    namespace="demo.client", strict_namespace=True)
            print("Cloud-filtered text:")
            print(capsule["text"])
            # Never send capsule["redactions"] or the full result to a remote model.

            vault.record("demo.secret", "private_note", "fictional local detail",
                         sensitivity="SECRET")
            try:
                vault.context("private note", provider="openai",
                              namespace="demo.secret", strict_namespace=True)
            except LocalRoutingRequired:
                print("Cloud recall refused: an eligible SECRET fact requires local routing.")
        finally:
            vault.close()


if __name__ == "__main__":
    main()
