"""TEST ONLY app-owned node for disposable persistence evidence."""
node ProofRecord {
    def __jac_access__ -> AccessLevel { return AccessLevel.WRITE; }
    has value: str;
}
