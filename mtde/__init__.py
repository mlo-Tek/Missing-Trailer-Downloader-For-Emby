__version__ = "0.4.0"

# Install the narrow movie safety layer before service.py imports trailer helpers.
# Movie matching remains based on upstream MTDP Movies.py, with only the proven
# false-positive guards requested during the Emby port.
from .hardening import install_trailer_hardening

install_trailer_hardening()

from .safety_refinement import install_safety_refinement

install_safety_refinement()

from .auto_repair import install_auto_repair

install_auto_repair()

from .context_safety import install_contextual_safety

install_contextual_safety()

from .ambiguity_refinement import install_ambiguity_refinement

install_ambiguity_refinement()

from .upgrade_temp_fix import install_upgrade_temp_fix

install_upgrade_temp_fix()

from .final_safety import install_final_safety

install_final_safety()

# Web performance/cache adaptation for Emby. This does not define the scanner;
# Movies + TV processing now live in the core service again, matching upstream's
# separate Movies.py / TV.py design.
from .ui_tv_perf import install_ui_tv_performance
from .ui_tv_perf_refinement import install_ui_tv_performance_refinement

install_ui_tv_performance()
install_ui_tv_performance_refinement()

from .dashboard_resolution_filter import install_dashboard_resolution_filter

install_dashboard_resolution_filter()
