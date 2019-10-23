import logging
# The StreamView object is a container that manages several atoms, whose activity
#   patterns are taken and then mixed. This is mainly motivated to modulate the diverse
#   activity patterns depending on the transformations.
from copy import deepcopy
from functools import reduce
from typing import Callable, Tuple, ClassVar

from somaxlibrary import Tools
from somaxlibrary.ActivityPattern import AbstractActivityPattern
from somaxlibrary.Atom import Atom
from somaxlibrary.Corpus import Corpus
from somaxlibrary.Exceptions import InvalidPath
from somaxlibrary.Labels import AbstractLabel
from somaxlibrary.MaxOscLib import DuplicateKeyError
from somaxlibrary.MemorySpaces import NGramMemorySpace
from somaxlibrary.Tools import SequencedList


class StreamView(object):
    def __init__(self, name: str, weight: float = 1.0, merge_actions: Tuple[Callable, ...] = None):
        self.logger = logging.getLogger(__name__)
        self.logger.debug("[__init__] Creating streamview {} with weight {} and merge actions {}"
                          .format(name, weight, merge_actions))

        self.name = name
        self._merge_actions = [cls() for cls in merge_actions] if merge_actions else []  # TODO: Maybe remove
        self.atoms: {str: Atom} = dict()
        self.streamviews: {str: StreamView} = {}
        self.weight = weight

    def __repr__(self):
        return "Streamview with name {0} and atoms {1}.".format(self.name, self.atoms)

    def get_streamview(self, path: [str]) -> 'StreamView':
        """ Raises: KeyError. Technically also IndexError, but should not occur if input is well-formatted (expected)"""
        if not path:
            return self

        target_name: str = path.pop(0)
        if path:  # Path is not empty: descend recursively
            return self.streamviews[target_name].get_streamview(path)
        else:
            return self.streamviews[target_name]

    def get_atom(self, path: [str]) -> Atom:
        """ Raises: KeyError. Technically also IndexError, but should not occur if input is well-formatted (expected)"""
        target_name: str = path.pop(0)
        if path:  # Path is not empty: descend recursively
            return self.streamviews[target_name].get_atom(path)
        else:
            return self.atoms[target_name]

    def create_atom(self, path: [str], weight: float, label_type: ClassVar[AbstractLabel],
                    activity_type: ClassVar[AbstractActivityPattern], memory_type: ClassVar[NGramMemorySpace],
                    corpus: Corpus, self_influenced: bool):
        """creating an atom at required path
        Raises: KeyError, InvalidPath, DuplicateKeyError"""
        self.logger.debug("[create_atom] Attempting to create atom with path {}.".format(path))

        new_atom_name: str = path.pop(-1)
        parent_streamview: 'StreamView' = self.get_streamview(path)
        if new_atom_name in parent_streamview.atoms.keys():
            raise DuplicateKeyError(f"An atom with the name '{new_atom_name}' already exists in "
                                    f"streamview '{parent_streamview.name}'.")
        parent_streamview.atoms[new_atom_name] = Atom(new_atom_name, weight, label_type, activity_type, memory_type,
                                                      corpus, self_influenced)

    def create_streamview(self, path: [str], weight: float, merge_actions: (ClassVar, ...)):
        """creating a streamview at required path
        Raises: KeyError, InvalidPath, DuplicateKeyError"""
        self.logger.debug("[create_streamview] Attempting to create streamview with path {}.".format(path))

        new_streamview_name: str = path.pop(-1)
        parent_streamview: 'StreamView' = self.get_streamview(path)
        if new_streamview_name in parent_streamview.streamviews.keys():
            raise DuplicateKeyError(f"A streamview with the name {new_streamview_name} already exists in "
                                    f"streamview {parent_streamview.name}.")
        parent_streamview.streamviews[new_streamview_name] = StreamView(new_streamview_name, weight, merge_actions)

    # # TODO: Only used at one place. Consider replacing/streamlining behaviour
    # def add_atom(self, atom, name=None, copy=False, replace=False):
    #     '''add an existing atom in the current streamview'''
    #     if name == None:
    #         name = atom.name
    #     if name in self.atoms.keys():
    #         if not replace:
    #             raise Exception("{0} already exists in {1}".format(atom.name, self.name))
    #     if copy:
    #         # TODO: Why? ~~~
    #         new_atom: Atom = deepcopy(atom)
    #         new_atom.name = name
    #         self.atoms[name] = new_atom
    #     else:
    #         self.atoms[name] = atom
    #
    # def get_atom(self, name, copy=False):
    #     '''fetching an atom'''
    #     path, path_bottom = Tools.parse_path(name)
    #     if path_bottom != None and path in self.atoms.keys():
    #         return self.atoms[path].get_atom(path_bottom)
    #     elif path_bottom == None and path in self.atoms.keys():
    #         return self.atoms[path]
    #     else:
    #         return None

    def delete_atom(self, name):
        '''deleting an atom'''
        if not ":" in name:
            del self.atoms[name]
        else:
            head, tail = Tools.parse_path(name)
            self.atoms[name].delete_atom(tail)

    # def influence(self, path, time, *data, **kwargs):
    #     '''influences all sub-atoms with data'''
    #     self.logger.debug("[influence] Call to influence in streamview {} with path {}, time {}, args {} and kwargs {}"
    #                       .format(self.name, path, time, data, kwargs))
    #     if path == None or path == "":
    #         for atom in self.atoms.values():
    #             atom.influence(time, *data)
    #     else:
    #         pf, pr = Tools.parse_path(path)
    #         if pf in self.atoms.keys():
    #             if isinstance(self.atoms[pf], Atom.Atom):
    #                 self.atoms[pf].influence(time, *data, **kwargs)
    #             elif isinstance(self.atoms[pf], StreamView):
    #                 self.atoms[pf].influence(pr, time, *data, **kwargs)
    #     self.logger.debug("[influence] Influence in streamview {} terminated successfully.".format(self.name))

    def read(self, corpus: Corpus):
        '''read all sub-atoms with data'''
        self.logger.debug(f"[read] Init read in streamview {self.name} with corpus {corpus}")
        for atom in self.atoms.values():
            atom.read(corpus)

    def get_activities(self, date, path=None, weighted=True):
        '''get separated activities of children'''
        if path != None:
            if ':' in path:
                head, tail = Tools.split_path(head, tail)
                activities = self.atoms[head].get_activities(date, path=tail)
            else:
                activities = self.atoms[path].get_activities(date)
        else:
            activities = dict()
            for name, atom in self.atoms.iteritems():
                activities[name] = atom.get_merged_activity(date, weighted=weighted)
        if issubclass(type(activities), Tools.SequencedList):
            activities = {path: activities}
        return activities

    def get_merged_activity(self, date, weighted=True):
        '''get merged activities of children'''
        weight_sum = float(reduce(lambda x, y: x + y.weight, self.atoms.values(), 0.0))  # TODO: Not used
        merged_activity = SequencedList()
        for atom in self.atoms.values():
            w = atom.weight if weighted else 1.0
            merged_activity = merged_activity + atom.get_activity(date).mul(w, 0)
        for merge_action in self._merge_actions:
            merged_activity = merge_action.merge(merged_activity)
        self.logger.debug("[get_merged_activity] In streamview {}, returning merged activity {}."
                          .format(self.name, merged_activity))
        return merged_activity

    def set_weight(self, path, weight):
        '''set weight of atom addressed at path'''
        if not ":" in path:
            self.atoms[path].set_weight(weight)
        else:
            head, tail = Tools.parse_path(path)
            self.atoms[head].set_weight(tail, weight)

    def get_info_dict(self):
        '''returns info dictionary'''
        infodict = {"activity type": str(type(self)), "weight": self.weight, "type": "Streamview"}
        infodict["atoms"] = dict()
        for a, v in self.atoms.items():
            infodict["atoms"][a] = v.get_info_dict()
        return infodict

    def reset(self, time):
        for f in self.atoms.values():
            f._reset(time)
