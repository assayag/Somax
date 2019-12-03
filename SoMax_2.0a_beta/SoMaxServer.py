import argparse
import asyncio
import logging
import logging.config
import os
from typing import ClassVar, Any, Dict, Union

from maxosc.MaxOsc import Caller
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

from somaxlibrary.ActivityPattern import AbstractActivityPattern
from somaxlibrary.CorpusBuilder import CorpusBuilder
from somaxlibrary.CorpusEvent import CorpusEvent
from somaxlibrary.Exceptions import InvalidPath, InvalidLabelInput, DuplicateKeyError, InvalidJsonFormat, ParameterError
from somaxlibrary.IOParser import IOParser
from somaxlibrary.Labels import AbstractLabel
from somaxlibrary.MemorySpaces import AbstractMemorySpace
from somaxlibrary.MergeActions import AbstractMergeAction
from somaxlibrary.Player import Player
from somaxlibrary.Target import Target, SimpleOscTarget
from somaxlibrary.Transforms import AbstractTransform
from somaxlibrary.scheduler.ScheduledObject import TriggerMode
from somaxlibrary.scheduler.Scheduler import Scheduler


class SoMaxServer(Caller):

    def __init__(self, in_port: int, out_port: int, ip: str = IOParser.DEFAULT_IP):
        super(SoMaxServer, self).__init__(parse_parenthesis_as_list=False)
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing SoMaxServer with input port {in_port} and ip '{ip}'.")
        self.players: {str: Player} = dict()
        self.scheduler = Scheduler()
        self.builder = CorpusBuilder()
        self.ip: str = ip
        self.in_port: int = in_port
        self.out_port: int = out_port
        self.target: Target = SimpleOscTarget("/server", out_port, ip)  # TODO: Change to multiosctarget for distributed
        self.server: AsyncIOOSCUDPServer = None
        self.io_parser: IOParser = IOParser()

    async def _run(self) -> None:
        self.logger.info("SoMaxServer started.")
        osc_dispatcher: Dispatcher = Dispatcher()
        osc_dispatcher.map("/server", self._process_osc)
        osc_dispatcher.set_default_handler(self._unmatched_osc)
        self.server: AsyncIOOSCUDPServer = AsyncIOOSCUDPServer((self.ip, self.in_port), osc_dispatcher,
                                                               asyncio.get_event_loop())
        transport, protocol = await self.server.create_serve_endpoint()
        await self.scheduler.init_async_loop()
        transport.close()
        self.logger.info("SoMaxServer was successfully terminated.")


    def _process_osc(self, _address, *args):
        # TODO: Move string formatting elsewhere
        args_formatted: [str] = []
        for arg in args:
            if isinstance(arg, str) and " " in arg:
                args_formatted.append("'" + arg + "'")
            else:
                args_formatted.append(str(arg))
        args_str: str = " ".join([str(arg) for arg in args_formatted])
        self.call(args_str)

    def _unmatched_osc(self, address: str, *_args, **_kwargs) -> None:
        self.logger.info("The address {} does not exist.".format(address))

    # TODO: Send properly over OSC
    def send_warning(self, warning: str, *args, **kwargs):
        print(warning)

    ######################################################
    # CREATION OF PLAYERS/STREAMVIEWS/ATOMS
    ######################################################

    def new_player(self, name: str, port: int, ip: str = "", trig_mode: str = "", override: bool = False):
        # TODO: Parse merge actions, peakselector
        if name in self.players:
            if not override:
                self.logger.error(f"A player with the name '{name}' already exists.")
                return
            else:
                self.delete_player(name)
        address: str = self.io_parser.parse_osc_address(name)
        ip: str = self.io_parser.parse_ip(ip)
        trig_mode: TriggerMode = self.io_parser.parse_trigger_mode(trig_mode)
        target: Target = SimpleOscTarget(address, port, ip)
        self.players[name] = Player(name, target, trig_mode)

        if trig_mode == TriggerMode.AUTOMATIC:
            self.scheduler.add_trigger_event(self.players[name])
        self.logger.info(f"Created player '{name}' with port {port} and ip {ip}.")

    def delete_player(self, name: str):
        try:
            self.scheduler.delete_trigger(self.players[name])
            del self.players[name]
        except KeyError:
            self.logger.error(f"No player deleted as a player named {name} does not exist.")


    @staticmethod
    def _osc_callback(self):
        pass  # TODO: implement

    # TODO: Clean up default arguments.
    # TODO: Rather player and path as one argument: player:s1:atom1, etc
    def create_streamview(self, player: str, path: str = "streamview", weight: float = 1.0,
                          merge_actions=""):
        self.logger.debug("[create_streamview] called for player {0} with name {1}, weight {2} and merge actions {3}."
                          .format(player, path, weight, merge_actions))
        path_and_name: [str] = IOParser.parse_streamview_atom_path(path)
        merge_actions: [AbstractMergeAction] = self.io_parser.parse_merge_actions(merge_actions)

        try:
            self.players[player].create_streamview(path_and_name, weight, merge_actions)
            self.logger.info(f"Created streamview with path '{player + '::' + path}'")
        except KeyError:
            self.logger.error(f"Could not create streamview for player '{player}' at path '{path}'.")
        except DuplicateKeyError as e:
            self.logger.error(f"{str(e)} No streamview was created.")

    def create_atom(self, player: str, path: str, weight: float = 1.0, label: str = "",
                    activity_type: str = "", memory_type: str = "", self_influenced: bool = False,
                    transforms: (str, ...) = (""), transform_parse_mode=""):
        self.logger.debug(f"[create_atom] called for player {player} with path {path}.")
        path_and_name: [str] = IOParser.parse_streamview_atom_path(path)
        label: ClassVar[AbstractLabel] = self.io_parser.parse_label_type(label)
        activity_type: ClassVar[AbstractActivityPattern] = self.io_parser.parse_activity_type(activity_type)
        memory_type: ClassVar[AbstractMemorySpace] = self.io_parser.parse_memspace_type(memory_type)

        try:
            transforms: [(ClassVar[AbstractTransform], ...)] = self.io_parser.parse_transforms(transforms,
                                                                                               transform_parse_mode)
        except IOError as e:
            self.logger.error(f"{str(e)} Setting Transforms to default.")
            transforms: [(ClassVar[AbstractTransform], ...)] = IOParser.DEFAULT_TRANSFORMS
        try:
            self.players[player].create_atom(path_and_name, weight, label, activity_type, memory_type,
                                             self_influenced, transforms)
            self.logger.info(f"Created atom with path '{player + '::' + path}'")
            self.players[player]._parse_parameters()    # TODO: Not ideal
        except InvalidPath as e:
            self.logger.error(f"Could not create atom at path {path}. [Message]: {str(e)}")
        except KeyError:
            self.logger.error(f"Could not create atom at path {path}. The parent streamview/player does not exist.")
        except DuplicateKeyError as e:
            self.logger.error(f"{str(e)}. No atom was created.")

    def add_transform(self, player: str, path: str, transforms: [str], parse_mode=""):
        self.logger.debug(f"[add_transform] called for player {player} with path {path}.")
        path_and_name: [str] = self.io_parser.parse_streamview_atom_path(path)
        try:
            transforms: [(ClassVar[AbstractTransform], ...)] = self.io_parser.parse_transforms(transforms, parse_mode)
        except IOError as e:
            self.logger.error(f"{str(e)} No Transform was added.")
            return
        try:
            self.players[player].add_transforms(path_and_name, transforms)
        except KeyError:
            self.logger.error(f"Could not add transform at path {path}. The parent streamview/player does not exist.")
        # TODO: parameter dict

    ######################################################
    # SCHEDULER
    ######################################################

    def start(self):
        self.clear_all()
        self.scheduler.start()
        self.logger.info(f"Scheduler Started. Current beat is {self.scheduler.beat}.")

    def stop(self):
        """stops the scheduler and reset all players"""
        # TODO: IO Error handling
        self.scheduler.stop()
        self.clear_all()
        self.logger.info("Scheduler was stopped.")

    def clear_all(self):
        for player in self.players.values():
            player.clear()

    def get_time(self):
        self.target.send_simple("time", self.scheduler.time)

    def get_tempo(self):
        self.target.send_simple("tempo", self.scheduler.tempo)

    def set_tempo(self, tempo: float):
        # TODO: Error checking
        self.scheduler.add_tempo_event(self.scheduler.time, tempo)

    def set_tempo_master(self, player: Union[str, None]):
        try:
            self.scheduler.tempo_master = self.players[player]
            self.logger.debug(f"[set_tempo_master] Tempo master set to '{player}'.")
            self.target.send_simple("tempo_master", True)
        except KeyError:
            if player is None:
                self.scheduler.tempo_master = None
            else:
                self.logger.error(f"No player named '{player}' exists.")
                self.target.send_simple("tempo_master", False)



    ######################################################
    # TIMING METHODS
    ######################################################

    # TODO: Reimplement
    # def set_tempo(self, tempo):
    #     tempo = float(tempo)
    #     self.scheduler.set_tempo(tempo)
    #     self.client.send_message("/tempo", tempo)

    # TODO: Reimplement
    # def set_original_tempo(self, original_tempo):
    #     self.original_tempo = bool(original_tempo)
    #     self.scheduler.set_original_tempo(self.original_tempo)

    ######################################################
    # FEEDBACK METHODS
    ######################################################

    # TODO:Reimplement
    # def set_activity_feedback(self, _address, content):
    #     path, player = content[0:2]
    #     if path == "None":
    #         path = None
    #     if player in self.players:
    #         self.players[player]["output_activity"] = path

    # TODO: activity_profile
    # def send_activity_profile(self, time):
    #     for n, p in self.players.items():
    #         if p["output_activity"]:
    #             if p["output_activity"] == 'Player':
    #                 path = None
    #             else:
    #                 path = p["output_activity"]
    #             activity_profiles = p['player'].get_activities(time, path=path, weighted=True)
    #             final_activity_str = ""
    #             for st, pr in activity_profiles.iteritems():
    #                 for d, e in pr:
    #                     final_activity_str += str(d) + " " + str(e[0]) + " " + st + " "
    #                     if len(final_activity_str) > 5000:
    #                         break
    #                 if len(final_activity_str) > 5000:
    #                     break
    #             p['player'].send(final_activity_str, "/activity")

    # TODO: parameter_dict
    # def send_parameter_dict(self, *_args):
    #     info = dict()
    #     info["players"] = dict()
    #     for name, player in self.players.items():
    #         info["players"][name] = player['player'].get_parameter_dict()
    #
    #     def get_class_name(obj):
    #         return obj.__name__
    #
    #     def regularize(corpus_list):
    #         corpus_list = list(map(lambda x: os.path.splitext(x)[0], corpus_list))
    #         corpus_list = reduce(lambda x, y: str(x) + " " + str(y), corpus_list)
    #         return corpus_list
    #
    #     info["memory_types"] = regularize(map(get_class_name, sm.MEMORY_TYPES))
    #     info["event_types"] = regularize(map(get_class_name, sm.EVENT_TYPES))
    #     info["label_types"] = regularize(map(get_class_name, sm.LABEL_TYPES))
    #     info["contents_types"] = regularize(map(get_class_name, sm.CONTENTS_TYPES))
    #     info["transform_types"] = regularize(map(get_class_name, sm.TRANSFORM_TYPES))
    #     info["timing_type"] = self.scheduler.timing_type
    #     corpus_list = filter(lambda x: x[0] != "." and os.path.splitext(x)[1] == ".json", os.listdir("corpus/"))
    #     corpus_list = map(lambda x: os.path.splitext(x)[0], corpus_list)
    #     corpus_list = reduce(lambda x, y: str(x) + " " + str(y), corpus_list)
    #     info["corpus_list"] = corpus_list
    #
    #     self.client.send_message("/serverdict", "clear")
    #     messages = sm.Tools.dic_to_strout(info)
    #     for m in messages:
    #         self.client.send_message("/serverdict", m)
    #     self.client.send_message("/serverdict", " ")

    ######################################################
    # EVENTS METHODS
    ######################################################

    # TODO: Remove and change into generic set param
    def trigger_mode(self, player: str, mode: str):
        trigger_mode: TriggerMode = self.io_parser.parse_trigger_mode(mode)
        try:
            previous_trigger_mode: TriggerMode = self.players[player].trigger_mode
            self.players[player].trigger_mode = trigger_mode
            self.players[player]._parse_parameters()    # TODO: Definitely not ideal
            # self.players[player].update_parameter_dict()
        except KeyError:
            self.logger.error(f"Could not set mode. No player named '{player}' exists.")
            return
        if previous_trigger_mode != trigger_mode and trigger_mode == TriggerMode.AUTOMATIC:
            self.scheduler.add_trigger_event(self.players[player])
        self.logger.debug(f"[trigger_mode]: Trigger mode set to '{trigger_mode}' for player '{player}'.")

    # TODO: Reimplement or remove
    # def new_event(self, player_name, time=None, event=None):
    #     self.logger.debug("[new_event] Call to new_event for player {} at time {} with content {}."
    #                       .format(player_name, time, event))
    #     time = self.scheduler.time if time is None else time
    #     if event is not None:
    #         self.scheduler.reset(player_name)
    #     self.process_intern_event(('ask_for_event', player_name, time, event))
    #     self.logger.debug("[new_event] New event created.")

    def influence(self, player: str, path: str, label_keyword: str, value: Any, **kwargs):
        self.logger.debug(f"[influence] called for player '{player}' with path '{path}', "
                          f"label keyword '{label_keyword}', value '{value}' and kwargs {kwargs}")
        try:
            labels: [AbstractLabel] = AbstractLabel.classify_as(label_keyword, value, **kwargs)
        except InvalidLabelInput as e:
            self.logger.error(str(e) + "No action performed.")
            return
        # TODO: Error handling (KeyError players + path_and_name)
        path_and_name: [str] = IOParser.parse_streamview_atom_path(path)
        time: float = self.scheduler.time
        try:
            for label in labels:
                self.players[player].influence(path_and_name, label, time, **kwargs)
        except KeyError:
            self.logger.error(f"No player named '{player}' exists.")

    def influence_onset(self, player):
        try:
            if self.players[player].trigger_mode == TriggerMode.MANUAL:
                self.logger.debug(f"[influence_onset] Influence onset triggered for player '{player}'.")
                self.scheduler.add_trigger_event(self.players[player])
        except KeyError:
            self.logger.error(f"No player named '{player}' exists.")

    # TODO: Implement jump
    # def jump(self, player):
    #     # TODO: IO Error handling
    #     self.logger.debug("[jump] called for player {0}.".format(player))
    #     self.players[player].jump()

    def read_corpus(self, player: str, filepath: str):
        # TODO: IO Error handling
        self.logger.debug(f"[read_corpus] called for player '{player}' and file '{filepath}'.")
        self.logger.info(f"Reading corpus at '{filepath}' for player '{player}'...")
        try:
            self.players[player].read_corpus(filepath)
            self.logger.info(f"Corpus successfully loaded in player '{player}'.")
        except KeyError:
            self.logger.error(f"Could not load corpus. No player named '{player}' exists.")
        except InvalidJsonFormat as e:
            self.logger.error(f"{str(e)} No corpus was read. (recommended action: rebuild corpus)")

    def set_param(self, path: str, value: Any):
        self.logger.debug(f"[set_param] Setting parameter at '{path}' to {value} (type={type(value)}).")
        path_parsed: [str] = IOParser.parse_streamview_atom_path(path)
        try:
            player: str = path_parsed.pop(0)
            self.players[player].set_param(path_parsed, value)
        except (IndexError, KeyError):
            self.logger.error(f"Invalid path")  # TODO Proper message
        except ParameterError as e:
            self.logger.error(str(e))

    def get_param(self, path: str):
        path_parsed: [str] = IOParser.parse_streamview_atom_path(path)
        try:
            player: str = path_parsed.pop(0)
            self.target.send_simple("param", [path, self.players[player].get_param(path_parsed).value])
        except (IndexError, KeyError):
            self.logger.error(f"Invalid path")  # TODO Proper message
        except ParameterError as e:
            self.logger.error(str(e))

    ######################################################
    # MAX INTERFACE INFORMATION
    ######################################################


    def parameter_dict(self):
        self.logger.debug(f"[parameter_dict] creating parameter_dict.")
        parameter_dict: Dict[str, Dict[str, ...]] = {}
        for name, player in self.players.items():
            parameter_dict[name] = player.max_representation()
        self.target.send_dict(parameter_dict)

    def get_corpus_files(self):
        filepath: str = os.path.join(os.path.dirname(__file__), "Corpus")
        for file in os.listdir(filepath):
            if file.endswith(".json"):
                corpus_name, _ = os.path.splitext(file)
                self.target.send_simple("corpus_info", (corpus_name, os.path.join(filepath, file)))
        self.target.send_simple("corpus_info", ["bang"])

    def get_player_names(self):
        for player_name in self.players.keys():
            self.target.send_simple("player_name", [player_name])

    def get_peaks(self, player: str):
        # TODO: IO Error handling
        try:
            self.players[player].send_peaks(self.scheduler.time)
        except KeyError:
            return

    def poll_server(self):
        self.target.send_simple("poll_server", ["bang"])



    ######################################################
    # CORPUS METHODS
    ######################################################

    def build_corpus(self, path, output='corpus/', **kwargs):
        # TODO: IO Error handling
        self.logger.info(f"Building corpus from file '{path}' to location'{output}.")
        self.builder.build_corpus(path, output, **kwargs)
        self.logger.info("File {0} has been output at location '{1}'".format(path, output))
        # TODO: Info dict
        # self.send_parameter_dict()

    ######################################################
    # DEBUGGING
    ######################################################

    def _debug_state(self, player: str, state_index: int):
        event: CorpusEvent = self.players[player].corpus.event_at(state_index)
        self.scheduler.add_corpus_event(self.players[player], self.scheduler.time, event)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Launch and manage a SoMaxServer')
    parser.add_argument('in_port', metavar='IN_PORT', type=int, nargs=1,
                        help='in port used by the server')
    parser.add_argument('out_port', metavar='OUT_PORT', type=int, nargs=1,
                        help='out port used by the server')
    # TODO: Ip as input argument

    logging.config.fileConfig('logging.ini', disable_existing_loggers=False)

    args = parser.parse_args()
    in_port = args.in_port[0]
    out_port = args.out_port[0]
    somax_server = SoMaxServer(in_port, out_port)


    async def gather():
        # await asyncio.gather(somax_server._run(), somax_server._gui_callback())
        await asyncio.gather(somax_server._run())


    asyncio.run(gather())
