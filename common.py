"""Topologia explícita, persistência local da demonstração e publicação confirmada."""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
import pika

EXCHANGE = 'norma.events'
DLX = 'norma.dlx'
DLQ = 'norma.dlq'
BINDINGS = {
    'norma.payment': ['pedido.criado'],
    'norma.inventory': ['pagamento.aprovado'],
    'norma.notifications': ['pedido.*', 'pagamento.*', 'estoque.*'],
}

def db():
    root = Path(os.getenv('DATA_DIR', 'data'))
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / 'norma.db', timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript('''
      CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY, request_key TEXT UNIQUE, payload TEXT NOT NULL,
        total INTEGER NOT NULL, status TEXT NOT NULL, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS processed (
        service TEXT, event_id TEXT, rejected INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(service,event_id));
      CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, event TEXT,
        worker TEXT, created REAL, detail TEXT);
      CREATE TABLE IF NOT EXISTS outbox (
        event_id TEXT PRIMARY KEY, order_id TEXT, routing_key TEXT,
        body TEXT, sent INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS reservations (
        order_id TEXT PRIMARY KEY, items TEXT NOT NULL);
    ''')
    return con

def connect():
    params = pika.URLParameters(os.getenv('RABBITMQ_URL', 'amqp://norma:norma-local-demo@127.0.0.1:5672/%2F'))
    params.heartbeat = 60
    params.socket_timeout = 5
    params.blocked_connection_timeout = 10
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    topology(ch)
    ch.confirm_delivery()
    return conn, ch

def topology(ch):
    ch.exchange_declare(exchange=EXCHANGE, exchange_type='topic', durable=True)
    ch.exchange_declare(exchange=DLX, exchange_type='direct', durable=True)
    ch.queue_declare(queue=DLQ, durable=True)
    ch.queue_bind(queue=DLQ, exchange=DLX, routing_key='erro')
    for queue, keys in BINDINGS.items():
        ch.queue_declare(queue=queue, durable=True, arguments={
            'x-dead-letter-exchange': DLX, 'x-dead-letter-routing-key': 'erro'})
        for key in keys:
            ch.queue_bind(queue=queue, exchange=EXCHANGE, routing_key=key)

def event(order_id, kind, data):
    return {'event_id': str(uuid.uuid4()), 'order_id': order_id,
            'type': kind, 'occurred_at': time.time(), 'data': data}

def enqueue(con, ev):
    con.execute('INSERT OR IGNORE INTO outbox(event_id,order_id,routing_key,body) VALUES (?,?,?,?)',
                (ev['event_id'], ev['order_id'], ev['type'], json.dumps(ev)))

def flush(ch, order_id=None):
    con = db()
    try:
        rows = con.execute('SELECT * FROM outbox WHERE sent=0' +
                           (' AND order_id=?' if order_id else ''),
                           (order_id,) if order_id else ()).fetchall()
        for row in rows:
            ch.basic_publish(exchange=EXCHANGE, routing_key=row['routing_key'],
                body=row['body'], mandatory=True,
                properties=pika.BasicProperties(delivery_mode=2, content_type='application/json',
                    message_id=row['event_id'], correlation_id=row['order_id']))
            with con:
                con.execute('UPDATE outbox SET sent=1 WHERE event_id=?', (row['event_id'],))
    finally:
        con.close()

def record(con, order_id, kind, worker, detail=''):
    con.execute('INSERT INTO history(order_id,event,worker,created,detail) VALUES (?,?,?,?,?)',
                (order_id, kind, worker, time.time(), detail))
