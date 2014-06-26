def gen_composite_processor(*funcs):
    """Applies the each func on the metrics in a chain"""

    def composite_processor(host, name, val, timestamp):
        tmp = host, name, val, timestamp
        for func in funcs:
            tmp = func(*tmp)
            if tmp is None:
                break
        return tmp
    return composite_processor
