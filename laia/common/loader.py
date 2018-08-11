from __future__ import absolute_import

import os
from glob import glob
from importlib import import_module
from typing import Optional, Callable, Any

import torch

from laia.common.logging import get_logger
from laia.common.random import set_rng_state
import natsort as ns


try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError

_logger = get_logger(__name__)


class Loader(object):
    def __call__(self, *args, **kwargs):
        return self.load(*args, **kwargs)

    def load(self, *args, **kwargs):
        raise NotImplementedError


class BasicLoader(Loader):
    def load(self, filepath, gpu=None):
        # type: (str, Optional[int]) -> Optional
        device = "cuda:{}".format(gpu - 1) if gpu else "cpu"
        try:
            return torch.load(filepath, map_location=device)
        except FileNotFoundError:
            _logger.info("Could not find the file {}", filepath)
        return None


class ObjectLoader(Loader):
    def __init__(self, filepath, gpu=None):
        # type: (str, Optional[int]) -> None
        self._filepath = filepath
        self._gpu = gpu
        self._loader = BasicLoader()

    def load(self):
        # type: () -> Optional
        obj = self._loader.load(self._filepath, gpu=self._gpu)
        if obj is None:
            return None
        module = import_module(obj["module"])
        fn = getattr(module, obj["name"])
        args = obj.get("args", [])
        kwargs = obj.get("kwargs", {})
        return fn(*args, **kwargs)


class ModelLoader(ObjectLoader):
    def __init__(self, load_path, filename="model", gpu=None):
        # type: (str, str, Optional[int]) -> None
        self._path = os.path.join(load_path, filename)
        super(ModelLoader, self).__init__(self._path, gpu=gpu)

    def load(self):
        # type: () -> Optional
        model = super(ModelLoader, self).load()
        if model is not None:
            _logger.info("Loaded model {}", self._path)
        return model


class CheckpointLoader(Loader):
    def __init__(self, gpu=None):
        # type: (int) -> None
        self._gpu = gpu
        self._loader = BasicLoader()

    def load(self, filepath):
        # type: (str) -> Optional
        state = self._loader.load(filepath, gpu=self._gpu)
        if state is not None:
            _logger.info("Loaded checkpoint {}", filepath)
        return state

    def load_by(self, pattern, key=None, reverse=True):
        # type: (str, Optional[Callable], bool) -> Optional
        matches = glob(pattern)
        if not len(matches):
            return None
        filepath = ns.natsorted(matches, key=key, reverse=reverse, alg=ns.ns.PATH)[0]
        return self.load(filepath)


class ModelCheckpointLoader(CheckpointLoader):
    def __init__(self, model, gpu=None):
        # type: (torch.nn.Module, int) -> None
        super(ModelCheckpointLoader, self).__init__(gpu=gpu)
        self._model = model

    def load(self, filepath):
        # type: (str) -> Optional
        state = super(ModelCheckpointLoader, self).load(filepath)
        if state is not None:
            self._model.load_state_dict(state)

    def load_by(self, pattern, key=None, reverse=True):
        # type: (str, Optional[Callable], bool) -> Optional
        state = super(ModelCheckpointLoader, self).load_by(
            pattern, key=key, reverse=reverse
        )
        if state is not None:
            self._model.load_state_dict(state)


class StateCheckpointLoader(CheckpointLoader):
    def __init__(self, obj, gpu=None):
        # type: (Any, int) -> None
        super(StateCheckpointLoader, self).__init__(gpu=gpu)
        self._obj = obj

    def load(self, filepath):
        # type: (str) -> Optional
        state = super(StateCheckpointLoader, self).load(filepath)
        if state is not None:
            set_rng_state(state.pop("rng"), self._gpu)
            self._obj.load_state_dict(state)

    def load_by(self, pattern, key=None, reverse=True):
        # type: (str, Optional[Callable], bool) -> Optional
        state = super(StateCheckpointLoader, self).load_by(
            pattern, key=key, reverse=reverse
        )
        if state is not None:
            set_rng_state(state.pop("rng"))
            self._obj.load_state_dict(state)