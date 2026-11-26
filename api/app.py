import json
import time
import uuid
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from waitress import serve
from common import db, connect, enqueue, event, flush, record

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'
app = Flask(__name__, static_folder=str(FRONTEND), static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
CATALOG = {1:189000, 2:429000, 3:64900, 4:18900, 5:79000, 6:45900}

def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get('items'), list) or not 1 <= len(data['items']) <= 6:
        raise ValueError('Envie entre 1 e 6 produtos.')
    seen = set()
    amount = 0
    for item in data['items']:
        if not isinstance(item, dict):
            raise ValueError('Produto inválido.')
        pid, qty = item.get('id'), item.get('quantity')
        if type(pid) is not int or pid not in CATALOG or pid in seen:
            raise ValueError('Produto inválido ou repetido.')
        if type(qty) is not int or not 1 <= qty <= 99:
            raise ValueError('Quantidade inválida.')
        seen.add(pid)
        amount += CATALOG[pid] * qty
    if data.get('method') not in ('pix', 'card') or data.get('outcome') not in ('success', 'decline'):
        raise ValueError('Forma ou cenário de pagamento inválido.')
    return amount + (0 if amount >= 150000 else 2990)

@app.get('/')
def index():
    return send_from_directory(FRONTEND, 'index.html')

@app.post('/api/orders')
def create_order():
    data = request.get_json(silent=True)
    try:
        amount = validate(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    key = request.headers.get('Idempotency-Key', str(uuid.uuid4()))
    if not isinstance(key, str) or not 1 <= len(key) <= 100:
        return jsonify(error='Chave muito longa'), 400
    # Não recebemos nome, endereço ou dados de cartão. Somente dados fictícios do pedido.
    clean = {k:data[k] for k in ('items', 'method', 'outcome')}
    canonical = json.dumps(clean, sort_keys=True)
    con = db()
    with con:
        con.execute('BEGIN IMMEDIATE')
        previous = con.execute('SELECT * FROM orders WHERE request_key=?', (key,)).fetchone()
        if previous:
            if previous['payload'] != canonical:
                return jsonify(error='Chave já usada com outro pedido.'), 409
            oid = previous['id']
        else:
            oid = str(uuid.uuid4())
            con.execute('INSERT INTO orders VALUES (?,?,?,?,?,?)',
                        (oid,key,canonical,amount,'recebido',time.time()))
            enqueue(con, event(oid, 'pedido.criado', {**clean, 'total_cents':amount}))
            record(con, oid, 'pedido.recebido', 'api', 'Pedido validado; aguardando processamento')
    con.close()
    try:
        connection, channel = connect()
        try:
            flush(channel, oid)
        finally:
            connection.close()
    except Exception:
        # Outbox durável evita perder um pedido validado; reenvio usa a mesma chave.
        return jsonify(error='Broker indisponível. Pedido salvo; tente novamente com a mesma chave.',
                       order_id=oid, status='aguardando_broker'), 503
    return jsonify(order_id=oid, status='recebido', message='Pedido recebido / Em processamento',
                   total_cents=amount), 202

@app.get('/api/orders/<oid>')
def get_order(oid):
    con = db()
    row = con.execute('SELECT id,total,status,created FROM orders WHERE id=?', (oid,)).fetchone()
    history = con.execute('SELECT event,worker,created,detail FROM history WHERE order_id=? ORDER BY id', (oid,)).fetchall()
    con.close()
    if not row:
        return jsonify(error='Pedido não encontrado'), 404
    return jsonify(**dict(row), history=[dict(r) for r in history])

@app.get('/api/orders')
def list_orders():
    con = db()
    rows = con.execute('SELECT id,total,status,created FROM orders ORDER BY created DESC LIMIT 100').fetchall()
    con.close()
    return jsonify([dict(r) for r in rows])

@app.get('/api/health')
def health():
    try:
        conn, _ = connect()
        conn.close()
        return jsonify(api='ok', rabbitmq='ok')
    except Exception:
        return jsonify(api='ok', rabbitmq='indisponivel'), 503

if __name__ == '__main__':
    db().close()
    print('NORMA em http://localhost:8000 | Painel: /demo.html', flush=True)
    serve(app, host='0.0.0.0', port=8000, threads=8)
