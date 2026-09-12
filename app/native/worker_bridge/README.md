# Superseded native worker-bridge experiment

This directory contains the pre-ADR-009 macOS launcher/XPC feasibility bridge. It is retained as
historical evidence and is not part of the current self-hosted web release boundary. Current
browser/document/model workers must be server-owned, isolated and mediated through the contracts
and deployment topology under `specs/001-autonomous-release/` and `deploy/`.

`app/native/speech_worker.cpp` is outside this directory and is not classified by this note;
compiled server-worker code is not itself a native desktop product surface.
