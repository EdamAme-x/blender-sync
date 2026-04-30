from blender_sync.domain.entities import ChannelKind, IceServer


class InMemoryTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[ChannelKind, bytes]] = []
        self._recv_cb = None
        self._state_cb = None
        self.ice_servers: tuple[IceServer, ...] = ()
        self.closed = False

    def configure(self, ice_servers):
        self.ice_servers = ice_servers

    async def create_offer(self) -> str: return "v=0\no=offer"
    async def create_answer(self, offer_sdp: str) -> str: return "v=0\no=answer"
    async def accept_answer(self, answer_sdp: str) -> None: return
    async def gather_complete(self, timeout: float) -> None: return
    def local_description(self): return "v=0\no=local"

    async def send(self, channel, data: bytes) -> None:
        self.sent.append((channel, data))

    def on_recv(self, callback):
        self._recv_cb = callback

    def on_state_change(self, callback):
        self._state_cb = callback

    def deliver(self, channel: ChannelKind, data: bytes) -> None:
        if self._recv_cb:
            self._recv_cb(channel, data)

    async def close(self) -> None:
        self.closed = True
