import os
import tempfile
import unittest
from api.app import validate
from common import db, event
from workers.worker import process

class Rules(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('DATA_DIR')
        os.environ['DATA_DIR'] = self.temp.name
    def tearDown(self):
        if self.old is None: os.environ.pop('DATA_DIR',None)
        else: os.environ['DATA_DIR']=self.old
        self.temp.cleanup()
    def test_total_server_side(self):
        self.assertEqual(validate({'items':[{'id':4,'quantity':1}], 'method':'pix','outcome':'success'}),21890)
    def test_invalid_quantity(self):
        for qty in (0,-1,1.2,True,100):
            with self.assertRaises(ValueError):
                validate({'items':[{'id':4,'quantity':qty}], 'method':'pix','outcome':'success'})
    def test_idempotence(self):
        ev=event('test','pedido.criado',{'outcome':'success','items':[]})
        process('payment','p1',ev)
        process('payment','p2',ev)
        con=db()
        self.assertEqual(con.execute('SELECT count(*) FROM outbox').fetchone()[0],1)
        self.assertEqual(con.execute('SELECT count(*) FROM history').fetchone()[0],1)
        con.close()
    def test_decline(self):
        self.assertTrue(process('payment','p1',event('test','pedido.criado',{'outcome':'decline'})))
        con=db()
        self.assertEqual(con.execute('SELECT routing_key FROM outbox').fetchone()[0],'pagamento.recusado')
        self.assertEqual(con.execute('SELECT count(*) FROM reservations').fetchone()[0],0)
        con.close()
    def test_bad_payload(self):
        with self.assertRaises(ValueError): process('payment','p1',{'type':'pedido.criado'})

if __name__=='__main__': unittest.main()
