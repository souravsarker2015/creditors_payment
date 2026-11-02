"""A pond's photo is the farm's own: it comes through the app, not a public address."""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.business.core.testing import make_farm
from apps.business.ponds.forms import PondForm
from apps.business.ponds.models import Pond

MEDIA = tempfile.mkdtemp()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@override_settings(MEDIA_ROOT=MEDIA)
class PondPhotoTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.b, self.owner, self.staff = make_farm()
        self.pond = Pond.objects.create(business=self.b, name="East", photo=SimpleUploadedFile("east.png", PNG))
        self.url = reverse("receipt_view", args=["pond", self.pond.pk])

    def test_the_farm_sees_it(self):
        self.client.force_login(self.staff)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), PNG)

    def test_another_farm_doesnt(self):
        _b, stranger, _staff = make_farm("other")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_nobody_signed_out_does(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_pages_never_name_the_file(self):
        self.client.force_login(self.owner)
        for page in (reverse("business:ponds"), reverse("business:pond_detail", args=[self.pond.pk])):
            r = self.client.get(page)
            self.assertContains(r, self.url)
            self.assertNotContains(r, self.pond.photo.url)

    def test_the_form_links_the_private_copy(self):
        html = str(PondForm(instance=self.pond, business=self.b)["photo"])
        self.assertIn(self.url, html)
        self.assertNotIn(self.pond.photo.url, html)
