"""Generic camera policy. No cloud calls or installation-specific camera names."""

import math
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import atomic_json, clean_text


class Director:
    def __init__(self, data, sources, settings):
        self.path = data / "selection.json"
        self.settings = settings
        try:
            import json

            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = {}
        ids = [s["id"] for s in sources]
        self.active = (
            saved.get("camera_id")
            if saved.get("camera_id") in ids
            else (ids[0] if ids else None)
        )
        self.mode = saved.get("mode", "automatic")
        if self.mode not in ("automatic", "manual"):
            self.mode = "automatic"
        last = saved.get("last_switch")
        self.last_switch = (
            last
            if type(last) in (float, int)
            and math.isfinite(last)
            and last <= time.time()
            else time.time()
        )
        self.revision = uuid.uuid4().hex
        self.candidate = None
        self.confirmations = 0
        self.result = {}
        self.compared_at = None
        self.seen = []
        self.failures = 0
        self.status = "waiting"

    def reset(self):
        self.candidate = None
        self.confirmations = 0

    def persist(self):
        atomic_json(
            self.path,
            {
                "camera_id": self.active,
                "mode": self.mode,
                "last_switch": self.last_switch,
            },
        )

    def select(self, mode, camera_id=None, now=None):
        ids = {s["id"] for s in self.settings["sources"]}
        if mode not in ("automatic", "manual") or (
            camera_id is not None and camera_id not in ids
        ):
            raise ValueError("Unknown selection")
        if camera_id is not None and camera_id != self.active:
            self.active = camera_id
            self.last_switch = time.time() if now is None else now
        self.mode = mode
        self.status = "manual" if mode == "manual" else "waiting"
        self.revision = uuid.uuid4().hex
        self.failures = 0
        self.reset()
        self.persist()

    def active_time_preferences(self, now=None):
        timestamp = time.time() if now is None else now
        try:
            local = datetime.fromtimestamp(
                timestamp, ZoneInfo(self.settings.get("timezone", "UTC"))
            ).time()
        except (OverflowError, OSError, ValueError):
            local = datetime.fromtimestamp(timestamp, ZoneInfo("UTC")).time()
        active = []
        for period in ("morning", "evening"):
            camera = self.settings.get(f"{period}_camera", "")
            bonus = self.settings.get(f"{period}_bonus", 0)
            if not camera or bonus <= 0:
                continue
            start = datetime.strptime(
                self.settings[f"{period}_start"], "%H:%M"
            ).time()
            end = datetime.strptime(self.settings[f"{period}_end"], "%H:%M").time()
            in_window = (
                start <= local < end
                if start < end
                else local >= start or local < end
            )
            if in_window:
                active.append({"period": period, "camera_id": camera, "bonus": bonus})
        return active

    def time_bonuses(self, now=None):
        result = {}
        for preference in self.active_time_preferences(now):
            camera = preference["camera_id"]
            result[camera] = result.get(camera, 0) + preference["bonus"]
        return result

    def scores(self, now=None):
        timed = self.time_bonuses(now)
        return {c: v["score"] + timed.get(c, 0) for c, v in self.result.items()}

    def health_tick(self, healthy):
        if healthy.get(self.active):
            self.failures = 0
            return
        self.failures += 1
        self.reset()
        self.status = "no_video"
        if self.mode != "automatic" or self.failures < 2:
            return
        choices = [c for c, ok in healthy.items() if ok]
        if choices:
            scores = self.scores()
            best = max(choices, key=lambda c: scores.get(c, 0))
            self.select("automatic", best)
            self.status = "failover"

    def comparison(self, body, healthy, running, sources_revision, now=None):
        now = time.time() if now is None else now
        if not isinstance(body, dict) or set(body) != {
            "comparison_id",
            "observed_at",
            "sources_revision",
            "selection_revision",
            "scores",
        }:
            raise ValueError("Invalid comparison")
        if (
            body["sources_revision"] != sources_revision
            or body["selection_revision"] != self.revision
        ):
            raise ValueError("Selection changed during comparison")
        stamp = body["observed_at"]
        identity = body["comparison_id"]
        if (
            type(stamp) not in (int, float)
            or not math.isfinite(stamp)
            or not -5 <= now - stamp <= 180
        ):
            raise ValueError("Expired comparison")
        if (
            not isinstance(identity, str)
            or not 1 <= len(identity) <= 80
            or identity in self.seen
        ):
            raise ValueError("Duplicate comparison")
        ids = {s["id"] for s in self.settings["sources"]}
        result = body["scores"]
        if not isinstance(result, dict) or set(result) != ids:
            raise ValueError("Incomplete comparison")
        for value in result.values():
            if (
                not isinstance(value, dict)
                or set(value) != {"score", "usable", "reason"}
                or type(value["score"]) is not int
                or not 0 <= value["score"] <= 100
                or type(value["usable"]) is not bool
                or not isinstance(value["reason"], str)
            ):
                raise ValueError("Invalid camera score")
        self.result = {
            c: dict(v, reason=clean_text(v["reason"], 600)) for c, v in result.items()
        }
        self.compared_at = now
        self.seen = (self.seen + [identity])[-32:]
        if self.mode != "automatic" or not running:
            self.reset()
            self.status = "manual" if self.mode == "manual" else "idle"
            return
        # Never use an old cached snapshot as evidence of a healthy source.
        available = [c for c in ids if healthy.get(c, False)]
        if not available:
            self.reset()
            self.status = "no_video"
            return
        usable = [c for c in available if result[c]["usable"]]
        if not usable:
            self.reset()
            self.status = "no_detail"
            return
        scores = self.scores(now)
        best = max(usable, key=lambda c: scores[c])
        if (
            self.active in usable
            and scores[best] - scores[self.active] < self.settings["minimum_margin"]
        ):
            best = self.active
        if best == self.active:
            self.reset()
            self.status = "keep"
            return
        self.confirmations = self.confirmations + 1 if self.candidate == best else 1
        self.candidate = best
        self.confirmations = min(self.confirmations, self.settings["confirmations"])
        self.status = "candidate"
        if (
            self.confirmations >= self.settings["confirmations"]
            and now - self.last_switch >= self.settings["minimum_dwell"]
        ):
            self.select("automatic", best, now)
            self.status = "selected"

    def status_dict(self):
        return dict(
            mode=self.mode,
            camera_id=self.active,
            last_switch=self.last_switch,
            selection_revision=self.revision,
            candidate=self.candidate,
            confirmations=self.confirmations,
            comparison=self.result,
            compared_at=self.compared_at,
            effective_scores=self.scores(),
            active_time_preferences=self.active_time_preferences(),
            applied_time_bonuses=self.time_bonuses(),
            decision=self.status,
        )
