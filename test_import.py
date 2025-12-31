import sys
import os

# Add the parent directory of custom_components to path
sys.path.append("/root/git/veronika-vacuum-manager/custom_components")

try:
    import veronika
    print("Successfully imported veronika package")
    from veronika import manager
    print("Successfully imported veronika.manager")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
