"""Teste com RabbitMQ REAL. Inicie somente o broker, sem API/workers paralelos.
Executar da raiz: python tests/integration.py
Cria pedidos fictícios, pausa workers próprios, não apaga filas existentes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from common import connect
os.chdir(ROOT)
OUT=ROOT/'evidencias'
OUT.mkdir(exist_ok=True)
processes=[]
streams=[]
evidence={'started_at':time.strftime('%Y-%m-%d %H:%M:%S'),'tests':{}}

def start(module,*args):
    filename='-'.join(args) if args else 'api'
    stream=open(OUT/(filename+'.log'),'a',encoding='utf-8')
    streams.append(stream)
    p=subprocess.Popen([sys.executable,'-u','-m',module,*args],cwd=ROOT,
        stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PAYMENT_DELAY':'1'})
    processes.append(p)
    return p
def stop(p):
    p.terminate()
    p.wait(timeout=10)
def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=10) as r:
        return json.load(r)
def wait(fn,timeout=50):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            value=fn()
            if value:return value
        except Exception:pass
        time.sleep(.4)
    raise AssertionError('Timeout aguardando condição')
def send(outcome='success',key=None):
    payload={'items':[{'id':4,'quantity':1}],'method':'pix','outcome':outcome}
    req=urllib.request.Request('http://127.0.0.1:8000/api/orders',data=json.dumps(payload).encode(),
        headers={'Content-Type':'application/json','Idempotency-Key':key or str(uuid.uuid4())})
    before=time.monotonic()
    with urllib.request.urlopen(req,timeout=15) as r:
        data=json.load(r)
        assert r.status==202
    return {**data,'http_status':202,'response_ms':round((time.monotonic()-before)*1000)}
def completed(oid):return get('/api/orders/'+oid)['status']=='concluido'
def qstate(queue):
    c,ch=connect()
    try:
        m=ch.queue_declare(queue=queue,passive=True).method
        return {'ready':m.message_count,'consumers':m.consumer_count}
    finally:c.close()

try:
    assert qstate('norma.payment')['consumers']==0,'Pare os workers existentes antes do teste'
    start('api.app')
    wait(lambda:get('/api/health')['rabbitmq']=='ok')
    start('workers.worker','inventory','inventory-test')
    start('workers.worker','notifications','notifications-test')
    payment=start('workers.worker','payment','payment-A')
    wait(lambda:qstate('norma.payment')['consumers']==1)
    normal=send()
    wait(lambda:completed(normal['order_id']))
    evidence['tests']['normal']={**normal,'final':get('/api/orders/'+normal['order_id'])}
    stop(payment)
    wait(lambda:qstate('norma.payment')['consumers']==0)
    before=qstate('norma.payment')['ready']
    queued=[send() for _ in range(3)]
    ready=qstate('norma.payment')
    assert ready['ready']>=before+3
    payment=start('workers.worker','payment','payment-A')
    wait(lambda:all(completed(p['order_id']) for p in queued))
    evidence['tests']['chaos']={'orders':[p['order_id'] for p in queued],
        'stopped':ready,'after':qstate('norma.payment'),'recovered':True}
    dlq_before=qstate('norma.dlq')['ready']
    decline=send('decline')
    wait(lambda:qstate('norma.dlq')['ready']>dlq_before)
    evidence['tests']['dlq']={'order':decline['order_id'],'before':dlq_before,
        'after':qstate('norma.dlq'),'final':get('/api/orders/'+decline['order_id'])}
    second=start('workers.worker','payment','payment-B')
    wait(lambda:qstate('norma.payment')['consumers']==2)
    burst=[send() for _ in range(10)]
    wait(lambda:all(completed(p['order_id']) for p in burst))
    counts={}
    for p in burst:
        history=get('/api/orders/'+p['order_id'])['history']
        for h in history:
            if h['event']=='pagamento.aprovado':counts[h['worker']]=counts.get(h['worker'],0)+1
    assert len(counts)==2 and sum(counts.values())==10
    evidence['tests']['scaling']={'distribution':counts,'orders':[p['order_id'] for p in burst],
        'queue':qstate('norma.payment')}
    key=str(uuid.uuid4())
    a,b=send(key=key),send(key=key)
    assert a['order_id']==b['order_id']
    wait(lambda:completed(a['order_id']))
    evidence['tests']['idempotency']={'same_order_id':a['order_id']==b['order_id']}
    evidence['passed']=True
    print(json.dumps(evidence,ensure_ascii=False,indent=2))
finally:
    (OUT/'resultados.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    for p in processes:
        if p.poll() is None:stop(p)
    for f in streams:f.close()

