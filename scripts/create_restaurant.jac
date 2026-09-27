import json;
import os;
import from services.importer { import_restaurant }
import from services.models { Restaurant }

with entry {
    record_json = os.environ.get("MLOCAL_RESTAURANT_RECORD", "{}");
    try {
        record = json.loads(record_json);
        if not record.get("slug") {
            print("No slug provided.");
        } else {
            r = import_restaurant(record);
            if jid(root) != jid(root.shared) {
                root.shared ++> r;
            }
            print("Success");
        }
    } except Exception as e {
        print("Error: " + str(e));
    }
}
