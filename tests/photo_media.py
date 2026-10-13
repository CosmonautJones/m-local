import base64
from contextlib import closing
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
from PIL import Image
from services import media_upload as media


def payload(size: tuple[int,int]=(600,400)) -> str:
    output=BytesIO()
    image=Image.new('RGB',size,'orange')
    exif=Image.Exif();exif[270]='private camera note'
    image.save(output,'JPEG',exif=exif)
    return 'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode()


class PhotoUploadTests(unittest.TestCase):
    def setUp(self):
        self.store=tempfile.TemporaryDirectory()
        self.patch=patch.object(media,'photo_directory',return_value=Path(self.store.name))
        self.patch.start()
        self.private=patch.dict(os.environ,{'MLOCAL_ONBOARDING_DIR':str(Path(self.store.name)/'private')});self.private.start()
    def tearDown(self):
        self.private.stop();self.patch.stop();self.store.cleanup()
    def test_normalizes_and_strips_metadata(self):
        url=media.save_photo(payload((1800,1200)),'owner')
        self.assertEqual(media.owned_photo(url,'owner'),url)
        with Image.open(Path(self.store.name)/url.rsplit('/',1)[-1]) as image:
            self.assertEqual(image.format,'JPEG')
            self.assertLessEqual(max(image.size),1600)
            self.assertFalse(image.getexif())
    def test_owner_cannot_reuse_another_owners_local_photo(self):
        url=media.save_photo(payload(),'other')
        with self.assertRaises(ValueError):media.owned_photo(url,'owner')
    def test_rejects_non_photos_and_oversized_payload(self):
        for data in ['data:image/svg+xml;base64,PHN2Zz4=', 'data:image/jpeg;base64,!!!!', 'data:image/jpeg;base64,'+'A'*1400000, 'data:image/jpeg;base64,'+base64.b64encode(b'<html>fake jpg').decode()]:
            with self.assertRaises(ValueError):media.save_photo(data,'owner')
        self.assertEqual(list(Path(self.store.name).glob('*.jpg')),[])
    def test_owner_quota_does_not_destroy_current_photos(self):
        with closing(media.photo_registry()) as db, db:
            for i in range(30):db.execute('INSERT INTO photos VALUES (?,?,?,?,?)',(str(i)+'.jpg','owner',str(i),100,__import__('time').time()))
        with self.assertRaises(ValueError):media.save_photo(payload(),'owner')
        with closing(media.photo_registry()) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM photos').fetchone()[0],30)
    def test_rejects_missing_traversal_and_symlinks(self):
        for url in ['/static/photos/../../config.jpg','/static/photos/'+'a'*32+'.jpg']:
            with self.assertRaises(ValueError):media.owned_photo(url,'owner')


    def test_deduplicates_without_public_owner_identifier(self):
        first=media.save_photo(payload(),'owner')
        self.assertEqual(media.save_photo(payload(),'owner'),first)
        self.assertNotIn(__import__('hashlib').sha256(b'owner').hexdigest()[:16],first)
        self.assertEqual(len(list(Path(self.store.name).glob('*.jpg'))),1)

    def test_website_png_uses_same_normalization(self):
        raw=BytesIO();Image.new('RGB',(800,600),'green').save(raw,'PNG')
        url=media.save_image_bytes(raw.getvalue(),'owner')
        self.assertEqual(media.owned_photo(url,'owner'),url)
        with Image.open(Path(self.store.name)/url.rsplit('/',1)[-1]) as image:self.assertEqual(image.format,'JPEG')

if __name__=='__main__':unittest.main()
