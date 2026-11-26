"""Executar: python -m workers.worker payment|inventory|notifications [nome]"""
import json
import os
import socket
import sys
import time
import pika
from common import connect, db, enqueue, event, flush, record

def process(service, name, ev):
    if not isinstance(ev, dict) or not all(k in ev for k in ('event_id','order_id','type','data')):
        raise ValueError('Envelope inválido')
    oid, eid, data = ev['order_id'], ev['event_id'], ev['data']
    if not isinstance(data, dict) or not isinstance(eid,str) or not isinstance(oid,str):
        raise ValueError('Envelope inválido')
    if service == 'payment' and (ev['type'] != 'pedido.criado' or data.get('outcome') not in ('success','decline')):
        raise ValueError('Dados de pagamento inválidos')
    if service == 'inventory' and (ev['type'] != 'pagamento.aprovado' or not isinstance(data.get('items'),list)):
        raise ValueError('Dados de estoque inválidos')
    con = db()
    try:
        with con:
            con.execute('BEGIN IMMEDIATE')
            existing = con.execute('SELECT rejected FROM processed WHERE service=? AND event_id=?', (service,eid)).fetchone()
            if existing:
                return bool(existing['rejected'])
            rejected = service == 'payment' and data['outcome'] == 'decline'
            if service == 'payment':
                kind = 'pagamento.recusado' if rejected else 'pagamento.aprovado'
                con.execute('UPDATE orders SET status=? WHERE id=?', ('recusado' if rejected else 'pago',oid))
                enqueue(con, event(oid, kind, data))
                record(con,oid,kind,name,'Sem limite (simulado)' if rejected else 'Pagamento de teste aprovado')
            elif service == 'inventory':
                con.execute('INSERT OR IGNORE INTO reservations VALUES (?,?)', (oid,json.dumps(data['items'])))
                con.execute('UPDATE orders SET status=? WHERE id=?', ('concluido',oid))
                enqueue(con,event(oid,'estoque.reservado',data))
                record(con,oid,'estoque.reservado',name,'Reserva fictícia registrada após pagamento aprovado')
            else:
                record(con,oid,'notificacao.'+ev['type'],name,'Notificação registrada; nenhum e-mail real enviado')
            con.execute('INSERT INTO processed VALUES (?,?,?)',(service,eid,int(rejected)))
        return rejected
    finally:
        con.close()

def main():
    service = sys.argv[1] if len(sys.argv)>1 else 'payment'
    if service not in ('payment','inventory','notifications'):
        raise SystemExit('Use payment, inventory ou notifications')
    name = sys.argv[2] if len(sys.argv)>2 else service+'@'+socket.gethostname()
    while True:
        conn = None
        try:
            conn,ch = connect()
            flush(ch)
            ch.basic_qos(prefetch_count=1)
            print(f'[{name}] ONLINE queue=norma.{service} prefetch=1 auto_ack=False',flush=True)
            def consume(channel, delivery, props, body):
                try:
                    ev = json.loads(body)
                    if not isinstance(ev, dict):
                        raise ValueError('Envelope precisa ser um objeto JSON')
                    print(f'[{name}] RECEBIDO key={delivery.routing_key} order={ev.get("order_id")} redelivered={delivery.redelivered}',flush=True)
                    if service=='payment':
                        conn.sleep(float(os.getenv('PAYMENT_DELAY','3')))
                    rejected = process(service,name,ev)
                    flush(channel,ev['order_id'])
                    if rejected:
                        channel.basic_nack(delivery_tag=delivery.delivery_tag,requeue=False)
                        print(f'[{name}] NACK requeue=False -> norma.dlq order={ev["order_id"]}',flush=True)
                    else:
                        channel.basic_ack(delivery_tag=delivery.delivery_tag)
                        print(f'[{name}] ACK order={ev["order_id"]}',flush=True)
                except (ValueError,KeyError,TypeError) as exc:
                    channel.basic_nack(delivery_tag=delivery.delivery_tag,requeue=False)
                    print(f'[{name}] INVALIDO -> DLQ: {exc}',flush=True)
                # Falha transitória de rede/DB sai do callback, fecha a conexão e
                # reentrega a mensagem sem ACK após reconexão com pausa.
            ch.basic_consume(queue='norma.'+service,on_message_callback=consume,auto_ack=False)
            ch.start_consuming()
        except KeyboardInterrupt:
            print(f'[{name}] INTERROMPIDO; sem ACK volta para Ready',flush=True)
            break
        except Exception as exc:
            print(f'[{name}] RECONECTANDO em 3s ({type(exc).__name__})',flush=True)
            time.sleep(3)
        finally:
            if conn and conn.is_open:
                conn.close()

if __name__=='__main__':
    main()
