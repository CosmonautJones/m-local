import unittest
from unittest.mock import patch

from services.website_import import parse_page, public_target, collect_website


class WebsiteImportTests(unittest.TestCase):
    def test_blocks_private_and_ambiguous_destinations(self):
        for url in ('file:///etc/passwd', 'http://example.com', 'https://user:pass@example.com',
                    'https://localhost', 'https://127.0.0.1', 'https://[::1]',
                    'https://example.com:8443', 'https://example.com\\@localhost',
                    'https://2130706433', 'https://example.com\n.evil.test'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_target(url)

    def test_rejects_any_private_dns_answer(self):
        answers = [(2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('10.0.0.1', 443))]
        with patch('socket.getaddrinfo', return_value=answers), self.assertRaises(ValueError):
            public_target('https://example.com')

    def test_extracts_restaurant_jsonld_and_relative_candidates(self):
        html = '''<title>Fixture Cafe</title><script type="application/ld+json">
        {"@graph":[{"@type":"Restaurant","name":"Fixture Cafe","servesCuisine":"Korean",
         "description":"Lunch downtown", "address":{"streetAddress":"123 Test St","addressLocality":"Ann Arbor"},
         "image":["/photo.jpg"],"hasMenu":"/menu.pdf"}]}</script>
         <a href="/menu">Our Menu</a><img src="/food.jpg" alt="Lunch bowl">
         <script>stealSecrets()</script><p>Fresh bowls daily</p>'''
        result = parse_page(html, 'https://example.com/')
        self.assertEqual(result['name'], 'Fixture Cafe')
        self.assertEqual(result['cuisine'], 'Korean')
        self.assertEqual(result['address'], '123 Test St, Ann Arbor')
        self.assertIn('https://example.com/menu.pdf', result['menu_urls'])
        self.assertIn('https://example.com/photo.jpg', result['image_urls'])
        self.assertNotIn('stealSecrets', result['text'])
        self.assertIn('Fresh bowls daily', result['text'])

    def test_jsonld_logo_leads_and_localhost_is_absent(self):
        html = '''<title>Fixture Cafe</title>
        <meta property="og:image" content="https://example.com/og.jpg">
        <script type="application/ld+json">
        {"@type":"Restaurant","name":"Fixture Cafe",
         "logo":["http://localhost/secret.png",
                 {"@type":"ImageObject","url":"https://example.com/logo.png"}],
         "image":"https://example.com/jsonld.jpg"}
        </script>
        <img src="https://example.com/inline.jpg">
        <img src="http://localhost/x">'''
        result = parse_page(html, 'https://example.com/')
        self.assertEqual(result['image_urls'], [
            'https://example.com/logo.png',
            'https://example.com/og.jpg',
            'https://example.com/jsonld.jpg',
            'https://example.com/inline.jpg',
        ])
        self.assertEqual(result['image_url'], 'https://example.com/logo.png')
        self.assertFalse(any('localhost' in url for url in result['image_urls']))

    def test_menu_page_image_does_not_replace_homepage_logo(self):
        home = '''<title>Fixture Cafe</title>
        <meta property="og:image" content="https://example.com/og.jpg">
        <script type="application/ld+json">
        {"@type":"Restaurant","name":"Fixture Cafe",
         "logo":{"@type":"ImageObject","url":"https://example.com/logo.png"},
         "image":"https://example.com/jsonld.jpg"}
        </script>
        <img src="https://example.com/inline.jpg"><a href="/menu">Menu</a>'''

        def fetch(url):
            if url.endswith('/robots.txt'):
                return url, 'text/plain', b'User-agent: *\nAllow: /'
            if url.endswith('/menu'):
                return url, 'text/html', b'<img src="https://example.com/menu-photo.jpg">'
            return url, 'text/html', home.encode()

        result = collect_website('https://example.com/', fetch=fetch)
        self.assertEqual(result['image_url'], 'https://example.com/logo.png')
        self.assertEqual(result['image_urls'][0], 'https://example.com/logo.png')
        self.assertIn('https://example.com/menu-photo.jpg', result['image_urls'])

    def test_menu_image_is_chosen_only_when_homepage_has_none(self):
        def fetch(url):
            if url.endswith('/robots.txt'):
                return url, 'text/plain', b'User-agent: *\nAllow: /'
            if url.endswith('/menu'):
                return url, 'text/html', b'<img src="https://example.com/menu-photo.jpg">'
            return url, 'text/html', b'<title>Cafe</title><a href="/menu">Menu</a>'

        result = collect_website('https://example.com/', fetch=fetch)
        self.assertEqual(result['image_url'], 'https://example.com/menu-photo.jpg')
        self.assertEqual(result['image_urls'], ['https://example.com/menu-photo.jpg'])

    def test_unsafe_links_never_become_image_or_menu_candidates(self):
        result = parse_page('<img src="data:text/html,evil"><img src="http://localhost/x">'
                            '<a href="javascript:alert(1)">Menu</a>', 'https://example.com')
        self.assertEqual(result['image_urls'], [])
        self.assertEqual(result['image_url'], '')
        self.assertEqual(result['menu_urls'], [])

    def test_collection_obeys_robots_and_only_follows_bounded_same_site_html(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if url.endswith('/robots.txt'):
                return url, 'text/plain', b'User-agent: *\nDisallow: /private'
            if url.endswith('/menu'):
                return url, 'text/html', b'<p>Soup $8</p>'
            return url, 'text/html', b'<title>Cafe</title><a href="/menu">Menu</a><a href="https://elsewhere.test/menu">Menu</a><a href="/private">Menu</a>'
        result = collect_website('https://example.com/', fetch=fetch)
        self.assertIn('Soup $8', result['text'])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['sources'], ['https://example.com/', 'https://example.com/menu'])

    def test_robots_denial_is_not_ignored(self):
        def fetch(url):
            return url, 'text/plain', b'User-agent: *\nDisallow: /'
        with self.assertRaises(ValueError):
            collect_website('https://example.com/', fetch=fetch)


if __name__ == '__main__':
    unittest.main()
