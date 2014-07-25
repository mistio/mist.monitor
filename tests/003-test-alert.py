from mist.alert import alert


def test_compute():
    def check(operator, aggregate, values, threshold, exp_state, exp_retval):
        args = (operator, aggregate, values, threshold)
        state, retval = alert.compute(*args)
        msg = "mist.alert.compute(%r, %r, %r, %r)" % args
        assert state == exp_state, "%s: state = %s != %s" % (msg, state,
                                                             exp_state)
        assert retval == exp_retval, "%s: retval = %s != %s" % (msg, retval,
                                                                exp_retval)

    check('gt', 'all', range(10), 50, False, 9)
    check('gt', 'all', range(10), 5, False, 5)
    check('gt', 'all', range(10), -1, True, 9)
    check('lt', 'all', range(10), -3, False, 0)
    check('lt', 'all', range(10), 3, False, 3)
    check('lt', 'all', range(10), 30, True, 0)

    check('gt', 'any', range(10), 50, False, 9)
    check('gt', 'any', range(10), 5, True, 9)
    check('gt', 'any', range(10), -1, True, 9)
    check('lt', 'any', range(10), -3, False, 0)
    check('lt', 'any', range(10), 3, True, 0)
    check('lt', 'any', range(10), 30, True, 0)

    check('gt', 'avg', range(10), 50, False, 4.5)
    check('gt', 'avg', range(10), 5, False, 4.5)
    check('gt', 'avg', range(10), 3, True, 4.5)
    check('gt', 'avg', range(10), -1, True, 4.5)
    check('lt', 'avg', range(10), -3, False, 4.5)
    check('lt', 'avg', range(10), 3, False, 4.5)
    check('lt', 'avg', range(10), 5, True, 4.5)
    check('lt', 'avg', range(10), 30, True, 4.5)
