"""A fresh control-plane interpreter must not load gateway cryptographic custody."""
import os
import subprocess
import sys


def test_control_import_does_not_import_vault_root_or_crypto():
    script = """
import sys
import app.workers.credential_channel
import app.api.credential_routes
import app.api.credential_wiring
import app.api.first_party_catalog
import app.server
for name in ('app.workers.credential_vault', 'app.workers.credential_root',
             'app.workers.credential_envelope', 'app.workers.credential_journal',
             'app.operations.credential_root_init', 'nacl.secret'):
    assert name not in sys.modules, name
print('control boundary clean')
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True,
        timeout=20, env=os.environ | {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false", "DD_TRACE_ENABLED": "false"})
    assert result.returncode == 0, result.stderr
    assert result.stdout == "control boundary clean\n"
