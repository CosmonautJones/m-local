#!/usr/bin/env python3
"""Decision ledger for business application review.

Stores approve/reject decisions in the onboarding SQLite database alongside
the drafts table. Every decision is final: approving the same actor twice
returns the original slug without creating a duplicate. Rejecting after
approval is an error.
"""
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from uuid import UUID


def _db_path() -> Path:
    return Path(os.environ.get('MLOCAL_ONBOARDING_DIR', '.jac/onboarding')).resolve() / 'onboarding.sqlite3'


def _connect():
    path = _db_path()
    if not path.exists():
        raise RuntimeError(f'Onboarding database not found at {path}. Start the app first.')
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('BEGIN IMMEDIATE')
    db.execute('''CREATE TABLE IF NOT EXISTS decisions (
        actor TEXT PRIMARY KEY,
        decision TEXT NOT NULL,
        slug TEXT,
        reason TEXT DEFAULT '',
        decided_at REAL NOT NULL
    )''')
    db.commit()
    return db


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a business name."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower().strip())
    slug = slug.strip('-')
    return slug or 'business'


def _canonical_actor(actor: str) -> str:
    """Normalize actor ID to 32-hex form (matching jid(root) output)."""
    return UUID(actor).hex


def list_pending() -> list[dict]:
    """Return all drafts with status 'pending_review' that have no decision."""
    db = _connect()
    try:
        rows = db.execute(
            'SELECT d.actor, d.body, d.updated, a.email, a.name '
            'FROM drafts d '
            'LEFT JOIN accounts a ON d.actor = a.actor '
            'LEFT JOIN decisions dec ON d.actor = dec.actor '
            'WHERE dec.actor IS NULL'
        ).fetchall()
        results = []
        for row in rows:
            body = json.loads(row['body']) if row['body'] else {}
            if body.get('status') != 'pending_review':
                continue
            results.append({
                'actor_id': row['actor'],
                'email': row['email'] or '(unknown)',
                'applicant_name': row['name'] or '(unknown)',
                'business_name': body.get('name', ''),
                'cuisine': body.get('cuisine', ''),
                'address': body.get('address', ''),
                'website': body.get('website', ''),
                'description': body.get('description', ''),
                'submitted_at': row['updated'],
            })
        return results
    finally:
        db.close()


def list_decisions() -> list[dict]:
    """Return all recorded decisions."""
    db = _connect()
    try:
        rows = db.execute(
            'SELECT dec.actor, dec.decision, dec.slug, dec.reason, dec.decided_at, '
            'a.email, a.name '
            'FROM decisions dec '
            'LEFT JOIN accounts a ON dec.actor = a.actor '
            'ORDER BY dec.decided_at DESC'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def get_draft(actor: str) -> dict:
    """Read a single applicant's draft."""
    actor = _canonical_actor(actor)
    db = _connect()
    try:
        row = db.execute('SELECT body FROM drafts WHERE actor=?', (actor,)).fetchone()
        return json.loads(row['body']) if row else {}
    finally:
        db.close()


def existing_decision(actor: str) -> dict | None:
    """Check if a decision already exists for this actor."""
    actor = _canonical_actor(actor)
    db = _connect()
    try:
        row = db.execute('SELECT * FROM decisions WHERE actor=?', (actor,)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def _unique_slug(db, base_slug: str) -> str:
    """Ensure the slug is unique by appending a counter if needed."""
    slug = base_slug
    counter = 2
    while True:
        existing = db.execute(
            'SELECT COUNT(*) FROM decisions WHERE slug=?', (slug,)
        ).fetchone()[0]
        if not existing:
            return slug
        slug = f'{base_slug}-{counter}'
        counter += 1


def record_approval(actor: str, slug_override: str = '') -> dict:
    """Record an approval decision. Returns the slug for the new restaurant.

    Idempotent: if the actor was already approved, returns the existing decision
    without creating duplicates.
    """
    actor = _canonical_actor(actor)
    db = _connect()
    try:
        # Check existing decision
        existing = db.execute('SELECT * FROM decisions WHERE actor=?', (actor,)).fetchone()
        if existing:
            if existing['decision'] == 'approved':
                return {'already': True, 'slug': existing['slug'],
                        'message': f'Already approved as {existing["slug"]}.'}
            raise ValueError(f'This application was already rejected. Cannot approve.')

        # Read draft
        draft_row = db.execute('SELECT body FROM drafts WHERE actor=?', (actor,)).fetchone()
        if not draft_row:
            raise ValueError(f'No application found for actor {actor}.')
        draft = json.loads(draft_row['body'])
        if draft.get('status') != 'pending_review':
            raise ValueError(f'Application status is "{draft.get("status", "unknown")}", not pending_review.')

        # Generate slug
        if slug_override:
            slug = _slugify(slug_override)
        else:
            slug = _slugify(draft.get('name', 'business'))
        slug = _unique_slug(db, slug)

        # Record decision
        db.execute('BEGIN IMMEDIATE')
        db.execute(
            'INSERT INTO decisions VALUES (?,?,?,?,?)',
            (actor, 'approved', slug, '', time.time())
        )
        # Update draft status
        draft['status'] = 'approved'
        db.execute(
            'UPDATE drafts SET body=?, updated=? WHERE actor=?',
            (json.dumps(draft), time.time(), actor)
        )
        db.commit()

        return {
            'already': False,
            'slug': slug,
            'name': draft.get('name', ''),
            'cuisine': draft.get('cuisine', ''),
            'address': draft.get('address', ''),
            'description': draft.get('description', ''),
            'message': f'Approved. Restaurant slug: {slug}',
        }
    finally:
        db.close()


def record_rejection(actor: str, reason: str = '') -> dict:
    """Record a rejection decision."""
    actor = _canonical_actor(actor)
    if not reason.strip():
        raise ValueError('A rejection reason is required.')
    db = _connect()
    try:
        existing = db.execute('SELECT * FROM decisions WHERE actor=?', (actor,)).fetchone()
        if existing:
            if existing['decision'] == 'rejected':
                return {'already': True, 'message': 'Already rejected.'}
            raise ValueError('This application was already approved. Cannot reject.')

        draft_row = db.execute('SELECT body FROM drafts WHERE actor=?', (actor,)).fetchone()
        if not draft_row:
            raise ValueError(f'No application found for actor {actor}.')

        draft = json.loads(draft_row['body'])

        db.execute('BEGIN IMMEDIATE')
        db.execute(
            'INSERT INTO decisions VALUES (?,?,?,?,?)',
            (actor, 'rejected', None, reason.strip(), time.time())
        )
        draft['status'] = 'rejected'
        db.execute(
            'UPDATE drafts SET body=?, updated=? WHERE actor=?',
            (json.dumps(draft), time.time(), actor)
        )
        db.commit()

        return {'already': False, 'message': f'Rejected: {reason.strip()}'}
    finally:
        db.close()
