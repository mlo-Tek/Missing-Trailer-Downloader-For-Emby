__version__ = "0.3.17"

# Install the narrow MTDE safety layer before service.py imports trailer helpers.
# This keeps the upstream MTDP matcher as the base while filtering only the
# false-positive classes observed in real MTDE runs.
from .hardening import install_trailer_hardening

install_trailer_hardening()

# Automatic repair is destructive. Refine the supplemental safety classifier
# conservatively before auto_repair imports it so legitimate historical MTDE
# trailers are not deleted merely because their YouTube title contains release
# descriptors such as Exklusiv, Neuer, Extended, 3D, Restaurierung/Blu-ray,
# Kinotrailer or GermanTrailer.
from .safety_refinement import install_safety_refinement

install_safety_refinement()

# A normal scan may automatically repair a local trailer only when MTDE can
# prove from its own persistent logs that it downloaded that exact file and the
# recorded source candidate is unsafe under the current safety rules. Untracked
# local/manual trailers are never deleted automatically.
from .auto_repair import install_auto_repair

install_auto_repair()

# Add the contextual guards after auto-repair is installed so historical repair,
# replacement searches, subtitle validation and candidate-set ambiguity checks
# all share the same safety stack.
from .context_safety import install_contextual_safety

install_contextual_safety()
