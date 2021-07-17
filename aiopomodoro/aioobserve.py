"""asyncio-based observation of attribute mutation events.

This module provides an ObservableMixIn mix-in to make any class observable.

observe(observable, name) asynchronously yields the value of the `name`
attribute on modification.

The special sentinel value DELETED signifies attribute deletion."""

from contextlib import ExitStack
from collections import defaultdict
import asyncio
from inspect import isawaitable

__all__ = ["ObservableMixIn", "observe", "notify", "seq", "switch", "DELETED"]

SENTINEL = object()

# Sentinel value indicating an attribute deletion event
DELETED = object()

class ObservableMixIn:
    """Mix-in class facilitating observation of attribute changes."""
    def __init__(self, *args, **kwargs):
        self.__dict__[SENTINEL] = defaultdict(set)
        super().__init__(*args, **kwargs)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if SENTINEL in (o := self.__dict__) and (o := o[SENTINEL].get(name)):
            for function in o:
                function(value)

    def __delattr__(self, name):
        super().__delattr__(name)
        if SENTINEL in (o := self.__dict__) and (o := o[SENTINEL].get(name)):
            for function in o:
                function(DELETED)

def state(event, sentinel, value=None):
    while True:
        if (update := (yield value)) is sentinel:
            event.clear()
        else:
            value = update
            event.set()

async def observe(observable, name, *, factory=asyncio.Event):
    """Observes the attribute `name` for changes.
    
    Asynchronously yields attribute values, blocking until a new value
    is assigned."""
    s = state(signal := factory(), read := object())
    s.send(None)
    try:
        observable.__dict__[SENTINEL][name].add(s.send)
        while True:
            await signal.wait()
            yield s.send(read)
    finally:
        if (o := observable.__dict__.get(SENTINEL)) and (o := o.get(name)):
            o.discard(s.send)

def notify(observable, *args):
    """Given an observable object, notifies all observers of the given
    attributes.
    
    Returns the number of notifications fired."""
    count = 0
    for name in args:
        if (callbacks := observable.__dict__[SENTINEL].get(name)):
            value = getattr(observable, name)
            for function in callbacks:
                function(value)
                count += 1
    return count

def seq(observable, name, function=None, *, factory=asyncio.Event):
    """Returns a coroutine that sequentially calls the decorated function or
    coroutine, passing every change in the given observable."""
    async def coroutine(function):
        async for value in observe(observable, name, factory=factory):
            if isawaitable(awaitable := function(value)):
                await awaitable
    return coroutine if function is None else coroutine(function)

def switch(observable, name, function=None, *, factory=asyncio.Event):
    """Returns a coroutine that calls the decorated coroutine, cancelling
    the previously active coroutine."""
    async def coroutine(function):
        with ExitStack() as stack:
            async for value in observe(observable, name, factory=factory):
                if isawaitable(awaitable := function(value)):
                    stack.close()
                    task = asyncio.create_task(awaitable)
                    stack.callback(task.cancel)
    return coroutine if function is None else coroutine(function)

observe.seq = seq
observe.switch = switch
