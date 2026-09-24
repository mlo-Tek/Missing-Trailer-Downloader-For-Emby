__version__ = "0.3.12"

# Install the narrow MTDE safety layer before service.py imports trailer helpers.
# This keeps the upstream MTDP matcher as the base while filtering only the
# false-positive classes observed in real MTDE runs.
from .hardening import install_trailer_hardening

install_trailer_hardening()
