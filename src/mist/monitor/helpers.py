from random import getrandbits
def get_rand_token(bits=256):
    """Generate a random number of specified length and return its hex string.

    Default is to generate 256 bits = 32 bytes, resulting in a 64 characters
    token to be generated (since a byte needs 2 hex chars).

    """
    return hex(getrandbits(bits))[2:-1]

