"""A PDF with no selectable text (a page printed to PDF) is handed to the AI as a
document so its pages are read as images. No real API call: the client is faked
and stopped right after the request is built.

Run from the backend folder:  py -3.12 -m unittest discover -s tests -t .
"""
import os
import unittest
from unittest import mock

import profile_review
from career import ingestion


class Stop(Exception):
    pass


def fake_client():
    captured = {}
    client = mock.MagicMock()

    def create(**kwargs):
        captured.update(kwargs)
        raise Stop()

    client.messages.create.side_effect = create
    return client, captured


class PicturePdf(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"})
        env.start()
        self.addCleanup(env.stop)

    def test_linkedin_review_sends_the_pdf_as_a_document_block(self):
        client, captured = fake_client()
        with mock.patch.object(profile_review.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(Stop):
                profile_review.review_profile([], "", "", "", "QUJD")
        blocks = captured["messages"][0]["content"]
        docs = [b for b in blocks if b["type"] == "document"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"], {"type": "base64", "media_type": "application/pdf", "data": "QUJD"})

    def test_linkedin_review_without_a_document_is_unchanged(self):
        client, captured = fake_client()
        with mock.patch.object(profile_review.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(Stop):
                profile_review.review_profile([], "Headline: Treasury", "", "")
        self.assertFalse([b for b in captured["messages"][0]["content"] if b["type"] == "document"])

    def test_import_sends_the_pdf_as_a_document_and_a_placeholder_prompt(self):
        client, captured = fake_client()
        with mock.patch.object(ingestion.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(Stop):
                ingestion.start_resume_review("", "QUJD")
        content = captured["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "document")
        self.assertIn("page images", content[1]["text"])

    def test_import_with_text_still_sends_plain_text(self):
        client, captured = fake_client()
        with mock.patch.object(ingestion.anthropic, "Anthropic", return_value=client):
            with self.assertRaises(Stop):
                ingestion.start_resume_review("Treasury Manager at JPMorgan")
        self.assertIsInstance(captured["messages"][0]["content"], str)


if __name__ == "__main__":
    unittest.main()
