"""Mist Core DAL

DAL can stand for 'Database Abstraction Layer', 'Data Access Layer' and
several more similar combinations.

The role of this DAL is to take control over all persistence related
operations like reading from and writing to some storage, locking for
conflict avoidance and caching for performance gain. The rest of the
application knows nothing about how the storage is implemented and is
only presented with a simple, object oriented API.

Mist.core.dal imports and extends mist.io.dal.

Mist core uses mongo as its storage backend, while also using memcache
for caching. Since it is multithreaded, it also needs to implement some
locking mechanism. Mist io uses yaml files as its storage backend.

In every case we store data using a main dict consisting of nested
dicts, lists, ints, strs etc. This module provides an object oriented
interface on those dicts.

Classes that inherit BaseModel are initiated using a dict. Dict keys are
on the fly transformed to object attributes, based on predefined fields.
A BaseModel subclass can have fields that are themselves BaseModel
derivatives or collections of BaseModel derivatives.
"""


import logging
import abc
from time import time, sleep
from contextlib import contextmanager


from pymongo import MongoClient
from memcache import Client as MemcacheClient


import mist.io.dal
from mist.io import config


log = logging.getLogger(__name__)


### Data Access Object ###


class FieldsDict(mist.io.dal.FieldsDict):
    """Override FieldsDict so that '.' in keys are escaped.

    This is due to mongo's limitation on dict keys. We transparently replace
    all '.' with '^' when reading/writing from/to mongo.

    """

    def __getitem__(self, key):
        if isinstance(key, basestring):
            key = key.replace('.', '^')
        return super(FieldsDict, self).__getitem__(key)

    def __setitem__(self, key, value):
        if isinstance(key, basestring):
            key = key.replace('.', '^')
        return super(FieldsDict, self).__setitem__(key, value)

    def __delitem__(self, key):
        if isinstance(key, basestring):
            key = key.replace('.', '^')
        return super(FieldsDict, self).__delitem__(key)

    def __iter__(self):
        for key in super(FieldsDict, self).__iter__():
            if isinstance(key, basestring):
                key = key.replace('^', '.')
            yield key


### Persistence handling ###


class OODictMongo(mist.io.dal.OODict):
    """Add mongo storage capabilities to OODict."""

    __metaclass__ = abc.ABCMeta

    def __init__(self, mongo_uri, mongo_db, mongo_coll, mongo_id="_id",
                 mongo_client=None, _dict=None):
        super(OODictMongo, self).__init__(_dict)
        self._mongo_uri = mongo_uri
        self._mongo_db = mongo_db
        self._mongo_coll = mongo_coll
        self._mongo_client = mongo_client
        self._mongo_id = mongo_id

    def _reinit(self, _dict=None):
        super(OODictMongo, self).__init__(_dict)

    def _get_mongo_coll(self):
        """Don't actually set up db connection unless it is needed."""
        if not self._mongo_client:
            log.error("Starting new mongo connection.")
            self._mongo_client = MongoClient(self._mongo_uri)
        db = self._mongo_client[self._mongo_db]
        collection = db[self._mongo_coll]
        return collection

    def get_from_field(self, key, value):
        """Get user by a key:value pair from mongo"""
        item = self._get_mongo_coll().find_one({key: value}) or {}
        self._reinit(item)

    def refresh(self):
        """Refresh self data from mongo."""
        self.get_from_field(self._mongo_id, self._dict[self._mongo_id])

    def save(self):
        """Save user data to mongo."""
        self._get_mongo_coll().save(self._dict)

    def delete(self):
        """Delete user from mongo."""
        self._get_mongo_coll().remove({self._mongo_id: self._dict[self._mongo_id]})

    def create(self):
        """Create user data to mongo."""
        self._get_mongo_coll().save(self._dict)
        self._reinit(self._dict)

    def __del__(self):
        if self._mongo_client:
            self._mongo_client.close()


class OODictMongoMemcache(OODictMongo):
    """Add memcache caching capabilities to a OODictMongo."""

    def __init__(self, memcache_host, mongo_uri, mongo_db, mongo_coll,
                 mongo_id="_id", mongo_client=None, memcache_client=None,
                 _dict=None):
        super(OODictMongoMemcache, self).__init__(
            mongo_uri, mongo_db, mongo_coll, mongo_id,
            mongo_client, _dict
        )
        self._memcache_host = memcache_host
        ## self._memcache_lock = memache_lock
        if memcache_client is None:
            self._memcache = MemcacheClient(memcache_host)
        else:
            self._memcache = memcache_client

    def _memcache_key(self, mongo_id=None):
        return str("%s:%s:%s" % (self._mongo_db, self._mongo_coll,
                             mongo_id or self._dict.get(self._mongo_id, '')))

    def get_from_field(self, key, value, flush=False):
        """Get user by a key:value pair from mongo or memcache."""

        # if searching by id key, then we can find it in memcache
        if not flush and key == self._mongo_id:
            item = self._memcache.get(self._memcache_key(value))
            if item:
                log.info("Cache hit.")
                return self._reinit(item)
        log.info("Cache miss.")
        # didn't find it in memcache, search in mongo and update cache
        super(OODictMongoMemcache, self).get_from_field(key, value)
        item = self._dict
        if item:
            self._memcache.set(self._memcache_key(), item)
            return self._reinit(item)

    def refresh(self, flush=False):
        """Refresh self data from memcache. If flush is True, then
        flush memcache entry and force a refresh from mongo.

        """
        self.get_from_field(self._mongo_id, self._dict[self._mongo_id], flush)

    def save(self):
        """Save user data to storage."""

        self._memcache.set(self._memcache_key(), self._dict)
        super(OODictMongoMemcache, self).save()

    def delete(self):
        """Delete user from storage."""
        self._memcache.delete(self._memcache_key())
        super(OODictMongoMemcache, self).delete()


class OODictMongoMemcacheLock(OODictMongoMemcache):
    """Add locking capabilities to a MongoMemcacheEngine."""

    _rlock = None

    def __init__(self, memcache_host, mongo_uri, mongo_db, mongo_coll,
                 mongo_id="_id", mongo_client=None, memcache_client=None,
                 _dict=None):
        super(OODictMongoMemcacheLock, self).__init__(
            memcache_host, mongo_uri, mongo_db, mongo_coll, mongo_id,
            mongo_client, memcache_client, _dict
        )
        lock_key = "%s:rlock" % self._memcache_key()
        self._rlock = MemcacheLock(self._memcache, lock_key)

    def _reinit(self, _dict=None):
        """Reinitiate the user object."""
        super(OODictMongoMemcacheLock, self)._reinit(_dict)
        lock_key = "%s:rlock" % self._memcache_key()
        self._rlock.reset(lock_key)

    @contextmanager
    def lock_n_load(self):
        """Acquire write lock on user and refresh self data. Afterwards,
        user data can be edited and saved by calling user.save().

        It must be used with a 'with' statement as follows:
            with user.lock_n_load():
                # edit user
                user.save()
        Lock is automatically released after exiting the 'with' block.
        """

        try:
            # don't refresh if reentering lock
            self._rlock.acquire() and self.refresh()
            log.debug("Acquired lock")
            yield   # here execution returns to the with statement
        except Exception as exc:
            # This block is executed if an exception is raised in the try
            # block above or inside the with statement that called this.
            # Returning False will reraise it.
            log.error("lock_n_load got an exception: %r" % exc)
            raise
        finally:
            # This block is always executed in the end no matter what
            # to ensure we always release the lock.
            # lock sanity check
            if not self._rlock.check():
                log.critical("Race condition   ! Aborting! Will "
                             "not release lock since we don't have it!")
                raise Exception('Race condition')
            else:
                # release lock
                log.debug("Releasing lock")
                self._rlock.release()

    def save(self):
        """Save user data to storage. Raises exception if not in a
        "with user.lock_n_load():" code block.
        """

        ## if self._memcache_lock:
        if not self._rlock.isset():
            raise Exception("Attempting to save without prior lock. "
                            "You should be ashamed of yourself.")

        # lock sanity check
        if not self._rlock.check():
            log.critical("Race condition! Aborting! Will not save!")
            raise Exception('Race condition detected!')

        # All went fine. Save to cache and database.
        super(OODictMongoMemcacheLock, self).save()

    def delete(self):
        """Delete user from storage."""
        with self.lock_n_load():
            super(OODictMongoMemcacheLock, self).delete()


class MemcacheLock(object):
    """This class implements a basic locking mechanism in memcache.
    The lock is initialized given a memcache host and a key where the
    lock info will be stored. When acquired, any MemcacheLock instance
    with the same key won't be able to acquire the lock. Once however
    a certain MemcacheLock instance has acquired a lock, its acquire()
    method can be called again. You have to release as many times as
    you lock. This doesn't implement the reentrant property the way
    usual Rlocks do. For example, it doesn't enforce that the releases
    are in exact reverse order of acquires. That however is enforced by
    the use of the with statement higher up in other classes using this
    one.
    """

    sleep = 0.05  # seconds to sleep while waiting for lock
    break_after = 10  # seconds to wait before breaking lock

    def __init__(self, memcache_client, key):
        self.key = key
        self.cache = memcache_client
        self.value = ''
        self.re_counter = 0  # reentrant counter

    def reset(self, key):
        if self.key != key:
            self.__init__(self.cache, key)

    def acquire(self):
        value = "%f" % time()

        # lock already acquired
        if self.value:
            if not self.check():
                pass  # FIXME : someone broke the lock?
            self.re_counter += 1
            return False

        # lock not already acquired by us
        times = 0
        while self.cache.get(self.key):
            sleep(self.sleep)
            times += 1
            if times * self.sleep >= self.break_after:
                log.critical("Hey, I've been waiting for lock '%s' "
                             "for %.1f secs! I'll brake the fucking "
                             "lock!" % (self.key, self.break_after))
                break
        self.cache.set(self.key, value)
        self.value = value
        if times:
            log.info("Slept for %.1f secs and then acquired "
                    "lock '%s'." % (times * self.sleep, self.key))
        else:
            log.debug("Acquired lock '%s'." % self.key)
        return True

    def release(self):
        if self.re_counter:
            self.re_counter -= 1
        else:
            log.debug("Releasing lock '%s'." % self.key)
            self.cache.delete(self.key)
            self.value = ''

    def check(self):
        if self.value:
            if self.cache.get(self.key) == self.value:
                return True
        pass

    def isset(self):
        return bool(self.value)

    def __repr__(self):
        return "MemcacheLock(key='%s')" % self.key


class User(OODictMongoMemcacheLock):

    def __init__(self, _dict=None, mongo_client=None, memcache_client=None):
        return super(User, self).__init__(
            memcache_host=config.MEMCACHED_HOST,
            mongo_uri=config.MONGO_URI,
            mongo_db='mist',
            mongo_coll='users',
            mongo_id='email',
            mongo_client=mongo_client,
            memcache_client=memcache_client,
            _dict=_dict
        )
