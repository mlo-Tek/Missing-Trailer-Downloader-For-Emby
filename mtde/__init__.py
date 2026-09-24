__version__ = "0.3.13"

# Install the narrow MTDE safety layer before service.py imports trailer helpers.
# This keeps the upstream MTDP matcher as the base while filtering only the
# false-positive classes observed in real MTDE runs.
from .hardening import install_trailer_hardening

install_trailer_hardening()

# A normal scan may automatically repair a local trailer only when MTDE can
# prove from its own persistent logs that it downloaded that exact file and the
# recorded source candidate is unsafe under the current safety rules. Untracked
# local/manual trailers are never deleted automatically.
from .auto_repair import install_auto_repair

install_auto_repair()
