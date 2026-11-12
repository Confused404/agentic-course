import os
import sys

# The harness runs these against a WORKSPACE: PROMO_WORKSPACE points at it. The workspace goes AFTER this
# directory (so it can't shadow _helpers) and is only used to import promo.
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(1, os.environ.get("PROMO_WORKSPACE", os.getcwd()))
