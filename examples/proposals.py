"""Review an agent's proposed change in an isolated temporary vault."""
from pathlib import Path
from tempfile import TemporaryDirectory

from memty import open_ledger


def main() -> None:
    with TemporaryDirectory(prefix="memty-inbox-") as directory:
        vault = open_ledger(path=Path(directory) / "vault.sqlite3")
        try:
            vault.record("demo.project", "database", "PostgreSQL 16",
                         verification_state="USER_CONFIRMED")
            proposal = vault.propose("demo.project", "database", "PostgreSQL 17",
                                     proposed_by="example-agent", reason="Upgrade planned")
            print("Proposal status:", proposal["status"])
            print("Current value:", vault.find("demo.project", "database")["value"])
            if proposal["status"] == "pending_review":
                # In a real application, display the proposal and get the user's decision first.
                vault.resolve_proposal(proposal["proposal_id"], approve=True)
                print("After approval:", vault.find("demo.project", "database")["value"])
        finally:
            vault.close()


if __name__ == "__main__":
    main()
