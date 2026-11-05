"""Video stream receiver."""
import cv2


class StreamReceiver:

    def __init__(self, source=0):

        self.source = source

        self.capture = None

    def start(self):

        self.capture = cv2.VideoCapture(
            self.source
        )

        if not self.capture.isOpened():

            raise RuntimeError(
                "Unable to open video stream"
            )

    def read(self):

        if self.capture is None:
            return None

        success, frame = self.capture.read()

        if not success:
            return None

        return frame

    def release(self):

        if self.capture:
            self.capture.release()