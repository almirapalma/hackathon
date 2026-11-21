# PayeeLock local MVP

A local, simulated payment workflow with a Python backend and SQLite persistence. It does **not** connect to a bank, authenticate users or recipients, contact a landlord, or move real money. It must not be exposed to the internet or used for real payments.

## Run

Requires Python 3.9 or later; no third-party packages.

```sh
python3 server.py
```

Open http://127.0.0.1:8000. Stop with Ctrl-C. Data is stored in `payeelock.sqlite3`; delete it while the server is stopped to reset the demo. The seeded recipient is James Wilson with account 4829 3011.

## Flow

The server compares normalized account numbers against the saved record. A match creates a ready transfer; a new recipient or changed account creates a held transfer. The UI simulates a trusted-contact decision: confirmation makes that specific transfer ready, rejection cancels it. A ready transfer can be sent to a simulated provider, which records an event but moves no money. Confirming a change does not overwrite the saved recipient.

Run tests with `python3 -m unittest -v`.

## Before real-world use

Implement authentication and authorization, authenticated out-of-band recipient verification, encrypted sensitive data and secrets management, audit and operational controls, and a bank/payment-provider integration that enforces holds at the actual point of payment. Security review and appropriate financial and legal compliance are required. This demo's verification endpoint deliberately accepts simulated user input and is not evidence of recipient identity.
