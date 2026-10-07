"""Local operator review. Run in the app workspace with its private store and database."""
import argparse;
import json;
import sqlite3;
import from uuid { UUID }
import from services.email_codes { existing_store }

with entry {
    parser = argparse.ArgumentParser(description=__doc__);
    parser.add_argument("command", choices=["list", "approve"]);
    parser.add_argument("--actor", `default="");
    parser.add_argument("--by", `default="");
    parser.add_argument("--note", `default="");
    parser.add_argument("--submission", `default="");
    args = parser.parse_args();
    try {
        state = existing_store();
        if args.command == "list" {
            print(json.dumps(state.pending_businesses(), indent=2));
        } else {
            actor = UUID(args.actor).hex;
            state.approve_business(actor, args.by, args.note, args.submission);
            print("Business approved. The owner can continue to offers.");
        }
    } except ValueError as error { parser.error(str(error)); }
    except (OSError, sqlite3.Error, RuntimeError) {
        parser.error("Business review could not read or update the private store. Check filesystem access and database health before retrying.");
    }
}
