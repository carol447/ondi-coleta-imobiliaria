import json
import sys
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from cards_store import CardsStore


class CardsStoreTest(unittest.TestCase):
    def test_migration_updates_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "old.json"
            legacy.write_text(json.dumps([{"id_anuncio": "1", "worker": "worker1", "preco": 100, "cidade": "Teste"}]))
            store = CardsStore(root / "cards.db", legacy)
            self.assertEqual(store.counts("worker1"), (1, 1))
            self.assertEqual(store.save([{"id_anuncio": "1", "worker": "worker2", "preco": 200}], "worker2"), (0, 1, 1))
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda i: store.save([{"id_anuncio": str(i), "worker": "worker1"}], "worker1"), range(2, 32)))
            restarted = CardsStore(root / "cards.db", legacy)
            self.assertEqual(restarted.counts("worker2"), (31, 1))
            row = next(r for r in restarted.all() if r["id_anuncio"] == "1")
            self.assertEqual(row["preco"], 200)
            self.assertEqual(row["cidade"], "Teste")
            self.assertEqual(json.loads(legacy.read_text())[0]["preco"], 100)


if __name__ == "__main__":
    unittest.main()
