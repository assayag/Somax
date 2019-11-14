import asyncio
import logging
import time

from somaxlibrary.Corpus import ContentType
from somaxlibrary.CorpusEvent import CorpusEvent, Note
from somaxlibrary.Exceptions import InvalidCorpus
from somaxlibrary.Player import Player
from somaxlibrary.scheduler.ScheduledEvent import ScheduledEvent, MidiEvent, AudioEvent, AutomaticTriggerEvent, \
    OscEvent, \
    TempoEvent, ManualTriggerEvent, AbstractTriggerEvent
from somaxlibrary.scheduler.ScheduledObject import TriggerMode


class Scheduler:
    DEFAULT_CALLBACK_INTERVAL: float = 0.001  # seconds
    TRIGGER_PRETIME: float = 0.1  # seconds

    def __init__(self, tempo: float = 120.0):
        self.logger = logging.getLogger(__name__)
        self._last_callback_time: float = time.time()
        self.tempo: float = tempo
        self.beat: float = 0.0
        self.running: bool = False
        self.queue: [ScheduledEvent] = []  # TODO: NO PREMATURE OPTIMIZATION PLEASE
        self.tempo_master: Player = None
        self.terminated = False

    async def init_async_loop(self, callback_interval: int = DEFAULT_CALLBACK_INTERVAL):
        self.logger.debug(f"Scheduler initialized with callback interval {callback_interval}.")
        while not self.terminated:
            await asyncio.sleep(callback_interval)
            self._callback()

    def terminate(self):
        self.terminated = True

    def start(self) -> None:
        self.logger.info(f"Scheduler Started. Current beat is {self.beat}.")
        self._last_callback_time = time.time()
        self.running = True

    def _callback(self):
        if self.running:
            self._update_time()
            self._process_internal_events()

    def _process_internal_events(self) -> None:
        events: [ScheduledEvent] = [e for e in self.queue if e.trigger_time <= self.beat]
        self.queue = [e for e in self.queue if e.trigger_time > self.beat]
        for event in events:
            # TODO: isinstance on all
            if type(event) == TempoEvent:
                self._process_tempo_event(event)
            if type(event) == MidiEvent:
                self._process_midi_event(event)
            elif type(event) == AudioEvent:
                self._process_audio_event(event)
            elif isinstance(event, AbstractTriggerEvent):
                self._process_trigger_event(event)
            elif type(event) == OscEvent:
                self._process_osc_event(event)

    def _process_tempo_event(self, tempo_event: TempoEvent) -> None:
        self.tempo = tempo_event.tempo

    def _process_midi_event(self, midi_event: MidiEvent) -> None:
        player: Player = midi_event.player
        player.target.send_midi([midi_event.note, midi_event.velocity, midi_event.channel])
        player.target.send_state(midi_event.state)

    def _process_audio_event(self, audio_event: AudioEvent) -> None:
        pass  # TODO

    def _process_trigger_event(self, trigger_event: AbstractTriggerEvent) -> None:
        player: Player = trigger_event.player
        try:
            # TODO: Critical bug here when event.duration is 0 (for example first event)
            # event: CorpusEvent = player.new_event(trigger_event.target_time)
            event: CorpusEvent = player.new_event(self.time)
        except InvalidCorpus as e:
            self.logger.error(str(e))
            return

        self.add_corpus_event(player, trigger_event.target_time, event)

        if isinstance(trigger_event, AutomaticTriggerEvent) and player.trigger_mode == TriggerMode.AUTOMATIC:
            next_trigger_time: float = trigger_event.trigger_time + event.duration
            next_target_time: float = trigger_event.target_time + event.duration
            self._add_automatic_trigger_event(player, next_trigger_time, next_target_time)

    def _process_osc_event(self, osc_event: OscEvent) -> None:
        pass

    def add_tempo_event(self, trigger_time: float, tempo: float):
        self.queue.append(TempoEvent(trigger_time, tempo))

    def add_osc_event(self):
        pass  # TODO

    def add_corpus_event(self, player: Player, trigger_time: float, corpus_event: CorpusEvent):
        self._update_time()
        if player is self.tempo_master:
            self.add_tempo_event(trigger_time, corpus_event.tempo)

        if player.corpus.content_type == ContentType.AUDIO:
            event: ScheduledEvent = AudioEvent(trigger_time, player, corpus_event.onset, corpus_event.duration, corpus_event.state_index)
            self.queue.append(event)
        elif player.corpus.content_type == ContentType.MIDI:
            # Handle held notes from previous state:
            note_offs_previous: [Note] = [n for n in player.held_notes if n not in corpus_event.held_to()]
            note_ons: [Note] = [n for n in corpus_event.notes if n not in player.held_notes]
            note_offs: [Note] = [n for n in corpus_event.notes if n not in corpus_event.held_from()]
            player.held_notes = corpus_event.held_from()

            # Queue midi events for note ons/offs
            for note in note_offs_previous:
                self.queue.append(MidiEvent(trigger_time, player, note.pitch, 0, note.channel, corpus_event.state_index))
            for note in note_ons:
                self.queue.append(MidiEvent(trigger_time + note.onset, player, note.pitch, note.velocity, note.channel, corpus_event.state_index))
            for note in note_offs:
                position_in_state: float = note.onset + note.duration
                self.queue.append(MidiEvent(trigger_time + position_in_state, player, note.pitch, 0, note.channel, corpus_event.state_index))

    def add_trigger_event(self, player: Player):
        if player.trigger_mode == TriggerMode.AUTOMATIC and not self._has_trigger(player):
            self._add_automatic_trigger_event(player, self.beat - self.TRIGGER_PRETIME * self.tempo / 60.0, self.beat)
        elif player.trigger_mode == TriggerMode.MANUAL:
            self._add_manual_trigger_event(player, self.beat)
        else:
            self.logger.debug("Could not add trigger.")

    def delete_trigger(self, player: Player):
        self.queue = [e for e in self.queue if not (isinstance(e, AutomaticTriggerEvent) and e.player == player)]

    def _has_trigger(self, player: Player) -> bool:  # TODO: Unoptimized approach
        for event in self.queue:
            try:
                if isinstance(event, AutomaticTriggerEvent) and event.player == player:
                    return True
            except AttributeError:
                continue
        return False

    def _add_automatic_trigger_event(self, player: Player, trigger_time: float, target_time: float):
        self.queue.append(AutomaticTriggerEvent(trigger_time, player, target_time))

    def _add_manual_trigger_event(self, player: Player, trigger_time: float):
        self.queue.append(ManualTriggerEvent(trigger_time, player))

    def _sanity_check(self):
        pass  # TODO

    def _update_time(self):
        if self.running:
            t: float = time.time()
            delta_time: float = t - self._last_callback_time
            self._last_callback_time = t
            self.beat += delta_time * self.tempo / 60.0

    @property
    def time(self) -> float:
        if self.running:
            self._update_time()
        return self.beat

    def pause(self) -> None:
        self.running = False

    def stop(self) -> None:
        self.running = False
        remamining_queue: [ScheduledEvent] = self.queue[:]
        self.queue = []
        self.beat = 0
        for event in remamining_queue[:]:
            # Add new triggers for all existing automatically triggered
            if isinstance(event, AutomaticTriggerEvent):
                self.add_trigger_event(event.player)
            if isinstance(event, MidiEvent) and event.velocity == 0:
                self._process_midi_event(event)
