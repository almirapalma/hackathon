import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
import server

class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.DB_PATH = os.path.join(self.tmp.name, 'test.sqlite3')
        server.init_db()
    def tearDown(self): self.tmp.cleanup()
    def create(self, **changes):
        data = dict(recipient_id='landlord', account='4829 3011', amount='1800.00', reference='Rent')
        data.update(changes)
        return server.create_transfer(data)
    def test_match_can_send_once(self):
        t = self.create(); self.assertEqual(t['status'], 'ready')
        self.assertEqual(server.send(t['id'])['status'], 'simulated_sent')
        with self.assertRaises(RuntimeError): server.send(t['id'])
    def test_changed_account_requires_confirmation(self):
        t = self.create(account='4829 3017'); self.assertEqual(t['status'], 'held')
        with self.assertRaises(RuntimeError): server.send(t['id'])
        self.assertEqual(server.decide(t['id'], 'confirmed')['status'], 'ready')
        self.assertEqual(server.send(t['id'])['status'], 'simulated_sent')
        self.assertEqual(self.create(account='4829 3017')['status'], 'held')
    def test_new_recipient_rejected_cannot_send(self):
        t = self.create(recipient_id=None, recipient_name='Alex', account='12345678')
        self.assertEqual(t['status'], 'held')
        self.assertEqual(server.decide(t['id'], 'rejected')['status'], 'cancelled')
        with self.assertRaises(RuntimeError): server.send(t['id'])
        with self.assertRaises(RuntimeError): server.decide(t['id'], 'confirmed')
    def test_invalid_data(self):
        for changes in ({'account':'12x34'}, {'amount':'NaN'}, {'amount':'1.001'}, {'recipient_id':'unknown'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.create(**changes)
    def test_competing_decisions_have_one_winner(self):
        t=self.create(account='48293017')
        def attempt(decision):
            try: return server.decide(t['id'], decision)['decision']
            except RuntimeError: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt, ['confirmed','rejected']))
        self.assertEqual(results.count('conflict'), 1)
        self.assertIn(server.get_transfer(t['id'])['decision'], ('confirmed','rejected'))

if __name__ == '__main__': unittest.main()
