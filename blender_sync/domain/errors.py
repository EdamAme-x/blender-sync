class SyncError(Exception):
    pass


class TransportError(SyncError):
    pass


class SignalingError(SyncError):
    pass


class CodecError(SyncError):
    pass


class TokenParseError(SyncError):
    pass


class SceneError(SyncError):
    pass
