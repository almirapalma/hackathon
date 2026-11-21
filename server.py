"""PayeeLock local demonstration server. No real transfers or identity verification."""
import json
import os
import re
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = os.environ.get('PAYEELOCK_DB', str(ROOT / 'payeelock.sqlite3'))


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS recipients (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, verified_account TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transfers (
          id TEXT PRIMARY KEY, recipient_id TEXT, recipient_name TEXT NOT NULL,
          account TEXT NOT NULL, amount_cents INTEGER NOT NULL, reference TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('held','ready','cancelled','simulated_sent')),
          decision TEXT CHECK(decision IN ('confirmed','rejected') OR decision IS NULL),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(recipient_id) REFERENCES recipients(id)
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, transfer_id TEXT NOT NULL REFERENCES transfers(id),
          event TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        db.execute('INSERT OR IGNORE INTO recipients VALUES (?, ?, ?)', ('landlord', 'James Wilson', '48293011'))


def account_number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9 -]+', value):
        raise ValueError('Account number must contain digits, spaces or hyphens only.')
    normalized = value.replace(' ', '').replace('-', '')
    if not 4 <= len(normalized) <= 34:
        raise ValueError('Account number must contain 4 to 34 digits.')
    return normalized


def create_transfer(data):
    account = account_number(data.get('account'))
    try:
        amount = Decimal(str(data.get('amount', '')).replace(',', ''))
        if not amount.is_finite() or amount <= 0 or amount > 100000000 or amount.as_tuple().exponent < -2:
            raise ValueError()
        cents = int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError('Enter a positive amount with at most two decimal places.')
    reference = data.get('reference', '')
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 140:
        raise ValueError('A reference of up to 140 characters is required.')
    recipient_id = data.get('recipient_id')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        recipient = db.execute('SELECT * FROM recipients WHERE id=?', (recipient_id,)).fetchone() if recipient_id else None
        if recipient_id and not recipient:
            raise ValueError('Unknown saved recipient.')
        name = recipient['name'] if recipient else data.get('recipient_name', '')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('A recipient name is required.')
        status = 'ready' if recipient and recipient['verified_account'] == account else 'held'
        transfer_id = str(uuid.uuid4())
        db.execute('INSERT INTO transfers(id,recipient_id,recipient_name,account,amount_cents,reference,status) VALUES(?,?,?,?,?,?,?)',
                   (transfer_id, recipient_id or None, name.strip(), account, cents, reference.strip(), status))
        db.execute('INSERT INTO events(transfer_id,event) VALUES(?,?)', (transfer_id, 'matched' if status == 'ready' else 'verification_required'))
    return get_transfer(transfer_id)


def get_transfer(transfer_id):
    with connect() as db:
        row = db.execute('SELECT id,recipient_id,recipient_name,amount_cents,reference,status,decision,created_at FROM transfers WHERE id=?', (transfer_id,)).fetchone()
        if not row:
            raise LookupError('Transfer not found.')
        result = dict(row)
        result['events'] = [dict(x) for x in db.execute('SELECT event,created_at FROM events WHERE transfer_id=? ORDER BY id', (transfer_id,))]
        return result


def decide(transfer_id, decision):
    if decision not in ('confirmed', 'rejected'):
        raise ValueError('Decision must be confirmed or rejected.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT status FROM transfers WHERE id=?', (transfer_id,)).fetchone()
        if not row:
            raise LookupError('Transfer not found.')
        if row['status'] != 'held':
            raise RuntimeError('Only a held transfer can be verified.')
        status = 'ready' if decision == 'confirmed' else 'cancelled'
        db.execute('UPDATE transfers SET status=?,decision=? WHERE id=?', (status, decision, transfer_id))
        db.execute('INSERT INTO events(transfer_id,event) VALUES(?,?)', (transfer_id, 'simulated_verification_' + decision))
    return get_transfer(transfer_id)


def send(transfer_id):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT status FROM transfers WHERE id=?', (transfer_id,)).fetchone()
        if not row:
            raise LookupError('Transfer not found.')
        if row['status'] != 'ready':
            raise RuntimeError('Only a ready transfer can be sent.')
        db.execute("UPDATE transfers SET status='simulated_sent' WHERE id=?", (transfer_id,))
        db.execute("INSERT INTO events(transfer_id,event) VALUES(?, 'simulated_payment_sent')", (transfer_id,))
    return get_transfer(transfer_id)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            data = (ROOT / 'dist/index.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path.startswith('/api/transfers/'):
            try: self.reply(200, get_transfer(path.split('/')[-1]))
            except LookupError as e: self.reply(404, {'error':str(e)})
        else: self.reply(404, {'error':'Not found.'})

    def do_POST(self):
        # This is a local-only demonstration, not an authenticated banking API.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.reply(403, {'error':'Cross-origin requests are not allowed.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 8192: raise ValueError('Invalid request size.')
            if self.headers.get_content_type() != 'application/json': raise ValueError('Content-Type must be application/json.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict): raise ValueError('JSON object required.')
            parts = urlparse(self.path).path.strip('/').split('/')
            if parts == ['api','transfers']: result = create_transfer(data); status = 201
            elif len(parts) == 4 and parts[:2] == ['api','transfers'] and parts[3] == 'verify': result = decide(parts[2], data.get('decision')); status = 200
            elif len(parts) == 4 and parts[:2] == ['api','transfers'] and parts[3] == 'send': result = send(parts[2]); status = 200
            else: return self.reply(404, {'error':'Not found.'})
            self.reply(status, result)
        except (ValueError, json.JSONDecodeError) as e: self.reply(400, {'error':str(e)})
        except LookupError as e: self.reply(404, {'error':str(e)})
        except RuntimeError as e: self.reply(409, {'error':str(e)})


if __name__ == '__main__':
    init_db()
    print('PayeeLock demo: http://127.0.0.1:8000 (no real bank connection)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8000), Handler).serve_forever()
