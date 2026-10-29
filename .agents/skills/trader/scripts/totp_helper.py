"""
TOTP Helper for Indian Broker 2FA Login
Generates the current 6-digit Time-based One-Time Password mandated by SEBI for daily API login.
"""

import sys
try:
    import pyotp
except ImportError:
    pyotp = None


def get_current_totp(secret: str) -> str:
    """
    Generate the active 6-digit TOTP code.

    Args:
        secret: The base32 TOTP secret string provided during 2FA setup in the broker portal.
    """
    if pyotp is None:
        raise ImportError("pyotp is required for automated TOTP. Install with: pip install pyotp")
    totp = pyotp.TOTP(secret.strip().replace(" ", ""))
    return totp.now()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        totp_secret = sys.argv[1]
        print(f"Generated TOTP: {get_current_totp(totp_secret)}")
    else:
        print("Usage: python totp_helper.py <YOUR_BASE32_TOTP_SECRET>")
