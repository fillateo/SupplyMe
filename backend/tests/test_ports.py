"""Every adapter really does satisfy the port it is bound to.

`app/ports/base.py` declares seven Protocols and says of them: "Every external
dependency is a Protocol here and an adapter in app/adapters/. Nothing above
this line knows which adapter is bound." That is structurally true — `Providers`
holds every adapter as `Any` and the workflow only ever calls methods — but it
is exactly what made the Protocols inert. Six of the seven were imported by
nothing, checked by nothing, and could have drifted from their adapters without
a single test noticing; only `Scheduler` was held to its signature, by
`tests/test_resilience.py`, and that test exists because a scheduler that
silently dropped a keyword argument would have failed only in the cloud, on the
first follow-up timer of the first real mission.

A Protocol nothing verifies is a comment with a class statement around it. This
is what makes the documented seam load-bearing: every adapter the product can
bind, and every double the suite can bind, is checked against the port it claims
to implement — the method must exist, and it must accept the same parameters
under the same names and kinds.

Signatures rather than `isinstance`: these Protocols are `runtime_checkable`,
which only ever checks that an attribute of the right name exists. A `send` that
had quietly lost `thread_id` would pass `isinstance` and break threading.
"""

from __future__ import annotations

import inspect

import pytest

from app.ports.base import (
    LLM,
    EventBus,
    MailProvider,
    MapsProvider,
    Scheduler,
    SearchProvider,
    Store,
)

# --------------------------------------------------------------------------
# Every binding the product or the suite can make, and the port it claims.
# --------------------------------------------------------------------------


def _adapters() -> list[tuple[type, type, str]]:
    """(protocol, implementation, label) for everything bindable.

    Imported inside the function so a missing optional Google dependency fails
    one parametrised case with a readable name rather than the whole module at
    collection time.
    """
    from app.adapters.firestore_store import FirestoreStore
    from app.adapters.gemini_llm import GeminiLLM
    from app.adapters.gmail_provider import GmailProvider
    from app.adapters.google_providers import GoogleSearchProvider, PlacesProvider
    from app.adapters.imap_mail import SmtpImapMailProvider
    from app.adapters.local_bus import LocalBus
    from app.adapters.mail_redirect import RedirectingMailProvider
    from app.adapters.memory_store import MemoryStore
    from app.adapters.pubsub_bus import PubSubBus
    from app.adapters.scheduler import CloudTasksScheduler, LocalScheduler
    from app.adapters.smtp_mail import SmtpMailProvider

    from .doubles_providers import MockMailProvider, MockMapsProvider, MockSearchProvider
    from .scripted_llm import ScriptedLLM

    return [
        # Search
        (SearchProvider, GoogleSearchProvider, "search/live"),
        (SearchProvider, MockSearchProvider, "search/double"),
        # Maps
        (MapsProvider, PlacesProvider, "maps/live"),
        (MapsProvider, MockMapsProvider, "maps/double"),
        # Mail — four real bindings plus the double. The redirect wrapper is in
        # this list deliberately: it is what stands between a live mission and a
        # stranger's inbox, and it is bound *in front of* whichever provider is
        # configured, so it has to satisfy the same port.
        (MailProvider, SmtpMailProvider, "mail/smtp"),
        (MailProvider, SmtpImapMailProvider, "mail/smtp+imap"),
        (MailProvider, GmailProvider, "mail/gmail"),
        (MailProvider, RedirectingMailProvider, "mail/redirect-wrapper"),
        (MailProvider, MockMailProvider, "mail/double"),
        # Store
        (Store, MemoryStore, "store/memory"),
        (Store, FirestoreStore, "store/firestore"),
        # Bus
        (EventBus, LocalBus, "bus/local"),
        (EventBus, PubSubBus, "bus/pubsub"),
        # Scheduler
        (Scheduler, LocalScheduler, "scheduler/local"),
        (Scheduler, CloudTasksScheduler, "scheduler/cloud-tasks"),
        # Model
        (LLM, GeminiLLM, "llm/gemini"),
        (LLM, ScriptedLLM, "llm/scripted"),
    ]


def _protocol_methods(protocol: type) -> list[str]:
    return [
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    ]


CASES = _adapters()


@pytest.mark.parametrize(
    ("protocol", "implementation"),
    [(p, i) for p, i, _ in CASES],
    ids=[label for _, _, label in CASES],
)
def test_the_adapter_implements_every_method_its_port_declares(protocol, implementation):
    declared = _protocol_methods(protocol)
    assert declared, f"{protocol.__name__} declares no methods, so it constrains nothing"
    missing = [name for name in declared if not callable(getattr(implementation, name, None))]
    assert not missing, (
        f"{implementation.__name__} is bound as {protocol.__name__} but has no {missing}"
    )


@pytest.mark.parametrize(
    ("protocol", "implementation"),
    [(p, i) for p, i, _ in CASES],
    ids=[label for _, _, label in CASES],
)
def test_the_adapter_accepts_the_arguments_its_port_promises(protocol, implementation):
    """Same parameter names, same kinds.

    A caller written against the port passes `limit=` or `compressible=` by
    keyword. An implementation that renamed one, or made it positional-only,
    type-checks nowhere and raises at the first call — in the cloud, on a real
    mission.
    """
    for name in _protocol_methods(protocol):
        expected = inspect.signature(getattr(protocol, name)).parameters
        actual = inspect.signature(getattr(implementation, name)).parameters

        for parameter, spec in expected.items():
            if parameter == "self":
                continue
            assert parameter in actual, (
                f"{implementation.__name__}.{name} is missing "
                f"{protocol.__name__}.{name}'s `{parameter}`"
            )
            assert actual[parameter].kind == spec.kind, (
                f"{implementation.__name__}.{name} takes `{parameter}` as "
                f"{actual[parameter].kind.description}, but {protocol.__name__} "
                f"promises {spec.kind.description}"
            )


def test_every_protocol_in_the_ports_module_has_at_least_one_adapter():
    """A port with no implementation is a drawing, not a seam."""
    from app.ports import base

    protocols = {
        obj.__name__
        for obj in vars(base).values()
        # `__module__` filters out `typing.Protocol` itself, which is imported
        # into this namespace and is not a port.
        if isinstance(obj, type)
        and getattr(obj, "_is_protocol", False)
        and obj.__module__ == base.__name__
    }
    covered = {p.__name__ for p, _, _ in CASES}
    assert protocols == covered, (
        f"ports declared but never bound to an adapter: {sorted(protocols - covered)}; "
        f"adapters checked against a port that no longer exists: {sorted(covered - protocols)}"
    )
