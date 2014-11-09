from django.core.cache import cache

from distributedlock import distributedlock, MemcachedLock


def CacheLock(key, lock=None, blocking=True, timeout=10000):
    if lock is None:
        lock = MemcachedLock(key=key, client=cache, timeout=timeout)

    return distributedlock(key, lock, blocking)


def NonBlockingCacheLock(key, lock=None, blocking=False, timeout=10000):
    if lock is None:
        lock = MemcachedLock(key=key, client=cache, timeout=timeout)

    return distributedlock(key, lock, blocking)

