import unittest
from online_chat.message_content import decode, encode, quote, preview
from desktop_chat.message_widgets import map_url


class MessageContentTests(unittest.TestCase):
    def test_reply_and_forward_roundtrip(self):
        original = {"local_id": "cfb9f688-539a-436c-88b3-b6b5c6a71e3e", "outgoing": False, "text": "Привет"}
        reference = quote(original, "anna", "boris")
        body = encode("Ответ", reply=reference, forward=reference)
        content = decode(body)
        self.assertEqual(content["reply"]["id"], original["local_id"])
        self.assertEqual(content["forward"]["sender"], "boris")
        self.assertEqual(preview(body), "Ответ")

    def test_ios_envelope_is_compatible(self):
        body = 'OCM1:{"text":"Ответ","reply":{"id":"uuid","sender":"anna","text":"Фото"},"location":{"latitude":55.75,"longitude":37.61}}'
        self.assertEqual(decode(body)["reply"]["text"], "Фото")
        self.assertEqual(preview(body), "📍 Местоположение")

    def test_legacy_location_and_map_coordinate_order(self):
        content = decode("📍 Местоположение\nhttps://maps.apple.com/?ll=55.75,37.61")
        self.assertEqual(content["location"], {"latitude": 55.75, "longitude": 37.61})
        self.assertIn("37.610000%2C55.750000", map_url(content["location"]))
        self.assertEqual(map_url(content["location"], "2gis"), "https://2gis.ru/geo/37.610000,55.750000")

    def test_malformed_content_stays_plain_text(self):
        for body in ("OCM1:{bad", 'OCM1:{"text":3}', "Привет"):
            self.assertEqual(decode(body)["text"], body)
        self.assertNotIn("location", decode('OCM1:{"text":"test","location":{"latitude":999,"longitude":0}}'))
