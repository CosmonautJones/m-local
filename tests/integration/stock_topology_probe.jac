"""TEST ONLY minimal native HTTP entry, never imported by M-Local."""
import from tests.integration.stock_topology_hook { ready, create_probe, write_probe, read_probe }

def:pub probe_ready() -> str { return ready(); }
def:pub probe_create(value: str) -> str { return create_probe(value); }
def:pub probe_write(record_id: str, value: str, mode: str, sqlstate: str) -> str {
    return write_probe(record_id, value, mode, sqlstate);
}
def:pub probe_read(record_id: str) -> str { return read_probe(record_id); }
