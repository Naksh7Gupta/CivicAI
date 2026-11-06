import unittest
from unittest.mock import patch

from app.ingestion.stream_receiver import StreamReceiver


class FakeCapture:
    def __init__(self):
        self.positions = [0.0, 0.0, 80.0]
        self.index = 0

    def isOpened(self):
        return True

    def get(self, property_id):
        import cv2
        if property_id == cv2.CAP_PROP_FPS:
            return 25.0
        if property_id == cv2.CAP_PROP_POS_MSEC:
            value = self.positions[self.index]
            self.index += 1
            return value
        return 0.0

    def read(self):
        return True, object()

    def release(self):
        pass


class StreamReceiverTests(unittest.TestCase):
    def test_timestamp_remains_monotonic_when_opencv_repeats_zero(self):
        capture = FakeCapture()
        with patch("app.ingestion.stream_receiver.cv2.VideoCapture", return_value=capture):
            receiver = StreamReceiver("video.mp4")
            receiver.start()
            receiver.read()
            first = receiver.last_timestamp_seconds
            receiver.read()
            second = receiver.last_timestamp_seconds
            receiver.read()
            third = receiver.last_timestamp_seconds
        self.assertEqual(first, 0.0)
        self.assertAlmostEqual(second, 0.04)
        self.assertAlmostEqual(third, 0.08)
        self.assertLess(first, second)
        self.assertLess(second, third)


if __name__ == "__main__":
    unittest.main()
