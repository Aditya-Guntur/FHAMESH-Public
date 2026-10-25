"""Inter-agent communication via Redis pub/sub."""

from .channels import ChannelRouter
from .middleware import MessageMiddleware
from .transport import RedisTransport
