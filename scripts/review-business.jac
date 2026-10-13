"""Local operator review. Run in the app workspace with its private store and database."""
import argparse;
import json;
import sqlite3;
import from uuid { UUID }
import from services.email_codes { existing_store }

with entry {
    parser = argparse.ArgumentParser(description=__doc__);
    parser.add_argument("command", choices=["list", "approve", "status", "audit", "suspend", "reinstate"]);
    parser.add_argument("--actor", `default="");
    parser.add_argument("--by", `default="");
    parser.add_argument("--note", `default="");
    parser.add_argument("--submission", `default="");
    parser.add_argument("--revision", type=int, `default=-1);
    parser.add_argument("--command-id", `default="");
    args = parser.parse_args();
    try {
        state = existing_store();
        if args.command == "list" {
            print(json.dumps(state.pending_businesses(), indent=2));
        } elif args.command == "approve" {
            actor = UUID(args.actor).hex;
            state.approve_business(actor, args.by, args.note, args.submission);
            print("Business approved. The owner can continue to offers.");
        } elif args.command == "status" {
            print(json.dumps(state.business_status(args.actor), indent=2));
        } elif args.command == "audit" {
            print(json.dumps(state.business_status_events(args.actor), indent=2));
        } else {
            target = "suspended" if args.command == "suspend" else "active";
            receipt = state.change_business_status(args.actor, target, args.by, args.note, args.revision, args.command_id);
            print(json.dumps(receipt, indent=2));
        }
    } except ValueError as error { parser.error(str(error)); }
    except (OSError, sqlite3.Error, RuntimeError) {
        parser.error("Business review could not read or update the private store. Check filesystem access and database health before retrying.");
    }
}
