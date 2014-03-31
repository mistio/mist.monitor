from random import getrandbits


def get_rand_token(bits=256):
    """Generate a random number of specified length and return its hex string.

    Default is to generate 256 bits = 32 bytes, resulting in a 64 characters
    token to be generated (since a byte needs 2 hex chars).

    """
    return hex(getrandbits(bits))[2:-1]


def tdelta_to_str(secs):
    parts = []
    if not secs:
        return ""
    mins, secs = divmod(secs, 60)
    parts.append((secs, 'sec'))
    if mins:
        hours, mins = divmod(mins, 60)
        parts.append((mins, 'min'))
        if hours:
            days, hours = divmod(hours, 24)
            parts.append((hours, 'hour'))
            if days:
                parts.append((days, 'day'))
    texts = []
    for num, label in reversed(parts):
        if num > 1:
            label += 's'
        texts.append("%d %s" % (num, label))
    return ", ".join(texts)
