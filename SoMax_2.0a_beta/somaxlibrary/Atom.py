import logging
# Atom is the core object that contains an activity pattern and a memory space.
# He basically does two things : managing influences and updating activity.
from typing import ClassVar

from somaxlibrary import MemorySpaces
from somaxlibrary.ActivityPatterns import AbstractActivityPattern, ClassicActivityPattern
from somaxlibrary.Corpus import Corpus
from somaxlibrary.Labels import MelodicLabel, AbstractLabel
from somaxlibrary.MemorySpaces import AbstractMemorySpace
from somaxlibrary.Peak import Peak


class Atom(object):
    def __init__(self, name: str = "atom", weight: float = 1.0,
                 label_type: ClassVar[AbstractLabel] = MelodicLabel,
                 activity_type: ClassVar[AbstractActivityPattern] = ClassicActivityPattern,
                 memory_type: ClassVar[AbstractMemorySpace] = MemorySpaces.NGramMemorySpace,
                 corpus: Corpus = None, self_influenced: bool = False):
        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"[__init__ Creating atom '{name}'.")
        self.weight: float = weight
        self.activity_pattern: AbstractActivityPattern = activity_type()  # creates activity
        self.memory_space: AbstractMemorySpace = memory_type(corpus, label_type)
        self.name = name
        self.active = False
        self.self_influenced: bool = self_influenced
        if corpus:
            self.read(corpus, label_type)

    # def __repr__(self):
    #     return "Atom with {0} and {1}".format(type(self.activityPattern), type(self.memory_space))

    # Tells the memory space to load the file filez
    def read(self, corpus, label_type=ClassVar[MelodicLabel]):
        # if memory_type != None:
        #     if different memory type, create a new memory space
        # memory_class = getattr(MemorySpaces, memory_type)
        # self.memory_space = memory_class(label_type=label_type, contents_type=contents_type, event_type=event_type)
        # read file
        # self.logger.info("Atom {} reading file {}...".format(self.name, corpus))
        self.memory_space.read(corpus)
        # if success == False:
        #     TODO: Exception or log.error?
        #     raise Exception("[ERROR] failed to load the file ", corpus)
        # else:
        # self.logger.info("Atom {} file {} loaded".format(self.name, corpus))
        # set current file
        # self.current_file = corpus

    # set current weight of atom
    def set_weight(self, weight):
        self.logger.debug("[set_weight] Atom {} setting weight to {}.".format(self.name, weight))
        self.weight = float(weight)

    # influences the memory with incoming data
    def influence(self, label: AbstractLabel, time: float, **kwargs):
        # we get the activity peaks created by influence
        peaks: [Peak] = self.memory_space.influence(label, time, **kwargs)
        self.activity_pattern.update_activity(time)  # we update the activity profile to the current time
        if peaks:
            self.activity_pattern.insert(peaks)  # we insert the peaks into the activity profile

    # external method to get back atom's activity
    def get_activity(self, date, weighted=True):
        w = self.weight if weighted else 1.0
        activity = self.activity_pattern.get_activity(date)
        # returns weighted activity
        return activity.mul(w, 0)

    # sugar
    def get_activities(self, date, weighted=True):
        return self.get_activity(date, weighted)

    def get_merged_activity(self, date, weighted=True):
        return self.get_activity(date, weighted)

    # own copy method
    # def copy(self, name):
    #     atom = Atom(name=name, weight=self.weight, label_type=self.memory_space.label_type,
    #                 contents_type=self.memory_space.contents_type, event_type=self.memory_space.event_type,
    #                 activity_type=self.activity_type, memory_type=self.memory_type)
    #     atom.memory_space = self.memory_type(self.memory_space.get_dates_list(), self.memory_space.get_events_list(),
    #                                          label_type=self.memory_space.label_type,
    #                                          contents_type=self.memory_space.contents_type,
    #                                          event_type=self.memory_space.event_type)
    #     atom.current_file = self.current_file
    #     return atom

    # external method to fetch properties of the atom
    # def get_info_dict(self):
    #     infodict = {"activity": self.activityPattern.__desc__(), "memory": self.memory_space.__desc__(),
    #                 "event_type": self.memory_space.event_type.__desc__(),
    #                 "label_type": self.memory_space.label_type.__desc__(),
    #                 "contents_type": self.memory_space.contents_type.__desc__(), "name": self.name,
    #                 "weight": self.weight, "type": "Atom", "active": self.active}
    #     if self.current_file != None:
    #         infodict["current_file"] = str(self.current_file)
    #         infodict["length"] = len(self.memory_space)
    #     else:
    #         infodict["current_file"] = "None"
    #         infodict["length"] = 0
    #     return infodict

    # def isAvailable(self):
    #     return self.activityPattern.isAvailable() and self.memory_space.is_available()

    def reset(self, time):
        self.activity_pattern.reset(time)
