import asyncio
import json
import logging
import os
import ssl
import uuid

import cv2
from aiohttp import web
from av import VideoFrame

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder, MediaRelay


ROOT = os.path.dirname(__file__)

logger = logging.getLogger("pc")
pcs = set()
relay = MediaRelay()


class VideoTransformTrack(MediaStreamTrack):

    kind = "video"

    def __init__(self, track, transform):
        super().__init__()
        self.track = track
        self.transform = transform

    async def recv(self):
        frame = await self.track.recv()
        if self.transform == "rotate":
            img = frame.to_ndarray(format="bgr24")
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
            frame = VideoFrame.from_ndarray(img, format="bgr24")
            cv2.imshow("frame", img)
            cv2.waitKey(1)
            return frame
        else:
            return frame


async def offer(request):
    print("something")
    params = await request.json()

    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pc_id = "PeerConnection(%s)" % uuid.uuid4()
    pcs.add(pc)

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("Created for %s", request.remote)

    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str) and message.startswith("ping"):
                channel.send("pong" + message[4:])

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state change %s", pc.connection_state)
        if pc.connection_state == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("tracks")
    async def on_tracks(track):
        log_info("Got %d tracks", len(track))

        if track.kind == "video":
            pc.addTrack(VideoTransformTrack(track, "rotate"))
        else:
            pc.addTrack(track)

        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.id)

    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_post("/offer", offer)
    web.run_app(app, host="0.0.0.0", port=8000
                )
