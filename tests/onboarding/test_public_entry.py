import unittest
from pathlib import Path


class PublicEntryTests(unittest.TestCase):
    def test_entry_module_does_not_embed_images(self):
        text = Path('main.jac').read_text(encoding='utf-8')
        self.assertNotIn('<img', text)
        mobui = text.split('import from "@jac/mobui"', 1)[1].split('}', 1)[0]
        self.assertNotIn('Image', mobui)


if __name__ == '__main__':
    unittest.main()
