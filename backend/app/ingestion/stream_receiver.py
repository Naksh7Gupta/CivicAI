"""Video stream receiver."""
import cv2


class StreamReceiver:

    def __init__(self, source):

        self.source = source

        self.capture = None

    def start(self):

        if not isinstance(self.source, (str, bytes)):
            raise TypeError("Video source must be a filesystem path.")

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