"""Jarvis à la demande : il compte les demandes et s'arrête seul quand plus personne ne s'en sert."""

import time

from fastapi.testclient import TestClient

import main
import on_demand


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_idle_time_counts_from_the_last_request():
    clock = Clock()
    activity = on_demand.Activity(clock)
    clock.now += 600
    assert activity.idle_for() == 600

    # Une réponse en flux (une phrase après l'autre) occupe Jarvis jusqu'à sa fin.
    activity.begin()
    clock.now += 900
    assert activity.idle_for() == 0
    activity.end()
    clock.now += 30
    assert activity.idle_for() == 30


def test_when_jarvis_may_go_to_sleep():
    assert on_demand.should_sleep(20 * 60, 20, alarms_pending=False)
    assert not on_demand.should_sleep(19 * 60, 20, alarms_pending=False)
    # Une alarme en attente le garde éveillé : c'est lui qui doit la faire sonner.
    assert not on_demand.should_sleep(3 * 3600, 20, alarms_pending=True)
    # 0 minute : il ne s'arrête jamais de lui-même.
    assert not on_demand.should_sleep(10 * 3600, 0, alarms_pending=False)


def test_the_watcher_puts_jarvis_to_sleep(monkeypatch):
    slept = []
    clock = Clock()
    activity = on_demand.Activity(clock)
    clock.now += 3600
    thread = on_demand.watch_idle(activity, 20, lambda: False, lambda: slept.append(True), interval=0.01)
    thread.join(timeout=2)
    assert slept == [True]

    pending = []
    on_demand.watch_idle(activity, 20, lambda: True, lambda: pending.append(True), interval=0.01)
    time.sleep(0.1)
    assert pending == []  # alarme en attente : il reste allumé


def test_every_request_counts_as_activity(monkeypatch):
    monkeypatch.setattr(main.llm, "warm_up", lambda: None)
    monkeypatch.setattr(main.llm, "ollama_status", lambda: (True, "ok"))
    with TestClient(main.app, base_url="http://localhost") as client:
        main.activity.last = main.activity.clock() - 3600
        client.get("/api/status")
    assert main.activity.idle_for() < 5


def test_started_by_hand_there_is_no_launchd_socket():
    # Lancé à la main (ou pendant les tests), Jarvis ouvre son port lui-même et ne s'arrête jamais seul.
    assert on_demand.launchd_sockets() == []
