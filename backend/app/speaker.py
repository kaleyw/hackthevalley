"""Spoken announcements so bystanders near the camera can help.

Uses the Mac's built-in voice (`say`), so it plays through whatever the Mac's sound output
is set to: the laptop speakers, or a Bluetooth speaker like a JBL. On computers without
`say`, announcements are only logged.

The announcement names the location only, never describes the person or guesses why
they're down. It repeats until someone is with them, then stops: "Help is here" when a
responder taps "I'm here" (not when they just accept), or "Someone is with the person" when
the camera sees someone stay with them.
Several people down at the same location are announced together ("2 people near ..."),
and each one getting help is announced separately, with how many still need help. If the
person gets back up, bystanders are told (staff still check on them); if they go down
again, it's announced again right away.
"""

import asyncio
import logging
import os
import shutil

ENABLED = os.getenv("SPEAKER_ENABLED", "1") != "0"
REPEAT_SECONDS = int(os.getenv("SPEAKER_REPEAT_SECONDS", 20))
CHIME = "/System/Library/Sounds/Glass.aiff"
ACTIVE = {"open", "acknowledged", "on_scene"}
log = logging.getLogger("uvicorn.error")


def help_reached(event):
    return bool(event["arrived_at"] or event["help_detected_at"])


def needs_announcing(event):
    return (event["status"] in ACTIVE and not event["speaker_silenced"]
            and not help_reached(event) and not event["got_up_at"])


def help_message(location, group):
    who = "Someone" if len(group) == 1 else f"{len(group)} people"
    staff = ("Staff are on the way." if all(e["status"] == "acknowledged" for e in group)
             else "Staff have been notified.")
    return (f"Attention please. {who} near {location} may need help. "
            f"If you are nearby, please check on them. {staff}")


def still_waiting_note(location, still_waiting):
    if still_waiting == 1:
        return f" One more person near {location} still needs help."
    if still_waiting > 1:
        return f" {still_waiting} more people near {location} still need help."
    return ""


def staff_here_message(location, still_waiting):
    return (f"Help is here near {location}. Staff are with the person now, so there's no need "
            f"to worry. Thank you.{still_waiting_note(location, still_waiting)}")


def someone_with_them_message(location, still_waiting):
    return f"Thank you. Someone is with the person near {location} now.{still_waiting_note(location, still_waiting)}"


def got_up_message(location, still_waiting):
    return (f"Update: the person near {location} is now back on their feet. Staff will still "
            f"check on them.{still_waiting_note(location, still_waiting)}")


class Speaker:
    def __init__(self):
        self.lock = asyncio.Lock()       # one announcement at a time, never overlapping
        self.last_said: dict[str, float] = {}  # location -> loop time of its last announcement
        self.announced: set[int] = set()       # event IDs included in an announcement
        self.staff_here_said: set[int] = set()        # responder tapped "I'm here"
        self.someone_with_them_said: set[int] = set()  # camera saw someone stay with them
        self.got_up_said: set[int] = set()
        self.tasks: set[asyncio.Task] = set()

    def update(self, event, active_events):
        """Call whenever an event changes, and periodically: speaks if an announcement is due.

        active_events: all currently active events, so people down at the same location can
        be announced together.
        """
        now = asyncio.get_running_loop().time()
        eid, location = event["id"], event["location"]
        waiting = [e for e in active_events if e["location"] == location and needs_announcing(e)]
        if needs_announcing(event):
            if event not in waiting:
                waiting.append(event)
            last = self.last_said.get(location)
            # A new person down, or someone down again after getting up, is announced right away
            new_case = eid not in self.announced or eid in self.got_up_said
            self.got_up_said.discard(eid)
            if new_case or last is None or now - last >= REPEAT_SECONDS:
                self.last_said[location] = now
                self.announced.update(e["id"] for e in waiting)
                self._speak(help_message(location, waiting))
            return
        if eid not in self.announced or event["speaker_silenced"]:
            return
        others = len([e for e in waiting if e["id"] != eid])
        # "Help is here" only when a responder says they've arrived, never just for accepting
        if event["arrived_at"] and eid not in self.staff_here_said:
            self.staff_here_said.add(eid)
            self._speak(staff_here_message(location, others))
        elif (event["help_detected_at"] and not event["arrived_at"]
              and eid not in self.someone_with_them_said):
            self.someone_with_them_said.add(eid)
            self._speak(someone_with_them_message(location, others))
        elif (event["got_up_at"] and eid not in self.got_up_said
              and event["status"] in ACTIVE and not help_reached(event)):
            self.got_up_said.add(eid)
            self._speak(got_up_message(location, others))

    def _speak(self, text):
        # Run in the background so API requests never wait for the voice to finish
        task = asyncio.create_task(self._play(text))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _play(self, text):
        log.info("[speaker] %s", text)
        if not ENABLED or not shutil.which("say"):
            return
        async with self.lock:
            try:
                if os.path.exists(CHIME):
                    await (await asyncio.create_subprocess_exec("afplay", CHIME)).wait()
                await (await asyncio.create_subprocess_exec("say", text)).wait()
            except Exception:
                log.exception("[speaker] couldn't play announcement")


speaker = Speaker()
